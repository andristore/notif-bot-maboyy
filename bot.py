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

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
CHECK_INTERVAL = max(60, int(os.getenv("CHECK_INTERVAL", "120")))
DB_PATH = os.getenv("DB_PATH", "live_notifier.db")

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
    if is_owner_or_admin(interaction):
        return True

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
            "Kelola notifikasi **YouTube Live Stream** "
            "dan **TikTok LIVE** menggunakan tombol di bawah."
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

    @discord.ui.button(
        label="Test YouTube",
        emoji="📺",
        style=discord.ButtonStyle.danger,
        custom_id="hi_notifku:test_youtube",
        row=1
    )
    async def test_youtube_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await require_owner_or_admin(interaction):
            return

        await interaction.response.defer(
            ephemeral=True
        )

        ok = await send_live_notification(
            interaction.guild_id,
            "youtube",
            "Test Creator",
            "Test YouTube Live Stream",
            "https://www.youtube.com/"
        )

        await interaction.followup.send(
            (
                "✅ Test YouTube dikirim."
                if ok
                else
                "❌ Atur channel YouTube terlebih dahulu."
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="Test TikTok",
        emoji="🎵",
        style=discord.ButtonStyle.danger,
        custom_id="hi_notifku:test_tiktok",
        row=1
    )
    async def test_tiktok_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await require_owner_or_admin(interaction):
            return

        await interaction.response.defer(
            ephemeral=True
        )

        ok = await send_live_notification(
            interaction.guild_id,
            "tiktok",
            "testcreator",
            "Test TikTok LIVE",
            "https://www.tiktok.com/"
        )

        await interaction.followup.send(
            (
                "✅ Test TikTok dikirim."
                if ok
                else
                "❌ Atur channel TikTok terlebih dahulu."
            ),
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
