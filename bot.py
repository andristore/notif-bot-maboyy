import os
import io
import json
import time
import asyncio
import logging
import sqlite3
from contextlib import closing
from typing import Optional

import aiohttp
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from TikTokLive import TikTokLiveClient
from yt_dlp import YoutubeDL

load_dotenv()

# ============================================================
# CONFIG
# ============================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()

DEFAULT_CHECK_INTERVAL = max(60, int(os.getenv("CHECK_INTERVAL", "120")))
BASE_MONITOR_TICK = max(30, int(os.getenv("BASE_MONITOR_TICK", "30")))

DB_PATH = os.getenv("DB_PATH", "live_notifier.db")

OWNER_IDS = {
    int(x.strip())
    for x in os.getenv("OWNER_IDS", "").split(",")
    if x.strip().isdigit()
}

REQUIRED_GUILD_ID = int(os.getenv("REQUIRED_GUILD_ID", "0") or 0)
REQUIRED_GUILD_INVITE = os.getenv("REQUIRED_GUILD_INVITE", "").strip()

FREE_HOST_LIMIT = max(1, int(os.getenv("FREE_HOST_LIMIT", "5")))
PREMIUM_HOST_LIMIT = max(FREE_HOST_LIMIT, int(os.getenv("PREMIUM_HOST_LIMIT", "100")))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("hi-notifku")

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

http: Optional[aiohttp.ClientSession] = None
STARTED_AT = int(time.time())


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,)
    ).fetchone() is not None


def columns(conn, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def add_column_if_missing(conn, table: str, name: str, sql_type: str):
    if name not in columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def migrate_database():
    with closing(db()) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        # Guild config
        if not table_exists(conn, "guild_config"):
            conn.execute("""
                CREATE TABLE guild_config (
                    guild_id INTEGER PRIMARY KEY,
                    youtube_channel_id INTEGER,
                    tiktok_channel_id INTEGER,
                    mention_role_id INTEGER,
                    log_channel_id INTEGER
                )
            """)
        else:
            old_cols = columns(conn, "guild_config")
            needed = {
                "guild_id",
                "youtube_channel_id",
                "tiktok_channel_id",
                "mention_role_id"
            }

            if not needed.issubset(old_cols):
                conn.execute("DROP TABLE IF EXISTS guild_config_v2")
                conn.execute("""
                    CREATE TABLE guild_config_v2 (
                        guild_id INTEGER PRIMARY KEY,
                        youtube_channel_id INTEGER,
                        tiktok_channel_id INTEGER,
                        mention_role_id INTEGER,
                        log_channel_id INTEGER
                    )
                """)

                yt_expr = (
                    "youtube_channel_id"
                    if "youtube_channel_id" in old_cols
                    else ("channel_id" if "channel_id" in old_cols else "NULL")
                )
                tt_expr = (
                    "tiktok_channel_id"
                    if "tiktok_channel_id" in old_cols
                    else ("channel_id" if "channel_id" in old_cols else "NULL")
                )
                role_expr = (
                    "mention_role_id"
                    if "mention_role_id" in old_cols
                    else ("role_id" if "role_id" in old_cols else "NULL")
                )
                log_expr = "log_channel_id" if "log_channel_id" in old_cols else "NULL"

                conn.execute(f"""
                    INSERT OR REPLACE INTO guild_config_v2(
                        guild_id,
                        youtube_channel_id,
                        tiktok_channel_id,
                        mention_role_id,
                        log_channel_id
                    )
                    SELECT
                        guild_id,
                        {yt_expr},
                        {tt_expr},
                        {role_expr},
                        {log_expr}
                    FROM guild_config
                """)

                conn.execute("DROP TABLE guild_config")
                conn.execute("ALTER TABLE guild_config_v2 RENAME TO guild_config")

            add_column_if_missing(conn, "guild_config", "log_channel_id", "INTEGER")

        # Hosts
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
                    channel_id INTEGER,
                    role_id INTEGER,
                    custom_live_message TEXT,
                    custom_post_message TEXT,
                    custom_end_message TEXT,
                    notify_live_end INTEGER NOT NULL DEFAULT 0,
                    check_interval INTEGER NOT NULL DEFAULT 120,
                    last_check INTEGER,
                    last_error TEXT,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    cooldown_until INTEGER,
                    UNIQUE(guild_id, platform, target)
                )
            """)
        else:
            additions = {
                "enabled": "INTEGER NOT NULL DEFAULT 1",
                "channel_id": "INTEGER",
                "role_id": "INTEGER",
                "custom_live_message": "TEXT",
                "custom_post_message": "TEXT",
                "custom_end_message": "TEXT",
                "notify_live_end": "INTEGER NOT NULL DEFAULT 0",
                "check_interval": f"INTEGER NOT NULL DEFAULT {DEFAULT_CHECK_INTERVAL}",
                "last_check": "INTEGER",
                "last_error": "TEXT",
                "error_count": "INTEGER NOT NULL DEFAULT 0",
                "cooldown_until": "INTEGER",
            }
            for name, sql_type in additions.items():
                add_column_if_missing(conn, "hosts", name, sql_type)

        # Live state
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

        # TikTok post state
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

        # Guild plan/access
        if not table_exists(conn, "guild_settings"):
            conn.execute("""
                CREATE TABLE guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    plan TEXT NOT NULL DEFAULT 'free',
                    access_state TEXT NOT NULL DEFAULT 'allowed'
                )
            """)

        # Additional bot owners managed from DM
        if not table_exists(conn, "bot_owners"):
            conn.execute("""
                CREATE TABLE bot_owners (
                    user_id INTEGER PRIMARY KEY,
                    added_by INTEGER,
                    added_at INTEGER NOT NULL
                )
            """)

        # Activity log
        if not table_exists(conn, "activity_log"):
            conn.execute("""
                CREATE TABLE activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    actor_id INTEGER,
                    action TEXT NOT NULL,
                    detail TEXT,
                    created_at INTEGER NOT NULL
                )
            """)

        conn.commit()
        log.info("Database schema ready.")


def ensure_guild(guild_id: int):
    with closing(db()) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO guild_config(
                guild_id,
                youtube_channel_id,
                tiktok_channel_id,
                mention_role_id,
                log_channel_id
            )
            VALUES(?,NULL,NULL,NULL,NULL)
        """, (guild_id,))

        conn.execute("""
            INSERT OR IGNORE INTO guild_settings(
                guild_id, plan, access_state
            )
            VALUES(?, 'free', 'allowed')
        """, (guild_id,))

        conn.commit()


def get_config(guild_id: int):
    ensure_guild(guild_id)
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM guild_config WHERE guild_id=?",
            (guild_id,)
        ).fetchone()


def get_guild_settings(guild_id: int):
    ensure_guild(guild_id)
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM guild_settings WHERE guild_id=?",
            (guild_id,)
        ).fetchone()


def set_plan(guild_id: int, plan: str):
    plan = "premium" if plan == "premium" else "free"
    ensure_guild(guild_id)
    with closing(db()) as conn:
        conn.execute(
            "UPDATE guild_settings SET plan=? WHERE guild_id=?",
            (plan, guild_id)
        )
        conn.commit()


def set_access_state(guild_id: int, state: str):
    if state not in {"allowed", "blacklist", "whitelist"}:
        state = "allowed"
    ensure_guild(guild_id)
    with closing(db()) as conn:
        conn.execute(
            "UPDATE guild_settings SET access_state=? WHERE guild_id=?",
            (state, guild_id)
        )
        conn.commit()


def host_limit_for_guild(guild_id: int) -> int:
    settings = get_guild_settings(guild_id)
    return PREMIUM_HOST_LIMIT if settings["plan"] == "premium" else FREE_HOST_LIMIT


def set_default_channel(guild_id: int, platform: str, channel_id: Optional[int]):
    ensure_guild(guild_id)
    column = "youtube_channel_id" if platform == "youtube" else "tiktok_channel_id"
    with closing(db()) as conn:
        conn.execute(
            f"UPDATE guild_config SET {column}=? WHERE guild_id=?",
            (channel_id, guild_id)
        )
        conn.commit()


def set_default_role(guild_id: int, role_id: Optional[int]):
    ensure_guild(guild_id)
    with closing(db()) as conn:
        conn.execute(
            "UPDATE guild_config SET mention_role_id=? WHERE guild_id=?",
            (role_id, guild_id)
        )
        conn.commit()


def set_log_channel(guild_id: int, channel_id: Optional[int]):
    ensure_guild(guild_id)
    with closing(db()) as conn:
        conn.execute(
            "UPDATE guild_config SET log_channel_id=? WHERE guild_id=?",
            (channel_id, guild_id)
        )
        conn.commit()


def get_hosts(guild_id: int):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT * FROM hosts
            WHERE guild_id=?
            ORDER BY platform, id
        """, (guild_id,)).fetchall()


def get_host(host_id: int):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM hosts WHERE id=?",
            (host_id,)
        ).fetchone()


def get_enabled_hosts():
    with closing(db()) as conn:
        return conn.execute("""
            SELECT * FROM hosts
            WHERE enabled=1
            ORDER BY guild_id, platform, id
        """).fetchall()


def add_host(
    guild_id: int,
    platform: str,
    target: str,
    display_name=None,
    extra=None
):
    ensure_guild(guild_id)

    existing = None
    with closing(db()) as conn:
        existing = conn.execute("""
            SELECT * FROM hosts
            WHERE guild_id=? AND platform=? AND target=?
        """, (guild_id, platform, target)).fetchone()

    if not existing and len(get_hosts(guild_id)) >= host_limit_for_guild(guild_id):
        raise ValueError(
            f"Batas host tercapai ({host_limit_for_guild(guild_id)} host)."
        )

    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO hosts(
                guild_id,
                platform,
                target,
                display_name,
                extra,
                enabled,
                check_interval
            )
            VALUES(?,?,?,?,?,1,?)
            ON CONFLICT(guild_id, platform, target)
            DO UPDATE SET
                display_name=excluded.display_name,
                extra=COALESCE(excluded.extra, hosts.extra),
                enabled=1
        """, (
            guild_id,
            platform,
            target,
            display_name,
            extra,
            DEFAULT_CHECK_INTERVAL
        ))

        conn.execute("""
            INSERT OR IGNORE INTO live_state(
                guild_id, platform, target, is_live, live_key
            )
            VALUES(?,?,?,0,NULL)
        """, (guild_id, platform, target))

        conn.commit()


def delete_host(host_id: int):
    row = get_host(host_id)
    if not row:
        return

    with closing(db()) as conn:
        conn.execute("DELETE FROM hosts WHERE id=?", (host_id,))
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


def set_host_enabled(host_id: int, enabled: bool):
    with closing(db()) as conn:
        conn.execute(
            "UPDATE hosts SET enabled=? WHERE id=?",
            (1 if enabled else 0, host_id)
        )
        conn.commit()


def toggle_host(host_id: int):
    row = get_host(host_id)
    if not row:
        return None
    enabled = not bool(row["enabled"])
    set_host_enabled(host_id, enabled)
    return enabled


def set_host_channel(host_id: int, channel_id: Optional[int]):
    with closing(db()) as conn:
        conn.execute(
            "UPDATE hosts SET channel_id=? WHERE id=?",
            (channel_id, host_id)
        )
        conn.commit()


def set_host_role(host_id: int, role_id: Optional[int]):
    with closing(db()) as conn:
        conn.execute(
            "UPDATE hosts SET role_id=? WHERE id=?",
            (role_id, host_id)
        )
        conn.commit()


def set_host_interval(host_id: int, seconds: int):
    seconds = max(60, min(3600, seconds))
    with closing(db()) as conn:
        conn.execute(
            "UPDATE hosts SET check_interval=? WHERE id=?",
            (seconds, host_id)
        )
        conn.commit()


def set_host_notify_end(host_id: int, enabled: bool):
    with closing(db()) as conn:
        conn.execute(
            "UPDATE hosts SET notify_live_end=? WHERE id=?",
            (1 if enabled else 0, host_id)
        )
        conn.commit()


def set_host_messages(
    host_id: int,
    live_message: Optional[str] = None,
    post_message: Optional[str] = None,
    end_message: Optional[str] = None
):
    with closing(db()) as conn:
        conn.execute("""
            UPDATE hosts SET
                custom_live_message=COALESCE(?, custom_live_message),
                custom_post_message=COALESCE(?, custom_post_message),
                custom_end_message=COALESCE(?, custom_end_message)
            WHERE id=?
        """, (
            live_message,
            post_message,
            end_message,
            host_id
        ))
        conn.commit()


def clear_host_messages(host_id: int):
    with closing(db()) as conn:
        conn.execute("""
            UPDATE hosts SET
                custom_live_message=NULL,
                custom_post_message=NULL,
                custom_end_message=NULL
            WHERE id=?
        """, (host_id,))
        conn.commit()


def set_host_health(
    host_id: int,
    error: Optional[str] = None,
    *,
    success: bool = False
):
    now = int(time.time())

    with closing(db()) as conn:
        row = conn.execute(
            "SELECT error_count FROM hosts WHERE id=?",
            (host_id,)
        ).fetchone()

        if not row:
            return

        if success:
            conn.execute("""
                UPDATE hosts SET
                    last_check=?,
                    last_error=NULL,
                    error_count=0,
                    cooldown_until=NULL
                WHERE id=?
            """, (now, host_id))
        else:
            errors = int(row["error_count"] or 0) + 1
            cooldown = None

            if errors >= 3:
                cooldown_seconds = min(1800, 60 * (2 ** min(errors - 3, 4)))
                cooldown = now + cooldown_seconds

            conn.execute("""
                UPDATE hosts SET
                    last_check=?,
                    last_error=?,
                    error_count=?,
                    cooldown_until=?
                WHERE id=?
            """, (
                now,
                (error or "Unknown error")[:1000],
                errors,
                cooldown,
                host_id
            ))

        conn.commit()


def get_live_state(guild_id: int, platform: str, target: str):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT * FROM live_state
            WHERE guild_id=? AND platform=? AND target=?
        """, (
            guild_id,
            platform,
            target
        )).fetchone()


def update_live_state(
    guild_id: int,
    platform: str,
    target: str,
    is_live: bool,
    live_key=None
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO live_state(
                guild_id, platform, target, is_live, live_key
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
    post_id: Optional[str]
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO tiktok_post_state(
                guild_id,
                username,
                last_post_id,
                initialized
            )
            VALUES(?,?,?,1)
            ON CONFLICT(guild_id, username)
            DO UPDATE SET
                last_post_id=excluded.last_post_id,
                initialized=1
        """, (
            guild_id,
            username,
            post_id
        ))
        conn.commit()


def delete_guild_data(guild_id: int):
    with closing(db()) as conn:
        for table in [
            "guild_config",
            "guild_settings",
            "hosts",
            "live_state",
            "tiktok_post_state",
            "activity_log"
        ]:
            conn.execute(
                f"DELETE FROM {table} WHERE guild_id=?",
                (guild_id,)
            )
        conn.commit()


def add_db_owner(user_id: int, added_by: int):
    with closing(db()) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO bot_owners(
                user_id, added_by, added_at
            )
            VALUES(?,?,?)
        """, (
            user_id,
            added_by,
            int(time.time())
        ))
        conn.commit()


def remove_db_owner(user_id: int):
    with closing(db()) as conn:
        conn.execute(
            "DELETE FROM bot_owners WHERE user_id=?",
            (user_id,)
        )
        conn.commit()


def db_owner_ids() -> set[int]:
    with closing(db()) as conn:
        return {
            int(row["user_id"])
            for row in conn.execute(
                "SELECT user_id FROM bot_owners"
            ).fetchall()
        }


def add_activity(
    guild_id: Optional[int],
    actor_id: Optional[int],
    action: str,
    detail: str = ""
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO activity_log(
                guild_id,
                actor_id,
                action,
                detail,
                created_at
            )
            VALUES(?,?,?,?,?)
        """, (
            guild_id,
            actor_id,
            action,
            detail[:1500],
            int(time.time())
        ))
        conn.commit()


def recent_activity(guild_id: int, limit: int = 10):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT * FROM activity_log
            WHERE guild_id=?
            ORDER BY id DESC
            LIMIT ?
        """, (
            guild_id,
            limit
        )).fetchall()


# ============================================================
# ACCESS CONTROL
# ============================================================

def is_primary_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


def is_global_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS or user_id in db_owner_ids()


async def require_global_owner(interaction: discord.Interaction) -> bool:
    if is_global_owner(interaction.user.id):
        return True

    await safe_reply(
        interaction,
        "🔒 Panel ini hanya untuk **Global Owner Bot**."
    )
    return False


async def is_user_in_required_guild(user_id: int) -> bool:
    if not REQUIRED_GUILD_ID:
        return True

    required = bot.get_guild(REQUIRED_GUILD_ID)

    if required is None:
        log.error(
            "Bot tidak berada di REQUIRED_GUILD_ID=%s",
            REQUIRED_GUILD_ID
        )
        return False

    if required.get_member(user_id):
        return True

    try:
        await required.fetch_member(user_id)
        return True
    except discord.NotFound:
        return False
    except discord.Forbidden:
        log.error("Tidak dapat fetch member required guild.")
        return False
    except discord.HTTPException as exc:
        log.warning("Membership check error: %s", exc)
        return False


async def guild_owner_verified(guild: discord.Guild) -> bool:
    return await is_user_in_required_guild(guild.owner_id)


def required_join_text() -> str:
    if REQUIRED_GUILD_INVITE:
        return (
            "🔒 Owner server belum terverifikasi.\n"
            "Owner server wajib join Discord Owner/Support:\n"
            f"{REQUIRED_GUILD_INVITE}"
        )

    return (
        "🔒 Owner server belum terverifikasi.\n"
        "REQUIRED_GUILD_INVITE belum diisi."
    )


def guild_access_allowed(guild_id: int) -> bool:
    settings = get_guild_settings(guild_id)
    return settings["access_state"] != "blacklist"


# ============================================================
# SAFE DISCORD HELPERS
# ============================================================

async def safe_reply(
    interaction: discord.Interaction,
    content: str = "",
    *,
    embed: Optional[discord.Embed] = None,
    view: Optional[discord.ui.View] = None,
    ephemeral: bool = True
):
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                content=content or None,
                embed=embed,
                view=view,
                ephemeral=ephemeral
            )
        else:
            await interaction.response.send_message(
                content=content or None,
                embed=embed,
                view=view,
                ephemeral=ephemeral
            )
    except Exception:
        log.exception("Interaction response gagal")


async def resolve_channel(channel_id: Optional[int]):
    if not channel_id:
        return None

    channel = bot.get_channel(channel_id)
    if channel:
        return channel

    try:
        return await bot.fetch_channel(channel_id)
    except Exception:
        return None


def render_template(
    template: Optional[str],
    *,
    creator: str,
    url: str,
    platform: str
) -> Optional[str]:
    if not template:
        return None

    replacements = {
        "{creator}": creator,
        "{url}": url,
        "{platform}": platform,
    }

    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)

    return rendered[:2000]


def notification_target(host):
    cfg = get_config(host["guild_id"])

    channel_id = host["channel_id"] or (
        cfg["youtube_channel_id"]
        if host["platform"] == "youtube"
        else cfg["tiktok_channel_id"]
    )

    role_id = host["role_id"] or cfg["mention_role_id"]

    return channel_id, role_id


async def send_notification(
    host,
    embed: discord.Embed,
    content_override: Optional[str] = None
):
    channel_id, role_id = notification_target(host)
    channel = await resolve_channel(channel_id)

    if not channel:
        return False

    content_parts = []

    if role_id:
        content_parts.append(f"<@&{role_id}>")

    if content_override:
        content_parts.append(content_override)

    content = "\n".join(content_parts) if content_parts else None

    try:
        await channel.send(
            content=content,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                roles=True,
                users=False,
                everyone=False
            )
        )
        return True
    except discord.Forbidden:
        log.error("Forbidden kirim ke channel=%s", channel_id)
        return False
    except discord.HTTPException as exc:
        log.error("Discord HTTP error: %s", exc)
        return False


async def send_activity_to_discord(
    guild_id: int,
    title: str,
    detail: str
):
    cfg = get_config(guild_id)
    if not cfg["log_channel_id"]:
        return

    channel = await resolve_channel(cfg["log_channel_id"])
    if not channel:
        return

    try:
        embed = discord.Embed(
            title=f"🧾 {title}",
            description=detail[:4000],
            color=discord.Color.dark_gray()
        )
        embed.set_footer(text="Hi Notifku • Activity Log")
        await channel.send(embed=embed)
    except Exception:
        log.exception("Gagal kirim activity log")


async def log_action(
    guild_id: int,
    actor_id: int,
    action: str,
    detail: str
):
    add_activity(guild_id, actor_id, action, detail)
    await send_activity_to_discord(
        guild_id,
        action,
        f"Actor: <@{actor_id}>\n{detail}"
    )


# ============================================================
# YOUTUBE
# ============================================================

async def yt_api(endpoint: str, params: dict):
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY belum diisi.")

    if http is None or http.closed:
        raise RuntimeError("HTTP session belum siap.")

    payload = dict(params)
    payload["key"] = YOUTUBE_API_KEY

    async with http.get(
        f"https://www.googleapis.com/youtube/v3/{endpoint}",
        params=payload,
        timeout=aiohttp.ClientTimeout(total=20)
    ) as response:
        data = await response.json()

        if response.status != 200:
            raise RuntimeError(
                data.get("error", {}).get(
                    "message",
                    f"YouTube HTTP {response.status}"
                )
            )

        return data


async def resolve_youtube_channel(channel_id: str):
    data = await yt_api(
        "channels",
        {
            "part": "snippet,contentDetails",
            "id": channel_id
        }
    )

    items = data.get("items", [])

    if not items:
        raise ValueError("YouTube Channel ID tidak ditemukan.")

    item = items[0]

    return (
        item["snippet"]["title"],
        item["contentDetails"]["relatedPlaylists"]["uploads"]
    )


async def check_youtube_live(host):
    channel_id = host["target"]
    name = host["display_name"] or channel_id
    uploads = host["extra"]

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
                host["id"]
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

    ids = [
        x.get("contentDetails", {}).get("videoId")
        for x in playlist.get("items", [])
        if x.get("contentDetails", {}).get("videoId")
    ]

    previous = get_live_state(
        host["guild_id"],
        "youtube",
        channel_id
    )

    if not ids:
        if previous and previous["is_live"]:
            await maybe_send_live_end(host, name, "YouTube")
        update_live_state(
            host["guild_id"],
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
            "id": ",".join(ids)
        }
    )

    live_video = next(
        (
            item
            for item in videos.get("items", [])
            if item.get("snippet", {}).get("liveBroadcastContent") == "live"
        ),
        None
    )

    if not live_video:
        if previous and previous["is_live"]:
            await maybe_send_live_end(host, name, "YouTube")

        update_live_state(
            host["guild_id"],
            "youtube",
            channel_id,
            False,
            None
        )
        return

    video_id = live_video["id"]
    snippet = live_video["snippet"]
    url = f"https://www.youtube.com/watch?v={video_id}"

    same_live = (
        previous
        and previous["is_live"]
        and previous["live_key"] == video_id
    )

    if not same_live:
        creator = snippet.get("channelTitle", name)

        embed = discord.Embed(
            title="🔴 YouTube LIVE",
            description=f"**{creator}** sedang live!",
            url=url,
            color=discord.Color.red()
        )

        embed.add_field(
            name="Judul",
            value=snippet.get("title", "Live sekarang")[:1024],
            inline=False
        )

        custom = render_template(
            host["custom_live_message"],
            creator=creator,
            url=url,
            platform="YouTube"
        )

        await send_notification(host, embed, custom)

    update_live_state(
        host["guild_id"],
        "youtube",
        channel_id,
        True,
        video_id
    )


# ============================================================
# TIKTOK
# ============================================================

async def check_tiktok_live(host):
    username = host["target"].lstrip("@")
    previous = get_live_state(
        host["guild_id"],
        "tiktok",
        username
    )

    client = TikTokLiveClient(unique_id=f"@{username}")

    try:
        live = await asyncio.wait_for(
            client.is_live(),
            timeout=25
        )
    except asyncio.TimeoutError:
        raise RuntimeError(f"Timeout TikTok LIVE @{username}")

    if live:
        if not previous or not previous["is_live"]:
            url = f"https://www.tiktok.com/@{username}/live"

            embed = discord.Embed(
                title="🔴 TikTok LIVE",
                description=f"**@{username}** sedang LIVE!",
                url=url,
                color=discord.Color.from_rgb(0, 170, 255)
            )

            custom = render_template(
                host["custom_live_message"],
                creator=f"@{username}",
                url=url,
                platform="TikTok"
            )

            await send_notification(host, embed, custom)

        update_live_state(
            host["guild_id"],
            "tiktok",
            username,
            True,
            username
        )

    else:
        if previous and previous["is_live"]:
            await maybe_send_live_end(
                host,
                f"@{username}",
                "TikTok"
            )

        update_live_state(
            host["guild_id"],
            "tiktok",
            username,
            False,
            None
        )


async def maybe_send_live_end(host, creator: str, platform: str):
    if not host["notify_live_end"]:
        return

    url = (
        f"https://www.tiktok.com/@{host['target'].lstrip('@')}"
        if platform == "TikTok"
        else "https://www.youtube.com/"
    )

    embed = discord.Embed(
        title=f"⚫ {platform} LIVE Selesai",
        description=f"Live dari **{creator}** telah selesai.",
        color=discord.Color.dark_gray()
    )

    custom = render_template(
        host["custom_end_message"],
        creator=creator,
        url=url,
        platform=platform
    )

    await send_notification(host, embed, custom)


def _latest_tiktok_post_sync(username: str):
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
            f"https://www.tiktok.com/@{username}",
            download=False
        )

    if not info:
        return None

    for entry in info.get("entries") or []:
        if not entry:
            continue

        post_id = str(
            entry.get("id")
            or entry.get("display_id")
            or ""
        ).strip()

        if not post_id:
            continue

        url = entry.get("webpage_url") or entry.get("url")

        if not isinstance(url, str) or not url.startswith("http"):
            url = f"https://www.tiktok.com/@{username}/video/{post_id}"

        return {
            "id": post_id,
            "url": url,
            "description": (
                entry.get("title")
                or entry.get("description")
                or ""
            ),
            "thumbnail": entry.get("thumbnail")
        }

    return None


async def check_tiktok_post(host):
    username = host["target"].lstrip("@")

    try:
        latest = await asyncio.wait_for(
            asyncio.to_thread(
                _latest_tiktok_post_sync,
                username
            ),
            timeout=35
        )
    except asyncio.TimeoutError:
        raise RuntimeError(f"Timeout TikTok post @{username}")

    if not latest:
        return

    state = get_tiktok_post_state(
        host["guild_id"],
        username
    )

    if not state or not state["initialized"]:
        update_tiktok_post_state(
            host["guild_id"],
            username,
            latest["id"]
        )
        return

    if latest["id"] == state["last_post_id"]:
        return

    description = (latest.get("description") or "").strip()

    if len(description) > 700:
        description = description[:697] + "..."

    embed = discord.Embed(
        title="🆕 TikTok Post Baru",
        description=(
            f"**@{username}** mengunggah postingan baru."
            + (f"\n\n{description}" if description else "")
        ),
        url=latest["url"],
        color=discord.Color.from_rgb(0, 170, 255)
    )

    if latest.get("thumbnail"):
        embed.set_image(url=latest["thumbnail"])

    custom = render_template(
        host["custom_post_message"],
        creator=f"@{username}",
        url=latest["url"],
        platform="TikTok"
    )

    await send_notification(host, embed, custom)

    update_tiktok_post_state(
        host["guild_id"],
        username,
        latest["id"]
    )


# ============================================================
# MONITOR
# ============================================================

def host_due(host, now: int) -> bool:
    if host["cooldown_until"] and now < int(host["cooldown_until"]):
        return False

    last = int(host["last_check"] or 0)
    interval = int(host["check_interval"] or DEFAULT_CHECK_INTERVAL)

    return now - last >= interval


@tasks.loop(seconds=BASE_MONITOR_TICK)
async def monitor_loop():
    now = int(time.time())

    for host in get_enabled_hosts():
        if not host_due(host, now):
            continue

        guild = bot.get_guild(host["guild_id"])

        if guild is None:
            continue

        if not guild_access_allowed(guild.id):
            set_host_health(
                host["id"],
                "Server diblacklist oleh Global Owner."
            )
            continue

        if REQUIRED_GUILD_ID and not await guild_owner_verified(guild):
            set_host_health(
                host["id"],
                "Owner server belum join Discord Owner/Support."
            )
            continue

        try:
            if host["platform"] == "youtube":
                await check_youtube_live(host)
                set_host_health(host["id"], success=True)

            elif host["platform"] == "tiktok":
                errors = []

                for label, checker in [
                    ("LIVE", check_tiktok_live),
                    ("POST", check_tiktok_post),
                ]:
                    try:
                        await checker(host)
                    except Exception as exc:
                        errors.append(f"{label}: {exc}")

                if errors:
                    set_host_health(
                        host["id"],
                        " | ".join(errors)
                    )
                else:
                    set_host_health(
                        host["id"],
                        success=True
                    )

        except Exception as exc:
            set_host_health(
                host["id"],
                str(exc)
            )
            log.exception(
                "Checker gagal host_id=%s",
                host["id"]
            )

        await asyncio.sleep(1)


@monitor_loop.before_loop
async def before_monitor():
    await bot.wait_until_ready()


# ============================================================
# BACKUP / RESTORE
# ============================================================

def export_guild_backup(guild_id: int) -> dict:
    cfg = dict(get_config(guild_id))
    settings = dict(get_guild_settings(guild_id))
    hosts = [dict(x) for x in get_hosts(guild_id)]

    # Runtime-only fields do not need restore.
    for host in hosts:
        for key in [
            "id",
            "last_check",
            "last_error",
            "error_count",
            "cooldown_until"
        ]:
            host.pop(key, None)

    return {
        "version": 4,
        "guild_id": guild_id,
        "guild_config": cfg,
        "guild_settings": settings,
        "hosts": hosts,
    }


def restore_guild_backup(data: dict, target_guild_id: int):
    if not isinstance(data, dict):
        raise ValueError("Backup JSON tidak valid.")

    cfg = data.get("guild_config") or {}
    settings = data.get("guild_settings") or {}
    hosts = data.get("hosts") or []

    ensure_guild(target_guild_id)

    set_default_channel(
        target_guild_id,
        "youtube",
        cfg.get("youtube_channel_id")
    )
    set_default_channel(
        target_guild_id,
        "tiktok",
        cfg.get("tiktok_channel_id")
    )
    set_default_role(
        target_guild_id,
        cfg.get("mention_role_id")
    )
    set_log_channel(
        target_guild_id,
        cfg.get("log_channel_id")
    )

    set_plan(
        target_guild_id,
        settings.get("plan", "free")
    )
    set_access_state(
        target_guild_id,
        settings.get("access_state", "allowed")
    )

    restored = 0

    for raw in hosts:
        if raw.get("platform") not in {"tiktok", "youtube"}:
            continue

        target = str(raw.get("target") or "").strip()
        if not target:
            continue

        try:
            add_host(
                target_guild_id,
                raw["platform"],
                target,
                raw.get("display_name"),
                raw.get("extra")
            )
        except ValueError:
            break

        with closing(db()) as conn:
            row = conn.execute("""
                SELECT id FROM hosts
                WHERE guild_id=? AND platform=? AND target=?
            """, (
                target_guild_id,
                raw["platform"],
                target
            )).fetchone()

        if row:
            host_id = row["id"]
            set_host_channel(host_id, raw.get("channel_id"))
            set_host_role(host_id, raw.get("role_id"))
            set_host_interval(
                host_id,
                int(raw.get("check_interval") or DEFAULT_CHECK_INTERVAL)
            )
            set_host_notify_end(
                host_id,
                bool(raw.get("notify_live_end"))
            )

            with closing(db()) as conn:
                conn.execute("""
                    UPDATE hosts SET
                        custom_live_message=?,
                        custom_post_message=?,
                        custom_end_message=?,
                        enabled=?
                    WHERE id=?
                """, (
                    raw.get("custom_live_message"),
                    raw.get("custom_post_message"),
                    raw.get("custom_end_message"),
                    1 if raw.get("enabled", 1) else 0,
                    host_id
                ))
                conn.commit()

            restored += 1

    return restored


# ============================================================
# EMBEDS
# ============================================================

def fmt_time(ts: Optional[int]) -> str:
    return f"<t:{int(ts)}:R>" if ts else "Belum pernah"


def owner_home_embed():
    embed = discord.Embed(
        title="🔐 Hi Notifku • Global Owner",
        description=(
            "Semua pengaturan dilakukan **hanya melalui DM bot**.\n"
            "Pilih server yang ingin dikelola."
        ),
        color=discord.Color.blue()
    )

    embed.add_field(
        name="Server",
        value=str(len(bot.guilds)),
        inline=True
    )
    embed.add_field(
        name="Uptime",
        value=f"<t:{STARTED_AT}:R>",
        inline=True
    )
    embed.add_field(
        name="Owner Aktif",
        value=str(len(OWNER_IDS | db_owner_ids())),
        inline=True
    )

    return embed


def server_embed(guild: discord.Guild):
    cfg = get_config(guild.id)
    settings = get_guild_settings(guild.id)
    hosts = get_hosts(guild.id)

    embed = discord.Embed(
        title="🔔 Hi Notifku",
        description=f"Server: **{guild.name}**",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="Plan",
        value=settings["plan"].upper(),
        inline=True
    )
    embed.add_field(
        name="Host",
        value=f"{len(hosts)}/{host_limit_for_guild(guild.id)}",
        inline=True
    )
    embed.add_field(
        name="Access",
        value=settings["access_state"],
        inline=True
    )

    embed.add_field(
        name="TikTok Channel",
        value=(
            f"<#{cfg['tiktok_channel_id']}>"
            if cfg["tiktok_channel_id"]
            else "Belum diatur"
        ),
        inline=False
    )
    embed.add_field(
        name="YouTube Channel",
        value=(
            f"<#{cfg['youtube_channel_id']}>"
            if cfg["youtube_channel_id"]
            else "Belum diatur"
        ),
        inline=False
    )
    embed.add_field(
        name="Mention Role",
        value=(
            f"<@&{cfg['mention_role_id']}>"
            if cfg["mention_role_id"]
            else "Tidak ada"
        ),
        inline=False
    )
    embed.add_field(
        name="Log Channel",
        value=(
            f"<#{cfg['log_channel_id']}>"
            if cfg["log_channel_id"]
            else "Belum diatur"
        ),
        inline=False
    )

    return embed


def host_embed(host):
    platform_name = "TikTok" if host["platform"] == "tiktok" else "YouTube"

    embed = discord.Embed(
        title=f"{'🎵' if host['platform']=='tiktok' else '📺'} {platform_name} Host",
        color=discord.Color.green() if host["enabled"] else discord.Color.dark_gray()
    )

    embed.add_field(
        name="Target",
        value=f"`{host['target']}`",
        inline=False
    )
    embed.add_field(
        name="Status",
        value="🟢 Running" if host["enabled"] else "⏸️ Paused",
        inline=True
    )
    embed.add_field(
        name="Interval",
        value=f"{host['check_interval']} detik",
        inline=True
    )
    embed.add_field(
        name="Live End",
        value="ON" if host["notify_live_end"] else "OFF",
        inline=True
    )
    embed.add_field(
        name="Last Check",
        value=fmt_time(host["last_check"]),
        inline=True
    )
    embed.add_field(
        name="Error Count",
        value=str(host["error_count"] or 0),
        inline=True
    )
    embed.add_field(
        name="Cooldown",
        value=fmt_time(host["cooldown_until"]) if host["cooldown_until"] else "Tidak",
        inline=True
    )
    embed.add_field(
        name="Channel Khusus",
        value=f"<#{host['channel_id']}>" if host["channel_id"] else "Pakai default",
        inline=False
    )
    embed.add_field(
        name="Role Khusus",
        value=f"<@&{host['role_id']}>" if host["role_id"] else "Pakai default",
        inline=False
    )

    if host["last_error"]:
        embed.add_field(
            name="⚠️ Error Terakhir",
            value=host["last_error"][:900],
            inline=False
        )

    embed.set_footer(text=f"Host ID: {host['id']}")
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
        placeholder="TikTok: username | YouTube: UC...",
        max_length=120
    )

    def __init__(self, guild_id: int):
        super().__init__(title="Tambah Host", timeout=300)
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        platform = self.platform.value.strip().lower()
        target = self.target.value.strip()

        if platform not in {"tiktok", "youtube"}:
            await safe_reply(
                interaction,
                "❌ Platform harus `tiktok` atau `youtube`."
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
                await safe_reply(
                    interaction,
                    "❌ Username TikTok tidak valid."
                )
                return

            try:
                add_host(
                    self.guild_id,
                    "tiktok",
                    username,
                    f"@{username}"
                )
            except ValueError as exc:
                await safe_reply(interaction, f"❌ {exc}")
                return

            await log_action(
                self.guild_id,
                interaction.user.id,
                "Tambah Host",
                f"TikTok @{username}"
            )

            await safe_reply(
                interaction,
                f"✅ TikTok **@{username}** ditambahkan."
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

            await log_action(
                self.guild_id,
                interaction.user.id,
                "Tambah Host",
                f"YouTube {name} ({target})"
            )

            await interaction.followup.send(
                f"✅ YouTube **{name}** ditambahkan.",
                ephemeral=True
            )
        except Exception as exc:
            await interaction.followup.send(
                f"❌ `{exc}`",
                ephemeral=True
            )


class BulkImportModal(discord.ui.Modal):
    data = discord.ui.TextInput(
        label="Daftar Host",
        placeholder=(
            "tiktok,username1\n"
            "tiktok,username2\n"
            "youtube,UCxxxxxxxx"
        ),
        style=discord.TextStyle.paragraph,
        max_length=4000
    )

    def __init__(self, guild_id: int):
        super().__init__(title="Import Host Massal", timeout=300)
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        added = 0
        errors = []

        for line in self.data.value.splitlines():
            line = line.strip()
            if not line:
                continue

            if "," not in line:
                errors.append(f"`{line}` → format salah")
                continue

            platform, target = [
                x.strip()
                for x in line.split(",", 1)
            ]

            platform = platform.lower()

            try:
                if platform == "tiktok":
                    username = target.lstrip("@")
                    add_host(
                        self.guild_id,
                        "tiktok",
                        username,
                        f"@{username}"
                    )
                    added += 1

                elif platform == "youtube":
                    name, uploads = await resolve_youtube_channel(target)
                    add_host(
                        self.guild_id,
                        "youtube",
                        target,
                        name,
                        uploads
                    )
                    added += 1

                else:
                    errors.append(f"`{line}` → platform tidak valid")

            except Exception as exc:
                errors.append(f"`{line}` → {exc}")

        await log_action(
            self.guild_id,
            interaction.user.id,
            "Import Host Massal",
            f"Berhasil: {added}, gagal: {len(errors)}"
        )

        message = f"✅ Berhasil menambahkan **{added} host**."

        if errors:
            message += "\n\n⚠️ Gagal:\n" + "\n".join(errors[:10])

        await interaction.followup.send(
            message[:1900],
            ephemeral=True
        )


class IdModal(discord.ui.Modal):
    value_input = discord.ui.TextInput(
        label="ID Discord",
        placeholder="Masukkan ID angka",
        max_length=25
    )

    def __init__(
        self,
        title: str,
        kind: str,
        guild_id: int,
        host_id: Optional[int] = None
    ):
        super().__init__(title=title, timeout=300)
        self.kind = kind
        self.guild_id = guild_id
        self.host_id = host_id

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.value_input.value.strip()

        if not raw.isdigit():
            await safe_reply(
                interaction,
                "❌ ID harus berupa angka."
            )
            return

        value = int(raw)
        guild = bot.get_guild(self.guild_id)

        if not guild:
            await safe_reply(
                interaction,
                "❌ Server tidak ditemukan."
            )
            return

        channel_kinds = {
            "default_tiktok_channel",
            "default_youtube_channel",
            "host_channel",
            "log_channel"
        }

        if self.kind in channel_kinds:
            channel = guild.get_channel(value)

            if not isinstance(channel, discord.TextChannel):
                await safe_reply(
                    interaction,
                    "❌ ID bukan text channel server tersebut."
                )
                return

            perms = channel.permissions_for(guild.me)

            if not (
                perms.view_channel
                and perms.send_messages
                and perms.embed_links
            ):
                await safe_reply(
                    interaction,
                    "❌ Bot perlu View Channel + Send Messages + Embed Links."
                )
                return

            if self.kind == "default_tiktok_channel":
                set_default_channel(self.guild_id, "tiktok", value)
            elif self.kind == "default_youtube_channel":
                set_default_channel(self.guild_id, "youtube", value)
            elif self.kind == "host_channel":
                set_host_channel(self.host_id, value)
            elif self.kind == "log_channel":
                set_log_channel(self.guild_id, value)

            await log_action(
                self.guild_id,
                interaction.user.id,
                "Ubah Channel",
                f"{self.kind} → {value}"
            )

            await safe_reply(
                interaction,
                f"✅ Channel diatur ke <#{value}>."
            )
            return

        if self.kind in {"default_role", "host_role"}:
            role = guild.get_role(value)

            if not role:
                await safe_reply(
                    interaction,
                    "❌ Role tidak ditemukan."
                )
                return

            if self.kind == "default_role":
                set_default_role(self.guild_id, value)
            else:
                set_host_role(self.host_id, value)

            await log_action(
                self.guild_id,
                interaction.user.id,
                "Ubah Role",
                f"{self.kind} → {role.name}"
            )

            await safe_reply(
                interaction,
                f"✅ Role diatur ke **{role.name}**."
            )


class IntervalModal(discord.ui.Modal):
    seconds = discord.ui.TextInput(
        label="Interval detik",
        placeholder="60 - 3600",
        max_length=4
    )

    def __init__(self, guild_id: int, host_id: int):
        super().__init__(title="Interval Host", timeout=300)
        self.guild_id = guild_id
        self.host_id = host_id

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.seconds.value.strip()

        if not raw.isdigit():
            await safe_reply(
                interaction,
                "❌ Interval harus angka."
            )
            return

        seconds = max(60, min(3600, int(raw)))
        set_host_interval(self.host_id, seconds)

        await log_action(
            self.guild_id,
            interaction.user.id,
            "Ubah Interval",
            f"Host {self.host_id} → {seconds} detik"
        )

        await safe_reply(
            interaction,
            f"✅ Interval host = **{seconds} detik**."
        )


class CustomMessageModal(discord.ui.Modal):
    live = discord.ui.TextInput(
        label="Pesan LIVE",
        placeholder="{creator} sedang LIVE! {url}",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=1000
    )
    post = discord.ui.TextInput(
        label="Pesan Post Baru",
        placeholder="{creator} upload baru! {url}",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=1000
    )
    ended = discord.ui.TextInput(
        label="Pesan LIVE selesai",
        placeholder="LIVE {creator} sudah selesai.",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=1000
    )

    def __init__(self, guild_id: int, host_id: int):
        super().__init__(title="Custom Pesan Host", timeout=300)
        self.guild_id = guild_id
        self.host_id = host_id

    async def on_submit(self, interaction: discord.Interaction):
        set_host_messages(
            self.host_id,
            self.live.value.strip() or None,
            self.post.value.strip() or None,
            self.ended.value.strip() or None
        )

        await log_action(
            self.guild_id,
            interaction.user.id,
            "Custom Pesan",
            f"Host {self.host_id} diperbarui."
        )

        await safe_reply(
            interaction,
            "✅ Custom pesan tersimpan.\nPlaceholder: `{creator}`, `{url}`, `{platform}`."
        )


class OwnerIdModal(discord.ui.Modal):
    user_id = discord.ui.TextInput(
        label="Discord User ID",
        placeholder="123456789012345678",
        max_length=25
    )

    def __init__(self, action: str):
        super().__init__(
            title="Tambah Owner" if action == "add" else "Hapus Owner",
            timeout=300
        )
        self.action = action

    async def on_submit(self, interaction: discord.Interaction):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(
                interaction,
                "❌ Hanya OWNER_IDS utama yang boleh mengubah owner tambahan."
            )
            return

        raw = self.user_id.value.strip()

        if not raw.isdigit():
            await safe_reply(interaction, "❌ User ID harus angka.")
            return

        user_id = int(raw)

        if self.action == "add":
            add_db_owner(user_id, interaction.user.id)
            await safe_reply(
                interaction,
                f"✅ <@{user_id}> ditambahkan sebagai Global Owner tambahan."
            )
        else:
            if user_id in OWNER_IDS:
                await safe_reply(
                    interaction,
                    "❌ OWNER_IDS utama tidak dapat dihapus dari panel."
                )
                return

            remove_db_owner(user_id)
            await safe_reply(
                interaction,
                f"✅ Owner tambahan `{user_id}` dihapus."
            )


# ============================================================
# SELECTS / VIEWS
# ============================================================

class GuildSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=g.name[:100],
                value=str(g.id),
                description=f"ID: {g.id}"[:100]
            )
            for g in bot.guilds[:25]
        ]

        if not options:
            options = [
                discord.SelectOption(
                    label="Tidak ada server",
                    value="0"
                )
            ]

        super().__init__(
            placeholder="Pilih server...",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return

        guild = bot.get_guild(int(self.values[0]))

        if not guild:
            await safe_reply(
                interaction,
                "❌ Server tidak ditemukan."
            )
            return

        await interaction.response.edit_message(
            embed=server_embed(guild),
            view=ServerOwnerView(guild.id)
        )


class OwnerHomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)
        self.add_item(GuildSelect())

    @discord.ui.button(
        label="Health Bot",
        emoji="🩺",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def health(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_global_owner(interaction):
            return

        hosts = []
        for guild in bot.guilds:
            hosts.extend(get_hosts(guild.id))

        error_hosts = sum(1 for h in hosts if h["last_error"])
        paused = sum(1 for h in hosts if not h["enabled"])

        embed = discord.Embed(
            title="🩺 Hi Notifku Health",
            color=discord.Color.green()
        )

        embed.add_field(
            name="Discord",
            value=f"✅ {round(bot.latency * 1000)} ms",
            inline=True
        )
        embed.add_field(
            name="Uptime",
            value=f"<t:{STARTED_AT}:R>",
            inline=True
        )
        embed.add_field(
            name="Servers",
            value=str(len(bot.guilds)),
            inline=True
        )
        embed.add_field(
            name="Hosts",
            value=str(len(hosts)),
            inline=True
        )
        embed.add_field(
            name="Paused",
            value=str(paused),
            inline=True
        )
        embed.add_field(
            name="With Errors",
            value=str(error_hosts),
            inline=True
        )
        embed.add_field(
            name="YouTube API",
            value="✅ Loaded" if YOUTUBE_API_KEY else "⚠️ Empty",
            inline=True
        )
        embed.add_field(
            name="Database",
            value=f"`{DB_PATH}`",
            inline=False
        )

        await interaction.response.edit_message(
            embed=embed,
            view=BackHomeView()
        )

    @discord.ui.button(
        label="Kelola Owner",
        emoji="👑",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def owners(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(
                interaction,
                "❌ Hanya OWNER_IDS utama yang dapat membuka menu ini."
            )
            return

        all_owners = OWNER_IDS | db_owner_ids()

        embed = discord.Embed(
            title="👑 Global Owners",
            description="\n".join(f"• <@{x}> (`{x}`)" for x in sorted(all_owners)) or "Tidak ada",
            color=discord.Color.gold()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=OwnerManagementView()
        )


class BackHomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class OwnerManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(
        label="Tambah Owner",
        emoji="➕",
        style=discord.ButtonStyle.success
    )
    async def add_owner(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            OwnerIdModal("add")
        )

    @discord.ui.button(
        label="Hapus Owner",
        emoji="➖",
        style=discord.ButtonStyle.danger
    )
    async def remove_owner(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            OwnerIdModal("remove")
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class ServerOwnerView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id

    @discord.ui.button(label="Kelola Host", emoji="👤", style=discord.ButtonStyle.primary, row=0)
    async def hosts(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)
        if not guild:
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="👤 Kelola Host",
                description=f"Server: **{guild.name}**",
                color=discord.Color.blue()
            ),
            view=HostMenuView(self.guild_id)
        )

    @discord.ui.button(label="Default Notif", emoji="📣", style=discord.ButtonStyle.primary, row=0)
    async def defaults(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="📣 Default Notifikasi",
                description="Dipakai oleh host yang tidak memiliki channel/role khusus.",
                color=discord.Color.blue()
            ),
            view=DefaultConfigView(self.guild_id)
        )

    @discord.ui.button(label="Setup Wizard", emoji="🪄", style=discord.ButtonStyle.success, row=0)
    async def wizard(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)
        cfg = get_config(self.guild_id)
        hosts = get_hosts(self.guild_id)

        embed = discord.Embed(
            title="🪄 Setup Wizard",
            description=f"Server: **{guild.name if guild else self.guild_id}**",
            color=discord.Color.green()
        )

        embed.add_field(
            name="1. TikTok Channel",
            value="✅" if cfg["tiktok_channel_id"] else "❌ Belum",
            inline=True
        )
        embed.add_field(
            name="2. YouTube Channel",
            value="✅" if cfg["youtube_channel_id"] else "❌ Belum",
            inline=True
        )
        embed.add_field(
            name="3. Mention Role",
            value="✅" if cfg["mention_role_id"] else "➖ Opsional",
            inline=True
        )
        embed.add_field(
            name="4. Host Pertama",
            value="✅" if hosts else "❌ Belum",
            inline=True
        )

        await interaction.response.edit_message(
            embed=embed,
            view=WizardView(self.guild_id)
        )

    @discord.ui.button(label="Server Access", emoji="🔐", style=discord.ButtonStyle.secondary, row=1)
    async def access(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=server_embed(bot.get_guild(self.guild_id)),
            view=ServerAccessView(self.guild_id)
        )

    @discord.ui.button(label="Backup", emoji="💾", style=discord.ButtonStyle.secondary, row=1)
    async def backup(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = export_guild_backup(self.guild_id)
        payload = json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ).encode("utf-8")

        file = discord.File(
            io.BytesIO(payload),
            filename=f"hi-notifku-backup-{self.guild_id}.json"
        )

        await interaction.response.send_message(
            "✅ Backup dibuat. Untuk restore, kirim file JSON ini kembali lewat DM bot.",
            file=file,
            ephemeral=True
        )

    @discord.ui.button(label="Activity", emoji="🧾", style=discord.ButtonStyle.secondary, row=1)
    async def activity(self, interaction: discord.Interaction, button: discord.ui.Button):
        rows = recent_activity(self.guild_id, 10)

        text = "\n".join(
            f"• <t:{r['created_at']}:R> — **{r['action']}** — {r['detail']}"
            for r in rows
        ) or "Belum ada activity."

        embed = discord.Embed(
            title="🧾 Activity Terakhir",
            description=text[:4000],
            color=discord.Color.dark_gray()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=ServerOwnerView(self.guild_id)
        )

    @discord.ui.button(label="Verifikasi Join", emoji="✅", style=discord.ButtonStyle.secondary, row=2)
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)

        if not guild:
            return

        if await guild_owner_verified(guild):
            await safe_reply(
                interaction,
                "✅ Owner server sudah join Discord Owner/Support."
            )
        else:
            await safe_reply(
                interaction,
                required_join_text()
            )

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)
        if guild:
            await interaction.response.edit_message(
                embed=server_embed(guild),
                view=ServerOwnerView(self.guild_id)
            )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=2)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class ServerAccessView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id

    @discord.ui.button(label="Free", style=discord.ButtonStyle.secondary)
    async def free(self, interaction: discord.Interaction, button: discord.ui.Button):
        set_plan(self.guild_id, "free")
        await log_action(
            self.guild_id,
            interaction.user.id,
            "Ubah Plan",
            "Plan → FREE"
        )
        await safe_reply(interaction, "✅ Plan FREE aktif.")

    @discord.ui.button(label="Premium", emoji="⭐", style=discord.ButtonStyle.success)
    async def premium(self, interaction: discord.Interaction, button: discord.ui.Button):
        set_plan(self.guild_id, "premium")
        await log_action(
            self.guild_id,
            interaction.user.id,
            "Ubah Plan",
            "Plan → PREMIUM"
        )
        await safe_reply(interaction, "✅ Plan PREMIUM aktif.")

    @discord.ui.button(label="Blacklist", emoji="🚫", style=discord.ButtonStyle.danger)
    async def blacklist(self, interaction: discord.Interaction, button: discord.ui.Button):
        set_access_state(self.guild_id, "blacklist")
        await log_action(
            self.guild_id,
            interaction.user.id,
            "Server Access",
            "BLACKLIST"
        )
        await safe_reply(interaction, "🚫 Server diblacklist.")

    @discord.ui.button(label="Whitelist", emoji="✅", style=discord.ButtonStyle.success)
    async def whitelist(self, interaction: discord.Interaction, button: discord.ui.Button):
        set_access_state(self.guild_id, "whitelist")
        await log_action(
            self.guild_id,
            interaction.user.id,
            "Server Access",
            "WHITELIST"
        )
        await safe_reply(interaction, "✅ Server ditandai whitelist.")

    @discord.ui.button(label="Allowed Normal", style=discord.ButtonStyle.secondary)
    async def normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        set_access_state(self.guild_id, "allowed")
        await safe_reply(interaction, "✅ Access kembali normal.")

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)
        if guild:
            await interaction.response.edit_message(
                embed=server_embed(guild),
                view=ServerOwnerView(self.guild_id)
            )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class HostMenuView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id

    @discord.ui.button(label="Tambah Host", emoji="➕", style=discord.ButtonStyle.success)
    async def add_host_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            AddHostModal(self.guild_id)
        )

    @discord.ui.button(label="Import Massal", emoji="📥", style=discord.ButtonStyle.success)
    async def bulk(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            BulkImportModal(self.guild_id)
        )

    @discord.ui.button(label="Daftar Host", emoji="📋", style=discord.ButtonStyle.primary)
    async def list_hosts_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        rows = get_hosts(self.guild_id)

        if not rows:
            await safe_reply(interaction, "Belum ada host.")
            return

        await safe_reply(
            interaction,
            f"📋 Menampilkan **{len(rows)} host**."
        )

        for host in rows:
            await interaction.channel.send(
                embed=host_embed(host),
                view=HostCardView(self.guild_id, host["id"])
            )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)
        if guild:
            await interaction.response.edit_message(
                embed=server_embed(guild),
                view=ServerOwnerView(self.guild_id)
            )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class DefaultConfigView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id

    @discord.ui.button(label="TikTok Channel", emoji="🎵", style=discord.ButtonStyle.primary)
    async def tt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            IdModal(
                "Default TikTok Channel",
                "default_tiktok_channel",
                self.guild_id
            )
        )

    @discord.ui.button(label="YouTube Channel", emoji="📺", style=discord.ButtonStyle.primary)
    async def yt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            IdModal(
                "Default YouTube Channel",
                "default_youtube_channel",
                self.guild_id
            )
        )

    @discord.ui.button(label="Mention Role", emoji="🔔", style=discord.ButtonStyle.secondary)
    async def role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            IdModal(
                "Default Mention Role",
                "default_role",
                self.guild_id
            )
        )

    @discord.ui.button(label="Log Channel", emoji="🧾", style=discord.ButtonStyle.secondary)
    async def logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            IdModal(
                "Activity Log Channel",
                "log_channel",
                self.guild_id
            )
        )

    @discord.ui.button(label="Matikan Role", emoji="🔕", style=discord.ButtonStyle.secondary)
    async def role_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        set_default_role(self.guild_id, None)
        await safe_reply(interaction, "✅ Default role dimatikan.")

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)
        if guild:
            await interaction.response.edit_message(
                embed=server_embed(guild),
                view=ServerOwnerView(self.guild_id)
            )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class WizardView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id

    @discord.ui.button(label="1. TikTok Channel", emoji="🎵", style=discord.ButtonStyle.primary)
    async def tt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            IdModal(
                "Wizard • TikTok Channel",
                "default_tiktok_channel",
                self.guild_id
            )
        )

    @discord.ui.button(label="2. YouTube Channel", emoji="📺", style=discord.ButtonStyle.primary)
    async def yt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            IdModal(
                "Wizard • YouTube Channel",
                "default_youtube_channel",
                self.guild_id
            )
        )

    @discord.ui.button(label="3. Mention Role", emoji="🔔", style=discord.ButtonStyle.secondary)
    async def role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            IdModal(
                "Wizard • Mention Role",
                "default_role",
                self.guild_id
            )
        )

    @discord.ui.button(label="4. Tambah Host", emoji="➕", style=discord.ButtonStyle.success)
    async def host(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            AddHostModal(self.guild_id)
        )

    @discord.ui.button(label="Selesai", emoji="✅", style=discord.ButtonStyle.success, row=1)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)
        if guild:
            await interaction.response.edit_message(
                embed=server_embed(guild),
                view=ServerOwnerView(self.guild_id)
            )


class HostCardView(discord.ui.View):
    def __init__(self, guild_id: int, host_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id
        self.host_id = host_id

        host = get_host(host_id)

        if host:
            if host["platform"] == "tiktok":
                b1 = discord.ui.Button(
                    label="Test LIVE",
                    emoji="🧪",
                    style=discord.ButtonStyle.success,
                    row=0
                )
                b1.callback = self.test_tiktok_live
                self.add_item(b1)

                b2 = discord.ui.Button(
                    label="Test Post",
                    emoji="🆕",
                    style=discord.ButtonStyle.success,
                    row=0
                )
                b2.callback = self.test_tiktok_post
                self.add_item(b2)
            else:
                b1 = discord.ui.Button(
                    label="Test LIVE",
                    emoji="🧪",
                    style=discord.ButtonStyle.success,
                    row=0
                )
                b1.callback = self.test_youtube_live
                self.add_item(b1)

        specs = [
            ("Custom Pesan", "✏️", discord.ButtonStyle.primary, 1, self.custom_messages),
            ("Interval", "⏱️", discord.ButtonStyle.secondary, 1, self.interval),
            ("Live End ON/OFF", "⚫", discord.ButtonStyle.secondary, 1, self.toggle_end),
            ("Channel Host", "📣", discord.ButtonStyle.secondary, 2, self.channel),
            ("Role Host", "🔔", discord.ButtonStyle.secondary, 2, self.role),
            ("Pakai Default", "♻️", discord.ButtonStyle.secondary, 2, self.reset_defaults),
            ("Pause / Resume", "⏯️", discord.ButtonStyle.secondary, 3, self.toggle),
            ("Clear Pesan", "🧹", discord.ButtonStyle.secondary, 3, self.clear_messages),
            ("Hapus", "🗑️", discord.ButtonStyle.danger, 3, self.delete),
            ("Kembali", "⬅️", discord.ButtonStyle.secondary, 4, self.back),
            ("Menu Awal", "🏠", discord.ButtonStyle.secondary, 4, self.home),
        ]

        for label, emoji, style, row, callback in specs:
            button = discord.ui.Button(
                label=label,
                emoji=emoji,
                style=style,
                row=row
            )
            button.callback = callback
            self.add_item(button)

    async def valid_host(self, interaction):
        if not await require_global_owner(interaction):
            return None

        host = get_host(self.host_id)

        if not host or host["guild_id"] != self.guild_id:
            await safe_reply(
                interaction,
                "❌ Host tidak ditemukan."
            )
            return None

        return host

    async def test_tiktok_live(self, interaction):
        host = await self.valid_host(interaction)
        if not host:
            return

        url = f"https://www.tiktok.com/@{host['target']}/live"

        embed = discord.Embed(
            title="🔴 TikTok LIVE • TEST",
            description=f"**@{host['target']}** sedang LIVE!",
            url=url,
            color=discord.Color.from_rgb(0, 170, 255)
        )

        custom = render_template(
            host["custom_live_message"],
            creator=f"@{host['target']}",
            url=url,
            platform="TikTok"
        )

        ok = await send_notification(host, embed, custom)

        await safe_reply(
            interaction,
            "✅ Test LIVE dikirim." if ok else "❌ Gagal kirim."
        )

    async def test_tiktok_post(self, interaction):
        host = await self.valid_host(interaction)
        if not host:
            return

        url = f"https://www.tiktok.com/@{host['target']}"

        embed = discord.Embed(
            title="🆕 TikTok Post • TEST",
            description=f"Contoh post baru dari **@{host['target']}**.",
            url=url,
            color=discord.Color.from_rgb(0, 170, 255)
        )

        custom = render_template(
            host["custom_post_message"],
            creator=f"@{host['target']}",
            url=url,
            platform="TikTok"
        )

        ok = await send_notification(host, embed, custom)

        await safe_reply(
            interaction,
            "✅ Test Post dikirim." if ok else "❌ Gagal kirim."
        )

    async def test_youtube_live(self, interaction):
        host = await self.valid_host(interaction)
        if not host:
            return

        url = "https://www.youtube.com/"

        embed = discord.Embed(
            title="🔴 YouTube LIVE • TEST",
            description=f"**{host['display_name'] or host['target']}** sedang LIVE!",
            url=url,
            color=discord.Color.red()
        )

        custom = render_template(
            host["custom_live_message"],
            creator=host["display_name"] or host["target"],
            url=url,
            platform="YouTube"
        )

        ok = await send_notification(host, embed, custom)

        await safe_reply(
            interaction,
            "✅ Test LIVE dikirim." if ok else "❌ Gagal kirim."
        )

    async def custom_messages(self, interaction):
        host = await self.valid_host(interaction)
        if host:
            await interaction.response.send_modal(
                CustomMessageModal(
                    self.guild_id,
                    self.host_id
                )
            )

    async def interval(self, interaction):
        host = await self.valid_host(interaction)
        if host:
            await interaction.response.send_modal(
                IntervalModal(
                    self.guild_id,
                    self.host_id
                )
            )

    async def toggle_end(self, interaction):
        host = await self.valid_host(interaction)
        if not host:
            return

        enabled = not bool(host["notify_live_end"])
        set_host_notify_end(
            self.host_id,
            enabled
        )

        await log_action(
            self.guild_id,
            interaction.user.id,
            "Live End",
            f"Host {self.host_id} → {'ON' if enabled else 'OFF'}"
        )

        await safe_reply(
            interaction,
            f"✅ Notifikasi LIVE selesai **{'ON' if enabled else 'OFF'}**."
        )

    async def channel(self, interaction):
        host = await self.valid_host(interaction)
        if host:
            await interaction.response.send_modal(
                IdModal(
                    "Channel Khusus Host",
                    "host_channel",
                    self.guild_id,
                    self.host_id
                )
            )

    async def role(self, interaction):
        host = await self.valid_host(interaction)
        if host:
            await interaction.response.send_modal(
                IdModal(
                    "Role Khusus Host",
                    "host_role",
                    self.guild_id,
                    self.host_id
                )
            )

    async def reset_defaults(self, interaction):
        host = await self.valid_host(interaction)
        if not host:
            return

        set_host_channel(self.host_id, None)
        set_host_role(self.host_id, None)

        await safe_reply(
            interaction,
            "✅ Host kembali memakai default channel & role."
        )

    async def toggle(self, interaction):
        host = await self.valid_host(interaction)
        if not host:
            return

        enabled = toggle_host(self.host_id)

        await safe_reply(
            interaction,
            "✅ Host Running." if enabled else "⏸️ Host Paused."
        )

    async def clear_messages(self, interaction):
        host = await self.valid_host(interaction)
        if not host:
            return

        clear_host_messages(self.host_id)

        await safe_reply(
            interaction,
            "✅ Custom pesan dihapus."
        )

    async def delete(self, interaction):
        host = await self.valid_host(interaction)
        if not host:
            return

        delete_host(self.host_id)

        await log_action(
            self.guild_id,
            interaction.user.id,
            "Hapus Host",
            f"{host['platform']} {host['target']}"
        )

        await safe_reply(
            interaction,
            "🗑️ Host dihapus."
        )

        try:
            await interaction.message.delete()
        except Exception:
            pass

    async def back(self, interaction):
        guild = bot.get_guild(self.guild_id)

        if guild:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="👤 Kelola Host",
                    description=f"Server: **{guild.name}**",
                    color=discord.Color.blue()
                ),
                view=HostMenuView(self.guild_id)
            )

    async def home(self, interaction):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )



# ============================================================
# ONE GLOBAL SLASH COMMAND
# ============================================================

@bot.tree.command(
    name="menu",
    description="Buka panel lengkap Hi Notifku melalui DM."
)
async def menu_command(interaction: discord.Interaction):
    # Hanya Global Owner yang memiliki akses ke panel lengkap.
    if not is_global_owner(interaction.user.id):
        await safe_reply(
            interaction,
            "🔒 Menu lengkap Hi Notifku hanya dapat digunakan oleh **Global Owner Bot**."
        )
        return

    # Kirim panel lengkap ke DM user.
    try:
        dm = interaction.user.dm_channel
        if dm is None:
            dm = await interaction.user.create_dm()

        await dm.send(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )

        await safe_reply(
            interaction,
            "✅ **Panel lengkap Hi Notifku sudah dikirim ke DM kamu.**\n"
            "Semua pengaturan tetap dilakukan melalui DM."
        )

    except discord.Forbidden:
        await safe_reply(
            interaction,
            "❌ Saya tidak bisa mengirim DM ke akunmu.\n"
            "Aktifkan DM dari member server, lalu jalankan `/menu` lagi."
        )

    except Exception as exc:
        log.exception("/menu error")
        await safe_reply(
            interaction,
            f"❌ Gagal membuka menu: `{type(exc).__name__}: {exc}`"
        )


# ============================================================
# DM / SERVER EVENTS
# ============================================================

async def handle_backup_attachment(message: discord.Message) -> bool:
    if not message.attachments:
        return False

    json_attachment = next(
        (
            a
            for a in message.attachments
            if a.filename.lower().endswith(".json")
        ),
        None
    )

    if not json_attachment:
        return False

    try:
        raw = await json_attachment.read()
        data = json.loads(raw.decode("utf-8"))

        guild_id = int(data.get("guild_id", 0))
        guild = bot.get_guild(guild_id)

        if not guild:
            await message.channel.send(
                "❌ Guild ID pada backup tidak ditemukan di bot."
            )
            return True

        restored = restore_guild_backup(
            data,
            guild_id
        )

        await message.channel.send(
            f"✅ Restore selesai untuk **{guild.name}**. Host dipulihkan: **{restored}**."
        )

        await log_action(
            guild_id,
            message.author.id,
            "Restore Backup",
            f"{restored} host dipulihkan."
        )

    except Exception as exc:
        await message.channel.send(
            f"❌ Restore gagal: `{type(exc).__name__}: {exc}`"
        )

    return True


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.guild is None:
        if not is_global_owner(message.author.id):
            try:
                await message.channel.send(
                    "🔒 Panel Hi Notifku hanya untuk Global Owner."
                )
            except Exception:
                pass
            return

        if await handle_backup_attachment(message):
            return

        try:
            await message.channel.send(
                embed=owner_home_embed(),
                view=OwnerHomeView()
            )
        except Exception:
            log.exception("Gagal mengirim DM owner panel")

        return

    # Tidak ada konfigurasi di server.
    # Mention bot diarahkan ke DM.
    bot_mentioned = bot.user is not None and bot.user in message.mentions

    if bot_mentioned:
        try:
            embed = discord.Embed(
                title="📩 Pengaturan Hi Notifku",
                description=(
                    "Semua pengaturan bot dilakukan melalui **DM Hi Notifku**.\n\n"
                    "Buka profil bot → **Message / Kirim Pesan**."
                ),
                color=discord.Color.blue()
            )

            await message.reply(
                embed=embed,
                mention_author=False
            )
        except Exception:
            log.exception("Redirect DM gagal")

        return

    await bot.process_commands(message)


@bot.event
async def on_guild_join(guild: discord.Guild):
    try:
        ensure_guild(guild.id)

        if REQUIRED_GUILD_ID and not await guild_owner_verified(guild):
            channel = guild.system_channel

            if channel is None:
                for candidate in guild.text_channels:
                    perms = candidate.permissions_for(guild.me)
                    if perms.view_channel and perms.send_messages:
                        channel = candidate
                        break

            if channel:
                embed = discord.Embed(
                    title="🔒 Hi Notifku • Verifikasi Wajib",
                    description=(
                        required_join_text()
                        + "\n\n📩 Semua pengaturan dilakukan melalui DM bot."
                    ),
                    color=discord.Color.orange()
                )

                await channel.send(
                    content=f"<@{guild.owner_id}>",
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(users=True)
                )

    except Exception:
        log.exception("on_guild_join error")


@bot.event
async def on_guild_remove(guild: discord.Guild):
    try:
        delete_guild_data(guild.id)
        log.info("Data guild %s dibersihkan.", guild.id)
    except Exception:
        log.exception("Guild cleanup gagal")


@bot.event
async def on_ready():
    global http

    if http is None or http.closed:
        http = aiohttp.ClientSession()

    log.info(
        "Login sebagai %s (%s)",
        bot.user,
        bot.user.id
    )

    # Sync exactly one global slash command: /menu.
    try:
        synced = await bot.tree.sync()
        log.info(
            "Slash commands synced: %s (DM-only mode)",
            len(synced)
        )
    except Exception:
        log.exception("Slash command sync gagal")

    if not monitor_loop.is_running():
        monitor_loop.start()


# ============================================================
# MAIN
# ============================================================

async def main():
    global http

    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN belum diisi.")

    migrate_database()

    try:
        await bot.start(DISCORD_TOKEN)
    finally:
        if http and not http.closed:
            await http.close()


if __name__ == "__main__":
    asyncio.run(main())
