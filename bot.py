import os
import asyncio
import logging
import sqlite3
from contextlib import closing
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from TikTokLive import TikTokLiveClient
from yt_dlp import YoutubeDL

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
CHECK_INTERVAL = max(60, int(os.getenv("CHECK_INTERVAL", "120")))
DB_PATH = os.getenv("DB_PATH", "live_notifier.db")

# Server Discord owner/support yang wajib diikuti oleh owner server pengguna.
# Contoh:
# REQUIRED_GUILD_ID=123456789012345678
# REQUIRED_GUILD_INVITE=https://discord.gg/xxxxxx
REQUIRED_GUILD_ID = int(os.getenv("REQUIRED_GUILD_ID", "0") or 0)
REQUIRED_GUILD_INVITE = os.getenv("REQUIRED_GUILD_INVITE", "").strip()

OWNER_IDS = {
    int(x.strip())
    for x in os.getenv("OWNER_IDS", "").split(",")
    if x.strip().isdigit()
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("hi-notifku")

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

http: Optional[aiohttp.ClientSession] = None
_views_registered = False


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    ).fetchone()
    return row is not None


def table_columns(conn, table_name: str) -> set[str]:
    if not table_exists(conn, table_name):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def migrate_database():
    """
    Migrasi aman dari versi bot lama ke schema terbaru.

    Versi lama:
      guild_config(guild_id, channel_id, role_id)

    Versi baru:
      guild_config(guild_id, youtube_channel_id, tiktok_channel_id, mention_role_id)
    """
    with closing(db()) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        # ---------------- guild_config ----------------
        if table_exists(conn, "guild_config"):
            cols = table_columns(conn, "guild_config")

            new_cols = {
                "guild_id",
                "youtube_channel_id",
                "tiktok_channel_id",
                "mention_role_id"
            }

            if not new_cols.issubset(cols):
                log.info("Migrating legacy guild_config schema...")

                conn.execute("DROP TABLE IF EXISTS guild_config_new")
                conn.execute("""
                    CREATE TABLE guild_config_new (
                        guild_id INTEGER PRIMARY KEY,
                        youtube_channel_id INTEGER,
                        tiktok_channel_id INTEGER,
                        mention_role_id INTEGER
                    )
                """)

                # Ambil data legacy bila tersedia.
                select_parts = ["guild_id"]

                if "youtube_channel_id" in cols:
                    select_parts.append("youtube_channel_id")
                elif "channel_id" in cols:
                    select_parts.append("channel_id AS youtube_channel_id")
                else:
                    select_parts.append("NULL AS youtube_channel_id")

                if "tiktok_channel_id" in cols:
                    select_parts.append("tiktok_channel_id")
                elif "channel_id" in cols:
                    # Untuk data lama, channel lama juga dijadikan default TikTok.
                    select_parts.append("channel_id AS tiktok_channel_id")
                else:
                    select_parts.append("NULL AS tiktok_channel_id")

                if "mention_role_id" in cols:
                    select_parts.append("mention_role_id")
                elif "role_id" in cols:
                    select_parts.append("role_id AS mention_role_id")
                else:
                    select_parts.append("NULL AS mention_role_id")

                query = f"SELECT {', '.join(select_parts)} FROM guild_config"
                rows = conn.execute(query).fetchall()

                for row in rows:
                    conn.execute("""
                        INSERT OR REPLACE INTO guild_config_new(
                            guild_id,
                            youtube_channel_id,
                            tiktok_channel_id,
                            mention_role_id
                        )
                        VALUES(?,?,?,?)
                    """, (
                        row["guild_id"],
                        row["youtube_channel_id"],
                        row["tiktok_channel_id"],
                        row["mention_role_id"],
                    ))

                conn.execute("DROP TABLE guild_config")
                conn.execute("ALTER TABLE guild_config_new RENAME TO guild_config")

        else:
            conn.execute("""
                CREATE TABLE guild_config (
                    guild_id INTEGER PRIMARY KEY,
                    youtube_channel_id INTEGER,
                    tiktok_channel_id INTEGER,
                    mention_role_id INTEGER
                )
            """)

        # ---------------- hosts ----------------
        if not table_exists(conn, "hosts"):
            conn.execute("""
                CREATE TABLE hosts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    platform TEXT NOT NULL CHECK(platform IN ('youtube','tiktok')),
                    target TEXT NOT NULL,
                    display_name TEXT,
                    extra TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(guild_id, platform, target)
                )
            """)
        else:
            host_cols = table_columns(conn, "hosts")
            if "enabled" not in host_cols:
                conn.execute(
                    "ALTER TABLE hosts ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
                )

        # ---------------- live_state ----------------
        if not table_exists(conn, "live_state"):
            conn.execute("""
                CREATE TABLE live_state (
                    guild_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    target TEXT NOT NULL,
                    is_live INTEGER NOT NULL DEFAULT 0,
                    live_key TEXT,
                    PRIMARY KEY(guild_id, platform, target)
                )
            """)

        # ---------------- tiktok_post_state ----------------
        if not table_exists(conn, "tiktok_post_state"):
            conn.execute("""
                CREATE TABLE tiktok_post_state (
                    guild_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    last_post_id TEXT,
                    initialized INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(guild_id, username)
                )
            """)

        conn.commit()
        log.info("Database schema ready.")


def init_db():
    migrate_database()


def ensure_guild(guild_id: int):
    with closing(db()) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO guild_config(
                guild_id,
                youtube_channel_id,
                tiktok_channel_id,
                mention_role_id
            )
            VALUES(?, NULL, NULL, NULL)
        """, (guild_id,))
        conn.commit()


def get_config(guild_id: int):
    ensure_guild(guild_id)

    with closing(db()) as conn:
        row = conn.execute(
            "SELECT * FROM guild_config WHERE guild_id=?",
            (guild_id,)
        ).fetchone()

        # Safety fallback, jangan pernah return None.
        if row is None:
            conn.execute("""
                INSERT OR REPLACE INTO guild_config(
                    guild_id,
                    youtube_channel_id,
                    tiktok_channel_id,
                    mention_role_id
                )
                VALUES(?, NULL, NULL, NULL)
            """, (guild_id,))
            conn.commit()

            row = conn.execute(
                "SELECT * FROM guild_config WHERE guild_id=?",
                (guild_id,)
            ).fetchone()

        return row


def set_platform_channel(guild_id: int, platform: str, channel_id: int):
    ensure_guild(guild_id)

    column = (
        "youtube_channel_id"
        if platform == "youtube"
        else "tiktok_channel_id"
    )

    with closing(db()) as conn:
        conn.execute(
            f"UPDATE guild_config SET {column}=? WHERE guild_id=?",
            (channel_id, guild_id)
        )
        conn.commit()


def set_mention_role(guild_id: int, role_id: Optional[int]):
    ensure_guild(guild_id)

    with closing(db()) as conn:
        conn.execute(
            "UPDATE guild_config SET mention_role_id=? WHERE guild_id=?",
            (role_id, guild_id)
        )
        conn.commit()


def add_host(guild_id: int, platform: str, target: str, display_name=None, extra=None):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO hosts(
                guild_id,
                platform,
                target,
                display_name,
                extra,
                enabled
            )
            VALUES(?,?,?,?,?,1)
            ON CONFLICT(guild_id, platform, target)
            DO UPDATE SET
                display_name=excluded.display_name,
                extra=excluded.extra,
                enabled=1
        """, (
            guild_id,
            platform,
            target,
            display_name,
            extra
        ))

        conn.execute("""
            INSERT OR IGNORE INTO live_state(
                guild_id,
                platform,
                target,
                is_live,
                live_key
            )
            VALUES(?,?,?,0,NULL)
        """, (
            guild_id,
            platform,
            target
        ))

        conn.commit()


def update_host(host_id: int, target: str, display_name: Optional[str] = None):
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT * FROM hosts WHERE id=?",
            (host_id,)
        ).fetchone()

        if not row:
            return False

        old_target = row["target"]

        conn.execute("""
            UPDATE hosts
            SET target=?,
                display_name=COALESCE(?, display_name),
                extra=NULL
            WHERE id=?
        """, (
            target,
            display_name,
            host_id
        ))

        if old_target != target:
            conn.execute("""
                DELETE FROM live_state
                WHERE guild_id=? AND platform=? AND target=?
            """, (
                row["guild_id"],
                row["platform"],
                old_target
            ))

            conn.execute("""
                INSERT OR REPLACE INTO live_state(
                    guild_id,
                    platform,
                    target,
                    is_live,
                    live_key
                )
                VALUES(?,?,?,0,NULL)
            """, (
                row["guild_id"],
                row["platform"],
                target
            ))

            if row["platform"] == "tiktok":
                conn.execute("""
                    DELETE FROM tiktok_post_state
                    WHERE guild_id=? AND username=?
                """, (
                    row["guild_id"],
                    old_target.lstrip("@")
                ))

        conn.commit()
        return True


def delete_host(host_id: int):
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT * FROM hosts WHERE id=?",
            (host_id,)
        ).fetchone()

        if not row:
            return

        conn.execute(
            "DELETE FROM hosts WHERE id=?",
            (host_id,)
        )

        conn.execute("""
            DELETE FROM live_state
            WHERE guild_id=? AND platform=? AND target=?
        """, (
            row["guild_id"],
            row["platform"],
            row["target"]
        ))

        if row["platform"] == "tiktok":
            conn.execute("""
                DELETE FROM tiktok_post_state
                WHERE guild_id=? AND username=?
            """, (
                row["guild_id"],
                row["target"].lstrip("@")
            ))

        conn.commit()


def toggle_host(host_id: int):
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT * FROM hosts WHERE id=?",
            (host_id,)
        ).fetchone()

        if not row:
            return None

        enabled = 0 if row["enabled"] else 1

        conn.execute(
            "UPDATE hosts SET enabled=? WHERE id=?",
            (enabled, host_id)
        )

        conn.commit()
        return bool(enabled)


def get_host(host_id: int):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM hosts WHERE id=?",
            (host_id,)
        ).fetchone()


def get_hosts(guild_id: int):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT * FROM hosts
            WHERE guild_id=?
            ORDER BY platform, id
        """, (guild_id,)).fetchall()


def get_all_enabled_hosts():
    with closing(db()) as conn:
        return conn.execute("""
            SELECT * FROM hosts
            WHERE enabled=1
            ORDER BY guild_id, platform, id
        """).fetchall()


def get_state(guild_id: int, platform: str, target: str):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT * FROM live_state
            WHERE guild_id=? AND platform=? AND target=?
        """, (
            guild_id,
            platform,
            target
        )).fetchone()


def update_state(
    guild_id: int,
    platform: str,
    target: str,
    is_live: bool,
    live_key=None
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO live_state(
                guild_id,
                platform,
                target,
                is_live,
                live_key
            )
            VALUES(?,?,?,?,?)
            ON CONFLICT(guild_id, platform, target)
            DO UPDATE SET
                is_live=excluded.is_live,
                live_key=excluded.live_key
        """, (
            guild_id,
            platform,
            target,
            int(is_live),
            live_key
        ))

        conn.commit()



def get_tiktok_post_state(guild_id: int, username: str):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT * FROM tiktok_post_state
            WHERE guild_id=? AND username=?
        """, (
            guild_id,
            username
        )).fetchone()


def update_tiktok_post_state(
    guild_id: int,
    username: str,
    last_post_id: Optional[str],
    initialized: bool = True
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO tiktok_post_state(
                guild_id,
                username,
                last_post_id,
                initialized
            )
            VALUES(?,?,?,?)
            ON CONFLICT(guild_id, username)
            DO UPDATE SET
                last_post_id=excluded.last_post_id,
                initialized=excluded.initialized
        """, (
            guild_id,
            username,
            last_post_id,
            int(initialized)
        ))
        conn.commit()



# ============================================================
# REQUIRED OWNER/SUPPORT SERVER MEMBERSHIP
# ============================================================

async def is_user_in_required_guild(user_id: int) -> bool:
    """
    True bila user merupakan member server owner/support.
    Jika REQUIRED_GUILD_ID=0, fitur gate dinonaktifkan.
    """
    if not REQUIRED_GUILD_ID:
        return True

    required_guild = bot.get_guild(REQUIRED_GUILD_ID)

    if required_guild is None:
        log.error(
            "REQUIRED_GUILD_ID=%s tetapi bot tidak berada di server tersebut.",
            REQUIRED_GUILD_ID
        )
        return False

    member = required_guild.get_member(user_id)

    if member is not None:
        return True

    try:
        member = await required_guild.fetch_member(user_id)
        return member is not None
    except discord.NotFound:
        return False
    except discord.Forbidden:
        log.error(
            "Tidak dapat fetch member di required guild. "
            "Aktifkan Server Members Intent dan pastikan bot berada di server owner."
        )
        return False
    except discord.HTTPException as exc:
        log.warning(
            "Gagal cek membership user_id=%s: %s",
            user_id,
            exc
        )
        return False


async def is_guild_owner_verified(guild: discord.Guild) -> bool:
    return await is_user_in_required_guild(guild.owner_id)


def required_join_text() -> str:
    if REQUIRED_GUILD_INVITE:
        return (
            "🔒 **Akses Hi Notifku terkunci**\\n"
            "Owner server ini wajib bergabung ke server Discord Owner/Support terlebih dahulu.\\n\\n"
            f"➡️ Join: {REQUIRED_GUILD_INVITE}\\n\\n"
            "Setelah join, coba lagi menu/command."
        )

    return (
        "🔒 **Akses Hi Notifku terkunci**\\n"
        "Owner server ini wajib bergabung ke server Discord Owner/Support terlebih dahulu.\\n"
        "Link invite support belum dikonfigurasi oleh pemilik bot."
    )


async def require_guild_owner_membership(
    interaction: discord.Interaction
) -> bool:
    """
    Gate fitur server.
    Global bot owner selalu boleh mengakses.
    """
    if is_global_owner_user(interaction.user.id):
        return True

    guild = interaction.guild

    if guild is None:
        return True

    verified = await is_guild_owner_verified(guild)

    if verified:
        return True

    message = required_join_text()

    if interaction.response.is_done():
        await interaction.followup.send(
            message,
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            message,
            ephemeral=True
        )

    return False


async def send_required_join_notice(guild: discord.Guild):
    """
    Kirim notice ketika bot baru masuk server tetapi owner server belum join support.
    """
    if not REQUIRED_GUILD_ID:
        return

    if await is_guild_owner_verified(guild):
        return

    channel = guild.system_channel

    if channel is None:
        # Cari text channel pertama yang bisa ditulis bot
        me = guild.me
        for candidate in guild.text_channels:
            if me is None:
                continue
            perms = candidate.permissions_for(me)
            if perms.view_channel and perms.send_messages:
                channel = candidate
                break

    if channel is None:
        return

    try:
        embed = discord.Embed(
            title="🔒 Hi Notifku • Verifikasi Wajib",
            description=required_join_text(),
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Owner Server",
            value=f"<@{guild.owner_id}>",
            inline=False
        )
        embed.set_footer(
            text="Setelah owner server join Discord support, fitur akan terbuka otomatis."
        )

        await channel.send(
            content=f"<@{guild.owner_id}>",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True)
        )
    except Exception:
        log.exception(
            "Gagal mengirim required join notice ke guild %s",
            guild.id
        )


# ============================================================
# PERMISSION
# ============================================================

def is_owner_or_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.id in OWNER_IDS:
        return True

    if not interaction.guild:
        return False

    if not isinstance(interaction.user, discord.Member):
        return False

    perms = interaction.user.guild_permissions

    return (
        perms.administrator
        or perms.manage_guild
    )


async def require_owner_or_admin(interaction: discord.Interaction) -> bool:
    if not is_owner_or_admin(interaction):
        message = "❌ Menu ini hanya dapat digunakan oleh **Owner/Admin**."

        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True
            )

        return False

    # Global bot owner bypass gate.
    if is_global_owner_user(interaction.user.id):
        return True

    # Untuk command/menu di server, owner server wajib join support server.
    if not await require_guild_owner_membership(interaction):
        return False

    return True


# ============================================================
# API HELPERS
# ============================================================

async def yt_api(endpoint: str, params: dict):
    if not YOUTUBE_API_KEY:
        raise RuntimeError(
            "YOUTUBE_API_KEY belum diisi di Railway Variables."
        )

    if http is None or http.closed:
        raise RuntimeError("HTTP session belum siap.")

    params = dict(params)
    params["key"] = YOUTUBE_API_KEY

    url = f"https://www.googleapis.com/youtube/v3/{endpoint}"

    async with http.get(
        url,
        params=params,
        timeout=aiohttp.ClientTimeout(total=20)
    ) as response:

        data = await response.json()

        if response.status != 200:
            raise RuntimeError(
                data.get("error", {}).get(
                    "message",
                    f"YouTube API HTTP {response.status}"
                )
            )

        return data


async def resolve_youtube_channel(channel_id: str):
    channel_id = channel_id.strip()

    if not channel_id:
        raise ValueError("Channel ID YouTube kosong.")

    data = await yt_api(
        "channels",
        {
            "part": "snippet,contentDetails",
            "id": channel_id
        }
    )

    items = data.get("items", [])

    if not items:
        raise ValueError(
            "Channel ID YouTube tidak ditemukan."
        )

    item = items[0]

    return (
        item["snippet"]["title"],
        item["contentDetails"]["relatedPlaylists"]["uploads"]
    )


async def resolve_discord_channel(channel_id: Optional[int]):
    if not channel_id:
        return None

    channel = bot.get_channel(channel_id)

    if channel:
        return channel

    try:
        return await bot.fetch_channel(channel_id)
    except Exception as exc:
        log.warning(
            "Tidak dapat mengakses Discord channel %s: %s",
            channel_id,
            exc
        )
        return None


async def send_live_notification(
    guild_id: int,
    platform: str,
    creator: str,
    title: str,
    url: str,
    thumbnail: Optional[str] = None,
):
    config = get_config(guild_id)

    if not config:
        log.error(
            "Guild config tidak tersedia untuk guild %s",
            guild_id
        )
        return False

    channel_id = (
        config["youtube_channel_id"]
        if platform == "youtube"
        else config["tiktok_channel_id"]
    )

    channel = await resolve_discord_channel(channel_id)

    if not channel:
        return False

    content = None
    allowed_mentions = discord.AllowedMentions.none()

    role_id = config["mention_role_id"]

    if role_id:
        content = f"<@&{role_id}>"
        allowed_mentions = discord.AllowedMentions(roles=True)

    if platform == "youtube":
        embed = discord.Embed(
            title="🔴 YouTube LIVE STREAM",
            description=f"**{creator}** sedang live sekarang!",
            url=url,
            color=discord.Color.red()
        )

        embed.add_field(
            name="Judul Live",
            value=(title or "Live sekarang")[:1024],
            inline=False
        )

        embed.add_field(
            name="Tonton",
            value=f"[Buka YouTube Live]({url})",
            inline=False
        )

    else:
        embed = discord.Embed(
            title="🔴 TikTok LIVE",
            description=f"**@{creator}** sedang LIVE di TikTok!",
            url=url,
            color=discord.Color.from_rgb(0, 170, 255)
        )

        embed.add_field(
            name="Tonton",
            value=f"[Buka TikTok Live]({url})",
            inline=False
        )

    if thumbnail:
        embed.set_image(url=thumbnail)

    embed.set_footer(
        text="Hi Notifku • Automatic Live Notification"
    )

    try:
        await channel.send(
            content=content,
            embed=embed,
            allowed_mentions=allowed_mentions
        )
        return True

    except discord.Forbidden:
        log.error(
            "Bot tidak punya permission kirim pesan ke channel %s",
            channel_id
        )
        return False

    except discord.HTTPException as exc:
        log.error(
            "Discord HTTP error saat kirim notif: %s",
            exc
        )
        return False



async def send_tiktok_post_notification(
    guild_id: int,
    username: str,
    post_id: str,
    post_url: str,
    description: str = "",
    thumbnail: Optional[str] = None,
):
    config = get_config(guild_id)

    if not config:
        return False

    channel_id = config["tiktok_channel_id"]
    channel = await resolve_discord_channel(channel_id)

    if not channel:
        return False

    content = None
    allowed_mentions = discord.AllowedMentions.none()

    role_id = config["mention_role_id"]
    if role_id:
        content = f"<@&{role_id}>"
        allowed_mentions = discord.AllowedMentions(roles=True)

    clean_description = (description or "").strip()
    if len(clean_description) > 700:
        clean_description = clean_description[:697] + "..."

    embed = discord.Embed(
        title="🆕 TikTok Post Baru",
        description=(
            f"**@{username}** baru saja mengunggah postingan baru."
            + (f"\\n\\n{clean_description}" if clean_description else "")
        ),
        url=post_url,
        color=discord.Color.from_rgb(0, 170, 255)
    )

    embed.add_field(
        name="Lihat Postingan",
        value=f"[Buka di TikTok]({post_url})",
        inline=False
    )

    embed.add_field(
        name="Post ID",
        value=f"`{post_id}`",
        inline=False
    )

    if thumbnail:
        embed.set_image(url=thumbnail)

    embed.set_footer(
        text="Hi Notifku • TikTok New Post"
    )

    try:
        await channel.send(
            content=content,
            embed=embed,
            allowed_mentions=allowed_mentions
        )
        return True

    except discord.Forbidden:
        log.error(
            "Bot tidak punya permission kirim TikTok post ke channel %s",
            channel_id
        )
        return False

    except discord.HTTPException as exc:
        log.error(
            "Discord HTTP error saat kirim TikTok post: %s",
            exc
        )
        return False


def _extract_latest_tiktok_post_sync(username: str):
    """
    Ambil post TikTok terbaru via yt-dlp.
    Tidak butuh API key, tetapi bergantung pada akses publik TikTok.
    """
    profile_url = f"https://www.tiktok.com/@{username}"

    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": 3,
        "skip_download": True,
        "ignoreerrors": True,
        "socket_timeout": 20,
    }

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(
            profile_url,
            download=False
        )

    if not info:
        return None

    entries = info.get("entries") or []

    for entry in entries:
        if not entry:
            continue

        post_id = str(
            entry.get("id")
            or entry.get("display_id")
            or ""
        ).strip()

        if not post_id:
            continue

        url = (
            entry.get("webpage_url")
            or entry.get("url")
            or f"https://www.tiktok.com/@{username}/video/{post_id}"
        )

        # yt-dlp extract_flat bisa memberi URL bukan webpage URL.
        if isinstance(url, str) and not url.startswith("http"):
            url = f"https://www.tiktok.com/@{username}/video/{post_id}"

        title = (
            entry.get("title")
            or entry.get("description")
            or ""
        )

        thumbnail = entry.get("thumbnail")

        return {
            "id": post_id,
            "url": url,
            "description": title,
            "thumbnail": thumbnail,
        }

    return None


async def get_latest_tiktok_post(username: str):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _extract_latest_tiktok_post_sync,
                username
            ),
            timeout=35
        )
    except asyncio.TimeoutError:
        raise RuntimeError(
            f"Timeout saat cek postingan TikTok @{username}"
        )


async def check_tiktok_new_post(row):
    username = row["target"].strip().lstrip("@")
    guild_id = row["guild_id"]

    latest = await get_latest_tiktok_post(username)

    if not latest:
        log.warning(
            "Tidak menemukan posting TikTok terbaru untuk @%s",
            username
        )
        return

    state = get_tiktok_post_state(
        guild_id,
        username
    )

    latest_id = latest["id"]

    # First run = bootstrap saja. Jangan kirim post lama sebagai notifikasi baru.
    if not state or not state["initialized"]:
        update_tiktok_post_state(
            guild_id,
            username,
            latest_id,
            True
        )
        log.info(
            "TikTok post baseline @%s = %s",
            username,
            latest_id
        )
        return

    previous_id = state["last_post_id"]

    if latest_id != previous_id:
        sent = await send_tiktok_post_notification(
            guild_id=guild_id,
            username=username,
            post_id=latest_id,
            post_url=latest["url"],
            description=latest.get("description", ""),
            thumbnail=latest.get("thumbnail")
        )

        # Tetap update state meskipun channel belum diset agar tidak spam post lama berulang.
        update_tiktok_post_state(
            guild_id,
            username,
            latest_id,
            True
        )

        log.info(
            "TikTok new post @%s: %s sent=%s",
            username,
            latest_id,
            sent
        )


# ============================================================
# LIVE CHECKER
# ============================================================

async def check_youtube_host(row):
    guild_id = row["guild_id"]
    channel_id = row["target"]
    name = row["display_name"] or channel_id
    uploads = row["extra"]

    if not uploads:
        name, uploads = await resolve_youtube_channel(channel_id)

        with closing(db()) as conn:
            conn.execute("""
                UPDATE hosts
                SET display_name=?, extra=?
                WHERE id=?
            """, (
                name,
                uploads,
                row["id"]
            ))
            conn.commit()

    playlist = await yt_api(
        "playlistItems",
        {
            "part": "contentDetails",
            "playlistId": uploads,
            "maxResults": 8
        }
    )

    video_ids = [
        item.get("contentDetails", {}).get("videoId")
        for item in playlist.get("items", [])
        if item.get("contentDetails", {}).get("videoId")
    ]

    if not video_ids:
        update_state(
            guild_id,
            "youtube",
            channel_id,
            False,
            None
        )
        return

    videos = await yt_api(
        "videos",
        {
            "part": "snippet,liveStreamingDetails",
            "id": ",".join(video_ids)
        }
    )

    live_video = next(
        (
            item
            for item in videos.get("items", [])
            if item.get("snippet", {}).get(
                "liveBroadcastContent"
            ) == "live"
        ),
        None
    )

    previous = get_state(
        guild_id,
        "youtube",
        channel_id
    )

    if not live_video:
        update_state(
            guild_id,
            "youtube",
            channel_id,
            False,
            None
        )
        return

    video_id = live_video["id"]
    snippet = live_video["snippet"]

    is_same_live = (
        previous
        and previous["is_live"]
        and previous["live_key"] == video_id
    )

    if not is_same_live:
        thumbnails = snippet.get(
            "thumbnails",
            {}
        )

        thumbnail = (
            thumbnails.get("maxres", {})
            or thumbnails.get("standard", {})
            or thumbnails.get("high", {})
            or thumbnails.get("medium", {})
        ).get("url")

        await send_live_notification(
            guild_id=guild_id,
            platform="youtube",
            creator=snippet.get(
                "channelTitle",
                name
            ),
            title=snippet.get(
                "title",
                "Live sekarang"
            ),
            url=f"https://www.youtube.com/watch?v={video_id}",
            thumbnail=thumbnail
        )

    update_state(
        guild_id,
        "youtube",
        channel_id,
        True,
        video_id
    )


async def check_tiktok_host(row):
    username = row["target"].strip().lstrip("@")

    previous = get_state(
        row["guild_id"],
        "tiktok",
        username
    )

    client = TikTokLiveClient(
        unique_id=f"@{username}"
    )

    try:
        is_live = await asyncio.wait_for(
            client.is_live(),
            timeout=25
        )

    except asyncio.TimeoutError:
        raise RuntimeError(
            f"Timeout saat cek TikTok @{username}"
        )

    if is_live:
        if not previous or not previous["is_live"]:
            await send_live_notification(
                guild_id=row["guild_id"],
                platform="tiktok",
                creator=username,
                title="Live sekarang",
                url=f"https://www.tiktok.com/@{username}/live"
            )

        update_state(
            row["guild_id"],
            "tiktok",
            username,
            True,
            username
        )

    else:
        update_state(
            row["guild_id"],
            "tiktok",
            username,
            False,
            None
        )


@tasks.loop(seconds=CHECK_INTERVAL)
async def live_checker():
    rows = get_all_enabled_hosts()

    for row in rows:
        try:
            if row["platform"] == "youtube":
                await check_youtube_host(row)

            elif row["platform"] == "tiktok":
                await check_tiktok_host(row)

                try:
                    await check_tiktok_new_post(row)
                except Exception:
                    log.exception(
                        "Gagal cek postingan baru TikTok @%s",
                        row["target"]
                    )

        except Exception:
            log.exception(
                "Gagal cek host %s:%s",
                row["platform"],
                row["target"]
            )

        await asyncio.sleep(1)


@live_checker.before_loop
async def before_live_checker():
    await bot.wait_until_ready()


# ============================================================
# EMBEDS
# ============================================================

def dashboard_embed(guild_id: int):
    cfg = get_config(guild_id)

    if not cfg:
        raise RuntimeError(
            "Konfigurasi server gagal dibuat."
        )

    hosts = get_hosts(guild_id)

    youtube_count = sum(
        1
        for host in hosts
        if host["platform"] == "youtube"
    )

    tiktok_count = sum(
        1
        for host in hosts
        if host["platform"] == "tiktok"
    )

    running_count = sum(
        1
        for host in hosts
        if host["enabled"]
    )

    embed = discord.Embed(
        title="🔔 Hi Notifku",
        description=(
            "Kelola **host** dan **channel notifikasi** di sini. "
            "Tombol test tersedia di panel masing-masing host."
        ),
        color=discord.Color.blue()
    )

    embed.add_field(
        name="📺 YouTube Hosts",
        value=str(youtube_count),
        inline=True
    )

    embed.add_field(
        name="🎵 TikTok Hosts",
        value=str(tiktok_count),
        inline=True
    )

    embed.add_field(
        name="🟢 Running",
        value=str(running_count),
        inline=True
    )

    youtube_channel = (
        f"<#{cfg['youtube_channel_id']}>"
        if cfg["youtube_channel_id"]
        else "Belum diatur"
    )

    tiktok_channel = (
        f"<#{cfg['tiktok_channel_id']}>"
        if cfg["tiktok_channel_id"]
        else "Belum diatur"
    )

    mention_role = (
        f"<@&{cfg['mention_role_id']}>"
        if cfg["mention_role_id"]
        else "Tidak ada"
    )

    embed.add_field(
        name="📺 Channel YouTube",
        value=youtube_channel,
        inline=False
    )

    embed.add_field(
        name="🎵 Channel TikTok",
        value=tiktok_channel,
        inline=False
    )

    embed.add_field(
        name="🔔 Mention Role",
        value=mention_role,
        inline=False
    )

    embed.set_footer(
        text="Owner/Admin Panel • Hi Notifku"
    )

    return embed


def host_embed(row):
    platform = (
        "YouTube"
        if row["platform"] == "youtube"
        else "TikTok"
    )

    icon = (
        "📺"
        if row["platform"] == "youtube"
        else "🎵"
    )

    status = (
        "🟢 Running"
        if row["enabled"]
        else "🔴 Paused"
    )

    embed = discord.Embed(
        title=f"{icon} {platform} Host",
        color=discord.Color.dark_theme()
    )

    embed.add_field(
        name="Account Name",
        value=row["display_name"] or row["target"],
        inline=False
    )

    embed.add_field(
        name="Target",
        value=f"`{row['target']}`",
        inline=False
    )

    embed.add_field(
        name="Status",
        value=status,
        inline=False
    )

    embed.set_footer(
        text=f"Host ID: {row['id']}"
    )

    return embed


# ============================================================
# MODALS
# ============================================================

class AddHostModal(discord.ui.Modal):
    platform = discord.ui.TextInput(
        label="Platform",
        placeholder="tiktok atau youtube",
        max_length=10
    )

    target = discord.ui.TextInput(
        label="Username / YouTube Channel ID",
        placeholder="TikTok: username | YouTube: UCxxxxxxxx",
        max_length=120
    )

    def __init__(self):
        super().__init__(
            title="Tambah Host",
            timeout=300
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        if not await require_owner_or_admin(interaction):
            return

        platform = self.platform.value.strip().lower()
        target = self.target.value.strip()

        if platform not in ("tiktok", "youtube"):
            await interaction.response.send_message(
                "❌ Platform harus `tiktok` atau `youtube`.",
                ephemeral=True
            )
            return

        if not target:
            await interaction.response.send_message(
                "❌ Target tidak boleh kosong.",
                ephemeral=True
            )
            return

        if platform == "tiktok":
            username = (
                target
                .replace("https://www.tiktok.com/@", "")
                .replace("https://tiktok.com/@", "")
                .split("/")[0]
                .lstrip("@")
                .strip()
            )

            if not username:
                await interaction.response.send_message(
                    "❌ Username TikTok tidak valid.",
                    ephemeral=True
                )
                return

            add_host(
                interaction.guild_id,
                "tiktok",
                username,
                f"@{username}",
                None
            )

            await interaction.response.send_message(
                f"✅ TikTok **@{username}** berhasil ditambahkan.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            name, uploads = await resolve_youtube_channel(target)

            add_host(
                interaction.guild_id,
                "youtube",
                target,
                name,
                uploads
            )

            await interaction.followup.send(
                f"✅ YouTube **{name}** berhasil ditambahkan.",
                ephemeral=True
            )

        except Exception as exc:
            log.exception(
                "Gagal tambah YouTube host"
            )

            await interaction.followup.send(
                f"❌ Gagal menambahkan YouTube: `{exc}`",
                ephemeral=True
            )


class EditHostModal(discord.ui.Modal):
    target_input = discord.ui.TextInput(
        label="Target Baru",
        placeholder="Username TikTok / Channel ID YouTube",
        max_length=120
    )

    def __init__(self, host_id: int):
        super().__init__(
            title="Edit Host",
            timeout=300
        )

        self.host_id = host_id
        row = get_host(host_id)

        if row:
            self.target_input.default = row["target"]

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        if not await require_owner_or_admin(interaction):
            return

        row = get_host(self.host_id)

        if not row:
            await interaction.response.send_message(
                "❌ Host tidak ditemukan.",
                ephemeral=True
            )
            return

        target = self.target_input.value.strip()

        if row["platform"] == "tiktok":
            username = (
                target
                .replace("https://www.tiktok.com/@", "")
                .replace("https://tiktok.com/@", "")
                .split("/")[0]
                .lstrip("@")
                .strip()
            )

            update_host(
                self.host_id,
                username,
                f"@{username}"
            )

            await interaction.response.send_message(
                f"✅ Host diubah menjadi **@{username}**.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            name, uploads = await resolve_youtube_channel(target)

            update_host(
                self.host_id,
                target,
                name
            )

            with closing(db()) as conn:
                conn.execute(
                    "UPDATE hosts SET extra=? WHERE id=?",
                    (
                        uploads,
                        self.host_id
                    )
                )
                conn.commit()

            await interaction.followup.send(
                f"✅ Host YouTube diubah menjadi **{name}**.",
                ephemeral=True
            )

        except Exception as exc:
            await interaction.followup.send(
                f"❌ Gagal edit YouTube: `{exc}`",
                ephemeral=True
            )


# ============================================================
# CONFIG VIEW
# ============================================================

class ChannelSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Pilih channel YouTube Live...",
        min_values=1,
        max_values=1,
        row=0
    )
    async def youtube_channel(
        self,
        interaction: discord.Interaction,
        select: discord.ui.ChannelSelect
    ):
        if not await require_owner_or_admin(interaction):
            return

        channel = select.values[0]

        set_platform_channel(
            interaction.guild_id,
            "youtube",
            channel.id
        )

        await interaction.response.send_message(
            f"✅ Channel YouTube diatur ke {channel.mention}.",
            ephemeral=True
        )

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Pilih channel TikTok Live...",
        min_values=1,
        max_values=1,
        row=1
    )
    async def tiktok_channel(
        self,
        interaction: discord.Interaction,
        select: discord.ui.ChannelSelect
    ):
        if not await require_owner_or_admin(interaction):
            return

        channel = select.values[0]

        set_platform_channel(
            interaction.guild_id,
            "tiktok",
            channel.id
        )

        await interaction.response.send_message(
            f"✅ Channel TikTok diatur ke {channel.mention}.",
            ephemeral=True
        )

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Pilih role notifikasi...",
        min_values=1,
        max_values=1,
        row=2
    )
    async def role_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.RoleSelect
    ):
        if not await require_owner_or_admin(interaction):
            return

        role = select.values[0]

        set_mention_role(
            interaction.guild_id,
            role.id
        )

        await interaction.response.send_message(
            f"✅ Mention role diatur ke {role.mention}.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Matikan Mention Role",
        emoji="🔕",
        style=discord.ButtonStyle.secondary,
        row=3
    )
    async def disable_role(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await require_owner_or_admin(interaction):
            return

        set_mention_role(
            interaction.guild_id,
            None
        )

        await interaction.response.send_message(
            "✅ Mention role dimatikan.",
            ephemeral=True
        )


# ============================================================
# HOST CARD VIEW
# ============================================================

class HostCardView(discord.ui.View):
    def __init__(self, host_id: int):
        super().__init__(
            timeout=600
        )

        self.host_id = host_id

    @discord.ui.button(
        label="Edit",
        emoji="✏️",
        style=discord.ButtonStyle.secondary
    )
    async def edit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await require_owner_or_admin(interaction):
            return

        await interaction.response.send_modal(
            EditHostModal(self.host_id)
        )

    @discord.ui.button(
        label="Notif",
        emoji="📣",
        style=discord.ButtonStyle.primary
    )
    async def notification_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await require_owner_or_admin(interaction):
            return

        row = get_host(self.host_id)

        if not row:
            await interaction.response.send_message(
                "❌ Host tidak ditemukan.",
                ephemeral=True
            )
            return

        cfg = get_config(interaction.guild_id)

        channel_id = (
            cfg["youtube_channel_id"]
            if row["platform"] == "youtube"
            else cfg["tiktok_channel_id"]
        )

        channel_text = (
            f"<#{channel_id}>"
            if channel_id
            else "Belum diatur"
        )

        await interaction.response.send_message(
            f"📣 Channel notifikasi host ini: {channel_text}",
            ephemeral=True
        )

    @discord.ui.button(
        label="Test",
        emoji="🧪",
        style=discord.ButtonStyle.success
    )
    async def test_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await require_owner_or_admin(interaction):
            return

        row = get_host(self.host_id)

        if not row:
            await interaction.response.send_message(
                "❌ Host tidak ditemukan.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        if row["platform"] == "youtube":
            ok = await send_live_notification(
                interaction.guild_id,
                "youtube",
                row["display_name"] or row["target"],
                "Test YouTube Live Stream",
                "https://www.youtube.com/"
            )

        else:
            ok = await send_live_notification(
                interaction.guild_id,
                "tiktok",
                row["target"],
                "Test TikTok LIVE",
                f"https://www.tiktok.com/@{row['target']}/live"
            )

        await interaction.followup.send(
            (
                "✅ Test notifikasi berhasil dikirim."
                if ok
                else
                "❌ Channel notifikasi belum diatur atau bot tidak punya permission."
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="Pause / Resume",
        emoji="⏯️",
        style=discord.ButtonStyle.secondary
    )
    async def pause_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await require_owner_or_admin(interaction):
            return

        enabled = toggle_host(self.host_id)
        row = get_host(self.host_id)

        if enabled is None or row is None:
            await interaction.response.send_message(
                "❌ Host tidak ditemukan.",
                ephemeral=True
            )
            return

        try:
            await interaction.message.edit(
                embed=host_embed(row),
                view=HostCardView(self.host_id)
            )
        except Exception:
            log.exception(
                "Gagal refresh host card"
            )

        await interaction.response.send_message(
            (
                "✅ Host sekarang **Running**."
                if enabled
                else
                "⏸️ Host sekarang **Paused**."
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="Hapus",
        emoji="🗑️",
        style=discord.ButtonStyle.danger
    )
    async def delete_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await require_owner_or_admin(interaction):
            return

        row = get_host(self.host_id)

        if not row:
            await interaction.response.send_message(
                "❌ Host sudah tidak ditemukan.",
                ephemeral=True
            )
            return

        delete_host(self.host_id)

        await interaction.response.send_message(
            "🗑️ Host berhasil dihapus.",
            ephemeral=True
        )

        try:
            await interaction.message.delete()
        except Exception:
            pass


# ============================================================
# MAIN DASHBOARD VIEW
# ============================================================

class DashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Tambah Host",
        emoji="➕",
        style=discord.ButtonStyle.success,
        custom_id="hi_notifku:add_host",
        row=0
    )
    async def add_host_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await require_owner_or_admin(interaction):
            return

        await interaction.response.send_modal(
            AddHostModal()
        )

    @discord.ui.button(
        label="Daftar Host",
        emoji="📋",
        style=discord.ButtonStyle.primary,
        custom_id="hi_notifku:list_hosts",
        row=0
    )
    async def list_hosts_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await require_owner_or_admin(interaction):
            return

        rows = get_hosts(interaction.guild_id)

        if not rows:
            await interaction.response.send_message(
                "Belum ada host. Tekan **➕ Tambah Host**.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"📋 Menampilkan **{len(rows)} host**.",
            ephemeral=True
        )

        for row in rows:
            await interaction.channel.send(
                embed=host_embed(row),
                view=HostCardView(row["id"])
            )

    @discord.ui.button(
        label="Channel & Role",
        emoji="📣",
        style=discord.ButtonStyle.secondary,
        custom_id="hi_notifku:config",
        row=0
    )
    async def config_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await require_owner_or_admin(interaction):
            return

        await interaction.response.send_message(
            "Pilih channel dan role:",
            view=ChannelSetupView(),
            ephemeral=True
        )

    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        custom_id="hi_notifku:refresh",
        row=1
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await require_owner_or_admin(interaction):
            return

        try:
            embed = dashboard_embed(
                interaction.guild_id
            )

            await interaction.response.edit_message(
                embed=embed,
                view=DashboardView()
            )

        except Exception as exc:
            log.exception(
                "Gagal refresh dashboard"
            )

            if interaction.response.is_done():
                await interaction.followup.send(
                    f"❌ Refresh gagal: `{exc}`",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ Refresh gagal: `{exc}`",
                    ephemeral=True
                )




# ============================================================
# SLASH COMMANDS
# ============================================================

@bot.tree.command(
    name="live_panel",
    description="Buka dashboard Hi Notifku."
)
async def live_panel(
    interaction: discord.Interaction
):
    try:
        if not interaction.guild_id:
            await interaction.response.send_message(
                "❌ Gunakan command ini di server Discord.",
                ephemeral=True
            )
            return

        if not await require_owner_or_admin(interaction):
            return

        # Segera defer agar Discord tidak timeout walau DB sedang migrasi/slow.
        await interaction.response.defer(
            ephemeral=False,
            thinking=True
        )

        embed = dashboard_embed(
            interaction.guild_id
        )

        await interaction.followup.send(
            embed=embed,
            view=DashboardView()
        )

    except Exception as exc:
        log.exception(
            "Error pada /live_panel"
        )

        message = (
            "❌ Terjadi error saat membuka panel.\n"
            f"`{type(exc).__name__}: {exc}`"
        )

        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    message,
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    message,
                    ephemeral=True
                )
        except Exception:
            log.exception(
                "Gagal mengirim error response /live_panel"
            )


@bot.tree.command(
    name="live_panel_private",
    description="Buka dashboard Hi Notifku secara private."
)
async def live_panel_private(
    interaction: discord.Interaction
):
    try:
        if not interaction.guild_id:
            await interaction.response.send_message(
                "❌ Gunakan command ini di server Discord.",
                ephemeral=True
            )
            return

        if not await require_owner_or_admin(interaction):
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        await interaction.followup.send(
            embed=dashboard_embed(
                interaction.guild_id
            ),
            view=DashboardView(),
            ephemeral=True
        )

    except Exception as exc:
        log.exception(
            "Error pada /live_panel_private"
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                f"❌ `{type(exc).__name__}: {exc}`",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ `{type(exc).__name__}: {exc}`",
                ephemeral=True
            )



# ============================================================
# OWNER-ONLY DM CONTROL PANEL
# ============================================================

def is_global_owner_user(user_id: int) -> bool:
    return user_id in OWNER_IDS


async def require_global_owner_dm(interaction: discord.Interaction) -> bool:
    if is_global_owner_user(interaction.user.id):
        return True

    message = "❌ Panel DM ini hanya dapat digunakan oleh **Owner Bot**."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)

    return False


def get_bot_guild(guild_id: int) -> Optional[discord.Guild]:
    return bot.get_guild(guild_id)


def dm_server_embed(guild: discord.Guild):
    cfg = get_config(guild.id)
    hosts = get_hosts(guild.id)

    yt_count = sum(1 for h in hosts if h["platform"] == "youtube")
    tt_count = sum(1 for h in hosts if h["platform"] == "tiktok")
    running_count = sum(1 for h in hosts if h["enabled"])

    yt_channel = (
        f"<#{cfg['youtube_channel_id']}> (`{cfg['youtube_channel_id']}`)"
        if cfg["youtube_channel_id"]
        else "Belum diatur"
    )

    tt_channel = (
        f"<#{cfg['tiktok_channel_id']}> (`{cfg['tiktok_channel_id']}`)"
        if cfg["tiktok_channel_id"]
        else "Belum diatur"
    )

    role = (
        f"<@&{cfg['mention_role_id']}> (`{cfg['mention_role_id']}`)"
        if cfg["mention_role_id"]
        else "Tidak ada"
    )

    embed = discord.Embed(
        title="🔐 Hi Notifku • Owner DM Panel",
        description=(
            f"Server: **{guild.name}**\n"
            f"Server ID: `{guild.id}`\n\n"
            "Semua pengaturan pada panel ini khusus **Owner Bot**."
        ),
        color=discord.Color.blue()
    )

    embed.add_field(name="📺 YouTube Hosts", value=str(yt_count), inline=True)
    embed.add_field(name="🎵 TikTok Hosts", value=str(tt_count), inline=True)
    embed.add_field(name="🟢 Running", value=str(running_count), inline=True)

    embed.add_field(name="📺 Channel YouTube", value=yt_channel, inline=False)
    embed.add_field(name="🎵 Channel TikTok", value=tt_channel, inline=False)
    embed.add_field(name="🔔 Mention Role", value=role, inline=False)

    if REQUIRED_GUILD_ID:
        embed.add_field(
            name="🔐 Required Discord",
            value=(
                f"Server ID: `{REQUIRED_GUILD_ID}`\n"
                "Owner server pengguna wajib menjadi member."
            ),
            inline=False
        )

    embed.set_footer(text="Hi Notifku • Owner DM Control")
    return embed


class SetChannelIdModal(discord.ui.Modal):
    channel_id_input = discord.ui.TextInput(
        label="Discord Channel ID",
        placeholder="Contoh: 123456789012345678",
        max_length=25
    )

    def __init__(self, guild_id: int, platform: str):
        title = "Set Channel TikTok" if platform == "tiktok" else "Set Channel YouTube"
        super().__init__(title=title, timeout=300)
        self.guild_id = guild_id
        self.platform = platform

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_global_owner_dm(interaction):
            return

        raw = self.channel_id_input.value.strip()

        if not raw.isdigit():
            await interaction.response.send_message(
                "❌ Channel ID harus berupa angka.",
                ephemeral=True
            )
            return

        channel_id = int(raw)
        guild = get_bot_guild(self.guild_id)

        if guild is None:
            await interaction.response.send_message(
                "❌ Bot sudah tidak berada di server tersebut.",
                ephemeral=True
            )
            return

        channel = guild.get_channel(channel_id)

        if channel is None:
            try:
                fetched = await guild.fetch_channel(channel_id)
                channel = fetched
            except Exception:
                channel = None

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ ID tersebut bukan text channel yang dapat dipakai bot di server ini.",
                ephemeral=True
            )
            return

        perms = channel.permissions_for(guild.me)
        if not perms.view_channel or not perms.send_messages or not perms.embed_links:
            await interaction.response.send_message(
                "❌ Bot belum punya permission **View Channel + Send Messages + Embed Links** di channel tersebut.",
                ephemeral=True
            )
            return

        set_platform_channel(
            self.guild_id,
            self.platform,
            channel_id
        )

        label = "TikTok" if self.platform == "tiktok" else "YouTube"

        await interaction.response.send_message(
            f"✅ Channel {label} untuk **{guild.name}** diatur ke <#{channel_id}>.",
            ephemeral=True
        )


class SetRoleIdModal(discord.ui.Modal):
    role_id_input = discord.ui.TextInput(
        label="Discord Role ID",
        placeholder="Contoh: 123456789012345678",
        max_length=25
    )

    def __init__(self, guild_id: int):
        super().__init__(title="Set Mention Role", timeout=300)
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_global_owner_dm(interaction):
            return

        raw = self.role_id_input.value.strip()

        if not raw.isdigit():
            await interaction.response.send_message(
                "❌ Role ID harus berupa angka.",
                ephemeral=True
            )
            return

        role_id = int(raw)
        guild = get_bot_guild(self.guild_id)

        if guild is None:
            await interaction.response.send_message(
                "❌ Bot sudah tidak berada di server tersebut.",
                ephemeral=True
            )
            return

        role = guild.get_role(role_id)

        if role is None:
            try:
                roles = await guild.fetch_roles()
                role = discord.utils.get(roles, id=role_id)
            except Exception:
                role = None

        if role is None:
            await interaction.response.send_message(
                "❌ Role tidak ditemukan di server tersebut.",
                ephemeral=True
            )
            return

        set_mention_role(self.guild_id, role_id)

        await interaction.response.send_message(
            f"✅ Mention role untuk **{guild.name}** diatur ke **{role.name}** (`{role.id}`).",
            ephemeral=True
        )


class OwnerAddHostModal(discord.ui.Modal):
    platform = discord.ui.TextInput(
        label="Platform",
        placeholder="tiktok atau youtube",
        max_length=10
    )

    target = discord.ui.TextInput(
        label="Username / YouTube Channel ID",
        placeholder="TikTok: username | YouTube: UCxxxxxxxx",
        max_length=120
    )

    def __init__(self, guild_id: int):
        super().__init__(title="Owner • Tambah Host", timeout=300)
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_global_owner_dm(interaction):
            return

        guild = get_bot_guild(self.guild_id)
        if guild is None:
            await interaction.response.send_message(
                "❌ Bot sudah tidak berada di server tersebut.",
                ephemeral=True
            )
            return

        platform = self.platform.value.strip().lower()
        target = self.target.value.strip()

        if platform not in ("tiktok", "youtube"):
            await interaction.response.send_message(
                "❌ Platform harus `tiktok` atau `youtube`.",
                ephemeral=True
            )
            return

        if platform == "tiktok":
            username = (
                target
                .replace("https://www.tiktok.com/@", "")
                .replace("https://tiktok.com/@", "")
                .split("/")[0]
                .lstrip("@")
                .strip()
            )

            if not username:
                await interaction.response.send_message(
                    "❌ Username TikTok tidak valid.",
                    ephemeral=True
                )
                return

            add_host(
                self.guild_id,
                "tiktok",
                username,
                f"@{username}",
                None
            )

            await interaction.response.send_message(
                f"✅ TikTok **@{username}** ditambahkan ke **{guild.name}**.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            name, uploads = await resolve_youtube_channel(target)

            add_host(
                self.guild_id,
                "youtube",
                target,
                name,
                uploads
            )

            await interaction.followup.send(
                f"✅ YouTube **{name}** ditambahkan ke **{guild.name}**.",
                ephemeral=True
            )

        except Exception as exc:
            await interaction.followup.send(
                f"❌ Gagal menambahkan YouTube: `{exc}`",
                ephemeral=True
            )


class OwnerHostActionsView(discord.ui.View):
    def __init__(self, guild_id: int, host_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id
        self.host_id = host_id

        row = get_host(host_id)

        # Test hanya ada di panel host yang benar-benar terdaftar.
        if row:
            if row["platform"] == "tiktok":
                live_btn = discord.ui.Button(
                    label="Test LIVE",
                    emoji="🧪",
                    style=discord.ButtonStyle.success,
                    row=0
                )
                live_btn.callback = self.test_tiktok_live_callback
                self.add_item(live_btn)

                post_btn = discord.ui.Button(
                    label="Test Post",
                    emoji="🆕",
                    style=discord.ButtonStyle.success,
                    row=0
                )
                post_btn.callback = self.test_tiktok_post_callback
                self.add_item(post_btn)

            elif row["platform"] == "youtube":
                live_btn = discord.ui.Button(
                    label="Test LIVE",
                    emoji="🧪",
                    style=discord.ButtonStyle.success,
                    row=0
                )
                live_btn.callback = self.test_youtube_live_callback
                self.add_item(live_btn)

        pause_btn = discord.ui.Button(
            label="Pause / Resume",
            emoji="⏯️",
            style=discord.ButtonStyle.secondary,
            row=1
        )
        pause_btn.callback = self.toggle_host_callback
        self.add_item(pause_btn)

        delete_btn = discord.ui.Button(
            label="Hapus",
            emoji="🗑️",
            style=discord.ButtonStyle.danger,
            row=1
        )
        delete_btn.callback = self.delete_host_callback
        self.add_item(delete_btn)

        back_btn = discord.ui.Button(
            label="Kembali",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary,
            row=2
        )
        back_btn.callback = self.back_callback
        self.add_item(back_btn)

        home_btn = discord.ui.Button(
            label="Menu Awal",
            emoji="🏠",
            style=discord.ButtonStyle.secondary,
            row=2
        )
        home_btn.callback = self.home_callback
        self.add_item(home_btn)

    async def _validate_owner_and_host(self, interaction: discord.Interaction):
        if not await require_global_owner_dm(interaction):
            return None

        row = get_host(self.host_id)

        if not row or row["guild_id"] != self.guild_id:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "❌ Host tidak ditemukan.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "❌ Host tidak ditemukan.",
                    ephemeral=True
                )
            return None

        return row

    async def test_tiktok_live_callback(self, interaction: discord.Interaction):
        row = await self._validate_owner_and_host(interaction)
        if row is None:
            return

        await interaction.response.defer(ephemeral=True)

        ok = await send_live_notification(
            self.guild_id,
            "tiktok",
            row["target"],
            "Test TikTok LIVE",
            f"https://www.tiktok.com/@{row['target']}/live"
        )

        await interaction.followup.send(
            "✅ Test LIVE host TikTok berhasil dikirim."
            if ok else
            "❌ Channel TikTok belum diatur atau bot tidak dapat mengirim.",
            ephemeral=True
        )

    async def test_tiktok_post_callback(self, interaction: discord.Interaction):
        row = await self._validate_owner_and_host(interaction)
        if row is None:
            return

        await interaction.response.defer(ephemeral=True)

        username = row["target"].lstrip("@")

        ok = await send_tiktok_post_notification(
            guild_id=self.guild_id,
            username=username,
            post_id="TEST123",
            post_url=f"https://www.tiktok.com/@{username}",
            description=f"Ini adalah contoh notifikasi postingan baru dari @{username}."
        )

        await interaction.followup.send(
            "✅ Test Post host TikTok berhasil dikirim."
            if ok else
            "❌ Channel TikTok belum diatur atau bot tidak dapat mengirim.",
            ephemeral=True
        )

    async def test_youtube_live_callback(self, interaction: discord.Interaction):
        row = await self._validate_owner_and_host(interaction)
        if row is None:
            return

        await interaction.response.defer(ephemeral=True)

        ok = await send_live_notification(
            self.guild_id,
            "youtube",
            row["display_name"] or row["target"],
            "Test YouTube Live Stream",
            "https://www.youtube.com/"
        )

        await interaction.followup.send(
            "✅ Test LIVE host YouTube berhasil dikirim."
            if ok else
            "❌ Channel YouTube belum diatur atau bot tidak dapat mengirim.",
            ephemeral=True
        )

    async def toggle_host_callback(self, interaction: discord.Interaction):
        row = await self._validate_owner_and_host(interaction)
        if row is None:
            return

        enabled = toggle_host(self.host_id)

        await interaction.response.send_message(
            "✅ Host sekarang **Running**."
            if enabled else
            "⏸️ Host sekarang **Paused**.",
            ephemeral=True
        )

    async def delete_host_callback(self, interaction: discord.Interaction):
        row = await self._validate_owner_and_host(interaction)
        if row is None:
            return

        delete_host(self.host_id)

        await interaction.response.send_message(
            "🗑️ Host berhasil dihapus.",
            ephemeral=True
        )

        try:
            await interaction.message.delete()
        except Exception:
            pass

    async def back_callback(self, interaction: discord.Interaction):
        if not await require_global_owner_dm(interaction):
            return

        guild = get_bot_guild(self.guild_id)

        if guild is None:
            await interaction.response.edit_message(
                embed=owner_dm_home_embed(),
                view=OwnerDMHomeView()
            )
            return

        embed = discord.Embed(
            title="👤 Kelola Host",
            description=f"Server: **{guild.name}**\nPilih tindakan host di bawah.",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=OwnerHostMenuView(self.guild_id)
        )

    async def home_callback(self, interaction: discord.Interaction):
        if not await require_global_owner_dm(interaction):
            return

        await interaction.response.edit_message(
            embed=owner_dm_home_embed(),
            view=OwnerDMHomeView()
        )


class OwnerServerPanelView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id

    async def ensure_owner_and_guild(self, interaction: discord.Interaction):
        if not await require_global_owner_dm(interaction):
            return None

        guild = get_bot_guild(self.guild_id)
        if guild is None:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "❌ Bot sudah tidak berada di server tersebut.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "❌ Bot sudah tidak berada di server tersebut.",
                    ephemeral=True
                )
            return None

        return guild

    @discord.ui.button(
        label="Kelola Host",
        emoji="👤",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def host_menu_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = await self.ensure_owner_and_guild(interaction)
        if guild is None:
            return

        embed = discord.Embed(
            title="👤 Kelola Host",
            description=f"Server: **{guild.name}**\nPilih tindakan host di bawah.",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=OwnerHostMenuView(self.guild_id)
        )

    @discord.ui.button(
        label="Atur Notifikasi",
        emoji="📣",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def notif_menu_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = await self.ensure_owner_and_guild(interaction)
        if guild is None:
            return

        embed = discord.Embed(
            title="📣 Atur Notifikasi",
            description=(
                f"Server: **{guild.name}**\n"
                "Atur channel TikTok, YouTube, dan mention role."
            ),
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=OwnerNotifMenuView(self.guild_id)
        )

    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = await self.ensure_owner_and_guild(interaction)
        if guild is None:
            return

        await interaction.response.edit_message(
            embed=dm_server_embed(guild),
            view=OwnerServerPanelView(self.guild_id)
        )

    @discord.ui.button(
        label="Ganti Server",
        emoji="🔁",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def switch_server_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_global_owner_dm(interaction):
            return

        await interaction.response.edit_message(
            embed=owner_dm_home_embed(),
            view=OwnerDMHomeView()
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def home_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_global_owner_dm(interaction):
            return

        await interaction.response.edit_message(
            embed=owner_dm_home_embed(),
            view=OwnerDMHomeView()
        )


def owner_dm_home_embed():
    embed = discord.Embed(
        title="🔐 Hi Notifku • Owner Control",
        description=(
            "Panel ini berada di **DM bot** dan hanya dapat digunakan oleh Owner.\n\n"
            "Pilih server di menu bawah. Setelah itu gunakan **Kelola Host** atau **Atur Notifikasi**."
        ),
        color=discord.Color.blue()
    )

    embed.add_field(
        name="Server aktif",
        value=str(len(bot.guilds)),
        inline=True
    )

    embed.add_field(
        name="Owner terdaftar",
        value=str(len(OWNER_IDS)),
        inline=True
    )

    embed.set_footer(
        text="Hi Notifku • Private Owner DM Panel"
    )

    return embed


class OwnerGuildSelect(discord.ui.Select):
    def __init__(self):
        guilds = list(bot.guilds)[:25]

        options = [
            discord.SelectOption(
                label=guild.name[:100],
                value=str(guild.id),
                description=f"ID: {guild.id}"[:100],
                emoji="🏠"
            )
            for guild in guilds
        ]

        if not options:
            options = [
                discord.SelectOption(
                    label="Bot belum ada di server",
                    value="0",
                    description="Invite bot ke server terlebih dahulu."
                )
            ]

        super().__init__(
            placeholder="Pilih server yang ingin diatur...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="hi_notifku:owner_dm:guild_select"
        )

    async def callback(self, interaction: discord.Interaction):
        if not await require_global_owner_dm(interaction):
            return

        guild_id = int(self.values[0])

        if guild_id == 0:
            await interaction.response.send_message(
                "❌ Bot belum berada di server mana pun.",
                ephemeral=True
            )
            return

        guild = get_bot_guild(guild_id)

        if guild is None:
            await interaction.response.send_message(
                "❌ Server tidak ditemukan.",
                ephemeral=True
            )
            return

        await interaction.response.edit_message(
            embed=dm_server_embed(guild),
            view=OwnerServerPanelView(guild_id)
        )


class OwnerDMHomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)
        self.add_item(OwnerGuildSelect())


async def send_owner_dm_panel(user: discord.User | discord.Member):
    dm = user.dm_channel

    if dm is None:
        dm = await user.create_dm()

    await dm.send(
        embed=owner_dm_home_embed(),
        view=OwnerDMHomeView()
    )


@bot.tree.command(
    name="owner_dm",
    description="Buka/kirim panel kontrol khusus Owner."
)
async def owner_dm(
    interaction: discord.Interaction
):
    try:
        if not is_global_owner_user(interaction.user.id):
            await interaction.response.send_message(
                "❌ Command ini hanya untuk **Owner Bot**.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        try:
            await send_owner_dm_panel(
                interaction.user
            )

            await interaction.followup.send(
                "✅ Panel Owner sudah dikirim ke DM. Setelah ini kamu juga bisa cukup ketik `menu` langsung di DM bot.",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Bot tidak bisa mengirim DM. Aktifkan **Allow direct messages from server members** lalu coba lagi.",
                ephemeral=True
            )

    except Exception as exc:
        log.exception("Error /owner_dm")

        if interaction.response.is_done():
            await interaction.followup.send(
                f"❌ `{type(exc).__name__}: {exc}`",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ `{type(exc).__name__}: {exc}`",
                ephemeral=True
            )


@bot.tree.command(
    name="owner_panel",
    description="Buka panel Owner langsung jika command digunakan di DM."
)
async def owner_panel(
    interaction: discord.Interaction
):
    if not is_global_owner_user(interaction.user.id):
        await interaction.response.send_message(
            "❌ Command ini hanya untuk **Owner Bot**.",
            ephemeral=True
        )
        return

    # Bila command digunakan di guild, kirim panel ke DM agar tetap private.
    if interaction.guild_id is not None:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        try:
            await send_owner_dm_panel(
                interaction.user
            )

            await interaction.followup.send(
                "✅ Panel Owner sudah dikirim ke DM.",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Bot tidak dapat mengirim DM ke akunmu.",
                ephemeral=True
            )
        return

    await interaction.response.send_message(
        embed=owner_dm_home_embed(),
        view=OwnerDMHomeView()
    )




@bot.tree.command(
    name="owner_check",
    description="Cek apakah akunmu terdaftar sebagai Owner Hi Notifku."
)
async def owner_check(interaction: discord.Interaction):
    owner = is_global_owner_user(interaction.user.id)

    embed = discord.Embed(
        title="🔐 Hi Notifku • Owner Check",
        color=discord.Color.green() if owner else discord.Color.red()
    )

    embed.add_field(
        name="Discord User ID",
        value=f"`{interaction.user.id}`",
        inline=False
    )

    embed.add_field(
        name="Status",
        value="✅ Terdaftar sebagai Owner" if owner else "❌ Belum terdaftar di OWNER_IDS",
        inline=False
    )

    embed.add_field(
        name="OWNER_IDS terbaca",
        value=str(len(OWNER_IDS)),
        inline=False
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ============================================================
# GLOBAL APP COMMAND ERROR HANDLER
# ============================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    log.exception(
        "App command error",
        exc_info=error
    )

    original = getattr(
        error,
        "original",
        error
    )

    message = (
        "❌ Terjadi error pada command.\n"
        f"`{type(original).__name__}: {original}`"
    )

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True
            )
    except Exception:
        pass



@bot.event
async def on_message(message: discord.Message):
    # Abaikan pesan dari bot.
    if message.author.bot:
        return

    # Semua pesan private/DM terdeteksi dari guild=None.
    # Tidak membaca isi pesan, jadi tidak membutuhkan Message Content Intent.
    if message.guild is None:
        user_id = message.author.id

        log.info(
            "DM received from user_id=%s owner=%s",
            user_id,
            is_global_owner_user(user_id)
        )

        # Hanya OWNER_IDS yang boleh mendapatkan panel.
        if not is_global_owner_user(user_id):
            try:
                await message.channel.send(
                    "🔒 **Hi Notifku Owner Panel**\n"
                    "Akses DM panel hanya tersedia untuk Owner Bot."
                )
            except Exception:
                log.exception("Gagal membalas DM non-owner")
            return

        try:
            await message.channel.send(
                embed=owner_dm_home_embed(),
                view=OwnerDMHomeView()
            )
        except discord.Forbidden:
            log.exception("Discord Forbidden saat membalas DM owner")
        except discord.HTTPException:
            log.exception("Discord HTTPException saat membalas DM owner")
        except Exception:
            log.exception("Gagal mengirim Owner DM Panel")

        return

    # Agar command prefix tetap dapat diproses di server bila diperlukan.
    await bot.process_commands(message)



@bot.tree.command(
    name="verify_join",
    description="Cek apakah owner server sudah join Discord Owner/Support."
)
async def verify_join(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Command ini hanya bisa digunakan di server.",
            ephemeral=True
        )
        return

    if is_global_owner_user(interaction.user.id):
        await interaction.response.send_message(
            "✅ Kamu adalah Global Owner Bot dan tidak terkena gate.",
            ephemeral=True
        )
        return

    verified = await is_guild_owner_verified(interaction.guild)

    if verified:
        await interaction.response.send_message(
            "✅ Owner server sudah terverifikasi sebagai member Discord Owner/Support. "
            "Fitur Hi Notifku sudah terbuka.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            required_join_text(),
            ephemeral=True
        )


@bot.event
async def on_guild_join(guild: discord.Guild):
    try:
        await send_required_join_notice(guild)
    except Exception:
        log.exception(
            "Error on_guild_join guild_id=%s",
            guild.id
        )


# ============================================================
# EVENTS
# ============================================================

@bot.event
async def on_ready():
    global http, _views_registered

    if http is None or http.closed:
        http = aiohttp.ClientSession()

    if not _views_registered:
        bot.add_view(
            DashboardView()
        )
        _views_registered = True

    log.info(
        "Login sebagai %s (%s)",
        bot.user,
        bot.user.id
    )

    try:
        synced = await bot.tree.sync()

        log.info(
            "Slash commands synced: %s",
            len(synced)
        )

    except Exception:
        log.exception(
            "Slash command sync gagal"
        )

    if not live_checker.is_running():
        live_checker.start()


async def main():
    global http

    if not DISCORD_TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN belum diisi di Railway Variables."
        )

    init_db()

    try:
        await bot.start(
            DISCORD_TOKEN
        )

    finally:
        if http and not http.closed:
            await http.close()


if __name__ == "__main__":
    asyncio.run(main())
