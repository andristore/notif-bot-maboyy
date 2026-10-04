import os
import io
import json
import hashlib
import hmac
import time
import asyncio
import csv
import logging
import platform
import sqlite3
import shutil
import socket
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional

import aiohttp
from aiohttp import web
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from TikTokLive import TikTokLiveClient
from yt_dlp import YoutubeDL

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except Exception:
    AESGCM = None

try:
    from PIL import Image, ImageDraw, ImageStat
except Exception:
    Image = None
    ImageDraw = None
    ImageStat = None

load_dotenv()

# ============================================================
# CONFIG
# ============================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()

APP_VERSION = "1.12.0"
CURRENT_SCHEMA_VERSION = 25
GIT_COMMIT = (
    os.getenv("RAILWAY_GIT_COMMIT_SHA", "")
    or os.getenv("GIT_COMMIT", "")
).strip()
BUILD_ID = (
    os.getenv("RAILWAY_DEPLOYMENT_ID", "")
    or os.getenv("BUILD_ID", "")
).strip()
FULL_BACKUP_HOURS = max(
    6,
    int(os.getenv("FULL_BACKUP_HOURS", "168"))
)
BACKUP_ENCRYPTION_PASSWORD = os.getenv(
    "BACKUP_ENCRYPTION_PASSWORD",
    ""
).strip()

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

FREE_HOST_LIMIT = max(1, int(os.getenv("FREE_HOST_LIMIT", "3")))
PREMIUM_HOST_LIMIT = max(FREE_HOST_LIMIT, int(os.getenv("PREMIUM_HOST_LIMIT", "100")))
PREMIUM_WARNING_DAYS = max(1, int(os.getenv("PREMIUM_WARNING_DAYS", "3")))

MONITOR_CONCURRENCY = max(1, min(20, int(os.getenv("MONITOR_CONCURRENCY", "5"))))
AUTO_BACKUP_HOURS = max(1, int(os.getenv("AUTO_BACKUP_HOURS", "48")))
AUTO_BACKUP_KEEP = max(1, min(30, int(os.getenv("AUTO_BACKUP_KEEP", "7"))))

INVOICE_EXPIRE_MINUTES = max(10, int(os.getenv("INVOICE_EXPIRE_MINUTES", "60")))
PREMIUM_GRACE_HOURS = max(0, int(os.getenv("PREMIUM_GRACE_HOURS", "24")))
USER_RATE_LIMIT_SECONDS = max(2, int(os.getenv("USER_RATE_LIMIT_SECONDS", "5")))
ERROR_ALERT_THRESHOLD = max(2, int(os.getenv("ERROR_ALERT_THRESHOLD", "5")))
AUTO_PAUSE_ERRORS = max(ERROR_ALERT_THRESHOLD, int(os.getenv("AUTO_PAUSE_ERRORS", "20")))
NOTIFICATION_SEND_CONCURRENCY = max(1, min(10, int(os.getenv("NOTIFICATION_SEND_CONCURRENCY", "3"))))
NOTIFICATION_MIN_DELAY_MS = max(0, min(5000, int(os.getenv("NOTIFICATION_MIN_DELAY_MS", "250"))))
EVENT_RETENTION_DAYS = max(7, int(os.getenv("EVENT_RETENTION_DAYS", "30")))
NOTIFICATION_MAX_RETRIES = max(
    1,
    min(10, int(os.getenv("NOTIFICATION_MAX_RETRIES", "3")))
)
NOTIFICATION_RETRY_SECONDS = max(
    15,
    min(3600, int(os.getenv("NOTIFICATION_RETRY_SECONDS", "60")))
)
VERIFICATION_WARNING_DAYS = max(
    1,
    min(14, int(os.getenv("VERIFICATION_WARNING_DAYS", "7")))
)
AUTO_ACTIVATE_VERIFIED_PAYMENTS = os.getenv(
    "AUTO_ACTIVATE_VERIFIED_PAYMENTS",
    "true"
).strip().lower() in {"1", "true", "yes", "on"}

PAYMENT_PROOF_MAX_MB = max(
    2,
    min(20, int(os.getenv("PAYMENT_PROOF_MAX_MB", "10")))
)
PAYMENT_WEBHOOK_ENABLED = os.getenv(
    "PAYMENT_WEBHOOK_ENABLED",
    "false"
).strip().lower() in {"1", "true", "yes", "on"}
PAYMENT_WEBHOOK_SECRET = os.getenv("PAYMENT_WEBHOOK_SECRET", "").strip()
PAYMENT_WEBHOOK_PATH = os.getenv(
    "PAYMENT_WEBHOOK_PATH",
    "/payment/callback"
).strip() or "/payment/callback"
PAYMENT_WEBHOOK_PORT = max(
    1,
    min(65535, int(os.getenv("PORT", os.getenv("PAYMENT_WEBHOOK_PORT", "8080"))))
)
PAYMENT_WEBHOOK_MAX_SKEW_SECONDS = max(
    60,
    min(3600, int(os.getenv("PAYMENT_WEBHOOK_MAX_SKEW_SECONDS", "300")))
)
PAYMENT_EVENT_MAX_RETRIES = max(
    1,
    min(10, int(os.getenv("PAYMENT_EVENT_MAX_RETRIES", "5")))
)
PAYMENT_EVENT_RETRY_SECONDS = max(
    30,
    min(3600, int(os.getenv("PAYMENT_EVENT_RETRY_SECONDS", "120")))
)
PAYMENT_DUAL_APPROVAL_THRESHOLD = max(
    0,
    int(os.getenv("PAYMENT_DUAL_APPROVAL_THRESHOLD", "0"))
)
USE_AUTO_SHARDING = os.getenv("USE_AUTO_SHARDING", "false").strip().lower() in {"1", "true", "yes", "on"}
BACKUP_CHANNEL_ID = int(os.getenv("BACKUP_CHANNEL_ID", "0") or 0)
PAYMENT_LOG_CHANNEL_ID = int(os.getenv("PAYMENT_LOG_CHANNEL_ID", "0") or 0)
AUDIT_WEBHOOK_URL = os.getenv("AUDIT_WEBHOOK_URL", "").strip()
TRANSACTION_RETENTION_DAYS = max(30, int(os.getenv("TRANSACTION_RETENTION_DAYS", "365")))
ACTIVITY_RETENTION_DAYS = max(7, int(os.getenv("ACTIVITY_RETENTION_DAYS", "90")))
EXPIRED_INVOICE_RETENTION_DAYS = max(7, int(os.getenv("EXPIRED_INVOICE_RETENTION_DAYS", "30")))
DB_MAINTENANCE_HOURS = max(6, int(os.getenv("DB_MAINTENANCE_HOURS", "24")))
VERIFICATION_RETENTION_DAYS = max(
    7,
    int(os.getenv("VERIFICATION_RETENTION_DAYS", "30"))
)

_db_parent = os.path.dirname(os.path.abspath(DB_PATH))
AUTO_BACKUP_DIR = os.getenv(
    "AUTO_BACKUP_DIR",
    os.path.join(_db_parent, "backups")
).strip()

QRIS_STORAGE_DIR = os.getenv(
    "QRIS_STORAGE_DIR",
    os.path.join(_db_parent, "qris")
).strip()

PREMIUM_PACKAGES_RAW = os.getenv(
    "PREMIUM_PACKAGES",
    "7:10000,30:25000,90:60000"
).strip()


def parse_premium_packages(raw: str):
    packages = []
    for item in raw.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue

        days_raw, price_raw = item.split(":", 1)

        if not days_raw.strip().isdigit() or not price_raw.strip().isdigit():
            continue

        days = max(1, int(days_raw.strip()))
        price = max(0, int(price_raw.strip()))
        packages.append((days, price))

    if not packages:
        packages = [
            (7, 10000),
            (30, 25000),
            (90, 60000),
        ]

    return packages[:5]


PREMIUM_PACKAGES = parse_premium_packages(PREMIUM_PACKAGES_RAW)


def rupiah(value: int) -> str:
    return "Rp" + f"{int(value):,}".replace(",", ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("hi-notifku")

intents = discord.Intents.default()
intents.members = True

bot = (
    commands.AutoShardedBot(command_prefix="!", intents=intents)
    if USE_AUTO_SHARDING
    else commands.Bot(command_prefix="!", intents=intents)
)

http: Optional[aiohttp.ClientSession] = None
STARTED_AT = int(time.time())

# Temporary DM upload state for owner QRIS image uploads.
pending_qris_uploads = {}

user_action_cooldowns = {}
pending_restore_previews = {}

notification_send_semaphore = asyncio.Semaphore(NOTIFICATION_SEND_CONCURRENCY)
SAFE_MODE = False
SAFE_MODE_REASON = ""
payment_web_runner = None


runtime_metrics = {
    "notifications_sent": 0,
    "notifications_failed": 0,
    "notifications_queued": 0,
    "checker_runs": 0,
    "checker_errors": 0,
    "last_loop_lag_ms": 0.0,
}




SUPPORTED_PLATFORMS = {
    "youtube",
    "tiktok",
    "twitch",
    "kick",
    "instagram",
    "facebook",
}

PLATFORM_META = {
    "youtube": ("YouTube", "📺"),
    "tiktok": ("TikTok", "🎵"),
    "twitch": ("Twitch", "🟣"),
    "kick": ("Kick", "🟢"),
    "instagram": ("Instagram", "📸"),
    "facebook": ("Facebook", "🔵"),
}


def platform_display_name(platform: str) -> str:
    return PLATFORM_META.get(
        str(platform).lower(),
        (str(platform).title(), "🌐")
    )[0]


def platform_icon(platform: str) -> str:
    return PLATFORM_META.get(
        str(platform).lower(),
        (str(platform).title(), "🌐")
    )[1]


def normalize_social_target(platform: str, target: str) -> str:
    platform = platform.lower().strip()
    target = target.strip()

    if platform == "youtube":
        return target

    if platform == "tiktok":
        target = target.replace("https://www.tiktok.com/@", "")
        target = target.replace("https://tiktok.com/@", "")
        return target.split("/")[0].lstrip("@").strip()

    if platform == "twitch":
        target = target.replace("https://www.twitch.tv/", "")
        return target.split("/")[0].lstrip("@").strip()

    if platform == "kick":
        target = target.replace("https://kick.com/", "")
        return target.split("/")[0].lstrip("@").strip()

    if platform == "instagram":
        target = target.replace("https://www.instagram.com/", "")
        target = target.replace("https://instagram.com/", "")
        return target.split("/")[0].lstrip("@").strip()

    if platform == "facebook":
        if target.startswith(("http://", "https://")):
            return target.rstrip("/")
        return target.lstrip("@").strip()

    return target


def host_public_url(host, *, live: bool = False) -> str:
    platform = host["platform"]
    target = str(host["target"]).strip()

    if platform == "youtube":
        return f"https://www.youtube.com/channel/{target}/live" if live else f"https://www.youtube.com/channel/{target}"

    if platform == "tiktok":
        username = target.lstrip("@")
        return f"https://www.tiktok.com/@{username}/live" if live else f"https://www.tiktok.com/@{username}"

    if platform == "twitch":
        return f"https://www.twitch.tv/{target.lstrip('@')}"

    if platform == "kick":
        return f"https://kick.com/{target.lstrip('@')}"

    if platform == "instagram":
        return f"https://www.instagram.com/{target.lstrip('@')}/"

    if platform == "facebook":
        return target if target.startswith(("http://", "https://")) else f"https://www.facebook.com/{target.lstrip('@')}"

    return target



async def fetch_public_ip(
    *,
    ipv6: bool = False
) -> Optional[str]:
    """
    Best-effort public IP lookup.
    IPv4 uses api.ipify.org and IPv6 uses api6.ipify.org.
    """
    url = (
        "https://api6.ipify.org"
        if ipv6
        else "https://api.ipify.org"
    )

    session = http
    own_session = False

    try:
        if session is None or session.closed:
            session = aiohttp.ClientSession()
            own_session = True

        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=5)
        ) as response:
            if response.status != 200:
                return None

            value = (await response.text()).strip()
            if not value:
                return None

            # Keep output compact and safe.
            if len(value) > 80:
                return None

            return value

    except Exception:
        return None

    finally:
        if own_session and session is not None:
            await session.close()


def local_ip_candidates() -> tuple[Optional[str], Optional[str]]:
    ipv4 = None
    ipv6 = None

    try:
        infos = socket.getaddrinfo(
            socket.gethostname(),
            None,
            type=socket.SOCK_STREAM
        )
        for family, _, _, _, sockaddr in infos:
            if family == socket.AF_INET and not ipv4:
                candidate = sockaddr[0]
                if candidate and not candidate.startswith("127."):
                    ipv4 = candidate
            elif family == socket.AF_INET6 and not ipv6:
                candidate = sockaddr[0].split("%", 1)[0]
                if candidate and candidate != "::1":
                    ipv6 = candidate
    except Exception:
        pass

    return ipv4, ipv6


async def current_ip_info() -> dict:
    public_v4, public_v6 = await asyncio.gather(
        fetch_public_ip(ipv6=False),
        fetch_public_ip(ipv6=True)
    )

    local_v4, local_v6 = local_ip_candidates()

    return {
        "ipv4": public_v4 or local_v4 or "Tidak tersedia",
        "ipv6": public_v6 or local_v6 or "Tidak tersedia",
        "ipv4_public": bool(public_v4),
        "ipv6_public": bool(public_v6),
    }


def apply_ip_fields(
    embed: discord.Embed,
    ip_info: dict
) -> discord.Embed:
    embed.add_field(
        name="IPv4",
        value=f"`{ip_info['ipv4']}`",
        inline=False
    )
    embed.add_field(
        name="IPv6",
        value=f"`{ip_info['ipv6']}`",
        inline=False
    )
    return embed


class PingView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = int(user_id)

    async def valid(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.user_id:
            await safe_reply(
                interaction,
                "🔒 Tombol `/ping` ini bukan milikmu."
            )
            return False
        return True

    @discord.ui.button(
        label="Ambil IP",
        emoji="📋",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def get_ip(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        info = await current_ip_info()

        await interaction.followup.send(
            (
                "**IP Hi Notifku**\n"
                f"IPv4: `{info['ipv4']}`\n"
                f"IPv6: `{info['ipv6']}`\n\n"
                "Tekan lama / pilih teks untuk menyalin."
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def refresh(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )
        info = await current_ip_info()
        embed = bot_status_embed()
        apply_ip_fields(embed, info)

        await interaction.edit_original_response(
            embed=embed,
            view=PingView(self.user_id)
        )




# ============================================================
# BOT STATUS / PING
# ============================================================

def human_bytes(value: int) -> str:
    size = float(max(0, value))
    units = ["B", "KB", "MB", "GB", "TB"]

    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024

    return f"{size:.2f} TB"


def bot_status_embed():
    now = int(time.time())
    uptime_seconds = max(0, now - STARTED_AT)

    days, rem = divmod(uptime_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    uptime_parts = []
    if days:
        uptime_parts.append(f"{days}h")
    if hours:
        uptime_parts.append(f"{hours}j")
    uptime_parts.append(f"{minutes}m")
    uptime_text = " ".join(uptime_parts)

    try:
        disk = shutil.disk_usage(".")
        disk_used = human_bytes(disk.used)
        disk_total = human_bytes(disk.total)
        storage_text = f"{disk_used} / {disk_total}"
    except Exception:
        storage_text = "Tidak diketahui"

    total_hosts = 0
    enabled_hosts = 0

    for guild in bot.guilds:
        try:
            hosts = get_hosts(guild.id)
            total_hosts += len(hosts)
            enabled_hosts += sum(1 for h in hosts if h["enabled"])
        except Exception:
            pass

    embed = discord.Embed(
        title="🏓 Hi Notifku",
        description="Ringkasan status bot.",
        color=discord.Color.green()
    )

    embed.add_field(
        name="Status",
        value="🟢 Online" if bot.is_ready() else "🟡 Starting",
        inline=True
    )
    embed.add_field(
        name="Ping",
        value=f"{round(bot.latency * 1000)} ms",
        inline=True
    )
    embed.add_field(
        name="Uptime",
        value=uptime_text,
        inline=True
    )
    embed.add_field(
        name="Server",
        value=str(len(bot.guilds)),
        inline=True
    )
    embed.add_field(
        name="Host",
        value=f"{enabled_hosts}/{total_hosts} aktif",
        inline=True
    )
    embed.add_field(
        name="Storage",
        value=storage_text,
        inline=True
    )

    embed.set_footer(text="Hi Notifku • /ping")
    return embed


# ============================================================
# DATABASE
# ============================================================

def db():
    db_path = Path(DB_PATH).expanduser()

    # SQLite cannot create missing parent directories itself.
    # Make the parent directory first so Railway /data paths work
    # when the volume is mounted correctly.
    parent = db_path.parent

    try:
        if str(parent) not in {"", "."}:
            parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise RuntimeError(
            f"Gagal membuat folder database: {parent}. "
            f"Pastikan Railway Volume ter-mount dan DB_PATH benar. "
            f"Detail: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        conn = sqlite3.connect(str(db_path), timeout=30)
    except sqlite3.OperationalError as exc:
        raise RuntimeError(
            f"SQLite tidak dapat membuka database di: {db_path}. "
            "Jika memakai DB_PATH=/data/live_notifier.db, pastikan Railway Volume "
            "dipasang ke mount path /data. "
            f"Detail: {exc}"
        ) from exc

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_meta (
                id INTEGER PRIMARY KEY CHECK(id=1),
                version INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS migration_history (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at INTEGER NOT NULL
            )
        """)

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
                    platform TEXT NOT NULL,
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
                    access_state TEXT NOT NULL DEFAULT 'allowed',
                    premium_started_at INTEGER,
                    premium_expires_at INTEGER,
                    premium_warning_sent INTEGER NOT NULL DEFAULT 0
                )
            """)
        else:
            add_column_if_missing(conn, "guild_settings", "premium_started_at", "INTEGER")
            add_column_if_missing(conn, "guild_settings", "premium_expires_at", "INTEGER")
            add_column_if_missing(conn, "guild_settings", "premium_warning_sent", "INTEGER NOT NULL DEFAULT 0")

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

        # Premium packages managed by owner
        if not table_exists(conn, "premium_packages"):
            conn.execute("""
                CREATE TABLE premium_packages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    days INTEGER NOT NULL UNIQUE,
                    price INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                )
            """)

            for days, price in PREMIUM_PACKAGES:
                conn.execute("""
                    INSERT OR IGNORE INTO premium_packages(days, price, enabled)
                    VALUES(?,?,1)
                """, (days, price))

        # Premium order / transaction queue
        if not table_exists(conn, "premium_orders"):
            conn.execute("""
                CREATE TABLE premium_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    requester_id INTEGER NOT NULL,
                    days INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    processed_by INTEGER,
                    activated_at INTEGER,
                    expires_at INTEGER
                )
            """)

        # Reminder history prevents duplicate H-7 / H-3 / H-1 messages.
        if not table_exists(conn, "premium_reminders"):
            conn.execute("""
                CREATE TABLE premium_reminders (
                    guild_id INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    days_before INTEGER NOT NULL,
                    sent_at INTEGER NOT NULL,
                    PRIMARY KEY(guild_id, expires_at, days_before)
                )
            """)

        # Automatic backup metadata
        if not table_exists(conn, "backup_log"):
            conn.execute("""
                CREATE TABLE backup_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    guild_count INTEGER NOT NULL,
                    ok INTEGER NOT NULL DEFAULT 1,
                    error TEXT
                )
            """)


        if not table_exists(conn, "bot_runtime_settings"):
            conn.execute("""
                CREATE TABLE bot_runtime_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    monitor_paused INTEGER NOT NULL DEFAULT 0,
                    notifications_paused INTEGER NOT NULL DEFAULT 0,
                    requests_paused INTEGER NOT NULL DEFAULT 0,
                    maintenance_all INTEGER NOT NULL DEFAULT 0,
                    updated_by INTEGER,
                    updated_at INTEGER
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO bot_runtime_settings(
                    id,
                    monitor_paused,
                    notifications_paused,
                    requests_paused,
                    maintenance_all
                )
                VALUES(1,0,0,0,0)
            """)


        conn.execute("""
            CREATE TABLE IF NOT EXISTS host_plan_pause (
                host_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                paused_at INTEGER NOT NULL,
                reason TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS host_auto_recovery (
                host_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                auto_paused_at INTEGER NOT NULL,
                last_retry_at INTEGER,
                retry_count INTEGER NOT NULL DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS server_risk_meta (
                guild_id INTEGER PRIMARY KEY,
                reason TEXT,
                expires_at INTEGER,
                updated_by INTEGER,
                updated_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS platform_incidents (
                platform TEXT PRIMARY KEY,
                state TEXT NOT NULL DEFAULT 'normal',
                error_hosts INTEGER NOT NULL DEFAULT 0,
                total_hosts INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS premium_coupons (
                code TEXT PRIMARY KEY,
                discount_type TEXT NOT NULL,
                discount_value INTEGER NOT NULL,
                expires_at INTEGER,
                max_uses INTEGER,
                used_count INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER,
                created_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS premium_coupon_redemptions (
                order_id INTEGER PRIMARY KEY,
                code TEXT NOT NULL,
                discount_amount INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                redeemed_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS premium_order_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                actor_id INTEGER,
                detail TEXT,
                created_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS owner_health_alerts (
                host_id INTEGER PRIMARY KEY,
                last_error_count INTEGER NOT NULL,
                last_sent_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS rollback_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_by INTEGER,
                created_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS request_reminders (
                request_kind TEXT NOT NULL,
                request_id INTEGER NOT NULL,
                milestone_hours INTEGER NOT NULL,
                sent_at INTEGER NOT NULL,
                PRIMARY KEY(request_kind, request_id, milestone_hours)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS request_recovery_log (
                request_kind TEXT NOT NULL,
                request_id INTEGER NOT NULL,
                sent_at INTEGER NOT NULL,
                PRIMARY KEY(request_kind, request_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_verifications (
                user_id INTEGER PRIMARY KEY,
                verified INTEGER NOT NULL DEFAULT 0,
                verified_at INTEGER,
                last_checked_at INTEGER NOT NULL,
                last_active_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                verification_source TEXT,
                status_reason TEXT
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_verifications_active
            ON user_verifications(verified, last_active_at)
        """)

        if not table_exists(conn, "guild_owner_verification"):
            conn.execute("""
                CREATE TABLE guild_owner_verification (
                    guild_id INTEGER PRIMARY KEY,
                    owner_id INTEGER NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0,
                    verified_at INTEGER,
                    last_checked_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    verification_source TEXT,
                    status_reason TEXT,
                    last_active_at INTEGER,
                    inactive_since INTEGER
                )
            """)
        else:
            verification_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(guild_owner_verification)"
                ).fetchall()
            }

            if "verification_source" not in verification_columns:
                conn.execute(
                    "ALTER TABLE guild_owner_verification "
                    "ADD COLUMN verification_source TEXT"
                )

            if "status_reason" not in verification_columns:
                conn.execute(
                    "ALTER TABLE guild_owner_verification "
                    "ADD COLUMN status_reason TEXT"
                )

            if "last_active_at" not in verification_columns:
                conn.execute(
                    "ALTER TABLE guild_owner_verification "
                    "ADD COLUMN last_active_at INTEGER"
                )

            if "inactive_since" not in verification_columns:
                conn.execute(
                    "ALTER TABLE guild_owner_verification "
                    "ADD COLUMN inactive_since INTEGER"
                )

        # Legacy single payment configuration
        if not table_exists(conn, "payment_settings"):
            conn.execute("""
                CREATE TABLE payment_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    method_name TEXT,
                    account_name TEXT,
                    account_number TEXT,
                    payment_note TEXT,
                    qris_url TEXT,
                    updated_at INTEGER
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO payment_settings(
                    id, method_name, account_name,
                    account_number, payment_note,
                    qris_url, updated_at
                )
                VALUES(1, NULL, NULL, NULL, NULL, NULL, NULL)
            """)

        # Multi payment methods
        if not table_exists(conn, "payment_methods"):
            conn.execute("""
                CREATE TABLE payment_methods (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    method_type TEXT NOT NULL,
                    method_name TEXT NOT NULL,
                    account_name TEXT,
                    account_number TEXT,
                    payment_note TEXT,
                    qris_image_url TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)

            # Import old single-method settings once if available.
            old = conn.execute(
                "SELECT * FROM payment_settings WHERE id=1"
            ).fetchone()

            if old and (
                old["method_name"]
                or old["account_number"]
                or old["qris_url"]
            ):
                method_type = (
                    "qris"
                    if old["qris_url"]
                    else "account"
                )

                conn.execute("""
                    INSERT INTO payment_methods(
                        method_type,
                        method_name,
                        account_name,
                        account_number,
                        payment_note,
                        qris_image_url,
                        enabled,
                        created_at,
                        updated_at
                    )
                    VALUES(?,?,?,?,?,?,1,?,?)
                """, (
                    method_type,
                    old["method_name"] or (
                        "QRIS"
                        if method_type == "qris"
                        else "Pembayaran"
                    ),
                    old["account_name"],
                    old["account_number"],
                    old["payment_note"],
                    old["qris_url"],
                    int(time.time()),
                    int(time.time())
                ))

        add_column_if_missing(conn, "payment_methods", "qris_image_path", "TEXT")

        # Extend premium orders with manual payment proof metadata
        add_column_if_missing(conn, "premium_orders", "proof_url", "TEXT")
        add_column_if_missing(conn, "premium_orders", "proof_message_id", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "proof_submitted_at", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "unique_code", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "expected_amount", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "received_amount", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "amount_verified", "INTEGER NOT NULL DEFAULT 0")
        add_column_if_missing(conn, "premium_orders", "payment_method_id", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "payment_method_name", "TEXT")
        add_column_if_missing(conn, "premium_orders", "invoice_deadline", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "rejection_reason", "TEXT")
        add_column_if_missing(conn, "premium_orders", "owner_note", "TEXT")
        add_column_if_missing(conn, "premium_orders", "proof_hash", "TEXT")
        add_column_if_missing(conn, "premium_orders", "payment_checked_at", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "invoice_ref", "TEXT")
        add_column_if_missing(conn, "premium_orders", "processing_by", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "processing_at", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "proof_sender_name", "TEXT")
        add_column_if_missing(conn, "premium_orders", "proof_sender_account", "TEXT")
        add_column_if_missing(conn, "premium_orders", "proof_transfer_time", "TEXT")
        add_column_if_missing(conn, "premium_orders", "proof_reference", "TEXT")
        add_column_if_missing(conn, "premium_orders", "proof_declared_amount", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "proof_note", "TEXT")
        add_column_if_missing(conn, "premium_orders", "proof_details_submitted_at", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "proof_scan_status", "TEXT")
        add_column_if_missing(conn, "premium_orders", "proof_scan_score", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "proof_scan_detail", "TEXT")
        add_column_if_missing(conn, "premium_orders", "proof_scan_at", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "proof_file_size", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "proof_image_width", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "proof_image_height", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "proof_mime", "TEXT")
        add_column_if_missing(conn, "premium_orders", "proof_edit_software", "TEXT")
        add_column_if_missing(conn, "premium_orders", "payment_reference", "TEXT")
        add_column_if_missing(conn, "premium_orders", "payment_source", "TEXT")
        add_column_if_missing(conn, "premium_orders", "paid_at", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "payment_verified_at", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "risk_score", "INTEGER NOT NULL DEFAULT 0")
        add_column_if_missing(conn, "premium_orders", "risk_level", "TEXT")
        add_column_if_missing(conn, "premium_orders", "risk_reasons", "TEXT")
        add_column_if_missing(conn, "premium_orders", "late_payment", "INTEGER NOT NULL DEFAULT 0")
        add_column_if_missing(conn, "premium_orders", "refund_status", "TEXT")
        add_column_if_missing(conn, "premium_orders", "refund_reason", "TEXT")
        add_column_if_missing(conn, "premium_orders", "refunded_at", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "override_reason", "TEXT")
        add_column_if_missing(conn, "premium_orders", "receipt_sent_at", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "activation_target_expires_at", "INTEGER")
        add_column_if_missing(conn, "premium_orders", "activation_effect_applied", "INTEGER NOT NULL DEFAULT 0")

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_premium_orders_payment_reference
            ON premium_orders(payment_reference)
            WHERE payment_reference IS NOT NULL
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS payment_callback_events (
                event_id TEXT PRIMARY KEY,
                invoice_ref TEXT,
                reference_id TEXT,
                amount INTEGER,
                payment_status TEXT,
                payload_hash TEXT NOT NULL,
                signature_valid INTEGER NOT NULL DEFAULT 0,
                received_at INTEGER NOT NULL,
                processed_at INTEGER,
                process_status TEXT NOT NULL DEFAULT 'received',
                error TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS payment_event_dead_letter (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                error TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                next_retry_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                resolved_at INTEGER
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS incident_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_key TEXT NOT NULL,
                incident_type TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                opened_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                acknowledged_by INTEGER,
                acknowledged_at INTEGER,
                resolved_at INTEGER
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_incident_history_status
            ON incident_history(status, updated_at DESC)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_backup_schedule_state (
                id INTEGER PRIMARY KEY CHECK(id=1),
                last_export_at INTEGER,
                last_path TEXT,
                last_error TEXT
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO system_backup_schedule_state(id)
            VALUES(1)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS runtime_tuning (
                id INTEGER PRIMARY KEY CHECK(id=1),
                monitor_concurrency INTEGER NOT NULL,
                notification_max_retries INTEGER NOT NULL,
                error_alert_threshold INTEGER NOT NULL,
                circuit_breaker_minutes INTEGER NOT NULL,
                updated_by INTEGER,
                updated_at INTEGER
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO runtime_tuning(
                id, monitor_concurrency, notification_max_retries,
                error_alert_threshold, circuit_breaker_minutes
            )
            VALUES(1,?,?,?,10)
        """, (
            int(MONITOR_CONCURRENCY),
            runtime_tuning_int(
                "notification_max_retries",
                NOTIFICATION_MAX_RETRIES
            ),
            int(ERROR_ALERT_THRESHOLD)
        ))

        conn.execute("""
            CREATE TABLE IF NOT EXISTS payment_health (
                id INTEGER PRIMARY KEY CHECK(id=1),
                last_callback_at INTEGER,
                last_success_at INTEGER,
                last_failure_at INTEGER,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO payment_health(
                id, success_count, failure_count
            )
            VALUES(1,0,0)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS payment_approvals (
                order_id INTEGER NOT NULL,
                approver_id INTEGER NOT NULL,
                approved_at INTEGER NOT NULL,
                PRIMARY KEY(order_id, approver_id)
            )
        """)

        add_column_if_missing(conn, "guild_settings", "premium_grace_until", "INTEGER")
        add_column_if_missing(conn, "guild_settings", "setup_completed", "INTEGER NOT NULL DEFAULT 0")

        add_column_if_missing(conn, "guild_settings", "maintenance_mode", "INTEGER NOT NULL DEFAULT 0")
        add_column_if_missing(conn, "guild_settings", "timezone", "TEXT DEFAULT 'Asia/Jakarta'")
        add_column_if_missing(conn, "guild_settings", "language", "TEXT DEFAULT 'id'")
        add_column_if_missing(conn, "guild_settings", "feature_flags", "TEXT")

        add_column_if_missing(conn, "hosts", "extra_channel_ids", "TEXT")
        add_column_if_missing(conn, "hosts", "extra_role_ids", "TEXT")
        add_column_if_missing(conn, "hosts", "schedule_days", "TEXT DEFAULT '0,1,2,3,4,5,6'")
        add_column_if_missing(conn, "hosts", "quiet_start", "TEXT")
        add_column_if_missing(conn, "hosts", "quiet_end", "TEXT")
        add_column_if_missing(conn, "hosts", "timezone", "TEXT")
        add_column_if_missing(conn, "hosts", "language", "TEXT")
        add_column_if_missing(conn, "hosts", "webhook_url", "TEXT")
        add_column_if_missing(conn, "hosts", "mention_everyone", "INTEGER NOT NULL DEFAULT 0")
        add_column_if_missing(conn, "hosts", "embed_title", "TEXT")
        add_column_if_missing(conn, "hosts", "embed_footer", "TEXT")
        add_column_if_missing(conn, "hosts", "embed_color", "INTEGER")
        add_column_if_missing(conn, "hosts", "auto_pause_threshold", "INTEGER")


        # Older databases restricted hosts.platform to youtube/tiktok.
        # Rebuild the table once so new social platforms can be stored.
        host_table_sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='hosts'"
        ).fetchone()

        host_table_sql = (
            host_table_sql_row["sql"]
            if host_table_sql_row and host_table_sql_row["sql"]
            else ""
        )

        if (
            "CHECK(platform IN ('youtube','tiktok'))" in host_table_sql
            or 'CHECK(platform IN ("youtube","tiktok"))' in host_table_sql
        ):
            conn.execute("DROP TABLE IF EXISTS hosts_social_v2")
            conn.execute("""
                CREATE TABLE hosts_social_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
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
                    extra_channel_ids TEXT,
                    extra_role_ids TEXT,
                    schedule_days TEXT DEFAULT '0,1,2,3,4,5,6',
                    quiet_start TEXT,
                    quiet_end TEXT,
                    timezone TEXT,
                    language TEXT,
                    webhook_url TEXT,
                    mention_everyone INTEGER NOT NULL DEFAULT 0,
                    embed_title TEXT,
                    embed_footer TEXT,
                    embed_color INTEGER,
                    auto_pause_threshold INTEGER,
                    UNIQUE(guild_id, platform, target)
                )
            """)

            conn.execute("""
                INSERT INTO hosts_social_v2(
                    id, guild_id, platform, target, display_name, extra,
                    enabled, channel_id, role_id, custom_live_message,
                    custom_post_message, custom_end_message, notify_live_end,
                    check_interval, last_check, last_error, error_count,
                    cooldown_until, extra_channel_ids, extra_role_ids,
                    schedule_days, quiet_start, quiet_end, timezone,
                    language, webhook_url, mention_everyone, embed_title,
                    embed_footer, embed_color, auto_pause_threshold
                )
                SELECT
                    id, guild_id, platform, target, display_name, extra,
                    enabled, channel_id, role_id, custom_live_message,
                    custom_post_message, custom_end_message, notify_live_end,
                    check_interval, last_check, last_error, error_count,
                    cooldown_until, extra_channel_ids, extra_role_ids,
                    schedule_days, quiet_start, quiet_end, timezone,
                    language, webhook_url, mention_everyone, embed_title,
                    embed_footer, embed_color, auto_pause_threshold
                FROM hosts
            """)

            conn.execute("DROP TABLE hosts")
            conn.execute("ALTER TABLE hosts_social_v2 RENAME TO hosts")

        if not table_exists(conn, "social_content_state"):
            conn.execute("""
                CREATE TABLE social_content_state (
                    host_id INTEGER PRIMARY KEY,
                    last_item_id TEXT,
                    initialized INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL
                )
            """)


        # Host managers are intentionally separate from bot_owners.
        # A host manager never becomes a global owner and never receives /owner access.
        if not table_exists(conn, "host_managers"):
            conn.execute("""
                CREATE TABLE host_managers (
                    host_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    can_edit_messages INTEGER NOT NULL DEFAULT 1,
                    can_schedule INTEGER NOT NULL DEFAULT 1,
                    can_pause INTEGER NOT NULL DEFAULT 1,
                    can_recheck INTEGER NOT NULL DEFAULT 1,
                    can_history INTEGER NOT NULL DEFAULT 1,
                    can_test INTEGER NOT NULL DEFAULT 1,
                    assigned_by INTEGER,
                    assigned_at INTEGER NOT NULL,
                    expires_at INTEGER,
                    PRIMARY KEY(host_id, user_id)
                )
            """)

        if not table_exists(conn, "host_manager_activity"):
            conn.execute("""
                CREATE TABLE host_manager_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    detail TEXT,
                    created_at INTEGER NOT NULL
                )
            """)


        if not table_exists(conn, "host_manager_preferences"):
            conn.execute("""
                CREATE TABLE host_manager_preferences (
                    host_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    onboarding_seen INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY(host_id, user_id)
                )
            """)

        if not table_exists(conn, "host_access_requests"):
            conn.execute("""
                CREATE TABLE host_access_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    host_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at INTEGER NOT NULL,
                    processed_by INTEGER,
                    processed_at INTEGER,
                    UNIQUE(host_id, user_id, status)
                )
            """)


        if not table_exists(conn, "server_host_access_requests"):
            conn.execute("""
                CREATE TABLE server_host_access_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at INTEGER NOT NULL,
                    approved_host_id INTEGER,
                    processed_by INTEGER,
                    processed_at INTEGER
                )
            """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_server_host_access_requests_pending
            ON server_host_access_requests(
                guild_id,
                user_id,
                status,
                created_at DESC
            )
        """)


        if not table_exists(conn, "server_host_managers"):
            conn.execute("""
                CREATE TABLE server_host_managers (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    approved_by INTEGER NOT NULL,
                    approved_at INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    expires_at INTEGER,
                    PRIMARY KEY(guild_id, user_id)
                )
            """)

        if not table_exists(conn, "host_creation_requests"):
            conn.execute("""
                CREATE TABLE host_creation_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    requester_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    target TEXT NOT NULL,
                    channel_id INTEGER NOT NULL,
                    role_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at INTEGER NOT NULL,
                    processed_by INTEGER,
                    processed_at INTEGER,
                    created_host_id INTEGER,
                    rejection_reason TEXT
                )
            """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_host_creation_requests_pending
            ON host_creation_requests(
                guild_id,
                requester_id,
                status,
                created_at DESC
            )
        """)

        if not table_exists(conn, "host_manager_warnings"):
            conn.execute("""
                CREATE TABLE host_manager_warnings (
                    host_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    warning_key TEXT NOT NULL,
                    sent_at INTEGER NOT NULL,
                    PRIMARY KEY(host_id, user_id, warning_key)
                )
            """)

        if not table_exists(conn, "user_blacklist"):
            conn.execute("""
                CREATE TABLE user_blacklist (
                    user_id INTEGER PRIMARY KEY,
                    reason TEXT,
                    added_by INTEGER,
                    created_at INTEGER NOT NULL
                )
            """)

        if not table_exists(conn, "owner_roles"):
            conn.execute("""
                CREATE TABLE owner_roles (
                    user_id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL DEFAULT 'server_admin',
                    updated_by INTEGER,
                    updated_at INTEGER NOT NULL
                )
            """)

        if not table_exists(conn, "error_alerts"):
            conn.execute("""
                CREATE TABLE error_alerts (
                    host_id INTEGER PRIMARY KEY,
                    last_alert_error_count INTEGER NOT NULL DEFAULT 0,
                    last_alert_at INTEGER
                )
            """)

        if not table_exists(conn, "restore_audit"):
            conn.execute("""
                CREATE TABLE restore_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    actor_id INTEGER,
                    created_at INTEGER NOT NULL,
                    summary TEXT
                )
            """)

        if not table_exists(conn, "pending_uploads"):
            conn.execute("""
                CREATE TABLE pending_uploads (
                    user_id INTEGER PRIMARY KEY,
                    upload_type TEXT NOT NULL,
                    target_id INTEGER,
                    created_at INTEGER NOT NULL
                )
            """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS notification_dead_letter (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                host_id INTEGER NOT NULL,
                event_type TEXT,
                event_key TEXT,
                content TEXT,
                embed_json TEXT NOT NULL,
                source_url TEXT,
                failure_reason TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                resolved_at INTEGER
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS validation_alerts (
                alert_key TEXT PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                host_id INTEGER,
                alert_type TEXT NOT NULL,
                sent_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_verification_warnings (
                user_id INTEGER NOT NULL,
                expiry_at INTEGER NOT NULL,
                days_before INTEGER NOT NULL,
                sent_at INTEGER NOT NULL,
                PRIMARY KEY(user_id, expiry_at, days_before)
            )
        """)

        if not table_exists(conn, "notification_history"):
            conn.execute("""
                CREATE TABLE notification_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    host_id INTEGER,
                    event_type TEXT,
                    event_key TEXT,
                    channel_id INTEGER,
                    message_id INTEGER,
                    status TEXT NOT NULL,
                    latency_ms INTEGER,
                    source_url TEXT,
                    title TEXT,
                    content TEXT,
                    embed_json TEXT,
                    created_at INTEGER NOT NULL
                )
            """)

        if not table_exists(conn, "notification_events"):
            conn.execute("""
                CREATE TABLE notification_events (
                    host_id INTEGER NOT NULL,
                    event_key TEXT NOT NULL,
                    event_type TEXT,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY(host_id, event_key)
                )
            """)

        if not table_exists(conn, "pending_notifications"):
            conn.execute("""
                CREATE TABLE pending_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    host_id INTEGER NOT NULL,
                    event_type TEXT,
                    event_key TEXT,
                    content TEXT,
                    embed_json TEXT NOT NULL,
                    source_url TEXT,
                    release_after INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)

        add_column_if_missing(
            conn,
            "pending_notifications",
            "retry_count",
            "INTEGER NOT NULL DEFAULT 0"
        )
        add_column_if_missing(
            conn,
            "pending_notifications",
            "max_retries",
            f"INTEGER NOT NULL DEFAULT {NOTIFICATION_MAX_RETRIES}"
        )
        add_column_if_missing(
            conn,
            "pending_notifications",
            "last_error",
            "TEXT"
        )

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_notifications_event_unique
            ON pending_notifications(host_id, event_key, event_type)
            WHERE event_key IS NOT NULL
        """)

        # Permanent Premium customer database. This is intentionally separate
        # from premium_orders because old transactional rows may be cleaned up.
        if not table_exists(conn, "premium_customer_ledger"):
            conn.execute("""
                CREATE TABLE premium_customer_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL UNIQUE,
                    guild_id INTEGER NOT NULL,
                    requester_id INTEGER NOT NULL,
                    invoice_ref TEXT,
                    days INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    activated_at INTEGER NOT NULL,
                    expires_at INTEGER,
                    source TEXT,
                    created_at INTEGER NOT NULL
                )
            """)

        if not table_exists(conn, "premium_customers"):
            conn.execute("""
                CREATE TABLE premium_customers (
                    guild_id INTEGER PRIMARY KEY,
                    guild_name TEXT,
                    first_buyer_id INTEGER NOT NULL,
                    last_buyer_id INTEGER NOT NULL,
                    first_purchased_at INTEGER NOT NULL,
                    last_purchased_at INTEGER NOT NULL,
                    current_expires_at INTEGER,
                    total_orders INTEGER NOT NULL DEFAULT 0,
                    total_days INTEGER NOT NULL DEFAULT 0,
                    total_spent INTEGER NOT NULL DEFAULT 0,
                    last_order_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'expired',
                    updated_at INTEGER NOT NULL
                )
            """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_premium_customer_ledger_guild
            ON premium_customer_ledger(guild_id, activated_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_premium_customer_ledger_user
            ON premium_customer_ledger(requester_id, activated_at DESC)
        """)

        # Backfill all successfully activated historical orders. INSERT OR IGNORE
        # makes this safe to run on every deploy.
        conn.execute("""
            INSERT OR IGNORE INTO premium_customer_ledger(
                order_id, guild_id, requester_id, invoice_ref, days, amount,
                activated_at, expires_at, source, created_at
            )
            SELECT
                id, guild_id, requester_id, invoice_ref, days, price,
                COALESCE(activated_at, updated_at, created_at), expires_at,
                COALESCE(payment_source, 'historical'),
                COALESCE(activated_at, updated_at, created_at)
            FROM premium_orders
            WHERE activated_at IS NOT NULL OR status='active'
        """)

        # Rebuild the aggregate customer table from the permanent ledger.
        customer_rows = conn.execute("""
            SELECT
                l.guild_id,
                MIN(l.activated_at) AS first_purchased_at,
                MAX(l.activated_at) AS last_purchased_at,
                MAX(l.expires_at) AS current_expires_at,
                COUNT(*) AS total_orders,
                SUM(l.days) AS total_days,
                SUM(l.amount) AS total_spent
            FROM premium_customer_ledger l
            GROUP BY l.guild_id
        """).fetchall()
        for customer in customer_rows:
            gid = int(customer["guild_id"])
            first_row = conn.execute("""
                SELECT requester_id FROM premium_customer_ledger
                WHERE guild_id=? ORDER BY activated_at ASC, id ASC LIMIT 1
            """, (gid,)).fetchone()
            last_row = conn.execute("""
                SELECT requester_id, order_id FROM premium_customer_ledger
                WHERE guild_id=? ORDER BY activated_at DESC, id DESC LIMIT 1
            """, (gid,)).fetchone()
            settings_row = conn.execute(
                "SELECT plan, premium_expires_at, premium_grace_until FROM guild_settings WHERE guild_id=?",
                (gid,)
            ).fetchone()
            expires = int(customer["current_expires_at"] or 0) or None
            active_now = False
            if settings_row:
                effective_until = int(settings_row["premium_grace_until"] or settings_row["premium_expires_at"] or 0)
                active_now = str(settings_row["plan"]) == "premium" and effective_until > int(time.time())
            conn.execute("""
                INSERT INTO premium_customers(
                    guild_id, guild_name, first_buyer_id, last_buyer_id,
                    first_purchased_at, last_purchased_at, current_expires_at,
                    total_orders, total_days, total_spent, last_order_id, status, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    first_buyer_id=excluded.first_buyer_id,
                    last_buyer_id=excluded.last_buyer_id,
                    first_purchased_at=excluded.first_purchased_at,
                    last_purchased_at=excluded.last_purchased_at,
                    current_expires_at=excluded.current_expires_at,
                    total_orders=excluded.total_orders,
                    total_days=excluded.total_days,
                    total_spent=excluded.total_spent,
                    last_order_id=excluded.last_order_id,
                    status=excluded.status,
                    updated_at=excluded.updated_at
            """, (
                gid, None, int(first_row["requester_id"]), int(last_row["requester_id"]),
                int(customer["first_purchased_at"]), int(customer["last_purchased_at"]), expires,
                int(customer["total_orders"] or 0), int(customer["total_days"] or 0),
                int(customer["total_spent"] or 0), int(last_row["order_id"]),
                "active" if active_now else "expired", int(time.time())
            ))

        if not table_exists(conn, "api_usage"):
            conn.execute("""
                CREATE TABLE api_usage (
                    day TEXT NOT NULL,
                    service TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    calls INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(day, service, endpoint)
                )
            """)

        if not table_exists(conn, "config_snapshots"):
            conn.execute("""
                CREATE TABLE config_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    reason TEXT,
                    payload TEXT NOT NULL
                )
            """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_notification_history_guild
            ON notification_history(guild_id, created_at DESC)
        """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_premium_orders_invoice_ref
            ON premium_orders(invoice_ref)
            WHERE invoice_ref IS NOT NULL
        """)

        now = int(time.time())
        conn.execute("""
            INSERT INTO schema_meta(id, version, updated_at)
            VALUES(1,?,?)
            ON CONFLICT(id)
            DO UPDATE SET version=excluded.version, updated_at=excluded.updated_at
        """, (
            CURRENT_SCHEMA_VERSION,
            now
        ))
        conn.execute("""
            INSERT OR IGNORE INTO migration_history(version, name, applied_at)
            VALUES(?,?,?)
        """, (
            CURRENT_SCHEMA_VERSION,
            f"Hi Notifku schema v{CURRENT_SCHEMA_VERSION}",
            now
        ))

        conn.commit()
        log.info(
            "Database schema ready. version=%s",
            CURRENT_SCHEMA_VERSION
        )


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


def set_plan(
    guild_id: int,
    plan: str,
    *,
    duration_days: Optional[int] = None,
    extend: bool = False
):
    plan = "premium" if plan == "premium" else "free"
    ensure_guild(guild_id)

    now = int(time.time())

    with closing(db()) as conn:
        if plan == "premium":
            current = conn.execute(
                "SELECT premium_expires_at FROM guild_settings WHERE guild_id=?",
                (guild_id,)
            ).fetchone()

            days = max(1, int(duration_days or 30))
            seconds = days * 86400

            if extend and current and current["premium_expires_at"] and int(current["premium_expires_at"]) > now:
                expires_at = int(current["premium_expires_at"]) + seconds
                started_at = None
            else:
                expires_at = now + seconds
                started_at = now

            conn.execute("""
                UPDATE guild_settings
                SET
                    plan='premium',
                    premium_started_at=COALESCE(?, premium_started_at),
                    premium_expires_at=?,
                    premium_warning_sent=0,
                    premium_grace_until=NULL
                WHERE guild_id=?
            """, (
                started_at,
                expires_at,
                guild_id
            ))
        else:
            conn.execute("""
                UPDATE guild_settings
                SET
                    plan='free',
                    premium_started_at=NULL,
                    premium_expires_at=NULL,
                    premium_warning_sent=0,
                    premium_grace_until=NULL
                WHERE guild_id=?
            """, (guild_id,))

        conn.commit()

    if plan == "premium":
        restored = reactivate_plan_paused_hosts(guild_id)
        if restored:
            add_activity(
                guild_id,
                None,
                "Premium Host Reactivation",
                f"{restored} host dipulihkan setelah Premium aktif."
            )
    else:
        paused = pause_excess_hosts_for_free(guild_id)
        if paused:
            add_activity(
                guild_id,
                None,
                "FREE Host Limit Applied",
                f"{paused} host dipause karena limit FREE."
            )



def premium_remaining_seconds(guild_id: int) -> Optional[int]:
    settings = get_guild_settings(guild_id)

    if settings["plan"] != "premium":
        return None

    expires_at = settings["premium_expires_at"]

    if not expires_at:
        return None

    return int(expires_at) - int(time.time())


def premium_expiry_text(guild_id: int) -> str:
    settings = get_guild_settings(guild_id)

    if settings["plan"] != "premium":
        return "Tidak aktif"

    expires_at = settings["premium_expires_at"]

    if not expires_at:
        return "Premium tanpa batas waktu"

    return f"<t:{int(expires_at)}:F> • <t:{int(expires_at)}:R>"


def mark_premium_warning_sent(guild_id: int, sent: bool = True):
    with closing(db()) as conn:
        conn.execute(
            "UPDATE guild_settings SET premium_warning_sent=? WHERE guild_id=?",
            (1 if sent else 0, guild_id)
        )
        conn.commit()


def set_access_state(guild_id: int, state: str):
    if state not in {"allowed", "blacklist", "whitelist", "warning", "suspended"}:
        state = "allowed"
    ensure_guild(guild_id)
    with closing(db()) as conn:
        conn.execute(
            "UPDATE guild_settings SET access_state=? WHERE guild_id=?",
            (state, guild_id)
        )
        conn.commit()


def host_limit_for_guild(guild_id: int) -> int:
    return int(premium_entitlements(int(guild_id))["host_limit"])


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



HOST_MANAGER_PERMISSION_COLUMNS = {
    "edit_messages": "can_edit_messages",
    "schedule": "can_schedule",
    "pause": "can_pause",
    "recheck": "can_recheck",
    "history": "can_history",
    "test": "can_test",
}


def host_manager_rows(user_id: int):
    now = int(time.time())
    with closing(db()) as conn:
        return conn.execute("""
            SELECT
                hm.*,
                h.guild_id,
                h.platform,
                h.target,
                h.display_name,
                h.enabled,
                h.last_error,
                h.last_check
            FROM host_managers hm
            JOIN hosts h ON h.id=hm.host_id
            WHERE hm.user_id=?
              AND (hm.expires_at IS NULL OR hm.expires_at>?)
            ORDER BY h.guild_id, h.platform, h.id
        """, (
            int(user_id),
            now
        )).fetchall()



def grant_server_host_manager(
    guild_id: int,
    user_id: int,
    approved_by: int,
    *,
    expires_at: Optional[int] = None
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO server_host_managers(
                guild_id,
                user_id,
                approved_by,
                approved_at,
                enabled,
                expires_at
            )
            VALUES(?,?,?,?,1,?)
            ON CONFLICT(guild_id, user_id)
            DO UPDATE SET
                approved_by=excluded.approved_by,
                approved_at=excluded.approved_at,
                enabled=1,
                expires_at=excluded.expires_at
        """, (
            int(guild_id),
            int(user_id),
            int(approved_by),
            int(time.time()),
            int(expires_at) if expires_at else None
        ))
        conn.commit()


def revoke_server_host_manager(
    guild_id: int,
    user_id: int
):
    with closing(db()) as conn:
        conn.execute("""
            UPDATE server_host_managers
            SET enabled=0
            WHERE guild_id=? AND user_id=?
        """, (
            int(guild_id),
            int(user_id)
        ))
        conn.commit()


def server_host_manager_access(
    user_id: int,
    guild_id: int
):
    now = int(time.time())
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM server_host_managers
            WHERE guild_id=?
              AND user_id=?
              AND enabled=1
              AND (expires_at IS NULL OR expires_at>?)
        """, (
            int(guild_id),
            int(user_id),
            now
        )).fetchone()


def server_host_manager_guild_ids(
    user_id: int
) -> list[int]:
    now = int(time.time())
    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT guild_id
            FROM server_host_managers
            WHERE user_id=?
              AND enabled=1
              AND (expires_at IS NULL OR expires_at>?)
            ORDER BY guild_id
        """, (
            int(user_id),
            now
        )).fetchall()

    return [int(row["guild_id"]) for row in rows]




def host_manager_guild_ids(user_id: int) -> list[int]:
    guild_ids = []

    for guild_id in server_host_manager_guild_ids(
        user_id
    ):
        if guild_id not in guild_ids:
            guild_ids.append(guild_id)

    for row in host_manager_rows(user_id):
        guild_id = int(row["guild_id"])
        if guild_id not in guild_ids:
            guild_ids.append(guild_id)

    return guild_ids


def host_manager_has_guild_access(
    user_id: int,
    guild_id: int
) -> bool:
    return int(guild_id) in host_manager_guild_ids(user_id)


def host_manager_visible_hosts(
    user_id: int,
    guild_id: int
):
    if not host_manager_has_guild_access(
        user_id,
        guild_id
    ):
        return []

    return get_hosts(int(guild_id))


def host_is_assigned_to_manager(user_id: int, host_id: int) -> bool:
    return host_manager_access(user_id, host_id) is not None


def host_manager_access(user_id: int, host_id: int):
    now = int(time.time())
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM host_managers
            WHERE host_id=? AND user_id=?
              AND (expires_at IS NULL OR expires_at>?)
        """, (
            int(host_id),
            int(user_id),
            now
        )).fetchone()


def host_manager_has_permission(
    user_id: int,
    host_id: int,
    permission: str
) -> bool:
    row = host_manager_access(user_id, host_id)
    if not row:
        return False

    column = HOST_MANAGER_PERMISSION_COLUMNS.get(permission)
    if not column:
        return False

    return bool(row[column])



def host_manager_pref(
    user_id: int,
    host_id: int
):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM host_manager_preferences
            WHERE user_id=? AND host_id=?
        """, (
            int(user_id),
            int(host_id)
        )).fetchone()


def set_host_manager_favorite(
    user_id: int,
    host_id: int,
    favorite: bool
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO host_manager_preferences(
                host_id, user_id, favorite, onboarding_seen, updated_at
            )
            VALUES(?,?,?,0,?)
            ON CONFLICT(host_id, user_id)
            DO UPDATE SET
                favorite=excluded.favorite,
                updated_at=excluded.updated_at
        """, (
            int(host_id),
            int(user_id),
            1 if favorite else 0,
            int(time.time())
        ))
        conn.commit()


def mark_host_manager_onboarding(
    user_id: int,
    host_id: int
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO host_manager_preferences(
                host_id, user_id, favorite, onboarding_seen, updated_at
            )
            VALUES(?,?,0,1,?)
            ON CONFLICT(host_id, user_id)
            DO UPDATE SET
                onboarding_seen=1,
                updated_at=excluded.updated_at
        """, (
            int(host_id),
            int(user_id),
            int(time.time())
        ))
        conn.commit()


def host_manager_needs_onboarding(user_id: int) -> bool:
    rows = host_manager_rows(user_id)
    if not rows:
        return False

    for row in rows:
        pref = host_manager_pref(
            user_id,
            int(row["host_id"])
        )
        if not pref or not pref["onboarding_seen"]:
            return True

    return False


def host_health_label(host) -> tuple[str, str]:
    if not host["enabled"]:
        return "⏸️", "Paused"

    errors = int(host["error_count"] or 0)

    if host["last_error"] and errors >= ERROR_ALERT_THRESHOLD:
        return "🔴", "Error"

    if host["last_error"] or errors > 0:
        return "🟡", "Warning"

    return "🟢", "Healthy"


def host_manager_guilds(user_id: int):
    guild_ids = host_manager_guild_ids(user_id)
    result = []

    for guild_id in guild_ids:
        guild = bot.get_guild(int(guild_id))
        if guild:
            result.append(guild)

    return result


def host_manager_hosts_for_guild(
    user_id: int,
    guild_id: int
):
    rows = host_manager_visible_hosts(
        user_id,
        guild_id
    )

    def sort_key(host):
        pref = host_manager_pref(
            user_id,
            int(host["id"])
        )
        favorite = int(pref["favorite"]) if pref else 0
        assigned = 1 if host_manager_access(
            user_id,
            int(host["id"])
        ) else 0

        return (
            -favorite,
            -assigned,
            str(host["platform"]),
            int(host["id"])
        )

    return sorted(rows, key=sort_key)


def host_manager_latest_notifications(
    user_id: int,
    guild_id: Optional[int] = None,
    limit: int = 10
):
    managed_ids = [
        int(row["host_id"])
        for row in host_manager_rows(user_id)
        if guild_id is None or int(row["guild_id"]) == int(guild_id)
    ]

    if not managed_ids:
        return []

    placeholders = ",".join("?" for _ in managed_ids)
    params = list(managed_ids)
    sql = f"""
        SELECT nh.*, h.platform, h.target, h.display_name
        FROM notification_history nh
        LEFT JOIN hosts h ON h.id=nh.host_id
        WHERE nh.host_id IN ({placeholders})
    """

    if guild_id is not None:
        sql += " AND nh.guild_id=?"
        params.append(int(guild_id))

    sql += " ORDER BY nh.id DESC LIMIT ?"
    params.append(max(1, min(25, int(limit))))

    with closing(db()) as conn:
        return conn.execute(
            sql,
            tuple(params)
        ).fetchall()


def host_manager_problem_hosts(
    user_id: int,
    guild_id: Optional[int] = None
):
    rows = (
        host_manager_hosts_for_guild(user_id, guild_id)
        if guild_id is not None
        else [
            get_host(int(row["host_id"]))
            for row in host_manager_rows(user_id)
        ]
    )

    return [
        row
        for row in rows
        if row and (
            not row["enabled"]
            or row["last_error"]
            or int(row["error_count"] or 0) > 0
        )
    ]


def host_manager_activity_rows(
    user_id: int,
    limit: int = 10
):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT hma.*, h.platform, h.target, h.display_name, h.guild_id
            FROM host_manager_activity hma
            LEFT JOIN hosts h ON h.id=hma.host_id
            WHERE hma.user_id=?
            ORDER BY hma.id DESC
            LIMIT ?
        """, (
            int(user_id),
            max(1, min(25, int(limit)))
        )).fetchall()


def create_host_access_request(
    user_id: int,
    host_id: int
) -> int:
    host = get_host(host_id)
    if not host:
        raise ValueError("Host tidak ditemukan.")

    if not host_manager_has_guild_access(
        user_id,
        int(host["guild_id"])
    ):
        raise ValueError("Kamu tidak memiliki akses ke server host ini.")

    if host_manager_access(user_id, host_id):
        raise ValueError("Kamu sudah memiliki akses kelola host ini.")

    with closing(db()) as conn:
        existing = conn.execute("""
            SELECT id
            FROM host_access_requests
            WHERE host_id=? AND user_id=? AND status='pending'
        """, (
            int(host_id),
            int(user_id)
        )).fetchone()

        if existing:
            return int(existing["id"])

        cur = conn.execute("""
            INSERT INTO host_access_requests(
                guild_id, host_id, user_id, status, created_at
            )
            VALUES(?,?,?,'pending',?)
        """, (
            int(host["guild_id"]),
            int(host_id),
            int(user_id),
            int(time.time())
        ))
        conn.commit()
        return int(cur.lastrowid)


def get_host_access_request(request_id: int):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM host_access_requests
            WHERE id=?
        """, (int(request_id),)).fetchone()


def process_host_access_request(
    request_id: int,
    *,
    approved: bool,
    actor_id: int
):
    row = get_host_access_request(request_id)
    if not row or row["status"] != "pending":
        return False

    if approved:
        assign_host_manager(
            int(row["host_id"]),
            int(row["user_id"]),
            assigned_by=int(actor_id),
            permissions=set(HOST_MANAGER_PERMISSION_COLUMNS)
        )

    with closing(db()) as conn:
        conn.execute("""
            UPDATE host_access_requests
            SET status=?,
                processed_by=?,
                processed_at=?
            WHERE id=? AND status='pending'
        """, (
            "approved" if approved else "denied",
            int(actor_id),
            int(time.time()),
            int(request_id)
        ))
        conn.commit()

    return True


def host_manager_permission_text(
    user_id: int,
    host_id: int
) -> str:
    access = host_manager_access(user_id, host_id)

    if not access:
        return "👁️ Read-only"

    labels = {
        "edit_messages": "Edit pesan",
        "schedule": "Jadwal",
        "pause": "Pause",
        "recheck": "Recheck",
        "history": "History",
        "test": "Test",
    }

    lines = []
    for key, column in HOST_MANAGER_PERMISSION_COLUMNS.items():
        mark = "✅" if access[column] else "❌"
        lines.append(f"{mark} {labels.get(key, key)}")

    return "\n".join(lines)


HOST_TEMPLATE_PRESETS = {
    "live_simple": "🔴 {creator} sedang LIVE di {platform}!\\n{url}",
    "live_hype": "🎉 {creator} lagi LIVE sekarang! Jangan ketinggalan 🔥\\n{url}",
    "post_simple": "🆕 Ada konten baru dari {creator} di {platform}.\\n{url}",
    "end_simple": "⚫ LIVE {creator} sudah selesai.",
}


def apply_host_template_preset(
    host_id: int,
    preset: str
):
    if preset == "reset":
        clear_host_messages(host_id)
        return

    value = HOST_TEMPLATE_PRESETS.get(preset)
    if not value:
        raise ValueError("Preset tidak ditemukan.")

    with closing(db()) as conn:
        if preset.startswith("post_"):
            conn.execute(
                "UPDATE hosts SET custom_post_message=? WHERE id=?",
                (value, int(host_id))
            )
        elif preset.startswith("end_"):
            conn.execute(
                "UPDATE hosts SET custom_end_message=? WHERE id=?",
                (value, int(host_id))
            )
        else:
            conn.execute(
                "UPDATE hosts SET custom_live_message=? WHERE id=?",
                (value, int(host_id))
            )
        conn.commit()


def assign_host_manager(
    host_id: int,
    user_id: int,
    *,
    assigned_by: int,
    permissions: Optional[set[str]] = None,
    expires_at: Optional[int] = None
):
    host = get_host(host_id)
    if not host:
        raise ValueError("Host tidak ditemukan.")

    permissions = permissions or set(HOST_MANAGER_PERMISSION_COLUMNS)
    values = {
        key: 1 if key in permissions else 0
        for key in HOST_MANAGER_PERMISSION_COLUMNS
    }

    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO host_managers(
                host_id, user_id,
                can_edit_messages, can_schedule, can_pause,
                can_recheck, can_history, can_test,
                assigned_by, assigned_at, expires_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(host_id, user_id)
            DO UPDATE SET
                can_edit_messages=excluded.can_edit_messages,
                can_schedule=excluded.can_schedule,
                can_pause=excluded.can_pause,
                can_recheck=excluded.can_recheck,
                can_history=excluded.can_history,
                can_test=excluded.can_test,
                assigned_by=excluded.assigned_by,
                assigned_at=excluded.assigned_at,
                expires_at=excluded.expires_at
        """, (
            int(host_id),
            int(user_id),
            values["edit_messages"],
            values["schedule"],
            values["pause"],
            values["recheck"],
            values["history"],
            values["test"],
            int(assigned_by),
            int(time.time()),
            int(expires_at) if expires_at else None
        ))
        conn.commit()


def revoke_host_manager(host_id: int, user_id: int):
    with closing(db()) as conn:
        conn.execute(
            "DELETE FROM host_managers WHERE host_id=? AND user_id=?",
            (int(host_id), int(user_id))
        )
        conn.commit()


def list_host_managers(host_id: int):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM host_managers
            WHERE host_id=?
            ORDER BY assigned_at ASC
        """, (int(host_id),)).fetchall()


def log_host_manager_action(
    host_id: int,
    user_id: int,
    action: str,
    detail: Optional[str] = None
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO host_manager_activity(
                host_id, user_id, action, detail, created_at
            )
            VALUES(?,?,?,?,?)
        """, (
            int(host_id),
            int(user_id),
            action[:100],
            detail[:1000] if detail else None,
            int(time.time())
        ))
        conn.commit()


def host_manager_stats(host_id: int) -> dict:
    now = int(time.time())
    cutoff_7d = now - 7 * 86400

    with closing(db()) as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                AVG(CASE WHEN latency_ms IS NOT NULL THEN latency_ms END) AS latency
            FROM notification_history
            WHERE host_id=? AND created_at>=?
        """, (
            int(host_id),
            cutoff_7d
        )).fetchone()

    total = int(row["total"] or 0)
    sent = int(row["sent"] or 0)
    failed = int(row["failed"] or 0)

    return {
        "total": total,
        "sent": sent,
        "failed": failed,
        "success_rate": round((sent / total) * 100, 1) if total else 0.0,
        "latency": int(row["latency"] or 0),
    }


def add_host(
    guild_id: int,
    platform: str,
    target: str,
    display_name=None,
    extra=None
):
    ensure_guild(guild_id)

    platform = platform.lower().strip()
    target = normalize_social_target(platform, target)

    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(
            "Platform tidak didukung. Gunakan: "
            + ", ".join(sorted(SUPPORTED_PLATFORMS))
        )

    if not target:
        raise ValueError("Target/username tidak boleh kosong.")

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

        conn.execute(
            "DELETE FROM social_content_state WHERE host_id=?",
            (host_id,)
        )
        conn.execute(
            "DELETE FROM host_managers WHERE host_id=?",
            (host_id,)
        )
        conn.execute(
            "DELETE FROM host_manager_activity WHERE host_id=?",
            (host_id,)
        )
        conn.execute(
            "DELETE FROM host_manager_preferences WHERE host_id=?",
            (host_id,)
        )
        conn.execute(
            "DELETE FROM host_access_requests WHERE host_id=?",
            (host_id,)
        )
        conn.execute(
            "DELETE FROM host_manager_warnings WHERE host_id=?",
            (host_id,)
        )

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



async def send_host_error_alert(host):
    if int(host["error_count"] or 0) < ERROR_ALERT_THRESHOLD:
        return

    with closing(db()) as conn:
        row = conn.execute(
            "SELECT * FROM error_alerts WHERE host_id=?",
            (host["id"],)
        ).fetchone()

    last_count = int(row["last_alert_error_count"] or 0) if row else 0

    if int(host["error_count"] or 0) <= last_count:
        return

    embed = discord.Embed(
        title="🚨 Host Monitor Error",
        description=(
            f"Host **#{host['id']}** mengalami error berulang."
        ),
        color=discord.Color.red()
    )
    embed.add_field(
        name="Host",
        value=f"{host['platform']} • `{host['target']}`",
        inline=False
    )
    embed.add_field(
        name="Error Count",
        value=str(host["error_count"]),
        inline=True
    )
    embed.add_field(
        name="Error",
        value=str(host["last_error"] or "-")[:1000],
        inline=False
    )

    for owner_id in primary_owner_ids():
        try:
            user = bot.get_user(owner_id) or await bot.fetch_user(owner_id)
            await user.send(embed=embed)
        except Exception:
            pass

    # Host Manager assigned to this host also receives a focused warning.
    for manager in list_host_managers(int(host["id"])):
        now = int(time.time())
        if manager["expires_at"] and int(manager["expires_at"]) <= now:
            continue

        try:
            user = bot.get_user(int(manager["user_id"])) or await bot.fetch_user(
                int(manager["user_id"])
            )
            await user.send(
                embed=discord.Embed(
                    title="⚠️ Host Kamu Bermasalah",
                    description=(
                        f"**{platform_display_name(host['platform'])} • "
                        f"{host['display_name'] or host['target']}**\n"
                        f"Error: `{str(host['last_error'] or '-')[:700]}`\n"
                        f"Jumlah error: **{host['error_count']}**\n\n"
                        "Buka `/menu → Host Saya` lalu gunakan **Recheck** "
                        "jika permission-mu mengizinkan."
                    ),
                    color=discord.Color.orange()
                )
            )
        except Exception:
            pass

    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO error_alerts(host_id, last_alert_error_count, last_alert_at)
            VALUES(?,?,?)
            ON CONFLICT(host_id)
            DO UPDATE SET
                last_alert_error_count=excluded.last_alert_error_count,
                last_alert_at=excluded.last_alert_at
        """, (
            host["id"],
            host["error_count"],
            int(time.time())
        ))
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

            threshold_row = conn.execute(
                "SELECT auto_pause_threshold FROM hosts WHERE id=?",
                (host_id,)
            ).fetchone()

            pause_threshold = int(
                (threshold_row["auto_pause_threshold"] if threshold_row else None)
                or AUTO_PAUSE_ERRORS
            )
            auto_disable = errors >= pause_threshold

            conn.execute("""
                UPDATE hosts SET
                    last_check=?,
                    last_error=?,
                    error_count=?,
                    cooldown_until=?,
                    enabled=CASE WHEN ? THEN 0 ELSE enabled END
                WHERE id=?
            """, (
                now,
                (error or "Unknown error")[:1000],
                errors,
                cooldown,
                1 if auto_disable else 0,
                host_id
            ))

        conn.commit()

    if not success:
        refreshed = get_host(host_id)
        if (
            refreshed
            and not refreshed["enabled"]
            and int(refreshed["error_count"] or 0) >= int(
                refreshed["auto_pause_threshold"] or AUTO_PAUSE_ERRORS
            )
        ):
            mark_host_auto_paused(host_id)



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

        conn.execute("""
            INSERT INTO schema_meta(id, version, updated_at)
            VALUES(1,?,?)
            ON CONFLICT(id)
            DO UPDATE SET
                version=excluded.version,
                updated_at=excluded.updated_at
        """, (
            CURRENT_SCHEMA_VERSION,
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



def create_rollback_snapshot(
    guild_id: int,
    reason: str,
    actor_id: Optional[int] = None
) -> int:
    payload = export_guild_backup(int(guild_id))
    with closing(db()) as conn:
        cur = conn.execute("""
            INSERT INTO rollback_snapshots(
                guild_id, reason, payload_json, created_by, created_at
            )
            VALUES(?,?,?,?,?)
        """, (
            int(guild_id),
            str(reason)[:200],
            json.dumps(payload, ensure_ascii=False),
            int(actor_id) if actor_id else None,
            int(time.time())
        ))
        conn.commit()
        return int(cur.lastrowid)


def pause_excess_hosts_for_free(guild_id: int) -> int:
    hosts = list(get_hosts(int(guild_id)))
    active_hosts = [h for h in hosts if bool(h["enabled"])]
    if len(active_hosts) <= FREE_HOST_LIMIT:
        return 0

    paused = 0
    now = int(time.time())
    # Preserve up to FREE_HOST_LIMIT hosts that are actually active.  Disabled
    # hosts must not consume a keep slot, otherwise downgrade can leave fewer
    # usable hosts than the FREE allowance.
    keep_ids = {int(h["id"]) for h in active_hosts[:FREE_HOST_LIMIT]}

    with closing(db()) as conn:
        for host in active_hosts:
            host_id = int(host["id"])
            if host_id in keep_ids:
                continue

            conn.execute("UPDATE hosts SET enabled=0 WHERE id=?", (host_id,))
            conn.execute("""
                INSERT INTO host_plan_pause(host_id, guild_id, paused_at, reason)
                VALUES(?,?,?,'free_limit')
                ON CONFLICT(host_id)
                DO UPDATE SET
                    guild_id=excluded.guild_id,
                    paused_at=excluded.paused_at,
                    reason=excluded.reason
            """, (host_id, int(guild_id), now))
            paused += 1
        conn.commit()

    return paused


def reactivate_plan_paused_hosts(guild_id: int) -> int:
    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT host_id FROM host_plan_pause
            WHERE guild_id=?
            ORDER BY paused_at ASC
        """, (int(guild_id),)).fetchall()

        restored = 0
        for row in rows:
            host_id = int(row["host_id"])
            exists = conn.execute(
                "SELECT 1 FROM hosts WHERE id=? AND guild_id=?",
                (host_id, int(guild_id))
            ).fetchone()
            if exists:
                conn.execute("UPDATE hosts SET enabled=1 WHERE id=?", (host_id,))
                restored += 1

        conn.execute("DELETE FROM host_plan_pause WHERE guild_id=?", (int(guild_id),))
        conn.commit()

    return restored


def mark_host_auto_paused(host_id: int):
    host = get_host(int(host_id))
    if not host:
        return

    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO host_auto_recovery(
                host_id, guild_id, auto_paused_at, last_retry_at, retry_count
            )
            VALUES(?,?,?,NULL,0)
            ON CONFLICT(host_id)
            DO UPDATE SET
                guild_id=excluded.guild_id,
                auto_paused_at=excluded.auto_paused_at
        """, (
            int(host_id),
            int(host["guild_id"]),
            int(time.time())
        ))
        conn.commit()


def clear_host_auto_recovery(host_id: int):
    with closing(db()) as conn:
        conn.execute(
            "DELETE FROM host_auto_recovery WHERE host_id=?",
            (int(host_id),)
        )
        conn.commit()


def server_usage_stats(guild_id: int, days: int = 7) -> dict:
    since = int(time.time()) - max(1, int(days)) * 86400
    with closing(db()) as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                AVG(CASE WHEN latency_ms IS NOT NULL THEN latency_ms END) AS latency
            FROM notification_history
            WHERE guild_id=? AND created_at>=?
        """, (int(guild_id), since)).fetchone()

    return {
        "total": int(row["total"] or 0),
        "sent": int(row["sent"] or 0),
        "failed": int(row["failed"] or 0),
        "latency": round(float(row["latency"] or 0)),
    }


def server_health_score(guild_id: int) -> int:
    hosts = list(get_hosts(int(guild_id)))
    if not hosts:
        return 100
    return round(sum(host_health_score(h) for h in hosts) / len(hosts))


def get_server_risk_meta(guild_id: int):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM server_risk_meta WHERE guild_id=?",
            (int(guild_id),)
        ).fetchone()


def set_server_risk_meta(
    guild_id: int,
    *,
    reason: str = "",
    expires_at: Optional[int] = None,
    actor_id: Optional[int] = None
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO server_risk_meta(
                guild_id, reason, expires_at, updated_by, updated_at
            )
            VALUES(?,?,?,?,?)
            ON CONFLICT(guild_id)
            DO UPDATE SET
                reason=excluded.reason,
                expires_at=excluded.expires_at,
                updated_by=excluded.updated_by,
                updated_at=excluded.updated_at
        """, (
            int(guild_id),
            str(reason)[:500],
            int(expires_at) if expires_at else None,
            int(actor_id) if actor_id else None,
            int(time.time())
        ))
        conn.commit()


def effective_access_state(guild_id: int) -> str:
    settings = get_guild_settings(int(guild_id))
    state = str(settings["access_state"] or "allowed")
    meta = get_server_risk_meta(guild_id)

    if (
        state in {"warning", "suspended"}
        and meta
        and meta["expires_at"]
        and int(meta["expires_at"]) <= int(time.time())
    ):
        set_access_state(guild_id, "allowed")
        set_server_risk_meta(
            guild_id,
            reason="Status risiko kedaluwarsa otomatis.",
            expires_at=None
        )
        return "allowed"

    return state


def platform_maintenance_key(platform: str) -> str:
    keys = platform_feature_keys(platform)
    return keys[0] if keys else ""


def platform_enabled(guild_id: int, platform: str) -> bool:
    keys = platform_feature_keys(platform)
    return all(feature_enabled(guild_id, key) for key in keys) if keys else True


def set_platform_enabled(guild_id: int, platform: str, enabled: bool):
    keys = platform_feature_keys(platform)
    if not keys:
        raise ValueError("Platform tidak valid.")

    flags = feature_flags_for_guild(guild_id)
    for key in keys:
        if key not in flags:
            raise ValueError(f"Feature tidak valid: {key}")
        flags[key] = bool(enabled)

    with closing(db()) as conn:
        conn.execute(
            "UPDATE guild_settings SET feature_flags=? WHERE guild_id=?",
            (json.dumps(flags), int(guild_id))
        )
        conn.commit()


def set_single_feature(guild_id: int, feature: str, enabled: bool):
    flags = feature_flags_for_guild(guild_id)
    if feature not in flags:
        raise ValueError("Feature tidak valid.")

    flags[feature] = bool(enabled)
    with closing(db()) as conn:
        conn.execute(
            "UPDATE guild_settings SET feature_flags=? WHERE guild_id=?",
            (json.dumps(flags), int(guild_id))
        )
        conn.commit()


def coupon_get(code_value: str):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM premium_coupons WHERE code=?",
            (str(code_value).strip().upper(),)
        ).fetchone()


def coupon_discount(code_value: str, price: int) -> tuple[int, int]:
    row = coupon_get(code_value)
    if not row or not row["enabled"]:
        raise ValueError("Kode promo tidak valid.")

    now = int(time.time())
    if row["expires_at"] and int(row["expires_at"]) <= now:
        raise ValueError("Kode promo sudah kedaluwarsa.")

    if (
        row["max_uses"] is not None
        and int(row["used_count"] or 0) >= int(row["max_uses"])
    ):
        raise ValueError("Kuota kode promo sudah habis.")

    value = int(row["discount_value"])
    if row["discount_type"] == "percent":
        discount = min(int(price), max(0, int(price) * value // 100))
    else:
        discount = min(int(price), max(0, value))

    return max(0, int(price) - discount), discount


def redeem_coupon_atomic(
    order_id: int,
    code_value: str,
    *,
    user_id: int,
    guild_id: int,
    base_price: int
) -> tuple[int, int]:
    code_value = str(code_value).strip().upper()
    now = int(time.time())

    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute("""
            SELECT discount_amount
            FROM premium_coupon_redemptions
            WHERE order_id=? AND code=?
        """, (int(order_id), code_value)).fetchone()

        if existing:
            discount = int(existing["discount_amount"] or 0)
            conn.commit()
            return max(0, int(base_price) - discount), discount

        row = conn.execute(
            "SELECT * FROM premium_coupons WHERE code=?",
            (code_value,)
        ).fetchone()

        if not row or not row["enabled"]:
            conn.rollback()
            raise ValueError("Kode promo tidak valid.")
        if row["expires_at"] and int(row["expires_at"]) <= now:
            conn.rollback()
            raise ValueError("Kode promo sudah kedaluwarsa.")
        if (
            row["max_uses"] is not None
            and int(row["used_count"] or 0) >= int(row["max_uses"])
        ):
            conn.rollback()
            raise ValueError("Kuota kode promo sudah habis.")

        value = int(row["discount_value"])
        if row["discount_type"] == "percent":
            discount = min(int(base_price), max(0, int(base_price) * value // 100))
        else:
            discount = min(int(base_price), max(0, value))

        cur = conn.execute("""
            UPDATE premium_coupons
            SET used_count=used_count+1
            WHERE code=? AND enabled=1
              AND (max_uses IS NULL OR used_count < max_uses)
        """, (code_value,))
        if cur.rowcount != 1:
            conn.rollback()
            raise ValueError("Kuota kode promo sudah habis.")

        conn.execute("""
            INSERT INTO premium_coupon_redemptions(
                order_id, code, discount_amount,
                user_id, guild_id, redeemed_at
            )
            VALUES(?,?,?,?,?,?)
        """, (
            int(order_id), code_value, int(discount),
            int(user_id), int(guild_id), now
        ))
        conn.commit()

    return max(0, int(base_price) - discount), discount


def create_coupon(
    code_value: str,
    discount_type: str,
    discount_value: int,
    *,
    expires_at: Optional[int] = None,
    max_uses: Optional[int] = None,
    actor_id: Optional[int] = None
):
    kind = "percent" if str(discount_type).lower() == "percent" else "fixed"
    code_value = str(code_value).strip().upper()
    if not code_value:
        raise ValueError("Kode promo kosong.")

    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO premium_coupons(
                code, discount_type, discount_value, expires_at,
                max_uses, used_count, enabled, created_by, created_at
            )
            VALUES(?,?,?,?,?,0,1,?,?)
            ON CONFLICT(code)
            DO UPDATE SET
                discount_type=excluded.discount_type,
                discount_value=excluded.discount_value,
                expires_at=excluded.expires_at,
                max_uses=excluded.max_uses,
                enabled=1
        """, (
            code_value,
            kind,
            max(0, int(discount_value)),
            int(expires_at) if expires_at else None,
            int(max_uses) if max_uses else None,
            int(actor_id) if actor_id else None,
            int(time.time())
        ))
        conn.commit()


def record_premium_event(
    order_id: int,
    status: str,
    *,
    actor_id: Optional[int] = None,
    detail: str = ""
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO premium_order_events(
                order_id, status, actor_id, detail, created_at
            )
            VALUES(?,?,?,?,?)
        """, (
            int(order_id),
            str(status)[:80],
            int(actor_id) if actor_id else None,
            str(detail)[:500],
            int(time.time())
        ))
        conn.commit()


def database_integrity_report() -> dict:
    cutoff = int(time.time()) - 1800
    with closing(db()) as conn:
        orphan_managers = conn.execute("""
            SELECT COUNT(*) AS total
            FROM host_managers hm
            LEFT JOIN hosts h ON h.id=hm.host_id
            WHERE h.id IS NULL
        """).fetchone()["total"]

        stuck_access = conn.execute("""
            SELECT COUNT(*) AS total
            FROM server_host_access_requests
            WHERE status='processing'
              AND processed_at<?
        """, (cutoff,)).fetchone()["total"]

        stuck_hosts = conn.execute("""
            SELECT COUNT(*) AS total
            FROM host_creation_requests
            WHERE status='processing'
              AND processed_at<?
        """, (cutoff,)).fetchone()["total"]

    return {
        "orphan_managers": int(orphan_managers or 0),
        "stuck_access": int(stuck_access or 0),
        "stuck_hosts": int(stuck_hosts or 0),
    }


def repair_database_integrity() -> dict:
    report = database_integrity_report()
    cutoff = int(time.time()) - 1800

    with closing(db()) as conn:
        conn.execute("""
            DELETE FROM host_managers
            WHERE host_id NOT IN (SELECT id FROM hosts)
        """)
        conn.execute("""
            UPDATE server_host_access_requests
            SET status='pending', processed_by=NULL, processed_at=NULL
            WHERE status='processing' AND processed_at<?
        """, (cutoff,))
        conn.execute("""
            UPDATE host_creation_requests
            SET status='pending', processed_by=NULL, processed_at=NULL
            WHERE status='processing' AND processed_at<?
        """, (cutoff,))
        conn.commit()

    return report



# ============================================================
# PLAN / PREMIUM HELPERS
# ============================================================

def guilds_by_plan(plan: str):
    plan = "premium" if plan == "premium" else "free"
    result = []

    for guild in bot.guilds:
        try:
            settings = get_guild_settings(guild.id)
            if settings["plan"] == plan:
                result.append(guild)
        except Exception:
            log.exception("Gagal membaca plan guild_id=%s", guild.id)

    return result


def primary_owner_ids():
    return sorted(OWNER_IDS)


async def notify_primary_owners_premium_request(
    guild: discord.Guild,
    requester: discord.abc.User,
    days: int,
    price: int,
    order_id: int
):
    sent = 0

    embed = discord.Embed(
        title=f"⭐ Premium #{order_id}",
        description=(
            f"**{guild.name}** • **{days} hari** • **{rupiah(price)}**\n"
            f"Peminta: <@{requester.id}>\n"
            "Buka `/owner` → **Request** untuk memproses."
        ),
        color=discord.Color.gold()
    )

    for owner_id in primary_owner_ids():
        try:
            user = bot.get_user(owner_id) or await bot.fetch_user(owner_id)
            await user.send(embed=embed)
            sent += 1
        except Exception:
            log.exception(
                "Gagal mengirim premium request ke owner_id=%s",
                owner_id
            )

    await send_payment_admin_log(
        "🆕 Premium Request Baru",
        (
            f"Invoice: `{ensure_invoice_ref(order_id)}`\n"
            f"Server: **{guild.name}** (`{guild.id}`)\n"
            f"User: <@{requester.id}>\n"
            f"Paket: **{days} hari** • **{rupiah(price)}**"
        ),
        guild_id=guild.id
    )

    add_activity(
        guild.id,
        requester.id,
        "Premium Request",
        (
            f"Order #{order_id}; {days} hari; {rupiah(price)}; "
            f"dikirim ke {sent} owner."
        )
    )

    return sent


# ============================================================
# PREMIUM PACKAGE DATABASE
# ============================================================

def get_premium_packages():
    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT id, days, price, enabled
            FROM premium_packages
            WHERE enabled=1
            ORDER BY days ASC
        """).fetchall()

    if rows:
        return [(int(r["days"]), int(r["price"])) for r in rows]

    return PREMIUM_PACKAGES


def upsert_premium_package(days: int, price: int):
    days = max(1, int(days))
    price = max(0, int(price))

    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO premium_packages(days, price, enabled)
            VALUES(?,?,1)
            ON CONFLICT(days)
            DO UPDATE SET
                price=excluded.price,
                enabled=1
        """, (days, price))
        conn.commit()


def delete_premium_package(days: int):
    with closing(db()) as conn:
        conn.execute(
            "DELETE FROM premium_packages WHERE days=?",
            (int(days),)
        )
        conn.commit()


def premium_packages_text():
    packages = get_premium_packages()
    if not packages:
        return "Belum ada paket Premium."
    return "\n".join(
        f"⭐ **{days} hari** • **{rupiah(price)}**"
        for days, price in packages
    )


PLAN_FEATURE_LABELS = {
    "priority_polling": "Priority checker",
    "custom_templates": "Custom pesan",
    "webhook": "Webhook delivery",
    "extra_channels": "Multi-channel / multi-role",
    "advanced_schedule": "Jadwal & quiet hours",
    "custom_branding": "Custom branding",
    "manager_presets": "Manager permission preset",
    "data_export": "Export data server",
}


def premium_access_effective(guild_id: int, now_ts: Optional[int] = None) -> bool:
    """Return whether Premium benefits are effective right now.

    This check is deliberately independent from the hourly expiry loop so an
    expired plan cannot keep Premium entitlements for up to another hour.  A
    configured grace period remains honored.
    """
    settings = get_guild_settings(int(guild_id))
    if str(settings["plan"] or "free").lower() != "premium":
        return False

    expires_at = settings["premium_expires_at"]
    if not expires_at:
        return True

    now = int(now_ts or time.time())
    expires_at = int(expires_at)
    if now <= expires_at:
        return True

    grace_until = settings["premium_grace_until"]
    if grace_until:
        return now < int(grace_until)

    # Before the expiry loop has persisted premium_grace_until, honor the
    # configured grace directly from the expiry timestamp.
    if PREMIUM_GRACE_HOURS > 0:
        return now < (expires_at + PREMIUM_GRACE_HOURS * 3600)

    return False


def premium_entitlements(guild_id: int) -> dict:
    """Single source of truth for FREE/Premium capabilities.

    Keep every Premium gate routed through this helper so a hidden button, old
    interaction, or stale configuration cannot bypass the active plan.
    """
    settings = get_guild_settings(int(guild_id))
    stored_plan = str(settings["plan"] or "free").lower()
    premium = premium_access_effective(int(guild_id))
    plan = "premium" if premium else "free"

    return {
        "plan": plan,
        "stored_plan": stored_plan,
        "premium": premium,
        "host_limit": PREMIUM_HOST_LIMIT if premium else FREE_HOST_LIMIT,
        "analytics_days": 30 if premium else 7,
        "priority_polling": premium,
        "custom_templates": premium,
        "webhook": premium,
        "extra_channels": premium,
        "advanced_schedule": premium,
        "custom_branding": premium,
        "manager_presets": premium,
        "data_export": premium,
    }


def premium_feature_enabled(guild_id: int, feature: str) -> bool:
    return bool(premium_entitlements(int(guild_id)).get(str(feature), False))


async def require_premium_feature(
    interaction: discord.Interaction,
    guild_id: int,
    feature: str,
    label: Optional[str] = None
) -> bool:
    if premium_feature_enabled(int(guild_id), feature):
        return True
    feature_label = label or PLAN_FEATURE_LABELS.get(feature, feature)
    await safe_reply(
        interaction,
        f"🔒 **{feature_label}** tersedia di Premium. "
        "Konfigurasi lama tetap tersimpan dan aktif kembali setelah Premium diperpanjang."
    )
    return False


def premium_host_template(host, field: str) -> Optional[str]:
    if not premium_feature_enabled(int(host["guild_id"]), "custom_templates"):
        return None
    try:
        return host[field]
    except Exception:
        return None


def premium_entitlements_text(guild_id: int) -> str:
    e = premium_entitlements(guild_id)
    return (
        f"Host **{e['host_limit']}** • Riwayat/analytics **{e['analytics_days']} hari**\n"
        f"{'✅' if e['priority_polling'] else '🔒'} Priority checker • "
        f"{'✅' if e['advanced_schedule'] else '🔒'} Jadwal\n"
        f"{'✅' if e['custom_templates'] else '🔒'} Custom pesan • "
        f"{'✅' if e['custom_branding'] else '🔒'} Branding\n"
        f"{'✅' if e['extra_channels'] else '🔒'} Multi-channel • "
        f"{'✅' if e['webhook'] else '🔒'} Webhook • "
        f"{'✅' if e['data_export'] else '🔒'} Export"
    )


def plan_comparison_text() -> str:
    return (
        f"🆓 **FREE** — {FREE_HOST_LIMIT} host, analytics 7 hari, channel/role utama, "
        "notifikasi standar.\n"
        f"⭐ **PREMIUM** — hingga {PREMIUM_HOST_LIMIT} host, analytics 30 hari, "
        "priority checker, custom pesan/branding, jadwal & quiet hours, "
        "multi-channel/role, webhook, dan export data.\n\n"
        "Saat Premium berakhir, konfigurasi Premium **tidak dihapus**; fitur dikunci "
        "dan host di atas limit FREE dipause sampai Premium aktif kembali."
    )




def premium_plan_summary_embed(guild: discord.Guild):
    settings = get_guild_settings(guild.id)
    plan = "premium" if premium_access_effective(guild.id) else "free"
    hosts = len(get_hosts(guild.id))
    limit = host_limit_for_guild(guild.id)

    embed = discord.Embed(
        title=f"⭐ Premium • {guild.name}",
        description=("Beli atau perpanjang Premium untuk server ini. "
                     "Pembayaran dapat dilakukan Pemilik Server atau Host Manager aktif."),
        color=discord.Color.gold()
    )
    embed.add_field(
        name="Status",
        value="⭐ **PREMIUM**" if plan == "premium" else "🆓 **FREE**",
        inline=True
    )
    embed.add_field(
        name="Host",
        value=f"**{hosts}/{limit}**",
        inline=True
    )
    if plan == "premium":
        embed.add_field(
            name="Aktif Sampai",
            value=premium_expiry_text(guild.id),
            inline=False
        )
    embed.add_field(
        name="Paket",
        value=premium_packages_text(),
        inline=False
    )
    embed.add_field(
        name="Benefit",
        value=premium_entitlements_text(guild.id),
        inline=False
    )
    embed.add_field(
        name="FREE vs Premium",
        value=plan_comparison_text()[:1024],
        inline=False
    )
    embed.set_footer(text="Premium berlaku untuk seluruh server • pilih paket lalu buat invoice")
    return embed


def list_user_premium_orders(user_id: int, guild_id: int, limit: int = 8):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM premium_orders
            WHERE requester_id=? AND guild_id=?
            ORDER BY id DESC
            LIMIT ?
        """, (
            int(user_id),
            int(guild_id),
            max(1, min(20, int(limit)))
        )).fetchall()


def user_premium_history_embed(user_id: int, guild_id: int):
    rows = list_user_premium_orders(user_id, guild_id, 8)
    lines = []
    for row in rows:
        ref = row["invoice_ref"] or ensure_invoice_ref(row["id"])
        lines.append(
            f"• `{ref}` • **{row['days']} hari** • "
            f"{order_status_label(row['status'])}"
        )
    return discord.Embed(
        title="🧾 Riwayat Premium",
        description="\n".join(lines) if lines else "Belum ada transaksi Premium.",
        color=discord.Color.gold()
    )


def owner_payment_menu_embed():
    return discord.Embed(
        title="💳 Payment Center",
        description="Request • Riwayat • Premium DB • Pendapatan",
        color=discord.Color.gold()
    )


def transaction_history_embed(limit: int = 15):
    """Build the Global Owner transaction-history embed.

    Kept deliberately read-only and tolerant of partially migrated rows so the
    Riwayat button never fails just because an older invoice is missing newer
    payment columns.
    """
    rows = list_transaction_history(max(1, min(25, int(limit))))

    embed = discord.Embed(
        title="🧾 Riwayat Transaksi",
        color=discord.Color.blurple()
    )

    if not rows:
        embed.description = "Belum ada transaksi Premium."
        embed.set_footer(text="Menampilkan transaksi Premium terbaru")
        return embed

    lines = []
    for row in rows:
        keys = set(row.keys())
        order_id = int(row["id"])
        ref = row["invoice_ref"] if "invoice_ref" in keys else None
        if not ref:
            try:
                ref = ensure_invoice_ref(order_id)
            except Exception:
                ref = f"ORDER-{order_id}"

        status = str(row["status"] or "unknown")
        try:
            status_text = order_status_label(status)
        except Exception:
            status_text = status.replace("_", " ").title()

        days = int(row["days"] or 0)
        price = int(row["price"] or 0)
        expected = (
            int(row["expected_amount"] or 0)
            if "expected_amount" in keys else price
        )
        received = (
            int(row["received_amount"] or 0)
            if "received_amount" in keys else 0
        )
        created_at = int(row["created_at"] or 0)

        amount_text = rupiah(expected or price)
        if received:
            amount_text += f" • diterima {rupiah(received)}"

        when = f"<t:{created_at}:d>" if created_at else "-"
        lines.append(
            f"`{ref}` • **{days} hari** • {status_text}\n"
            f"{amount_text} • {when}"
        )

    # Discord embed descriptions are capped at 4096 characters.
    description = "\n\n".join(lines)
    if len(description) > 3900:
        description = description[:3897] + "..."

    embed.description = description
    embed.set_footer(text=f"{len(rows)} transaksi terbaru • tombol Refresh untuk memperbarui")
    return embed


def record_premium_customer_activation(order_id: int, *, source: str = "payment") -> None:
    """Persist an activated Premium purchase in a permanent customer ledger.

    Idempotent by order_id, so retries cannot double-count a purchase.
    """
    order = get_premium_order(int(order_id))
    if not order:
        raise ValueError("Order Premium tidak ditemukan.")

    activated_at = int(order["activated_at"] or time.time())
    expires_at = int(order["expires_at"] or 0) or None
    guild_id = int(order["guild_id"])
    requester_id = int(order["requester_id"])
    invoice_ref = order["invoice_ref"] or ensure_invoice_ref(int(order_id))
    amount = int(order["price"] or 0)
    guild = bot.get_guild(guild_id)
    guild_name = guild.name[:120] if guild and guild.name else None

    with closing(db()) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO premium_customer_ledger(
                order_id, guild_id, requester_id, invoice_ref, days, amount,
                activated_at, expires_at, source, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """, (
            int(order_id), guild_id, requester_id, invoice_ref,
            int(order["days"]), amount, activated_at, expires_at,
            str(source or "payment")[:64], int(time.time())
        ))

        agg = conn.execute("""
            SELECT MIN(activated_at) AS first_at, MAX(activated_at) AS last_at,
                   MAX(expires_at) AS max_expires, COUNT(*) AS total_orders,
                   SUM(days) AS total_days, SUM(amount) AS total_spent
            FROM premium_customer_ledger WHERE guild_id=?
        """, (guild_id,)).fetchone()
        first = conn.execute("""
            SELECT requester_id FROM premium_customer_ledger
            WHERE guild_id=? ORDER BY activated_at ASC, id ASC LIMIT 1
        """, (guild_id,)).fetchone()
        last = conn.execute("""
            SELECT requester_id, order_id FROM premium_customer_ledger
            WHERE guild_id=? ORDER BY activated_at DESC, id DESC LIMIT 1
        """, (guild_id,)).fetchone()
        settings = conn.execute("""
            SELECT plan, premium_expires_at, premium_grace_until
            FROM guild_settings WHERE guild_id=?
        """, (guild_id,)).fetchone()
        effective_until = int(
            (settings["premium_grace_until"] if settings else 0)
            or (settings["premium_expires_at"] if settings else 0)
            or 0
        )
        active_now = bool(
            settings and str(settings["plan"]) == "premium"
            and effective_until > int(time.time())
        )

        conn.execute("""
            INSERT INTO premium_customers(
                guild_id, guild_name, first_buyer_id, last_buyer_id,
                first_purchased_at, last_purchased_at, current_expires_at,
                total_orders, total_days, total_spent, last_order_id, status, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(guild_id) DO UPDATE SET
                guild_name=COALESCE(excluded.guild_name, premium_customers.guild_name),
                first_buyer_id=excluded.first_buyer_id,
                last_buyer_id=excluded.last_buyer_id,
                first_purchased_at=excluded.first_purchased_at,
                last_purchased_at=excluded.last_purchased_at,
                current_expires_at=excluded.current_expires_at,
                total_orders=excluded.total_orders,
                total_days=excluded.total_days,
                total_spent=excluded.total_spent,
                last_order_id=excluded.last_order_id,
                status=excluded.status,
                updated_at=excluded.updated_at
        """, (
            guild_id, guild_name, int(first["requester_id"]), int(last["requester_id"]),
            int(agg["first_at"]), int(agg["last_at"]), int(agg["max_expires"] or 0) or None,
            int(agg["total_orders"] or 0), int(agg["total_days"] or 0),
            int(agg["total_spent"] or 0), int(last["order_id"]),
            "active" if active_now else "expired", int(time.time())
        ))
        conn.commit()


def premium_customer_database_rows(limit: int = 15):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT * FROM premium_customers
            ORDER BY last_purchased_at DESC
            LIMIT ?
        """, (max(1, min(25, int(limit))),)).fetchall()


def premium_customer_database_embed(limit: int = 15):
    rows = premium_customer_database_rows(limit)
    now = int(time.time())
    with closing(db()) as conn:
        stats = conn.execute("""
            SELECT COUNT(*) AS customers,
                   COALESCE(SUM(total_orders),0) AS orders,
                   COALESCE(SUM(total_spent),0) AS spent
            FROM premium_customers
        """).fetchone()

    embed = discord.Embed(
        title="⭐ Premium DB",
        description=(
            f"Server tercatat: **{int(stats['customers'] or 0)}** • "
            f"aktivasi: **{int(stats['orders'] or 0)}** • "
            f"nilai paket: **{rupiah(int(stats['spent'] or 0))}**"
        ),
        color=discord.Color.gold()
    )

    if not rows:
        embed.add_field(name="Data", value="Belum ada pelanggan Premium.", inline=False)
        return embed

    lines = []
    for row in rows:
        gid = int(row["guild_id"])
        guild = bot.get_guild(gid)
        name = (guild.name if guild else row["guild_name"]) or f"Server {gid}"
        expires = int(row["current_expires_at"] or 0)
        settings = get_guild_settings(gid)
        effective_until = int(settings["premium_grace_until"] or settings["premium_expires_at"] or 0) if settings else 0
        active = bool(settings and str(settings["plan"]) == "premium" and effective_until > now)
        status = "🟢 Aktif" if active else "⚪ Expired"
        expiry_text = f"<t:{expires}:d>" if expires else "-"
        lines.append(
            f"**{name[:48]}** • {status}\n"
            f"`{gid}` • pembeli <@{int(row['last_buyer_id'])}> • "
            f"{int(row['total_orders'])}x • {rupiah(int(row['total_spent']))} • exp {expiry_text}"
        )

    text = "\n\n".join(lines)
    embed.description += "\n\n" + (text[:3600] + ("..." if len(text) > 3600 else ""))
    embed.set_footer(text=f"{len(rows)} pelanggan terbaru • data aktivasi disimpan permanen")
    return embed


class PremiumCustomerDatabaseView(discord.ui.View):
    def __init__(self, viewer_id: int):
        super().__init__(timeout=900)
        self.viewer_id = int(viewer_id)

    async def valid(self, interaction, minimum="read_only"):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel ini bukan milikmu.")
            return False
        return await require_owner_level(interaction, minimum)

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=premium_customer_database_embed(),
            view=PremiumCustomerDatabaseView(self.viewer_id)
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_payment_menu_embed(),
            view=OwnerPaymentMenuView(self.viewer_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView(self.viewer_id)
        )


def premium_queue_embed():
    counts = premium_order_counts()
    waiting = (
        counts["pending"] + counts["proof_submitted"]
        + counts["amount_mismatch"] + counts["amount_verified"]
        + counts["paid"]
    )
    embed = discord.Embed(
        title="💳 Premium • Queue",
        description=f"Perlu diproses: **{waiting}**",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="Status",
        value=(
            f"🟡 Baru **{counts['pending']}** • "
            f"🧾 Bukti **{counts['proof_submitted']}**\n"
            f"🔴 Selisih **{counts['amount_mismatch']}** • "
            f"🟢 Sesuai **{counts['amount_verified']}**\n"
            f"🔵 Dibayar **{counts['paid']}** • "
            f"⭐ Aktif **{counts['active']}**"
        ),
        inline=False
    )
    embed.set_footer(text="Pilih invoice untuk melihat detail")
    return embed


# ============================================================
# PROFESSIONAL PAYMENT CORE
# ============================================================

PAYMENT_STATE_TRANSITIONS = {
    "pending": {
        "proof_submitted", "amount_verified", "amount_mismatch",
        "underpaid", "overpaid", "paid", "rejected",
        "invoice_expired", "late_payment"
    },
    "proof_submitted": {
        "amount_verified", "amount_mismatch", "underpaid",
        "overpaid", "paid", "rejected", "invoice_expired",
        "late_payment"
    },
    "amount_mismatch": {
        "amount_verified", "underpaid", "overpaid",
        "rejected", "invoice_expired"
    },
    "underpaid": {
        "amount_verified", "overpaid", "rejected",
        "invoice_expired", "refund_pending"
    },
    "overpaid": {
        "amount_verified", "underpaid", "rejected",
        "invoice_expired", "refund_pending"
    },
    "amount_verified": {
        "paid", "processing", "active", "refund_pending"
    },
    "paid": {
        "processing", "active", "refund_pending"
    },
    "processing": {
        "active", "amount_verified", "paid", "refund_pending"
    },
    "active": {
        "expired", "refund_pending"
    },
    "expired": {
        "refund_pending"
    },
    "invoice_expired": {
        "late_payment", "rejected"
    },
    "late_payment": {
        "amount_verified", "refund_pending", "rejected"
    },
    "refund_pending": {
        "refunded", "refund_failed"
    },
    "refund_failed": {
        "refund_pending", "refunded"
    },
    "rejected": set(),
    "refunded": set(),
}


def payment_transition_allowed(current: str, target: str) -> bool:
    if current == target:
        return True
    return target in PAYMENT_STATE_TRANSITIONS.get(str(current), set())


def payment_reference_in_use(
    reference_id: str,
    *,
    exclude_order_id: Optional[int] = None
) -> bool:
    ref = str(reference_id or "").strip()
    if not ref:
        return False

    sql = """
        SELECT id FROM premium_orders
        WHERE payment_reference=?
    """
    args = [ref]

    if exclude_order_id is not None:
        sql += " AND id<>?"
        args.append(int(exclude_order_id))

    sql += " LIMIT 1"

    with closing(db()) as conn:
        return conn.execute(sql, tuple(args)).fetchone() is not None


def calculate_payment_risk(order) -> tuple[int, str, list[str]]:
    score = 0
    reasons = []

    scan_status = (
        str(order["proof_scan_status"] or "")
        if "proof_scan_status" in order.keys()
        else ""
    )

    if scan_status == "review":
        score += 25
        reasons.append("Bukti perlu review.")
    elif scan_status == "rejected":
        score += 60
        reasons.append("Bukti ditolak screening.")

    if (
        "proof_edit_software" in order.keys()
        and order["proof_edit_software"]
    ):
        score += 20
        reasons.append("Metadata editing terdeteksi.")

    if order["received_amount"] is not None:
        expected = int(order["expected_amount"] or order["price"])
        received = int(order["received_amount"])
        if received != expected:
            score += 30
            reasons.append("Nominal transfer tidak sesuai.")

    if "late_payment" in order.keys() and int(order["late_payment"] or 0):
        score += 20
        reasons.append("Pembayaran diterima setelah invoice expired.")

    with closing(db()) as conn:
        recent = conn.execute("""
            SELECT COUNT(*) AS total
            FROM premium_orders
            WHERE requester_id=?
              AND id<>?
              AND created_at>=?
              AND status IN (
                  'amount_mismatch','underpaid','overpaid',
                  'rejected','invoice_expired'
              )
        """, (
            int(order["requester_id"]),
            int(order["id"]),
            int(time.time()) - 30 * 86400
        )).fetchone()

    failed_recent = int(recent["total"] or 0)
    if failed_recent >= 3:
        bump = min(20, failed_recent * 3)
        score += bump
        reasons.append(f"{failed_recent} transaksi bermasalah dalam 30 hari.")

    score = max(0, min(100, score))

    if score < 25:
        level = "low"
    elif score < 50:
        level = "medium"
    elif score < 75:
        level = "high"
    else:
        level = "critical"

    if not reasons:
        reasons.append("Tidak ada indikator risiko utama.")

    return score, level, reasons


def refresh_payment_risk(order_id: int):
    order = get_premium_order(order_id)
    if not order:
        return

    score, level, reasons = calculate_payment_risk(order)

    with closing(db()) as conn:
        conn.execute("""
            UPDATE premium_orders
            SET risk_score=?, risk_level=?, risk_reasons=?, updated_at=?
            WHERE id=?
        """, (
            score,
            level,
            " | ".join(reasons)[:1500],
            int(time.time()),
            int(order_id)
        ))
        conn.commit()


def payment_health_update(
    *,
    success: bool,
    error: Optional[str] = None,
    callback: bool = False
):
    now = int(time.time())

    with closing(db()) as conn:
        if success:
            conn.execute("""
                UPDATE payment_health
                SET
                    last_callback_at=CASE WHEN ? THEN ? ELSE last_callback_at END,
                    last_success_at=?,
                    success_count=success_count+1,
                    last_error=NULL
                WHERE id=1
            """, (
                1 if callback else 0,
                now,
                now
            ))
        else:
            conn.execute("""
                UPDATE payment_health
                SET
                    last_callback_at=CASE WHEN ? THEN ? ELSE last_callback_at END,
                    last_failure_at=?,
                    failure_count=failure_count+1,
                    last_error=?
                WHERE id=1
            """, (
                1 if callback else 0,
                now,
                now,
                str(error or "Unknown payment error")[:1000]
            ))
        conn.commit()


def payment_health_row():
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM payment_health WHERE id=1"
        ).fetchone()


def settlement_stats(days: int = 1) -> dict:
    since = int(time.time()) - max(1, int(days)) * 86400

    with closing(db()) as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total_orders,
                SUM(CASE WHEN status IN ('active','expired') THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN status='refunded' THEN 1 ELSE 0 END) AS refunded,
                SUM(CASE WHEN status IN (
                    'pending','proof_submitted','amount_verified',
                    'paid','processing','underpaid','overpaid','late_payment'
                ) THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status IN ('active','expired') THEN price ELSE 0 END) AS gross,
                SUM(CASE WHEN status='refunded' THEN price ELSE 0 END) AS refund_total
            FROM premium_orders
            WHERE created_at>=?
        """, (since,)).fetchone()

    gross = int(row["gross"] or 0)
    refunds = int(row["refund_total"] or 0)

    return {
        "total_orders": int(row["total_orders"] or 0),
        "successful": int(row["successful"] or 0),
        "refunded": int(row["refunded"] or 0),
        "pending": int(row["pending"] or 0),
        "gross": gross,
        "refund_total": refunds,
        "net": gross - refunds,
    }


def payment_settlement_embed():
    d1 = settlement_stats(1)
    d30 = settlement_stats(30)

    embed = discord.Embed(
        title="💰 Payment Settlement",
        description="Ringkasan settlement berdasarkan data transaksi bot.",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="24 Jam",
        value=(
            f"Berhasil **{d1['successful']}** • Pending **{d1['pending']}**\n"
            f"Refund **{d1['refunded']}** • Net **{rupiah(d1['net'])}**"
        ),
        inline=False
    )
    embed.add_field(
        name="30 Hari",
        value=(
            f"Berhasil **{d30['successful']}** • Pending **{d30['pending']}**\n"
            f"Gross **{rupiah(d30['gross'])}** • Refund **{rupiah(d30['refund_total'])}**\n"
            f"Net **{rupiah(d30['net'])}**"
        ),
        inline=False
    )
    return embed


def payment_health_embed():
    health = payment_health_row()

    last_callback = (
        f"<t:{int(health['last_callback_at'])}:R>"
        if health and health["last_callback_at"]
        else "-"
    )
    last_success = (
        f"<t:{int(health['last_success_at'])}:R>"
        if health and health["last_success_at"]
        else "-"
    )
    last_failure = (
        f"<t:{int(health['last_failure_at'])}:R>"
        if health and health["last_failure_at"]
        else "-"
    )

    embed = discord.Embed(
        title="🩺 Payment Health",
        description=(
            f"Webhook: **{'ON' if PAYMENT_WEBHOOK_ENABLED else 'OFF'}**\n"
            f"Auto activation: **{'ON' if AUTO_ACTIVATE_VERIFIED_PAYMENTS else 'OFF'}**"
        ),
        color=discord.Color.green()
    )
    embed.add_field(
        name="Callback",
        value=(
            f"Terakhir: {last_callback}\n"
            f"Sukses: **{int(health['success_count'] or 0) if health else 0}**\n"
            f"Gagal: **{int(health['failure_count'] or 0) if health else 0}**"
        ),
        inline=True
    )
    embed.add_field(
        name="Status terakhir",
        value=(
            f"Sukses: {last_success}\n"
            f"Gagal: {last_failure}"
        ),
        inline=True
    )
    if health and health["last_error"]:
        embed.add_field(
            name="Error terakhir",
            value=f"`{str(health['last_error'])[:900]}`",
            inline=False
        )
    return embed


def payment_event_dlq_count() -> int:
    with closing(db()) as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS total
            FROM payment_event_dead_letter
            WHERE resolved_at IS NULL
        """).fetchone()
    return int(row["total"] or 0)


def payment_receipt_embed(order):
    invoice_ref = order["invoice_ref"] or ensure_invoice_ref(order["id"])
    paid_at = (
        int(order["paid_at"])
        if "paid_at" in order.keys() and order["paid_at"]
        else int(order["payment_verified_at"])
        if "payment_verified_at" in order.keys() and order["payment_verified_at"]
        else int(order["activated_at"] or time.time())
    )

    embed = discord.Embed(
        title="🧾 Receipt • Hi Notifku",
        description=f"Invoice `{invoice_ref}`",
        color=discord.Color.green()
    )
    embed.add_field(
        name="Paket",
        value=f"⭐ {int(order['days'])} hari",
        inline=True
    )
    embed.add_field(
        name="Total",
        value=rupiah(int(order["expected_amount"] or order["price"])),
        inline=True
    )
    embed.add_field(
        name="Dibayar",
        value=f"<t:{paid_at}:F>",
        inline=False
    )
    if order["expires_at"]:
        embed.add_field(
            name="Premium sampai",
            value=f"<t:{int(order['expires_at'])}:F>",
            inline=False
        )
    if "payment_reference" in order.keys() and order["payment_reference"]:
        embed.add_field(
            name="Referensi",
            value=f"`{str(order['payment_reference'])[:120]}`",
            inline=False
        )
    embed.set_footer(text="Simpan receipt ini sebagai bukti transaksi.")
    return embed


async def send_payment_receipt(order_id: int) -> bool:
    order = get_premium_order(order_id)
    if not order:
        return False

    if "receipt_sent_at" in order.keys() and order["receipt_sent_at"]:
        return True

    try:
        user = bot.get_user(int(order["requester_id"])) or await bot.fetch_user(
            int(order["requester_id"])
        )
        await user.send(embed=payment_receipt_embed(order))

        with closing(db()) as conn:
            conn.execute("""
                UPDATE premium_orders
                SET receipt_sent_at=?, updated_at=?
                WHERE id=?
            """, (
                int(time.time()),
                int(time.time()),
                int(order_id)
            ))
            conn.commit()

        return True
    except Exception:
        log.exception("Gagal mengirim payment receipt order_id=%s", order_id)
        return False


def verify_payment_webhook_signature(
    raw_body: bytes,
    *,
    timestamp: str,
    signature: str
) -> bool:
    if not PAYMENT_WEBHOOK_SECRET:
        return False

    if not str(timestamp).isdigit():
        return False

    ts = int(timestamp)
    if abs(int(time.time()) - ts) > PAYMENT_WEBHOOK_MAX_SKEW_SECONDS:
        return False

    message = str(timestamp).encode("utf-8") + b"." + raw_body
    expected = hmac.new(
        PAYMENT_WEBHOOK_SECRET.encode("utf-8"),
        message,
        hashlib.sha256
    ).hexdigest()

    supplied = str(signature or "").strip().lower()
    if supplied.startswith("sha256="):
        supplied = supplied.split("=", 1)[1]

    return hmac.compare_digest(expected, supplied)


def record_payment_callback_event(
    *,
    event_id: str,
    invoice_ref: str,
    reference_id: str,
    amount: int,
    payment_status: str,
    payload_hash: str,
    signature_valid: bool
) -> bool:
    try:
        with closing(db()) as conn:
            conn.execute("""
                INSERT INTO payment_callback_events(
                    event_id, invoice_ref, reference_id, amount,
                    payment_status, payload_hash, signature_valid,
                    received_at, process_status
                )
                VALUES(?,?,?,?,?,?,?,?, 'received')
            """, (
                str(event_id)[:160],
                str(invoice_ref)[:160],
                str(reference_id)[:160],
                int(amount),
                str(payment_status)[:80],
                str(payload_hash)[:128],
                1 if signature_valid else 0,
                int(time.time())
            ))
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_order_by_invoice_ref(invoice_ref: str):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT * FROM premium_orders
            WHERE invoice_ref=?
            LIMIT 1
        """, (str(invoice_ref).strip(),)).fetchone()


def mark_callback_event(
    event_id: str,
    status: str,
    *,
    error: Optional[str] = None
):
    with closing(db()) as conn:
        conn.execute("""
            UPDATE payment_callback_events
            SET
                process_status=?,
                processed_at=?,
                error=?
            WHERE event_id=?
        """, (
            str(status)[:80],
            int(time.time()),
            str(error)[:1000] if error else None,
            str(event_id)
        ))
        conn.commit()


def enqueue_payment_event_dlq(
    event_id: str,
    payload: dict,
    error: str,
    *,
    retry_count: int = 0
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO payment_event_dead_letter(
                event_id, payload_json, error, retry_count,
                next_retry_at, created_at
            )
            VALUES(?,?,?,?,?,?)
        """, (
            str(event_id)[:160],
            json.dumps(payload, ensure_ascii=False)[:10000],
            str(error)[:1000],
            int(retry_count),
            int(time.time()) + PAYMENT_EVENT_RETRY_SECONDS,
            int(time.time())
        ))
        conn.commit()


async def process_verified_payment_event(
    payload: dict,
    *,
    source: str = "signed_webhook",
    from_retry: bool = False
) -> dict:
    event_id = str(payload.get("event_id") or "").strip()
    invoice_ref = str(payload.get("invoice_ref") or "").strip()
    reference_id = str(payload.get("reference_id") or "").strip()
    raw_status = str(payload.get("status") or "").strip().lower()

    try:
        amount = int(payload.get("amount"))
    except Exception:
        raise ValueError("amount wajib berupa integer.")

    if not event_id or not invoice_ref or not reference_id:
        raise ValueError(
            "event_id, invoice_ref, dan reference_id wajib diisi."
        )

    paid_states = {"paid", "success", "settled", "completed"}
    failed_states = {"failed", "cancelled", "canceled", "expired"}

    if raw_status not in paid_states | failed_states:
        raise ValueError("Status callback tidak dikenali.")

    order = get_order_by_invoice_ref(invoice_ref)
    if not order:
        raise ValueError("Invoice callback tidak ditemukan.")

    if payment_reference_in_use(
        reference_id,
        exclude_order_id=int(order["id"])
    ):
        refresh_payment_risk(int(order["id"]))
        raise ValueError(
            "Reference pembayaran sudah digunakan invoice lain."
        )

    now = int(time.time())

    if raw_status in failed_states:
        record_premium_event(
            int(order["id"]),
            "payment_callback_failed",
            detail=f"{source}:{raw_status}; ref={reference_id}"
        )
        return {
            "ok": True,
            "activated": False,
            "message": "Status pembayaran bukan sukses."
        }

    expected = int(order["expected_amount"] or order["price"])
    matched = amount == expected
    late = bool(
        order["invoice_deadline"]
        and now > int(order["invoice_deadline"])
        and not order["activated_at"]
    )

    with closing(db()) as conn:
        conn.execute("""
            UPDATE premium_orders
            SET
                received_amount=?,
                amount_verified=?,
                payment_checked_at=?,
                payment_verified_at=?,
                payment_reference=?,
                payment_source=?,
                paid_at=?,
                late_payment=?,
                status=?,
                updated_at=?
            WHERE id=?
        """, (
            amount,
            1 if matched else 0,
            now,
            now if matched else None,
            reference_id,
            source,
            now,
            1 if late else 0,
            (
                "late_payment"
                if late and matched
                else "amount_verified"
                if matched
                else "underpaid"
                if amount < expected
                else "overpaid"
            ),
            now,
            int(order["id"])
        ))
        conn.commit()

    refresh_payment_risk(int(order["id"]))

    if not matched:
        return {
            "ok": True,
            "activated": False,
            "message": (
                "Nominal kurang."
                if amount < expected
                else "Nominal lebih."
            )
        }

    if late:
        await send_payment_admin_log(
            "⏰ Late Payment",
            (
                f"Invoice: `{invoice_ref}`\n"
                f"Nominal: **{rupiah(amount)}**\n"
                f"Reference: `{reference_id}`\n"
                "Pembayaran valid tetapi masuk setelah invoice expired."
            ),
            guild_id=int(order["guild_id"])
        )
        return {
            "ok": True,
            "activated": False,
            "message": "Late payment menunggu review."
        }

    ok, message = await activate_verified_premium_order(
        int(order["id"]),
        actor_id=0,
        source=source,
        require_proof=False
    )

    return {
        "ok": True,
        "activated": bool(ok),
        "message": message
    }


async def payment_webhook_handler(request: web.Request):
    raw = await request.read()
    timestamp = request.headers.get("X-Payment-Timestamp", "")
    signature = request.headers.get("X-Payment-Signature", "")

    valid_signature = verify_payment_webhook_signature(
        raw,
        timestamp=timestamp,
        signature=signature
    )

    payment_health_update(
        success=valid_signature,
        error=None if valid_signature else "Invalid callback signature.",
        callback=True
    )

    if not valid_signature:
        return web.json_response(
            {"ok": False, "error": "invalid_signature"},
            status=401
        )

    try:
        payload = json.loads(raw.decode("utf-8"))
        event_id = str(payload.get("event_id") or "").strip()
        invoice_ref = str(payload.get("invoice_ref") or "").strip()
        reference_id = str(payload.get("reference_id") or "").strip()
        amount = int(payload.get("amount"))
        payment_status = str(payload.get("status") or "").strip()
    except Exception:
        return web.json_response(
            {"ok": False, "error": "invalid_payload"},
            status=400
        )

    payload_hash = hashlib.sha256(raw).hexdigest()

    inserted = record_payment_callback_event(
        event_id=event_id,
        invoice_ref=invoice_ref,
        reference_id=reference_id,
        amount=amount,
        payment_status=payment_status,
        payload_hash=payload_hash,
        signature_valid=True
    )

    if not inserted:
        return web.json_response(
            {"ok": True, "duplicate": True},
            status=200
        )

    try:
        result = await process_verified_payment_event(payload)
        mark_callback_event(event_id, "processed")
        payment_health_update(success=True, callback=False)
        return web.json_response(result, status=200)

    except Exception as exc:
        mark_callback_event(
            event_id,
            "failed",
            error=f"{type(exc).__name__}: {exc}"
        )
        enqueue_payment_event_dlq(
            event_id,
            payload,
            f"{type(exc).__name__}: {exc}"
        )
        payment_health_update(
            success=False,
            error=f"{type(exc).__name__}: {exc}",
            callback=False
        )
        log.exception("Payment callback processing gagal")
        return web.json_response(
            {"ok": False, "queued_for_retry": True},
            status=202
        )


async def payment_webhook_health_handler(request: web.Request):
    health = payment_health_row()
    return web.json_response({
        "ok": True,
        "webhook_enabled": PAYMENT_WEBHOOK_ENABLED,
        "last_callback_at": (
            int(health["last_callback_at"])
            if health and health["last_callback_at"]
            else None
        )
    })


async def start_payment_webhook_server():
    global payment_web_runner

    if not PAYMENT_WEBHOOK_ENABLED:
        return

    if not PAYMENT_WEBHOOK_SECRET:
        log.error(
            "PAYMENT_WEBHOOK_ENABLED=true tetapi PAYMENT_WEBHOOK_SECRET kosong."
        )
        return

    if payment_web_runner is not None:
        return

    app = web.Application(client_max_size=1024 * 1024)
    app.router.add_post(
        PAYMENT_WEBHOOK_PATH,
        payment_webhook_handler
    )
    app.router.add_get(
        "/health/payments",
        payment_webhook_health_handler
    )

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PAYMENT_WEBHOOK_PORT
    )
    await site.start()
    payment_web_runner = runner

    log.info(
        "Payment webhook listener aktif pada port %s path %s",
        PAYMENT_WEBHOOK_PORT,
        PAYMENT_WEBHOOK_PATH
    )


async def stop_payment_webhook_server():
    global payment_web_runner

    if payment_web_runner is None:
        return

    try:
        await payment_web_runner.cleanup()
    finally:
        payment_web_runner = None


# ============================================================
# PREMIUM ORDERS / TRANSACTIONS
# ============================================================

def generate_unique_payment_code(price: int = 0) -> int:
    code_value, _ = generate_collision_free_payment_code(price)
    return code_value


def verify_received_amount(order_id: int, received_amount: int) -> bool:
    order = get_premium_order(order_id)

    if not order:
        raise ValueError("Order tidak ditemukan.")

    expected = int(order["expected_amount"] or order["price"])
    received = int(received_amount)
    matched = expected == received
    now = int(time.time())

    if matched:
        status = "amount_verified"
    elif received < expected:
        status = "underpaid"
    else:
        status = "overpaid"

    with closing(db()) as conn:
        conn.execute("""
            UPDATE premium_orders
            SET
                received_amount=?,
                amount_verified=?,
                payment_checked_at=?,
                payment_verified_at=?,
                status=?,
                updated_at=?
            WHERE id=?
        """, (
            received,
            1 if matched else 0,
            now,
            now if matched else None,
            status,
            now,
            int(order_id)
        ))
        conn.commit()

    refresh_payment_risk(order_id)
    return matched


def payment_amount_status(order) -> str:
    expected = int(order["expected_amount"] or order["price"])
    received = order["received_amount"]

    if received is None:
        return (
            f"Harus ditransfer: **{rupiah(expected)}**\n"
            "Nominal masuk: **Belum dicek**"
        )

    received = int(received)

    if int(order["amount_verified"] or 0):
        return (
            f"Harus ditransfer: **{rupiah(expected)}**\n"
            f"Nominal masuk: **{rupiah(received)}**\n"
            "Status: ✅ **SESUAI**"
        )

    difference = received - expected
    if difference > 0:
        diff_text = f"lebih {rupiah(difference)}"
    else:
        diff_text = f"kurang {rupiah(abs(difference))}"

    return (
        f"Harus ditransfer: **{rupiah(expected)}**\n"
        f"Nominal masuk: **{rupiah(received)}**\n"
        f"Status: ❌ **TIDAK SESUAI** ({diff_text})"
    )




ORDER_STATUSES = {
    "pending", "proof_submitted", "amount_mismatch",
    "underpaid", "overpaid", "amount_verified", "paid",
    "processing", "active", "rejected", "expired",
    "invoice_expired", "late_payment", "refund_pending",
    "refunded", "refund_failed"
}


def create_premium_order(
    guild_id: int,
    requester_id: int,
    days: int,
    price: int
) -> int:
    """Create one active Premium invoice per server.

    The lock is server-wide, not requester-wide. This prevents a Server Owner
    and Host Manager from accidentally creating two payable invoices for the
    same server at the same time.
    """
    if is_user_blacklisted(requester_id):
        raise PermissionError("User diblacklist dari transaksi Premium.")

    now = int(time.time())
    unique_code, expected_amount = generate_collision_free_payment_code(int(price))
    deadline = now + (INVOICE_EXPIRE_MINUTES * 60)
    active_statuses = (
        "pending", "proof_submitted", "amount_mismatch",
        "underpaid", "overpaid", "amount_verified", "paid", "processing"
    )
    placeholders = ",".join("?" for _ in active_statuses)

    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(f"""
            SELECT id, requester_id, days, price
            FROM premium_orders
            WHERE guild_id=?
              AND status IN ({placeholders})
            ORDER BY id DESC
            LIMIT 1
        """, (int(guild_id), *active_statuses)).fetchone()

        if existing:
            if (
                int(existing["requester_id"]) == int(requester_id)
                and int(existing["days"]) == int(days)
                and int(existing["price"]) == int(price)
            ):
                conn.rollback()
                return int(existing["id"])

            conn.rollback()
            raise ValueError(
                "Server ini masih memiliki invoice Premium aktif. "
                "Selesaikan atau tunggu invoice tersebut kedaluwarsa sebelum membuat invoice baru."
            )

        cur = conn.execute("""
            INSERT INTO premium_orders(
                guild_id, requester_id, days, price,
                status, created_at, updated_at,
                unique_code, expected_amount,
                amount_verified, invoice_deadline
            )
            VALUES(?,?,?,?, 'pending',?,?,?,?,0,?)
        """, (
            int(guild_id), int(requester_id), int(days), int(price),
            now, now, unique_code, expected_amount, deadline
        ))
        order_id = int(cur.lastrowid)
        conn.commit()

    ensure_invoice_ref(order_id)
    return order_id


def get_premium_order(order_id: int):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM premium_orders WHERE id=?",
            (int(order_id),)
        ).fetchone()


def list_premium_orders(
    statuses=("pending", "paid"),
    limit: int = 25
):
    placeholders = ",".join("?" for _ in statuses)
    with closing(db()) as conn:
        return conn.execute(
            f"""
            SELECT *
            FROM premium_orders
            WHERE status IN ({placeholders})
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*statuses, int(limit))
        ).fetchall()


def list_transaction_history(limit: int = 20):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM premium_orders
            ORDER BY created_at DESC
            LIMIT ?
        """, (int(limit),)).fetchall()


def update_order_status(
    order_id: int,
    status: str,
    *,
    processed_by: Optional[int] = None,
    activated_at: Optional[int] = None,
    expires_at: Optional[int] = None
):
    if status not in ORDER_STATUSES:
        raise ValueError("Status order tidak valid.")

    now = int(time.time())

    current = get_premium_order(order_id)
    if not current:
        raise ValueError("Order tidak ditemukan.")

    current_status = str(current["status"])
    if not payment_transition_allowed(current_status, status):
        raise ValueError(
            f"Transisi status tidak valid: {current_status} → {status}"
        )

    with closing(db()) as conn:
        conn.execute("""
            UPDATE premium_orders
            SET status=?,
                updated_at=?,
                processed_by=COALESCE(?, processed_by),
                activated_at=COALESCE(?, activated_at),
                expires_at=COALESCE(?, expires_at)
            WHERE id=?
        """, (
            status,
            now,
            processed_by,
            activated_at,
            expires_at,
            int(order_id)
        ))
        conn.commit()

    record_premium_event(
        order_id,
        status,
        actor_id=processed_by,
        detail="Status invoice diperbarui."
    )



def premium_order_counts():
    with closing(db()) as conn:
        row = conn.execute("""
            SELECT
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status='proof_submitted' THEN 1 ELSE 0 END) AS proof_submitted,
                SUM(CASE WHEN status='amount_mismatch' THEN 1 ELSE 0 END) AS amount_mismatch,
                SUM(CASE WHEN status='underpaid' THEN 1 ELSE 0 END) AS underpaid,
                SUM(CASE WHEN status='overpaid' THEN 1 ELSE 0 END) AS overpaid,
                SUM(CASE WHEN status='late_payment' THEN 1 ELSE 0 END) AS late_payment,
                SUM(CASE WHEN status='refund_pending' THEN 1 ELSE 0 END) AS refund_pending,
                SUM(CASE WHEN status='refunded' THEN 1 ELSE 0 END) AS refunded,
                SUM(CASE WHEN status='amount_verified' THEN 1 ELSE 0 END) AS amount_verified,
                SUM(CASE WHEN status='paid' THEN 1 ELSE 0 END) AS paid,
                SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) AS rejected,
                SUM(CASE WHEN status='invoice_expired' THEN 1 ELSE 0 END) AS invoice_expired
            FROM premium_orders
        """).fetchone()

    return {
        "pending": int(row["pending"] or 0),
        "proof_submitted": int(row["proof_submitted"] or 0),
        "amount_mismatch": int(row["amount_mismatch"] or 0),
        "underpaid": int(row["underpaid"] or 0),
        "overpaid": int(row["overpaid"] or 0),
        "late_payment": int(row["late_payment"] or 0),
        "refund_pending": int(row["refund_pending"] or 0),
        "refunded": int(row["refunded"] or 0),
        "amount_verified": int(row["amount_verified"] or 0),
        "paid": int(row["paid"] or 0),
        "active": int(row["active"] or 0),
        "rejected": int(row["rejected"] or 0),
        "invoice_expired": int(row["invoice_expired"] or 0),
    }


def order_status_label(status: str) -> str:
    return invoice_status_label(status)


def premium_order_embed(order):
    guild = bot.get_guild(int(order["guild_id"]))
    guild_name = guild.name if guild else f"Server {order['guild_id']}"
    invoice_ref = order["invoice_ref"] or ensure_invoice_ref(order["id"])
    expected = int(order["expected_amount"] or order["price"])

    embed = discord.Embed(
        title=f"💳 {invoice_ref}",
        description=f"**{guild_name}** • {order_status_label(order['status'])}",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="Paket",
        value=f"⭐ **{order['days']} hari** • **{rupiah(order['price'])}**",
        inline=False
    )
    embed.add_field(
        name="Transfer",
        value=(
            f"**{rupiah(expected)}** • "
            f"`{order['payment_method_name'] or 'metode belum dipilih'}`"
        ),
        inline=False
    )
    embed.add_field(
        name="Peminta",
        value=f"<@{order['requester_id']}>",
        inline=True
    )
    embed.add_field(
        name="Deadline",
        value=invoice_deadline_text(order),
        inline=True
    )
    if order["received_amount"] is not None:
        embed.add_field(
            name="Nominal Masuk",
            value=(
                f"**{rupiah(int(order['received_amount']))}** • "
                f"{'✅ sesuai' if int(order['amount_verified'] or 0) else '❌ selisih'}"
            ),
            inline=False
        )
    if order["proof_url"]:
        detail_lines = [
            payment_proof_scan_label(order),
        ]

        if "proof_sender_name" in order.keys() and order["proof_sender_name"]:
            detail_lines.append(
                f"Pengirim: **{str(order['proof_sender_name'])[:80]}**"
            )

        if "proof_sender_account" in order.keys() and order["proof_sender_account"]:
            detail_lines.append(
                f"Akun: `{mask_account(order['proof_sender_account'])}`"
            )

        if "proof_transfer_time" in order.keys() and order["proof_transfer_time"]:
            detail_lines.append(
                f"Waktu: **{str(order['proof_transfer_time'])[:80]}**"
            )

        if "proof_reference" in order.keys() and order["proof_reference"]:
            detail_lines.append(
                f"Ref: `{str(order['proof_reference'])[:100]}`"
            )

        if "proof_scan_detail" in order.keys() and order["proof_scan_detail"]:
            detail_lines.append(
                f"Scan: {str(order['proof_scan_detail'])[:500]}"
            )

        embed.add_field(
            name="Screening Bukti",
            value="\n".join(detail_lines)[:1024],
            inline=False
        )
    if order["rejection_reason"]:
        embed.add_field(
            name="Penolakan",
            value=str(order["rejection_reason"])[:700],
            inline=False
        )
    if order["expires_at"]:
        embed.add_field(
            name="Premium Sampai",
            value=f"<t:{int(order['expires_at'])}:F> • <t:{int(order['expires_at'])}:R>",
            inline=False
        )
    if "payment_reference" in order.keys() and order["payment_reference"]:
        embed.add_field(
            name="Reference Pembayaran",
            value=f"`{str(order['payment_reference'])[:120]}`",
            inline=False
        )

    if "risk_level" in order.keys() and order["risk_level"]:
        risk_icon = {
            "low": "🟢",
            "medium": "🟡",
            "high": "🟠",
            "critical": "🔴",
        }.get(str(order["risk_level"]), "⚪")

        embed.add_field(
            name="Risk",
            value=(
                f"{risk_icon} **{str(order['risk_level']).upper()}** "
                f"• {int(order['risk_score'] or 0)}/100\n"
                f"{str(order['risk_reasons'] or '-')[:500]}"
            ),
            inline=False
        )

    if "refund_status" in order.keys() and order["refund_status"]:
        embed.add_field(
            name="Refund",
            value=(
                f"**{order['refund_status']}**"
                + (
                    f"\n{str(order['refund_reason'])[:400]}"
                    if order["refund_reason"]
                    else ""
                )
            ),
            inline=False
        )
    return embed


async def notify_order_user(order, message: str):
    try:
        user = bot.get_user(int(order["requester_id"])) or await bot.fetch_user(
            int(order["requester_id"])
        )
        await user.send(message)
        return True
    except Exception:
        return False


def reminder_already_sent(guild_id: int, expires_at: int, days_before: int) -> bool:
    with closing(db()) as conn:
        row = conn.execute("""
            SELECT 1
            FROM premium_reminders
            WHERE guild_id=? AND expires_at=? AND days_before=?
        """, (guild_id, expires_at, days_before)).fetchone()
    return row is not None


def mark_reminder_sent(guild_id: int, expires_at: int, days_before: int):
    with closing(db()) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO premium_reminders(
                guild_id, expires_at, days_before, sent_at
            )
            VALUES(?,?,?,?)
        """, (
            guild_id,
            expires_at,
            days_before,
            int(time.time())
        ))
        conn.commit()



# ============================================================
# PAYMENT METHODS / QRIS / PROOFS
# ============================================================

def list_payment_methods(enabled_only: bool = True):
    with closing(db()) as conn:
        if enabled_only:
            rows = conn.execute("""
                SELECT *
                FROM payment_methods
                WHERE enabled=1
                ORDER BY id ASC
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT *
                FROM payment_methods
                ORDER BY id ASC
            """).fetchall()

    return rows


def get_payment_method(method_id: int):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM payment_methods WHERE id=?",
            (int(method_id),)
        ).fetchone()



def ensure_qris_storage_dir() -> Path:
    folder = Path(QRIS_STORAGE_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def qris_image_path_for_method(method_id: int, extension: str = ".png") -> Path:
    ext = extension.lower().strip()

    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        ext = ".png"

    return ensure_qris_storage_dir() / f"qris-{int(method_id)}{ext}"


def remove_qris_file(path_value: Optional[str]):
    if not path_value:
        return

    try:
        path = Path(path_value)
        storage_root = ensure_qris_storage_dir().resolve()
        resolved = path.resolve()

        # Only remove files inside the configured QRIS storage directory.
        if storage_root == resolved.parent and resolved.exists():
            resolved.unlink()
    except Exception:
        log.exception("Gagal menghapus file QRIS lama")


async def save_qris_attachment(method_id: int, attachment: discord.Attachment) -> str:
    content_type = (attachment.content_type or "").lower()
    filename = (attachment.filename or "").lower()

    extension = Path(filename).suffix.lower()

    if extension not in {".png", ".jpg", ".jpeg", ".webp"}:
        if content_type == "image/png":
            extension = ".png"
        elif content_type in {"image/jpeg", "image/jpg"}:
            extension = ".jpg"
        elif content_type == "image/webp":
            extension = ".webp"
        else:
            raise ValueError(
                "File QRIS harus berupa PNG, JPG, JPEG, atau WEBP."
            )

    raw = await attachment.read()

    # Basic size guard: 10 MB.
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError("Ukuran gambar QRIS maksimal 10 MB.")

    # Basic file-signature validation.
    valid_signature = (
        raw.startswith(b"\x89PNG\r\n\x1a\n")
        or raw.startswith(b"\xff\xd8\xff")
        or raw.startswith(b"RIFF") and b"WEBP" in raw[:16]
    )

    if not valid_signature:
        raise ValueError("File tidak terdeteksi sebagai gambar QRIS yang valid.")

    method = get_payment_method(method_id)

    if not method:
        raise ValueError("Metode QRIS tidak ditemukan.")

    old_path = method["qris_image_path"] if "qris_image_path" in method.keys() else None
    new_path = qris_image_path_for_method(method_id, extension)

    # Replace old format/path cleanly.
    if old_path and Path(old_path) != new_path:
        remove_qris_file(old_path)

    new_path.write_bytes(raw)

    with closing(db()) as conn:
        conn.execute("""
            UPDATE payment_methods
            SET
                qris_image_path=?,
                qris_image_url=NULL,
                updated_at=?
            WHERE id=?
        """, (
            str(new_path),
            int(time.time()),
            int(method_id)
        ))
        conn.commit()

    return str(new_path)


def get_qris_file(method):
    if not method or method["method_type"] != "qris":
        return None

    path_value = (
        method["qris_image_path"]
        if "qris_image_path" in method.keys()
        else None
    )

    if not path_value:
        return None

    path = Path(path_value)

    if not path.exists() or not path.is_file():
        return None

    extension = path.suffix.lower()
    filename = (
        "qris.png"
        if extension == ".png"
        else "qris.jpg"
        if extension in {".jpg", ".jpeg"}
        else "qris.webp"
    )

    return discord.File(
        str(path),
        filename=filename
    )


def apply_qris_attachment_image(embed: discord.Embed, method) -> Optional[discord.File]:
    qris_file = get_qris_file(method)

    if qris_file:
        embed.set_image(url=f"attachment://{qris_file.filename}")
        return qris_file

    # Legacy fallback while old QRIS records are migrated/re-uploaded.
    if (
        method
        and method["method_type"] == "qris"
        and method["qris_image_url"]
    ):
        embed.set_image(url=method["qris_image_url"])

    return None


def add_payment_method(
    method_type: str,
    method_name: str,
    account_name: str = "",
    account_number: str = "",
    payment_note: str = "",
    qris_image_url: str = ""
) -> int:
    method_type = (
        "qris"
        if method_type.lower().strip() == "qris"
        else "account"
    )

    now = int(time.time())

    with closing(db()) as conn:
        cur = conn.execute("""
            INSERT INTO payment_methods(
                method_type,
                method_name,
                account_name,
                account_number,
                payment_note,
                qris_image_url,
                enabled,
                created_at,
                updated_at
            )
            VALUES(?,?,?,?,?,?,1,?,?)
        """, (
            method_type,
            method_name.strip() or (
                "QRIS"
                if method_type == "qris"
                else "Pembayaran"
            ),
            account_name.strip() or None,
            account_number.strip() or None,
            payment_note.strip() or None,
            qris_image_url.strip() or None,
            now,
            now
        ))
        conn.commit()
        return int(cur.lastrowid)


def update_payment_method(
    method_id: int,
    *,
    method_name: Optional[str] = None,
    account_name: Optional[str] = None,
    account_number: Optional[str] = None,
    payment_note: Optional[str] = None,
    qris_image_url: Optional[str] = None,
    qris_image_path: Optional[str] = None
):
    row = get_payment_method(method_id)

    if not row:
        raise ValueError("Metode pembayaran tidak ditemukan.")

    with closing(db()) as conn:
        conn.execute("""
            UPDATE payment_methods
            SET
                method_name=?,
                account_name=?,
                account_number=?,
                payment_note=?,
                qris_image_url=?,
                qris_image_path=?,
                updated_at=?
            WHERE id=?
        """, (
            row["method_name"] if method_name is None else (method_name.strip() or None),
            row["account_name"] if account_name is None else (account_name.strip() or None),
            row["account_number"] if account_number is None else (account_number.strip() or None),
            row["payment_note"] if payment_note is None else (payment_note.strip() or None),
            row["qris_image_url"] if qris_image_url is None else (qris_image_url.strip() or None),
            row["qris_image_path"] if qris_image_path is None else (qris_image_path.strip() or None),
            int(time.time()),
            int(method_id)
        ))
        conn.commit()


def delete_payment_method(method_id: int):
    method = get_payment_method(method_id)

    if method and method["method_type"] == "qris":
        path_value = (
            method["qris_image_path"]
            if "qris_image_path" in method.keys()
            else None
        )
        remove_qris_file(path_value)

    with closing(db()) as conn:
        conn.execute(
            "DELETE FROM payment_methods WHERE id=?",
            (int(method_id),)
        )
        conn.commit()


def payment_methods_ready() -> bool:
    return bool(list_payment_methods(True))


def payment_method_embed(method, order=None):
    embed = discord.Embed(
        title=f"💳 {method['method_name']}",
        color=discord.Color.gold()
    )

    if order:
        expected = int(order["expected_amount"] or order["price"])

        invoice_ref = order["invoice_ref"] or ensure_invoice_ref(order["id"])
        embed.description = (
            f"Invoice **`{invoice_ref}`**\n"
            f"📅 Paket: **{order['days']} hari**\n"
            f"💰 Harga paket: **{rupiah(order['price'])}**\n"
            f"🔢 Kode unik: **{int(order['unique_code'] or 0):03d}**\n"
            f"💳 Transfer tepat: **{rupiah(expected)}**"
        )

    if method["method_type"] == "qris":
        embed.add_field(
            name="Metode",
            value="QRIS",
            inline=False
        )
    else:
        if method["account_name"]:
            embed.add_field(
                name="Atas Nama",
                value=method["account_name"],
                inline=True
            )

        if method["account_number"]:
            embed.add_field(
                name="Nomor / Rekening",
                value=f"`{method['account_number']}`",
                inline=True
            )

    if method["payment_note"]:
        embed.add_field(
            name="Instruksi",
            value=method["payment_note"][:1024],
            inline=False
        )

    if order:
        embed.add_field(
            name="⚠️ Nominal + Kode Unik Wajib Tepat",
            value=(
                f"Harga paket: **{rupiah(int(order['price']))}**\n"
                f"Kode unik: **{int(order['unique_code'] or 0):03d}**\n"
                f"Total transfer: **{rupiah(int(order['expected_amount'] or order['price']))}**\n\n"
                "Transfer harus **PERSIS** sesuai Total Transfer di atas. "
                "Jangan hanya transfer harga paket, jangan dibulatkan, dan jangan "
                "mengubah kode unik."
            ),
            inline=False
        )

    embed.add_field(
        name="Setelah Membayar",
        value=(
            "Tekan **Saya Sudah Bayar**, isi detail transaksi, lalu kirim "
            "1 screenshot bukti transfer asli ke DM bot untuk screening otomatis.\n\n"
            "Bukti harus jelas, utuh, tidak diedit, dan menampilkan nominal serta "
            "informasi transaksi penting."
        ),
        inline=False
    )

    # QRIS image is attached by apply_qris_attachment_image().
    # Legacy remote URLs remain available as fallback.
    if (
        method["method_type"] == "qris"
        and not (
            "qris_image_path" in method.keys()
            and method["qris_image_path"]
            and Path(method["qris_image_path"]).exists()
        )
        and method["qris_image_url"]
    ):
        embed.set_image(url=method["qris_image_url"])

    return embed


def payment_methods_overview_embed():
    methods = list_payment_methods(False)

    embed = discord.Embed(
        title="💳 Metode Pembayaran Premium",
        color=discord.Color.gold()
    )

    if not methods:
        embed.description = "Belum ada metode pembayaran."
        return embed

    lines = []

    for method in methods:
        kind = "QRIS" if method["method_type"] == "qris" else "Akun/Rekening"
        status = "✅ Aktif" if method["enabled"] else "⏸️ Nonaktif"

        qris_path_ready = bool(
            method["method_type"] == "qris"
            and "qris_image_path" in method.keys()
            and method["qris_image_path"]
            and Path(method["qris_image_path"]).exists()
        )

        detail = method["account_number"] or (
            "Gambar QRIS tersimpan permanen"
            if qris_path_ready
            else "Gambar QRIS legacy"
            if method["qris_image_url"]
            else "Belum ada gambar QRIS"
        )

        lines.append(
            f"**#{method['id']} • {method['method_name']}**\n"
            f"{kind} • {status}\n"
            f"{detail}"
        )

    embed.description = "\n\n".join(lines)[:4000]
    return embed


def assign_order_payment_method(order_id: int, method_id: int):
    method = get_payment_method(method_id)

    if not method or not method["enabled"]:
        raise ValueError("Metode pembayaran tidak tersedia.")

    with closing(db()) as conn:
        conn.execute("""
            UPDATE premium_orders
            SET
                payment_method_id=?,
                payment_method_name=?,
                updated_at=?
            WHERE id=?
        """, (
            int(method_id),
            method["method_name"],
            int(time.time()),
            int(order_id)
        ))
        conn.commit()


def payment_proof_instruction_text() -> str:
    return (
        "📸 **Kirim 1 screenshot asli bukti pembayaran.**\n"
        "Pastikan **nominal sesuai Total Transfer termasuk kode unik**, "
        "serta waktu dan ID transaksi terlihat.\n"
        "Jangan edit atau crop berlebihan. Format: PNG/JPG/JPEG/WEBP."
    )


def mask_account(value: Optional[str]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "-"
    compact = "".join(ch for ch in raw if ch.isalnum())
    if len(compact) <= 4:
        return "••••"
    return "••••" + compact[-4:]


def save_payment_proof_details(
    order_id: int,
    *,
    sender_name: str,
    sender_account: str,
    transfer_time: str,
    reference: str,
    declared_amount: int,
    note: str = ""
):
    order = get_premium_order(order_id)
    if not order:
        raise ValueError("Order tidak ditemukan.")

    expected = int(order["expected_amount"] or order["price"])
    if int(declared_amount) != expected:
        raise ValueError(
            f"Nominal yang kamu isi harus persis {rupiah(expected)}."
        )

    reference_value = str(reference).strip()
    if not reference_value:
        raise ValueError("Nomor referensi transaksi wajib diisi.")

    with closing(db()) as conn:
        duplicate_ref = conn.execute("""
            SELECT id
            FROM premium_orders
            WHERE proof_reference=?
              AND id<>?
            LIMIT 1
        """, (
            reference_value,
            int(order_id)
        )).fetchone()

        if duplicate_ref:
            raise ValueError(
                f"Nomor referensi sudah dipakai pada invoice #{duplicate_ref['id']}."
            )

    with closing(db()) as conn:
        conn.execute("""
            UPDATE premium_orders
            SET
                proof_sender_name=?,
                proof_sender_account=?,
                proof_transfer_time=?,
                proof_reference=?,
                proof_declared_amount=?,
                proof_note=?,
                proof_details_submitted_at=?,
                updated_at=?
            WHERE id=?
        """, (
            str(sender_name).strip()[:120],
            str(sender_account).strip()[:120],
            str(transfer_time).strip()[:100],
            reference_value[:160],
            int(declared_amount),
            str(note).strip()[:500],
            int(time.time()),
            int(time.time()),
            int(order_id)
        ))
        conn.commit()


def scan_payment_proof_bytes(
    raw: bytes,
    *,
    filename: str,
    content_type: str
) -> dict:
    size = len(raw)
    max_bytes = PAYMENT_PROOF_MAX_MB * 1024 * 1024

    if not raw:
        raise ValueError("File bukti kosong.")

    if size > max_bytes:
        raise ValueError(
            f"Ukuran bukti maksimal {PAYMENT_PROOF_MAX_MB} MB."
        )

    lowered_name = str(filename or "").lower()
    content_type = str(content_type or "").lower()

    valid_signature = (
        raw.startswith(b"\x89PNG\r\n\x1a\n")
        or raw.startswith(b"\xff\xd8\xff")
        or (raw.startswith(b"RIFF") and b"WEBP" in raw[:16])
    )

    if not valid_signature:
        raise ValueError(
            "File bukti harus gambar PNG/JPG/JPEG/WEBP yang valid."
        )

    score = 100
    reasons = []
    width = None
    height = None
    edit_software = None
    entropy = None

    if Image is not None:
        try:
            with Image.open(io.BytesIO(raw)) as img:
                width, height = img.size
                fmt = (img.format or "").upper()

                if width < 300 or height < 300:
                    score -= 35
                    reasons.append("Resolusi terlalu kecil.")

                if width > 12000 or height > 12000:
                    score -= 20
                    reasons.append("Resolusi tidak wajar.")

                try:
                    entropy = float(img.convert("L").entropy())
                    if entropy < 2.0:
                        score -= 40
                        reasons.append("Gambar terlalu polos/kosong.")
                    elif entropy < 3.0:
                        score -= 15
                        reasons.append("Detail visual sangat rendah.")
                except Exception:
                    entropy = None

                try:
                    exif = img.getexif()
                    software = (
                        exif.get(305)
                        if exif
                        else None
                    )
                    if software:
                        edit_software = str(software)[:120]
                        suspicious_terms = (
                            "photoshop",
                            "gimp",
                            "canva",
                            "snapseed",
                            "lightroom",
                            "picsart",
                        )
                        if any(
                            term in edit_software.lower()
                            for term in suspicious_terms
                        ):
                            score -= 30
                            reasons.append(
                                "Metadata menunjukkan software editing."
                            )
                except Exception:
                    pass

                if fmt not in {"PNG", "JPEG", "WEBP"}:
                    score -= 30
                    reasons.append("Format gambar tidak umum.")

        except Exception as exc:
            raise ValueError(
                f"Gambar bukti tidak dapat dibaca: {type(exc).__name__}."
            )

    if size < 15 * 1024:
        score -= 20
        reasons.append("Ukuran file sangat kecil.")

    if not content_type.startswith("image/"):
        score -= 10
        reasons.append("Content-Type bukan image/*.")

    score = max(0, min(100, int(score)))

    if score >= 75:
        status = "passed"
    elif score >= 40:
        status = "review"
    else:
        status = "rejected"

    if not reasons:
        reasons.append("Tidak ditemukan indikator teknis mencurigakan.")

    return {
        "status": status,
        "score": score,
        "detail": " | ".join(reasons)[:1500],
        "file_size": size,
        "width": width,
        "height": height,
        "mime": content_type[:120],
        "edit_software": edit_software,
        "entropy": entropy,
        "filename": lowered_name[:200],
    }


def payment_proof_scan_label(order) -> str:
    status = (
        str(order["proof_scan_status"])
        if "proof_scan_status" in order.keys()
        and order["proof_scan_status"]
        else "belum_scan"
    )
    score = (
        int(order["proof_scan_score"])
        if "proof_scan_score" in order.keys()
        and order["proof_scan_score"] is not None
        else None
    )

    labels = {
        "passed": "✅ LULUS SCREENING",
        "review": "🟠 PERLU REVIEW",
        "rejected": "🔴 DITOLAK",
        "belum_scan": "⚪ BELUM DISCAN",
    }

    return (
        f"{labels.get(status, status.upper())}"
        + (f" • skor **{score}/100**" if score is not None else "")
    )


def commit_premium_activation(order_id: int, actor_id: int) -> int:
    """Atomically apply a Premium order exactly once and return expiry.

    Guild entitlement and order activation are committed in the same SQLite
    transaction. A process crash therefore cannot activate the server and leave
    the invoice unactivated, which previously could extend Premium twice on a
    retry.
    """
    now = int(time.time())

    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        order = conn.execute(
            "SELECT * FROM premium_orders WHERE id=?",
            (int(order_id),)
        ).fetchone()
        if not order:
            conn.rollback()
            raise ValueError("Order tidak ditemukan.")

        if order["activated_at"] or str(order["status"]) == "active":
            expiry = int(order["expires_at"] or order["activation_target_expires_at"] or 0)
            conn.rollback()
            return expiry

        if str(order["status"]) != "processing":
            conn.rollback()
            raise ValueError("Order belum diklaim untuk aktivasi.")

        settings = conn.execute(
            "SELECT * FROM guild_settings WHERE guild_id=?",
            (int(order["guild_id"]),)
        ).fetchone()
        if not settings:
            conn.rollback()
            raise ValueError("Pengaturan server tidak ditemukan.")

        target = int(order["activation_target_expires_at"] or 0)
        if not target:
            current_expiry = int(settings["premium_expires_at"] or 0)
            base = current_expiry if (
                str(settings["plan"] or "free").lower() == "premium"
                and current_expiry > now
            ) else now
            target = base + max(1, int(order["days"])) * 86400
            conn.execute(
                "UPDATE premium_orders SET activation_target_expires_at=? WHERE id=?",
                (target, int(order_id))
            )

        conn.execute("""
            UPDATE guild_settings
            SET plan='premium',
                premium_started_at=CASE
                    WHEN premium_started_at IS NULL THEN ?
                    ELSE premium_started_at
                END,
                premium_expires_at=?,
                premium_warning_sent=0,
                premium_grace_until=NULL
            WHERE guild_id=?
        """, (now, target, int(order["guild_id"])))

        conn.execute("""
            UPDATE premium_orders
            SET status='active',
                processed_by=COALESCE(?, processed_by),
                activated_at=COALESCE(activated_at, ?),
                expires_at=?,
                activation_effect_applied=1,
                updated_at=?
            WHERE id=?
        """, (int(actor_id), now, target, now, int(order_id)))
        conn.commit()

    restored = reactivate_plan_paused_hosts(int(order["guild_id"]))
    if restored:
        add_activity(
            int(order["guild_id"]), None, "Premium Host Reactivation",
            f"{restored} host dipulihkan setelah Premium aktif."
        )

    record_premium_event(
        int(order_id), "active", actor_id=int(actor_id),
        detail="Entitlement Premium diterapkan atomik."
    )
    return target


async def activate_verified_premium_order(
    order_id: int,
    *,
    actor_id: int,
    source: str,
    require_proof: bool = True
) -> tuple[bool, str]:
    order = get_premium_order(order_id)

    if not order:
        return False, "Order tidak ditemukan."

    if order["activated_at"] or order["status"] == "active":
        return True, "Premium sudah aktif."

    if not int(order["amount_verified"] or 0):
        return False, "Nominal pembayaran belum terverifikasi."

    if require_proof and not order["proof_url"]:
        return False, "Menunggu bukti transfer."

    scan_status = (
        str(order["proof_scan_status"] or "")
        if "proof_scan_status" in order.keys()
        else ""
    )

    if scan_status == "rejected":
        return False, "Bukti transfer ditolak screening otomatis."

    if require_proof and scan_status != "passed":
        return False, (
            "Bukti pembayaran belum lulus screening otomatis. "
            "Status review harus diperiksa Payment Admin sebelum Premium diaktifkan."
        )

    if not claim_order_for_activation(
        int(order_id),
        int(actor_id)
    ):
        refreshed = get_premium_order(order_id)
        if refreshed and refreshed["status"] == "active":
            return True, "Premium sudah aktif."
        return False, "Order sedang diproses."

    try:
        guild_id = int(order["guild_id"])
        expires_at = commit_premium_activation(int(order_id), int(actor_id))
        now = int(time.time())

        # Permanent, idempotent Premium customer record. A failure here must not
        # roll back a successfully activated subscription, so log and continue.
        try:
            record_premium_customer_activation(int(order_id), source=source)
        except Exception as customer_exc:
            log.exception(
                "Premium customer DB write failed for order %s: %s",
                order_id, customer_exc
            )

        invoice_ref = (
            order["invoice_ref"]
            or ensure_invoice_ref(order["id"])
        )

        add_activity(
            guild_id,
            int(actor_id),
            "Premium Auto Activated",
            (
                f"{invoice_ref}; {order['days']} hari; "
                f"source={source}; scan={scan_status or 'unknown'}"
            )
        )

        await audit_webhook(
            "Premium Auto Activated",
            (
                f"{invoice_ref} • {order['days']} hari • "
                f"source={source}"
            ),
            actor_id=int(actor_id),
            guild_id=guild_id
        )

        await send_payment_admin_log(
            "✅ Premium Otomatis Aktif",
            (
                f"Invoice: `{invoice_ref}`\n"
                f"Paket: **{order['days']} hari**\n"
                f"Nominal: **{rupiah(int(order['expected_amount'] or order['price']))}**\n"
                f"Sumber verifikasi: **{source}**\n"
                f"Screening bukti: **{scan_status or 'unknown'}**"
            ),
            guild_id=guild_id
        )

        msg = (
            f"✅ Pembayaran `{invoice_ref}` sudah terverifikasi.\n"
            f"⭐ Premium otomatis aktif **{order['days']} hari**.\n"
            f"Berakhir: {premium_expiry_text(guild_id)}"
        )

        await notify_order_user(order, msg)

        guild = bot.get_guild(guild_id)
        if guild:
            await dm_guild_owner(guild, msg)

        await send_payment_receipt(int(order_id))
        payment_health_update(success=True)

        return True, msg

    except Exception:
        release_order_claim(int(order_id))
        raise


async def maybe_auto_activate_verified_order(
    order_id: int,
    *,
    actor_id: int,
    source: str
) -> tuple[bool, str]:
    if not AUTO_ACTIVATE_VERIFIED_PAYMENTS:
        return False, "Auto-activate dinonaktifkan."

    order = get_premium_order(order_id)
    if not order:
        return False, "Order tidak ditemukan."

    if not int(order["amount_verified"] or 0):
        return False, "Nominal belum terverifikasi."

    if not order["proof_url"]:
        return False, "Menunggu bukti transfer."

    return await activate_verified_premium_order(
        order_id,
        actor_id=actor_id,
        source=source
    )




def save_payment_proof(
    order_id: int,
    proof_url: str,
    proof_message_id: int,
    proof_hash_value: Optional[str] = None,
    *,
    scan: Optional[dict] = None
):
    proof_hash = proof_hash_value or hashlib.sha256(
        proof_url.encode("utf-8")
    ).hexdigest()

    scan = scan or {}
    scan_status = str(scan.get("status") or "review")

    with closing(db()) as conn:
        duplicate = conn.execute("""
            SELECT id
            FROM premium_orders
            WHERE proof_hash=?
              AND id<>?
            LIMIT 1
        """, (
            proof_hash,
            int(order_id)
        )).fetchone()

        if duplicate:
            raise ValueError(
                f"Bukti pembayaran sudah pernah dipakai pada request #{duplicate['id']}."
            )

        if scan_status == "rejected":
            raise ValueError(
                "Bukti gagal screening otomatis. Kirim screenshot asli sesuai instruksi: "
                "utuh, jelas, tidak diedit, nominal/tanggal/referensi terlihat, dan bukan "
                "file yang pernah dipakai sebelumnya."
            )

        conn.execute("""
            UPDATE premium_orders
            SET
                proof_url=?,
                proof_message_id=?,
                proof_submitted_at=?,
                proof_hash=?,
                proof_scan_status=?,
                proof_scan_score=?,
                proof_scan_detail=?,
                proof_scan_at=?,
                proof_file_size=?,
                proof_image_width=?,
                proof_image_height=?,
                proof_mime=?,
                proof_edit_software=?,
                status='proof_submitted',
                updated_at=?
            WHERE id=?
        """, (
            proof_url,
            proof_message_id,
            int(time.time()),
            proof_hash,
            scan_status,
            int(scan.get("score") or 0),
            str(scan.get("detail") or "")[:1500],
            int(time.time()),
            int(scan.get("file_size") or 0),
            scan.get("width"),
            scan.get("height"),
            str(scan.get("mime") or "")[:120],
            (
                str(scan.get("edit_software"))[:120]
                if scan.get("edit_software")
                else None
            ),
            int(time.time()),
            int(order_id)
        ))
        conn.commit()


def latest_waiting_proof_order(user_id: int):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM premium_orders
            WHERE requester_id=?
              AND status IN ('pending','proof_submitted','amount_mismatch','amount_verified')
              AND payment_method_id IS NOT NULL
              AND proof_details_submitted_at IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
        """, (int(user_id),)).fetchone()



# ============================================================
# ADVANCED SECURITY / BILLING / REPORTS
# ============================================================

OWNER_ROLE_LEVELS = {
    "read_only": 0,
    "server_admin": 1,
    "payment_admin": 2,
    "super_owner": 3,
}


def action_rate_limited(user_id: int, action: str) -> bool:
    now = time.time()
    key = (int(user_id), str(action))
    last = user_action_cooldowns.get(key, 0.0)

    if now - last < USER_RATE_LIMIT_SECONDS:
        return True

    user_action_cooldowns[key] = now
    return False


def is_user_blacklisted(user_id: int) -> bool:
    with closing(db()) as conn:
        row = conn.execute(
            "SELECT 1 FROM user_blacklist WHERE user_id=?",
            (int(user_id),)
        ).fetchone()
    return row is not None


def blacklist_user(user_id: int, reason: str, added_by: int):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO user_blacklist(user_id, reason, added_by, created_at)
            VALUES(?,?,?,?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                reason=excluded.reason,
                added_by=excluded.added_by,
                created_at=excluded.created_at
        """, (
            int(user_id),
            reason[:500],
            int(added_by),
            int(time.time())
        ))
        conn.commit()


def unblacklist_user(user_id: int):
    with closing(db()) as conn:
        conn.execute(
            "DELETE FROM user_blacklist WHERE user_id=?",
            (int(user_id),)
        )
        conn.commit()


def owner_role(user_id: int) -> str:
    if is_primary_owner(user_id):
        return "super_owner"

    with closing(db()) as conn:
        row = conn.execute(
            "SELECT role FROM owner_roles WHERE user_id=?",
            (int(user_id),)
        ).fetchone()

    if row and row["role"] in OWNER_ROLE_LEVELS:
        return row["role"]

    if user_id in db_owner_ids():
        return "server_admin"

    return "read_only"


def set_owner_role(user_id: int, role: str, updated_by: int):
    if role not in OWNER_ROLE_LEVELS:
        raise ValueError("Role owner tidak valid.")

    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO owner_roles(user_id, role, updated_by, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                role=excluded.role,
                updated_by=excluded.updated_by,
                updated_at=excluded.updated_at
        """, (
            int(user_id),
            role,
            int(updated_by),
            int(time.time())
        ))
        conn.commit()


def owner_has_level(user_id: int, minimum: str) -> bool:
    return OWNER_ROLE_LEVELS.get(
        owner_role(user_id), -1
    ) >= OWNER_ROLE_LEVELS.get(minimum, 99)


def invoice_status_label(status: str) -> str:
    labels = {
        "pending": "🟡 Menunggu Pembayaran",
        "proof_submitted": "🟠 Bukti Dikirim",
        "amount_mismatch": "🔴 Nominal Tidak Sesuai",
        "underpaid": "🔻 Kurang Bayar",
        "overpaid": "🔺 Lebih Bayar",
        "amount_verified": "🟢 Nominal Sesuai",
        "paid": "🔵 Dibayar",
        "processing": "🟣 Diproses",
        "active": "✅ Aktif",
        "rejected": "❌ Ditolak",
        "expired": "⚫ Premium Selesai",
        "invoice_expired": "⌛ Invoice Kedaluwarsa",
        "late_payment": "⏰ Pembayaran Terlambat",
        "refund_pending": "↩️ Refund Diproses",
        "refunded": "✅ Refunded",
        "refund_failed": "❌ Refund Gagal",
    }
    return labels.get(status, status)


def active_expected_amount_exists(amount: int, exclude_order_id: Optional[int] = None) -> bool:
    sql = """
        SELECT 1
        FROM premium_orders
        WHERE expected_amount=?
          AND status IN (
              'pending','proof_submitted',
              'amount_mismatch','amount_verified','paid'
          )
    """
    args = [int(amount)]

    if exclude_order_id is not None:
        sql += " AND id<>?"
        args.append(int(exclude_order_id))

    sql += " LIMIT 1"

    with closing(db()) as conn:
        return conn.execute(sql, tuple(args)).fetchone() is not None


def generate_collision_free_payment_code(price: int) -> tuple[int, int]:
    base = int(price)

    for code_value in range(1, 1000):
        expected = base + code_value

        if not active_expected_amount_exists(expected):
            return code_value, expected

    raise RuntimeError(
        "Semua kode unik 001-999 sedang digunakan. "
        "Tunggu invoice lama kedaluwarsa."
    )


def invoice_deadline_text(order) -> str:
    deadline = order["invoice_deadline"]

    if not deadline:
        return "Tidak ditentukan"

    return f"<t:{int(deadline)}:F> • <t:{int(deadline)}:R>"


def revenue_stats():
    now = int(time.time())
    day_start = now - (now % 86400)
    month_start = now - (30 * 86400)

    with closing(db()) as conn:
        row = conn.execute("""
            SELECT
                SUM(CASE
                    WHEN status IN ('active','expired')
                     AND activated_at>=?
                    THEN price ELSE 0 END
                ) AS today,
                SUM(CASE
                    WHEN status IN ('active','expired')
                     AND activated_at>=?
                    THEN price ELSE 0 END
                ) AS month,
                SUM(CASE
                    WHEN status IN ('active','expired')
                    THEN price ELSE 0 END
                ) AS total,
                SUM(CASE
                    WHEN status IN ('active','expired')
                     AND activated_at>=?
                    THEN 1 ELSE 0 END
                ) AS orders_today
            FROM premium_orders
        """, (
            day_start,
            month_start,
            day_start
        )).fetchone()

        best = conn.execute("""
            SELECT days, COUNT(*) AS total
            FROM premium_orders
            WHERE status IN ('active','expired')
            GROUP BY days
            ORDER BY total DESC
            LIMIT 1
        """).fetchone()

        method = conn.execute("""
            SELECT payment_method_name, COUNT(*) AS total
            FROM premium_orders
            WHERE status IN ('active','expired')
              AND payment_method_name IS NOT NULL
            GROUP BY payment_method_name
            ORDER BY total DESC
            LIMIT 1
        """).fetchone()

    return {
        "today": int(row["today"] or 0),
        "month": int(row["month"] or 0),
        "total": int(row["total"] or 0),
        "orders_today": int(row["orders_today"] or 0),
        "best_package": (
            f"{best['days']} hari ({best['total']} transaksi)"
            if best else "-"
        ),
        "best_method": (
            f"{method['payment_method_name']} ({method['total']})"
            if method else "-"
        ),
    }


def export_transactions_csv_bytes() -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "created_at", "guild_id", "requester_id",
        "days", "price", "unique_code", "expected_amount",
        "received_amount", "payment_method", "status",
        "activated_at", "expires_at", "processed_by"
    ])

    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT *
            FROM premium_orders
            ORDER BY id DESC
        """).fetchall()

    for row in rows:
        writer.writerow([
            row["id"],
            row["created_at"],
            row["guild_id"],
            row["requester_id"],
            row["days"],
            row["price"],
            row["unique_code"],
            row["expected_amount"],
            row["received_amount"],
            row["payment_method_name"],
            row["status"],
            row["activated_at"],
            row["expires_at"],
            row["processed_by"],
        ])

    return output.getvalue().encode("utf-8-sig")


def host_status_text(host) -> str:
    now = int(time.time())

    if not host["enabled"]:
        return "⏸️ Paused"

    if host["cooldown_until"] and int(host["cooldown_until"]) > now:
        return f"🟡 Cooldown sampai <t:{int(host['cooldown_until'])}:R>"

    if host["last_error"]:
        return "🔴 Error"

    return "🟢 Normal"


def health_detail_embed():
    hosts = []

    for guild in bot.guilds:
        try:
            hosts.extend(get_hosts(guild.id))
        except Exception:
            pass

    error_hosts = [h for h in hosts if h["last_error"]]
    cooldown_hosts = [
        h for h in hosts
        if h["cooldown_until"]
        and int(h["cooldown_until"]) > int(time.time())
    ]

    embed = discord.Embed(
        title="🩺 Health Detail",
        color=discord.Color.green()
    )
    embed.add_field(
        name="Discord",
        value=f"Ping: **{round(bot.latency * 1000)} ms**",
        inline=True
    )
    embed.add_field(
        name="Database",
        value=(
            f"`{DB_PATH}`\n"
            f"Exists: **{'Ya' if os.path.exists(DB_PATH) else 'Tidak'}**"
        ),
        inline=True
    )
    embed.add_field(
        name="Monitor",
        value=(
            f"Host: **{len(hosts)}**\n"
            f"Error: **{len(error_hosts)}**\n"
            f"Cooldown: **{len(cooldown_hosts)}**"
        ),
        inline=True
    )
    try:
        qris_folder = ensure_qris_storage_dir()
        qris_files = len([
            item for item in qris_folder.iterdir()
            if item.is_file()
        ])
        qris_storage_text = (
            f"`{qris_folder}`\n"
            f"File: **{qris_files}**"
        )
    except Exception as exc:
        qris_storage_text = f"❌ {type(exc).__name__}"

    embed.add_field(
        name="QRIS Storage",
        value=qris_storage_text,
        inline=False
    )

    embed.add_field(
        name="API",
        value=(
            f"YouTube Key: **{'Loaded' if YOUTUBE_API_KEY else 'Kosong'}**\n"
            "TikTok: **Runtime checker**"
        ),
        inline=False
    )

    try:
        with closing(db()) as conn:
            last_backup = conn.execute("""
                SELECT *
                FROM backup_log
                ORDER BY created_at DESC
                LIMIT 1
            """).fetchone()

        if last_backup:
            embed.add_field(
                name="Backup Terakhir",
                value=(
                    f"<t:{last_backup['created_at']}:R>\n"
                    f"Status: **{'OK' if last_backup['ok'] else 'Gagal'}**"
                ),
                inline=False
            )
    except Exception:
        pass

    if error_hosts:
        lines = []
        for host in error_hosts[:8]:
            lines.append(
                f"• #{host['id']} {host['platform']} `{host['target']}` "
                f"({host['error_count']}x)"
            )
        embed.add_field(
            name="Host Bermasalah",
            value="\n".join(lines),
            inline=False
        )

    embed.add_field(
        name="Loops",
        value=(
            f"Monitor **{'ON' if monitor_loop.is_running() else 'OFF'}** • "
            f"Premium **{'ON' if premium_expiry_loop.is_running() else 'OFF'}**\n"
            f"Invoice **{'ON' if invoice_expiry_loop.is_running() else 'OFF'}** • "
            f"Backup **{'ON' if auto_backup_loop.is_running() else 'OFF'}**\n"
            f"Maintenance **{'ON' if db_maintenance_loop.is_running() else 'OFF'}**"
        ),
        inline=False
    )

    embed.add_field(
        name="Runtime Metrics",
        value=(
            f"Notif sent **{runtime_metrics['notifications_sent']}** • "
            f"failed **{runtime_metrics['notifications_failed']}**\n"
            f"Queued **{runtime_metrics['notifications_queued']}** • "
            f"checker errors **{runtime_metrics['checker_errors']}**\n"
            f"Event-loop lag **{runtime_metrics['last_loop_lag_ms']} ms**"
        ),
        inline=False
    )

    return embed


def backup_preview_embed(data: dict):
    if not isinstance(data, dict):
        return discord.Embed(
            title="❌ Backup Tidak Valid",
            color=discord.Color.red()
        )

    guild_id = int(data.get("guild_id") or 0)
    hosts = data.get("hosts") or []
    settings = data.get("guild_settings") or {}

    current_hosts = []
    current_plan = "-"
    guild = bot.get_guild(guild_id)

    if guild:
        try:
            current_hosts = list(get_hosts(guild_id))
            current_plan = str(
                get_guild_settings(guild_id)["plan"]
            ).upper()
        except Exception:
            pass

    incoming_keys = {
        (
            str(h.get("platform")),
            str(h.get("target"))
        )
        for h in hosts
        if isinstance(h, dict)
    }
    current_keys = {
        (
            str(h["platform"]),
            str(h["target"])
        )
        for h in current_hosts
    }

    add_count = len(incoming_keys - current_keys)
    existing_count = len(incoming_keys & current_keys)
    missing_count = len(current_keys - incoming_keys)

    embed = discord.Embed(
        title="🔎 Preview Restore + Diff",
        description=(
            "Periksa perubahan sebelum menerapkan backup. "
            "Restore tetap memerlukan konfirmasi manual."
        ),
        color=discord.Color.orange()
    )
    embed.add_field(
        name="Server",
        value=(
            f"**{guild.name if guild else 'Tidak ditemukan'}**\n"
            f"`{guild_id}`"
        ),
        inline=False
    )
    embed.add_field(
        name="Plan",
        value=(
            f"Sekarang: **{current_plan}**\n"
            f"Backup: **{str(settings.get('plan', 'free')).upper()}**"
        ),
        inline=True
    )
    embed.add_field(
        name="Host",
        value=(
            f"Sekarang: **{len(current_hosts)}**\n"
            f"Backup: **{len(hosts)}**"
        ),
        inline=True
    )
    embed.add_field(
        name="Diff Host",
        value=(
            f"➕ Baru dari backup: **{add_count}**\n"
            f"♻️ Sudah ada: **{existing_count}**\n"
            f"⚠️ Ada sekarang, tidak di backup: **{missing_count}**"
        ),
        inline=False
    )
    embed.add_field(
        name="Konfirmasi",
        value=(
            "Tekan **Konfirmasi Restore** hanya setelah diff sesuai."
        ),
        inline=False
    )
    return embed


# ============================================================
# STABILITY / INVOICE / AUDIT / MAINTENANCE
# ============================================================

async def defer_if_needed(interaction: discord.Interaction, *, ephemeral: bool = True) -> bool:
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=ephemeral, thinking=True)
            return True
    except Exception:
        log.exception("Interaction defer gagal")
    return False


def make_error_id() -> str:
    return f"E{int(time.time()) % 1000000:06d}"


async def report_interaction_error(
    interaction: Optional[discord.Interaction],
    error: Exception,
    context: str = "interaction"
):
    error_id = make_error_id()
    log.error(
        "Error ID %s | %s | %s: %s",
        error_id,
        context,
        type(error).__name__,
        error,
        exc_info=(type(error), error, error.__traceback__)
    )

    if interaction is not None:
        try:
            await safe_reply(
                interaction,
                f"❌ Fitur gagal diproses. Error ID: `{error_id}`"
            )
        except Exception:
            pass

    for owner_id in primary_owner_ids():
        try:
            user = bot.get_user(owner_id) or await bot.fetch_user(owner_id)
            await user.send(
                "🚨 **Hi Notifku Error** `" + error_id + "`\n"
                "Konteks: `" + context + "`\n"
                "`" + type(error).__name__ + ": " + str(error)[:1200] + "`"
            )
        except Exception:
            pass

    return error_id


async def global_view_error(
    self,
    interaction: discord.Interaction,
    error: Exception,
    item
):
    await report_interaction_error(
        interaction,
        error,
        context=(
            "view:"
            + self.__class__.__name__
            + ":"
            + str(getattr(item, "custom_id", None))
        )
    )


discord.ui.View.on_error = global_view_error


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: discord.app_commands.AppCommandError
):
    original = getattr(error, "original", error)
    await report_interaction_error(
        interaction,
        original,
        context="slash_command"
    )


def generate_invoice_ref(order_id: int, created_at: Optional[int] = None) -> str:
    ts = int(created_at or time.time())
    date_part = datetime.fromtimestamp(
        ts,
        tz=timezone.utc
    ).strftime("%Y%m%d")
    return f"INV-{date_part}-{int(order_id):06d}"


def ensure_invoice_ref(order_id: int) -> str:
    order = get_premium_order(order_id)

    if not order:
        raise ValueError("Order tidak ditemukan.")

    if order["invoice_ref"]:
        return str(order["invoice_ref"])

    ref = generate_invoice_ref(order_id, order["created_at"])

    with closing(db()) as conn:
        conn.execute(
            "UPDATE premium_orders SET invoice_ref=? WHERE id=?",
            (ref, int(order_id))
        )
        conn.commit()

    return ref


def invoice_image_bytes(order) -> bytes:
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow belum tersedia.")

    invoice_ref = order["invoice_ref"] or ensure_invoice_ref(order["id"])
    image = Image.new("RGB", (900, 650), "white")
    draw = ImageDraw.Draw(image)

    deadline = "-"
    if order["invoice_deadline"]:
        deadline = datetime.fromtimestamp(
            int(order["invoice_deadline"]),
            tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        ("HI NOTIFKU - PREMIUM INVOICE", 40, 35),
        (invoice_ref, 40, 90),
        ("Server ID: " + str(order["guild_id"]), 40, 160),
        ("Paket: " + str(order["days"]) + " hari", 40, 210),
        ("Harga: " + rupiah(order["price"]), 40, 260),
        ("Kode unik: " + f"{int(order['unique_code'] or 0):03d}", 40, 310),
        (
            "TOTAL TRANSFER: "
            + rupiah(int(order["expected_amount"] or order["price"])),
            40,
            370
        ),
        (
            "Metode: " + str(order["payment_method_name"] or "Belum dipilih"),
            40,
            440
        ),
        ("Deadline: " + deadline, 40, 495),
        ("Bayar sesuai nominal tepat. Jangan dibulatkan.", 40, 560),
    ]

    for text_value, x, y in lines:
        draw.text((x, y), text_value, fill="black")

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


async def send_payment_admin_log(
    title: str,
    description: str,
    *,
    guild_id: Optional[int] = None
):
    if not PAYMENT_LOG_CHANNEL_ID:
        return

    channel = bot.get_channel(PAYMENT_LOG_CHANNEL_ID)
    if not channel:
        return

    try:
        embed = discord.Embed(
            title=title,
            description=description[:4000],
            color=discord.Color.gold()
        )
        if guild_id:
            embed.set_footer(text=f"Guild ID: {guild_id}")
        await channel.send(embed=embed)
    except Exception:
        log.exception("Gagal mengirim payment log")


async def audit_webhook(
    action: str,
    detail: str,
    *,
    actor_id: Optional[int] = None,
    guild_id: Optional[int] = None
):
    if not AUDIT_WEBHOOK_URL or http is None or http.closed:
        return

    content = (
        "🧾 **" + action + "**\n"
        "Actor: `" + str(actor_id or "-") + "` • "
        "Guild: `" + str(guild_id or "-") + "`\n"
        + detail[:1500]
    )

    try:
        async with http.post(
            AUDIT_WEBHOOK_URL,
            json={"content": content},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status >= 300:
                log.warning("Audit webhook HTTP %s", response.status)
    except Exception:
        log.exception("Audit webhook gagal")


def set_pending_upload(user_id: int, upload_type: str, target_id: int):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO pending_uploads(user_id, upload_type, target_id, created_at)
            VALUES(?,?,?,?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                upload_type=excluded.upload_type,
                target_id=excluded.target_id,
                created_at=excluded.created_at
        """, (
            int(user_id),
            upload_type,
            int(target_id),
            int(time.time())
        ))
        conn.commit()


def get_pending_upload(user_id: int):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM pending_uploads WHERE user_id=?",
            (int(user_id),)
        ).fetchone()


def clear_pending_upload(user_id: int):
    with closing(db()) as conn:
        conn.execute(
            "DELETE FROM pending_uploads WHERE user_id=?",
            (int(user_id),)
        )
        conn.commit()


def claim_order_for_activation(order_id: int, actor_id: int) -> bool:
    now = int(time.time())

    with closing(db()) as conn:
        cur = conn.execute("""
            UPDATE premium_orders
            SET
                status='processing',
                processing_by=?,
                processing_at=?,
                updated_at=?
            WHERE id=?
              AND activated_at IS NULL
              AND status IN ('amount_verified','paid')
        """, (
            int(actor_id),
            now,
            now,
            int(order_id)
        ))
        conn.commit()
        return cur.rowcount == 1


def release_order_claim(
    order_id: int,
    fallback_status: str = "amount_verified"
):
    with closing(db()) as conn:
        conn.execute("""
            UPDATE premium_orders
            SET
                status=?,
                processing_by=NULL,
                processing_at=NULL,
                updated_at=?
            WHERE id=?
              AND status='processing'
              AND activated_at IS NULL
        """, (
            fallback_status,
            int(time.time()),
            int(order_id)
        ))
        conn.commit()


def order_is_actionable(order) -> bool:
    if not order:
        return False

    if order["activated_at"]:
        return False

    if order["status"] in {
        "active",
        "expired",
        "invoice_expired",
        "rejected",
        "processing"
    }:
        return False

    if (
        order["invoice_deadline"]
        and int(order["invoice_deadline"]) <= int(time.time())
    ):
        return False

    return True


def set_payment_method_enabled(method_id: int, enabled: bool):
    with closing(db()) as conn:
        conn.execute("""
            UPDATE payment_methods
            SET enabled=?, updated_at=?
            WHERE id=?
        """, (
            1 if enabled else 0,
            int(time.time()),
            int(method_id)
        ))
        conn.commit()


def database_maintenance():
    now = int(time.time())
    tx_cutoff = now - TRANSACTION_RETENTION_DAYS * 86400
    invoice_cutoff = now - EXPIRED_INVOICE_RETENTION_DAYS * 86400
    activity_cutoff = now - ACTIVITY_RETENTION_DAYS * 86400

    with closing(db()) as conn:
        conn.execute("""
            DELETE FROM premium_orders
            WHERE updated_at<?
              AND status IN ('expired','rejected')
        """, (tx_cutoff,))
        conn.execute("""
            DELETE FROM premium_orders
            WHERE updated_at<?
              AND status='invoice_expired'
        """, (invoice_cutoff,))

        if table_exists(conn, "activity_log"):
            activity_cols = columns(conn, "activity_log")
            time_col = (
                "created_at"
                if "created_at" in activity_cols
                else ("ts" if "ts" in activity_cols else None)
            )
            if time_col:
                conn.execute(
                    f"DELETE FROM activity_log WHERE {time_col}<?",
                    (activity_cutoff,)
                )

        conn.execute(
            "DELETE FROM premium_reminders WHERE sent_at<?",
            (tx_cutoff,)
        )
        conn.execute(
            "DELETE FROM pending_uploads WHERE created_at<?",
            (now - 86400,)
        )
        conn.execute(
            "DELETE FROM payment_callback_events WHERE received_at<?",
            (tx_cutoff,)
        )
        conn.execute(
            "DELETE FROM payment_event_dead_letter "
            "WHERE resolved_at IS NOT NULL AND resolved_at<?",
            (tx_cutoff,)
        )
        notifier_cutoff = now - EVENT_RETENTION_DAYS * 86400
        conn.execute(
            "DELETE FROM notification_history WHERE created_at<?",
            (notifier_cutoff,)
        )
        conn.execute(
            "DELETE FROM notification_events WHERE created_at<?",
            (notifier_cutoff,)
        )
        conn.execute(
            "DELETE FROM config_snapshots WHERE created_at<?",
            (now - max(30, TRANSACTION_RETENTION_DAYS) * 86400,)
        )
        conn.execute("""
            UPDATE premium_orders
            SET
                status=CASE
                    WHEN amount_verified=1 THEN 'amount_verified'
                    ELSE 'paid'
                END,
                processing_by=NULL,
                processing_at=NULL,
                updated_at=?
            WHERE status='processing'
              AND processing_at IS NOT NULL
              AND processing_at<?
              AND activated_at IS NULL
        """, (
            now,
            now - 600
        ))
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")


def sqlite_storage_stats() -> dict:
    db_path = Path(DB_PATH).expanduser()
    wal_path = Path(str(db_path) + "-wal")
    shm_path = Path(str(db_path) + "-shm")
    return {
        "db_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
        "shm_bytes": shm_path.stat().st_size if shm_path.exists() else 0,
    }


@tasks.loop(minutes=30)
async def sqlite_wal_monitor_loop():
    try:
        stats = sqlite_storage_stats()
        # If WAL grows past 64 MB, request a passive checkpoint.
        if stats["wal_bytes"] >= 64 * 1024 * 1024:
            with closing(db()) as conn:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                conn.commit()
            log.warning(
                "SQLite WAL checkpoint dipicu otomatis. wal_bytes=%s",
                stats["wal_bytes"]
            )
    except Exception:
        log.exception("SQLite WAL monitor gagal")


@sqlite_wal_monitor_loop.before_loop
async def before_sqlite_wal_monitor_loop():
    await bot.wait_until_ready()


@tasks.loop(hours=DB_MAINTENANCE_HOURS)
async def db_maintenance_loop():
    try:
        await asyncio.to_thread(database_maintenance)
        log.info("Database maintenance selesai.")
    except Exception:
        log.exception("Database maintenance gagal")


@db_maintenance_loop.before_loop
async def before_db_maintenance():
    await bot.wait_until_ready()


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


async def require_owner_level(
    interaction: discord.Interaction,
    minimum: str = "read_only"
) -> bool:
    if not is_global_owner(interaction.user.id):
        await safe_reply(
            interaction,
            (
                "🔒 Fitur ini hanya untuk **Global Owner Bot**.\n"
                "Pemilik Server dan Host Manager tidak memiliki akses."
            )
        )
        return False

    if not owner_has_level(
        interaction.user.id,
        minimum
    ):
        await safe_reply(
            interaction,
            (
                f"🔒 Role Global Owner-mu (**{owner_role(interaction.user.id)}**) "
                f"belum memenuhi akses **{minimum}**."
            )
        )
        return False

    return True


def is_server_owner(
    user_id: int,
    guild_id: int
) -> bool:
    guild = bot.get_guild(int(guild_id))
    return bool(
        guild
        and int(guild.owner_id) == int(user_id)
    )


async def require_server_owner(
    interaction: discord.Interaction,
    guild_id: int
) -> Optional[discord.Guild]:
    guild = bot.get_guild(int(guild_id))

    if (
        guild is not None
        and int(guild.owner_id) == int(interaction.user.id)
    ):
        return guild

    await safe_reply(
        interaction,
        (
            "🔒 Fitur ini khusus **Pemilik Server** terkait.\n"
            "Akses ini berbeda dari **Global Owner Bot**."
        )
    )
    return None


def premium_purchase_guild_ids(user_id: int) -> list[int]:
    """Servers where a user may buy/renew Premium.

    Premium is a server-level product. A server owner or an active Host Manager
    may pay for the server, while server-management permissions stay unchanged.
    """
    result: list[int] = []

    for guild in user_owned_guilds(int(user_id)):
        guild_id = int(guild.id)
        if guild_id not in result:
            result.append(guild_id)

    for guild_id in host_manager_guild_ids(int(user_id)):
        guild_id = int(guild_id)
        if bot.get_guild(guild_id) is not None and guild_id not in result:
            result.append(guild_id)

    return result


def can_purchase_premium(user_id: int, guild_id: int) -> bool:
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        return False
    if int(guild.owner_id) == int(user_id):
        return True
    return host_manager_has_guild_access(int(user_id), int(guild_id))


def premium_purchase_role_label(user_id: int, guild_id: int) -> str:
    guild = bot.get_guild(int(guild_id))
    if guild and int(guild.owner_id) == int(user_id):
        return "Pemilik Server"
    if host_manager_has_guild_access(int(user_id), int(guild_id)):
        return "Host Manager"
    return "Tidak ada akses"


async def require_premium_purchaser(
    interaction: discord.Interaction,
    guild_id: int
) -> Optional[discord.Guild]:
    guild = bot.get_guild(int(guild_id))
    if guild and can_purchase_premium(interaction.user.id, guild_id):
        return guild

    await safe_reply(
        interaction,
        (
            "🔒 Pembelian Premium untuk server ini hanya dapat dilakukan oleh "
            "**Pemilik Server** atau **Host Manager aktif**.\n"
            "Premium yang dibeli berlaku untuk server, bukan akun pribadi."
        )
    )
    return None


def access_role_label(
    user_id: int,
    guild_id: Optional[int] = None
) -> str:
    roles = []

    if is_global_owner(int(user_id)):
        roles.append("🛡️ Global Owner Bot")

    if guild_id is not None and is_server_owner(
        int(user_id),
        int(guild_id)
    ):
        roles.append("👑 Pemilik Server")

    if roles:
        return " • ".join(roles)

    return "👤 Pengguna"


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


def get_user_verification(user_id: int):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM user_verifications
            WHERE user_id=?
        """, (int(user_id),)).fetchone()


def set_user_verification(
    user_id: int,
    verified: bool,
    *,
    source: str,
    reason: str = "",
    mark_active: bool = False
):
    # Global Owner Bot is permanently exempt from user verification storage.
    if is_global_owner(int(user_id)):
        return

    now = int(time.time())

    with closing(db()) as conn:
        previous = conn.execute("""
            SELECT *
            FROM user_verifications
            WHERE user_id=?
        """, (int(user_id),)).fetchone()

        created_at = (
            int(previous["created_at"])
            if previous and previous["created_at"]
            else now
        )

        last_active_at = (
            now
            if mark_active
            else (
                int(previous["last_active_at"])
                if previous and previous["last_active_at"]
                else now
            )
        )

        conn.execute("""
            INSERT INTO user_verifications(
                user_id,
                verified,
                verified_at,
                last_checked_at,
                last_active_at,
                created_at,
                verification_source,
                status_reason
            )
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                verified=excluded.verified,
                verified_at=excluded.verified_at,
                last_checked_at=excluded.last_checked_at,
                last_active_at=excluded.last_active_at,
                verification_source=excluded.verification_source,
                status_reason=excluded.status_reason
        """, (
            int(user_id),
            1 if verified else 0,
            now if verified else None,
            now,
            last_active_at,
            created_at,
            str(source)[:80],
            str(reason)[:500]
        ))
        conn.commit()


def touch_user_verification_activity(user_id: int):
    if is_global_owner(int(user_id)):
        return

    now = int(time.time())

    with closing(db()) as conn:
        conn.execute("""
            UPDATE user_verifications
            SET last_active_at=?
            WHERE user_id=? AND verified=1
        """, (
            now,
            int(user_id)
        ))
        conn.commit()


def user_verification_is_active(user_id: int) -> bool:
    if is_global_owner(int(user_id)):
        return True

    row = get_user_verification(user_id)
    if not row or not row["verified"]:
        return False

    cutoff = int(time.time()) - (
        int(VERIFICATION_RETENTION_DAYS) * 86400
    )

    return int(row["last_active_at"] or 0) > cutoff


async def refresh_user_verification(
    user_id: int,
    *,
    source: str,
    mark_active: bool = False
) -> bool:
    if is_global_owner(int(user_id)):
        return True

    if not REQUIRED_GUILD_ID:
        return False

    verified = await is_user_in_required_guild(
        int(user_id)
    )

    set_user_verification(
        int(user_id),
        verified,
        source=source,
        reason=(
            "User terdeteksi di Server Owner/Support."
            if verified
            else "User tidak terdeteksi di Server Owner/Support."
        ),
        mark_active=mark_active
    )

    return verified


def user_verification_status_text(user_id: int) -> str:
    if is_global_owner(int(user_id)):
        return "👑 Global Owner • bypass"

    row = get_user_verification(user_id)

    if not row:
        return "🔒 Belum terverifikasi"

    if not row["verified"]:
        return "🔒 Tidak terverifikasi"

    last_active = int(row["last_active_at"] or 0)
    expires_at = last_active + int(VERIFICATION_RETENTION_DAYS) * 86400

    return (
        f"✅ Terverifikasi • aktif <t:{last_active}:R>\n"
        f"Retensi sampai <t:{expires_at}:R>"
    )


def cleanup_stale_user_verifications() -> int:
    cutoff = int(time.time()) - (
        int(VERIFICATION_RETENTION_DAYS) * 86400
    )

    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT user_id
            FROM user_verifications
            WHERE last_active_at<=?
        """, (cutoff,)).fetchall()

        removable = [
            int(row["user_id"])
            for row in rows
            if not is_global_owner(int(row["user_id"]))
        ]

        if removable:
            placeholders = ",".join("?" for _ in removable)
            conn.execute(
                f"""
                DELETE FROM user_verifications
                WHERE user_id IN ({placeholders})
                """,
                removable
            )
            conn.commit()

    return len(removable)




def set_guild_owner_verification(
    guild_id: int,
    owner_id: int,
    verified: bool,
    *,
    source: str = "live_check",
    reason: Optional[str] = None,
    user_active: bool = False
):
    now = int(time.time())

    with closing(db()) as conn:
        existing = conn.execute("""
            SELECT *
            FROM guild_owner_verification
            WHERE guild_id=?
        """, (int(guild_id),)).fetchone()

        created_at = (
            int(existing["created_at"])
            if existing and existing["created_at"]
            else now
        )

        previous_active = (
            int(existing["last_active_at"])
            if existing and "last_active_at" in existing.keys()
            and existing["last_active_at"]
            else None
        )

        previous_inactive_since = (
            int(existing["inactive_since"])
            if existing and "inactive_since" in existing.keys()
            and existing["inactive_since"]
            else None
        )

        last_active_at = now if user_active else previous_active

        # First known verification counts as activity.
        if last_active_at is None and verified:
            last_active_at = now

        inactive_since = None if verified else (
            previous_inactive_since or now
        )

        conn.execute("""
            INSERT INTO guild_owner_verification(
                guild_id,
                owner_id,
                verified,
                verified_at,
                last_checked_at,
                created_at,
                verification_source,
                status_reason,
                last_active_at,
                inactive_since
            )
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(guild_id)
            DO UPDATE SET
                owner_id=excluded.owner_id,
                verified=excluded.verified,
                verified_at=excluded.verified_at,
                last_checked_at=excluded.last_checked_at,
                verification_source=excluded.verification_source,
                status_reason=excluded.status_reason,
                last_active_at=COALESCE(excluded.last_active_at, guild_owner_verification.last_active_at),
                inactive_since=excluded.inactive_since
        """, (
            int(guild_id),
            int(owner_id),
            1 if verified else 0,
            now if verified else None,
            now,
            created_at,
            str(source),
            reason,
            last_active_at,
            inactive_since
        ))
        conn.commit()


def touch_guild_owner_verification_activity(
    guild_id: int,
    owner_id: int
):
    now = int(time.time())
    with closing(db()) as conn:
        conn.execute("""
            UPDATE guild_owner_verification
            SET last_active_at=?,
                owner_id=?
            WHERE guild_id=?
        """, (
            now,
            int(owner_id),
            int(guild_id)
        ))
        conn.commit()


def cleanup_stale_verification_records() -> int:
    """
    Legacy compatibility helper.
    Guild-owner verification is no longer deleted by the 30-day user
    retention policy. Retention applies to user_verifications instead.
    """
    return 0


def get_guild_owner_verification(guild_id: int):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT * FROM guild_owner_verification
            WHERE guild_id=?
        """, (int(guild_id),)).fetchone()


async def refresh_guild_owner_verification(
    guild: discord.Guild,
    *,
    source: str = "live_check",
    user_active: bool = False
) -> bool:
    if not REQUIRED_GUILD_ID:
        verified = True
        reason = "REQUIRED_GUILD_ID tidak dikonfigurasi."
    else:
        verified = await is_user_in_required_guild(
            guild.owner_id
        )
        reason = (
            "Owner terdeteksi sebagai member Server Owner/Support."
            if verified
            else "Owner belum terdeteksi di Server Owner/Support."
        )

    set_guild_owner_verification(
        guild.id,
        guild.owner_id,
        verified,
        source=source,
        reason=reason,
        user_active=user_active
    )
    return verified


async def verify_owned_guilds_for_user(
    user_id: int
) -> tuple[int, int]:
    owned = [
        guild for guild in bot.guilds
        if int(guild.owner_id) == int(user_id)
    ]
    verified_count = 0

    for guild in owned:
        if await refresh_guild_owner_verification(
            guild,
            source="owner_manual_refresh",
            user_active=True
        ):
            verified_count += 1

    return verified_count, len(owned)


async def auto_verify_owned_guilds_for_member(
    user_id: int,
    *,
    verified: bool
) -> int:
    """
    Automatically update every guild owned by this Discord user.
    Used when they join/leave REQUIRED_GUILD_ID.
    """
    updated = 0

    for guild in bot.guilds:
        if int(guild.owner_id) != int(user_id):
            continue

        set_guild_owner_verification(
            guild.id,
            guild.owner_id,
            verified,
            source=(
                "support_member_join"
                if verified
                else "support_member_remove"
            ),
            reason=(
                "Owner join Server Owner/Support."
                if verified
                else "Owner keluar dari Server Owner/Support."
            ),
            user_active=bool(verified)
        )
        updated += 1

    return updated


async def notify_owner_auto_verification(
    user_id: int,
    *,
    verified: bool,
    guild_count: int
):
    try:
        user = bot.get_user(int(user_id)) or await bot.fetch_user(int(user_id))

        if verified:
            await user.send(
                embed=discord.Embed(
                    title="✅ Verifikasi Pemilik Server Otomatis",
                    description=(
                        "Kamu sudah terdeteksi join **Server Owner/Support**.\n"
                        f"Sebanyak **{guild_count}** server milikmu otomatis "
                        "berstatus **TERVERIFIKASI**.\n\n"
                        "Notifier dapat berjalan tanpa menunggu persetujuan manual."
                    ),
                    color=discord.Color.green()
                )
            )
        else:
            await user.send(
                embed=discord.Embed(
                    title="🔒 Verifikasi Pemilik Server Dicabut",
                    description=(
                        "Kamu tidak lagi terdeteksi sebagai member "
                        "**Server Owner/Support**.\n"
                        f"Sebanyak **{guild_count}** server milikmu kembali "
                        "berstatus **BELUM TERVERIFIKASI** dan notifier ditahan."
                    ),
                    color=discord.Color.orange()
                )
            )
    except Exception:
        log.exception(
            "Gagal kirim DM perubahan verifikasi otomatis user_id=%s",
            user_id
        )




def guild_verification_status_text(guild_id: int) -> str:
    row = get_guild_owner_verification(guild_id)

    if not row:
        return "⚠️ Belum dicek"

    if row["verified"]:
        checked = (
            f" • <t:{int(row['last_checked_at'])}:R>"
            if row["last_checked_at"]
            else ""
        )
        return f"✅ Terverifikasi{checked}"

    checked = (
        f" • <t:{int(row['last_checked_at'])}:R>"
        if row["last_checked_at"]
        else ""
    )
    return f"🔒 Belum terverifikasi{checked}"


def guild_verification_detail_embed(guild: discord.Guild):
    row = get_guild_owner_verification(guild.id)

    if not row:
        return discord.Embed(
            title="🔐 Status Verifikasi Owner",
            description="Status belum pernah diperiksa.",
            color=discord.Color.orange()
        )

    verified = bool(row["verified"])
    embed = discord.Embed(
        title=f"🔐 Verifikasi Owner • {guild.name}",
        description=(
            "✅ **TERVERIFIKASI**"
            if verified
            else "🔒 **BELUM TERVERIFIKASI**"
        ),
        color=(
            discord.Color.green()
            if verified
            else discord.Color.orange()
        )
    )
    embed.add_field(
        name="Pemilik Server",
        value=f"<@{row['owner_id']}> (`{row['owner_id']}`)",
        inline=False
    )
    embed.add_field(
        name="Sumber",
        value=str(row["verification_source"] or "-"),
        inline=True
    )
    embed.add_field(
        name="Terakhir Dicek",
        value=(
            f"<t:{int(row['last_checked_at'])}:F>\n"
            f"<t:{int(row['last_checked_at'])}:R>"
            if row["last_checked_at"]
            else "-"
        ),
        inline=True
    )
    embed.add_field(
        name="Keterangan",
        value=str(row["status_reason"] or "-")[:1024],
        inline=False
    )
    last_active = (
        int(row["last_active_at"])
        if "last_active_at" in row.keys() and row["last_active_at"]
        else int(row["created_at"])
    )
    expiry = last_active + int(VERIFICATION_RETENTION_DAYS) * 86400

    embed.add_field(
        name="Retensi",
        value=(
            f"Aktivitas terakhir: <t:{last_active}:R>\n"
            f"Hapus otomatis jika tidak aktif sampai <t:{expiry}:F>"
        ),
        inline=False
    )

    embed.add_field(
        name="Aktivasi",
        value=(
            "Notifier boleh berjalan."
            if verified
            else (
                "Notifier ditahan. Owner cukup join Server Owner/Support; "
                "verifikasi aktif otomatis tanpa approval manual."
            )
        ),
        inline=False
    )
    return embed


async def guild_owner_verified(guild: discord.Guild) -> bool:
    # Always refresh live. Missing guild-owner verification rows are
    # recreated automatically and are not governed by user retention.
    return await refresh_guild_owner_verification(
        guild,
        source="live_check",
        user_active=False
    )


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


def get_runtime_tuning():
    """
    Bootstrap-safe runtime tuning reader.

    This function can be called before migrate_database() runs, because some
    UI/classes are constructed while the module is being imported. If the
    runtime_tuning table does not exist yet, return in-memory defaults instead
    of querying SQLite and crashing startup.
    """
    defaults = {
        "id": 1,
        "monitor_concurrency": int(MONITOR_CONCURRENCY),
        "notification_max_retries": int(NOTIFICATION_MAX_RETRIES),
        "error_alert_threshold": int(ERROR_ALERT_THRESHOLD),
        "circuit_breaker_minutes": 10,
        "updated_by": None,
        "updated_at": None,
    }

    try:
        with closing(db()) as conn:
            if not table_exists(conn, "runtime_tuning"):
                return defaults

            row = conn.execute(
                "SELECT * FROM runtime_tuning WHERE id=1"
            ).fetchone()

            if row:
                return row

            conn.execute("""
                INSERT OR IGNORE INTO runtime_tuning(
                    id, monitor_concurrency, notification_max_retries,
                    error_alert_threshold, circuit_breaker_minutes
                )
                VALUES(1,?,?,?,10)
            """, (
                int(MONITOR_CONCURRENCY),
                int(NOTIFICATION_MAX_RETRIES),
                int(ERROR_ALERT_THRESHOLD)
            ))
            conn.commit()

            row = conn.execute(
                "SELECT * FROM runtime_tuning WHERE id=1"
            ).fetchone()

            return row or defaults

    except sqlite3.OperationalError:
        # Database schema may still be bootstrapping.
        return defaults


def runtime_tuning_int(name: str, fallback: int) -> int:
    row = get_runtime_tuning()
    if row and name in row.keys():
        try:
            return int(row[name])
        except Exception:
            pass
    return int(fallback)


def update_runtime_tuning(
    *,
    monitor_concurrency: int,
    notification_max_retries: int,
    error_alert_threshold: int,
    circuit_breaker_minutes: int,
    actor_id: int
):
    values = {
        "monitor_concurrency": max(1, min(20, int(monitor_concurrency))),
        "notification_max_retries": max(1, min(10, int(notification_max_retries))),
        "error_alert_threshold": max(1, min(100, int(error_alert_threshold))),
        "circuit_breaker_minutes": max(1, min(60, int(circuit_breaker_minutes))),
    }
    with closing(db()) as conn:
        if not table_exists(conn, "runtime_tuning"):
            raise RuntimeError(
                "Database belum selesai migrasi. Coba lagi setelah bot Ready."
            )

        conn.execute("""
            UPDATE runtime_tuning
            SET
                monitor_concurrency=?,
                notification_max_retries=?,
                error_alert_threshold=?,
                circuit_breaker_minutes=?,
                updated_by=?,
                updated_at=?
            WHERE id=1
        """, (
            values["monitor_concurrency"],
            values["notification_max_retries"],
            values["error_alert_threshold"],
            values["circuit_breaker_minutes"],
            int(actor_id),
            int(time.time())
        ))
        conn.commit()
    return values


def get_runtime_settings():
    with closing(db()) as conn:
        row = conn.execute("""
            SELECT *
            FROM bot_runtime_settings
            WHERE id=1
        """).fetchone()

    if row:
        return row

    with closing(db()) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO bot_runtime_settings(
                id,
                monitor_paused,
                notifications_paused,
                requests_paused,
                maintenance_all
            )
            VALUES(1,0,0,0,0)
        """)
        conn.commit()
        return conn.execute(
            "SELECT * FROM bot_runtime_settings WHERE id=1"
        ).fetchone()


def set_runtime_setting(
    name: str,
    enabled: bool,
    actor_id: int
):
    allowed = {
        "monitor_paused",
        "notifications_paused",
        "requests_paused",
        "maintenance_all",
    }
    if name not in allowed:
        raise ValueError("Runtime setting tidak valid.")

    with closing(db()) as conn:
        conn.execute(
            f"""
            UPDATE bot_runtime_settings
            SET {name}=?,
                updated_by=?,
                updated_at=?
            WHERE id=1
            """,
            (
                1 if enabled else 0,
                int(actor_id),
                int(time.time())
            )
        )
        conn.commit()


def runtime_setting_enabled(name: str) -> bool:
    row = get_runtime_settings()
    return bool(row[name]) if row and name in row.keys() else False


def reset_host_error_state(host_id: int):
    with closing(db()) as conn:
        conn.execute("""
            UPDATE hosts
            SET last_error=NULL,
                error_count=0,
                cooldown_until=NULL
            WHERE id=?
        """, (int(host_id),))
        conn.commit()


def host_health_score(host) -> int:
    score = 100

    if not host["enabled"]:
        score -= 20

    errors = int(host["error_count"] or 0)
    score -= min(60, errors * 8)

    if host["last_error"]:
        score -= 15

    if (
        host["cooldown_until"]
        and int(host["cooldown_until"]) > int(time.time())
    ):
        score -= 15

    return max(0, min(100, score))


def access_state_label(state: str) -> str:
    return {
        "allowed": "🟢 Normal",
        "whitelist": "🔵 Whitelist",
        "warning": "🟡 Warning",
        "suspended": "🟠 Suspended",
        "blacklist": "🔴 Blacklist",
    }.get(str(state), str(state))


def global_notification_stats():
    now = int(time.time())
    day_start = now - 86400

    with closing(db()) as conn:
        summary = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                AVG(CASE WHEN latency_ms IS NOT NULL THEN latency_ms END) AS latency
            FROM notification_history
            WHERE created_at>=?
        """, (day_start,)).fetchone()

        recent = conn.execute("""
            SELECT nh.*, h.platform, h.target, h.display_name
            FROM notification_history nh
            LEFT JOIN hosts h ON h.id=nh.host_id
            ORDER BY nh.id DESC
            LIMIT 20
        """).fetchall()

    return summary, recent


def global_activity_rows(limit: int = 25):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM activity_log
            ORDER BY id DESC
            LIMIT ?
        """, (max(1, min(50, int(limit))),)).fetchall()


def api_usage_today_rows():
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with closing(db()) as conn:
        return conn.execute("""
            SELECT service, endpoint, calls
            FROM api_usage
            WHERE day=?
            ORDER BY calls DESC, service, endpoint
        """, (day,)).fetchall()


def manual_backup_payload_and_bytes():
    payload = create_full_backup_payload()
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2
    ).encode("utf-8")
    return payload, raw


def backup_restore_smoke_test(payload: dict) -> tuple[bool, str]:
    ok, detail = verify_backup_payload(payload)
    if not ok:
        return False, detail

    try:
        restored = json.loads(json.dumps(payload, ensure_ascii=False))
        for guild_item in restored.get("guilds", []):
            guild_id = int(guild_item["guild_id"])
            for host in guild_item.get("hosts", []):
                if "platform" not in host or "target" not in host:
                    return False, (
                        f"Host invalid pada guild {guild_id}: "
                        "platform/target tidak lengkap."
                    )
        return True, (
            f"Restore smoke-test OK • "
            f"{len(restored.get('guilds', []))} server."
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def verify_backup_payload(payload: dict) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Root backup bukan object JSON."

    version = payload.get("version")
    guilds = payload.get("guilds")

    if not isinstance(version, int):
        return False, "Field version tidak valid."

    if not isinstance(guilds, list):
        return False, "Field guilds tidak valid."

    for index, item in enumerate(guilds[:1000]):
        if not isinstance(item, dict):
            return False, f"Guild index {index} bukan object."
        if "guild_id" not in item:
            return False, f"Guild index {index} tidak memiliki guild_id."
        if not isinstance(item.get("hosts", []), list):
            return False, f"hosts pada guild {item.get('guild_id')} tidak valid."

    return True, f"Backup valid • version {version} • {len(guilds)} server"


def owner_self_test_results() -> list[tuple[str, bool, str]]:
    results = []

    results.append((
        "Discord",
        bool(bot.user),
        f"Bot {'online' if bot.user else 'belum ready'} • ping {round(bot.latency * 1000)} ms"
    ))

    try:
        with closing(db()) as conn:
            conn.execute("SELECT 1").fetchone()
        db_ok = True
        db_detail = f"Database OK • {DB_PATH}"
    except Exception as exc:
        db_ok = False
        db_detail = f"{type(exc).__name__}: {exc}"
    results.append(("Database", db_ok, db_detail))

    try:
        folder = Path(AUTO_BACKUP_DIR)
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".selftest-write"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        storage_ok = True
        storage_detail = f"Writable • {folder}"
    except Exception as exc:
        storage_ok = False
        storage_detail = f"{type(exc).__name__}: {exc}"
    results.append(("Storage", storage_ok, storage_detail))

    results.append((
        "YouTube API",
        bool(YOUTUBE_API_KEY),
        "Key loaded" if YOUTUBE_API_KEY else "YOUTUBE_API_KEY kosong"
    ))

    results.append((
        "Monitor Loop",
        monitor_loop.is_running(),
        "running" if monitor_loop.is_running() else "STOP"
    ))
    results.append((
        "Premium Loop",
        premium_expiry_loop.is_running(),
        "running" if premium_expiry_loop.is_running() else "STOP"
    ))
    results.append((
        "Invoice Loop",
        invoice_expiry_loop.is_running(),
        "running" if invoice_expiry_loop.is_running() else "STOP"
    ))
    results.append((
        "Backup Loop",
        auto_backup_loop.is_running(),
        "running" if auto_backup_loop.is_running() else "STOP"
    ))
    results.append((
        "Maintenance Loop",
        db_maintenance_loop.is_running(),
        "running" if db_maintenance_loop.is_running() else "STOP"
    ))

    settings = get_runtime_settings()
    results.append((
        "Emergency Mode",
        not bool(settings["maintenance_all"]),
        (
            "normal"
            if not settings["maintenance_all"]
            else "maintenance_all aktif"
        )
    ))

    return results




def guild_access_allowed(guild_id: int) -> bool:
    return effective_access_state(guild_id) not in {"blacklist", "suspended"}


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



# ============================================================
# NOTIFIER PRO
# ============================================================

DEFAULT_FEATURE_FLAGS = {
    "tiktok_live": True,
    "tiktok_post": True,
    "youtube_live": True,
    "twitch_live": True,
    "kick_live": True,
    "instagram_post": True,
    "facebook_post": True,
    "live_end": True,
}


def parse_id_csv(value: Optional[str]) -> list[int]:
    if not value:
        return []

    result = []
    for raw in str(value).replace(";", ",").split(","):
        raw = raw.strip()
        if raw.isdigit():
            number = int(raw)
            if number not in result:
                result.append(number)
    return result[:20]


def feature_flags_for_guild(guild_id: int) -> dict:
    settings = get_guild_settings(guild_id)
    flags = dict(DEFAULT_FEATURE_FLAGS)

    raw = settings["feature_flags"]
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                for key in flags:
                    if key in loaded:
                        flags[key] = bool(loaded[key])
        except Exception:
            pass

    return flags


def feature_enabled(guild_id: int, feature: str) -> bool:
    return feature_flags_for_guild(guild_id).get(feature, True)


def set_feature_flags(guild_id: int, enabled_names: list[str]):
    allowed = set(DEFAULT_FEATURE_FLAGS)
    enabled = {x.strip().lower() for x in enabled_names}
    payload = {
        key: key in enabled
        for key in allowed
    }

    with closing(db()) as conn:
        conn.execute(
            "UPDATE guild_settings SET feature_flags=? WHERE guild_id=?",
            (json.dumps(payload), int(guild_id))
        )
        conn.commit()


def set_guild_notifier_settings(
    guild_id: int,
    *,
    timezone_name: Optional[str] = None,
    language: Optional[str] = None,
    maintenance_mode: Optional[bool] = None
):
    ensure_guild(guild_id)
    current = get_guild_settings(guild_id)

    tz = timezone_name if timezone_name is not None else current["timezone"]
    lang = language if language is not None else current["language"]
    maintenance = (
        int(bool(maintenance_mode))
        if maintenance_mode is not None
        else int(current["maintenance_mode"] or 0)
    )

    try:
        ZoneInfo(tz or "Asia/Jakarta")
    except Exception:
        raise ValueError("Timezone tidak valid. Contoh: Asia/Jakarta")

    lang = (lang or "id").lower()
    if lang not in {"id", "en"}:
        lang = "id"

    with closing(db()) as conn:
        conn.execute("""
            UPDATE guild_settings
            SET timezone=?, language=?, maintenance_mode=?
            WHERE guild_id=?
        """, (
            tz or "Asia/Jakarta",
            lang,
            maintenance,
            int(guild_id)
        ))
        conn.commit()


def host_timezone(host) -> ZoneInfo:
    tz_name = host["timezone"] if "timezone" in host.keys() else None
    if not tz_name:
        settings = get_guild_settings(int(host["guild_id"]))
        tz_name = settings["timezone"] or "Asia/Jakarta"

    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("Asia/Jakarta")


def host_schedule_allowed(host, now_ts: Optional[int] = None) -> bool:
    if not premium_feature_enabled(int(host["guild_id"]), "advanced_schedule"):
        return True

    now_dt = datetime.fromtimestamp(
        int(now_ts or time.time()),
        tz=host_timezone(host)
    )

    raw_days = (
        host["schedule_days"]
        if "schedule_days" in host.keys()
        else None
    ) or "0,1,2,3,4,5,6"

    days = {
        int(x)
        for x in raw_days.split(",")
        if x.strip().isdigit() and 0 <= int(x) <= 6
    }

    return not days or now_dt.weekday() in days


def _parse_hhmm(value: Optional[str]):
    if not value or ":" not in value:
        return None
    try:
        hh, mm = value.split(":", 1)
        hh, mm = int(hh), int(mm)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except Exception:
        pass
    return None


def host_quiet_now(host, now_ts: Optional[int] = None) -> bool:
    if not premium_feature_enabled(int(host["guild_id"]), "advanced_schedule"):
        return False

    start = _parse_hhmm(host["quiet_start"] if "quiet_start" in host.keys() else None)
    end = _parse_hhmm(host["quiet_end"] if "quiet_end" in host.keys() else None)

    if not start or not end or start == end:
        return False

    now_dt = datetime.fromtimestamp(
        int(now_ts or time.time()),
        tz=host_timezone(host)
    )
    current = now_dt.hour * 60 + now_dt.minute
    s = start[0] * 60 + start[1]
    e = end[0] * 60 + end[1]

    if s < e:
        return s <= current < e
    return current >= s or current < e


def quiet_release_timestamp(host, now_ts: Optional[int] = None) -> int:
    now_dt = datetime.fromtimestamp(
        int(now_ts or time.time()),
        tz=host_timezone(host)
    )
    end = _parse_hhmm(host["quiet_end"] if "quiet_end" in host.keys() else None)

    if not end:
        return int(now_dt.timestamp())

    release = now_dt.replace(
        hour=end[0],
        minute=end[1],
        second=0,
        microsecond=0
    )

    if release <= now_dt:
        from datetime import timedelta
        release = release + timedelta(days=1)

    return int(release.timestamp())


def reserve_notification_event(
    host_id: int,
    event_key: Optional[str],
    event_type: str
) -> bool:
    if not event_key:
        return True

    try:
        with closing(db()) as conn:
            conn.execute("""
                INSERT INTO notification_events(
                    host_id, event_key, event_type, created_at
                )
                VALUES(?,?,?,?)
            """, (
                int(host_id),
                str(event_key)[:300],
                event_type[:80],
                int(time.time())
            ))
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def release_notification_event(
    host_id: int,
    event_key: Optional[str],
    event_type: str
):
    if not event_key:
        return

    with closing(db()) as conn:
        conn.execute("""
            DELETE FROM notification_events
            WHERE host_id=? AND event_key=? AND event_type=?
        """, (
            int(host_id),
            str(event_key)[:300],
            str(event_type)[:80]
        ))
        conn.commit()


def record_notification_history(
    *,
    guild_id: int,
    host_id: Optional[int],
    event_type: str,
    event_key: Optional[str],
    channel_id: Optional[int],
    message_id: Optional[int],
    status: str,
    latency_ms: Optional[int],
    source_url: Optional[str],
    title: Optional[str],
    content: Optional[str],
    embed: Optional[discord.Embed]
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO notification_history(
                guild_id, host_id, event_type, event_key,
                channel_id, message_id, status, latency_ms,
                source_url, title, content, embed_json, created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            int(guild_id),
            int(host_id) if host_id is not None else None,
            event_type[:80],
            event_key[:300] if event_key else None,
            int(channel_id) if channel_id else None,
            int(message_id) if message_id else None,
            status[:40],
            int(latency_ms) if latency_ms is not None else None,
            source_url[:1000] if source_url else None,
            title[:250] if title else None,
            content[:2000] if content else None,
            json.dumps(embed.to_dict(), ensure_ascii=False) if embed else None,
            int(time.time())
        ))
        conn.commit()


def notification_stats(guild_id: int) -> dict:
    analytics_days = int(premium_entitlements(int(guild_id))["analytics_days"])
    cutoff = int(time.time()) - analytics_days * 86400
    with closing(db()) as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS queued,
                AVG(CASE WHEN latency_ms IS NOT NULL THEN latency_ms END) AS avg_latency
            FROM notification_history
            WHERE guild_id=? AND created_at>=?
        """, (int(guild_id), cutoff)).fetchone()

        top = conn.execute("""
            SELECT host_id, COUNT(*) AS total
            FROM notification_history
            WHERE guild_id=? AND status='sent' AND created_at>=?
            GROUP BY host_id
            ORDER BY total DESC
            LIMIT 1
        """, (int(guild_id), cutoff)).fetchone()

    return {
        "total": int(row["total"] or 0),
        "sent": int(row["sent"] or 0),
        "failed": int(row["failed"] or 0),
        "queued": int(row["queued"] or 0),
        "avg_latency": int(row["avg_latency"] or 0),
        "top_host": (
            f"#{top['host_id']} ({top['total']} notif)"
            if top else "-"
        ),
    }


def recent_notifications(guild_id: int, limit: int = 25):
    analytics_days = int(premium_entitlements(int(guild_id))["analytics_days"])
    cutoff = int(time.time()) - analytics_days * 86400
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM notification_history
            WHERE guild_id=? AND created_at>=?
            ORDER BY id DESC
            LIMIT ?
        """, (
            int(guild_id),
            cutoff,
            max(1, min(100, int(limit)))
        )).fetchall()


def get_notification_record(record_id: int):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM notification_history WHERE id=?",
            (int(record_id),)
        ).fetchone()


def record_api_call(service: str, endpoint: str):
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO api_usage(day, service, endpoint, calls)
            VALUES(?,?,?,1)
            ON CONFLICT(day, service, endpoint)
            DO UPDATE SET calls=calls+1
        """, (
            day,
            service[:40],
            endpoint[:80]
        ))
        conn.commit()


def api_usage_today():
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with closing(db()) as conn:
        return conn.execute("""
            SELECT service, endpoint, calls
            FROM api_usage
            WHERE day=?
            ORDER BY service, endpoint
        """, (day,)).fetchall()


def host_delivery_channels(host) -> list[int]:
    primary, _ = notification_target(host)
    result = []

    if primary:
        result.append(int(primary))

    if (
        premium_feature_enabled(int(host["guild_id"]), "extra_channels")
        and "extra_channel_ids" in host.keys()
    ):
        for channel_id in parse_id_csv(host["extra_channel_ids"]):
            if channel_id not in result:
                result.append(channel_id)

    return result[:10]


def host_mention_roles(host) -> list[int]:
    _, primary_role = notification_target(host)
    result = []

    if primary_role:
        result.append(int(primary_role))

    if (
        premium_feature_enabled(int(host["guild_id"]), "extra_channels")
        and "extra_role_ids" in host.keys()
    ):
        for role_id in parse_id_csv(host["extra_role_ids"]):
            if role_id not in result:
                result.append(role_id)

    return result[:10]


def apply_host_embed_branding(host, embed: discord.Embed):
    if not premium_feature_enabled(int(host["guild_id"]), "custom_branding"):
        try:
            if not getattr(embed.footer, "text", None):
                embed.set_footer(text="Powered by Hi Notifku • FREE")
        except Exception:
            pass
        return

    if "embed_title" in host.keys() and host["embed_title"]:
        embed.title = str(host["embed_title"])[:256]

    if "embed_footer" in host.keys() and host["embed_footer"]:
        embed.set_footer(text=str(host["embed_footer"])[:2048])

    if "embed_color" in host.keys() and host["embed_color"]:
        try:
            embed.color = discord.Color(int(host["embed_color"]))
        except Exception:
            pass


def queue_notification_retry(
    host,
    embed: discord.Embed,
    content: Optional[str],
    *,
    event_type: str,
    event_key: Optional[str],
    source_url: Optional[str],
    retry_count: int = 0,
    last_error: str = ""
):
    release_after = int(time.time()) + (
        NOTIFICATION_RETRY_SECONDS * max(1, retry_count + 1)
    )

    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO pending_notifications(
                guild_id, host_id, event_type, event_key,
                content, embed_json, source_url,
                release_after, created_at,
                retry_count, max_retries, last_error
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            int(host["guild_id"]),
            int(host["id"]),
            str(event_type)[:80],
            str(event_key)[:300] if event_key else None,
            content[:2000] if content else None,
            json.dumps(embed.to_dict(), ensure_ascii=False),
            str(source_url)[:1000] if source_url else None,
            release_after,
            int(time.time()),
            int(retry_count),
            int(NOTIFICATION_MAX_RETRIES),
            str(last_error)[:1000]
        ))
        conn.commit()

    runtime_metrics["notifications_queued"] += 1


def move_notification_to_dead_letter(row, reason: str):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO notification_dead_letter(
                guild_id, host_id, event_type, event_key,
                content, embed_json, source_url,
                failure_reason, retry_count, created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?)
        """, (
            int(row["guild_id"]),
            int(row["host_id"]),
            row["event_type"],
            row["event_key"],
            row["content"],
            row["embed_json"],
            row["source_url"],
            str(reason)[:1000],
            int(row["retry_count"] or 0),
            int(time.time())
        ))
        conn.execute(
            "DELETE FROM pending_notifications WHERE id=?",
            (int(row["id"]),)
        )
        conn.commit()


def dead_letter_count() -> int:
    with closing(db()) as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS total
            FROM notification_dead_letter
            WHERE resolved_at IS NULL
        """).fetchone()
    return int(row["total"] or 0)


def recent_dead_letters(limit: int = 15):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM notification_dead_letter
            WHERE resolved_at IS NULL
            ORDER BY id DESC
            LIMIT ?
        """, (max(1, min(25, int(limit))),)).fetchall()




def queue_quiet_notification(
    host,
    embed: discord.Embed,
    content: Optional[str],
    event_type: str,
    event_key: Optional[str],
    source_url: Optional[str]
):
    release_after = quiet_release_timestamp(host)

    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO pending_notifications(
                guild_id, host_id, event_type, event_key,
                content, embed_json, source_url,
                release_after, created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (
            int(host["guild_id"]),
            int(host["id"]),
            event_type[:80],
            event_key[:300] if event_key else None,
            content[:2000] if content else None,
            json.dumps(embed.to_dict(), ensure_ascii=False),
            source_url[:1000] if source_url else None,
            release_after,
            int(time.time())
        ))
        conn.commit()

    runtime_metrics["notifications_queued"] += 1

    record_notification_history(
        guild_id=int(host["guild_id"]),
        host_id=int(host["id"]),
        event_type=event_type,
        event_key=event_key,
        channel_id=None,
        message_id=None,
        status="queued",
        latency_ms=None,
        source_url=source_url,
        title=embed.title,
        content=content,
        embed=embed
    )


async def _deliver_notification_now(
    host,
    embed: discord.Embed,
    content_override: Optional[str],
    *,
    event_type: str,
    event_key: Optional[str],
    source_url: Optional[str]
) -> bool:
    apply_host_embed_branding(host, embed)

    role_ids = host_mention_roles(host)
    content_parts = [f"<@&{rid}>" for rid in role_ids]

    allow_everyone = bool(
        host["mention_everyone"]
        if "mention_everyone" in host.keys()
        else 0
    )

    if allow_everyone:
        content_parts.append("@everyone")

    if content_override:
        content_parts.append(content_override)

    content = "\n".join(content_parts) if content_parts else None
    success_any = False
    start_ts = time.perf_counter()

    # Optional webhook replaces the primary-channel delivery. Extra channels still receive normal sends.
    webhook_url = (
        str(host["webhook_url"]).strip()
        if "webhook_url" in host.keys() and host["webhook_url"]
        else ""
    )

    channels = host_delivery_channels(host)
    primary_channel = channels[0] if channels else None

    if (
        webhook_url
        and premium_feature_enabled(int(host["guild_id"]), "webhook")
        and http is not None
        and not http.closed
    ):
        try:
            webhook = discord.Webhook.from_url(
                webhook_url,
                session=http
            )
            async with notification_send_semaphore:
                await webhook.send(
                    content=content,
                    embed=embed,
                    username="Hi Notifku",
                    allowed_mentions=discord.AllowedMentions(
                        roles=True,
                        users=False,
                        everyone=allow_everyone
                    ),
                    wait=True
                )
                if NOTIFICATION_MIN_DELAY_MS:
                    await asyncio.sleep(NOTIFICATION_MIN_DELAY_MS / 1000)
            success_any = True
            runtime_metrics["notifications_sent"] += 1
            latency = int((time.perf_counter() - start_ts) * 1000)
            record_notification_history(
                guild_id=int(host["guild_id"]),
                host_id=int(host["id"]),
                event_type=event_type,
                event_key=event_key,
                channel_id=None,
                message_id=None,
                status="sent",
                latency_ms=latency,
                source_url=source_url,
                title=embed.title,
                content=content,
                embed=embed
            )
        except Exception:
            runtime_metrics["notifications_failed"] += 1
            log.exception("Webhook notification gagal host_id=%s", host["id"])

        if success_any and primary_channel in channels:
            channels = channels[1:]

    for channel_id in channels:
        channel = await resolve_channel(channel_id)

        if not channel:
            runtime_metrics["notifications_failed"] += 1
            record_notification_history(
                guild_id=int(host["guild_id"]),
                host_id=int(host["id"]),
                event_type=event_type,
                event_key=event_key,
                channel_id=channel_id,
                message_id=None,
                status="failed",
                latency_ms=None,
                source_url=source_url,
                title=embed.title,
                content=content,
                embed=embed
            )
            continue

        try:
            async with notification_send_semaphore:
                message = await channel.send(
                    content=content,
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(
                        roles=True,
                        users=False,
                        everyone=allow_everyone
                    )
                )
                if NOTIFICATION_MIN_DELAY_MS:
                    await asyncio.sleep(NOTIFICATION_MIN_DELAY_MS / 1000)

            success_any = True
            runtime_metrics["notifications_sent"] += 1
            latency = int((time.perf_counter() - start_ts) * 1000)
            record_notification_history(
                guild_id=int(host["guild_id"]),
                host_id=int(host["id"]),
                event_type=event_type,
                event_key=event_key,
                channel_id=channel_id,
                message_id=int(message.id),
                status="sent",
                latency_ms=latency,
                source_url=source_url,
                title=embed.title,
                content=content,
                embed=embed
            )
        except Exception:
            runtime_metrics["notifications_failed"] += 1
            log.exception(
                "Delivery gagal host_id=%s channel_id=%s",
                host["id"],
                channel_id
            )
            record_notification_history(
                guild_id=int(host["guild_id"]),
                host_id=int(host["id"]),
                event_type=event_type,
                event_key=event_key,
                channel_id=channel_id,
                message_id=None,
                status="failed",
                latency_ms=None,
                source_url=source_url,
                title=embed.title,
                content=content,
                embed=embed
            )

    if not success_any:
        guild = bot.get_guild(int(host["guild_id"]))
        if guild:
            try:
                await validation_alert_once(
                    guild,
                    host,
                    "delivery_failed",
                    (
                        "❌ Semua jalur pengiriman notifikasi gagal. "
                        "Periksa webhook, channel, dan permission bot."
                    )
                )
            except Exception:
                pass

    return success_any


async def resend_notification_record(record_id: int) -> bool:
    row = get_notification_record(record_id)

    if not row or not row["channel_id"] or not row["embed_json"]:
        return False

    channel = await resolve_channel(int(row["channel_id"]))
    if not channel:
        return False

    try:
        embed = discord.Embed.from_dict(
            json.loads(row["embed_json"])
        )
        await channel.send(
            content=row["content"],
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                roles=True,
                users=False,
                everyone=False
            )
        )
        return True
    except Exception:
        log.exception("Resend notification gagal id=%s", record_id)
        return False


def create_config_snapshot(guild_id: int, reason: str = "manual") -> int:
    payload = export_guild_backup(int(guild_id))

    with closing(db()) as conn:
        cur = conn.execute("""
            INSERT INTO config_snapshots(
                guild_id, created_at, reason, payload
            )
            VALUES(?,?,?,?)
        """, (
            int(guild_id),
            int(time.time()),
            reason[:200],
            json.dumps(payload, ensure_ascii=False)
        ))
        conn.commit()
        return int(cur.lastrowid)


def latest_config_snapshot(guild_id: int):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM config_snapshots
            WHERE guild_id=?
            ORDER BY id DESC
            LIMIT 1
        """, (int(guild_id),)).fetchone()


def clone_notifier_config(source_guild_id: int, target_guild_id: int):
    source_cfg = get_config(source_guild_id)
    source_settings = get_guild_settings(source_guild_id)
    source_hosts = get_hosts(source_guild_id)

    ensure_guild(target_guild_id)
    create_config_snapshot(target_guild_id, "before clone")

    with closing(db()) as conn:
        conn.execute("""
            UPDATE guild_config
            SET youtube_channel_id=?, tiktok_channel_id=?,
                mention_role_id=?, log_channel_id=?
            WHERE guild_id=?
        """, (
            source_cfg["youtube_channel_id"],
            source_cfg["tiktok_channel_id"],
            source_cfg["mention_role_id"],
            source_cfg["log_channel_id"],
            int(target_guild_id)
        ))

        conn.execute("""
            UPDATE guild_settings
            SET timezone=?, language=?, feature_flags=?
            WHERE guild_id=?
        """, (
            source_settings["timezone"],
            source_settings["language"],
            source_settings["feature_flags"],
            int(target_guild_id)
        ))
        conn.commit()

    for host in source_hosts:
        try:
            add_host(
                target_guild_id,
                host["platform"],
                host["target"],
                host["display_name"],
                host["extra"]
            )
        except ValueError:
            break

        with closing(db()) as conn:
            row = conn.execute("""
                SELECT id FROM hosts
                WHERE guild_id=? AND platform=? AND target=?
            """, (
                int(target_guild_id),
                host["platform"],
                host["target"]
            )).fetchone()

            if row:
                conn.execute("""
                    UPDATE hosts SET
                        channel_id=?, role_id=?,
                        extra_channel_ids=?, extra_role_ids=?,
                        check_interval=?, notify_live_end=?,
                        custom_live_message=?, custom_post_message=?,
                        custom_end_message=?, schedule_days=?,
                        quiet_start=?, quiet_end=?, timezone=?,
                        language=?, webhook_url=?, mention_everyone=?,
                        embed_title=?, embed_footer=?, embed_color=?,
                        auto_pause_threshold=?
                    WHERE id=?
                """, (
                    host["channel_id"],
                    host["role_id"],
                    host["extra_channel_ids"],
                    host["extra_role_ids"],
                    host["check_interval"],
                    host["notify_live_end"],
                    host["custom_live_message"],
                    host["custom_post_message"],
                    host["custom_end_message"],
                    host["schedule_days"],
                    host["quiet_start"],
                    host["quiet_end"],
                    host["timezone"],
                    host["language"],
                    host["webhook_url"],
                    host["mention_everyone"],
                    host["embed_title"],
                    host["embed_footer"],
                    host["embed_color"],
                    host["auto_pause_threshold"],
                    row["id"]
                ))
                conn.commit()


def host_csv_bytes(guild_id: int) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "platform", "target", "display_name", "enabled",
        "check_interval", "channel_id", "role_id",
        "extra_channel_ids", "extra_role_ids",
        "schedule_days", "quiet_start", "quiet_end",
        "timezone", "language"
    ])

    for host in get_hosts(guild_id):
        writer.writerow([
            host["platform"],
            host["target"],
            host["display_name"] or "",
            host["enabled"],
            host["check_interval"],
            host["channel_id"] or "",
            host["role_id"] or "",
            host["extra_channel_ids"] or "",
            host["extra_role_ids"] or "",
            host["schedule_days"] or "",
            host["quiet_start"] or "",
            host["quiet_end"] or "",
            host["timezone"] or "",
            host["language"] or "",
        ])

    return output.getvalue().encode("utf-8-sig")


def diagnostics_embed(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        title=f"🩺 Diagnostics • {guild.name}",
        color=discord.Color.green()
    )

    hosts = get_hosts(guild.id)
    problems = []
    checked = set()

    for host in hosts:
        for channel_id in host_delivery_channels(host):
            if channel_id in checked:
                continue
            checked.add(channel_id)

            channel = guild.get_channel(channel_id)
            if not channel:
                problems.append(f"❌ Channel `{channel_id}` tidak ditemukan")
                continue

            perms = channel.permissions_for(guild.me)
            missing = []

            if not perms.view_channel:
                missing.append("View")
            if not perms.send_messages:
                missing.append("Send")
            if not perms.embed_links:
                missing.append("Embed")

            if missing:
                problems.append(
                    f"⚠️ <#{channel_id}>: " + ", ".join(missing)
                )

    embed.add_field(
        name="Server",
        value=(
            f"Host **{len(hosts)}** • "
            f"Plan **{get_guild_settings(guild.id)['plan'].upper()}**"
        ),
        inline=False
    )
    embed.add_field(
        name="Permission",
        value=(
            "\n".join(problems[:20])
            if problems
            else "✅ Channel yang dikonfigurasi siap digunakan."
        ),
        inline=False
    )

    flags = feature_flags_for_guild(guild.id)
    embed.add_field(
        name="Feature Flags",
        value=" • ".join(
            f"{'✅' if enabled else '⛔'} {name}"
            for name, enabled in flags.items()
        ),
        inline=False
    )

    return embed


def notifier_stats_embed(guild_id: int) -> discord.Embed:
    stats = notification_stats(guild_id)
    usage = api_usage_today()

    embed = discord.Embed(
        title="📈 Statistik Notifikasi",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="Delivery",
        value=(
            f"✅ **{stats['sent']}** terkirim\n"
            f"❌ **{stats['failed']}** gagal\n"
            f"⏳ **{stats['queued']}** pernah antre"
        ),
        inline=True
    )
    embed.add_field(
        name="Latency",
        value=f"Rata-rata **{stats['avg_latency']} ms**",
        inline=True
    )
    embed.add_field(
        name="Host Teraktif",
        value=stats["top_host"],
        inline=True
    )

    usage_text = "\n".join(
        f"{row['service']} `{row['endpoint']}`: **{row['calls']} call**"
        for row in usage[:12]
    ) or "Belum ada panggilan API hari ini."

    embed.add_field(
        name="API Usage Hari Ini",
        value=usage_text,
        inline=False
    )
    embed.set_footer(
        text="API usage adalah jumlah request lokal, bukan unit quota resmi Google."
    )
    return embed


async def send_notification(
    host,
    embed: discord.Embed,
    content_override: Optional[str] = None,
    *,
    event_type: str = "notification",
    event_key: Optional[str] = None,
    source_url: Optional[str] = None,
    dedupe: bool = True
):
    if (
        runtime_setting_enabled("notifications_paused")
        or runtime_setting_enabled("maintenance_all")
    ):
        log.warning(
            "Notifikasi ditahan oleh Emergency Mode host_id=%s",
            host["id"]
        )
        return False

    if dedupe and event_key:
        if not reserve_notification_event(
            int(host["id"]),
            event_key,
            event_type
        ):
            log.info(
                "Duplicate event ditahan host_id=%s event_key=%s",
                host["id"],
                event_key
            )
            return True

    if host_quiet_now(host):
        try:
            queue_quiet_notification(
                host, embed, content_override,
                event_type, event_key, source_url
            )
            return True
        except Exception:
            if dedupe and event_key:
                release_notification_event(
                    int(host["id"]), event_key, event_type
                )
            raise

    delivered = await _deliver_notification_now(
        host,
        embed,
        content_override,
        event_type=event_type,
        event_key=event_key,
        source_url=source_url
    )

    if not delivered:
        try:
            queue_notification_retry(
                host, embed, content_override,
                event_type=event_type,
                event_key=event_key,
                source_url=source_url,
                retry_count=0,
                last_error="Immediate delivery failed"
            )
        except Exception:
            if dedupe and event_key:
                release_notification_event(
                    int(host["id"]), event_key, event_type
                )
            raise

    return delivered


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
    await audit_webhook(
        action,
        detail,
        actor_id=actor_id,
        guild_id=guild_id
    )


# ============================================================
# YOUTUBE
# ============================================================

async def yt_api(endpoint: str, params: dict):
    record_api_call("youtube", endpoint)

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
            premium_host_template(host, "custom_live_message"),
            creator=creator,
            url=url,
            platform="YouTube"
        )

        await send_notification(
            host,
            embed,
            custom,
            event_type="youtube_live",
            event_key=f"youtube:live:{channel_id}:{video_id}",
            source_url=url
        )

    update_live_state(
        host["guild_id"],
        "youtube",
        channel_id,
        True,
        video_id
    )



def _tiktok_live_fallback_sync(username: str):
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 15,
    }

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(
                f"https://www.tiktok.com/@{username}/live",
                download=False
            )
    except Exception:
        return None

    if not info:
        return None

    is_live = bool(
        info.get("is_live")
        or info.get("live_status") == "is_live"
    )

    if not is_live:
        return None

    return {
        "id": str(info.get("id") or username),
        "title": info.get("title") or f"@{username} LIVE",
        "url": info.get("webpage_url")
        or f"https://www.tiktok.com/@{username}/live"
    }


async def check_tiktok_live_fallback(host):
    username = host["target"].lstrip("@")
    record_api_call("tiktok", "yt-dlp-live-fallback")

    data = await asyncio.wait_for(
        asyncio.to_thread(
            _tiktok_live_fallback_sync,
            username
        ),
        timeout=30
    )

    return data


def _youtube_live_fallback_sync(channel_id: str):
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 15,
    }

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/channel/{channel_id}/live",
                download=False
            )
    except Exception:
        return None

    if not info:
        return None

    if not (
        info.get("is_live")
        or info.get("live_status") == "is_live"
    ):
        return None

    return {
        "id": str(info.get("id") or channel_id),
        "title": info.get("title") or "YouTube LIVE",
        "url": info.get("webpage_url")
        or f"https://www.youtube.com/channel/{channel_id}/live"
    }


async def check_youtube_live_fallback(host):
    record_api_call("youtube", "yt-dlp-live-fallback")

    data = await asyncio.wait_for(
        asyncio.to_thread(
            _youtube_live_fallback_sync,
            host["target"]
        ),
        timeout=30
    )

    if not data:
        return False

    previous = get_live_state(
        host["guild_id"],
        "youtube",
        host["target"]
    )

    if previous and previous["is_live"] and previous["live_key"] == data["id"]:
        return True

    embed = discord.Embed(
        title="🔴 YouTube LIVE",
        description=f"**{host['display_name'] or host['target']}** sedang live!",
        url=data["url"],
        color=discord.Color.red()
    )
    embed.add_field(
        name="Judul",
        value=data["title"][:1024],
        inline=False
    )

    await send_notification(
        host,
        embed,
        render_template(
            premium_host_template(host, "custom_live_message"),
            creator=host["display_name"] or host["target"],
            url=data["url"],
            platform="YouTube"
        ),
        event_type="youtube_live",
        event_key=f"youtube:live:{host['target']}:{data['id']}",
        source_url=data["url"]
    )

    update_live_state(
        host["guild_id"],
        "youtube",
        host["target"],
        True,
        data["id"]
    )
    return True



def _generic_live_extract_sync(url: str):
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 20,
        "noplaylist": True,
    }

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        return None

    is_live = bool(
        info.get("is_live")
        or info.get("live_status") == "is_live"
    )

    if not is_live:
        return None

    return {
        "id": str(
            info.get("id")
            or info.get("display_id")
            or url
        ),
        "title": info.get("title") or "LIVE",
        "url": info.get("webpage_url") or url,
        "thumbnail": info.get("thumbnail"),
    }


async def check_generic_live(host):
    platform = host["platform"]
    url = host_public_url(host, live=True)

    record_api_call(platform, "yt-dlp-live")

    data = await asyncio.wait_for(
        asyncio.to_thread(
            _generic_live_extract_sync,
            url
        ),
        timeout=35
    )

    previous = get_live_state(
        host["guild_id"],
        platform,
        host["target"]
    )

    if not data:
        if (
            previous
            and previous["is_live"]
            and host["notify_live_end"]
            and feature_enabled(host["guild_id"], "live_end")
        ):
            embed = discord.Embed(
                title=f"⚫ {platform_display_name(platform)} LIVE Selesai",
                description=(
                    f"**{host['display_name'] or host['target']}** "
                    "sudah selesai LIVE."
                ),
                color=discord.Color.dark_grey()
            )

            await send_notification(
                host,
                embed,
                render_template(
                    premium_host_template(host, "custom_end_message"),
                    creator=host["display_name"] or host["target"],
                    url=url,
                    platform=platform_display_name(platform)
                ),
                event_type=f"{platform}_live_end",
                event_key=(
                    f"{platform}:live_end:{host['target']}:"
                    f"{previous['live_key'] or int(time.time() // 60)}"
                ),
                source_url=url
            )

        update_live_state(
            host["guild_id"],
            platform,
            host["target"],
            False,
            None
        )
        return False

    if (
        previous
        and previous["is_live"]
        and previous["live_key"] == data["id"]
    ):
        return True

    embed = discord.Embed(
        title=f"🔴 {platform_display_name(platform)} LIVE",
        description=(
            f"**{host['display_name'] or host['target']}** sedang LIVE!"
        ),
        url=data["url"],
        color=discord.Color.red()
    )
    embed.add_field(
        name="Judul",
        value=str(data["title"])[:1024],
        inline=False
    )

    if data.get("thumbnail"):
        embed.set_thumbnail(url=data["thumbnail"])

    await send_notification(
        host,
        embed,
        render_template(
            premium_host_template(host, "custom_live_message"),
            creator=host["display_name"] or host["target"],
            url=data["url"],
            platform=platform_display_name(platform)
        ),
        event_type=f"{platform}_live",
        event_key=f"{platform}:live:{host['target']}:{data['id']}",
        source_url=data["url"]
    )

    update_live_state(
        host["guild_id"],
        platform,
        host["target"],
        True,
        data["id"]
    )
    return True


def _generic_latest_content_sync(url: str):
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "playlistend": 3,
        "socket_timeout": 20,
    }

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        return None

    entries = info.get("entries")

    if entries:
        entries = [
            entry
            for entry in entries
            if entry
        ]
        if not entries:
            return None
        item = entries[0]
    else:
        item = info

    item_id = str(
        item.get("id")
        or item.get("display_id")
        or item.get("url")
        or ""
    ).strip()

    if not item_id:
        return None

    item_url = (
        item.get("webpage_url")
        or item.get("url")
        or url
    )

    return {
        "id": item_id,
        "title": item.get("title") or item.get("description") or "Konten baru",
        "url": item_url,
        "thumbnail": item.get("thumbnail"),
    }


def get_social_content_state(host_id: int):
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM social_content_state WHERE host_id=?",
            (int(host_id),)
        ).fetchone()


def set_social_content_state(
    host_id: int,
    item_id: str,
    initialized: bool = True
):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO social_content_state(
                host_id, last_item_id, initialized, updated_at
            )
            VALUES(?,?,?,?)
            ON CONFLICT(host_id)
            DO UPDATE SET
                last_item_id=excluded.last_item_id,
                initialized=excluded.initialized,
                updated_at=excluded.updated_at
        """, (
            int(host_id),
            str(item_id),
            1 if initialized else 0,
            int(time.time())
        ))
        conn.commit()


async def check_generic_content(host):
    platform = host["platform"]
    url = host_public_url(host)

    record_api_call(platform, "yt-dlp-latest-content")

    latest = await asyncio.wait_for(
        asyncio.to_thread(
            _generic_latest_content_sync,
            url
        ),
        timeout=35
    )

    if not latest:
        return False

    state = get_social_content_state(host["id"])

    if not state or not state["initialized"]:
        set_social_content_state(
            host["id"],
            latest["id"],
            True
        )
        return True

    if state["last_item_id"] == latest["id"]:
        return True

    embed = discord.Embed(
        title=f"🆕 {platform_display_name(platform)} • Konten Baru",
        description=(
            f"**{host['display_name'] or host['target']}** "
            "mengunggah konten baru."
        ),
        url=latest["url"],
        color=discord.Color.blue()
    )
    embed.add_field(
        name="Konten",
        value=str(latest["title"])[:1024],
        inline=False
    )

    if latest.get("thumbnail"):
        embed.set_thumbnail(url=latest["thumbnail"])

    await send_notification(
        host,
        embed,
        render_template(
            premium_host_template(host, "custom_post_message"),
            creator=host["display_name"] or host["target"],
            url=latest["url"],
            platform=platform_display_name(platform)
        ),
        event_type=f"{platform}_post",
        event_key=f"{platform}:post:{host['target']}:{latest['id']}",
        source_url=latest["url"]
    )

    set_social_content_state(
        host["id"],
        latest["id"],
        True
    )
    return True


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

    record_api_call("tiktok", "TikTokLiveClient.is_live")

    try:
        live = await asyncio.wait_for(
            client.is_live(),
            timeout=25
        )
    except Exception:
        fallback = await check_tiktok_live_fallback(host)
        live = bool(fallback)

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
                premium_host_template(host, "custom_live_message"),
                creator=f"@{username}",
                url=url,
                platform="TikTok"
            )

            await send_notification(
                host,
                embed,
                custom,
                event_type="tiktok_live",
                event_key=f"tiktok:live:{username}:{int(time.time() // 60)}",
                source_url=url
            )

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
        premium_host_template(host, "custom_end_message"),
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
        premium_host_template(host, "custom_post_message"),
        creator=f"@{username}",
        url=latest["url"],
        platform="TikTok"
    )

    await send_notification(
        host,
        embed,
        custom,
        event_type="tiktok_post",
        event_key=f"tiktok:post:{username}:{latest['id']}",
        source_url=latest["url"]
    )

    update_tiktok_post_state(
        host["guild_id"],
        username,
        latest["id"]
    )




# ============================================================
# INVOICE EXPIRY / GRACE PERIOD
# ============================================================

@tasks.loop(minutes=5)
async def payment_reconciliation_loop():
    if not AUTO_ACTIVATE_VERIFIED_PAYMENTS:
        return

    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT id
            FROM premium_orders
            WHERE activated_at IS NULL
              AND amount_verified=1
              AND status IN ('amount_verified','paid')
              AND proof_url IS NOT NULL
            ORDER BY updated_at ASC
            LIMIT 25
        """).fetchall()

    for row in rows:
        try:
            await maybe_auto_activate_verified_order(
                int(row["id"]),
                actor_id=0,
                source="automatic_reconciliation"
            )
        except Exception:
            log.exception(
                "Payment reconciliation gagal order_id=%s",
                row["id"]
            )


@payment_reconciliation_loop.before_loop
async def before_payment_reconciliation_loop():
    await bot.wait_until_ready()


@tasks.loop(minutes=2)
async def payment_event_retry_loop():
    now = int(time.time())

    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT *
            FROM payment_event_dead_letter
            WHERE resolved_at IS NULL
              AND next_retry_at<=?
            ORDER BY id ASC
            LIMIT 20
        """, (now,)).fetchall()

    for row in rows:
        retry_count = int(row["retry_count"] or 0)

        if retry_count >= PAYMENT_EVENT_MAX_RETRIES:
            continue

        try:
            payload = json.loads(row["payload_json"])
            result = await process_verified_payment_event(
                payload,
                source="payment_event_retry",
                from_retry=True
            )

            if result.get("ok"):
                with closing(db()) as conn:
                    conn.execute("""
                        UPDATE payment_event_dead_letter
                        SET resolved_at=?
                        WHERE id=?
                    """, (
                        int(time.time()),
                        int(row["id"])
                    ))
                    conn.commit()
                continue

            raise RuntimeError(str(result.get("message") or "retry failed"))

        except Exception as exc:
            with closing(db()) as conn:
                conn.execute("""
                    UPDATE payment_event_dead_letter
                    SET
                        retry_count=retry_count+1,
                        next_retry_at=?,
                        error=?
                    WHERE id=?
                """, (
                    int(time.time())
                    + PAYMENT_EVENT_RETRY_SECONDS * (retry_count + 2),
                    f"{type(exc).__name__}: {exc}"[:1000],
                    int(row["id"])
                ))
                conn.commit()


@payment_event_retry_loop.before_loop
async def before_payment_event_retry_loop():
    await bot.wait_until_ready()


@tasks.loop(minutes=5)
async def invoice_expiry_loop():
    now = int(time.time())

    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT *
            FROM premium_orders
            WHERE invoice_deadline IS NOT NULL
              AND invoice_deadline<=?
              AND status IN (
                  'pending','proof_submitted','amount_mismatch'
              )
        """, (now,)).fetchall()

        for row in rows:
            conn.execute("""
                UPDATE premium_orders
                SET status='invoice_expired', updated_at=?
                WHERE id=?
            """, (
                now,
                row["id"]
            ))

        conn.commit()

    for row in rows:
        await notify_order_user(
            row,
            (
                f"⌛ Invoice Premium **#{row['id']}** kedaluwarsa.\n"
                "Silakan buat request baru melalui `/menu`."
            )
        )


@invoice_expiry_loop.before_loop
async def before_invoice_expiry():
    await bot.wait_until_ready()


# ============================================================
# PREMIUM EXPIRY
# ============================================================

async def dm_guild_owner(guild: discord.Guild, message: str):
    try:
        owner = guild.owner or await guild.fetch_member(guild.owner_id)
        await owner.send(message)
        return True
    except Exception:
        log.warning(
            "Gagal DM owner guild_id=%s owner_id=%s",
            guild.id,
            guild.owner_id
        )
        return False


@tasks.loop(hours=1)
async def premium_expiry_loop():
    now = int(time.time())
    reminder_days = (7, 3, 1)

    for guild in list(bot.guilds):
        try:
            settings = get_guild_settings(guild.id)

            if settings["plan"] != "premium":
                continue

            expires_at = settings["premium_expires_at"]

            if not expires_at:
                continue

            expires_at = int(expires_at)
            grace_until = settings["premium_grace_until"]
            remaining = expires_at - now

            if remaining <= 0:
                # Start grace period once.
                if PREMIUM_GRACE_HOURS > 0 and not grace_until:
                    grace_until = now + (PREMIUM_GRACE_HOURS * 3600)

                    with closing(db()) as conn:
                        conn.execute("""
                            UPDATE guild_settings
                            SET premium_grace_until=?
                            WHERE guild_id=?
                        """, (
                            grace_until,
                            guild.id
                        ))
                        conn.commit()

                    await dm_guild_owner(
                        guild,
                        (
                            f"⚠️ Premium server **{guild.name}** sudah melewati expiry.\n"
                            f"Grace period **{PREMIUM_GRACE_HOURS} jam** aktif sampai "
                            f"<t:{grace_until}:F>.\n"
                            "Gunakan `/menu` untuk memperpanjang."
                        )
                    )
                    continue

                if grace_until and now < int(grace_until):
                    continue

                set_plan(guild.id, "free")

                await dm_guild_owner(
                    guild,
                    (
                        f"🆓 Premium server **{guild.name}** dan grace period telah berakhir.\n"
                        "Server kembali ke paket **FREE**."
                    )
                )

                add_activity(
                    guild.id,
                    bot.user.id if bot.user else 0,
                    "Premium Expired",
                    "Premium + grace period berakhir."
                )

                with closing(db()) as conn:
                    conn.execute("""
                        UPDATE premium_orders
                        SET status='expired', updated_at=?
                        WHERE guild_id=?
                          AND status='active'
                          AND expires_at IS NOT NULL
                          AND expires_at<=?
                    """, (
                        now,
                        guild.id,
                        now
                    ))
                    conn.commit()

                continue

            # reset stale grace when renewed
            if grace_until:
                with closing(db()) as conn:
                    conn.execute("""
                        UPDATE guild_settings
                        SET premium_grace_until=NULL
                        WHERE guild_id=?
                    """, (guild.id,))
                    conn.commit()

            for days_before in reminder_days:
                threshold = days_before * 86400

                if remaining <= threshold and not reminder_already_sent(
                    guild.id,
                    expires_at,
                    days_before
                ):
                    await dm_guild_owner(
                        guild,
                        (
                            f"⏳ Premium server **{guild.name}** akan berakhir "
                            f"dalam sekitar **{days_before} hari**.\n"
                            f"Berakhir: <t:{expires_at}:F> • <t:{expires_at}:R>"
                        )
                    )

                    mark_reminder_sent(
                        guild.id,
                        expires_at,
                        days_before
                    )

        except Exception:
            log.exception(
                "Premium expiry check gagal guild_id=%s",
                guild.id
            )


@premium_expiry_loop.before_loop
async def before_premium_expiry():
    await bot.wait_until_ready()


# ============================================================
# MONITOR
# ============================================================

def host_due(host, now: int) -> bool:
    if host["cooldown_until"] and now < int(host["cooldown_until"]):
        return False

    last = int(host["last_check"] or 0)
    interval = int(host["check_interval"] or DEFAULT_CHECK_INTERVAL)

    try:
        if premium_entitlements(int(host["guild_id"]))["priority_polling"]:
            interval = max(60, int(interval * 0.75))
    except Exception:
        pass

    # Adaptive backoff for repeatedly failing hosts.
    errors = int(host["error_count"] or 0)
    if errors:
        interval = min(
            max(interval, 60) * min(4, 1 + errors // 3),
            1800
        )

    # Deterministic jitter spreads host checks across time without randomness.
    jitter = int(host["id"]) % max(1, min(30, interval // 5 or 1))
    return now - last >= interval + jitter


@tasks.loop(hours=24)
async def verification_expiry_warning_loop():
    now = int(time.time())
    warning_seconds = VERIFICATION_WARNING_DAYS * 86400

    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT *
            FROM user_verifications
            WHERE verified=1
        """).fetchall()

    for row in rows:
        user_id = int(row["user_id"])

        if is_global_owner(user_id):
            continue

        expires_at = (
            int(row["last_active_at"])
            + VERIFICATION_RETENTION_DAYS * 86400
        )

        remaining = expires_at - now

        if remaining <= 0 or remaining > warning_seconds:
            continue

        with closing(db()) as conn:
            sent = conn.execute("""
                SELECT 1
                FROM user_verification_warnings
                WHERE user_id=? AND expiry_at=? AND days_before=?
            """, (
                user_id,
                expires_at,
                VERIFICATION_WARNING_DAYS
            )).fetchone()

        if sent:
            continue

        try:
            user = bot.get_user(user_id) or await bot.fetch_user(user_id)
            await user.send(
                (
                    "⏳ **Verifikasi Hi Notifku akan kedaluwarsa.**\n"
                    f"Jika tidak ada aktivitas, data verifikasi akan dihapus "
                    f"<t:{expires_at}:R>.\n"
                    "Gunakan bot melalui DM agar masa aktif diperbarui."
                )
            )

            with closing(db()) as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO user_verification_warnings(
                        user_id, expiry_at, days_before, sent_at
                    )
                    VALUES(?,?,?,?)
                """, (
                    user_id,
                    expires_at,
                    VERIFICATION_WARNING_DAYS,
                    now
                ))
                conn.commit()

        except Exception:
            pass


@verification_expiry_warning_loop.before_loop
async def before_verification_expiry_warning_loop():
    await bot.wait_until_ready()


def verification_dashboard_embed():
    now = int(time.time())
    d7 = now - 7 * 86400
    d30 = now - VERIFICATION_RETENTION_DAYS * 86400
    warning_cutoff = now - (
        (VERIFICATION_RETENTION_DAYS - VERIFICATION_WARNING_DAYS) * 86400
    )

    with closing(db()) as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN verified=1 THEN 1 ELSE 0 END) AS verified,
                SUM(CASE WHEN verified=1 AND last_active_at>=? THEN 1 ELSE 0 END) AS active7,
                SUM(CASE WHEN verified=1 AND last_active_at>=? THEN 1 ELSE 0 END) AS active30,
                SUM(CASE WHEN verified=1 AND last_active_at<=? AND last_active_at>? THEN 1 ELSE 0 END) AS expiring
            FROM user_verifications
        """, (
            d7,
            d30,
            warning_cutoff,
            d30
        )).fetchone()

    return discord.Embed(
        title="✅ User Verification",
        description="Retensi semua user • Global Owner dikecualikan.",
        color=discord.Color.green()
    ).add_field(
        name="Ringkasan",
        value=(
            f"Verified: **{int(row['verified'] or 0)}**\n"
            f"Aktif 7 hari: **{int(row['active7'] or 0)}**\n"
            f"Aktif ≤{VERIFICATION_RETENTION_DAYS} hari: "
            f"**{int(row['active30'] or 0)}**\n"
            f"Hampir expired: **{int(row['expiring'] or 0)}**"
        ),
        inline=False
    )




@tasks.loop(hours=24)
async def verification_retention_cleanup_loop():
    removed = cleanup_stale_user_verifications()

    if removed:
        log.info(
            "User verification retention menghapus %s user tidak aktif > %s hari.",
            removed,
            VERIFICATION_RETENTION_DAYS
        )


@verification_retention_cleanup_loop.before_loop
async def before_verification_retention_cleanup_loop():
    await bot.wait_until_ready()




async def validation_alert_once(
    guild: discord.Guild,
    host,
    alert_type: str,
    detail: str
):
    key = f"{host['id']}:{alert_type}"
    now = int(time.time())

    with closing(db()) as conn:
        previous = conn.execute(
            "SELECT sent_at FROM validation_alerts WHERE alert_key=?",
            (key,)
        ).fetchone()

    if previous and now - int(previous["sent_at"]) < 12 * 3600:
        return

    await dm_guild_owner(
        guild,
        (
            f"⚠️ **Validasi Host #{host['id']}**\n"
            f"{platform_display_name(host['platform'])} • "
            f"**{host['display_name'] or host['target']}**\n"
            f"{detail}"
        )
    )

    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO validation_alerts(
                alert_key, guild_id, host_id, alert_type, sent_at
            )
            VALUES(?,?,?,?,?)
            ON CONFLICT(alert_key)
            DO UPDATE SET sent_at=excluded.sent_at
        """, (
            key,
            int(guild.id),
            int(host["id"]),
            str(alert_type),
            now
        ))
        conn.commit()


@tasks.loop(hours=6)
async def host_target_validation_loop():
    for guild in list(bot.guilds):
        try:
            for host in get_hosts(guild.id):
                channel_ids = host_delivery_channels(host)

                if not channel_ids:
                    await validation_alert_once(
                        guild,
                        host,
                        "channel_missing",
                        "❌ Tidak ada channel notifikasi yang valid."
                    )
                else:
                    invalid_channels = [
                        cid for cid in channel_ids
                        if guild.get_channel(int(cid)) is None
                    ]
                    if invalid_channels:
                        await validation_alert_once(
                            guild,
                            host,
                            "channel_deleted",
                            "❌ Channel tidak ditemukan: "
                            + ", ".join(str(x) for x in invalid_channels[:5])
                        )

                invalid_roles = [
                    rid for rid in host_mention_roles(host)
                    if guild.get_role(int(rid)) is None
                ]
                if invalid_roles:
                    await validation_alert_once(
                        guild,
                        host,
                        "role_deleted",
                        "❌ Role tidak ditemukan: "
                        + ", ".join(str(x) for x in invalid_roles[:5])
                    )

                webhook_url = (
                    str(host["webhook_url"]).strip()
                    if "webhook_url" in host.keys() and host["webhook_url"]
                    else ""
                )

                if webhook_url and http is not None and not http.closed:
                    try:
                        webhook = discord.Webhook.from_url(
                            webhook_url,
                            session=http
                        )
                        await webhook.fetch()
                    except Exception:
                        await validation_alert_once(
                            guild,
                            host,
                            "webhook_invalid",
                            "❌ Webhook tidak valid / sudah dihapus."
                        )

        except Exception:
            log.exception(
                "Host target validation gagal guild_id=%s",
                guild.id
            )


@host_target_validation_loop.before_loop
async def before_host_target_validation_loop():
    await bot.wait_until_ready()




@tasks.loop(minutes=15)
async def server_owner_health_alert_loop():
    now = int(time.time())

    for guild in list(bot.guilds):
        try:
            for host in get_hosts(guild.id):
                errors = int(host["error_count"] or 0)
                if errors < ERROR_ALERT_THRESHOLD:
                    continue

                with closing(db()) as conn:
                    previous = conn.execute("""
                        SELECT *
                        FROM owner_health_alerts
                        WHERE host_id=?
                    """, (int(host["id"]),)).fetchone()

                if (
                    previous
                    and errors <= int(previous["last_error_count"])
                    and now - int(previous["last_sent_at"]) < 6 * 3600
                ):
                    continue

                await dm_guild_owner(
                    guild,
                    (
                        f"🚨 Host bermasalah: **{host['display_name'] or host['target']}**\n"
                        f"Platform: **{platform_display_name(host['platform'])}**\n"
                        f"Error berturut: **{errors}**\n"
                        f"Terakhir: `{str(host['last_error'] or '-')[:500]}`\n\n"
                        "Buka `/menu` → server → **Kelola Host**."
                    )
                )

                with closing(db()) as conn:
                    conn.execute("""
                        INSERT INTO owner_health_alerts(
                            host_id, last_error_count, last_sent_at
                        )
                        VALUES(?,?,?)
                        ON CONFLICT(host_id)
                        DO UPDATE SET
                            last_error_count=excluded.last_error_count,
                            last_sent_at=excluded.last_sent_at
                    """, (
                        int(host["id"]),
                        errors,
                        now
                    ))
                    conn.commit()

        except Exception:
            log.exception(
                "Server owner health alert gagal guild_id=%s",
                guild.id
            )


@server_owner_health_alert_loop.before_loop
async def before_server_owner_health_alert_loop():
    await bot.wait_until_ready()




def platform_feature_keys(platform: str) -> list[str]:
    return {
        "youtube": ["youtube_live"],
        "tiktok": ["tiktok_live", "tiktok_post"],
        "twitch": ["twitch_live"],
        "kick": ["kick_live"],
        "instagram": ["instagram_post"],
        "facebook": ["facebook_post"],
    }.get(str(platform).lower().strip(), [])


def host_auto_recovery_allowed(host) -> tuple[bool, str]:
    guild_id = int(host["guild_id"])
    settings = get_guild_settings(guild_id)

    if effective_access_state(guild_id) not in {"allowed", "whitelist"}:
        return False, "Akses server sedang dibatasi."

    if bool(settings["maintenance_mode"]):
        return False, "Server sedang maintenance."

    keys = platform_feature_keys(str(host["platform"]))
    if keys and not all(feature_enabled(guild_id, key) for key in keys):
        return False, "Platform sedang maintenance."

    if not premium_access_effective(guild_id):
        active_other = sum(
            1 for item in get_hosts(guild_id)
            if int(item["id"]) != int(host["id"]) and bool(item["enabled"])
        )
        if active_other >= FREE_HOST_LIMIT:
            return False, "Limit host FREE sudah penuh."

    return True, "OK"


@tasks.loop(minutes=30)
async def host_auto_recovery_loop():
    now = int(time.time())
    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT *
            FROM host_auto_recovery
            WHERE last_retry_at IS NULL OR last_retry_at<=?
            ORDER BY auto_paused_at ASC
            LIMIT 25
        """, (now - 1800,)).fetchall()

    for row in rows:
        host = get_host(int(row["host_id"]))
        if not host:
            clear_host_auto_recovery(int(row["host_id"]))
            continue

        try:
            allowed, reason = host_auto_recovery_allowed(host)
            if not allowed:
                with closing(db()) as conn:
                    conn.execute("""
                        UPDATE host_auto_recovery
                        SET last_retry_at=?, retry_count=retry_count+1
                        WHERE host_id=?
                    """, (now, int(row["host_id"])))
                    conn.commit()
                log.info(
                    "Auto recovery ditahan host_id=%s: %s",
                    host["id"], reason
                )
                continue

            await host_manager_recheck(host)

            refreshed = get_host(int(host["id"])) or host
            allowed, reason = host_auto_recovery_allowed(refreshed)
            if not allowed:
                log.info(
                    "Auto recovery batal host_id=%s setelah recheck: %s",
                    host["id"], reason
                )
                continue

            set_host_health(int(host["id"]), success=True)

            with closing(db()) as conn:
                conn.execute(
                    "UPDATE hosts SET enabled=1 WHERE id=?",
                    (int(host["id"]),)
                )
                conn.commit()

            clear_host_auto_recovery(int(host["id"]))
            guild = bot.get_guild(int(host["guild_id"]))
            if guild:
                await dm_guild_owner(
                    guild,
                    f"✅ Host **{host['display_name'] or host['target']}** pulih otomatis."
                )

        except Exception:
            with closing(db()) as conn:
                conn.execute("""
                    UPDATE host_auto_recovery
                    SET last_retry_at=?, retry_count=retry_count+1
                    WHERE host_id=?
                """, (now, int(row["host_id"])))
                conn.commit()


@host_auto_recovery_loop.before_loop
async def before_host_auto_recovery_loop():
    await bot.wait_until_ready()


@tasks.loop(minutes=10)
async def platform_outage_detection_loop():
    now = int(time.time())

    for platform_name in sorted(SUPPORTED_PLATFORMS):
        total = 0
        errors = 0

        for guild in bot.guilds:
            try:
                for host in get_hosts(guild.id):
                    if str(host["platform"]) != platform_name:
                        continue
                    total += 1
                    if (
                        host["last_error"]
                        and host["last_check"]
                        and now - int(host["last_check"]) <= 3600
                    ):
                        errors += 1
            except Exception:
                pass

        outage = total >= 3 and errors >= 3 and (errors / max(1, total)) >= 0.5
        state = "outage" if outage else "normal"

        with closing(db()) as conn:
            previous = conn.execute(
                "SELECT state FROM platform_incidents WHERE platform=?",
                (platform_name,)
            ).fetchone()

            conn.execute("""
                INSERT INTO platform_incidents(
                    platform, state, error_hosts, total_hosts, updated_at
                )
                VALUES(?,?,?,?,?)
                ON CONFLICT(platform)
                DO UPDATE SET
                    state=excluded.state,
                    error_hosts=excluded.error_hosts,
                    total_hosts=excluded.total_hosts,
                    updated_at=excluded.updated_at
            """, (
                platform_name,
                state,
                errors,
                total,
                now
            ))
            conn.commit()

        if outage:
            record_incident(
                f"platform:{platform_name}",
                "platform",
                f"{platform_display_name(platform_name)} outage",
                f"Host error {errors}/{total}."
            )

        if not outage and previous and previous["state"] == "outage":
            with closing(db()) as conn:
                incident = conn.execute("""
                    SELECT id FROM incident_history
                    WHERE incident_key=? AND status IN ('open','investigating')
                    ORDER BY id DESC LIMIT 1
                """, (f"platform:{platform_name}",)).fetchone()
            if incident:
                update_incident_status(int(incident["id"]), "resolved", 0)

        if outage and (not previous or previous["state"] != "outage"):
            for owner_id in primary_owner_ids():
                try:
                    user = bot.get_user(owner_id) or await bot.fetch_user(owner_id)
                    await user.send(
                        f"🌐 **Platform Incident** • {platform_display_name(platform_name)}\n"
                        f"Host error: **{errors}/{total}**. Kemungkinan gangguan provider."
                    )
                except Exception:
                    pass


@platform_outage_detection_loop.before_loop
async def before_platform_outage_detection_loop():
    await bot.wait_until_ready()




@tasks.loop(hours=6)
async def user_verification_reconcile_loop():
    if not REQUIRED_GUILD_ID:
        return

    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT user_id
            FROM user_verifications
            WHERE verified=1
        """).fetchall()

    for row in rows:
        user_id = int(row["user_id"])

        if is_global_owner(user_id):
            continue

        try:
            still_member = await is_user_in_required_guild(
                user_id
            )

            if not still_member:
                set_user_verification(
                    user_id,
                    False,
                    source="membership_reconcile",
                    reason="Membership Server Owner/Support tidak lagi terdeteksi.",
                    mark_active=False
                )

        except Exception:
            log.exception(
                "User verification reconcile gagal user_id=%s",
                user_id
            )


@user_verification_reconcile_loop.before_loop
async def before_user_verification_reconcile_loop():
    await bot.wait_until_ready()




@tasks.loop(hours=1)
async def owner_verification_reconcile_loop():
    """
    Reconcile all server-owner verification states.

    This repairs missed join/leave events after deploys, gateway reconnects,
    or temporary Discord API failures.
    """
    if not REQUIRED_GUILD_ID:
        return

    changed = 0

    for guild in list(bot.guilds):
        try:
            previous = get_guild_owner_verification(
                guild.id
            )

            # Missing guild-owner records must be repaired here.
            previous_verified = (
                bool(previous["verified"])
                if previous
                else None
            )
            previous_owner = (
                int(previous["owner_id"])
                if previous
                else None
            )

            current_verified = await refresh_guild_owner_verification(
                guild,
                source="hourly_reconcile"
            )

            if (
                previous_verified is None
                or previous_verified != current_verified
                or previous_owner != int(guild.owner_id)
            ):
                changed += 1
                log.info(
                    "Verification reconcile guild=%s owner=%s verified=%s",
                    guild.id,
                    guild.owner_id,
                    current_verified
                )

        except Exception:
            log.exception(
                "Verification reconcile gagal guild_id=%s",
                guild.id
            )

    if changed:
        log.info(
            "Verification reconcile memperbarui %s server.",
            changed
        )


@owner_verification_reconcile_loop.before_loop
async def before_owner_verification_reconcile_loop():
    await bot.wait_until_ready()


async def resend_pending_request_to_owner(
    request_kind: str,
    row
) -> bool:
    guild = bot.get_guild(int(row["guild_id"]))
    if not guild:
        return False

    try:
        owner = (
            guild.owner
            or bot.get_user(guild.owner_id)
            or await bot.fetch_user(guild.owner_id)
        )

        if request_kind == "manager":
            await owner.send(
                embed=server_host_access_request_embed(
                    int(row["id"])
                ),
                view=ServerOwnerAccessRequestView(
                    int(row["id"]),
                    int(row["user_id"]),
                    int(row["guild_id"])
                )
            )
        else:
            await owner.send(
                embed=host_creation_request_embed(
                    int(row["id"])
                ),
                view=ServerOwnerHostCreationApprovalView(
                    int(row["id"]),
                    int(row["guild_id"]),
                    int(row["requester_id"])
                )
            )

        return True

    except Exception:
        return False


async def recover_pending_request_views():
    """
    Re-send fresh approval buttons after restart/redeploy.
    Limited to once per request per 6 hours.
    """
    now = int(time.time())

    with closing(db()) as conn:
        access_rows = conn.execute("""
            SELECT *
            FROM server_host_access_requests
            WHERE status='pending'
            ORDER BY id DESC
        """).fetchall()

        host_rows = conn.execute("""
            SELECT *
            FROM host_creation_requests
            WHERE status='pending'
            ORDER BY id DESC
        """).fetchall()

    for kind, rows in (
        ("manager", access_rows),
        ("host", host_rows)
    ):
        for row in rows:
            with closing(db()) as conn:
                previous = conn.execute("""
                    SELECT sent_at
                    FROM request_recovery_log
                    WHERE request_kind=? AND request_id=?
                """, (
                    kind,
                    int(row["id"])
                )).fetchone()

            if (
                previous
                and now - int(previous["sent_at"]) < 6 * 3600
            ):
                continue

            if await resend_pending_request_to_owner(kind, row):
                with closing(db()) as conn:
                    conn.execute("""
                        INSERT INTO request_recovery_log(
                            request_kind,
                            request_id,
                            sent_at
                        )
                        VALUES(?,?,?)
                        ON CONFLICT(request_kind, request_id)
                        DO UPDATE SET sent_at=excluded.sent_at
                    """, (
                        kind,
                        int(row["id"]),
                        now
                    ))
                    conn.commit()


@tasks.loop(hours=1)
async def pending_request_recovery_loop():
    try:
        await recover_pending_request_views()
    except Exception:
        log.exception("Periodic pending request recovery gagal")


@pending_request_recovery_loop.before_loop
async def before_pending_request_recovery_loop():
    await bot.wait_until_ready()


@tasks.loop(hours=6)
async def pending_request_reminder_loop():
    now = int(time.time())

    with closing(db()) as conn:
        access_rows = conn.execute("""
            SELECT *
            FROM server_host_access_requests
            WHERE status='pending'
        """).fetchall()

        host_rows = conn.execute("""
            SELECT *
            FROM host_creation_requests
            WHERE status='pending'
        """).fetchall()

    for kind, rows in (
        ("manager", access_rows),
        ("host", host_rows)
    ):
        for row in rows:
            age_hours = max(
                0,
                (now - int(row["created_at"])) // 3600
            )

            milestone = (
                48 if age_hours >= 48
                else 24 if age_hours >= 24
                else 0
            )
            if not milestone:
                continue

            with closing(db()) as conn:
                sent = conn.execute("""
                    SELECT 1
                    FROM request_reminders
                    WHERE request_kind=?
                      AND request_id=?
                      AND milestone_hours=?
                """, (
                    kind,
                    int(row["id"]),
                    milestone
                )).fetchone()

            if sent:
                continue

            if await resend_pending_request_to_owner(kind, row):
                with closing(db()) as conn:
                    conn.execute("""
                        INSERT OR IGNORE INTO request_reminders(
                            request_kind,
                            request_id,
                            milestone_hours,
                            sent_at
                        )
                        VALUES(?,?,?,?)
                    """, (
                        kind,
                        int(row["id"]),
                        milestone,
                        now
                    ))
                    conn.commit()


@pending_request_reminder_loop.before_loop
async def before_pending_request_reminder_loop():
    await bot.wait_until_ready()




@tasks.loop(hours=12)
async def host_manager_expiry_warning_loop():
    now = int(time.time())
    h3 = now + 3 * 86400

    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT hm.*, h.platform, h.target, h.display_name
            FROM host_managers hm
            JOIN hosts h ON h.id=hm.host_id
            WHERE hm.expires_at IS NOT NULL
              AND hm.expires_at>?
              AND hm.expires_at<=?
        """, (
            now,
            h3
        )).fetchall()

    for row in rows:
        warning_key = f"expiry_h3:{int(row['expires_at'])}"

        with closing(db()) as conn:
            sent = conn.execute("""
                SELECT 1
                FROM host_manager_warnings
                WHERE host_id=? AND user_id=? AND warning_key=?
            """, (
                int(row["host_id"]),
                int(row["user_id"]),
                warning_key
            )).fetchone()

        if sent:
            continue

        try:
            user = bot.get_user(int(row["user_id"])) or await bot.fetch_user(
                int(row["user_id"])
            )
            await user.send(
                embed=discord.Embed(
                    title="⏳ Akses Host Akan Berakhir",
                    description=(
                        f"Host: **{platform_display_name(row['platform'])} • "
                        f"{row['display_name'] or row['target']}**\\n"
                        f"Berakhir: <t:{int(row['expires_at'])}:F> "
                        f"(<t:{int(row['expires_at'])}:R>)"
                    ),
                    color=discord.Color.orange()
                )
            )

            with closing(db()) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO host_manager_warnings(
                        host_id, user_id, warning_key, sent_at
                    )
                    VALUES(?,?,?,?)
                """, (
                    int(row["host_id"]),
                    int(row["user_id"]),
                    warning_key,
                    int(time.time())
                ))
                conn.commit()

        except Exception:
            log.exception(
                "Gagal kirim warning expiry Host Manager user_id=%s host_id=%s",
                row["user_id"],
                row["host_id"]
            )


@host_manager_expiry_warning_loop.before_loop
async def before_host_manager_expiry_warning_loop():
    await bot.wait_until_ready()


def platform_circuit_open(platform: str) -> bool:
    with closing(db()) as conn:
        row = conn.execute("""
            SELECT state, updated_at
            FROM platform_incidents
            WHERE platform=?
        """, (str(platform),)).fetchone()

    if not row or row["state"] != "outage":
        return False

    hold_seconds = runtime_tuning_int(
        "circuit_breaker_minutes",
        10
    ) * 60

    # Let probes through after the hold period so recovery can be detected.
    return int(time.time()) - int(row["updated_at"] or 0) < hold_seconds


@tasks.loop(seconds=BASE_MONITOR_TICK)
async def monitor_loop():
    if SAFE_MODE:
        return

    if runtime_setting_enabled("monitor_paused") or runtime_setting_enabled("maintenance_all"):
        return

    now = int(time.time())
    due_hosts = [
        host for host in get_enabled_hosts()
        if host_due(host, now)
        and host_schedule_allowed(host, now)
    ]

    runtime_metrics["checker_runs"] += len(due_hosts)

    semaphore = asyncio.Semaphore(
        runtime_tuning_int("monitor_concurrency", MONITOR_CONCURRENCY)
    )

    async def run_host(host):
        async with semaphore:
            guild = bot.get_guild(host["guild_id"])

            if guild is None:
                return

            if platform_circuit_open(str(host["platform"])):
                log.info(
                    "Circuit breaker aktif platform=%s host_id=%s",
                    host["platform"],
                    host["id"]
                )
                return

            if not guild_access_allowed(guild.id):
                set_host_health(
                    host["id"],
                    "Server diblacklist oleh Global Owner."
                )
                return

            if REQUIRED_GUILD_ID and not await guild_owner_verified(guild):
                set_host_health(
                    host["id"],
                    "Owner server belum join Discord Owner/Support."
                )
                return

            try:
                if host["platform"] == "youtube":
                    if feature_enabled(guild.id, "youtube_live"):
                        try:
                            await check_youtube_live(host)
                        except Exception:
                            fallback_ok = await check_youtube_live_fallback(host)
                            if not fallback_ok:
                                raise
                    set_host_health(host["id"], success=True)

                elif host["platform"] in {"twitch", "kick"}:
                    feature_name = f"{host['platform']}_live"

                    if feature_enabled(guild.id, feature_name):
                        await check_generic_live(host)

                    set_host_health(
                        host["id"],
                        success=True
                    )

                elif host["platform"] in {"instagram", "facebook"}:
                    feature_name = f"{host['platform']}_post"

                    if feature_enabled(guild.id, feature_name):
                        await check_generic_content(host)

                    set_host_health(
                        host["id"],
                        success=True
                    )

                elif host["platform"] == "tiktok":
                    errors = []

                    jobs = []
                    labels = []

                    if feature_enabled(guild.id, "tiktok_live"):
                        jobs.append(check_tiktok_live(host))
                        labels.append("LIVE")

                    if feature_enabled(guild.id, "tiktok_post"):
                        jobs.append(check_tiktok_post(host))
                        labels.append("POST")

                    results = await asyncio.gather(
                        *jobs,
                        return_exceptions=True
                    )

                    for label, result in zip(labels, results):
                        if isinstance(result, Exception):
                            errors.append(f"{label}: {result}")

                    if errors:
                        set_host_health(
                            host["id"],
                            " | ".join(errors)
                        )
                        refreshed = get_host(host["id"])
                        if refreshed:
                            await send_host_error_alert(refreshed)
                    else:
                        set_host_health(
                            host["id"],
                            success=True
                        )

            except Exception as exc:
                runtime_metrics["checker_errors"] += 1
                set_host_health(
                    host["id"],
                    str(exc)
                )
                log.exception(
                    "Checker gagal host_id=%s",
                    host["id"]
                )

                refreshed = get_host(host["id"])
                if refreshed:
                    await send_host_error_alert(refreshed)

    if due_hosts:
        await asyncio.gather(
            *(run_host(host) for host in due_hosts),
            return_exceptions=True
        )


@monitor_loop.before_loop
async def before_monitor():
    await bot.wait_until_ready()




@tasks.loop(minutes=1)
async def pending_notification_loop():
    now = int(time.time())

    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT *
            FROM pending_notifications
            WHERE release_after<=?
            ORDER BY id ASC
            LIMIT 50
        """, (now,)).fetchall()

    for row in rows:
        host = get_host(int(row["host_id"]))

        if not host:
            move_notification_to_dead_letter(
                row,
                "Host tidak ditemukan."
            )
            continue

        if not host["enabled"]:
            # Keep disabled-host deliveries visible instead of silently deleting.
            move_notification_to_dead_letter(
                row,
                "Host sedang pause/nonaktif."
            )
            continue

        try:
            embed = discord.Embed.from_dict(
                json.loads(row["embed_json"])
            )

            ok = await _deliver_notification_now(
                host,
                embed,
                row["content"],
                event_type=row["event_type"] or "queued",
                event_key=row["event_key"],
                source_url=row["source_url"]
            )

            if ok:
                with closing(db()) as conn:
                    conn.execute(
                        "DELETE FROM pending_notifications WHERE id=?",
                        (int(row["id"]),)
                    )
                    conn.commit()
                continue

            retry_count = int(row["retry_count"] or 0) + 1
            max_retries = int(
                row["max_retries"] or runtime_tuning_int(
                    "notification_max_retries",
                    NOTIFICATION_MAX_RETRIES
                )
            )

            if retry_count >= max_retries:
                move_notification_to_dead_letter(
                    row,
                    f"Gagal setelah {retry_count} retry."
                )
                continue

            with closing(db()) as conn:
                conn.execute("""
                    UPDATE pending_notifications
                    SET retry_count=?,
                        release_after=?,
                        last_error=?
                    WHERE id=?
                """, (
                    retry_count,
                    now + NOTIFICATION_RETRY_SECONDS * (retry_count + 1),
                    "Delivery retry gagal.",
                    int(row["id"])
                ))
                conn.commit()

        except Exception as exc:
            retry_count = int(row["retry_count"] or 0) + 1
            max_retries = int(
                row["max_retries"] or runtime_tuning_int(
                    "notification_max_retries",
                    NOTIFICATION_MAX_RETRIES
                )
            )

            if retry_count >= max_retries:
                move_notification_to_dead_letter(
                    row,
                    f"{type(exc).__name__}: {exc}"
                )
            else:
                with closing(db()) as conn:
                    conn.execute("""
                        UPDATE pending_notifications
                        SET retry_count=?,
                            release_after=?,
                            last_error=?
                        WHERE id=?
                    """, (
                        retry_count,
                        now + NOTIFICATION_RETRY_SECONDS * (retry_count + 1),
                        f"{type(exc).__name__}: {exc}"[:1000],
                        int(row["id"])
                    ))
                    conn.commit()


@pending_notification_loop.before_loop
async def before_pending_notification_loop():
    await bot.wait_until_ready()


@tasks.loop(minutes=10)
async def event_cleanup_loop():
    cutoff = int(time.time()) - EVENT_RETENTION_DAYS * 86400

    with closing(db()) as conn:
        conn.execute(
            "DELETE FROM notification_events WHERE created_at<?",
            (cutoff,)
        )
        conn.execute(
            "DELETE FROM notification_history WHERE created_at<?",
            (cutoff,)
        )
        conn.execute(
            "DELETE FROM api_usage WHERE day<?",
            (
                datetime.fromtimestamp(
                    cutoff,
                    tz=timezone.utc
                ).strftime("%Y-%m-%d"),
            )
        )
        conn.commit()


@event_cleanup_loop.before_loop
async def before_event_cleanup_loop():
    await bot.wait_until_ready()


@tasks.loop(seconds=30)
async def loop_lag_metrics():
    start = time.perf_counter()
    await asyncio.sleep(0)
    runtime_metrics["last_loop_lag_ms"] = round(
        (time.perf_counter() - start) * 1000,
        2
    )


@loop_lag_metrics.before_loop
async def before_loop_lag_metrics():
    await bot.wait_until_ready()


# ============================================================
# AUTOMATIC BACKUP
# ============================================================

def create_full_backup_payload():
    return {
        "version": 5,
        "created_at": int(time.time()),
        "guilds": [
            export_guild_backup(guild.id)
            for guild in bot.guilds
        ],
    }


def prune_auto_backups():
    try:
        folder = Path(AUTO_BACKUP_DIR)
        files = sorted(
            folder.glob("hi-notifku-auto-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        for old in files[AUTO_BACKUP_KEEP:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        log.exception("Gagal membersihkan backup lama")



async def send_auto_backup_to_primary_owners(
    payload: dict,
    ts: int
) -> dict:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2
    ).encode("utf-8")

    sent = 0
    failed = 0

    for owner_id in primary_owner_ids():
        try:
            owner = bot.get_user(owner_id)

            if owner is None:
                owner = await bot.fetch_user(owner_id)

            await owner.send(
                content=(
                    "🗄️ **Auto Backup Hi Notifku**\n"
                    f"Waktu: <t:{ts}:F>\n"
                    f"Server: **{len(payload.get('guilds', []))}**\n"
                    "Simpan file ini di tempat aman."
                ),
                file=discord.File(
                    io.BytesIO(raw),
                    filename=f"hi-notifku-auto-{ts}.json"
                )
            )

            sent += 1
            log.info(
                "Auto backup berhasil dikirim ke primary owner_id=%s",
                owner_id
            )

        except Exception as exc:
            failed += 1
            log.warning(
                "Auto backup gagal dikirim ke primary owner_id=%s: %s: %s",
                owner_id,
                type(exc).__name__,
                exc
            )

    return {
        "sent": sent,
        "failed": failed
    }



def last_successful_auto_backup_at() -> Optional[int]:
    """
    Return the newest successful automatic-backup timestamp.

    Uses both SQLite history and a marker/file timestamp from AUTO_BACKUP_DIR,
    so a bot restart/redeploy does not reset the 48-hour schedule.
    """
    latest = 0

    try:
        with closing(db()) as conn:
            row = conn.execute("""
                SELECT MAX(created_at) AS last_at
                FROM backup_log
                WHERE ok=1
                  AND path LIKE ?
            """, ("%hi-notifku-auto-%",)).fetchone()

        if row and row["last_at"]:
            latest = max(latest, int(row["last_at"]))
    except Exception:
        log.exception("Gagal membaca waktu auto backup terakhir dari database")

    try:
        folder = Path(AUTO_BACKUP_DIR)
        marker = folder / ".last_auto_backup"

        if marker.exists():
            raw = marker.read_text(encoding="utf-8").strip()
            if raw.isdigit():
                latest = max(latest, int(raw))

        if folder.exists():
            backups = list(folder.glob("hi-notifku-auto-*.json"))
            if backups:
                latest = max(
                    latest,
                    int(max(p.stat().st_mtime for p in backups))
                )
    except Exception:
        log.exception("Gagal membaca waktu auto backup terakhir dari storage")

    return latest or None


def auto_backup_due(
    now: Optional[int] = None
) -> tuple[bool, Optional[int]]:
    now = int(now or time.time())
    last_at = last_successful_auto_backup_at()

    if last_at is None:
        return True, None

    due_at = int(last_at) + int(AUTO_BACKUP_HOURS * 3600)
    return now >= due_at, due_at


def mark_auto_backup_completed(ts: int):
    try:
        folder = Path(AUTO_BACKUP_DIR)
        folder.mkdir(parents=True, exist_ok=True)

        marker = folder / ".last_auto_backup"
        marker.write_text(str(int(ts)), encoding="utf-8")
    except Exception:
        log.exception("Gagal menyimpan marker jadwal auto backup")


@tasks.loop(hours=1)
async def auto_backup_loop():
    try:
        now = int(time.time())
        due, due_at = auto_backup_due(now)

        if not due:
            log.info(
                "Auto backup belum jatuh tempo. Berikutnya sekitar %s",
                due_at
            )
            return

        folder = Path(AUTO_BACKUP_DIR)
        folder.mkdir(parents=True, exist_ok=True)

        payload = create_full_backup_payload()
        ts = int(time.time())
        path = folder / f"hi-notifku-auto-{ts}.json"

        backup_bytes = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2
        ).encode("utf-8")

        path.write_bytes(backup_bytes)

        with closing(db()) as conn:
            conn.execute("""
                INSERT INTO backup_log(path, created_at, guild_count, ok, error)
                VALUES(?,?,?,?,NULL)
            """, (
                str(path),
                ts,
                len(payload["guilds"]),
                1
            ))
            conn.commit()

        prune_auto_backups()
        mark_auto_backup_completed(ts)
        log.info(
            "Auto backup dibuat: %s • backup berikutnya sekitar %s jam lagi",
            path,
            AUTO_BACKUP_HOURS
        )

        dm_result = await send_auto_backup_to_primary_owners(
            payload,
            ts
        )

        log.info(
            "Auto backup DM owner: sent=%s failed=%s",
            dm_result["sent"],
            dm_result["failed"]
        )

        if BACKUP_CHANNEL_ID:
            channel = bot.get_channel(BACKUP_CHANNEL_ID)

            if channel and isinstance(
                channel,
                (discord.TextChannel, discord.Thread)
            ):
                try:
                    await channel.send(
                        content=(
                            f"🗄️ Auto backup Hi Notifku • "
                            f"<t:{ts}:F> • {len(payload['guilds'])} server"
                        ),
                        file=discord.File(
                            io.BytesIO(backup_bytes),
                            filename=f"hi-notifku-auto-{ts}.json"
                        )
                    )
                except Exception:
                    log.exception("Gagal kirim backup ke channel Discord")

    except Exception as exc:
        log.exception("Auto backup gagal")
        try:
            with closing(db()) as conn:
                conn.execute("""
                    INSERT INTO backup_log(path, created_at, guild_count, ok, error)
                    VALUES(?,?,?,?,?)
                """, (
                    AUTO_BACKUP_DIR,
                    int(time.time()),
                    len(bot.guilds),
                    0,
                    str(exc)[:1000]
                ))
                conn.commit()
        except Exception:
            pass


@auto_backup_loop.before_loop
async def before_auto_backup():
    await bot.wait_until_ready()

    last_at = last_successful_auto_backup_at()
    if last_at:
        due_at = int(last_at) + int(AUTO_BACKUP_HOURS * 3600)
        log.info(
            "Auto backup schedule dipulihkan. Last=%s next_due=%s",
            last_at,
            due_at
        )
    else:
        log.info(
            "Belum ada riwayat auto backup. Backup pertama akan dibuat saat loop berjalan."
        )


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

    set_guild_notifier_settings(
        target_guild_id,
        timezone_name=settings.get("timezone") or "Asia/Jakarta",
        language=settings.get("language") or "id",
        maintenance_mode=bool(settings.get("maintenance_mode", 0))
    )

    if settings.get("feature_flags"):
        with closing(db()) as conn:
            conn.execute(
                "UPDATE guild_settings SET feature_flags=? WHERE guild_id=?",
                (settings.get("feature_flags"), target_guild_id)
            )
            conn.commit()

    restored = 0

    for raw in hosts:
        if raw.get("platform") not in SUPPORTED_PLATFORMS:
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
                        enabled=?,
                        extra_channel_ids=?,
                        extra_role_ids=?,
                        schedule_days=?,
                        quiet_start=?,
                        quiet_end=?,
                        timezone=?,
                        language=?,
                        webhook_url=?,
                        mention_everyone=?,
                        embed_title=?,
                        embed_footer=?,
                        embed_color=?,
                        auto_pause_threshold=?
                    WHERE id=?
                """, (
                    raw.get("custom_live_message"),
                    raw.get("custom_post_message"),
                    raw.get("custom_end_message"),
                    1 if raw.get("enabled", 1) else 0,
                    raw.get("extra_channel_ids"),
                    raw.get("extra_role_ids"),
                    raw.get("schedule_days") or "0,1,2,3,4,5,6",
                    raw.get("quiet_start"),
                    raw.get("quiet_end"),
                    raw.get("timezone"),
                    raw.get("language"),
                    raw.get("webhook_url"),
                    1 if raw.get("mention_everyone") else 0,
                    raw.get("embed_title"),
                    raw.get("embed_footer"),
                    raw.get("embed_color"),
                    raw.get("auto_pause_threshold"),
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

def global_access_stats() -> dict:
    server_owner_ids = {
        int(guild.owner_id)
        for guild in bot.guilds
        if guild.owner_id
    }

    now = int(time.time())

    with closing(db()) as conn:
        host_manager_users = conn.execute("""
            SELECT COUNT(DISTINCT user_id) AS total
            FROM host_managers
            WHERE expires_at IS NULL OR expires_at>?
        """, (now,)).fetchone()

        server_manager_users = conn.execute("""
            SELECT COUNT(DISTINCT user_id) AS total
            FROM server_host_managers
            WHERE enabled=1
              AND (expires_at IS NULL OR expires_at>?)
        """, (now,)).fetchone()

        pending_access = conn.execute("""
            SELECT COUNT(*) AS total
            FROM server_host_access_requests
            WHERE status='pending'
        """).fetchone()

        pending_hosts = conn.execute("""
            SELECT COUNT(*) AS total
            FROM host_creation_requests
            WHERE status='pending'
        """).fetchone()

        blacklist = conn.execute("""
            SELECT COUNT(*) AS total
            FROM user_blacklist
        """).fetchone()

    return {
        "global_owners": len(OWNER_IDS | db_owner_ids()),
        "primary_owners": len(OWNER_IDS),
        "server_owners": len(server_owner_ids),
        "host_managers": int(host_manager_users["total"] or 0),
        "server_host_managers": int(server_manager_users["total"] or 0),
        "pending_access": int(pending_access["total"] or 0),
        "pending_hosts": int(pending_hosts["total"] or 0),
        "blacklisted": int(blacklist["total"] or 0),
    }


def global_owner_access_embed(viewer_id: int):
    stats = global_access_stats()
    role = owner_role(viewer_id)

    embed = discord.Embed(
        title="🛡️ Security & Access • Global Owner",
        description=(
            "Pusat kontrol akses bot. **Pemilik Server** dan **Host Manager** "
            "tetap berada di `/menu` dan tidak dapat membuka panel ini."
        ),
        color=discord.Color.dark_blue()
    )
    embed.add_field(
        name="Akun Global",
        value=(
            f"Primary Owner: **{stats['primary_owners']}**\n"
            f"Global Owner total: **{stats['global_owners']}**\n"
            f"Role kamu: **{role}**"
        ),
        inline=True
    )
    embed.add_field(
        name="Akun Non-Global",
        value=(
            f"Pemilik Server: **{stats['server_owners']}**\n"
            f"Host Manager: **{stats['host_managers']}**\n"
            f"Manager tingkat server: **{stats['server_host_managers']}**"
        ),
        inline=True
    )
    embed.add_field(
        name="Request Pending",
        value=(
            f"Akses Manager: **{stats['pending_access']}**\n"
            f"Host Baru: **{stats['pending_hosts']}**"
        ),
        inline=True
    )
    embed.add_field(
        name="Batas Akses",
        value=(
            "🛡️ **Global Owner Bot** → `/owner`, lintas server sesuai role owner.\n"
            "👑 **Pemilik Server** → `/menu`, hanya server miliknya.\n"
            "🎙️ **Host Manager** → `/menu`, hanya server/host yang disetujui.\n"
            "✅ Approval Host Manager/host baru tetap milik **Pemilik Server**."
        ),
        inline=False
    )
    embed.add_field(
        name="Blacklist",
        value=f"User dibatasi: **{stats['blacklisted']}**",
        inline=True
    )
    embed.set_footer(
        text="Global Owner Bot • panel terisolasi dari /menu"
    )
    return embed


def global_request_audit_embed():
    stats = global_access_stats()

    with closing(db()) as conn:
        access_rows = conn.execute("""
            SELECT *
            FROM server_host_access_requests
            WHERE status='pending'
            ORDER BY id DESC
            LIMIT 10
        """).fetchall()

        host_rows = conn.execute("""
            SELECT *
            FROM host_creation_requests
            WHERE status='pending'
            ORDER BY id DESC
            LIMIT 10
        """).fetchall()

    lines = []

    for row in access_rows:
        guild = bot.get_guild(int(row["guild_id"]))
        lines.append(
            f"🎙️ **Akses #{row['id']}** • "
            f"{guild.name if guild else row['guild_id']} • "
            f"<@{row['user_id']}>"
        )

    for row in host_rows:
        guild = bot.get_guild(int(row["guild_id"]))
        lines.append(
            f"➕ **Host #{row['id']}** • "
            f"{guild.name if guild else row['guild_id']} • "
            f"`{row['platform']}:{row['target']}`"
        )

    embed = discord.Embed(
        title="📨 Audit Request Global",
        description=(
            "\n".join(lines)
            if lines
            else "✅ Tidak ada request server yang pending."
        ),
        color=discord.Color.orange()
    )
    embed.add_field(
        name="Total",
        value=(
            f"Akses Manager **{stats['pending_access']}** • "
            f"Host Baru **{stats['pending_hosts']}**"
        ),
        inline=False
    )
    embed.add_field(
        name="Mode",
        value=(
            "👁️ **Read-only audit.** Global Owner dapat memantau, tetapi "
            "persetujuan tetap wajib dilakukan oleh **Pemilik Server**."
        ),
        inline=False
    )
    return embed


def owner_backup_status_embed():
    last_at = last_successful_auto_backup_at()
    due = None

    if last_at:
        due = int(last_at) + int(AUTO_BACKUP_HOURS * 3600)

    embed = discord.Embed(
        title="🗄️ Backup Status",
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="Interval",
        value=f"**{AUTO_BACKUP_HOURS} jam**",
        inline=True
    )
    embed.add_field(
        name="Backup Terakhir",
        value=(
            f"<t:{last_at}:F>\n<t:{last_at}:R>"
            if last_at
            else "Belum ada"
        ),
        inline=True
    )
    embed.add_field(
        name="Backup Berikutnya",
        value=(
            f"<t:{due}:F>\n<t:{due}:R>"
            if due
            else "Menunggu backup pertama"
        ),
        inline=True
    )
    embed.add_field(
        name="Storage",
        value=f"`{AUTO_BACKUP_DIR}`",
        inline=False
    )
    embed.add_field(
        name="Proteksi Redeploy",
        value=(
            "✅ Jadwal membaca backup terakhir dari database/storage. "
            "Redeploy tidak seharusnya mengirim backup ulang sebelum jatuh tempo."
        ),
        inline=False
    )
    return embed




def platform_health_summary() -> dict:
    summary = {
        platform: {
            "total": 0,
            "healthy": 0,
            "warning": 0,
            "error": 0,
        }
        for platform in SUPPORTED_PLATFORMS
    }

    for guild in bot.guilds:
        try:
            hosts = get_hosts(guild.id)
        except Exception:
            continue

        for host in hosts:
            platform = str(host["platform"])
            if platform not in summary:
                continue

            score = host_health_score(host)
            summary[platform]["total"] += 1

            if score >= 90:
                summary[platform]["healthy"] += 1
            elif score >= 60:
                summary[platform]["warning"] += 1
            else:
                summary[platform]["error"] += 1

    return summary


def owner_platform_health_embed():
    summary = platform_health_summary()
    lines = []

    for platform in sorted(SUPPORTED_PLATFORMS):
        item = summary[platform]
        if item["total"] == 0:
            icon = "⚪"
        elif item["error"]:
            icon = "🔴"
        elif item["warning"]:
            icon = "🟡"
        else:
            icon = "🟢"

        with closing(db()) as conn:
            incident = conn.execute(
                "SELECT state FROM platform_incidents WHERE platform=?",
                (platform,)
            ).fetchone()

        incident_text = (
            " • 🚨 OUTAGE"
            if incident and incident["state"] == "outage"
            else ""
        )

        lines.append(
            f"{icon} **{platform_display_name(platform)}** — "
            f"{item['healthy']} sehat • "
            f"{item['warning']} warning • "
            f"{item['error']} error • "
            f"{item['total']} total{incident_text}"
        )

    return discord.Embed(
        title="🌐 Platform Health",
        description="\n".join(lines),
        color=discord.Color.blurple()
    ).add_field(
        name="Catatan",
        value=(
            "Status dihitung dari health/error host. "
            "Gangguan platform eksternal dapat memengaruhi banyak host sekaligus."
        ),
        inline=False
    )




def owner_self_test_embed():
    results = owner_self_test_results()
    passed = sum(1 for _, ok, _ in results if ok)

    lines = [
        f"{'✅' if ok else '❌'} **{name}** — {detail}"
        for name, ok, detail in results
    ]

    return discord.Embed(
        title="🧪 Self Test Bot",
        description="\n".join(lines),
        color=(
            discord.Color.green()
            if passed == len(results)
            else discord.Color.orange()
        )
    ).add_field(
        name="Ringkasan",
        value=f"**{passed}/{len(results)}** pemeriksaan OK",
        inline=False
    )


def owner_error_center_embed():
    hosts = []
    for guild in bot.guilds:
        try:
            hosts.extend(get_hosts(guild.id))
        except Exception:
            pass

    problems = [
        host
        for host in hosts
        if (
            host["last_error"]
            or int(host["error_count"] or 0) > 0
            or not host["enabled"]
        )
    ]

    lines = []
    for host in sorted(
        problems,
        key=lambda x: (host_health_score(x), -int(x["error_count"] or 0))
    )[:20]:
        score = host_health_score(host)
        icon = "🟢" if score >= 90 else "🟡" if score >= 60 else "🔴"
        guild = bot.get_guild(int(host["guild_id"]))
        label = host["display_name"] or host["target"]
        lines.append(
            f"{icon} **#{host['id']} {platform_display_name(host['platform'])} • {label}** "
            f"— {score}%\n"
            f"↳ {guild.name if guild else host['guild_id']} • "
            f"error {int(host['error_count'] or 0)}"
        )

    embed = discord.Embed(
        title="🚨 Error & Recovery Center",
        description=(
            "\n".join(lines)
            if lines
            else "✅ Tidak ada host bermasalah."
        ),
        color=(
            discord.Color.orange()
            if problems
            else discord.Color.green()
        )
    )
    embed.add_field(
        name="Recovery",
        value=(
            "Pilih host bermasalah untuk **Recheck** atau **Reset Error**. "
            "Reset tidak mengubah konfigurasi host."
        ),
        inline=False
    )
    return embed


def owner_notification_center_embed():
    summary, rows = global_notification_stats()

    lines = []
    for row in rows[:15]:
        status_icon = (
            "✅" if row["status"] == "sent"
            else "❌" if row["status"] == "failed"
            else "⏳"
        )
        label = row["display_name"] or row["target"] or f"Host {row['host_id']}"
        lines.append(
            f"{status_icon} <t:{row['created_at']}:R> • "
            f"**{label}** • `{row['event_type'] or 'notification'}`"
        )

    embed = discord.Embed(
        title="🔔 Notification Center",
        description=(
            "\n".join(lines)
            if lines
            else "Belum ada riwayat notifikasi."
        ),
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="24 Jam",
        value=(
            f"Total **{int(summary['total'] or 0)}** • "
            f"Sent **{int(summary['sent'] or 0)}** • "
            f"Failed **{int(summary['failed'] or 0)}** • "
            f"Latency **{round(float(summary['latency'] or 0))} ms**"
        ),
        inline=False
    )
    return embed


def owner_quota_embed():
    rows = api_usage_today_rows()

    lines = [
        f"• **{row['service']}** `{row['endpoint']}` → **{row['calls']} calls**"
        for row in rows[:25]
    ]

    return discord.Embed(
        title="📡 API / Quota Monitor",
        description=(
            "\n".join(lines)
            if lines
            else "Belum ada API call tercatat hari ini."
        ),
        color=discord.Color.blurple()
    ).add_field(
        name="Catatan",
        value=(
            "Angka ini adalah **jumlah call lokal bot**, bukan unit quota resmi "
            "Google/YouTube."
        ),
        inline=False
    )


def owner_audit_embed():
    rows = global_activity_rows(20)

    lines = []
    for row in rows:
        guild = bot.get_guild(int(row["guild_id"])) if row["guild_id"] else None
        lines.append(
            f"• <t:{row['created_at']}:R> • "
            f"**{row['action']}**\n"
            f"  Actor `{row['actor_id'] or '-'}` • "
            f"{guild.name if guild else row['guild_id'] or 'global'}"
        )

    return discord.Embed(
        title="🧾 Global Audit Log",
        description=(
            "\n".join(lines)
            if lines
            else "Belum ada aktivitas."
        ),
        color=discord.Color.dark_gray()
    )


def owner_emergency_embed():
    row = get_runtime_settings()

    def mark(value):
        return "🔴 ON" if value else "🟢 OFF"

    embed = discord.Embed(
        title="🚨 Emergency Control",
        description=(
            "Hanya **Primary Global Owner**. Semua perubahan tersimpan di database."
        ),
        color=discord.Color.red()
    )
    embed.add_field(
        name="Pause Checker",
        value=mark(bool(row["monitor_paused"])),
        inline=True
    )
    embed.add_field(
        name="Stop Notifikasi",
        value=mark(bool(row["notifications_paused"])),
        inline=True
    )
    embed.add_field(
        name="Stop Request Baru",
        value=mark(bool(row["requests_paused"])),
        inline=True
    )
    embed.add_field(
        name="Maintenance Global",
        value=mark(bool(row["maintenance_all"])),
        inline=True
    )
    return embed


def owner_risk_embed():
    lines = []
    for guild in bot.guilds[:30]:
        settings = get_guild_settings(guild.id)
        state = str(settings["access_state"] or "allowed")
        if state != "allowed":
            lines.append(
                f"• **{guild.name}** (`{guild.id}`) — {access_state_label(state)}"
            )

    return discord.Embed(
        title="🛡️ Server Risk Control",
        description=(
            "\n".join(lines)
            if lines
            else "✅ Semua server dalam status Normal."
        ),
        color=discord.Color.orange()
    ).add_field(
        name="Status",
        value="Normal • Warning • Suspended • Blacklist • Whitelist",
        inline=False
    )


def owner_backup_center_embed():
    last_at = last_successful_auto_backup_at()
    due = (
        int(last_at) + int(AUTO_BACKUP_HOURS * 3600)
        if last_at else None
    )

    return discord.Embed(
        title="🗄️ Backup Center",
        description=(
            "Backup manual **tidak mengubah jadwal auto backup 48 jam**."
        ),
        color=discord.Color.blurple()
    ).add_field(
        name="Auto Backup",
        value=(
            f"Terakhir: {f'<t:{last_at}:R>' if last_at else 'belum ada'}\n"
            f"Berikutnya: {f'<t:{due}:R>' if due else 'menunggu backup pertama'}"
        ),
        inline=False
    ).add_field(
        name="Storage",
        value=f"`{AUTO_BACKUP_DIR}`",
        inline=False
    )




def release_info_text() -> str:
    commit = GIT_COMMIT[:8] if GIT_COMMIT else "local"
    build = BUILD_ID[:12] if BUILD_ID else "-"
    return (
        f"v{APP_VERSION} • schema {CURRENT_SCHEMA_VERSION} • "
        f"commit `{commit}` • build `{build}`"
    )


def schema_history_rows(limit: int = 10):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT * FROM migration_history
            ORDER BY version DESC
            LIMIT ?
        """, (max(1, min(50, int(limit))),)).fetchall()


def owner_home_embed():
    free_count = len(guilds_by_plan("free"))
    premium_count = len(guilds_by_plan("premium"))
    stats = global_access_stats()

    hosts = []
    for guild in bot.guilds:
        try:
            hosts.extend(get_hosts(guild.id))
        except Exception:
            pass

    errors = sum(1 for host in hosts if host["last_error"])

    embed = discord.Embed(
        title="🛡️ Hi Notifku • Global Owner",
        description="Panel utama administrasi bot.",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="Server",
        value=(
            f"**{len(bot.guilds)}** total • 🆓 **{free_count}** • ⭐ **{premium_count}**"
        ),
        inline=False
    )
    embed.add_field(
        name="Notifier",
        value=(
            f"Host **{len(hosts)}** • Error **{errors}** • Ping **{round(bot.latency * 1000)} ms**"
        ),
        inline=False
    )
    embed.add_field(
        name="Akses",
        value=(
            f"Owner **{stats['global_owners']}** • Server Owner **{stats['server_owners']}** • "
            f"Manager **{stats['host_managers']}**"
        ),
        inline=False
    )
    embed.add_field(
        name="Status",
        value=(
            f"Request Manager **{stats['pending_access']}** • Host **{stats['pending_hosts']}** • "
            f"Uptime <t:{STARTED_AT}:R>"
        ),
        inline=False
    )
    embed.set_footer(
        text=f"v{APP_VERSION} • schema {CURRENT_SCHEMA_VERSION} • /owner • DM only"
    )
    return embed

def server_embed(guild: discord.Guild):
    cfg = get_config(guild.id)
    settings = get_guild_settings(guild.id)
    hosts = get_hosts(guild.id)

    tt_channel = (
        f"<#{cfg['tiktok_channel_id']}>"
        if cfg["tiktok_channel_id"] else "-"
    )
    yt_channel = (
        f"<#{cfg['youtube_channel_id']}>"
        if cfg["youtube_channel_id"] else "-"
    )
    mention_role = (
        f"<@&{cfg['mention_role_id']}>"
        if cfg["mention_role_id"] else "-"
    )
    log_channel = (
        f"<#{cfg['log_channel_id']}>"
        if cfg["log_channel_id"] else "-"
    )

    embed = discord.Embed(
        title=f"🔔 {guild.name}",
        description=(
            f"Plan **{'PREMIUM' if premium_access_effective(guild.id) else 'FREE'}** • "
            f"Host **{len(hosts)}/{host_limit_for_guild(guild.id)}** • "
            f"Access **{settings['access_state']}**"
        ),
        color=(
            discord.Color.gold()
            if premium_access_effective(guild.id)
            else discord.Color.blue()
        )
    )

    if premium_access_effective(guild.id):
        embed.add_field(
            name="Premium",
            value=premium_expiry_text(guild.id),
            inline=False
        )

    embed.add_field(
        name="Channel",
        value=f"🎵 {tt_channel}\n📺 {yt_channel}",
        inline=True
    )
    embed.add_field(
        name="Mention / Log",
        value=f"🔔 {mention_role}\n🧾 {log_channel}",
        inline=True
    )
    embed.set_footer(text=f"Server ID: {guild.id}")
    return embed


def host_embed(host):
    platform_name = platform_display_name(host["platform"])
    status = host_status_text(host)

    channel_text = (
        f"<#{host['channel_id']}>"
        if host["channel_id"] else "Default"
    )
    role_text = (
        f"<@&{host['role_id']}>"
        if host["role_id"] else "Default"
    )

    embed = discord.Embed(
        title=f"{platform_icon(host['platform'])} {platform_name}",
        description=(
            f"`{host['target']}`\n"
            f"{status} • Interval **{host['check_interval']}s**"
        ),
        color=(
            discord.Color.green()
            if host["enabled"] and not host["last_error"]
            else discord.Color.orange()
        )
    )

    embed.add_field(
        name="Channel / Role",
        value=f"{channel_text} • {role_text}",
        inline=False
    )
    embed.add_field(
        name="Monitor",
        value=(
            f"Last: {fmt_time(host['last_check'])}\n"
            f"Error: **{host['error_count'] or 0}**"
        ),
        inline=True
    )
    embed.add_field(
        name="Live End",
        value="ON" if host["notify_live_end"] else "OFF",
        inline=True
    )

    if host["last_error"]:
        embed.add_field(
            name="Error Terakhir",
            value=str(host["last_error"])[:700],
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
        placeholder="youtube/tiktok/twitch/kick/instagram/facebook",
        max_length=20
    )
    target = discord.ui.TextInput(
        label="Username / Channel ID / URL",
        placeholder="Username, YouTube Channel ID, atau URL Facebook",
        max_length=300
    )

    def __init__(self, guild_id: int):
        super().__init__(title="Tambah Host Sosmed", timeout=300)
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        platform = self.platform.value.strip().lower()
        target_raw = self.target.value.strip()

        if platform not in SUPPORTED_PLATFORMS:
            await safe_reply(
                interaction,
                (
                    "❌ Platform belum didukung.\n"
                    "Gunakan: `youtube`, `tiktok`, `twitch`, `kick`, "
                    "`instagram`, atau `facebook`."
                )
            )
            return

        target = normalize_social_target(
            platform,
            target_raw
        )

        if not target:
            await safe_reply(
                interaction,
                "❌ Username/target tidak valid."
            )
            return

        if platform == "youtube":
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
            return

        display = (
            f"@{target}"
            if platform != "facebook" or not target.startswith("http")
            else target
        )

        try:
            add_host(
                self.guild_id,
                platform,
                target,
                display
            )
        except ValueError as exc:
            await safe_reply(
                interaction,
                f"❌ {exc}"
            )
            return

        await log_action(
            self.guild_id,
            interaction.user.id,
            "Tambah Host",
            f"{platform_display_name(platform)} {display}"
        )

        note = ""
        if platform in {"instagram", "facebook"}:
            note = (
                "\n⚠️ Instagram/Facebook memakai extractor best-effort; "
                "akun privat atau halaman yang meminta login bisa gagal dipantau."
            )

        await safe_reply(
            interaction,
            (
                f"✅ {platform_icon(platform)} "
                f"**{platform_display_name(platform)}** `{display}` ditambahkan."
                f"{note}"
            )
        )


class BulkImportModal(discord.ui.Modal):
    data = discord.ui.TextInput(
        label="Daftar Host",
        placeholder=(
            "tiktok,username\n"
            "youtube,UCxxxxxxxx\n"
            "twitch,username\n"
            "kick,username\n"
            "instagram,username\n"
            "facebook,https://facebook.com/namapage"
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

            platform, target_raw = [
                x.strip()
                for x in line.split(",", 1)
            ]
            platform = platform.lower()

            if platform not in SUPPORTED_PLATFORMS:
                errors.append(
                    f"`{line}` → platform tidak didukung"
                )
                continue

            target = normalize_social_target(
                platform,
                target_raw
            )

            try:
                if platform == "youtube":
                    name, uploads = await resolve_youtube_channel(target)
                    add_host(
                        self.guild_id,
                        platform,
                        target,
                        name,
                        uploads
                    )
                else:
                    add_host(
                        self.guild_id,
                        platform,
                        target,
                        f"@{target}" if not target.startswith("http") else target
                    )

                added += 1

            except Exception as exc:
                errors.append(
                    f"`{line}` → {exc}"
                )

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
        if not await require_premium_feature(
            interaction, self.guild_id, "custom_templates", "Custom pesan"
        ):
            return

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



class PremiumDurationModal(discord.ui.Modal):
    days = discord.ui.TextInput(
        label="Masa aktif Premium (hari)",
        placeholder="Contoh: 30",
        max_length=5
    )

    def __init__(self, guild_id: int, mode: str = "activate"):
        title = "Aktifkan Premium" if mode == "activate" else "Perpanjang Premium"
        super().__init__(title=title, timeout=300)
        self.guild_id = guild_id
        self.mode = mode

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return

        raw = self.days.value.strip()

        if not raw.isdigit():
            await safe_reply(
                interaction,
                "❌ Jumlah hari harus berupa angka."
            )
            return

        days = int(raw)

        if days < 1 or days > 3650:
            await safe_reply(
                interaction,
                "❌ Masa aktif harus antara **1 sampai 3650 hari**."
            )
            return

        extend = self.mode == "extend"

        set_plan(
            self.guild_id,
            "premium",
            duration_days=days,
            extend=extend
        )

        guild = bot.get_guild(self.guild_id)

        await log_action(
            self.guild_id,
            interaction.user.id,
            "Premium Duration",
            (
                f"{'Perpanjang' if extend else 'Aktifkan'} Premium "
                f"{days} hari. Expiry: {premium_expiry_text(self.guild_id)}"
            )
        )

        if guild:
            try:
                owner = guild.owner or await guild.fetch_member(guild.owner_id)
                await owner.send(
                    f"⭐ Server **{guild.name}** sekarang **PREMIUM**.\n"
                    f"Masa aktif: **{days} hari**.\n"
                    f"Berakhir: {premium_expiry_text(self.guild_id)}"
                )
            except Exception:
                log.warning(
                    "Tidak bisa DM owner guild_id=%s setelah aktivasi Premium.",
                    self.guild_id
                )

        await safe_reply(
            interaction,
            (
                f"⭐ Premium berhasil {'diperpanjang' if extend else 'diaktifkan'} "
                f"selama **{days} hari**.\n"
                f"Berakhir: {premium_expiry_text(self.guild_id)}"
            )
        )





class ReceivedAmountModal(discord.ui.Modal):
    amount = discord.ui.TextInput(
        label="Nominal Transfer yang Masuk",
        placeholder="Contoh: 25137",
        max_length=15
    )

    def __init__(self, order_id: int):
        super().__init__(
            title="Cek Nominal Transfer",
            timeout=300
        )
        self.order_id = order_id

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return

        raw = (
            self.amount.value
            .strip()
            .replace(".", "")
            .replace(",", "")
            .replace("Rp", "")
            .replace("rp", "")
            .replace(" ", "")
        )

        if not raw.isdigit():
            await safe_reply(
                interaction,
                "❌ Nominal harus berupa angka."
            )
            return

        received = int(raw)
        matched = verify_received_amount(
            self.order_id,
            received
        )

        order = get_premium_order(self.order_id)

        if matched:
            auto_ok = False
            auto_message = ""

            try:
                auto_ok, auto_message = await maybe_auto_activate_verified_order(
                    self.order_id,
                    actor_id=interaction.user.id,
                    source="verified_received_amount"
                )
            except Exception as exc:
                log.exception("Auto aktivasi Premium gagal")
                auto_message = f"Auto aktivasi gagal: {type(exc).__name__}"

            await safe_reply(
                interaction,
                (
                    f"✅ Nominal **SESUAI**.\n"
                    f"Harga paket: **{rupiah(int(order['price']))}**\n"
                    f"Kode unik: **{int(order['unique_code'] or 0):03d}**\n"
                    f"Total wajib: **{rupiah(order['expected_amount'])}**\n"
                    f"Nominal masuk: **{rupiah(received)}**\n\n"
                    + (
                        "⭐ **Premium otomatis aktif sesuai paket.**"
                        if auto_ok
                        else f"ℹ️ {auto_message}"
                    )
                )
            )
        else:
            expected = int(order["expected_amount"] or order["price"])
            diff = received - expected
            detail = (
                f"lebih {rupiah(diff)}"
                if diff > 0
                else f"kurang {rupiah(abs(diff))}"
            )

            await safe_reply(
                interaction,
                (
                    f"❌ Nominal **TIDAK SESUAI**.\n"
                    f"Harga paket: **{rupiah(int(order['price']))}**\n"
                    f"Kode unik: **{int(order['unique_code'] or 0):03d}**\n"
                    f"Harus masuk persis: **{rupiah(expected)}**\n"
                    f"Nominal masuk: **{rupiah(received)}**\n"
                    f"Selisih: **{detail}**\n\n"
                    "Nominal wajib termasuk kode unik dan tidak boleh dibulatkan."
                )
            )


class AccountPaymentMethodModal(discord.ui.Modal):
    method_name = discord.ui.TextInput(
        label="Nama Metode",
        placeholder="Contoh: DANA / BCA / GoPay",
        max_length=100
    )
    account_name = discord.ui.TextInput(
        label="Atas Nama",
        placeholder="Contoh: Andri Store",
        max_length=100,
        required=False
    )
    account_number = discord.ui.TextInput(
        label="Nomor / Rekening",
        placeholder="Contoh: 081234567890",
        max_length=100
    )
    payment_note = discord.ui.TextInput(
        label="Instruksi",
        placeholder="Contoh: Transfer sesuai nominal unik.",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False
    )

    def __init__(self):
        super().__init__(
            title="Tambah Rekening / E-Wallet",
            timeout=300
        )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(
                interaction,
                "❌ Hanya OWNER_IDS utama yang dapat mengatur pembayaran."
            )
            return

        method_id = add_payment_method(
            "account",
            self.method_name.value,
            self.account_name.value,
            self.account_number.value,
            self.payment_note.value
        )

        await safe_reply(
            interaction,
            f"✅ Metode pembayaran **#{method_id}** berhasil ditambahkan."
        )


class QRISNameModal(discord.ui.Modal):
    method_name = discord.ui.TextInput(
        label="Nama QRIS",
        placeholder="Contoh: QRIS Hi Notifku",
        max_length=100
    )
    account_name = discord.ui.TextInput(
        label="Atas Nama",
        placeholder="Contoh: Andri Store",
        max_length=100,
        required=False
    )
    payment_note = discord.ui.TextInput(
        label="Instruksi",
        placeholder="Contoh: Scan QRIS dan bayar sesuai nominal unik.",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False
    )

    def __init__(self):
        super().__init__(
            title="Siapkan Upload QRIS",
            timeout=300
        )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(
                interaction,
                "❌ Hanya OWNER_IDS utama yang dapat mengatur pembayaran."
            )
            return

        method_id = add_payment_method(
            "qris",
            self.method_name.value,
            self.account_name.value,
            "",
            self.payment_note.value,
            ""
        )

        # Remember which QRIS method awaits image upload.
        pending_qris_uploads[interaction.user.id] = method_id
        set_pending_upload(interaction.user.id, "qris", method_id)

        await safe_reply(
            interaction,
            (
                f"✅ QRIS **#{method_id}** dibuat.\n"
                "Sekarang kirim **gambar QRIS** ke DM bot ini.\n"
                "Gambar pertama yang kamu kirim akan dipasang ke QRIS tersebut."
            )
        )



class EditPaymentMethodModal(discord.ui.Modal):
    method_name = discord.ui.TextInput(
        label="Nama Metode",
        max_length=100
    )
    account_name = discord.ui.TextInput(
        label="Atas Nama",
        max_length=100,
        required=False
    )
    account_number = discord.ui.TextInput(
        label="Nomor / Rekening",
        max_length=100,
        required=False
    )
    payment_note = discord.ui.TextInput(
        label="Instruksi",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False
    )

    def __init__(self, method_id: int):
        self.method_id = int(method_id)
        method = get_payment_method(self.method_id)
        super().__init__(title="Edit Metode Pembayaran", timeout=300)

        if method:
            self.method_name.default = method["method_name"] or ""
            self.account_name.default = method["account_name"] or ""
            self.account_number.default = method["account_number"] or ""
            self.payment_note.default = method["payment_note"] or ""

    async def on_submit(self, interaction: discord.Interaction):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return

        update_payment_method(
            self.method_id,
            method_name=self.method_name.value,
            account_name=self.account_name.value,
            account_number=self.account_number.value,
            payment_note=self.payment_note.value
        )
        await safe_reply(interaction, "✅ Metode pembayaran diperbarui.")


class PaymentMethodAdminSelect(discord.ui.Select):
    def __init__(self, action: str):
        self.action = action
        methods = list_payment_methods(False)[:25]

        options = [
            discord.SelectOption(
                label=f"#{m['id']} • {m['method_name']}"[:100],
                value=str(m["id"]),
                description=(
                    ("Aktif" if m["enabled"] else "Nonaktif")
                    + " • "
                    + ("QRIS" if m["method_type"] == "qris" else "Rekening/E-Wallet")
                )[:100]
            )
            for m in methods
        ]

        if not options:
            options = [
                discord.SelectOption(
                    label="Tidak ada metode",
                    value="0"
                )
            ]

        super().__init__(
            placeholder="Pilih metode pembayaran...",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return

        method_id = int(self.values[0])

        if method_id == 0:
            await safe_reply(interaction, "Belum ada metode pembayaran.")
            return

        method = get_payment_method(method_id)

        if not method:
            await safe_reply(interaction, "❌ Metode tidak ditemukan.")
            return

        if self.action == "edit":
            await interaction.response.send_modal(
                EditPaymentMethodModal(method_id)
            )
            return

        if self.action == "toggle":
            set_payment_method_enabled(
                method_id,
                not bool(method["enabled"])
            )
            await safe_reply(
                interaction,
                "✅ Status metode pembayaran diperbarui."
            )

            return

        if self.action == "qris":
            if method["method_type"] != "qris":
                await safe_reply(
                    interaction,
                    "❌ Metode yang dipilih bukan QRIS."
                )
                return

            pending_qris_uploads[interaction.user.id] = method_id
            set_pending_upload(
                interaction.user.id,
                "qris",
                method_id
            )
            await safe_reply(
                interaction,
                "📎 Kirim gambar QRIS baru ke DM bot ini."
            )


class PaymentMethodAdminSelectView(discord.ui.View):
    def __init__(self, action: str):
        super().__init__(timeout=300)
        self.add_item(PaymentMethodAdminSelect(action))

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=payment_methods_overview_embed(),
            view=PaymentSettingsView()
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class DeletePaymentMethodModal(discord.ui.Modal):
    method_id = discord.ui.TextInput(
        label="ID Metode Pembayaran",
        placeholder="Contoh: 2",
        max_length=10
    )

    def __init__(self):
        super().__init__(
            title="Hapus Metode Pembayaran",
            timeout=300
        )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return

        raw = self.method_id.value.strip()

        if not raw.isdigit():
            await safe_reply(interaction, "❌ ID harus berupa angka.")
            return

        method = get_payment_method(int(raw))

        if not method:
            await safe_reply(interaction, "❌ Metode tidak ditemukan.")
            return

        delete_payment_method(int(raw))

        await safe_reply(
            interaction,
            f"✅ Metode **#{raw} • {method['method_name']}** dihapus."
        )


class PaymentSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(
        label="Rekening",
        emoji="🏦",
        style=discord.ButtonStyle.success,
        row=0
    )
    async def add_account(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return

        await interaction.response.send_modal(
            AccountPaymentMethodModal()
        )

    @discord.ui.button(
        label="QRIS",
        emoji="🧾",
        style=discord.ButtonStyle.success,
        row=0
    )
    async def add_qris(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return

        await interaction.response.send_modal(
            QRISNameModal()
        )

    @discord.ui.button(
        label="Edit",
        emoji="✏️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def edit_method(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return
        await interaction.response.edit_message(
            embed=payment_methods_overview_embed(),
            view=PaymentMethodAdminSelectView("edit")
        )

    @discord.ui.button(
        label="Aktif / Nonaktif",
        emoji="⏯️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def toggle_method(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return
        await interaction.response.edit_message(
            embed=payment_methods_overview_embed(),
            view=PaymentMethodAdminSelectView("toggle")
        )

    @discord.ui.button(
        label="Ganti QRIS",
        emoji="🖼️",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def replace_qris(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return
        await interaction.response.edit_message(
            embed=payment_methods_overview_embed(),
            view=PaymentMethodAdminSelectView("qris")
        )

    @discord.ui.button(
        label="Hapus",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        row=1
    )
    async def delete_method(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return

        await interaction.response.send_modal(
            DeletePaymentMethodModal()
        )

    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=payment_methods_overview_embed(),
            view=PaymentSettingsView()
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        all_owners = OWNER_IDS | db_owner_ids()

        embed = discord.Embed(
            title="👑 Kelola Owner",
            description=(
                "\n".join(
                    f"• <@{x}> (`{x}`) • **{owner_role(x)}**"
                    for x in sorted(all_owners)
                ) or "Tidak ada"
            ),
            color=discord.Color.gold()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=OwnerManagementView()
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class PremiumPackageModal(discord.ui.Modal):
    days = discord.ui.TextInput(
        label="Hari",
        placeholder="Contoh: 30",
        max_length=5
    )
    price = discord.ui.TextInput(
        label="Isi Harga (Rp)",
        placeholder="Contoh: 25000",
        max_length=12
    )

    def __init__(self):
        super().__init__(
            title="Tambah / Ubah Paket Premium",
            timeout=300
        )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(
                interaction,
                "❌ Hanya OWNER_IDS utama yang dapat mengatur harga."
            )
            return

        days_raw = self.days.value.strip()
        price_raw = self.price.value.strip().replace(".", "").replace(",", "")

        if not days_raw.isdigit() or not price_raw.isdigit():
            await safe_reply(
                interaction,
                "❌ Hari dan harga harus berupa angka."
            )
            return

        days = int(days_raw)
        price = int(price_raw)

        if days < 1 or days > 3650:
            await safe_reply(
                interaction,
                "❌ Hari harus antara 1 sampai 3650."
            )
            return

        upsert_premium_package(days, price)

        await safe_reply(
            interaction,
            f"✅ Paket berhasil disimpan.\n📅 Hari: **{days} hari**\n💰 Isi Harga: **{rupiah(price)}**."
        )


class DeletePremiumPackageModal(discord.ui.Modal):
    days = discord.ui.TextInput(
        label="Jumlah hari paket yang dihapus",
        placeholder="Contoh: 30",
        max_length=5
    )

    def __init__(self):
        super().__init__(
            title="Hapus Paket Premium",
            timeout=300
        )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(
                interaction,
                "❌ Hanya OWNER_IDS utama yang dapat mengatur harga."
            )
            return

        raw = self.days.value.strip()

        if not raw.isdigit():
            await safe_reply(
                interaction,
                "❌ Jumlah hari harus berupa angka."
            )
            return

        days = int(raw)
        delete_premium_package(days)

        await safe_reply(
            interaction,
            f"✅ Paket **{days} hari** dihapus."
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



def start_verify_embed(user_id: int, verified: bool):
    if verified:
        embed = discord.Embed(
            title="✅ Verifikasi Berhasil",
            description=(
                "Kamu sudah bergabung ke **server resmi Hi Notifku**.\n\n"
                "Sekarang kamu bisa menggunakan `/menu`."
            ),
            color=discord.Color.green()
        )
    else:
        embed = discord.Embed(
            title="🔒 Verifikasi Hi Notifku",
            description=(
                "Untuk menggunakan Hi Notifku, kamu wajib bergabung ke "
                "**Server Resmi Owner/Support** terlebih dahulu.\n\n"
                "Setelah join, tekan **Verifikasi Join**."
            ),
            color=discord.Color.orange()
        )

        if REQUIRED_GUILD_INVITE:
            embed.add_field(
                name="Server Support",
                value=REQUIRED_GUILD_INVITE,
                inline=False
            )

    embed.set_footer(text=f"User ID: {user_id}")
    return embed


class StartVerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        if REQUIRED_GUILD_INVITE:
            self.add_item(
                discord.ui.Button(
                    label="Join Server Support",
                    emoji="🔗",
                    style=discord.ButtonStyle.link,
                    url=REQUIRED_GUILD_INVITE
                )
            )

    @discord.ui.button(
        label="Verifikasi Join",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="hi_notifku:start_verify"
    )
    async def verify_join(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        # Global owner bypass
        if is_global_owner(interaction.user.id):
            await interaction.response.edit_message(
                embed=start_verify_embed(
                    interaction.user.id,
                    True
                ),
                view=None
            )
            return

        verified = await is_user_in_required_guild(
            interaction.user.id
        )

        if verified:
            await interaction.response.edit_message(
                embed=start_verify_embed(
                    interaction.user.id,
                    True
                ),
                view=None
            )
        else:
            await safe_reply(
                interaction,
                (
                    "❌ Kamu belum terdeteksi sebagai member Server Resmi Owner/Support.\n"
                    "Join server terlebih dahulu lalu tekan **Verifikasi Join** lagi."
                )
            )


def user_server_embed(guild: discord.Guild):
    settings = get_guild_settings(guild.id)
    plan = "premium" if premium_access_effective(guild.id) else "free"

    embed = discord.Embed(
        title="🔔 Hi Notifku",
        description=f"Server: **{guild.name}**",
        color=discord.Color.gold() if plan == "premium" else discord.Color.blue()
    )

    embed.add_field(
        name="Plan",
        value="⭐ PREMIUM" if plan == "premium" else "🆓 FREE",
        inline=True
    )
    current_hosts = len(get_hosts(guild.id))
    host_limit = host_limit_for_guild(guild.id)

    embed.add_field(
        name="Host",
        value=f"{current_hosts}/{host_limit}",
        inline=True
    )

    embed.add_field(
        name="Premium",
        value=(
            f"⭐ Aktif • {premium_expiry_text(guild.id)}"
            if plan == "premium"
            else "🆓 FREE • tekan **Premium** untuk upgrade"
        ),
        inline=False
    )

    embed.add_field(
        name="Akses",
        value="👑 Pemilik Server",
        inline=True
    )
    embed.add_field(
        name="Verifikasi Owner",
        value=guild_verification_status_text(guild.id),
        inline=True
    )

    pending_total = (
        len(pending_server_access_requests(guild.id))
        + len(pending_host_creation_requests(guild.id))
    )
    embed.add_field(
        name="Request Pending",
        value=f"📨 {pending_total}",
        inline=True
    )
    stats7 = server_usage_stats(guild.id, 7)
    embed.add_field(
        name="Health Score",
        value=f"**{server_health_score(guild.id)}%**",
        inline=True
    )
    embed.add_field(
        name="Notif 7 Hari",
        value=f"✅ {stats7['sent']} • ❌ {stats7['failed']}",
        inline=True
    )

    embed.set_footer(
        text=(
            "Kelola host server sendiri melalui tombol Kelola Host. "
            "Panel Global Owner tetap terpisah."
        )
    )
    return embed



def user_owned_guilds(user_id: int):
    return [
        guild
        for guild in bot.guilds
        if int(guild.owner_id) == int(user_id)
    ]


async def user_mutual_guilds(user_id: int):
    result = []

    for guild in bot.guilds:
        if int(guild.owner_id) == int(user_id):
            # Already handled as a server owner.
            continue

        member = guild.get_member(int(user_id))

        if member is None:
            try:
                member = await guild.fetch_member(int(user_id))
            except Exception:
                member = None

        if member is not None:
            result.append(guild)

    return result


def guild_host_count(guild_id: int) -> int:
    return len(get_hosts(int(guild_id)))


def claim_host_creation_request(
    request_id: int,
    actor_id: int
) -> bool:
    with closing(db()) as conn:
        cur = conn.execute("""
            UPDATE host_creation_requests
            SET status='processing',
                processed_by=?,
                processed_at=?
            WHERE id=? AND status='pending'
        """, (
            int(actor_id),
            int(time.time()),
            int(request_id)
        ))
        conn.commit()
        return cur.rowcount == 1


def reset_host_creation_request_claim(
    request_id: int
):
    with closing(db()) as conn:
        conn.execute("""
            UPDATE host_creation_requests
            SET status='pending',
                processed_by=NULL,
                processed_at=NULL
            WHERE id=? AND status='processing'
        """, (int(request_id),))
        conn.commit()


def claim_server_access_request(
    request_id: int,
    actor_id: int
) -> bool:
    with closing(db()) as conn:
        cur = conn.execute("""
            UPDATE server_host_access_requests
            SET status='processing',
                processed_by=?,
                processed_at=?
            WHERE id=? AND status='pending'
        """, (
            int(actor_id),
            int(time.time()),
            int(request_id)
        ))
        conn.commit()
        return cur.rowcount == 1


def reset_server_access_request_claim(
    request_id: int
):
    with closing(db()) as conn:
        conn.execute("""
            UPDATE server_host_access_requests
            SET status='pending',
                processed_by=NULL,
                processed_at=NULL
            WHERE id=? AND status='processing'
        """, (int(request_id),))
        conn.commit()




def create_server_host_access_request(
    guild_id: int,
    user_id: int
) -> int:
    if (
        runtime_setting_enabled("requests_paused")
        or runtime_setting_enabled("maintenance_all")
    ):
        raise RuntimeError(
            "Request baru sedang dinonaktifkan sementara oleh Global Owner."
        )

    with closing(db()) as conn:
        existing = conn.execute("""
            SELECT id
            FROM server_host_access_requests
            WHERE guild_id=? AND user_id=? AND status='pending'
            ORDER BY id DESC
            LIMIT 1
        """, (
            int(guild_id),
            int(user_id)
        )).fetchone()

        if existing:
            return int(existing["id"])

        cur = conn.execute("""
            INSERT INTO server_host_access_requests(
                guild_id,
                user_id,
                status,
                created_at
            )
            VALUES(?,?,'pending',?)
        """, (
            int(guild_id),
            int(user_id),
            int(time.time())
        ))
        conn.commit()
        return int(cur.lastrowid)


def get_server_host_access_request(
    request_id: int
):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM server_host_access_requests
            WHERE id=?
        """, (int(request_id),)).fetchone()


def finish_server_host_access_request(
    request_id: int,
    *,
    status: str,
    actor_id: int,
    host_id: Optional[int] = None
) -> bool:
    if status not in {"approved", "denied", "cancelled"}:
        raise ValueError("Status request tidak valid.")

    with closing(db()) as conn:
        cur = conn.execute("""
            UPDATE server_host_access_requests
            SET status=?,
                approved_host_id=?,
                processed_by=?,
                processed_at=?
            WHERE id=? AND status IN ('pending','processing')
        """, (
            status,
            int(host_id) if host_id else None,
            int(actor_id),
            int(time.time()),
            int(request_id)
        ))
        conn.commit()
        return cur.rowcount > 0


def server_host_access_request_embed(
    request_id: int
):
    row = get_server_host_access_request(
        request_id
    )

    if not row:
        return discord.Embed(
            title="📨 Permintaan Host Manager",
            description="Request tidak ditemukan.",
            color=discord.Color.red()
        )

    guild = bot.get_guild(int(row["guild_id"]))
    guild_name = (
        guild.name
        if guild
        else f"Server {row['guild_id']}"
    )
    hosts = get_hosts(int(row["guild_id"]))

    embed = discord.Embed(
        title=f"📨 Request Host Manager #{request_id}",
        description=(
            f"User <@{row['user_id']}> (`{row['user_id']}`) meminta akses "
            f"Host Manager di server **{guild_name}**.\n\n"
            f"Host tersedia: **{len(hosts)}**\n"
            f"Status: **{str(row['status']).upper()}**"
        ),
        color=(
            discord.Color.orange()
            if row["status"] == "pending"
            else discord.Color.green()
            if row["status"] == "approved"
            else discord.Color.red()
        )
    )

    if row["status"] == "pending":
        embed.add_field(
            name="Tindakan Pemilik Server",
            value=(
                "✅ **Setujui** → beri akses Host Manager tingkat server\n"
                "❌ **Tolak** → request ditutup"
            ),
            inline=False
        )

        embed.add_field(
            name="Setelah Disetujui",
            value=(
                "Host Manager dapat membuka dashboard server dan mengajukan "
                "host baru. Setiap host baru tetap harus kamu setujui."
            ),
            inline=False
        )

    embed.set_footer(
        text=(
            "Hanya Pemilik Server yang dapat memproses • "
            "Global Owner Bot tidak diperlukan"
        )
    )
    return embed




def create_host_creation_request(
    guild_id: int,
    requester_id: int,
    platform: str,
    target: str,
    channel_id: int,
    role_id: Optional[int]
) -> int:
    if (
        runtime_setting_enabled("requests_paused")
        or runtime_setting_enabled("maintenance_all")
    ):
        raise RuntimeError(
            "Pengajuan host baru sedang dinonaktifkan sementara oleh Global Owner."
        )

    if not server_host_manager_access(
        requester_id,
        guild_id
    ) and not host_manager_has_guild_access(
        requester_id,
        guild_id
    ):
        raise PermissionError(
            "Akses Host Manager server tidak aktif."
        )

    with closing(db()) as conn:
        existing = conn.execute("""
            SELECT id
            FROM host_creation_requests
            WHERE guild_id=?
              AND requester_id=?
              AND platform=?
              AND target=?
              AND status='pending'
            ORDER BY id DESC
            LIMIT 1
        """, (
            int(guild_id),
            int(requester_id),
            platform,
            target
        )).fetchone()

        if existing:
            return int(existing["id"])

        cur = conn.execute("""
            INSERT INTO host_creation_requests(
                guild_id,
                requester_id,
                platform,
                target,
                channel_id,
                role_id,
                status,
                created_at
            )
            VALUES(?,?,?,?,?,?,'pending',?)
        """, (
            int(guild_id),
            int(requester_id),
            platform,
            target,
            int(channel_id),
            int(role_id) if role_id else None,
            int(time.time())
        ))
        conn.commit()
        return int(cur.lastrowid)


def get_host_creation_request(
    request_id: int
):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM host_creation_requests
            WHERE id=?
        """, (
            int(request_id),
        )).fetchone()


def finish_host_creation_request(
    request_id: int,
    *,
    status: str,
    actor_id: int,
    host_id: Optional[int] = None,
    reason: Optional[str] = None
) -> bool:
    if status not in {
        "approved",
        "denied",
        "cancelled"
    }:
        raise ValueError("Status request host tidak valid.")

    with closing(db()) as conn:
        cur = conn.execute("""
            UPDATE host_creation_requests
            SET status=?,
                processed_by=?,
                processed_at=?,
                created_host_id=?,
                rejection_reason=?
            WHERE id=? AND status IN ('pending','processing')
        """, (
            status,
            int(actor_id),
            int(time.time()),
            int(host_id) if host_id else None,
            reason,
            int(request_id)
        ))
        conn.commit()
        return cur.rowcount > 0


def host_creation_request_embed(
    request_id: int
):
    row = get_host_creation_request(
        request_id
    )

    if not row:
        return discord.Embed(
            title="➕ Request Host Baru",
            description="Request tidak ditemukan.",
            color=discord.Color.red()
        )

    guild = bot.get_guild(
        int(row["guild_id"])
    )
    guild_name = (
        guild.name
        if guild
        else f"Server {row['guild_id']}"
    )

    embed = discord.Embed(
        title=f"➕ Request Host Baru #{request_id}",
        description=(
            f"Host Manager <@{row['requester_id']}> meminta menambahkan "
            f"host baru ke **{guild_name}**.\n\n"
            f"Platform: **{platform_display_name(row['platform'])}**\n"
            f"Target: `{row['target']}`\n"
            f"Channel: <#{row['channel_id']}>\n"
            f"Role: {('<@&' + str(row['role_id']) + '>') if row['role_id'] else 'Tidak ada'}\n"
            f"Status: **{str(row['status']).upper()}**"
        ),
        color=(
            discord.Color.orange()
            if row["status"] == "pending"
            else discord.Color.green()
            if row["status"] == "approved"
            else discord.Color.red()
        )
    )
    embed.add_field(
        name="Keamanan",
        value=(
            "Host **belum ditambahkan ke notifier** sampai Pemilik Server "
            "menekan **✅ Setujui**."
        ),
        inline=False
    )
    embed.set_footer(
        text="Hanya Pemilik Server yang dapat menyetujui host baru"
    )
    return embed


def pending_host_creation_requests(
    guild_id: int,
    *,
    requester_id: Optional[int] = None
):
    sql = """
        SELECT *
        FROM host_creation_requests
        WHERE guild_id=? AND status='pending'
    """
    params = [int(guild_id)]

    if requester_id is not None:
        sql += " AND requester_id=?"
        params.append(int(requester_id))

    sql += " ORDER BY id DESC"

    with closing(db()) as conn:
        return conn.execute(
            sql,
            tuple(params)
        ).fetchall()




def server_owner_contact_embed(
    user_id: int,
    guild_ids: list[int]
):
    embed = discord.Embed(
        title="🎙️ Belum Memiliki Host",
        description=(
            "Kamu belum ditugaskan sebagai Host Manager.\n\n"
            "Pilih **server tempat host berada**, lalu kamu bisa melihat "
            "**pemilik server** atau mengirim **permintaan akses Host Manager** "
            "langsung kepadanya.\n\n"
            "ℹ️ Yang dimaksud **pemilik server** adalah owner server Discord, "
            "bukan Global Owner Hi Notifku."
        ),
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="Server yang Ditemukan",
        value=str(len(guild_ids)),
        inline=True
    )
    embed.add_field(
        name="Akses /owner",
        value="❌ Tidak ada",
        inline=True
    )
    embed.set_footer(
        text="Pilih server terlebih dahulu"
    )
    return embed


class ServerOwnerContactSelect(discord.ui.Select):
    def __init__(
        self,
        user_id: int,
        guild_ids: list[int]
    ):
        self.user_id = int(user_id)
        self.guild_ids = [
            int(x)
            for x in guild_ids
        ]

        options = []
        for guild_id in self.guild_ids[:25]:
            guild = bot.get_guild(guild_id)
            if not guild:
                continue

            options.append(
                discord.SelectOption(
                    label=guild.name[:100],
                    description=(
                        f"{guild_host_count(guild.id)} host • "
                        f"Owner ID {guild.owner_id}"
                    )[:100],
                    value=str(guild.id),
                    emoji="🏢"
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="Tidak ada server mutual",
                    description="Tidak ditemukan server yang sama dengan bot.",
                    value="0",
                    emoji="ℹ️"
                )
            )

        super().__init__(
            placeholder="Pilih server tempat host berada",
            options=options,
            row=0
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "❌ Menu ini bukan milikmu."
            )
            return

        guild_id = int(self.values[0])

        if not guild_id:
            await safe_reply(
                interaction,
                "ℹ️ Tidak ada server yang dapat dipilih."
            )
            return

        if guild_id not in self.guild_ids:
            await safe_reply(
                interaction,
                "🔒 Server tidak tersedia pada menu ini."
            )
            return

        guild = bot.get_guild(guild_id)
        if not guild:
            await safe_reply(
                interaction,
                "❌ Server tidak ditemukan."
            )
            return

        await interaction.response.edit_message(
            embed=selected_server_owner_embed(
                guild,
                self.user_id
            ),
            view=SelectedServerOwnerView(
                self.user_id,
                guild.id,
                self.guild_ids
            )
        )


def selected_server_owner_embed(
    guild: discord.Guild,
    user_id: int
):
    owner = guild.owner
    owner_text = (
        owner.mention
        if owner
        else f"<@{guild.owner_id}>"
    )

    hosts = get_hosts(guild.id)

    embed = discord.Embed(
        title=f"👑 Pemilik Server • {guild.name}",
        description=(
            f"Pemilik server: **{owner_text}**\n"
            f"Server ID: `{guild.id}`\n"
            f"Host tersedia: **{len(hosts)}**\n\n"
            "Tekan **📨 Minta Akses Host** untuk mengirim permintaan "
            "langsung ke pemilik server."
        ),
        color=discord.Color.gold()
    )

    if not hosts:
        embed.add_field(
            name="Belum Ada Host",
            value=(
                "Pemilik server perlu membuat host terlebih dahulu melalui "
                "`/menu → pilih server → Kelola Host → Tambah Host`."
            ),
            inline=False
        )

    embed.set_footer(
        text="Pemilik server Discord • bukan Global Owner bot"
    )
    return embed


class ServerOwnerHostGrantSelect(discord.ui.Select):
    def __init__(
        self,
        request_id: int,
        requester_id: int,
        guild_id: int
    ):
        self.request_id = int(request_id)
        self.requester_id = int(requester_id)
        self.guild_id = int(guild_id)

        hosts = get_hosts(self.guild_id)
        options = []

        for host in hosts[:25]:
            label = (
                host["display_name"]
                or host["target"]
                or f"Host {host['id']}"
            )
            options.append(
                discord.SelectOption(
                    label=(
                        f"{platform_display_name(host['platform'])} • {label}"
                    )[:100],
                    description=f"Host ID {host['id']}"[:100],
                    value=str(host["id"]),
                    emoji=platform_icon(host["platform"])
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="Belum ada host",
                    description="Buat host dulu lalu tekan Setujui kembali.",
                    value="0",
                    emoji="ℹ️"
                )
            )

        super().__init__(
            placeholder="Pilih host yang akan diberikan",
            options=options,
            row=0
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        guild = await require_server_owner(
            interaction,
            self.guild_id
        )
        if not guild:
            return

        request = get_server_host_access_request(
            self.request_id
        )

        if (
            not request
            or request["status"] != "pending"
            or int(request["guild_id"]) != self.guild_id
            or int(request["user_id"]) != self.requester_id
        ):
            await safe_reply(
                interaction,
                "ℹ️ Request sudah diproses atau tidak valid."
            )
            return

        host_id = int(self.values[0])

        if not host_id:
            await safe_reply(
                interaction,
                (
                    "ℹ️ Server belum mempunyai host.\n"
                    "Buat host melalui `/menu → pilih server → Kelola Host → "
                    "Tambah Host`, lalu tekan **Setujui** lagi pada request."
                )
            )
            return

        host = get_host(host_id)

        if (
            not host
            or int(host["guild_id"]) != self.guild_id
        ):
            await safe_reply(
                interaction,
                "❌ Host bukan milik server ini."
            )
            return

        assign_host_manager(
            host_id,
            self.requester_id,
            assigned_by=interaction.user.id,
            permissions=set(HOST_MANAGER_PERMISSION_COLUMNS)
        )

        finish_server_host_access_request(
            self.request_id,
            status="approved",
            actor_id=interaction.user.id,
            host_id=host_id
        )

        log_host_manager_action(
            host_id,
            self.requester_id,
            "approved_by_server_owner",
            f"server_owner_id={interaction.user.id}"
        )

        try:
            requester = (
                bot.get_user(self.requester_id)
                or await bot.fetch_user(self.requester_id)
            )
            await requester.send(
                embed=discord.Embed(
                    title="✅ Akses Host Disetujui",
                    description=(
                        f"Pemilik server **{guild.name}** menyetujui aksesmu ke:\n"
                        f"**{platform_display_name(host['platform'])} • "
                        f"{host['display_name'] or host['target']}**\n\n"
                        "Buka `/menu → 🎙️ Host Saya`."
                    ),
                    color=discord.Color.green()
                )
            )
        except Exception:
            pass

        await interaction.response.edit_message(
            content=(
                f"✅ Request **#{self.request_id}** disetujui.\n"
                f"<@{self.requester_id}> sekarang menjadi Host Manager untuk "
                f"**{platform_display_name(host['platform'])} • "
                f"{host['display_name'] or host['target']}**."
            ),
            embed=None,
            view=None
        )


class ServerOwnerHostGrantView(discord.ui.View):
    def __init__(
        self,
        request_id: int,
        requester_id: int,
        guild_id: int
    ):
        super().__init__(timeout=900)
        self.request_id = int(request_id)
        self.requester_id = int(requester_id)
        self.guild_id = int(guild_id)

        self.add_item(
            ServerOwnerHostGrantSelect(
                self.request_id,
                self.requester_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Kembali ke Request",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        guild = await require_server_owner(
            interaction,
            self.guild_id
        )
        if not guild:
            return

        request = get_server_host_access_request(
            self.request_id
        )

        await interaction.response.edit_message(
            embed=server_host_access_request_embed(
                self.request_id
            ),
            view=(
                ServerOwnerAccessRequestView(
                    self.request_id,
                    self.requester_id,
                    self.guild_id
                )
                if request and request["status"] == "pending"
                else None
            )
        )


class ServerOwnerAccessRequestView(discord.ui.View):
    def __init__(
        self,
        request_id: int,
        requester_id: int,
        guild_id: int
    ):
        super().__init__(timeout=None)
        self.request_id = int(request_id)
        self.requester_id = int(requester_id)
        self.guild_id = int(guild_id)
        self.approve.custom_id = f"hin:server_access:{self.request_id}:approve"
        self.deny.custom_id = f"hin:server_access:{self.request_id}:deny"

    async def valid(
        self,
        interaction: discord.Interaction
    ):
        guild = await require_server_owner(
            interaction,
            self.guild_id
        )
        if not guild:
            return None

        request = get_server_host_access_request(
            self.request_id
        )

        if (
            not request
            or request["status"] != "pending"
            or int(request["guild_id"]) != self.guild_id
            or int(request["user_id"]) != self.requester_id
        ):
            await safe_reply(
                interaction,
                "ℹ️ Request sudah diproses atau tidak valid."
            )
            return None

        return guild

    @discord.ui.button(
        label="Setujui",
        emoji="✅",
        style=discord.ButtonStyle.success,
        row=0
    )
    async def approve(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        guild = await self.valid(interaction)
        if not guild:
            return

        if action_rate_limited(
            interaction.user.id,
            f"approve_server_manager:{self.request_id}"
        ):
            await safe_reply(
                interaction,
                "⏳ Request sedang diproses. Jangan tekan dua kali."
            )
            return

        if not claim_server_access_request(
            self.request_id,
            interaction.user.id
        ):
            await safe_reply(
                interaction,
                "ℹ️ Request sedang atau sudah diproses."
            )
            return

        try:
            grant_server_host_manager(
                self.guild_id,
                self.requester_id,
                interaction.user.id
            )

            if not finish_server_host_access_request(
                self.request_id,
                status="approved",
                actor_id=interaction.user.id
            ):
                raise RuntimeError(
                    "Finalisasi request akses gagal."
                )
        except Exception:
            reset_server_access_request_claim(
                self.request_id
            )
            raise

        try:
            requester = (
                bot.get_user(self.requester_id)
                or await bot.fetch_user(
                    self.requester_id
                )
            )
            await requester.send(
                embed=discord.Embed(
                    title="✅ Akses Host Manager Disetujui",
                    description=(
                        f"Pemilik server **{guild.name}** telah menyetujui "
                        "akses Host Manager-mu.\n\n"
                        "Sekarang buka:\n"
                        "`/menu → 🎙️ Host Manager → pilih server`\n\n"
                        "Kamu dapat **mengajukan host baru**, tetapi setiap host "
                        "baru tetap wajib disetujui Pemilik Server sebelum aktif."
                    ),
                    color=discord.Color.green()
                )
            )
        except Exception:
            pass

        await interaction.response.edit_message(
            content=(
                f"✅ Request **#{self.request_id}** disetujui.\n"
                f"<@{self.requester_id}> sekarang memiliki akses "
                f"**Host Manager** ke server **{guild.name}**.\n"
                "Host baru yang diajukan tetap membutuhkan persetujuanmu."
            ),
            embed=None,
            view=None
        )

    @discord.ui.button(
        label="Tolak",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        row=0
    )
    async def deny(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        guild = await self.valid(interaction)
        if not guild:
            return

        if action_rate_limited(
            interaction.user.id,
            f"deny_server_manager:{self.request_id}"
        ):
            await safe_reply(
                interaction,
                "⏳ Request sedang diproses. Jangan tekan dua kali."
            )
            return

        if not claim_server_access_request(
            self.request_id,
            interaction.user.id
        ):
            await safe_reply(
                interaction,
                "ℹ️ Request sedang atau sudah diproses."
            )
            return

        finish_server_host_access_request(
            self.request_id,
            status="denied",
            actor_id=interaction.user.id
        )

        try:
            requester = (
                bot.get_user(self.requester_id)
                or await bot.fetch_user(self.requester_id)
            )
            await requester.send(
                f"❌ Permintaan Host Manager **#{self.request_id}** untuk "
                f"server **{guild.name}** ditolak oleh pemilik server."
            )
        except Exception:
            pass

        await interaction.response.edit_message(
            content=f"❌ Request **#{self.request_id}** ditolak.",
            embed=None,
            view=None
        )



class SelectedServerOwnerView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        guild_id: int,
        guild_ids: list[int]
    ):
        super().__init__(timeout=900)
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)
        self.guild_ids = [
            int(x)
            for x in guild_ids
        ]

    async def valid(
        self,
        interaction: discord.Interaction
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "❌ Menu ini bukan milikmu."
            )
            return None

        if self.guild_id not in self.guild_ids:
            await safe_reply(
                interaction,
                "🔒 Server tidak tersedia."
            )
            return None

        guild = bot.get_guild(self.guild_id)
        if not guild:
            await safe_reply(
                interaction,
                "❌ Server tidak ditemukan."
            )
            return None

        return guild

    @discord.ui.button(
        label="Pemilik Server",
        emoji="👑",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def server_owner(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        guild = await self.valid(interaction)
        if not guild:
            return

        owner = guild.owner
        owner_name = (
            str(owner)
            if owner
            else f"User ID {guild.owner_id}"
        )

        await safe_reply(
            interaction,
            (
                f"👑 Pemilik **{guild.name}** adalah "
                f"<@{guild.owner_id}> (`{owner_name}`).\n"
                "Tekan mention tersebut untuk membuka profil Discord pemilik server."
            )
        )

    @discord.ui.button(
        label="Minta Akses Host",
        emoji="📨",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def request_access(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        guild = await self.valid(interaction)
        if not guild:
            return

        request_id = create_server_host_access_request(
            guild.id,
            self.user_id
        )

        try:
            owner = (
                guild.owner
                or await bot.fetch_user(int(guild.owner_id))
            )

            await owner.send(
                embed=server_host_access_request_embed(
                    request_id
                ),
                view=ServerOwnerAccessRequestView(
                    request_id,
                    self.user_id,
                    guild.id
                )
            )
            sent = True
        except Exception:
            sent = False

        if sent:
            await safe_reply(
                interaction,
                (
                    f"✅ Request **#{request_id}** sudah dikirim ke "
                    f"**Pemilik Server** <@{guild.owner_id}>.\n"
                    "Owner server dapat menekan **✅ Setujui** atau **❌ Tolak**."
                )
            )
        else:
            await safe_reply(
                interaction,
                (
                    f"⚠️ Request **#{request_id}** sudah tersimpan, tetapi bot "
                    f"tidak dapat mengirim DM ke Pemilik Server <@{guild.owner_id}>.\n"
                    "Kemungkinan DM owner tertutup."
                )
            )

    @discord.ui.button(
        label="Pilih Server Lain",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "❌ Menu ini bukan milikmu."
            )
            return

        await interaction.response.edit_message(
            embed=server_owner_contact_embed(
                self.user_id,
                self.guild_ids
            ),
            view=ServerOwnerContactView(
                self.user_id,
                self.guild_ids
            )
        )


class ServerOwnerContactView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        guild_ids: list[int]
    ):
        super().__init__(timeout=900)
        self.user_id = int(user_id)
        self.guild_ids = [
            int(x)
            for x in guild_ids
        ]
        self.add_item(
            ServerOwnerContactSelect(
                self.user_id,
                self.guild_ids
            )
        )



class MenuRoleChoiceView(discord.ui.View):
    """
    /menu root.
    Pemilik Server and Host Manager are deliberately separated.
    Global Owner Bot remains exclusively on /owner.
    """
    def __init__(self, user_id: int):
        super().__init__(timeout=900)
        self.user_id = int(user_id)

    async def valid_user(
        self,
        interaction: discord.Interaction
    ) -> bool:
        if int(interaction.user.id) != self.user_id:
            await safe_reply(
                interaction,
                "❌ Menu ini bukan milikmu."
            )
            return False
        return True

    @discord.ui.button(
        label="Pemilik Server",
        emoji="👑",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def server_owner_menu(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid_user(interaction):
            return

        guilds = user_owned_guilds(self.user_id)

        if not guilds:
            await safe_reply(
                interaction,
                (
                    "ℹ️ Kamu tidak terdeteksi sebagai **Pemilik Server** "
                    "pada server yang memakai Hi Notifku."
                )
            )
            return

        await interaction.response.edit_message(
            embed=server_owner_menu_home_embed(
                self.user_id
            ),
            view=DMUserGuildPickerView(
                self.user_id,
                0
            )
        )

    @discord.ui.button(
        label="Host Manager",
        emoji="🎙️",
        style=discord.ButtonStyle.success,
        row=0
    )
    async def host_manager_menu(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid_user(interaction):
            return

        managed_guilds = host_manager_guild_ids(
            self.user_id
        )

        if managed_guilds:
            await interaction.response.edit_message(
                embed=host_manager_home_embed(
                    self.user_id
                ),
                view=HostManagerHomeView(
                    self.user_id
                )
            )
            return

        # No Host Manager assignment yet: offer server-owner contact flow.
        mutual = await user_mutual_guilds(
            self.user_id
        )
        guild_ids = [
            int(guild.id)
            for guild in mutual
        ]

        if not guild_ids:
            await safe_reply(
                interaction,
                (
                    "ℹ️ Kamu belum memiliki akses **Host Manager** dan "
                    "tidak ditemukan server mutual yang memakai Hi Notifku."
                )
            )
            return

        await interaction.response.edit_message(
            embed=server_owner_contact_embed(
                self.user_id,
                guild_ids
            ),
            view=ServerOwnerContactView(
                self.user_id,
                guild_ids
            )
        )


    @discord.ui.button(
        label="Premium",
        emoji="⭐",
        style=discord.ButtonStyle.primary,
        row=1
    )
    async def premium_menu(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid_user(interaction):
            return

        guild_ids = premium_purchase_guild_ids(self.user_id)
        if not guild_ids:
            await safe_reply(
                interaction,
                (
                    "ℹ️ Premium dapat dibeli oleh **Pemilik Server** atau "
                    "**Host Manager aktif**.\n"
                    "Kamu belum memiliki server yang memenuhi akses tersebut."
                )
            )
            return

        await interaction.response.edit_message(
            embed=premium_purchase_home_embed(self.user_id),
            view=PremiumGuildPickerView(self.user_id)
        )


def server_owner_menu_home_embed(
    user_id: int
):
    guilds = user_owned_guilds(user_id)

    embed = discord.Embed(
        title="👑 Pemilik Server",
        description=(
            "Pilih server yang **kamu miliki** untuk mengatur plan dan host.\n"
            "Menu ini hanya berlaku pada server milikmu."
        ),
        color=discord.Color.gold()
    )
    embed.add_field(
        name="Server Milikmu",
        value=str(len(guilds)),
        inline=True
    )
    embed.add_field(
        name="Akses",
        value="👑 Pemilik Server",
        inline=True
    )
    embed.add_field(
        name="Global Owner Bot",
        value="❌ Gunakan `/owner` secara terpisah",
        inline=False
    )
    embed.set_footer(
        text="Pemilik Server • tidak memiliki akses Global Owner Bot"
    )
    return embed



class DMUserGuildSelect(discord.ui.Select):
    def __init__(self, user_id: int, page: int = 0):
        self.user_id = int(user_id)
        self.page = max(0, int(page))

        guilds = user_owned_guilds(self.user_id)
        start = self.page * 25
        current = guilds[start:start + 25]

        options = [
            discord.SelectOption(
                label=g.name[:100],
                value=str(g.id),
                description=f"Server ID: {g.id}"[:100]
            )
            for g in current
        ]

        if not options:
            options = [
                discord.SelectOption(
                    label="Tidak ada server milikmu",
                    value="0",
                    description="Bot harus sudah terpasang di server milikmu."
                )
            ]

        super().__init__(
            placeholder=f"Pilih server • Halaman {self.page + 1}",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "❌ Menu ini bukan milikmu."
            )
            return

        guild_id = int(self.values[0])

        if guild_id == 0:
            await safe_reply(
                interaction,
                "ℹ️ Tidak ada server milikmu yang sedang memakai Hi Notifku."
            )
            return

        guild = bot.get_guild(guild_id)

        if guild is None or int(guild.owner_id) != interaction.user.id:
            await safe_reply(
                interaction,
                "❌ Server tidak ditemukan atau kamu bukan owner server tersebut."
            )
            return

        await interaction.response.edit_message(
            embed=user_server_embed(guild),
            view=UserServerMenuView(guild.id)
        )


class DMUserGuildPickerView(discord.ui.View):
    def __init__(self, user_id: int, page: int = 0):
        super().__init__(timeout=900)
        self.user_id = int(user_id)
        self.page = max(0, int(page))
        self.add_item(DMUserGuildSelect(self.user_id, self.page))

    @discord.ui.button(
        label="Sebelumnya",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Menu ini bukan milikmu.")
            return

        await interaction.response.edit_message(
            view=DMUserGuildPickerView(
                self.user_id,
                max(0, self.page - 1)
            )
        )

    @discord.ui.button(
        label="Berikutnya",
        emoji="➡️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Menu ini bukan milikmu.")
            return

        guilds = user_owned_guilds(self.user_id)
        max_page = max(0, (len(guilds) - 1) // 25)

        await interaction.response.edit_message(
            view=DMUserGuildPickerView(
                self.user_id,
                min(max_page, self.page + 1)
            )
        )


    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Menu ini bukan milikmu.")
            return

        await interaction.response.edit_message(
            embed=dm_menu_home_embed(self.user_id),
            view=MenuRoleChoiceView(self.user_id)
        )


def dm_menu_home_embed(user_id: int):
    owned_guilds = user_owned_guilds(user_id)
    managed_hosts = host_manager_rows(user_id)
    managed_guilds = host_manager_guild_ids(user_id)

    owner_status = (
        f"✅ {len(owned_guilds)} server"
        if owned_guilds
        else "❌ Tidak ada"
    )
    host_status = (
        f"✅ {len(managed_guilds)} server • {len(managed_hosts)} host"
        if managed_guilds
        else "❌ Belum ada akses"
    )

    embed = discord.Embed(
        title="📩 Hi Notifku • Pilih Akses",
        description=(
            "Pilih menu sesuai kebutuhanmu.\n\n"
            "👑 **Pemilik Server** — kelola server sendiri.\n"
            "🎙️ **Host Manager** — kelola host yang diberikan.\n"
            "⭐ **Premium** — beli/perpanjang Premium untuk server yang kamu kelola.\n\n"
            "🛡️ Global Owner Bot tetap khusus `/owner`."
        ),
        color=discord.Color.blue()
    )
    embed.add_field(
        name="👑 Pemilik Server",
        value=owner_status,
        inline=True
    )
    embed.add_field(
        name="🎙️ Host Manager",
        value=host_status,
        inline=True
    )
    embed.set_footer(
        text="/menu • Server Owner • Host Manager • Premium"
    )
    return embed


def premium_purchase_home_embed(user_id: int):
    guild_ids = premium_purchase_guild_ids(user_id)
    premium_count = sum(
        1 for guild_id in guild_ids
        if premium_access_effective(guild_id)
    )
    embed = discord.Embed(
        title="⭐ Premium Hi Notifku",
        description=(
            "Pilih server untuk membeli atau memperpanjang Premium.\n"
            "**Pemilik Server dan Host Manager aktif dapat melakukan pembayaran.**\n\n"
            "Premium aktif untuk **seluruh server**, bukan hanya host atau akun pembeli."
        ),
        color=discord.Color.gold()
    )
    embed.add_field(
        name="Server tersedia",
        value=str(len(guild_ids)),
        inline=True
    )
    embed.add_field(
        name="Premium aktif",
        value=str(premium_count),
        inline=True
    )
    embed.add_field(
        name="Paket",
        value=premium_packages_text()[:1024],
        inline=False
    )
    embed.set_footer(text="Pilih server • pembayaran tidak mengubah hak akses Host Manager")
    return embed


class PremiumGuildSelect(discord.ui.Select):
    def __init__(self, user_id: int):
        self.user_id = int(user_id)
        guild_ids = premium_purchase_guild_ids(self.user_id)[:25]
        options = []
        for guild_id in guild_ids:
            guild = bot.get_guild(guild_id)
            if not guild:
                continue
            active = premium_access_effective(guild_id)
            role = premium_purchase_role_label(self.user_id, guild_id)
            options.append(
                discord.SelectOption(
                    label=guild.name[:100],
                    value=str(guild_id),
                    description=(
                        f"{role} • {'PREMIUM' if active else 'FREE'}"
                    )[:100],
                    emoji="⭐" if active else "🆓"
                )
            )

        if not options:
            options = [
                discord.SelectOption(
                    label="Tidak ada server tersedia",
                    value="0",
                    emoji="ℹ️"
                )
            ]

        super().__init__(
            placeholder="Pilih server untuk Premium",
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Menu ini bukan milikmu.")
            return

        guild_id = int(self.values[0])
        if not guild_id:
            await safe_reply(interaction, "ℹ️ Tidak ada server yang dapat dipilih.")
            return

        guild = await require_premium_purchaser(interaction, guild_id)
        if not guild:
            return

        await interaction.response.edit_message(
            embed=premium_plan_summary_embed(guild),
            view=UserPremiumView(guild_id, self.user_id)
        )


class PremiumGuildPickerView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=900)
        self.user_id = int(user_id)
        self.add_item(PremiumGuildSelect(self.user_id))

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(self, interaction, button):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Menu ini bukan milikmu.")
            return

        # Host-only users return to Host Manager; mixed/owner users return to /menu.
        if host_manager_guild_ids(self.user_id) and not user_owned_guilds(self.user_id):
            await interaction.response.edit_message(
                embed=host_manager_home_embed(self.user_id),
                view=HostManagerHomeView(self.user_id)
            )
            return

        await interaction.response.edit_message(
            embed=dm_menu_home_embed(self.user_id),
            view=MenuRoleChoiceView(self.user_id)
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def home(self, interaction, button):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Menu ini bukan milikmu.")
            return
        await interaction.response.edit_message(
            embed=dm_menu_home_embed(self.user_id),
            view=MenuRoleChoiceView(self.user_id)
        )


def pending_server_access_requests(
    guild_id: int
):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT *
            FROM server_host_access_requests
            WHERE guild_id=? AND status='pending'
            ORDER BY id DESC
        """, (
            int(guild_id),
        )).fetchall()


def server_owner_requests_embed(
    guild_id: int
):
    access_rows = pending_server_access_requests(
        guild_id
    )
    host_rows = pending_host_creation_requests(
        guild_id
    )
    guild = bot.get_guild(int(guild_id))
    name = guild.name if guild else f"Server {guild_id}"

    embed = discord.Embed(
        title=f"📨 Request Server • {name}",
        description=(
            "Semua request yang menunggu persetujuan Pemilik Server "
            "dikumpulkan di satu tempat."
        ),
        color=discord.Color.orange()
    )
    embed.add_field(
        name="🎙️ Akses Host Manager",
        value=str(len(access_rows)),
        inline=True
    )
    embed.add_field(
        name="➕ Host Baru",
        value=str(len(host_rows)),
        inline=True
    )
    embed.add_field(
        name="Keamanan",
        value=(
            "Request hanya dapat diproses oleh **Pemilik Server** ini. "
            "Global Owner Bot tidak diperlukan."
        ),
        inline=False
    )
    return embed


class ServerOwnerPendingAccessSelect(discord.ui.Select):
    def __init__(
        self,
        user_id: int,
        guild_id: int,
        page: int = 0
    ):
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)
        self.page = max(0, int(page))

        rows = pending_server_access_requests(
            self.guild_id
        )
        start = self.page * 25
        current = rows[start:start + 25]

        options = [
            discord.SelectOption(
                label=f"Request #{row['id']} • User {row['user_id']}"[:100],
                description=f"pending • <@{row['user_id']}>"[:100],
                value=str(row["id"]),
                emoji="🎙️"
            )
            for row in current
        ]

        if not options:
            options.append(
                discord.SelectOption(
                    label="Tidak ada request akses",
                    description="Tidak ada request pada halaman ini.",
                    value="0",
                    emoji="✅"
                )
            )

        super().__init__(
            placeholder=f"Request akses • Halaman {self.page + 1}",
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "❌ Menu ini bukan milikmu.")
            return

        guild = await require_server_owner(
            interaction,
            self.guild_id
        )
        if not guild:
            return

        request_id = int(self.values[0])
        if not request_id:
            await safe_reply(
                interaction,
                "ℹ️ Tidak ada request akses pada halaman ini."
            )
            return

        row = get_server_host_access_request(
            request_id
        )
        if (
            not row
            or row["status"] != "pending"
            or int(row["guild_id"]) != self.guild_id
        ):
            await safe_reply(
                interaction,
                "ℹ️ Request sudah diproses atau tidak valid."
            )
            return

        await interaction.response.edit_message(
            embed=server_host_access_request_embed(
                request_id
            ),
            view=ServerOwnerAccessRequestView(
                request_id,
                int(row["user_id"]),
                self.guild_id
            )
        )


class ServerOwnerPendingHostSelect(discord.ui.Select):
    def __init__(
        self,
        user_id: int,
        guild_id: int,
        page: int = 0
    ):
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)
        self.page = max(0, int(page))

        rows = pending_host_creation_requests(
            self.guild_id
        )
        start = self.page * 25
        current = rows[start:start + 25]

        options = [
            discord.SelectOption(
                label=(
                    f"#{row['id']} • "
                    f"{platform_display_name(row['platform'])} • {row['target']}"
                )[:100],
                description=f"Requester {row['requester_id']} • pending"[:100],
                value=str(row["id"]),
                emoji=platform_icon(row["platform"])
            )
            for row in current
        ]

        if not options:
            options.append(
                discord.SelectOption(
                    label="Tidak ada request host",
                    description="Tidak ada request pada halaman ini.",
                    value="0",
                    emoji="✅"
                )
            )

        super().__init__(
            placeholder=f"Request host baru • Halaman {self.page + 1}",
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "❌ Menu ini bukan milikmu.")
            return

        guild = await require_server_owner(
            interaction,
            self.guild_id
        )
        if not guild:
            return

        request_id = int(self.values[0])
        if not request_id:
            await safe_reply(
                interaction,
                "ℹ️ Tidak ada request host pada halaman ini."
            )
            return

        row = get_host_creation_request(
            request_id
        )
        if (
            not row
            or row["status"] != "pending"
            or int(row["guild_id"]) != self.guild_id
        ):
            await safe_reply(
                interaction,
                "ℹ️ Request sudah diproses atau tidak valid."
            )
            return

        await interaction.response.edit_message(
            embed=host_creation_request_embed(
                request_id
            ),
            view=ServerOwnerHostCreationApprovalView(
                request_id,
                self.guild_id,
                int(row["requester_id"])
            )
        )


class ServerOwnerRequestsView(discord.ui.View):
    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=900)
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)

    async def valid(self, interaction: discord.Interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(
                interaction,
                "❌ Menu ini bukan milikmu."
            )
            return None
        return await require_server_owner(
            interaction,
            self.guild_id
        )

    @discord.ui.button(
        label="Akses Manager",
        emoji="🎙️",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def access_requests(self, interaction, button):
        if not await self.valid(interaction):
            return

        await interaction.response.edit_message(
            embed=server_owner_requests_embed(
                self.guild_id
            ),
            view=ServerOwnerAccessRequestsListView(
                self.user_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Host Baru",
        emoji="➕",
        style=discord.ButtonStyle.success,
        row=0
    )
    async def host_requests(self, interaction, button):
        if not await self.valid(interaction):
            return

        await interaction.response.edit_message(
            embed=server_owner_requests_embed(
                self.guild_id
            ),
            view=ServerOwnerHostRequestsListView(
                self.user_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Cari Request",
        emoji="🔎",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def search_request(self, interaction, button):
        if not await self.valid(interaction):
            return

        await interaction.response.send_modal(
            ServerOwnerRequestSearchModal(
                self.user_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def back(self, interaction, button):
        guild = await self.valid(interaction)
        if not guild:
            return

        await interaction.response.edit_message(
            embed=user_server_embed(guild),
            view=UserServerMenuView(
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def home(self, interaction, button):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "❌ Menu ini bukan milikmu.")
            return

        await interaction.response.edit_message(
            embed=dm_menu_home_embed(
                self.user_id
            ),
            view=MenuRoleChoiceView(
                self.user_id
            )
        )


class ServerOwnerAccessRequestsListView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        guild_id: int,
        page: int = 0
    ):
        super().__init__(timeout=900)
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)
        self.page = max(0, int(page))

        self.add_item(
            ServerOwnerPendingAccessSelect(
                self.user_id,
                self.guild_id,
                self.page
            )
        )

    async def valid(self, interaction: discord.Interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "❌ Menu ini bukan milikmu.")
            return False
        return bool(
            await require_server_owner(
                interaction,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Sebelumnya",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def previous(self, interaction, button):
        if not await self.valid(interaction):
            return

        await interaction.response.edit_message(
            embed=server_owner_requests_embed(
                self.guild_id
            ),
            view=ServerOwnerAccessRequestsListView(
                self.user_id,
                self.guild_id,
                max(0, self.page - 1)
            )
        )

    @discord.ui.button(
        label="Berikutnya",
        emoji="➡️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def next_page(self, interaction, button):
        if not await self.valid(interaction):
            return

        total = len(
            pending_server_access_requests(
                self.guild_id
            )
        )
        max_page = max(0, (total - 1) // 25)

        await interaction.response.edit_message(
            embed=server_owner_requests_embed(
                self.guild_id
            ),
            view=ServerOwnerAccessRequestsListView(
                self.user_id,
                self.guild_id,
                min(max_page, self.page + 1)
            )
        )

    @discord.ui.button(
        label="Kembali ke Request",
        emoji="↩️",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def back(self, interaction, button):
        if not await self.valid(interaction):
            return

        await interaction.response.edit_message(
            embed=server_owner_requests_embed(
                self.guild_id
            ),
            view=ServerOwnerRequestsView(
                self.user_id,
                self.guild_id
            )
        )


class ServerOwnerHostRequestsListView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        guild_id: int,
        page: int = 0
    ):
        super().__init__(timeout=900)
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)
        self.page = max(0, int(page))

        self.add_item(
            ServerOwnerPendingHostSelect(
                self.user_id,
                self.guild_id,
                self.page
            )
        )

    async def valid(self, interaction: discord.Interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "❌ Menu ini bukan milikmu.")
            return False
        return bool(
            await require_server_owner(
                interaction,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Sebelumnya",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def previous(self, interaction, button):
        if not await self.valid(interaction):
            return

        await interaction.response.edit_message(
            embed=server_owner_requests_embed(
                self.guild_id
            ),
            view=ServerOwnerHostRequestsListView(
                self.user_id,
                self.guild_id,
                max(0, self.page - 1)
            )
        )

    @discord.ui.button(
        label="Berikutnya",
        emoji="➡️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def next_page(self, interaction, button):
        if not await self.valid(interaction):
            return

        total = len(
            pending_host_creation_requests(
                self.guild_id
            )
        )
        max_page = max(0, (total - 1) // 25)

        await interaction.response.edit_message(
            embed=server_owner_requests_embed(
                self.guild_id
            ),
            view=ServerOwnerHostRequestsListView(
                self.user_id,
                self.guild_id,
                min(max_page, self.page + 1)
            )
        )

    @discord.ui.button(
        label="Kembali ke Request",
        emoji="↩️",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def back(self, interaction, button):
        if not await self.valid(interaction):
            return

        await interaction.response.edit_message(
            embed=server_owner_requests_embed(
                self.guild_id
            ),
            view=ServerOwnerRequestsView(
                self.user_id,
                self.guild_id
            )
        )


class ServerOwnerRequestSearchModal(discord.ui.Modal):
    query = discord.ui.TextInput(
        label="Cari Request",
        placeholder="ID request, user ID, username target, atau platform",
        max_length=120
    )

    def __init__(self, user_id: int, guild_id: int):
        super().__init__(
            title="Cari Request Server",
            timeout=300
        )
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)

    async def on_submit(self, interaction: discord.Interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "❌ Form ini bukan milikmu.")
            return

        guild = await require_server_owner(
            interaction,
            self.guild_id
        )
        if not guild:
            return

        q = self.query.value.strip().lower()

        access_rows = [
            row
            for row in pending_server_access_requests(self.guild_id)
            if (
                q in str(row["id"]).lower()
                or q in str(row["user_id"]).lower()
            )
        ]

        host_rows = [
            row
            for row in pending_host_creation_requests(self.guild_id)
            if (
                q in str(row["id"]).lower()
                or q in str(row["requester_id"]).lower()
                or q in str(row["platform"]).lower()
                or q in str(row["target"]).lower()
            )
        ]

        lines = []

        for row in access_rows[:10]:
            lines.append(
                f"🎙️ **Akses #{row['id']}** • User `{row['user_id']}`"
            )

        for row in host_rows[:10]:
            lines.append(
                f"➕ **Host #{row['id']}** • "
                f"{platform_display_name(row['platform'])} • `{row['target']}`"
            )

        await safe_reply(
            interaction,
            "",
            embed=discord.Embed(
                title="🔎 Hasil Pencarian Request",
                description=(
                    "\n".join(lines)
                    if lines
                    else f"Tidak ditemukan request pending untuk `{q}`."
                ),
                color=discord.Color.blurple()
            )
        )



class ServerOwnerDeleteHostConfirmView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        host_id: int
    ):
        super().__init__(timeout=120)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.host_id = int(host_id)

    @discord.ui.button(
        label="Ya, Hapus Host",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        row=0
    )
    async def confirm(self, interaction, button):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "❌ Menu ini bukan milikmu.")
            return

        guild = await require_server_owner(
            interaction,
            self.guild_id
        )
        if not guild:
            return

        if action_rate_limited(
            interaction.user.id,
            f"delete_host_confirm:{self.host_id}"
        ):
            await safe_reply(
                interaction,
                "⏳ Aksi sedang diproses. Jangan tekan dua kali."
            )
            return

        host = get_host_for_server_owner(
            self.guild_id,
            self.host_id,
            interaction.user.id
        )
        if not host:
            await safe_reply(
                interaction,
                "ℹ️ Host sudah dihapus atau tidak ditemukan."
            )
            return

        label = host["display_name"] or host["target"]
        delete_host(
            self.host_id
        )

        await log_action(
            self.guild_id,
            interaction.user.id,
            "Server Owner Hapus Host",
            f"{platform_display_name(host['platform'])} {label}"
        )

        await interaction.response.edit_message(
            embed=user_server_hosts_embed(
                guild
            ),
            view=UserServerHostsView(
                self.guild_id,
                self.user_id
            )
        )

    @discord.ui.button(
        label="Batal",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def cancel(self, interaction, button):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "❌ Menu ini bukan milikmu.")
            return

        host = get_host_for_server_owner(
            self.guild_id,
            self.host_id,
            interaction.user.id
        )
        if not host:
            await safe_reply(
                interaction,
                "ℹ️ Host tidak ditemukan."
            )
            return

        await interaction.response.edit_message(
            embed=user_server_host_detail_embed(
                host
            ),
            view=UserServerHostCardView(
                self.guild_id,
                self.user_id,
                self.host_id
            )
        )



class UserPremiumPackageSelect(discord.ui.Select):
    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        renewal = premium_access_effective(self.guild_id)

        options = [
            discord.SelectOption(
                label=f"{days} hari • {rupiah(price)}"[:100],
                description="Perpanjang Premium" if renewal else "Aktifkan Premium",
                value=f"{days}:{price}",
                emoji="⭐"
            )
            for days, price in get_premium_packages()[:25]
        ]
        if not options:
            options = [
                discord.SelectOption(
                    label="Belum ada paket",
                    value="0:0",
                    emoji="ℹ️"
                )
            ]
        super().__init__(
            placeholder="Pilih paket Premium",
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Menu ini bukan milikmu.")
            return

        guild = await require_premium_purchaser(interaction, self.guild_id)
        if not guild:
            return

        days_raw, price_raw = self.values[0].split(":", 1)
        days, price = int(days_raw), int(price_raw)

        if days <= 0:
            await safe_reply(interaction, "ℹ️ Belum ada paket Premium.")
            return

        if (days, price) not in get_premium_packages():
            await safe_reply(interaction, "⚠️ Paket berubah. Buka ulang menu Premium.")
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⭐ Konfirmasi Premium",
                description=(
                    f"Server: **{guild.name}**\n"
                    f"Paket: **{days} hari**\n"
                    f"Harga: **{rupiah(price)}**\n\n"
                    "Lanjutkan untuk membuat invoice pembayaran."
                ),
                color=discord.Color.gold()
            ),
            view=UserPremiumConfirmView(
                self.guild_id,
                self.user_id,
                days,
                price
            )
        )


class UserPremiumView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.add_item(UserPremiumPackageSelect(self.guild_id, self.user_id))

    async def valid(self, interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Menu ini bukan milikmu.")
            return None
        return await require_premium_purchaser(interaction, self.guild_id)

    @discord.ui.button(label="Riwayat", emoji="🧾", style=discord.ButtonStyle.secondary, row=1)
    async def history(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=user_premium_history_embed(self.user_id, self.guild_id),
            view=UserPremiumHistoryView(self.guild_id, self.user_id)
        )

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def refresh(self, interaction, button):
        guild = await self.valid(interaction)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=premium_plan_summary_embed(guild),
            view=UserPremiumView(self.guild_id, self.user_id)
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction, button):
        guild = await self.valid(interaction)
        if not guild:
            return
        if is_server_owner(self.user_id, self.guild_id):
            await interaction.response.edit_message(
                embed=user_server_embed(guild),
                view=UserServerMenuView(self.guild_id)
            )
        else:
            await interaction.response.edit_message(
                embed=premium_purchase_home_embed(self.user_id),
                view=PremiumGuildPickerView(self.user_id)
            )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=2)
    async def home(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=dm_menu_home_embed(self.user_id),
            view=MenuRoleChoiceView(self.user_id)
        )


class UserPremiumHistoryView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction, button):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Menu ini bukan milikmu.")
            return
        guild = await require_premium_purchaser(interaction, self.guild_id)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=premium_plan_summary_embed(guild),
            view=UserPremiumView(self.guild_id, self.user_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=0)
    async def home(self, interaction, button):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Menu ini bukan milikmu.")
            return
        await interaction.response.edit_message(
            embed=dm_menu_home_embed(self.user_id),
            view=MenuRoleChoiceView(self.user_id)
        )


class PremiumPromoModal(discord.ui.Modal):
    code_input = discord.ui.TextInput(
        label="Kode Promo",
        placeholder="Contoh: HINOTIF10",
        max_length=40
    )

    def __init__(
        self,
        guild_id: int,
        user_id: int,
        days: int,
        base_price: int
    ):
        super().__init__(title="Gunakan Promo", timeout=300)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.days = int(days)
        self.base_price = int(base_price)

    async def on_submit(self, interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Form ini bukan milikmu.")
            return

        guild = await require_premium_purchaser(interaction, self.guild_id)
        if not guild:
            return

        code_value = self.code_input.value.strip().upper()

        try:
            final_price, discount = coupon_discount(
                code_value,
                self.base_price
            )
        except Exception as exc:
            await safe_reply(interaction, f"❌ {exc}")
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🎟️ Promo Diterapkan",
                description=(
                    f"Server: **{guild.name if guild else self.guild_id}**\n"
                    f"Paket: **{self.days} hari**\n"
                    f"Harga awal: ~~{rupiah(self.base_price)}~~\n"
                    f"Diskon: **{rupiah(discount)}**\n"
                    f"Total: **{rupiah(final_price)}**"
                ),
                color=discord.Color.green()
            ),
            view=UserPremiumConfirmView(
                self.guild_id,
                self.user_id,
                self.days,
                final_price,
                base_price=self.base_price,
                coupon_code=code_value
            )
        )




class UserPremiumConfirmView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        days: int,
        price: int,
        *,
        base_price: Optional[int] = None,
        coupon_code: Optional[str] = None
    ):
        super().__init__(timeout=180)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.days = int(days)
        self.price = int(price)
        self.base_price = int(
            base_price if base_price is not None else price
        )
        self.coupon_code = coupon_code

    @discord.ui.button(label="Buat Invoice", emoji="✅", style=discord.ButtonStyle.success, row=0)
    async def confirm(self, interaction, button):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Konfirmasi ini bukan milikmu.")
            return

        guild = await require_premium_purchaser(interaction, self.guild_id)
        if not guild:
            return

        if action_rate_limited(
            interaction.user.id,
            f"premium_invoice:{self.guild_id}"
        ):
            await safe_reply(
                interaction,
                "⏳ Tunggu beberapa detik sebelum membuat invoice lagi."
            )
            return

        settings_now = get_guild_settings(self.guild_id)
        if settings_now["maintenance_mode"]:
            await safe_reply(interaction, "🛠️ Premium sedang maintenance.")
            return

        if (self.days, self.base_price) not in get_premium_packages():
            await safe_reply(interaction, "⚠️ Paket berubah. Buka ulang menu Premium.")
            return

        try:
            order_id = create_premium_order(
                guild.id,
                interaction.user.id,
                self.days,
                self.price
            )
        except ValueError as exc:
            await safe_reply(interaction, f"⚠️ {exc}")
            return

        if self.coupon_code:
            try:
                final_price, discount = redeem_coupon_atomic(
                    order_id,
                    self.coupon_code,
                    user_id=interaction.user.id,
                    guild_id=guild.id,
                    base_price=self.base_price
                )
            except ValueError as exc:
                await safe_reply(interaction, f"❌ Promo gagal: {exc}")
                return

            if final_price != int(self.price):
                await safe_reply(
                    interaction,
                    "⚠️ Nilai promo berubah. Buka ulang invoice Premium."
                )
                return

            record_premium_event(
                order_id,
                "promo_applied",
                actor_id=interaction.user.id,
                detail=f"{self.coupon_code} • diskon {rupiah(discount)}"
            )

        await notify_primary_owners_premium_request(
            guild,
            interaction.user,
            self.days,
            self.price,
            order_id
        )

        order = get_premium_order(order_id)
        methods = list_payment_methods(True)

        if not methods:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title=f"✅ Invoice #{order_id} Dibuat",
                    description=(
                        "Metode pembayaran belum tersedia. "
                        "Invoice tersimpan dan owner sudah diberi notifikasi."
                    ),
                    color=discord.Color.orange()
                ),
                view=UserPremiumHistoryView(self.guild_id, self.user_id)
            )
            return

        expected = int(order["expected_amount"] or self.price)
        embed = discord.Embed(
            title=f"💳 {order['invoice_ref'] or ensure_invoice_ref(order_id)}",
            description=(
                f"⭐ **{self.days} hari** • **{rupiah(self.price)}**\n"
                f"Transfer tepat: **{rupiah(expected)}**\n"
                f"Deadline: {invoice_deadline_text(order)}\n\n"
                "Pilih metode pembayaran."
            ),
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(
            embed=embed,
            view=PaymentMethodSelectView(order_id)
        )

    @discord.ui.button(label="Promo", emoji="🎟️", style=discord.ButtonStyle.secondary, row=0)
    async def promo(self, interaction, button):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Konfirmasi ini bukan milikmu.")
            return

        await interaction.response.send_modal(
            PremiumPromoModal(
                self.guild_id,
                self.user_id,
                self.days,
                self.base_price
            )
        )

    @discord.ui.button(label="Batal", emoji="✖️", style=discord.ButtonStyle.secondary, row=0)
    async def cancel(self, interaction, button):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Konfirmasi ini bukan milikmu.")
            return
        guild = await require_premium_purchaser(interaction, self.guild_id)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=premium_plan_summary_embed(guild),
            view=UserPremiumView(self.guild_id, self.user_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction, button):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Konfirmasi ini bukan milikmu.")
            return
        await interaction.response.edit_message(
            embed=dm_menu_home_embed(self.user_id),
            view=MenuRoleChoiceView(self.user_id)
        )


def server_audit_timeline_embed(guild_id: int):
    guild = bot.get_guild(int(guild_id))
    rows = recent_activity(int(guild_id), 15)
    lines = [
        f"• <t:{int(row['created_at'])}:R> **{row['action']}**"
        + (f" — {str(row['detail'])[:120]}" if row["detail"] else "")
        for row in rows
    ]
    return discord.Embed(
        title=f"🧾 Timeline • {guild.name if guild else guild_id}",
        description="\n".join(lines) if lines else "Belum ada aktivitas.",
        color=discord.Color.blurple()
    )


def server_insights_embed(guild_id: int):
    guild = bot.get_guild(int(guild_id))
    entitlements = premium_entitlements(int(guild_id))
    analytics_days = int(entitlements["analytics_days"])
    stats = server_usage_stats(guild_id, analytics_days)
    score = server_health_score(guild_id)

    embed = discord.Embed(
        title=f"📊 Insights • {guild.name if guild else guild_id}",
        description=f"Health Score: **{score}%**",
        color=discord.Color.green() if score >= 80 else discord.Color.orange()
    )
    embed.add_field(
        name=f"{analytics_days} Hari",
        value=(
            f"Notif **{stats['total']}** • ✅ {stats['sent']} • ❌ {stats['failed']}\n"
            f"Latency **{stats['latency']} ms**"
        ),
        inline=False
    )
    embed.add_field(
        name="Plan",
        value=(
            f"⭐ PREMIUM • {premium_expiry_text(guild_id)}"
            if entitlements["premium"]
            else "🆓 FREE • analytics dibatasi 7 hari"
        ),
        inline=False
    )
    return embed


def server_export_bytes(guild_id: int) -> tuple[bytes, bytes]:
    payload = export_guild_backup(int(guild_id))
    json_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2
    ).encode("utf-8")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "host_id", "platform", "target", "display_name",
        "enabled", "error_count", "last_error"
    ])
    for host in get_hosts(int(guild_id)):
        writer.writerow([
            host["id"],
            host["platform"],
            host["target"],
            host["display_name"],
            host["enabled"],
            host["error_count"],
            host["last_error"],
        ])

    return json_bytes, output.getvalue().encode("utf-8-sig")


def platform_control_embed(guild_id: int):
    guild = bot.get_guild(int(guild_id))
    flags = feature_flags_for_guild(guild_id)
    lines = []

    for platform in ["youtube","tiktok","twitch","kick","instagram","facebook"]:
        enabled = platform_enabled(guild_id, platform)
        lines.append(
            f"{'🟢' if enabled else '🔴'} **{platform_display_name(platform)}** — "
            f"{'Aktif' if enabled else 'Maintenance'}"
        )

    return discord.Embed(
        title=f"🌐 Platform • {guild.name if guild else guild_id}",
        description="\n".join(lines),
        color=discord.Color.blurple()
    )


class ServerPlatformSelect(discord.ui.Select):
    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        flags = feature_flags_for_guild(self.guild_id)

        options = []
        for platform in ["youtube","tiktok","twitch","kick","instagram","facebook"]:
            enabled = platform_enabled(self.guild_id, platform)
            options.append(
                discord.SelectOption(
                    label=(
                        f"{platform_display_name(platform)} • "
                        f"{'Aktif' if enabled else 'Maintenance'}"
                    )[:100],
                    value=platform,
                    emoji="🟢" if enabled else "🔴"
                )
            )

        super().__init__(
            placeholder="Pilih platform untuk Aktif/Maintenance",
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Menu ini bukan milikmu.")
            return

        if not await require_server_owner(interaction, self.guild_id):
            return

        platform = self.values[0]
        current = platform_enabled(self.guild_id, platform)

        set_platform_enabled(self.guild_id, platform, not current)
        add_activity(
            self.guild_id,
            interaction.user.id,
            "Platform Maintenance",
            f"{platform}={'aktif' if not current else 'maintenance'}"
        )

        await interaction.response.edit_message(
            embed=platform_control_embed(self.guild_id),
            view=ServerPlatformControlView(
                self.guild_id,
                self.user_id
            )
        )


class ServerPlatformControlView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.add_item(
            ServerPlatformSelect(
                self.guild_id,
                self.user_id
            )
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        guild = await require_server_owner(interaction, self.guild_id)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=user_server_embed(guild),
            view=UserServerMenuView(self.guild_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction, button):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Menu ini bukan milikmu.")
            return
        await interaction.response.edit_message(
            embed=dm_menu_home_embed(self.user_id),
            view=MenuRoleChoiceView(self.user_id)
        )


class ServerInsightsView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)

    async def valid(self, interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Menu ini bukan milikmu.")
            return None
        return await require_server_owner(interaction, self.guild_id)

    @discord.ui.button(label="Timeline", emoji="🧾", style=discord.ButtonStyle.secondary, row=0)
    async def timeline(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=server_audit_timeline_embed(self.guild_id),
            view=ServerInsightsView(self.guild_id, self.user_id)
        )

    @discord.ui.button(label="Export", emoji="📤", style=discord.ButtonStyle.primary, row=0)
    async def export(self, interaction, button):
        if not await self.valid(interaction):
            return
        if not await require_premium_feature(
            interaction, self.guild_id, "data_export", "Export data server"
        ):
            return
        json_bytes, csv_bytes = server_export_bytes(self.guild_id)
        await interaction.response.send_message(
            content="📤 Export server.",
            files=[
                discord.File(
                    io.BytesIO(json_bytes),
                    filename=f"server-{self.guild_id}.json"
                ),
                discord.File(
                    io.BytesIO(csv_bytes),
                    filename=f"server-{self.guild_id}-hosts.csv"
                ),
            ],
            ephemeral=True
        )

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=server_insights_embed(self.guild_id),
            view=ServerInsightsView(self.guild_id, self.user_id)
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        guild = await self.valid(interaction)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=user_server_embed(guild),
            view=UserServerMenuView(self.guild_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=dm_menu_home_embed(self.user_id),
            view=MenuRoleChoiceView(self.user_id)
        )


def server_onboarding_embed(guild_id: int):
    guild = bot.get_guild(int(guild_id))
    cfg = get_config(guild_id)
    hosts = get_hosts(guild_id)
    verified = get_guild_owner_verification(guild_id)

    checks = [
        ("Owner verified", bool(verified and verified["verified"])),
        ("Channel YouTube", bool(cfg["youtube_channel_id"])),
        ("Channel TikTok/default", bool(cfg["tiktok_channel_id"])),
        ("Host pertama", bool(hosts)),
    ]

    return discord.Embed(
        title=f"🧭 Setup • {guild.name if guild else guild_id}",
        description="\n".join(
            f"{'✅' if ok else '⬜'} {label}"
            for label, ok in checks
        ),
        color=discord.Color.blurple()
    ).add_field(
        name="Langkah berikut",
        value="Gunakan **Kelola Host** untuk menambah host atau test notifier.",
        inline=False
    )


class ServerOnboardingView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)

    @discord.ui.button(label="Kelola Host", emoji="📡", style=discord.ButtonStyle.primary, row=0)
    async def hosts(self, interaction, button):
        guild = await require_server_owner(interaction, self.guild_id)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=user_server_hosts_embed(guild),
            view=UserServerHostsView(self.guild_id, self.user_id)
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        guild = await require_server_owner(interaction, self.guild_id)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=user_server_embed(guild),
            view=UserServerMenuView(self.guild_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction, button):
        await interaction.response.edit_message(
            embed=dm_menu_home_embed(self.user_id),
            view=MenuRoleChoiceView(self.user_id)
        )




class UserServerMenuView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)

    async def valid_owner(self, interaction):
        return await require_server_owner(interaction, self.guild_id)

    @discord.ui.button(label="Premium", emoji="⭐", style=discord.ButtonStyle.success, row=0)
    async def premium(self, interaction, button):
        guild = await self.valid_owner(interaction)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=premium_plan_summary_embed(guild),
            view=UserPremiumView(self.guild_id, interaction.user.id)
        )

    @discord.ui.button(label="Kelola Host", emoji="📡", style=discord.ButtonStyle.primary, row=0)
    async def manage_hosts(self, interaction, button):
        guild = await self.valid_owner(interaction)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=user_server_hosts_embed(guild),
            view=UserServerHostsView(guild.id, interaction.user.id)
        )

    @discord.ui.button(label="Request", emoji="📨", style=discord.ButtonStyle.secondary, row=0)
    async def requests(self, interaction, button):
        guild = await self.valid_owner(interaction)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=server_owner_requests_embed(self.guild_id),
            view=ServerOwnerRequestsView(interaction.user.id, self.guild_id)
        )

    @discord.ui.button(label="Insights", emoji="📊", style=discord.ButtonStyle.secondary, row=1)
    async def insights(self, interaction, button):
        guild = await self.valid_owner(interaction)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=server_insights_embed(self.guild_id),
            view=ServerInsightsView(self.guild_id, interaction.user.id)
        )

    @discord.ui.button(label="Platform", emoji="🌐", style=discord.ButtonStyle.secondary, row=1)
    async def platform(self, interaction, button):
        guild = await self.valid_owner(interaction)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=platform_control_embed(self.guild_id),
            view=ServerPlatformControlView(self.guild_id, interaction.user.id)
        )

    @discord.ui.button(label="Setup", emoji="🧭", style=discord.ButtonStyle.secondary, row=1)
    async def setup(self, interaction, button):
        guild = await self.valid_owner(interaction)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=server_onboarding_embed(self.guild_id),
            view=ServerOnboardingView(self.guild_id, interaction.user.id)
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction, button):
        await interaction.response.edit_message(
            embed=dm_menu_home_embed(interaction.user.id),
            view=MenuRoleChoiceView(interaction.user.id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=2)
    async def home(self, interaction, button):
        await interaction.response.edit_message(
            embed=dm_menu_home_embed(interaction.user.id),
            view=MenuRoleChoiceView(interaction.user.id)
        )


def user_server_hosts_embed(guild: discord.Guild):
    hosts = get_hosts(guild.id)
    settings = get_guild_settings(guild.id)
    limit = host_limit_for_guild(guild.id)
    plan = str(settings["plan"] or "free").upper()

    embed = discord.Embed(
        title=f"📡 Host Server • {guild.name}",
        description=(
            "Kelola host milik servermu sendiri.\n"
            "Fitur ini tersedia untuk **FREE dan PREMIUM** dan "
            "tidak memberikan akses ke panel Global Owner."
        ),
        color=discord.Color.blue()
    )
    embed.add_field(
        name="Plan",
        value=f"{'⭐' if plan == 'PREMIUM' else '🆓'} {plan}",
        inline=True
    )
    embed.add_field(
        name="Pemakaian Host",
        value=f"**{len(hosts)}/{limit}**",
        inline=True
    )
    embed.add_field(
        name="Platform",
        value="YouTube • TikTok • Twitch • Kick • Instagram • Facebook",
        inline=False
    )
    embed.set_footer(
        text="Server Owner Self-Service • terpisah dari /owner"
    )
    return embed


def get_host_for_server_owner(
    guild_id: int,
    host_id: int,
    user_id: int
):
    guild = bot.get_guild(int(guild_id))
    if (
        guild is None
        or int(guild.owner_id) != int(user_id)
    ):
        return None

    host = get_host(int(host_id))
    if (
        not host
        or int(host["guild_id"]) != int(guild_id)
    ):
        return None

    return host


class UserAddHostModal(discord.ui.Modal):
    platform = discord.ui.TextInput(
        label="Platform",
        placeholder="youtube/tiktok/twitch/kick/instagram/facebook",
        max_length=20
    )
    target = discord.ui.TextInput(
        label="Username / Channel ID / URL",
        placeholder="Contoh: username atau UCxxxx / URL Facebook",
        max_length=300
    )
    channel_id_input = discord.ui.TextInput(
        label="Channel Discord tujuan",
        placeholder="ID channel Discord",
        max_length=25
    )
    role_id_input = discord.ui.TextInput(
        label="Role mention (opsional)",
        placeholder="ID role Discord, boleh kosong",
        required=False,
        max_length=25
    )

    def __init__(self, guild_id: int, user_id: int):
        super().__init__(
            title="Tambah Host Server",
            timeout=300
        )
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "🔒 Form ini bukan milikmu."
            )
            return

        guild = bot.get_guild(self.guild_id)
        if (
            guild is None
            or int(guild.owner_id) != int(interaction.user.id)
        ):
            await safe_reply(
                interaction,
                "🔒 Hanya **Pemilik Server** yang dapat menambah host."
            )
            return

        current = len(get_hosts(self.guild_id))
        limit = host_limit_for_guild(self.guild_id)
        if current >= limit:
            settings = get_guild_settings(self.guild_id)
            if premium_access_effective(self.guild_id):
                msg = f"❌ Batas host PREMIUM tercapai (**{current}/{limit}**)."
            else:
                msg = (
                    f"❌ Batas host FREE tercapai (**{current}/{limit}**).\n"
                    "Upgrade Premium jika membutuhkan lebih banyak host."
                )
            await safe_reply(interaction, msg)
            return

        platform = self.platform.value.strip().lower()
        target_raw = self.target.value.strip()

        if platform not in SUPPORTED_PLATFORMS:
            await safe_reply(
                interaction,
                (
                    "❌ Platform tidak didukung.\n"
                    "Gunakan `youtube`, `tiktok`, `twitch`, `kick`, "
                    "`instagram`, atau `facebook`."
                )
            )
            return

        channel_raw = self.channel_id_input.value.strip()
        if not channel_raw.isdigit():
            await safe_reply(
                interaction,
                "❌ Channel Discord harus berupa ID angka."
            )
            return

        channel = guild.get_channel(int(channel_raw))
        if not isinstance(
            channel,
            (discord.TextChannel, discord.Thread)
        ):
            await safe_reply(
                interaction,
                "❌ Channel tujuan tidak ditemukan di server tersebut."
            )
            return

        me = guild.me
        if isinstance(channel, discord.TextChannel) and me:
            perms = channel.permissions_for(me)
            if not (
                perms.view_channel
                and perms.send_messages
                and perms.embed_links
            ):
                await safe_reply(
                    interaction,
                    (
                        "❌ Bot belum punya izin **View Channel + "
                        "Send Messages + Embed Links** di channel tersebut."
                    )
                )
                return

        role_id = None
        role_raw = self.role_id_input.value.strip()
        if role_raw:
            if not role_raw.isdigit():
                await safe_reply(
                    interaction,
                    "❌ Role Discord harus berupa ID angka."
                )
                return
            role = guild.get_role(int(role_raw))
            if role is None:
                await safe_reply(
                    interaction,
                    "❌ Role tidak ditemukan di server tersebut."
                )
                return
            role_id = int(role_raw)

        target = normalize_social_target(
            platform,
            target_raw
        )
        if not target:
            await safe_reply(
                interaction,
                "❌ Username/target tidak valid."
            )
            return

        await defer_if_needed(interaction)

        try:
            display_name = (
                f"@{target}"
                if not target.startswith(("http://", "https://"))
                else target
            )
            extra = None

            if platform == "youtube":
                display_name, extra = await resolve_youtube_channel(target)

            add_host(
                self.guild_id,
                platform,
                target,
                display_name,
                extra
            )

            with closing(db()) as conn:
                row = conn.execute("""
                    SELECT id
                    FROM hosts
                    WHERE guild_id=? AND platform=? AND target=?
                """, (
                    self.guild_id,
                    platform,
                    target
                )).fetchone()

            if not row:
                raise RuntimeError("Host berhasil diproses tetapi ID host tidak ditemukan.")

            set_host_channel(
                int(row["id"]),
                int(channel_raw)
            )
            set_host_role(
                int(row["id"]),
                role_id
            )

            await log_action(
                self.guild_id,
                interaction.user.id,
                "Server Owner Tambah Host",
                (
                    f"{platform_display_name(platform)} {target} "
                    f"channel={channel_raw}"
                )
            )

            refreshed_count = len(get_hosts(self.guild_id))
            await interaction.followup.send(
                (
                    f"✅ {platform_icon(platform)} **{platform_display_name(platform)}** "
                    f"`{display_name}` berhasil ditambahkan.\n"
                    f"📣 Channel: <#{channel_raw}>\n"
                    f"📊 Host: **{refreshed_count}/{limit}**"
                ),
                ephemeral=True
            )

        except Exception as exc:
            await interaction.followup.send(
                f"❌ Gagal menambahkan host: `{type(exc).__name__}: {exc}`",
                ephemeral=True
            )


class UserServerHostSelect(discord.ui.Select):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        page: int = 0,
        query: str = ""
    ):
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.page = max(0, int(page))
        self.query = str(query or "").strip().lower()

        hosts = list(get_hosts(self.guild_id))

        if self.query:
            hosts = [
                host for host in hosts
                if (
                    self.query in str(host["id"]).lower()
                    or self.query in str(host["platform"]).lower()
                    or self.query in str(host["target"]).lower()
                    or self.query in str(host["display_name"] or "").lower()
                )
            ]

        start = self.page * 25
        current = hosts[start:start + 25]

        options = []
        for host in current:
            label = host["display_name"] or host["target"]
            state = "Aktif" if host["enabled"] else "Pause"
            options.append(
                discord.SelectOption(
                    label=(
                        f"{platform_display_name(host['platform'])} • {label}"
                    )[:100],
                    description=(
                        f"{state} • Host ID {host['id']}"
                    )[:100],
                    value=str(host["id"]),
                    emoji=platform_icon(host["platform"])
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="Host tidak ditemukan",
                    description="Coba halaman atau pencarian lain.",
                    value="0",
                    emoji="ℹ️"
                )
            )

        super().__init__(
            placeholder=f"Pilih host • Halaman {self.page + 1}",
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "🔒 Menu ini bukan milikmu."
            )
            return

        host_id = int(self.values[0])
        if not host_id:
            await safe_reply(
                interaction,
                "ℹ️ Host tidak ditemukan."
            )
            return

        host = get_host_for_server_owner(
            self.guild_id,
            host_id,
            interaction.user.id
        )
        if not host:
            await safe_reply(
                interaction,
                "🔒 Host tidak ditemukan atau bukan milik servermu."
            )
            return

        await interaction.response.edit_message(
            embed=user_server_host_detail_embed(host),
            view=UserServerHostCardView(
                self.guild_id,
                self.user_id,
                host_id
            )
        )


def user_server_host_detail_embed(host):
    status = "🟢 Aktif" if host["enabled"] else "⏸️ Pause"
    channel = (
        f"<#{host['channel_id']}>"
        if host["channel_id"]
        else "Belum diatur"
    )
    role = (
        f"<@&{host['role_id']}>"
        if host["role_id"]
        else "Tidak ada"
    )

    embed = discord.Embed(
        title=(
            f"{platform_icon(host['platform'])} "
            f"{platform_display_name(host['platform'])} • "
            f"{host['display_name'] or host['target']}"
        ),
        description=(
            f"{status}\n"
            f"Target: `{host['target']}`"
        ),
        color=(
            discord.Color.green()
            if host["enabled"]
            else discord.Color.orange()
        )
    )
    embed.add_field(
        name="Channel",
        value=channel,
        inline=True
    )
    embed.add_field(
        name="Role",
        value=role,
        inline=True
    )
    embed.add_field(
        name="Monitor",
        value=(
            f"Last: {fmt_time(host['last_check'])}\n"
            f"Error: **{host['error_count'] or 0}**"
        ),
        inline=False
    )
    if host["last_error"]:
        embed.add_field(
            name="Error Terakhir",
            value=str(host["last_error"])[:800],
            inline=False
        )
    embed.set_footer(
        text=(
            f"Server Owner Self-Service • Host ID {host['id']} • "
            "tanpa akses /owner"
        )
    )
    return embed


class ServerBulkHostActionView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=300)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)

    async def valid(self, interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Menu ini bukan milikmu.")
            return None
        return await require_server_owner(interaction, self.guild_id)

    async def set_all(self, interaction, enabled: bool):
        guild = await self.valid(interaction)
        if not guild:
            return

        create_rollback_snapshot(
            self.guild_id,
            "bulk_resume" if enabled else "bulk_pause",
            interaction.user.id
        )

        with closing(db()) as conn:
            conn.execute(
                "UPDATE hosts SET enabled=? WHERE guild_id=?",
                (1 if enabled else 0, self.guild_id)
            )
            conn.commit()

        await interaction.response.edit_message(
            embed=user_server_hosts_embed(guild),
            view=UserServerHostsView(self.guild_id, self.user_id)
        )

    @discord.ui.button(label="Pause Semua", emoji="⏸️", style=discord.ButtonStyle.danger, row=0)
    async def pause_all(self, interaction, button):
        await self.set_all(interaction, False)

    @discord.ui.button(label="Resume Semua", emoji="▶️", style=discord.ButtonStyle.success, row=0)
    async def resume_all(self, interaction, button):
        await self.set_all(interaction, True)

    @discord.ui.button(label="Recheck Semua", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def recheck_all(self, interaction, button):
        guild = await self.valid(interaction)
        if not guild:
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, failed = 0, 0

        for host in get_hosts(self.guild_id):
            try:
                await host_manager_recheck(host)
                ok += 1
            except Exception:
                failed += 1

        await interaction.followup.send(
            f"🔄 Recheck selesai • ✅ {ok} • ❌ {failed}",
            ephemeral=True
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        guild = await self.valid(interaction)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=user_server_hosts_embed(guild),
            view=UserServerHostsView(self.guild_id, self.user_id)
        )




class UserServerHostSearchModal(discord.ui.Modal):
    query = discord.ui.TextInput(
        label="Cari Host",
        placeholder="ID / platform / username / target",
        max_length=120
    )

    def __init__(self, guild_id: int, user_id: int):
        super().__init__(title="Cari Host Server", timeout=300)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)

    async def on_submit(self, interaction: discord.Interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "🔒 Form ini bukan milikmu.")
            return

        if not await require_server_owner(interaction, self.guild_id):
            return

        guild = bot.get_guild(self.guild_id)
        await interaction.response.edit_message(
            embed=user_server_hosts_embed(guild),
            view=UserServerHostsView(
                self.guild_id,
                self.user_id,
                page=0,
                query=self.query.value.strip()
            )
        )


class UserServerHostsView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        page: int = 0,
        query: str = ""
    ):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.page = max(0, int(page))
        self.query = str(query or "")

        self.add_item(
            UserServerHostSelect(
                self.guild_id,
                self.user_id,
                self.page,
                self.query
            )
        )

    async def valid_owner(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "🔒 Menu ini bukan milikmu."
            )
            return None

        return await require_server_owner(
            interaction,
            self.guild_id
        )

    def filtered_hosts(self):
        hosts = list(get_hosts(self.guild_id))
        q = self.query.strip().lower()

        if q:
            hosts = [
                host for host in hosts
                if (
                    q in str(host["id"]).lower()
                    or q in str(host["platform"]).lower()
                    or q in str(host["target"]).lower()
                    or q in str(host["display_name"] or "").lower()
                )
            ]

        return hosts

    @discord.ui.button(
        label="Tambah Host",
        emoji="➕",
        style=discord.ButtonStyle.success,
        row=1
    )
    async def add_host_button(self, interaction, button):
        guild = await self.valid_owner(interaction)
        if not guild:
            return

        current = len(get_hosts(self.guild_id))
        limit = host_limit_for_guild(self.guild_id)

        if current >= limit:
            settings = get_guild_settings(self.guild_id)
            await safe_reply(
                interaction,
                (
                    f"❌ Batas host "
                    f"{'PREMIUM' if premium_access_effective(self.guild_id) else 'FREE'} "
                    f"sudah tercapai (**{current}/{limit}**)."
                )
            )
            return

        await interaction.response.send_modal(
            UserAddHostModal(
                self.guild_id,
                self.user_id
            )
        )

    @discord.ui.button(
        label="◀",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def previous(self, interaction, button):
        guild = await self.valid_owner(interaction)
        if not guild:
            return

        await interaction.response.edit_message(
            embed=user_server_hosts_embed(guild),
            view=UserServerHostsView(
                self.guild_id,
                self.user_id,
                max(0, self.page - 1),
                self.query
            )
        )

    @discord.ui.button(
        label="▶",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def next_page(self, interaction, button):
        guild = await self.valid_owner(interaction)
        if not guild:
            return

        hosts = self.filtered_hosts()
        max_page = max(0, (len(hosts) - 1) // 25)

        await interaction.response.edit_message(
            embed=user_server_hosts_embed(guild),
            view=UserServerHostsView(
                self.guild_id,
                self.user_id,
                min(max_page, self.page + 1),
                self.query
            )
        )

    @discord.ui.button(
        label="Cari",
        emoji="🔎",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def search(self, interaction, button):
        if not await self.valid_owner(interaction):
            return

        await interaction.response.send_modal(
            UserServerHostSearchModal(
                self.guild_id,
                self.user_id
            )
        )

    @discord.ui.button(
        label="Bulk",
        emoji="🧰",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def bulk(self, interaction, button):
        guild = await self.valid_owner(interaction)
        if not guild:
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"🧰 Bulk Host • {guild.name}",
                description=(
                    "Aksi massal membuat rollback snapshot sebelum perubahan."
                ),
                color=discord.Color.orange()
            ),
            view=ServerBulkHostActionView(
                self.guild_id,
                self.user_id
            )
        )

    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def refresh(self, interaction, button):
        guild = await self.valid_owner(interaction)
        if not guild:
            return

        await interaction.response.edit_message(
            embed=user_server_hosts_embed(guild),
            view=UserServerHostsView(
                self.guild_id,
                self.user_id,
                self.page,
                self.query
            )
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=3
    )
    async def back(self, interaction, button):
        guild = await self.valid_owner(interaction)
        if not guild:
            return

        await interaction.response.edit_message(
            embed=user_server_embed(guild),
            view=UserServerMenuView(
                self.user_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=3
    )
    async def home(self, interaction, button):
        if not await self.valid_owner(interaction):
            return

        await interaction.response.edit_message(
            embed=dm_menu_home_embed(self.user_id),
            view=MenuRoleChoiceView(self.user_id)
        )


HOST_MANAGER_PERMISSION_PRESETS = {
    "readonly": set(),
    "moderator": {"pause", "recheck", "history", "test"},
    "content": {"edit_messages", "schedule", "history", "test"},
    "full": set(HOST_MANAGER_PERMISSION_COLUMNS),
}


class ServerOwnerManagerPermissionModal(discord.ui.Modal):
    manager_id = discord.ui.TextInput(
        label="User ID Host Manager",
        placeholder="123456789012345678",
        max_length=24
    )
    permissions = discord.ui.TextInput(
        label="Permissions / Preset",
        placeholder="full / moderator / content / readonly atau list permission",
        style=discord.TextStyle.paragraph,
        max_length=250
    )
    expiry_days = discord.ui.TextInput(
        label="Masa Akses (hari)",
        placeholder="Kosong = permanen; contoh 7 / 30",
        required=False,
        max_length=5
    )

    def __init__(self, guild_id: int, host_id: int, owner_id: int):
        super().__init__(title="Permission Host Manager", timeout=300)
        self.guild_id = int(guild_id)
        self.host_id = int(host_id)
        self.owner_id = int(owner_id)

    async def on_submit(self, interaction):
        if int(interaction.user.id) != self.owner_id:
            await safe_reply(interaction, "🔒 Menu ini bukan milikmu.")
            return
        if not await require_server_owner(interaction, self.guild_id):
            return

        raw_id = self.manager_id.value.strip()
        if not raw_id.isdigit():
            await safe_reply(interaction, "❌ User ID harus angka.")
            return

        allowed = set(HOST_MANAGER_PERMISSION_COLUMNS)
        raw_permissions = self.permissions.value.strip().lower()
        if raw_permissions in HOST_MANAGER_PERMISSION_PRESETS:
            requested = set(HOST_MANAGER_PERMISSION_PRESETS[raw_permissions])
        else:
            requested = {
                item.strip().lower()
                for item in raw_permissions.split(",")
                if item.strip()
            }
        invalid = sorted(requested - allowed)
        if invalid:
            await safe_reply(
                interaction,
                "❌ Permission tidak valid: " + ", ".join(invalid)
            )
            return

        manager_id = int(raw_id)
        expires_at = None
        raw_expiry = self.expiry_days.value.strip()
        if raw_expiry:
            if not raw_expiry.isdigit() or int(raw_expiry) < 1:
                await safe_reply(interaction, "❌ Masa akses harus angka hari minimal 1.")
                return
            expires_at = int(time.time()) + int(raw_expiry) * 86400

        assign_host_manager(
            self.host_id,
            manager_id,
            assigned_by=interaction.user.id,
            permissions=requested,
            expires_at=expires_at
        )
        await log_action(
            self.guild_id,
            interaction.user.id,
            "Host Manager Permission",
            (
                f"host_id={self.host_id} manager={manager_id} "
                f"permissions={','.join(sorted(requested)) or 'read-only'}"
            )
        )
        await safe_reply(
            interaction,
            (
                f"✅ Permission Host Manager <@{manager_id}> diperbarui.\n"
                f"{host_manager_permission_text(manager_id, self.host_id)}"
            )
        )


class UserServerHostCardView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        host_id: int
    ):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.host_id = int(host_id)

    async def valid(
        self,
        interaction: discord.Interaction
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "🔒 Menu ini bukan milikmu."
            )
            return None

        host = get_host_for_server_owner(
            self.guild_id,
            self.host_id,
            interaction.user.id
        )
        if not host:
            await safe_reply(
                interaction,
                "🔒 Host tidak ditemukan atau bukan milik servermu."
            )
            return None
        return host

    @discord.ui.button(
        label="Pause / Resume",
        emoji="⏯️",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def toggle(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction)
        if not host:
            return

        toggle_host(self.host_id)
        refreshed = get_host(self.host_id)

        await log_action(
            self.guild_id,
            interaction.user.id,
            "Server Owner Pause/Resume Host",
            f"host_id={self.host_id} enabled={bool(refreshed['enabled'])}"
        )

        await interaction.response.edit_message(
            embed=user_server_host_detail_embed(refreshed),
            view=UserServerHostCardView(
                self.guild_id,
                self.user_id,
                self.host_id
            )
        )

    @discord.ui.button(
        label="Recheck",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def recheck(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction)
        if not host:
            return

        key = f"server_owner_recheck:{self.host_id}"
        if action_rate_limited(
            interaction.user.id,
            key
        ):
            await safe_reply(
                interaction,
                "⏳ Recheck terlalu cepat. Coba lagi beberapa detik."
            )
            return

        await defer_if_needed(interaction)

        try:
            await host_manager_recheck(host)
            await interaction.followup.send(
                "✅ Recheck host selesai.",
                ephemeral=True
            )
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Recheck gagal: `{type(exc).__name__}: {exc}`",
                ephemeral=True
            )

    @discord.ui.button(
        label="Hapus Host",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        row=0
    )
    async def delete(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction)
        if not host:
            return

        label = host["display_name"] or host["target"]

        await safe_reply(
            interaction,
            (
                f"⚠️ Yakin ingin menghapus **{platform_display_name(host['platform'])} "
                f"• {label}**?\n"
                "Aksi ini juga menghapus assignment Host Manager terkait."
            ),
            view=ServerOwnerDeleteHostConfirmView(
                self.guild_id,
                self.user_id,
                self.host_id
            )
        )

    @discord.ui.button(
        label="Manager",
        emoji="🎙️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def manager_permissions(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction)
        if not host:
            return
        await interaction.response.send_modal(
            ServerOwnerManagerPermissionModal(
                self.guild_id,
                self.host_id,
                self.user_id
            )
        )

    @discord.ui.button(
        label="Clone",
        emoji="🧬",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def clone_host(self, interaction: discord.Interaction, button: discord.ui.Button):
        host = await self.valid(interaction)
        if not host:
            return
        await interaction.response.send_modal(
            HostCloneModal(self.host_id, self.user_id)
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction)
        if not host:
            return

        guild = bot.get_guild(self.guild_id)
        await interaction.response.edit_message(
            embed=user_server_hosts_embed(guild),
            view=UserServerHostsView(
                self.guild_id,
                self.user_id
            )
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def home(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "🔒 Menu ini bukan milikmu."
            )
            return

        await interaction.response.edit_message(
            embed=dm_menu_home_embed(self.user_id),
            view=MenuRoleChoiceView(
                self.user_id
            )
        )



def host_manager_home_embed(user_id: int):
    rows = host_manager_rows(user_id)
    guilds = host_manager_guilds(user_id)
    problems = host_manager_problem_hosts(user_id)
    latest = host_manager_latest_notifications(user_id, limit=5)
    first_time = host_manager_needs_onboarding(user_id)

    description = (
        "Panel khusus **Host Manager**. Pilih server terlebih dahulu agar "
        "host dari server berbeda tidak pernah tercampur."
    )

    if first_time:
        description += (
            "\n\n👋 **Pertama kali?** Pilih server → pilih host. "
            "Gunakan Quick Action untuk Preview, Recheck, Pesan, Jadwal, dan History."
        )

    embed = discord.Embed(
        title="🎙️ Host Saya",
        description=description,
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="Server",
        value=str(len(guilds)),
        inline=True
    )
    embed.add_field(
        name="Host Dikelola",
        value=str(len(rows)),
        inline=True
    )
    embed.add_field(
        name="Masalah",
        value=str(len(problems)),
        inline=True
    )
    embed.add_field(
        name="Notif Terakhir",
        value=str(len(latest)),
        inline=True
    )
    embed.add_field(
        name="Akses Owner",
        value="❌ Tidak ada",
        inline=True
    )
    embed.set_footer(
        text="Host Panel • terpisah total dari /owner"
    )
    return embed


def host_manager_detail_embed(host, user_id: int):
    access = host_manager_access(user_id, host["id"])
    stats = host_manager_stats(host["id"])

    permissions = []
    if access:
        for key, column in HOST_MANAGER_PERMISSION_COLUMNS.items():
            if access[column]:
                permissions.append(key.replace("_", " ").title())

    embed = host_embed(host)
    embed.title = f"🎙️ Host Saya • {platform_display_name(host['platform'])}"
    embed.add_field(
        name="Statistik 7 Hari",
        value=(
            f"Notif: **{stats['total']}**\n"
            f"Berhasil: **{stats['sent']}**\n"
            f"Gagal: **{stats['failed']}**\n"
            f"Success: **{stats['success_rate']}%**\n"
            f"Latency: **{stats['latency']} ms**"
        ),
        inline=False
    )
    embed.add_field(
        name="Izin Host Manager",
        value=", ".join(permissions) if permissions else "Read-only",
        inline=False
    )
    health_icon, health_text = host_health_label(host)
    embed.add_field(
        name="Health",
        value=f"{health_icon} **{health_text}**",
        inline=True
    )
    embed.add_field(
        name="Permission",
        value=host_manager_permission_text(user_id, host["id"]),
        inline=False
    )

    embed.set_footer(
        text=f"Host Panel terisolasi • Host ID {host['id']} • Tidak ada akses Owner"
    )
    return embed


def host_manager_all_hosts_embed(
    user_id: int,
    guild_id: int
):
    rows = host_manager_visible_hosts(
        user_id,
        guild_id
    )
    assigned_ids = {
        int(row["host_id"])
        for row in host_manager_rows(user_id)
        if int(row["guild_id"]) == int(guild_id)
    }

    guild = bot.get_guild(int(guild_id))
    guild_name = guild.name if guild else f"Server {guild_id}"

    embed = discord.Embed(
        title=f"🌐 Semua Host • {guild_name}",
        description=(
            "Daftar ini hanya menampilkan host dari **server ini**.\n"
            "Host yang tidak ditugaskan kepadamu tetap bersifat **read-only**."
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Total Host Server",
        value=str(len(rows)),
        inline=True
    )
    embed.add_field(
        name="Bisa Dikelola",
        value=str(sum(1 for row in rows if int(row["id"]) in assigned_ids)),
        inline=True
    )
    embed.add_field(
        name="Read-only",
        value=str(sum(1 for row in rows if int(row["id"]) not in assigned_ids)),
        inline=True
    )

    embed.set_footer(
        text="Host Panel • hanya server ini • tidak menampilkan server lain"
    )
    return embed


class HostManagerAllHostsSelect(discord.ui.Select):
    def __init__(
        self,
        user_id: int,
        guild_id: int
    ):
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)

        rows = host_manager_visible_hosts(
            self.user_id,
            self.guild_id
        )

        assigned_ids = {
            int(row["host_id"])
            for row in host_manager_rows(self.user_id)
            if int(row["guild_id"]) == self.guild_id
        }

        options = []

        for row in rows[:25]:
            label = (
                row["display_name"]
                or row["target"]
                or f"Host {row['id']}"
            )
            access_label = (
                "Kelola"
                if int(row["id"]) in assigned_ids
                else "Read-only"
            )

            options.append(
                discord.SelectOption(
                    label=(
                        f"{platform_display_name(row['platform'])} • {label}"
                    )[:100],
                    description=(
                        f"{access_label} • Host ID {row['id']}"
                    )[:100],
                    value=str(row["id"]),
                    emoji=platform_icon(row["platform"])
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="Belum ada host",
                    description="Tidak ada host pada server ini.",
                    value="0",
                    emoji="ℹ️"
                )
            )

        super().__init__(
            placeholder="Pilih host dari server ini",
            options=options,
            row=0
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "❌ Panel ini bukan milikmu."
            )
            return

        if not host_manager_has_guild_access(
            self.user_id,
            self.guild_id
        ):
            await safe_reply(
                interaction,
                "🔒 Akses ke server ini sudah tidak tersedia."
            )
            return

        host_id = int(self.values[0])

        if not host_id:
            await safe_reply(
                interaction,
                "ℹ️ Tidak ada host pada server ini."
            )
            return

        host = get_host(host_id)

        if (
            not host
            or int(host["guild_id"]) != self.guild_id
        ):
            await safe_reply(
                interaction,
                "🔒 Host tersebut bukan bagian dari server ini."
            )
            return

        if host_is_assigned_to_manager(
            self.user_id,
            host_id
        ):
            await interaction.response.edit_message(
                embed=host_manager_detail_embed(
                    host,
                    self.user_id
                ),
                view=HostManagerDetailView(
                    self.user_id,
                    host_id
                )
            )
            return

        await interaction.response.edit_message(
            embed=host_manager_readonly_detail_embed(
                host,
                self.user_id
            ),
            view=HostManagerReadonlyHostView(
                self.user_id,
                host_id,
                self.guild_id
            )
        )


def host_manager_readonly_detail_embed(
    host,
    user_id: int
):
    guild = bot.get_guild(int(host["guild_id"]))
    guild_name = (
        guild.name
        if guild
        else f"Server {host['guild_id']}"
    )

    channel_text = (
        f"<#{host['channel_id']}>"
        if host["channel_id"]
        else "Default / belum diatur"
    )

    role_text = (
        f"<@&{host['role_id']}>"
        if host["role_id"]
        else "Tidak ada"
    )

    embed = discord.Embed(
        title=(
            f"👁️ Read-only • "
            f"{platform_icon(host['platform'])} "
            f"{platform_display_name(host['platform'])}"
        ),
        description=(
            f"**{host['display_name'] or host['target']}**\n"
            f"Server: **{guild_name}**\n"
            f"Target: `{host['target']}`"
        ),
        color=discord.Color.greyple()
    )

    embed.add_field(
        name="Status",
        value=(
            "🟢 Aktif"
            if host["enabled"]
            else "⏸️ Pause"
        ),
        inline=True
    )

    embed.add_field(
        name="Channel",
        value=channel_text,
        inline=True
    )

    embed.add_field(
        name="Role",
        value=role_text,
        inline=True
    )

    embed.add_field(
        name="Monitor",
        value=(
            f"Last check: {fmt_time(host['last_check'])}\n"
            f"Error: **{host['error_count'] or 0}**"
        ),
        inline=False
    )

    if host["last_error"]:
        embed.add_field(
            name="Error Terakhir",
            value=str(host["last_error"])[:800],
            inline=False
        )

    embed.add_field(
        name="Hak Akses",
        value=(
            "👁️ **Read-only**\n"
            "Kamu dapat melihat host ini karena host berada di server "
            "tempat kamu menjadi Host Manager."
        ),
        inline=False
    )

    embed.set_footer(
        text=(
            f"Host ID {host['id']} • Read-only • "
            "hanya server yang sama"
        )
    )

    return embed


class HostManagerReadonlyHostView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        host_id: int,
        guild_id: int
    ):
        super().__init__(timeout=900)
        self.user_id = int(user_id)
        self.host_id = int(host_id)
        self.guild_id = int(guild_id)

    async def valid(
        self,
        interaction: discord.Interaction
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "❌ Panel ini bukan milikmu."
            )
            return None

        if not host_manager_has_guild_access(
            self.user_id,
            self.guild_id
        ):
            await safe_reply(
                interaction,
                "🔒 Akses ke server ini sudah tidak tersedia."
            )
            return None

        host = get_host(self.host_id)

        if (
            not host
            or int(host["guild_id"]) != self.guild_id
        ):
            await safe_reply(
                interaction,
                "🔒 Host tersebut bukan bagian dari server ini."
            )
            return None

        return host

    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def refresh(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction)
        if not host:
            return

        await interaction.response.edit_message(
            embed=host_manager_readonly_detail_embed(
                host,
                self.user_id
            ),
            view=HostManagerReadonlyHostView(
                self.user_id,
                self.host_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Minta Akses",
        emoji="📨",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def request_access(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction)
        if not host:
            return

        try:
            request_id = create_host_access_request(
                self.user_id,
                self.host_id
            )
        except Exception as exc:
            await safe_reply(
                interaction,
                f"❌ {exc}"
            )
            return

        guild = bot.get_guild(self.guild_id)
        sent = False

        if guild:
            try:
                owner = guild.owner or await bot.fetch_user(
                    int(guild.owner_id)
                )
                await owner.send(
                    content=(
                        f"📨 **Request Akses Host #{self.host_id}**\n"
                        f"User: <@{self.user_id}>\n"
                        f"Server: **{guild.name}**\n"
                        f"Host: **{platform_display_name(host['platform'])} • "
                        f"{host['display_name'] or host['target']}**"
                    ),
                    view=HostAccessRequestDecisionView(
                        request_id,
                        self.guild_id
                    )
                )
                sent = True
            except Exception:
                pass

        await safe_reply(
            interaction,
            (
                f"✅ Request akses **#{request_id}** dikirim ke owner server."
                if sent
                else (
                    f"✅ Request akses **#{request_id}** tersimpan, "
                    "tetapi DM ke owner server gagal."
                )
            )
        )

    @discord.ui.button(
        label="Semua Host Server",
        emoji="🌐",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def all_hosts(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "❌ Panel ini bukan milikmu."
            )
            return

        if not host_manager_has_guild_access(
            self.user_id,
            self.guild_id
        ):
            await safe_reply(
                interaction,
                "🔒 Akses ke server ini sudah tidak tersedia."
            )
            return

        await interaction.response.edit_message(
            embed=host_manager_all_hosts_embed(
                self.user_id,
                self.guild_id
            ),
            view=HostManagerAllHostsView(
                self.user_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Host Saya",
        emoji="🎙️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def my_hosts(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "❌ Panel ini bukan milikmu."
            )
            return

        await interaction.response.edit_message(
            embed=host_manager_home_embed(
                self.user_id
            ),
            view=HostManagerHomeView(
                self.user_id
            )
        )


class HostManagerAllHostsView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        guild_id: int
    ):
        super().__init__(timeout=900)
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)

        self.add_item(
            HostManagerAllHostsSelect(
                self.user_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Host Saya",
        emoji="🎙️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def my_hosts(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "❌ Panel ini bukan milikmu."
            )
            return

        await interaction.response.edit_message(
            embed=host_manager_home_embed(
                self.user_id
            ),
            view=HostManagerHomeView(
                self.user_id
            )
        )

    @discord.ui.button(
        label="Menu Pengguna",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def user_home(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "❌ Panel ini bukan milikmu."
            )
            return

        await interaction.response.edit_message(
            embed=dm_menu_home_embed(
                self.user_id
            ),
            view=MenuRoleChoiceView(
                self.user_id
            )
        )


def host_manager_guild_embed(
    user_id: int,
    guild_id: int
):
    guild = bot.get_guild(int(guild_id))
    hosts = host_manager_hosts_for_guild(
        user_id,
        guild_id
    )
    managed = [
        host
        for host in hosts
        if host_manager_access(
            user_id,
            int(host["id"])
        )
    ]
    problems = host_manager_problem_hosts(
        user_id,
        guild_id
    )

    embed = discord.Embed(
        title=f"🏢 Host Server • {guild.name if guild else guild_id}",
        description=(
            "Daftar ini hanya untuk **server ini**. "
            "Host yang bukan tugasmu dapat dilihat sebagai read-only."
        ),
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="Semua Host",
        value=str(len(hosts)),
        inline=True
    )
    embed.add_field(
        name="Bisa Dikelola",
        value=str(len(managed)),
        inline=True
    )
    embed.add_field(
        name="Bermasalah",
        value=str(len(problems)),
        inline=True
    )
    embed.add_field(
        name="➕ Host Baru",
        value=(
            "Gunakan **Ajukan Host**. Host baru berstatus PENDING dan "
            "wajib disetujui Pemilik Server sebelum aktif."
        ),
        inline=False
    )
    embed.set_footer(
        text="Host Manager • server-scoped • host baru wajib approval owner server"
    )
    return embed


class HostManagerGuildSelect(discord.ui.Select):
    def __init__(self, user_id: int):
        self.user_id = int(user_id)
        guilds = host_manager_guilds(self.user_id)

        options = []
        for guild in guilds[:25]:
            managed = sum(
                1
                for row in host_manager_rows(self.user_id)
                if int(row["guild_id"]) == int(guild.id)
            )
            options.append(
                discord.SelectOption(
                    label=guild.name[:100],
                    description=f"{managed} host dikelola • akses server aktif"[:100],
                    value=str(guild.id),
                    emoji="🏢"
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="Belum ada server Host",
                    description="Belum ada host yang ditugaskan.",
                    value="0",
                    emoji="ℹ️"
                )
            )

        super().__init__(
            placeholder="Pilih server Host Manager",
            options=options,
            row=0
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "❌ Panel ini bukan milikmu."
            )
            return

        guild_id = int(self.values[0])

        if not guild_id:
            await safe_reply(
                interaction,
                "ℹ️ Belum ada server yang dapat dikelola."
            )
            return

        if not host_manager_has_guild_access(
            self.user_id,
            guild_id
        ):
            await safe_reply(
                interaction,
                "🔒 Akses server sudah tidak tersedia."
            )
            return

        await interaction.response.edit_message(
            embed=host_manager_guild_embed(
                self.user_id,
                guild_id
            ),
            view=HostManagerGuildDashboardView(
                self.user_id,
                guild_id,
                0
            )
        )


class HostManagerScopedHostSelect(discord.ui.Select):
    def __init__(
        self,
        user_id: int,
        guild_id: int,
        page: int = 0,
        host_ids: Optional[list[int]] = None
    ):
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)
        self.page = max(0, int(page))

        rows = host_manager_hosts_for_guild(
            self.user_id,
            self.guild_id
        )

        if host_ids is not None:
            allowed_ids = {int(x) for x in host_ids}
            rows = [
                row
                for row in rows
                if int(row["id"]) in allowed_ids
            ]

        self.total = len(rows)
        start = self.page * 25
        current = rows[start:start + 25]

        options = []
        for host in current:
            assigned = bool(
                host_manager_access(
                    self.user_id,
                    int(host["id"])
                )
            )
            pref = host_manager_pref(
                self.user_id,
                int(host["id"])
            )
            favorite = bool(
                pref and pref["favorite"]
            )
            health_icon, health_text = host_health_label(host)
            label = host["display_name"] or host["target"]

            options.append(
                discord.SelectOption(
                    label=(
                        f"{'⭐ ' if favorite else ''}"
                        f"{platform_display_name(host['platform'])} • {label}"
                    )[:100],
                    description=(
                        f"{health_icon} {health_text} • "
                        f"{'Kelola' if assigned else 'Read-only'} • "
                        f"Host {host['id']}"
                    )[:100],
                    value=str(host["id"]),
                    emoji=platform_icon(host["platform"])
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="Tidak ada host",
                    description="Tidak ada hasil pada halaman ini.",
                    value="0",
                    emoji="ℹ️"
                )
            )

        super().__init__(
            placeholder=f"Pilih host • Halaman {self.page + 1}",
            options=options,
            row=0
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(
                interaction,
                "❌ Panel ini bukan milikmu."
            )
            return

        host_id = int(self.values[0])
        if not host_id:
            await safe_reply(
                interaction,
                "ℹ️ Tidak ada host pada halaman ini."
            )
            return

        host = get_host(host_id)

        if (
            not host
            or int(host["guild_id"]) != self.guild_id
            or not host_manager_has_guild_access(
                self.user_id,
                self.guild_id
            )
        ):
            await safe_reply(
                interaction,
                "🔒 Host bukan bagian dari server aktif."
            )
            return

        if host_manager_access(
            self.user_id,
            host_id
        ):
            mark_host_manager_onboarding(
                self.user_id,
                host_id
            )
            await interaction.response.edit_message(
                embed=host_manager_detail_embed(
                    host,
                    self.user_id
                ),
                view=HostManagerDetailView(
                    self.user_id,
                    host_id
                )
            )
        else:
            await interaction.response.edit_message(
                embed=host_manager_readonly_detail_embed(
                    host,
                    self.user_id
                ),
                view=HostManagerReadonlyHostView(
                    self.user_id,
                    host_id,
                    self.guild_id
                )
            )


class HostManagerSearchModal(discord.ui.Modal):
    query = discord.ui.TextInput(
        label="Cari Host",
        placeholder="Username, nama, platform, atau ID host",
        max_length=100
    )

    def __init__(
        self,
        user_id: int,
        guild_id: int
    ):
        super().__init__(
            title="Cari Host Server",
            timeout=300
        )
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        if (
            interaction.user.id != self.user_id
            or not host_manager_has_guild_access(
                self.user_id,
                self.guild_id
            )
        ):
            await safe_reply(
                interaction,
                "🔒 Akses ditolak."
            )
            return

        q = self.query.value.strip().lower()
        rows = host_manager_hosts_for_guild(
            self.user_id,
            self.guild_id
        )

        matches = [
            row
            for row in rows
            if (
                q in str(row["id"])
                or q in str(row["platform"]).lower()
                or q in str(row["target"]).lower()
                or q in str(row["display_name"] or "").lower()
            )
        ]

        if not matches:
            await safe_reply(
                interaction,
                f"🔎 Tidak ada host cocok dengan `{q}`."
            )
            return

        ids = [
            int(row["id"])
            for row in matches[:25]
        ]

        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔎 Hasil Pencarian Host",
                description=(
                    f"Ditemukan **{len(matches)}** host. "
                    "Menampilkan maksimal 25 hasil pertama."
                ),
                color=discord.Color.blurple()
            ),
            view=HostSearchResultsView(
                self.user_id,
                self.guild_id,
                ids
            ),
            ephemeral=True
        )


class HostSearchResultsView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        guild_id: int,
        host_ids: list[int]
    ):
        super().__init__(timeout=600)
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)
        self.add_item(
            HostManagerScopedHostSelect(
                self.user_id,
                self.guild_id,
                0,
                host_ids
            )
        )


def host_manager_server_access_embed(
    user_id: int,
    guild_id: int
):
    guild = bot.get_guild(int(guild_id))
    server_access = server_host_manager_access(
        user_id,
        guild_id
    )

    rows = [
        row
        for row in host_manager_rows(user_id)
        if int(row["guild_id"]) == int(guild_id)
    ]

    lines = []
    for row in rows[:20]:
        perms = []
        for key, column in HOST_MANAGER_PERMISSION_COLUMNS.items():
            if row[column]:
                perms.append(key.replace("_", " "))

        lines.append(
            f"• **{platform_display_name(row['platform'])} • "
            f"{row['display_name'] or row['target']}**\n"
            f"  {', '.join(perms) if perms else 'read-only'}"
        )

    embed = discord.Embed(
        title=f"🔐 Akses Saya • {guild.name if guild else guild_id}",
        description=(
            "Ringkasan hak aksesmu pada server ini."
        ),
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="Akses Tingkat Server",
        value=(
            "✅ Aktif"
            if server_access
            else "ℹ️ Hanya assignment host"
        ),
        inline=True
    )
    embed.add_field(
        name="Host Assigned",
        value=str(len(rows)),
        inline=True
    )
    embed.add_field(
        name="Hak Host",
        value=(
            "\n".join(lines)
            if lines
            else (
                "Belum ada host assigned. Kamu masih dapat mengajukan host baru "
                "jika akses tingkat server aktif."
            )
        ),
        inline=False
    )
    embed.set_footer(
        text="Host Manager tidak memiliki akses /owner atau administrasi global"
    )
    return embed


def host_manager_latest_embed(
    user_id: int,
    guild_id: Optional[int] = None
):
    rows = host_manager_latest_notifications(
        user_id,
        guild_id,
        10
    )

    lines = []
    for row in rows:
        icon = (
            "✅"
            if row["status"] == "sent"
            else "⏳"
            if row["status"] == "queued"
            else "❌"
        )
        creator = (
            row["display_name"]
            or row["target"]
            or f"Host {row['host_id']}"
        )
        lines.append(
            f"{icon} <t:{row['created_at']}:R> • "
            f"**{creator}** • `{row['event_type'] or 'notif'}`"
        )

    embed = discord.Embed(
        title="🔔 Notifikasi Terakhir",
        description=(
            "\n".join(lines)
            if lines
            else "Belum ada riwayat notifikasi."
        ),
        color=discord.Color.blurple()
    )
    embed.set_footer(
        text="Hanya notifikasi host yang kamu kelola"
    )
    return embed


def host_manager_problems_embed(
    user_id: int,
    guild_id: Optional[int] = None
):
    rows = host_manager_problem_hosts(
        user_id,
        guild_id
    )

    lines = []
    for host in rows[:20]:
        icon, health = host_health_label(host)
        label = host["display_name"] or host["target"]
        reason = (
            str(host["last_error"])[:90]
            if host["last_error"]
            else "Host sedang pause"
        )
        lines.append(
            f"{icon} **{platform_display_name(host['platform'])} • {label}** "
            f"— {health}\n↳ {reason}"
        )

    embed = discord.Embed(
        title="⚠️ Host Bermasalah",
        description=(
            "\n".join(lines)
            if lines
            else "✅ Tidak ada host bermasalah."
        ),
        color=(
            discord.Color.orange()
            if rows
            else discord.Color.green()
        )
    )
    embed.set_footer(
        text="Error Center • gunakan Recheck pada host yang kamu kelola"
    )
    return embed


def host_manager_activity_embed(user_id: int):
    rows = host_manager_activity_rows(
        user_id,
        10
    )

    lines = []
    for row in rows:
        creator = (
            row["display_name"]
            or row["target"]
            or f"Host {row['host_id']}"
        )
        lines.append(
            f"• <t:{row['created_at']}:R> • **{creator}**\n"
            f"  `{row['action']}`"
        )

    return discord.Embed(
        title="🧾 Aktivitas Saya",
        description=(
            "\n".join(lines)
            if lines
            else "Belum ada aktivitas Host Manager."
        ),
        color=discord.Color.blurple()
    )


def host_manager_help_embed():
    return discord.Embed(
        title="❓ Bantuan Host Manager",
        description=(
            "**Alur tercepat**\n"
            "`/menu → Host Saya → pilih server → pilih host`\n\n"
            "**Status health**\n"
            "🟢 Healthy • 🟡 Warning • 🔴 Error • ⏸️ Paused\n\n"
            "**Permission**\n"
            "Tombol yang memerlukan izin akan tetap diverifikasi saat dipakai.\n\n"
            "**Ajukan Host Baru**\n"
            "Gunakan `Ajukan Host`. Host baru tidak aktif sebelum Pemilik Server menyetujui.\n\n"
            "**Host read-only**\n"
            "Kamu boleh melihat host lain di server yang sama, tetapi tidak dapat "
            "mengubahnya. Gunakan **Minta Akses** bila diperlukan.\n\n"
            "**Owner**\n"
            "Host Manager tidak memiliki akses `/owner`, pembayaran, backup, "
            "premium admin, atau konfigurasi Global Owner."
        ),
        color=discord.Color.blurple()
    )


class SimpleBackToHostHomeView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=600)
        self.user_id = int(user_id)

    @discord.ui.button(
        label="Host Saya",
        emoji="🎙️",
        style=discord.ButtonStyle.secondary
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return

        await interaction.response.edit_message(
            embed=host_manager_home_embed(
                self.user_id
            ),
            view=HostManagerHomeView(
                self.user_id
            )
        )


class HostManagerAddHostRequestModal(discord.ui.Modal):
    platform = discord.ui.TextInput(
        label="Platform",
        placeholder="youtube/tiktok/twitch/kick/instagram/facebook",
        max_length=20
    )
    target = discord.ui.TextInput(
        label="Username / Channel ID / URL",
        placeholder="Contoh: username, UCxxxx, atau URL",
        max_length=300
    )
    channel_id_input = discord.ui.TextInput(
        label="Channel Discord tujuan",
        placeholder="ID channel Discord",
        max_length=25
    )
    role_id_input = discord.ui.TextInput(
        label="Role mention (opsional)",
        placeholder="ID role Discord, boleh kosong",
        required=False,
        max_length=25
    )

    def __init__(
        self,
        user_id: int,
        guild_id: int
    ):
        super().__init__(
            title="Ajukan Host Baru",
            timeout=300
        )
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(
                interaction,
                "🔒 Form ini bukan milikmu."
            )
            return

        if not host_manager_has_guild_access(
            self.user_id,
            self.guild_id
        ):
            await safe_reply(
                interaction,
                "🔒 Akses Host Manager server sudah tidak aktif."
            )
            return

        guild = bot.get_guild(
            self.guild_id
        )
        if not guild:
            await safe_reply(
                interaction,
                "❌ Server tidak ditemukan."
            )
            return

        platform = self.platform.value.strip().lower()
        if platform not in SUPPORTED_PLATFORMS:
            await safe_reply(
                interaction,
                (
                    "❌ Platform tidak didukung. Gunakan `youtube`, `tiktok`, "
                    "`twitch`, `kick`, `instagram`, atau `facebook`."
                )
            )
            return

        target = normalize_social_target(
            platform,
            self.target.value.strip()
        )
        if not target:
            await safe_reply(
                interaction,
                "❌ Target/username tidak valid."
            )
            return

        channel_raw = self.channel_id_input.value.strip()
        if not channel_raw.isdigit():
            await safe_reply(
                interaction,
                "❌ Channel Discord harus berupa ID angka."
            )
            return

        channel = guild.get_channel(
            int(channel_raw)
        )
        if not isinstance(
            channel,
            (discord.TextChannel, discord.Thread)
        ):
            await safe_reply(
                interaction,
                "❌ Channel tujuan tidak ditemukan di server ini."
            )
            return

        me = guild.me
        if isinstance(channel, discord.TextChannel) and me:
            perms = channel.permissions_for(me)
            if not (
                perms.view_channel
                and perms.send_messages
                and perms.embed_links
            ):
                await safe_reply(
                    interaction,
                    (
                        "❌ Bot belum punya izin **View Channel + Send Messages "
                        "+ Embed Links** di channel tersebut."
                    )
                )
                return

        role_id = None
        role_raw = self.role_id_input.value.strip()
        if role_raw:
            if not role_raw.isdigit():
                await safe_reply(
                    interaction,
                    "❌ Role Discord harus berupa ID angka."
                )
                return

            role = guild.get_role(
                int(role_raw)
            )
            if role is None:
                await safe_reply(
                    interaction,
                    "❌ Role tidak ditemukan di server ini."
                )
                return
            role_id = int(role_raw)

        # Do not create an active host here. Only create PENDING request.
        request_id = create_host_creation_request(
            self.guild_id,
            self.user_id,
            platform,
            target,
            int(channel_raw),
            role_id
        )

        try:
            owner = (
                guild.owner
                or await bot.fetch_user(
                    int(guild.owner_id)
                )
            )
            await owner.send(
                embed=host_creation_request_embed(
                    request_id
                ),
                view=ServerOwnerHostCreationApprovalView(
                    request_id,
                    self.guild_id,
                    self.user_id
                )
            )
            sent = True
        except Exception:
            sent = False

        log_host_manager_action(
            0,
            self.user_id,
            "request_new_host",
            (
                f"guild={self.guild_id} request={request_id} "
                f"platform={platform} target={target}"
            )
        )

        await safe_reply(
            interaction,
            (
                f"✅ Host baru diajukan sebagai request **#{request_id}**.\n"
                "Status: **PENDING**.\n"
                "Host **belum aktif** sampai Pemilik Server menyetujuinya."
                + (
                    "\n📨 Permintaan sudah dikirim ke DM Pemilik Server."
                    if sent
                    else (
                        "\n⚠️ Request tersimpan tetapi DM Pemilik Server gagal. "
                        "Kemungkinan DM owner tertutup."
                    )
                )
            )
        )


class ServerOwnerHostCreationApprovalView(discord.ui.View):
    def __init__(
        self,
        request_id: int,
        guild_id: int,
        requester_id: int
    ):
        super().__init__(timeout=None)
        self.request_id = int(request_id)
        self.guild_id = int(guild_id)
        self.requester_id = int(requester_id)
        self.approve.custom_id = f"hin:host_create:{self.request_id}:approve"
        self.deny.custom_id = f"hin:host_create:{self.request_id}:deny"

    async def valid(
        self,
        interaction: discord.Interaction
    ):
        guild = await require_server_owner(
            interaction,
            self.guild_id
        )
        if not guild:
            return None, None

        row = get_host_creation_request(
            self.request_id
        )
        if (
            not row
            or row["status"] != "pending"
            or int(row["guild_id"]) != self.guild_id
            or int(row["requester_id"]) != self.requester_id
        ):
            await safe_reply(
                interaction,
                "ℹ️ Request host ini sudah diproses atau tidak valid."
            )
            return None, None

        return guild, row

    @discord.ui.button(
        label="Setujui Host",
        emoji="✅",
        style=discord.ButtonStyle.success,
        row=0
    )
    async def approve(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        guild, row = await self.valid(
            interaction
        )
        if not guild:
            return

        if action_rate_limited(
            interaction.user.id,
            f"approve_host_request:{self.request_id}"
        ):
            await safe_reply(
                interaction,
                "⏳ Request sedang diproses. Jangan tekan dua kali."
            )
            return

        current = len(
            get_hosts(self.guild_id)
        )
        limit = host_limit_for_guild(
            self.guild_id
        )

        if current >= limit:
            settings = get_guild_settings(
                self.guild_id
            )
            await safe_reply(
                interaction,
                (
                    f"❌ Batas host "
                    f"{'PREMIUM' if premium_access_effective(self.guild_id) else 'FREE'} "
                    f"sudah tercapai (**{current}/{limit}**).\n"
                    "Request tetap **PENDING** sampai slot host tersedia."
                )
            )
            return

        # Revalidate channel/role at approval time.
        channel = guild.get_channel(
            int(row["channel_id"])
        )
        if not isinstance(
            channel,
            (discord.TextChannel, discord.Thread)
        ):
            await safe_reply(
                interaction,
                "❌ Channel tujuan sudah tidak valid. Request belum diproses."
            )
            return

        role_id = (
            int(row["role_id"])
            if row["role_id"]
            else None
        )
        if role_id and guild.get_role(role_id) is None:
            await safe_reply(
                interaction,
                "❌ Role mention sudah tidak valid. Request belum diproses."
            )
            return

        platform = str(row["platform"])
        target = str(row["target"])

        # Duplicate active host protection.
        with closing(db()) as conn:
            duplicate = conn.execute("""
                SELECT id
                FROM hosts
                WHERE guild_id=? AND platform=? AND target=?
            """, (
                self.guild_id,
                platform,
                target
            )).fetchone()

        if duplicate:
            finish_host_creation_request(
                self.request_id,
                status="cancelled",
                actor_id=interaction.user.id,
                host_id=int(duplicate["id"]),
                reason="Host sudah ada."
            )
            await safe_reply(
                interaction,
                f"ℹ️ Host tersebut sudah ada sebagai Host #{duplicate['id']}."
            )
            return

        await defer_if_needed(
            interaction
        )

        if not claim_host_creation_request(
            self.request_id,
            interaction.user.id
        ):
            await interaction.followup.send(
                "ℹ️ Request sedang atau sudah diproses.",
                ephemeral=True
            )
            return

        try:
            display_name = (
                f"@{target}"
                if not target.startswith(
                    ("http://", "https://")
                )
                else target
            )
            extra = None

            if platform == "youtube":
                display_name, extra = await resolve_youtube_channel(
                    target
                )

            add_host(
                self.guild_id,
                platform,
                target,
                display_name,
                extra
            )

            with closing(db()) as conn:
                host = conn.execute("""
                    SELECT *
                    FROM hosts
                    WHERE guild_id=? AND platform=? AND target=?
                """, (
                    self.guild_id,
                    platform,
                    target
                )).fetchone()

            if not host:
                raise RuntimeError(
                    "Host dibuat tetapi ID tidak ditemukan."
                )

            host_id = int(host["id"])

            set_host_channel(
                host_id,
                int(row["channel_id"])
            )
            set_host_role(
                host_id,
                role_id
            )

            # Requester automatically manages the host they requested,
            # after server-owner approval.
            assign_host_manager(
                host_id,
                self.requester_id,
                assigned_by=interaction.user.id,
                permissions=set(
                    HOST_MANAGER_PERMISSION_COLUMNS
                )
            )

            finish_host_creation_request(
                self.request_id,
                status="approved",
                actor_id=interaction.user.id,
                host_id=host_id
            )

            try:
                requester = (
                    bot.get_user(self.requester_id)
                    or await bot.fetch_user(
                        self.requester_id
                    )
                )
                await requester.send(
                    embed=discord.Embed(
                        title="✅ Host Baru Disetujui",
                        description=(
                            f"Pemilik server **{guild.name}** menyetujui "
                            f"request host **#{self.request_id}**.\n\n"
                            f"Host: **{platform_display_name(platform)} • "
                            f"{display_name}**\n"
                            f"Channel: <#{row['channel_id']}>\n\n"
                            "Host sekarang **aktif di notifier** dan otomatis "
                            "ditambahkan ke daftar host yang kamu kelola."
                        ),
                        color=discord.Color.green()
                    )
                )
            except Exception:
                pass

            await interaction.followup.send(
                (
                    f"✅ Request **#{self.request_id}** disetujui.\n"
                    f"Host **{platform_display_name(platform)} • {display_name}** "
                    f"sekarang aktif sebagai Host #{host_id}."
                ),
                ephemeral=True
            )

        except Exception as exc:
            reset_host_creation_request_claim(
                self.request_id
            )
            await interaction.followup.send(
                (
                    f"❌ Gagal membuat host. Request tetap **PENDING**.\n"
                    f"`{type(exc).__name__}: {exc}`"
                ),
                ephemeral=True
            )

    @discord.ui.button(
        label="Tolak Host",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        row=0
    )
    async def deny(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        guild, row = await self.valid(
            interaction
        )
        if not guild:
            return

        if action_rate_limited(
            interaction.user.id,
            f"deny_host_request:{self.request_id}"
        ):
            await safe_reply(
                interaction,
                "⏳ Request sedang diproses. Jangan tekan dua kali."
            )
            return

        if not claim_host_creation_request(
            self.request_id,
            interaction.user.id
        ):
            await safe_reply(
                interaction,
                "ℹ️ Request sedang atau sudah diproses."
            )
            return

        finish_host_creation_request(
            self.request_id,
            status="denied",
            actor_id=interaction.user.id,
            reason="Ditolak Pemilik Server."
        )

        try:
            requester = (
                bot.get_user(self.requester_id)
                or await bot.fetch_user(
                    self.requester_id
                )
            )
            await requester.send(
                f"❌ Request host baru **#{self.request_id}** di "
                f"server **{guild.name}** ditolak oleh Pemilik Server."
            )
        except Exception:
            pass

        await interaction.response.edit_message(
            content=f"❌ Request host **#{self.request_id}** ditolak.",
            embed=None,
            view=None
        )


def host_manager_pending_requests_embed(
    user_id: int,
    guild_id: int
):
    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT *
            FROM host_creation_requests
            WHERE guild_id=? AND requester_id=?
            ORDER BY id DESC
            LIMIT 15
        """, (
            int(guild_id),
            int(user_id)
        )).fetchall()

    icons = {
        "pending": "🕓",
        "approved": "✅",
        "denied": "❌",
        "cancelled": "⚪",
    }

    lines = []
    for row in rows:
        status = str(row["status"])
        lines.append(
            f"{icons.get(status, '•')} **#{row['id']}** "
            f"{platform_icon(row['platform'])} `{row['target']}` "
            f"• **{status.upper()}** • <t:{row['created_at']}:R>"
        )

    return discord.Embed(
        title="🧾 Request Host Saya",
        description=(
            "\n".join(lines)
            if lines
            else "Belum ada riwayat request host."
        ),
        color=discord.Color.blurple()
    )


class HostManagerCancelRequestSelect(discord.ui.Select):
    def __init__(self, user_id: int, guild_id: int):
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)

        rows = pending_host_creation_requests(
            self.guild_id,
            requester_id=self.user_id
        )

        options = [
            discord.SelectOption(
                label=(
                    f"#{row['id']} • {platform_display_name(row['platform'])} "
                    f"• {row['target']}"
                )[:100],
                description="PENDING • pilih untuk membatalkan"[:100],
                value=str(row["id"]),
                emoji="🕓"
            )
            for row in rows[:25]
        ]

        if not options:
            options.append(
                discord.SelectOption(
                    label="Tidak ada request pending",
                    description="Tidak ada request yang bisa dibatalkan.",
                    value="0",
                    emoji="✅"
                )
            )

        super().__init__(
            placeholder="Pilih request yang ingin dibatalkan",
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if int(interaction.user.id) != self.user_id:
            await safe_reply(interaction, "❌ Menu ini bukan milikmu.")
            return

        if not host_manager_has_guild_access(
            self.user_id,
            self.guild_id
        ):
            await safe_reply(
                interaction,
                "🔒 Akses Host Manager server sudah tidak aktif."
            )
            return

        request_id = int(self.values[0])
        if not request_id:
            await safe_reply(
                interaction,
                "ℹ️ Tidak ada request pending."
            )
            return

        row = get_host_creation_request(
            request_id
        )
        if (
            not row
            or row["status"] != "pending"
            or int(row["guild_id"]) != self.guild_id
            or int(row["requester_id"]) != self.user_id
        ):
            await safe_reply(
                interaction,
                "ℹ️ Request sudah diproses atau bukan milikmu."
            )
            return

        if action_rate_limited(
            self.user_id,
            f"cancel_host_request:{request_id}"
        ):
            await safe_reply(
                interaction,
                "⏳ Request sedang diproses."
            )
            return

        finish_host_creation_request(
            request_id,
            status="cancelled",
            actor_id=self.user_id,
            reason="Dibatalkan oleh Host Manager."
        )

        await interaction.response.edit_message(
            content=f"✅ Request host **#{request_id}** dibatalkan.",
            embed=None,
            view=None
        )


class HostManagerCancelRequestsView(discord.ui.View):
    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=600)
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)
        self.add_item(
            HostManagerCancelRequestSelect(
                self.user_id,
                self.guild_id
            )
        )



class HostManagerGuildDashboardView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        guild_id: int,
        page: int = 0
    ):
        super().__init__(timeout=900)
        self.user_id = int(user_id)
        self.guild_id = int(guild_id)
        self.page = max(0, int(page))

        self.add_item(
            HostManagerScopedHostSelect(
                self.user_id,
                self.guild_id,
                self.page
            )
        )

    async def valid(
        self,
        interaction: discord.Interaction
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return False

        if not host_manager_has_guild_access(
            self.user_id,
            self.guild_id
        ):
            await safe_reply(
                interaction,
                "🔒 Akses server sudah tidak tersedia."
            )
            return False

        return True

    @discord.ui.button(
        label="Sebelumnya",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return

        await interaction.response.edit_message(
            embed=host_manager_guild_embed(
                self.user_id,
                self.guild_id
            ),
            view=HostManagerGuildDashboardView(
                self.user_id,
                self.guild_id,
                max(0, self.page - 1)
            )
        )

    @discord.ui.button(
        label="Berikutnya",
        emoji="➡️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def next_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return

        total = len(
            host_manager_hosts_for_guild(
                self.user_id,
                self.guild_id
            )
        )
        max_page = max(0, (total - 1) // 25)

        await interaction.response.edit_message(
            embed=host_manager_guild_embed(
                self.user_id,
                self.guild_id
            ),
            view=HostManagerGuildDashboardView(
                self.user_id,
                self.guild_id,
                min(max_page, self.page + 1)
            )
        )

    @discord.ui.button(
        label="Cari",
        emoji="🔎",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def search(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return

        await interaction.response.send_modal(
            HostManagerSearchModal(
                self.user_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Notif Terakhir",
        emoji="🔔",
        style=discord.ButtonStyle.primary,
        row=2
    )
    async def latest(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return

        await safe_reply(
            interaction,
            "",
            embed=host_manager_latest_embed(
                self.user_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Masalah Host",
        emoji="⚠️",
        style=discord.ButtonStyle.danger,
        row=2
    )
    async def problems(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return

        await safe_reply(
            interaction,
            "",
            embed=host_manager_problems_embed(
                self.user_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Ajukan Host",
        emoji="➕",
        style=discord.ButtonStyle.success,
        row=3
    )
    async def request_new_host(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return

        await interaction.response.send_modal(
            HostManagerAddHostRequestModal(
                self.user_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Riwayat Request",
        emoji="🧾",
        style=discord.ButtonStyle.secondary,
        row=3
    )
    async def my_requests(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return

        await safe_reply(
            interaction,
            "",
            embed=host_manager_pending_requests_embed(
                self.user_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Akses Saya",
        emoji="🔐",
        style=discord.ButtonStyle.secondary,
        row=4
    )
    async def my_access(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return

        await safe_reply(
            interaction,
            "",
            embed=host_manager_server_access_embed(
                self.user_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Batalkan Request",
        emoji="🛑",
        style=discord.ButtonStyle.secondary,
        row=4
    )
    async def cancel_request(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return

        await safe_reply(
            interaction,
            "Pilih request host yang masih **PENDING** untuk dibatalkan.",
            view=HostManagerCancelRequestsView(
                self.user_id,
                self.guild_id
            )
        )

    @discord.ui.button(
        label="Host Saya",
        emoji="🎙️",
        style=discord.ButtonStyle.secondary,
        row=4
    )
    async def host_home(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return

        await interaction.response.edit_message(
            embed=host_manager_home_embed(
                self.user_id
            ),
            view=HostManagerHomeView(
                self.user_id
            )
        )





class HostManagerHomeView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=900)
        self.user_id = int(user_id)
        self.add_item(
            HostManagerGuildSelect(
                self.user_id
            )
        )

    @discord.ui.button(
        label="Notif Terakhir",
        emoji="🔔",
        style=discord.ButtonStyle.primary,
        row=1
    )
    async def latest(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return

        await safe_reply(
            interaction,
            "",
            embed=host_manager_latest_embed(
                self.user_id
            )
        )

    @discord.ui.button(
        label="Masalah Host",
        emoji="⚠️",
        style=discord.ButtonStyle.danger,
        row=1
    )
    async def problems(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return

        await safe_reply(
            interaction,
            "",
            embed=host_manager_problems_embed(
                self.user_id
            )
        )

    @discord.ui.button(
        label="Aktivitas Saya",
        emoji="🧾",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def activity(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return

        await safe_reply(
            interaction,
            "",
            embed=host_manager_activity_embed(
                self.user_id
            )
        )

    @discord.ui.button(
        label="Premium",
        emoji="⭐",
        style=discord.ButtonStyle.success,
        row=2
    )
    async def premium(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return
        guild_ids = premium_purchase_guild_ids(self.user_id)
        if not guild_ids:
            await safe_reply(interaction, "ℹ️ Tidak ada server Host Manager yang dapat dibeli Premium.")
            return
        await interaction.response.edit_message(
            embed=premium_purchase_home_embed(self.user_id),
            view=PremiumGuildPickerView(self.user_id)
        )

    @discord.ui.button(
        label="Bantuan Host",
        emoji="❓",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def help_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return

        await safe_reply(
            interaction,
            "",
            embed=host_manager_help_embed()
        )

    @discord.ui.button(
        label="Menu Pengguna",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def back_user_menu(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return

        await interaction.response.edit_message(
            embed=dm_menu_home_embed(self.user_id),
            view=MenuRoleChoiceView(
                self.user_id
            )
        )


class HostManagerMessageModal(discord.ui.Modal):
    live_message = discord.ui.TextInput(
        label="Pesan LIVE (opsional)",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=1000
    )
    post_message = discord.ui.TextInput(
        label="Pesan Post (opsional)",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=1000
    )
    end_message = discord.ui.TextInput(
        label="Pesan LIVE Selesai (opsional)",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=1000
    )

    def __init__(self, user_id: int, host_id: int):
        super().__init__(
            title="Host Saya • Pesan Notifikasi",
            timeout=300
        )
        self.user_id = int(user_id)
        self.host_id = int(host_id)

        host = get_host(host_id)
        if host:
            self.live_message.default = host["custom_live_message"] or ""
            self.post_message.default = host["custom_post_message"] or ""
            self.end_message.default = host["custom_end_message"] or ""

    async def on_submit(self, interaction: discord.Interaction):
        if (
            interaction.user.id != self.user_id
            or not host_manager_has_permission(
                interaction.user.id,
                self.host_id,
                "edit_messages"
            )
        ):
            await safe_reply(
                interaction,
                "🔒 Kamu tidak punya izin mengubah pesan host ini."
            )
            return

        host = get_host(self.host_id)
        if not host:
            await safe_reply(interaction, "❌ Host tidak ditemukan.")
            return
        if not await require_premium_feature(
            interaction, int(host["guild_id"]), "custom_templates", "Custom pesan"
        ):
            return

        with closing(db()) as conn:
            conn.execute("""
                UPDATE hosts
                SET custom_live_message=?,
                    custom_post_message=?,
                    custom_end_message=?
                WHERE id=?
            """, (
                self.live_message.value.strip() or None,
                self.post_message.value.strip() or None,
                self.end_message.value.strip() or None,
                self.host_id
            ))
            conn.commit()

        log_host_manager_action(
            self.host_id,
            interaction.user.id,
            "edit_messages",
            "Mengubah template notifikasi."
        )

        await safe_reply(
            interaction,
            "✅ Pesan notifikasi host diperbarui."
        )


class HostManagerScheduleModal(discord.ui.Modal):
    days = discord.ui.TextInput(
        label="Hari aktif (0=Senin ... 6=Minggu)",
        placeholder="0,1,2,3,4,5,6",
        max_length=30
    )
    quiet_start = discord.ui.TextInput(
        label="Quiet mulai (HH:MM, kosong=OFF)",
        required=False,
        max_length=5
    )
    quiet_end = discord.ui.TextInput(
        label="Quiet selesai (HH:MM, kosong=OFF)",
        required=False,
        max_length=5
    )
    timezone_input = discord.ui.TextInput(
        label="Timezone",
        placeholder="WIB / WITA / WIT",
        max_length=60
    )

    def __init__(self, user_id: int, host_id: int):
        super().__init__(
            title="Host Saya • Jadwal",
            timeout=300
        )
        self.user_id = int(user_id)
        self.host_id = int(host_id)
        host = get_host(host_id)

        if host:
            self.days.default = host["schedule_days"] or "0,1,2,3,4,5,6"
            self.quiet_start.default = host["quiet_start"] or ""
            self.quiet_end.default = host["quiet_end"] or ""
            self.timezone_input.default = host["timezone"] or "Asia/Jakarta"

    async def on_submit(self, interaction: discord.Interaction):
        if (
            interaction.user.id != self.user_id
            or not host_manager_has_permission(
                interaction.user.id,
                self.host_id,
                "schedule"
            )
        ):
            await safe_reply(
                interaction,
                "🔒 Kamu tidak punya izin mengubah jadwal host ini."
            )
            return

        host = get_host(self.host_id)
        if not host:
            await safe_reply(interaction, "❌ Host tidak ditemukan.")
            return
        if not await require_premium_feature(
            interaction, int(host["guild_id"]), "advanced_schedule", "Jadwal & quiet hours"
        ):
            return

        raw_days = self.days.value.strip()
        day_values = []
        for raw in raw_days.split(","):
            raw = raw.strip()
            if not raw.isdigit() or not 0 <= int(raw) <= 6:
                await safe_reply(
                    interaction,
                    "❌ Hari aktif harus angka 0–6 dipisahkan koma."
                )
                return
            if raw not in day_values:
                day_values.append(raw)

        qs = self.quiet_start.value.strip()
        qe = self.quiet_end.value.strip()
        if bool(qs) != bool(qe):
            await safe_reply(
                interaction,
                "❌ Quiet start dan quiet end harus diisi bersamaan."
            )
            return

        if qs and (not _parse_hhmm(qs) or not _parse_hhmm(qe)):
            await safe_reply(
                interaction,
                "❌ Format quiet hours harus HH:MM."
            )
            return

        tz_raw = self.timezone_input.value.strip() or "WIB"
        tz_alias = {
            "WIB": "Asia/Jakarta",
            "WITA": "Asia/Makassar",
            "WIT": "Asia/Jayapura",
        }
        tz = tz_alias.get(tz_raw.upper(), tz_raw)

        try:
            ZoneInfo(tz)
        except Exception:
            await safe_reply(
                interaction,
                "❌ Timezone tidak valid. Contoh: `Asia/Jakarta`."
            )
            return

        with closing(db()) as conn:
            conn.execute("""
                UPDATE hosts
                SET schedule_days=?,
                    quiet_start=?,
                    quiet_end=?,
                    timezone=?
                WHERE id=?
            """, (
                ",".join(day_values),
                qs or None,
                qe or None,
                tz,
                self.host_id
            ))
            conn.commit()

        log_host_manager_action(
            self.host_id,
            interaction.user.id,
            "schedule",
            f"days={','.join(day_values)} quiet={qs or '-'}-{qe or '-'} tz={tz}"
        )

        await safe_reply(interaction, "✅ Jadwal host diperbarui.")


async def host_manager_recheck(host):
    platform = host["platform"]

    if platform == "youtube":
        try:
            await check_youtube_live(host)
        except Exception:
            await check_youtube_live_fallback(host)
    elif platform == "tiktok":
        await check_tiktok_live(host)
        await check_tiktok_post(host)
    elif platform in {"twitch", "kick"}:
        await check_generic_live(host)
    elif platform in {"instagram", "facebook"}:
        await check_generic_content(host)


class HostManagerHistoryView(discord.ui.View):
    def __init__(self, user_id: int, host_id: int):
        super().__init__(timeout=900)
        self.user_id = int(user_id)
        self.host_id = int(host_id)

    @discord.ui.button(
        label="Kembali ke Host",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if (
            interaction.user.id != self.user_id
            or not host_manager_access(self.user_id, self.host_id)
        ):
            await safe_reply(interaction, "🔒 Akses ditolak.")
            return

        host = get_host(self.host_id)
        await interaction.response.edit_message(
            embed=host_manager_detail_embed(
                host,
                self.user_id
            ),
            view=HostManagerDetailView(
                self.user_id,
                self.host_id
            )
        )


class HostManagerDetailView(discord.ui.View):
    def __init__(self, user_id: int, host_id: int):
        super().__init__(timeout=900)
        self.user_id = int(user_id)
        self.host_id = int(host_id)

    async def valid(
        self,
        interaction: discord.Interaction,
        permission: Optional[str] = None
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return None

        access = host_manager_access(
            interaction.user.id,
            self.host_id
        )

        if not access:
            await safe_reply(
                interaction,
                "🔒 Akses Host Manager sudah dicabut atau kedaluwarsa."
            )
            return None

        if permission and not host_manager_has_permission(
            interaction.user.id,
            self.host_id,
            permission
        ):
            await safe_reply(
                interaction,
                f"🔒 Kamu tidak punya izin `{permission}` untuk host ini."
            )
            return None

        host = get_host(self.host_id)
        if not host:
            await safe_reply(
                interaction,
                "❌ Host tidak ditemukan."
            )
            return None

        return host

    @discord.ui.button(
        label="Pesan",
        emoji="✏️",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def messages(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction, "edit_messages"):
            return
        await interaction.response.send_modal(
            HostManagerMessageModal(
                self.user_id,
                self.host_id
            )
        )

    @discord.ui.button(
        label="Jadwal",
        emoji="🗓️",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def schedule(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction, "schedule"):
            return
        await interaction.response.send_modal(
            HostManagerScheduleModal(
                self.user_id,
                self.host_id
            )
        )

    @discord.ui.button(
        label="Preview",
        emoji="👁️",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def preview(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction)
        if not host:
            return

        live_mode = host["platform"] in {
            "youtube", "tiktok", "twitch", "kick"
        }
        url = host_public_url(host, live=live_mode)

        embed = discord.Embed(
            title=f"🔔 Preview • {platform_display_name(host['platform'])}",
            description=(
                f"Contoh notifikasi untuk "
                f"**{host['display_name'] or host['target']}**."
            ),
            url=url,
            color=discord.Color.blurple()
        )

        await safe_reply(
            interaction,
            "Preview hanya terlihat olehmu.",
            embed=embed
        )

    @discord.ui.button(
        label="Test",
        emoji="🧪",
        style=discord.ButtonStyle.success,
        row=1
    )
    async def test(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction, "test")
        if not host:
            return

        url = host_public_url(
            host,
            live=host["platform"] in {"youtube", "tiktok", "twitch", "kick"}
        )
        embed = discord.Embed(
            title=f"🧪 TEST • {platform_display_name(host['platform'])}",
            description=(
                f"Test notifikasi dari "
                f"**{host['display_name'] or host['target']}**."
            ),
            url=url,
            color=discord.Color.green()
        )

        ok = await send_notification(
            host,
            embed,
            render_template(
                premium_host_template(host, "custom_live_message")
                or premium_host_template(host, "custom_post_message"),
                creator=host["display_name"] or host["target"],
                url=url,
                platform=platform_display_name(host["platform"])
            ),
            event_type="host_manager_test",
            source_url=url
        )

        log_host_manager_action(
            self.host_id,
            interaction.user.id,
            "test",
            f"success={bool(ok)}"
        )

        await safe_reply(
            interaction,
            "✅ Test dikirim." if ok else "❌ Test gagal dikirim."
        )

    @discord.ui.button(
        label="Recheck",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def recheck(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction, "recheck")
        if not host:
            return

        key = f"host_manager_recheck:{self.host_id}"
        if action_rate_limited(interaction.user.id, key):
            await safe_reply(
                interaction,
                "⏳ Recheck terlalu cepat. Tunggu beberapa detik."
            )
            return

        await defer_if_needed(interaction)

        try:
            await host_manager_recheck(host)
            log_host_manager_action(
                self.host_id,
                interaction.user.id,
                "recheck",
                "Manual recheck."
            )
            await interaction.followup.send(
                "✅ Recheck selesai.",
                ephemeral=True
            )
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Recheck gagal: `{type(exc).__name__}: {exc}`",
                ephemeral=True
            )

    @discord.ui.button(
        label="Pause / Resume",
        emoji="⏯️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def pause(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction, "pause")
        if not host:
            return

        action = "mengaktifkan" if not host["enabled"] else "pause"
        await safe_reply(
            interaction,
            (
                f"⚠️ Konfirmasi {action} host "
                f"**{host['display_name'] or host['target']}**?"
            ),
            view=HostPauseConfirmView(
                self.user_id,
                self.host_id
            )
        )

    @discord.ui.button(
        label="Template",
        emoji="🧩",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def template(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction, "edit_messages"):
            return

        await safe_reply(
            interaction,
            "🧩 Pilih preset atau reset ke default.",
            view=HostTemplatePresetView(
                self.user_id,
                self.host_id
            )
        )

    @discord.ui.button(
        label="Pin / Favorit",
        emoji="⭐",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def favorite(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction)
        if not host:
            return

        pref = host_manager_pref(
            self.user_id,
            self.host_id
        )
        current = bool(
            pref and pref["favorite"]
        )
        set_host_manager_favorite(
            self.user_id,
            self.host_id,
            not current
        )
        log_host_manager_action(
            self.host_id,
            self.user_id,
            "favorite",
            f"favorite={not current}"
        )

        await safe_reply(
            interaction,
            (
                "⭐ Host dipin ke bagian atas daftar."
                if not current
                else "✅ Pin host dilepas."
            )
        )

    @discord.ui.button(
        label="History",
        emoji="🕘",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def history(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction, "history")
        if not host:
            return

        analytics_days = int(premium_entitlements(int(host["guild_id"]))["analytics_days"])
        cutoff = int(time.time()) - analytics_days * 86400
        with closing(db()) as conn:
            rows = conn.execute("""
                SELECT *
                FROM notification_history
                WHERE host_id=? AND created_at>=?
                ORDER BY id DESC
                LIMIT 10
            """, (self.host_id, cutoff)).fetchall()

        if rows:
            lines = []
            for row in rows:
                icon = "✅" if row["status"] == "sent" else (
                    "⏳" if row["status"] == "queued" else "❌"
                )
                lines.append(
                    f"{icon} <t:{row['created_at']}:R> • "
                    f"`{row['event_type'] or 'notification'}` • "
                    f"{row['status']}"
                )
            description = "\n".join(lines)
        else:
            description = "Belum ada riwayat notifikasi."

        embed = discord.Embed(
            title="🕘 History Host Saya",
            description=description,
            color=discord.Color.blurple()
        )
        embed.set_footer(
            text=f"History {analytics_days} hari • hanya host yang ditugaskan kepadamu."
        )

        await interaction.response.edit_message(
            embed=embed,
            view=HostManagerHistoryView(
                self.user_id,
                self.host_id
            )
        )

    @discord.ui.button(
        label="Refresh",
        emoji="📊",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def refresh(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        host = await self.valid(interaction)
        if not host:
            return

        await interaction.response.edit_message(
            embed=host_manager_detail_embed(
                host,
                self.user_id
            ),
            view=HostManagerDetailView(
                self.user_id,
                self.host_id
            )
        )

    @discord.ui.button(
        label="Semua Host Server",
        emoji="🌐",
        style=discord.ButtonStyle.secondary,
        row=3
    )
    async def all_server_hosts(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return

        host = await self.valid(interaction)
        if not host:
            return

        guild_id = int(host["guild_id"])

        await interaction.response.edit_message(
            embed=host_manager_all_hosts_embed(
                self.user_id,
                guild_id
            ),
            view=HostManagerAllHostsView(
                self.user_id,
                guild_id
            )
        )

    @discord.ui.button(
        label="Host Saya",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=3
    )
    async def back_hosts(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return

        await interaction.response.edit_message(
            embed=host_manager_home_embed(
                self.user_id
            ),
            view=HostManagerHomeView(
                self.user_id
            )
        )

    @discord.ui.button(
        label="Menu Pengguna",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=3
    )
    async def user_home(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return

        await interaction.response.edit_message(
            embed=dm_menu_home_embed(self.user_id),
            view=MenuRoleChoiceView(self.user_id)
        )


class HostTemplatePresetView(discord.ui.View):
    def __init__(self, user_id: int, host_id: int):
        super().__init__(timeout=600)
        self.user_id = int(user_id)
        self.host_id = int(host_id)

    async def apply(
        self,
        interaction: discord.Interaction,
        preset: str
    ):
        if (
            interaction.user.id != self.user_id
            or not host_manager_has_permission(
                self.user_id,
                self.host_id,
                "edit_messages"
            )
        ):
            await safe_reply(
                interaction,
                "🔒 Kamu tidak punya izin mengubah template."
            )
            return

        host = get_host(self.host_id)
        if not host:
            await safe_reply(interaction, "❌ Host tidak ditemukan.")
            return
        if not await require_premium_feature(
            interaction, int(host["guild_id"]), "custom_templates", "Template Premium"
        ):
            return

        apply_host_template_preset(
            self.host_id,
            preset
        )

        log_host_manager_action(
            self.host_id,
            self.user_id,
            "template_preset",
            preset
        )

        await safe_reply(
            interaction,
            "✅ Template notifikasi diperbarui."
        )

    @discord.ui.button(
        label="LIVE Simple",
        emoji="🔴",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def live_simple(self, interaction, button):
        await self.apply(interaction, "live_simple")

    @discord.ui.button(
        label="LIVE Hype",
        emoji="🎉",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def live_hype(self, interaction, button):
        await self.apply(interaction, "live_hype")

    @discord.ui.button(
        label="Post Simple",
        emoji="🆕",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def post_simple(self, interaction, button):
        await self.apply(interaction, "post_simple")

    @discord.ui.button(
        label="Live End",
        emoji="⚫",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def end_simple(self, interaction, button):
        await self.apply(interaction, "end_simple")

    @discord.ui.button(
        label="Reset Default",
        emoji="♻️",
        style=discord.ButtonStyle.danger,
        row=2
    )
    async def reset(self, interaction, button):
        await self.apply(interaction, "reset")


class HostPauseConfirmView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        host_id: int
    ):
        super().__init__(timeout=120)
        self.user_id = int(user_id)
        self.host_id = int(host_id)

    @discord.ui.button(
        label="Ya, Ubah Status",
        emoji="✅",
        style=discord.ButtonStyle.danger
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if (
            interaction.user.id != self.user_id
            or not host_manager_has_permission(
                self.user_id,
                self.host_id,
                "pause"
            )
        ):
            await safe_reply(
                interaction,
                "🔒 Akses ditolak."
            )
            return

        enabled = toggle_host(self.host_id)
        log_host_manager_action(
            self.host_id,
            self.user_id,
            "pause_resume",
            f"enabled={enabled}"
        )

        await interaction.response.edit_message(
            content=(
                "✅ Host sekarang **AKTIF**."
                if enabled
                else "⏸️ Host sekarang **PAUSE**."
            ),
            embed=None,
            view=None
        )

    @discord.ui.button(
        label="Batal",
        emoji="✖️",
        style=discord.ButtonStyle.secondary
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.user_id:
            await safe_reply(interaction, "❌ Panel ini bukan milikmu.")
            return

        await interaction.response.edit_message(
            content="Dibatalkan.",
            embed=None,
            view=None
        )


class HostAccessRequestDecisionView(discord.ui.View):
    def __init__(
        self,
        request_id: int,
        guild_id: int
    ):
        super().__init__(timeout=None)
        self.request_id = int(request_id)
        self.guild_id = int(guild_id)
        self.approve.custom_id = f"hin:host_access:{self.request_id}:approve"
        self.deny.custom_id = f"hin:host_access:{self.request_id}:deny"

    async def valid_owner(
        self,
        interaction: discord.Interaction
    ):
        guild = bot.get_guild(self.guild_id)
        if (
            guild is None
            or int(guild.owner_id) != int(interaction.user.id)
        ):
            await safe_reply(
                interaction,
                "🔒 Hanya owner server terkait yang dapat memproses request ini."
            )
            return None
        return guild

    async def finish(
        self,
        interaction: discord.Interaction,
        approved: bool
    ):
        if not await self.valid_owner(interaction):
            return

        row = get_host_access_request(
            self.request_id
        )
        if not row or row["status"] != "pending":
            await safe_reply(
                interaction,
                "ℹ️ Request ini sudah diproses."
            )
            return

        ok = process_host_access_request(
            self.request_id,
            approved=approved,
            actor_id=interaction.user.id
        )

        if not ok:
            await safe_reply(
                interaction,
                "❌ Request gagal diproses."
            )
            return

        try:
            user = bot.get_user(int(row["user_id"])) or await bot.fetch_user(
                int(row["user_id"])
            )
            await user.send(
                f"{'✅' if approved else '❌'} Request akses Host #{row['host_id']} "
                f"{'disetujui' if approved else 'ditolak'} oleh owner server."
            )
        except Exception:
            pass

        await interaction.response.edit_message(
            content=(
                "✅ Request disetujui."
                if approved
                else "❌ Request ditolak."
            ),
            embed=None,
            view=None
        )

    @discord.ui.button(
        label="Setujui",
        emoji="✅",
        style=discord.ButtonStyle.success
    )
    async def approve(self, interaction, button):
        await self.finish(interaction, True)

    @discord.ui.button(
        label="Tolak",
        emoji="❌",
        style=discord.ButtonStyle.danger
    )
    async def deny(self, interaction, button):
        await self.finish(interaction, False)



class AssignHostManagerModal(discord.ui.Modal):
    user_id_input = discord.ui.TextInput(
        label="Discord User ID",
        placeholder="Contoh: 123456789012345678",
        max_length=25
    )
    permissions_input = discord.ui.TextInput(
        label="Izin (pisahkan koma)",
        placeholder="edit_messages,schedule,pause,recheck,history,test",
        default="edit_messages,schedule,pause,recheck,history,test",
        max_length=120
    )
    expiry_days = discord.ui.TextInput(
        label="Masa akses hari (kosong=permanen)",
        required=False,
        placeholder="30",
        max_length=5
    )

    def __init__(self, host_id: int):
        super().__init__(
            title="Owner • Assign Host Manager",
            timeout=300
        )
        self.host_id = int(host_id)

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return

        raw_user = self.user_id_input.value.strip()
        if not raw_user.isdigit():
            await safe_reply(
                interaction,
                "❌ Discord User ID harus angka."
            )
            return

        user_id = int(raw_user)
        requested = {
            x.strip().lower()
            for x in self.permissions_input.value.split(",")
            if x.strip()
        }
        invalid = requested - set(HOST_MANAGER_PERMISSION_COLUMNS)
        if invalid:
            await safe_reply(
                interaction,
                "❌ Izin tidak valid: " + ", ".join(sorted(invalid))
            )
            return

        expires_at = None
        raw_expiry = self.expiry_days.value.strip()
        if raw_expiry:
            if not raw_expiry.isdigit() or int(raw_expiry) < 1:
                await safe_reply(
                    interaction,
                    "❌ Masa akses harus jumlah hari."
                )
                return
            expires_at = int(time.time()) + int(raw_expiry) * 86400

        assign_host_manager(
            self.host_id,
            user_id,
            assigned_by=interaction.user.id,
            permissions=requested,
            expires_at=expires_at
        )

        host = get_host(self.host_id)
        try:
            user = bot.get_user(user_id) or await bot.fetch_user(user_id)
            await user.send(
                embed=discord.Embed(
                    title="🎙️ Kamu ditambahkan sebagai Host Manager",
                    description=(
                        f"Host: **{platform_display_name(host['platform'])} • "
                        f"{host['display_name'] or host['target']}**\n\n"
                        "Buka DM bot dan gunakan **`/menu` → `🎙️ Host Saya`**.\n"
                        "Akses Host Manager terpisah dari panel Owner."
                    ),
                    color=discord.Color.blurple()
                )
            )
        except Exception:
            pass

        await safe_reply(
            interaction,
            (
                f"✅ <@{user_id}> ditambahkan sebagai Host Manager.\n"
                f"Izin: `{', '.join(sorted(requested)) or 'read-only'}`"
            )
        )


class RevokeHostManagerModal(discord.ui.Modal):
    user_id_input = discord.ui.TextInput(
        label="Discord User ID yang dicabut",
        max_length=25
    )

    def __init__(self, host_id: int):
        super().__init__(
            title="Owner • Revoke Host Manager",
            timeout=300
        )
        self.host_id = int(host_id)

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return

        raw = self.user_id_input.value.strip()
        if not raw.isdigit():
            await safe_reply(interaction, "❌ ID harus angka.")
            return

        user_id = int(raw)
        revoke_host_manager(
            self.host_id,
            user_id
        )

        await safe_reply(
            interaction,
            f"✅ Akses Host Manager <@{user_id}> dicabut."
        )


class OwnerHostManagerView(discord.ui.View):
    def __init__(self, guild_id: int, host_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)
        self.host_id = int(host_id)

    async def valid(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return False
        host = get_host(self.host_id)
        if not host or int(host["guild_id"]) != self.guild_id:
            await safe_reply(interaction, "❌ Host tidak ditemukan.")
            return False
        return True

    @discord.ui.button(
        label="Tambah / Update Manager",
        emoji="➕",
        style=discord.ButtonStyle.success,
        row=0
    )
    async def add_manager(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return
        await interaction.response.send_modal(
            AssignHostManagerModal(self.host_id)
        )

    @discord.ui.button(
        label="Cabut Manager",
        emoji="➖",
        style=discord.ButtonStyle.danger,
        row=0
    )
    async def revoke_manager(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return
        await interaction.response.send_modal(
            RevokeHostManagerModal(self.host_id)
        )

    @discord.ui.button(
        label="Daftar Manager",
        emoji="👥",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def list_managers(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return

        rows = list_host_managers(self.host_id)
        if rows:
            lines = []
            now = int(time.time())
            for row in rows:
                expiry = (
                    f"<t:{row['expires_at']}:R>"
                    if row["expires_at"]
                    else "Permanen"
                )
                status = (
                    "aktif"
                    if not row["expires_at"] or row["expires_at"] > now
                    else "kedaluwarsa"
                )
                lines.append(
                    f"• <@{row['user_id']}> • {status} • {expiry}"
                )
            description = "\n".join(lines[:25])
        else:
            description = "Belum ada Host Manager."

        await safe_reply(
            interaction,
            "",
            embed=discord.Embed(
                title="👥 Host Manager",
                description=description,
                color=discord.Color.blue()
            )
        )

    @discord.ui.button(
        label="Kembali ke Host Owner",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not await self.valid(interaction):
            return

        host = get_host(self.host_id)
        await interaction.response.edit_message(
            embed=host_embed(host),
            view=HostCardView(
                self.guild_id,
                self.host_id
            )
        )



class PaymentMethodSelect(discord.ui.Select):
    def __init__(self, order_id: int):
        self.order_id = order_id
        methods = list_payment_methods(True)

        options = []

        for method in methods[:25]:
            kind = "QRIS" if method["method_type"] == "qris" else "Rekening / E-Wallet"

            options.append(
                discord.SelectOption(
                    label=method["method_name"][:100],
                    value=str(method["id"]),
                    description=kind
                )
            )

        if not options:
            options = [
                discord.SelectOption(
                    label="Belum ada metode pembayaran",
                    value="0"
                )
            ]

        super().__init__(
            placeholder="Pilih metode pembayaran...",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        method_id = int(self.values[0])

        if method_id == 0:
            await safe_reply(
                interaction,
                "⚠️ Owner belum menambahkan metode pembayaran."
            )
            return

        order = get_premium_order(self.order_id)

        if not order:
            await safe_reply(interaction, "❌ Request tidak ditemukan.")
            return

        if int(order["requester_id"]) != interaction.user.id:
            await safe_reply(interaction, "❌ Ini bukan request milikmu.")
            return

        assign_order_payment_method(
            self.order_id,
            method_id
        )

        order = get_premium_order(self.order_id)
        method = get_payment_method(method_id)

        embed = payment_method_embed(method, order)
        qris_file = apply_qris_attachment_image(embed, method)

        if qris_file:
            await interaction.response.edit_message(
                embed=embed,
                attachments=[qris_file],
                view=PaymentConfirmView(self.order_id)
            )
        else:
            await interaction.response.edit_message(
                embed=embed,
                attachments=[],
                view=PaymentConfirmView(self.order_id)
            )


class PaymentMethodSelectView(discord.ui.View):
    def __init__(self, order_id: int):
        super().__init__(timeout=900)
        self.order_id = int(order_id)
        self.add_item(PaymentMethodSelect(order_id))

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        order = get_premium_order(self.order_id)

        if not order:
            await safe_reply(interaction, "❌ Request tidak ditemukan.")
            return

        if int(order["requester_id"]) != int(interaction.user.id):
            await safe_reply(interaction, "🔒 Invoice ini bukan milikmu.")
            return

        guild = await require_premium_purchaser(
            interaction, int(order["guild_id"])
        )
        if not guild:
            return

        await interaction.response.edit_message(
            embed=premium_plan_summary_embed(guild),
            attachments=[],
            view=UserPremiumView(guild.id, interaction.user.id)
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=dm_menu_home_embed(interaction.user.id),
            attachments=[],
            view=MenuRoleChoiceView(interaction.user.id)
        )


class PaymentProofDetailsModal(discord.ui.Modal):
    sender_name = discord.ui.TextInput(
        label="Nama Pengirim",
        placeholder="Nama pada rekening/e-wallet pengirim",
        max_length=120
    )
    sender_account = discord.ui.TextInput(
        label="Rekening / Nomor Pengirim",
        placeholder="Nomor rekening/e-wallet pengirim",
        max_length=120
    )
    transfer_time = discord.ui.TextInput(
        label="Waktu Transfer",
        placeholder="Contoh: 05-10-2026 02:15 WIB",
        max_length=100
    )
    reference = discord.ui.TextInput(
        label="No. Referensi / Transaksi",
        placeholder="Nomor referensi dari aplikasi pembayaran",
        max_length=160
    )
    amount = discord.ui.TextInput(
        label="Nominal pada Bukti",
        placeholder="Contoh: 25137",
        max_length=15
    )

    def __init__(self, order_id: int):
        super().__init__(
            title="Detail Bukti Transfer",
            timeout=300
        )
        self.order_id = int(order_id)

    async def on_submit(self, interaction: discord.Interaction):
        order = get_premium_order(self.order_id)

        if not order:
            await safe_reply(interaction, "❌ Invoice tidak ditemukan.")
            return

        if int(order["requester_id"]) != int(interaction.user.id):
            await safe_reply(interaction, "🔒 Invoice ini bukan milikmu.")
            return

        raw_amount = (
            self.amount.value
            .strip()
            .replace(".", "")
            .replace(",", "")
            .replace("Rp", "")
            .replace("rp", "")
            .replace(" ", "")
        )

        if not raw_amount.isdigit():
            await safe_reply(interaction, "❌ Nominal harus berupa angka.")
            return

        try:
            save_payment_proof_details(
                self.order_id,
                sender_name=self.sender_name.value,
                sender_account=self.sender_account.value,
                transfer_time=self.transfer_time.value,
                reference=self.reference.value,
                declared_amount=int(raw_amount)
            )
        except ValueError as exc:
            await safe_reply(interaction, f"❌ {exc}")
            return

        await safe_reply(
            interaction,
            (
                "✅ Detail transfer disimpan.\n\n"
                f"Invoice: `{order['invoice_ref'] or ensure_invoice_ref(order['id'])}`\n"
                f"Harga paket: **{rupiah(int(order['price']))}**\n"
                f"Kode unik: **{int(order['unique_code'] or 0):03d}**\n"
                f"Total transfer wajib: **{rupiah(int(order['expected_amount'] or order['price']))}**\n"
                f"Pengirim: **{self.sender_name.value.strip()}**\n"
                f"Rekening: `{mask_account(self.sender_account.value)}`\n"
                f"Referensi: `{self.reference.value.strip()}`\n\n"
                "📎 Sekarang kirim **1 screenshot bukti transfer asli** "
                "sebagai attachment ke DM bot ini.\n\n"
                + payment_proof_instruction_text()
                + "\n\nBot akan melakukan screening otomatis sebelum bukti diteruskan."
            )
        )




class PaymentConfirmView(discord.ui.View):
    def __init__(self, order_id: int):
        super().__init__(timeout=900)
        self.order_id = order_id

    @discord.ui.button(
        label="Saya Sudah Bayar",
        emoji="✅",
        style=discord.ButtonStyle.success
    )
    async def paid(self, interaction: discord.Interaction, button: discord.ui.Button):
        order = get_premium_order(self.order_id)

        if not order:
            await safe_reply(interaction, "❌ Request tidak ditemukan.")
            return

        if int(order["requester_id"]) != interaction.user.id:
            await safe_reply(
                interaction,
                "❌ Tombol ini hanya untuk user yang membuat request."
            )
            return

        if order["status"] != "pending":
            await safe_reply(
                interaction,
                f"ℹ️ Status request saat ini: **{order_status_label(order['status'])}**"
            )
            return

        if not order["payment_method_id"]:
            await safe_reply(
                interaction,
                "❌ Pilih metode pembayaran terlebih dahulu."
            )
            return

        await interaction.response.send_modal(
            PaymentProofDetailsModal(self.order_id)
        )

    @discord.ui.button(
        label="Invoice",
        emoji="🧾",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def invoice(self, interaction: discord.Interaction, button: discord.ui.Button):
        order = get_premium_order(self.order_id)

        if not order or int(order["requester_id"]) != interaction.user.id:
            await safe_reply(interaction, "❌ Invoice tidak ditemukan.")
            return

        await defer_if_needed(interaction, ephemeral=True)

        try:
            image_bytes = await asyncio.to_thread(
                invoice_image_bytes,
                order
            )
            invoice_ref = order["invoice_ref"] or ensure_invoice_ref(order["id"])
            await interaction.followup.send(
                content=f"🧾 `{invoice_ref}`",
                file=discord.File(
                    io.BytesIO(image_bytes),
                    filename=f"{invoice_ref}.png"
                ),
                ephemeral=True
            )
        except Exception as exc:
            await report_interaction_error(
                interaction,
                exc,
                context="invoice_image"
            )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        order = get_premium_order(self.order_id)

        if not order:
            await safe_reply(interaction, "❌ Request tidak ditemukan.")
            return

        embed = discord.Embed(
            title=f"💳 Pilih Metode Pembayaran • #{self.order_id}",
            description=(
                f"📅 Paket: **{order['days']} hari**\n"
                f"💰 Harga: **{rupiah(order['price'])}**\n"
                f"💳 Transfer tepat: **{rupiah(int(order['expected_amount'] or order['price']))}**"
            ),
            color=discord.Color.gold()
        )

        await interaction.response.edit_message(
            embed=embed,
            attachments=[],
            view=PaymentMethodSelectView(self.order_id)
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=dm_menu_home_embed(interaction.user.id),
            attachments=[],
            view=MenuRoleChoiceView(interaction.user.id)
        )


class GuildSelect(discord.ui.Select):
    def __init__(self, page: int = 0, query: str = ""):
        self.page = max(0, int(page))
        self.query = query.strip().lower()

        guilds = list(bot.guilds)

        if self.query:
            guilds = [
                g for g in guilds
                if self.query in g.name.lower()
                or self.query in str(g.id)
            ]

        self.filtered_count = len(guilds)
        page_size = 25
        start = self.page * page_size
        page_guilds = guilds[start:start + page_size]

        options = [
            discord.SelectOption(
                label=g.name[:100],
                value=str(g.id),
                description=f"ID: {g.id}"[:100]
            )
            for g in page_guilds
        ]

        if not options:
            options = [
                discord.SelectOption(
                    label="Tidak ada server di halaman ini",
                    value="0"
                )
            ]

        super().__init__(
            placeholder=f"Pilih server • Halaman {self.page + 1}",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return

        guild_id = int(self.values[0])

        if guild_id == 0:
            await safe_reply(interaction, "❌ Server tidak ditemukan.")
            return

        guild = bot.get_guild(guild_id)

        if not guild:
            await safe_reply(interaction, "❌ Server tidak ditemukan.")
            return

        await interaction.response.edit_message(
            embed=server_embed(guild),
            view=ServerOwnerView(guild.id)
        )


class ServerSearchModal(discord.ui.Modal):
    query = discord.ui.TextInput(
        label="Nama Server / Server ID",
        placeholder="Contoh: Notif Server atau 123456...",
        max_length=100
    )

    def __init__(self):
        super().__init__(title="Cari Server", timeout=300)

    async def on_submit(self, interaction: discord.Interaction):
        q = self.query.value.strip()
        guilds = [
            g for g in bot.guilds
            if q.lower() in g.name.lower()
            or q in str(g.id)
        ]

        embed = discord.Embed(
            title="🔎 Hasil Pencarian Server",
            description=(
                f"Ditemukan **{len(guilds)}** server untuk `{q}`."
            ),
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=ServerBrowserView(0, q)
        )


class ServerBrowserView(discord.ui.View):
    def __init__(self, page: int = 0, query: str = ""):
        super().__init__(timeout=900)
        self.page = max(0, page)
        self.query = query
        self.add_item(GuildSelect(self.page, self.query))

    @discord.ui.button(label="Sebelumnya", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            view=ServerBrowserView(max(0, self.page - 1), self.query)
        )

    @discord.ui.button(label="Berikutnya", emoji="➡️", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            view=ServerBrowserView(self.page + 1, self.query)
        )

    @discord.ui.button(label="Cari", emoji="🔎", style=discord.ButtonStyle.secondary, row=1)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ServerSearchModal())

    @discord.ui.button(label="Reset", emoji="♻️", style=discord.ButtonStyle.secondary, row=1)
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            view=ServerBrowserView(0, "")
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )





def plan_overview_embed():
    free_guilds = guilds_by_plan("free")
    premium_guilds = guilds_by_plan("premium")

    embed = discord.Embed(
        title="📊 Daftar Server FREE / PREMIUM",
        description=(
            f"🆓 **FREE:** {len(free_guilds)} server\n"
            f"⭐ **PREMIUM:** {len(premium_guilds)} server"
        ),
        color=discord.Color.blue()
    )

    free_lines = [
        f"• **{g.name}**\n  ID: `{g.id}`"
        for g in free_guilds[:15]
    ]
    if len(free_guilds) > 15:
        free_lines.append(f"…dan **{len(free_guilds)-15} server lainnya**.")

    premium_lines = []
    for g in premium_guilds[:15]:
        settings = get_guild_settings(g.id)
        expires_at = settings["premium_expires_at"]
        expiry = f"<t:{int(expires_at)}:R>" if expires_at else "Tanpa expiry"
        premium_lines.append(
            f"• **{g.name}**\n"
            f"  ID: `{g.id}`\n"
            f"  Expiry: {expiry}"
        )
    if len(premium_guilds) > 15:
        premium_lines.append(f"…dan **{len(premium_guilds)-15} server lainnya**.")

    embed.add_field(
        name="🆓 Server FREE",
        value=("\n".join(free_lines) or "Belum ada server FREE.")[:1024],
        inline=False
    )
    embed.add_field(
        name="⭐ Server PREMIUM",
        value=("\n".join(premium_lines) or "Belum ada server PREMIUM.")[:1024],
        inline=False
    )
    embed.set_footer(text="Pilihan submenu dibuat abu-abu agar lebih rapi.")
    return embed

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class PlanOverviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_global_owner(interaction):
            return
        await interaction.response.edit_message(
            embed=plan_overview_embed(),
            view=PlanOverviewView()
        )

    @discord.ui.button(label="Server Free", emoji="🆓", style=discord.ButtonStyle.secondary, row=0)
    async def free_servers(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_global_owner(interaction):
            return
        guilds = guilds_by_plan("free")
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🆓 Server FREE",
                description=f"Total: **{len(guilds)} server**",
                color=discord.Color.blue()
            ),
            view=PlanListView("free")
        )

    @discord.ui.button(label="Server Premium", emoji="⭐", style=discord.ButtonStyle.secondary, row=0)
    async def premium_servers(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_global_owner(interaction):
            return
        guilds = guilds_by_plan("premium")
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⭐ Server PREMIUM",
                description=f"Total: **{len(guilds)} server**",
                color=discord.Color.gold()
            ),
            view=PlanListView("premium")
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )



def owner_dashboard_embed():
    orders = premium_order_counts()
    free_guilds = guilds_by_plan("free")
    premium_guilds = guilds_by_plan("premium")

    expiring_7d = 0
    now = int(time.time())

    for guild in premium_guilds:
        try:
            settings = get_guild_settings(guild.id)
            expires_at = settings["premium_expires_at"]
            if expires_at and 0 < int(expires_at) - now <= 7 * 86400:
                expiring_7d += 1
        except Exception:
            pass

    total_hosts = 0
    enabled_hosts = 0
    error_hosts = 0
    youtube_hosts = 0
    tiktok_hosts = 0
    other_hosts = 0

    for guild in bot.guilds:
        try:
            for host in get_hosts(guild.id):
                total_hosts += 1
                enabled_hosts += 1 if host["enabled"] else 0
                error_hosts += 1 if host["last_error"] else 0
                youtube_hosts += 1 if host["platform"] == "youtube" else 0
                tiktok_hosts += 1 if host["platform"] == "tiktok" else 0
                other_hosts += 1 if host["platform"] not in {"youtube", "tiktok"} else 0
        except Exception:
            pass

    embed = discord.Embed(
        title="📊 Dashboard Owner",
        description="Ringkasan operasional Hi Notifku.",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="Server",
        value=(
            f"Total: **{len(bot.guilds)}**\n"
            f"FREE: **{len(free_guilds)}**\n"
            f"PREMIUM: **{len(premium_guilds)}**"
        ),
        inline=True
    )
    embed.add_field(
        name="Premium",
        value=(
            f"Pending: **{orders['pending']}**\n"
            f"Bukti: **{orders['proof_submitted']}**\n"
            f"Nominal Sesuai: **{orders['amount_verified']}**\n"
            f"Dibayar: **{orders['paid']}**\n"
            f"Expired ≤7 hari: **{expiring_7d}**"
        ),
        inline=True
    )
    embed.add_field(
        name="Host",
        value=(
            f"Aktif: **{enabled_hosts}/{total_hosts}**\n"
            f"TikTok: **{tiktok_hosts}**\n"
            f"YouTube: **{youtube_hosts}**\n"
            f"Error: **{error_hosts}**"
        ),
        inline=True
    )

    try:
        disk = shutil.disk_usage(".")
        embed.add_field(
            name="Storage",
            value=(
                f"{human_bytes(disk.used)} / {human_bytes(disk.total)}\n"
                f"Sisa: **{human_bytes(disk.free)}**"
            ),
            inline=False
        )
    except Exception:
        pass

    rev = revenue_stats()

    embed.add_field(
        name="💰 Omzet Hari Ini",
        value=(
            f"**{rupiah(rev['today'])}**\n"
            f"{rev['orders_today']} transaksi"
        ),
        inline=True
    )
    embed.add_field(
        name="📅 Omzet 30 Hari",
        value=f"**{rupiah(rev['month'])}**",
        inline=True
    )
    embed.add_field(
        name="🏆 Paket Terlaris",
        value=rev["best_package"],
        inline=True
    )

    embed.set_footer(text="Gunakan tombol submenu untuk melihat detail.")
    return embed

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class PremiumOrderSelect(discord.ui.Select):
    def __init__(self):
        orders = list_premium_orders((
            "pending", "proof_submitted", "amount_mismatch",
            "underpaid", "overpaid", "amount_verified",
            "paid", "late_payment"
        ), 25)

        options = []

        for order in orders:
            guild = bot.get_guild(int(order["guild_id"]))
            guild_name = guild.name if guild else str(order["guild_id"])
            options.append(
                discord.SelectOption(
                    label=f"#{order['id']} • {guild_name}"[:100],
                    value=str(order["id"]),
                    description=(
                        f"{order_status_label(order['status'])} • "
                        f"{order['days']} hari • {rupiah(order['price'])}"
                    )[:100]
                )
            )

        if not options:
            options = [
                discord.SelectOption(
                    label="Tidak ada request pending",
                    value="0"
                )
            ]

        super().__init__(
            placeholder="Pilih Premium request...",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return

        order_id = int(self.values[0])

        if order_id == 0:
            await safe_reply(interaction, "✅ Tidak ada request yang perlu diproses.")
            return

        order = get_premium_order(order_id)

        if not order:
            await safe_reply(interaction, "❌ Request tidak ditemukan.")
            return

        await interaction.response.edit_message(
            embed=premium_order_embed(order),
            view=PremiumOrderManageView(order_id)
        )


class PremiumOrdersView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)
        self.add_item(PremiumOrderSelect())

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = premium_queue_embed()
        await interaction.response.edit_message(
            embed=embed,
            view=PremiumOrdersView()
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class RejectPremiumModal(discord.ui.Modal):
    reason = discord.ui.TextInput(
        label="Alasan Penolakan",
        placeholder="Contoh: bukti tidak valid / nominal tidak masuk",
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    def __init__(self, order_id: int):
        super().__init__(title="Tolak Premium Request", timeout=300)
        self.order_id = order_id

    async def on_submit(self, interaction: discord.Interaction):
        if not owner_has_level(interaction.user.id, "payment_admin"):
            await safe_reply(interaction, "❌ Akses Payment Admin diperlukan.")
            return

        order = get_premium_order(self.order_id)

        if not order:
            await safe_reply(interaction, "❌ Request tidak ditemukan.")
            return

        with closing(db()) as conn:
            conn.execute("""
                UPDATE premium_orders
                SET
                    status='rejected',
                    rejection_reason=?,
                    processed_by=?,
                    updated_at=?
                WHERE id=?
            """, (
                self.reason.value[:500],
                interaction.user.id,
                int(time.time()),
                self.order_id
            ))
            conn.commit()

        add_activity(
            order["guild_id"],
            interaction.user.id,
            "Premium Rejected",
            f"Order #{self.order_id}: {self.reason.value[:300]}"
        )

        await notify_order_user(
            order,
            (
                f"❌ Premium request **#{self.order_id}** ditolak.\n"
                f"Alasan: **{self.reason.value}**"
            )
        )

        await safe_reply(
            interaction,
            f"✅ Request #{self.order_id} ditolak."
        )


class OwnerOrderNoteModal(discord.ui.Modal):
    note = discord.ui.TextInput(
        label="Catatan Owner",
        placeholder="Catatan internal untuk transaksi ini",
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    def __init__(self, order_id: int):
        super().__init__(title="Catatan Transaksi", timeout=300)
        self.order_id = order_id

    async def on_submit(self, interaction: discord.Interaction):
        if not owner_has_level(interaction.user.id, "payment_admin"):
            await safe_reply(interaction, "❌ Akses Payment Admin diperlukan.")
            return

        with closing(db()) as conn:
            conn.execute("""
                UPDATE premium_orders
                SET owner_note=?, updated_at=?
                WHERE id=?
            """, (
                self.note.value[:500],
                int(time.time()),
                self.order_id
            ))
            conn.commit()

        await safe_reply(interaction, "✅ Catatan transaksi disimpan.")


class PaymentOverrideModal(discord.ui.Modal):
    reason = discord.ui.TextInput(
        label="Alasan Override",
        placeholder="Jelaskan kenapa transaksi perlu diaktifkan manual.",
        style=discord.TextStyle.paragraph,
        min_length=10,
        max_length=500
    )

    def __init__(self, order_id: int):
        super().__init__(title="Manual Payment Override", timeout=300)
        self.order_id = int(order_id)

    async def on_submit(self, interaction):
        if owner_role(interaction.user.id) != "super_owner":
            await safe_reply(
                interaction,
                "🔒 Override hanya untuk Super Owner."
            )
            return

        order = get_premium_order(self.order_id)
        if not order:
            await safe_reply(interaction, "❌ Invoice tidak ditemukan.")
            return

        if order["activated_at"] or str(order["status"]) == "active":
            await safe_reply(
                interaction,
                "ℹ️ Premium invoice ini sudah aktif."
            )
            return

        if str(order["status"]) in {"refunded", "refund_pending"}:
            await safe_reply(
                interaction,
                "❌ Invoice sedang/sudah dalam proses refund."
            )
            return

        create_rollback_snapshot(
            int(order["guild_id"]),
            "payment_manual_override",
            interaction.user.id
        )

        expected = int(order["expected_amount"] or order["price"])
        received = order["received_amount"]

        if received is None or int(received) != expected:
            await safe_reply(
                interaction,
                "❌ Override tetap membutuhkan nominal masuk yang persis sesuai invoice."
            )
            return

        with closing(db()) as conn:
            conn.execute("""
                UPDATE premium_orders
                SET
                    amount_verified=1,
                    payment_verified_at=?,
                    override_reason=?,
                    status='amount_verified',
                    updated_at=?
                WHERE id=?
            """, (
                int(time.time()),
                self.reason.value.strip()[:500],
                int(time.time()),
                self.order_id
            ))
            conn.commit()

        record_premium_event(
            self.order_id,
            "manual_override",
            actor_id=interaction.user.id,
            detail=self.reason.value.strip()
        )

        try:
            ok, msg = await activate_verified_premium_order(
                self.order_id,
                actor_id=interaction.user.id,
                source="super_owner_manual_override",
                require_proof=False
            )
        except Exception as exc:
            await safe_reply(
                interaction,
                f"❌ Override gagal: `{type(exc).__name__}: {exc}`"
            )
            return

        await safe_reply(
            interaction,
            "✅ Override berhasil dan Premium aktif." if ok else f"⚠️ {msg}"
        )


class PremiumOrderManageView(discord.ui.View):
    def __init__(self, order_id: int):
        super().__init__(timeout=900)
        self.order_id = int(order_id)

    async def get_actionable(
        self,
        interaction: discord.Interaction,
        *,
        require_verified: bool = False,
        require_proof: bool = False
    ):
        if not owner_has_level(interaction.user.id, "payment_admin"):
            await safe_reply(
                interaction,
                "❌ Akses Payment Admin diperlukan."
            )
            return None

        order = get_premium_order(self.order_id)

        if not order:
            await safe_reply(interaction, "❌ Request tidak ditemukan.")
            return None

        if not order_is_actionable(order):
            await safe_reply(
                interaction,
                "ℹ️ Request sudah diproses, kedaluwarsa, atau tidak aktif."
            )
            return None

        if require_proof and not order["proof_url"]:
            await safe_reply(interaction, "❌ Bukti pembayaran belum dikirim.")
            return None

        if require_verified and not int(order["amount_verified"] or 0):
            await safe_reply(
                interaction,
                "❌ Nominal transfer belum dinyatakan sesuai."
            )
            return None

        return order

    @discord.ui.button(
        label="Cek Nominal",
        emoji="🔢",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def check_amount(self, interaction: discord.Interaction, button: discord.ui.Button):
        order = await self.get_actionable(interaction)
        if not order:
            return

        await interaction.response.send_modal(
            ReceivedAmountModal(self.order_id)
        )

    @discord.ui.button(
        label="Dibayar",
        emoji="💵",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def mark_paid(self, interaction: discord.Interaction, button: discord.ui.Button):
        order = await self.get_actionable(
            interaction,
            require_verified=True
        )
        if not order:
            return

        update_order_status(
            self.order_id,
            "paid",
            processed_by=interaction.user.id
        )

        add_activity(
            int(order["guild_id"]),
            interaction.user.id,
            "Premium Payment",
            f"{order['invoice_ref'] or ensure_invoice_ref(order['id'])} dibayar."
        )

        await audit_webhook(
            "Payment Marked Paid",
            order["invoice_ref"] or ensure_invoice_ref(order["id"]),
            actor_id=interaction.user.id,
            guild_id=int(order["guild_id"])
        )

        await safe_reply(
            interaction,
            "✅ Pembayaran ditandai **Dibayar**."
        )

    @discord.ui.button(
        label="Terima & Aktif",
        emoji="✅",
        style=discord.ButtonStyle.success,
        row=0
    )
    async def approve_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        order = await self.get_actionable(
            interaction,
            require_verified=True,
            require_proof=True
        )
        if not order:
            return

        await defer_if_needed(interaction, ephemeral=True)

        try:
            ok, message = await activate_verified_premium_order(
                self.order_id,
                actor_id=interaction.user.id,
                source="manual_owner_approval"
            )

            if ok:
                await interaction.followup.send(
                    "✅ Premium berhasil diaktifkan.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"⚠️ {message}",
                    ephemeral=True
                )

        except Exception as exc:
            await report_interaction_error(
                interaction,
                exc,
                context="premium_activation"
            )

    @discord.ui.button(
        label="Tolak",
        emoji="✖️",
        style=discord.ButtonStyle.danger,
        row=1
    )
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        order = await self.get_actionable(interaction)
        if not order:
            return

        await interaction.response.send_modal(
            RejectPremiumModal(self.order_id)
        )

    @discord.ui.button(
        label="Override",
        emoji="🛡️",
        style=discord.ButtonStyle.danger,
        row=1
    )
    async def override(self, interaction: discord.Interaction, button: discord.ui.Button):
        if owner_role(interaction.user.id) != "super_owner":
            await safe_reply(interaction, "🔒 Override hanya untuk Super Owner.")
            return
        await interaction.response.send_modal(
            PaymentOverrideModal(self.order_id)
        )

    @discord.ui.button(
        label="Catatan",
        emoji="📝",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def owner_note(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not owner_has_level(interaction.user.id, "payment_admin"):
            await safe_reply(
                interaction,
                "❌ Akses Payment Admin diperlukan."
            )
            return

        await interaction.response.send_modal(
            OwnerOrderNoteModal(self.order_id)
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        counts = premium_order_counts()

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="💳 Request Premium",
                description=(
                    f"Pending **{counts['pending']}** • "
                    f"Bukti **{counts.get('proof_submitted', 0)}** • "
                    f"Dibayar **{counts['paid']}**"
                ),
                color=discord.Color.gold()
            ),
            view=PremiumOrdersView()
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class TransactionHistoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=transaction_history_embed(),
            view=TransactionHistoryView()
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )



def revenue_embed():
    stats = revenue_stats()

    embed = discord.Embed(
        title="💰 Laporan Pendapatan",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="Hari Ini",
        value=f"**{rupiah(stats['today'])}**\n{stats['orders_today']} transaksi",
        inline=True
    )
    embed.add_field(
        name="30 Hari",
        value=f"**{rupiah(stats['month'])}**",
        inline=True
    )
    embed.add_field(
        name="Total",
        value=f"**{rupiah(stats['total'])}**",
        inline=True
    )
    embed.add_field(
        name="Paket Terlaris",
        value=stats["best_package"],
        inline=True
    )
    embed.add_field(
        name="Metode Terpopuler",
        value=stats["best_method"],
        inline=True
    )
    return embed

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class RevenueReportView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(label="Export CSV", emoji="📥", style=discord.ButtonStyle.success)
    async def export_csv(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not owner_has_level(interaction.user.id, "payment_admin"):
            await safe_reply(interaction, "❌ Akses Payment Admin diperlukan.")
            return

        data = export_transactions_csv_bytes()
        file = discord.File(
            io.BytesIO(data),
            filename=f"hi-notifku-transaksi-{int(time.time())}.csv"
        )

        await interaction.response.send_message(
            "📊 Export transaksi:",
            file=file,
            ephemeral=True
        )

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=revenue_embed(),
            view=RevenueReportView()
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class HealthDetailView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=health_detail_embed(),
            view=HealthDetailView()
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class OwnerDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_dashboard_embed(),
            view=OwnerDashboardView()
        )

    @discord.ui.button(label="Health Detail", emoji="🛠️", style=discord.ButtonStyle.secondary, row=0)
    async def health_detail(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=health_detail_embed(),
            view=HealthDetailView()
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class OwnerAccessCenterView(discord.ui.View):
    def __init__(self, viewer_id: int):
        super().__init__(timeout=900)
        self.viewer_id = int(viewer_id)

    async def valid(
        self,
        interaction: discord.Interaction,
        minimum: str = "read_only"
    ) -> bool:
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(
                interaction,
                "🔒 Panel Global Owner ini bukan milikmu."
            )
            return False

        return await require_owner_level(
            interaction,
            minimum
        )

    @discord.ui.button(
        label="Refresh Akses",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return

        await interaction.response.edit_message(
            embed=global_owner_access_embed(
                self.viewer_id
            ),
            view=OwnerAccessCenterView(
                self.viewer_id
            )
        )

    @discord.ui.button(
        label="Audit Request",
        emoji="📨",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def requests(self, interaction, button):
        if not await self.valid(interaction):
            return

        await interaction.response.edit_message(
            embed=global_request_audit_embed(),
            view=OwnerReadOnlyAuditView(
                self.viewer_id
            )
        )

    @discord.ui.button(
        label="Backup Status",
        emoji="🗄️",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def backup(self, interaction, button):
        if not await self.valid(interaction):
            return

        await interaction.response.edit_message(
            embed=owner_backup_status_embed(),
            view=OwnerReadOnlyAuditView(
                self.viewer_id
            )
        )

    @discord.ui.button(
        label="Kelola Global Owner",
        emoji="🛡️",
        style=discord.ButtonStyle.danger,
        row=1
    )
    async def manage_global_owner(self, interaction, button):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel ini bukan milikmu.")
            return

        if not is_primary_owner(interaction.user.id):
            await safe_reply(
                interaction,
                "🔒 Hanya **Primary Global Owner** dari `OWNER_IDS`."
            )
            return

        all_owners = OWNER_IDS | db_owner_ids()
        embed = discord.Embed(
            title="🛡️ Kelola Global Owner Bot",
            description=(
                "\n".join(
                    f"• <@{uid}> (`{uid}`) • **{owner_role(uid)}**"
                    for uid in sorted(all_owners)
                )
                or "Tidak ada Global Owner."
            ),
            color=discord.Color.gold()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=OwnerManagementView()
        )

    @discord.ui.button(
        label="Menu Owner",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def home(self, interaction, button):
        if not await self.valid(interaction):
            return

        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView(
                self.viewer_id
            )
        )


class OwnerReadOnlyAuditView(discord.ui.View):
    def __init__(self, viewer_id: int):
        super().__init__(timeout=900)
        self.viewer_id = int(viewer_id)

    @discord.ui.button(
        label="Security & Access",
        emoji="🛡️",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def access(self, interaction, button):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel ini bukan milikmu.")
            return
        if not await require_global_owner(interaction):
            return

        await interaction.response.edit_message(
            embed=global_owner_access_embed(
                self.viewer_id
            ),
            view=OwnerAccessCenterView(
                self.viewer_id
            )
        )

    @discord.ui.button(
        label="Menu Owner",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def home(self, interaction, button):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel ini bukan milikmu.")
            return
        if not await require_global_owner(interaction):
            return

        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView(
                self.viewer_id
            )
        )






class PaymentRefundModal(discord.ui.Modal):
    invoice_ref = discord.ui.TextInput(
        label="Invoice",
        placeholder="INV-YYYYMMDD-XXXXXX",
        max_length=80
    )
    status_input = discord.ui.TextInput(
        label="Status Refund",
        placeholder="pending / refunded / failed",
        max_length=20
    )
    reason = discord.ui.TextInput(
        label="Alasan / Catatan",
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    def __init__(self):
        super().__init__(title="Update Refund", timeout=300)

    async def on_submit(self, interaction):
        if not owner_has_level(interaction.user.id, "payment_admin"):
            await safe_reply(interaction, "🔒 Akses Payment Admin diperlukan.")
            return

        order = get_order_by_invoice_ref(self.invoice_ref.value.strip())
        if not order:
            await safe_reply(interaction, "❌ Invoice tidak ditemukan.")
            return

        if str(order["status"]) == "refunded":
            await safe_reply(
                interaction,
                "ℹ️ Invoice ini sudah berstatus **refunded**."
            )
            return

        raw = self.status_input.value.strip().lower()
        mapping = {
            "pending": "refund_pending",
            "refunded": "refunded",
            "failed": "refund_failed",
        }
        target = mapping.get(raw)
        if not target:
            await safe_reply(
                interaction,
                "❌ Status harus pending / refunded / failed."
            )
            return

        current = str(order["status"])
        if not payment_transition_allowed(current, target):
            await safe_reply(
                interaction,
                f"❌ Transisi `{current}` → `{target}` tidak valid."
            )
            return

        now = int(time.time())

        with closing(db()) as conn:
            conn.execute("""
                UPDATE premium_orders
                SET
                    status=?,
                    refund_status=?,
                    refund_reason=?,
                    refunded_at=CASE WHEN ?='refunded' THEN ? ELSE refunded_at END,
                    processed_by=?,
                    updated_at=?
                WHERE id=?
            """, (
                target,
                target,
                self.reason.value.strip()[:500],
                target,
                now,
                interaction.user.id,
                now,
                int(order["id"])
            ))
            conn.commit()

        record_premium_event(
            int(order["id"]),
            target,
            actor_id=interaction.user.id,
            detail=self.reason.value.strip()
        )

        await safe_reply(
            interaction,
            f"✅ Refund `{order['invoice_ref']}` → **{target}**."
        )


class PaymentTestModal(discord.ui.Modal):
    invoice_ref = discord.ui.TextInput(
        label="Invoice",
        placeholder="INV-YYYYMMDD-XXXXXX",
        max_length=80
    )
    amount = discord.ui.TextInput(
        label="Nominal Simulasi",
        placeholder="25137",
        max_length=15
    )

    def __init__(self):
        super().__init__(title="Payment Test Mode", timeout=300)

    async def on_submit(self, interaction):
        if not owner_has_level(interaction.user.id, "payment_admin"):
            await safe_reply(interaction, "🔒 Akses Payment Admin diperlukan.")
            return

        order = get_order_by_invoice_ref(self.invoice_ref.value.strip())
        if not order:
            await safe_reply(interaction, "❌ Invoice tidak ditemukan.")
            return

        raw = self.amount.value.strip().replace(".", "").replace(",", "")
        if not raw.isdigit():
            await safe_reply(interaction, "❌ Nominal harus angka.")
            return

        expected = int(order["expected_amount"] or order["price"])
        amount = int(raw)

        await safe_reply(
            interaction,
            (
                "🧪 **Test Mode — tidak mengubah transaksi**\n"
                f"Invoice: `{order['invoice_ref']}`\n"
                f"Expected: **{rupiah(expected)}**\n"
                f"Simulasi: **{rupiah(amount)}**\n"
                f"Hasil: **{'MATCH' if amount == expected else 'MISMATCH'}**"
            )
        )


class OwnerBasicBackView(discord.ui.View):
    def __init__(self, viewer_id: int):
        super().__init__(timeout=900)
        self.viewer_id = int(viewer_id)

    async def valid(self, interaction):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel ini bukan milikmu.")
            return False
        return await require_global_owner(interaction)

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🧰 Owner Operations",
                description="Pilih pusat operasi Global Owner.",
                color=discord.Color.blurple()
            ),
            view=OwnerOpsHomeView(self.viewer_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=4)
    async def home(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView(self.viewer_id)
        )

class PaymentCenterView(OwnerBasicBackView):
    @discord.ui.button(label="Health", emoji="🩺", style=discord.ButtonStyle.secondary, row=0)
    async def health(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=payment_health_embed(),
            view=PaymentCenterView(self.viewer_id)
        )

    @discord.ui.button(label="Settlement", emoji="💰", style=discord.ButtonStyle.secondary, row=0)
    async def settlement(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=payment_settlement_embed(),
            view=PaymentCenterView(self.viewer_id)
        )

    @discord.ui.button(label="Reconcile", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def reconcile(self, interaction, button):
        if not await self.valid(interaction):
            return

        await defer_if_needed(interaction, ephemeral=True)

        with closing(db()) as conn:
            rows = conn.execute("""
                SELECT id
                FROM premium_orders
                WHERE activated_at IS NULL
                  AND amount_verified=1
                  AND status IN ('amount_verified','paid')
                  AND proof_url IS NOT NULL
                ORDER BY updated_at ASC
                LIMIT 50
            """).fetchall()

        activated = 0
        for row in rows:
            try:
                ok, _ = await maybe_auto_activate_verified_order(
                    int(row["id"]),
                    actor_id=interaction.user.id,
                    source="manual_reconciliation"
                )
                if ok:
                    activated += 1
            except Exception:
                log.exception(
                    "Manual payment reconciliation gagal order_id=%s",
                    row["id"]
                )

        await interaction.followup.send(
            f"✅ Reconciliation selesai. Premium diaktifkan: **{activated}**.",
            ephemeral=True
        )

    @discord.ui.button(label="Refund", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)
    async def refund(self, interaction, button):
        if not owner_has_level(interaction.user.id, "payment_admin"):
            await safe_reply(interaction, "🔒 Akses Payment Admin diperlukan.")
            return
        await interaction.response.send_modal(PaymentRefundModal())

    @discord.ui.button(label="Test", emoji="🧪", style=discord.ButtonStyle.secondary, row=1)
    async def test(self, interaction, button):
        if not owner_has_level(interaction.user.id, "payment_admin"):
            await safe_reply(interaction, "🔒 Akses Payment Admin diperlukan.")
            return
        await interaction.response.send_modal(PaymentTestModal())

    @discord.ui.button(label="Event DLQ", emoji="📮", style=discord.ButtonStyle.secondary, row=1)
    async def event_dlq(self, interaction, button):
        if not await self.valid(interaction):
            return

        await safe_reply(
            interaction,
            (
                f"📮 Payment event DLQ open: **{payment_event_dlq_count()}**\n"
                f"Retry otomatis maksimal **{PAYMENT_EVENT_MAX_RETRIES}x**."
            )
        )


def record_incident(incident_key: str, incident_type: str, title: str, detail: str, *, status: str = "open") -> int:
    now = int(time.time())
    with closing(db()) as conn:
        existing = conn.execute("""
            SELECT id FROM incident_history
            WHERE incident_key=? AND status IN ('open','investigating')
            ORDER BY id DESC LIMIT 1
        """, (incident_key,)).fetchone()
        if existing:
            conn.execute("""
                UPDATE incident_history SET detail=?, updated_at=? WHERE id=?
            """, (str(detail)[:2000], now, int(existing["id"])))
            conn.commit()
            return int(existing["id"])
        cur = conn.execute("""
            INSERT INTO incident_history(
                incident_key, incident_type, title, detail,
                status, opened_at, updated_at
            ) VALUES(?,?,?,?,?,?,?)
        """, (
            str(incident_key)[:200], str(incident_type)[:80],
            str(title)[:200], str(detail)[:2000], status, now, now
        ))
        conn.commit()
        return int(cur.lastrowid)


def update_incident_status(incident_id: int, status: str, actor_id: int):
    allowed = {"open", "investigating", "resolved", "ignored"}
    status = str(status).lower().strip()
    if status not in allowed:
        raise ValueError("Status incident tidak valid.")
    now = int(time.time())
    with closing(db()) as conn:
        conn.execute("""
            UPDATE incident_history
            SET status=?, updated_at=?, acknowledged_by=?, acknowledged_at=?,
                resolved_at=CASE WHEN ?='resolved' THEN ? ELSE resolved_at END
            WHERE id=?
        """, (
            status, now, int(actor_id), now, status, now, int(incident_id)
        ))
        conn.commit()


def recent_incidents(limit: int = 15):
    with closing(db()) as conn:
        return conn.execute("""
            SELECT * FROM incident_history ORDER BY id DESC LIMIT ?
        """, (max(1, min(50, int(limit))),)).fetchall()


class IncidentStatusModal(discord.ui.Modal):
    incident_id = discord.ui.TextInput(label="Incident ID", max_length=12)
    status_input = discord.ui.TextInput(
        label="Status",
        placeholder="investigating / resolved / ignored",
        max_length=20
    )

    def __init__(self):
        super().__init__(title="Update Incident", timeout=300)

    async def on_submit(self, interaction):
        if not await require_owner_level(interaction, "server_admin"):
            return
        if not self.incident_id.value.strip().isdigit():
            await safe_reply(interaction, "❌ Incident ID harus angka.")
            return
        try:
            update_incident_status(
                int(self.incident_id.value),
                self.status_input.value,
                interaction.user.id
            )
        except ValueError as exc:
            await safe_reply(interaction, f"❌ {exc}")
            return
        await safe_reply(interaction, "✅ Status incident diperbarui.")


def incident_center_embed():
    now = int(time.time())

    with closing(db()) as conn:
        platform_rows = conn.execute("""
            SELECT * FROM platform_incidents
            WHERE state='outage'
            ORDER BY updated_at DESC
        """).fetchall()

        dlq = conn.execute("""
            SELECT COUNT(*) AS total
            FROM notification_dead_letter
            WHERE resolved_at IS NULL
        """).fetchone()

        payment_dlq = conn.execute("""
            SELECT COUNT(*) AS total
            FROM payment_event_dead_letter
            WHERE resolved_at IS NULL
        """).fetchone()

        host_errors = conn.execute("""
            SELECT COUNT(*) AS total
            FROM hosts
            WHERE last_error IS NOT NULL AND last_error<>''
        """).fetchone()

    lines = []
    for row in platform_rows[:10]:
        lines.append(
            f"🌐 **{platform_display_name(row['platform'])}** • "
            f"{int(row['error_hosts'] or 0)}/{int(row['total_hosts'] or 0)} host error • "
            f"<t:{int(row['updated_at'])}:R>"
        )

    if not lines:
        lines.append("✅ Tidak ada platform outage aktif.")

    stats = sqlite_storage_stats()

    embed = discord.Embed(
        title="🚨 Incident Center",
        description="\n".join(lines),
        color=discord.Color.orange() if platform_rows else discord.Color.green()
    )
    embed.add_field(
        name="Antrian Masalah",
        value=(
            f"Notification DLQ: **{int(dlq['total'] or 0)}**\n"
            f"Payment DLQ: **{int(payment_dlq['total'] or 0)}**\n"
            f"Host error: **{int(host_errors['total'] or 0)}**"
        ),
        inline=True
    )
    embed.add_field(
        name="SQLite",
        value=(
            f"DB **{stats['db_bytes']/1024/1024:.1f} MB**\n"
            f"WAL **{stats['wal_bytes']/1024/1024:.1f} MB**"
        ),
        inline=True
    )
    recent = recent_incidents(8)
    recent_text = "\n".join(
        f"#{row['id']} • **{row['status']}** • {str(row['title'])[:60]} • "
        f"<t:{int(row['updated_at'])}:R>"
        for row in recent
    ) or "Belum ada incident history."
    embed.add_field(
        name="Incident History",
        value=recent_text[:1024],
        inline=False
    )
    embed.set_footer(text="Incident Center • status operasional terpusat")
    return embed


class OwnerIncidentCenterView(OwnerBasicBackView):
    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=incident_center_embed(),
            view=OwnerIncidentCenterView(self.viewer_id)
        )

    @discord.ui.button(label="Update Incident", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def update_incident(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.send_modal(IncidentStatusModal())

    @discord.ui.button(label="Checkpoint DB", emoji="🗃️", style=discord.ButtonStyle.secondary, row=0)
    async def checkpoint(self, interaction, button):
        if not await self.valid(interaction):
            return
        if not await require_owner_level(interaction, "server_admin"):
            return
        with closing(db()) as conn:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            conn.commit()
        await safe_reply(interaction, "✅ SQLite checkpoint selesai.")


class RuntimeTuningModal(discord.ui.Modal):
    monitor_concurrency = discord.ui.TextInput(
        label="Monitor Concurrency", placeholder="5", max_length=2
    )
    notification_retries = discord.ui.TextInput(
        label="Notification Max Retries", placeholder="3", max_length=2
    )
    error_threshold = discord.ui.TextInput(
        label="Error Alert Threshold", placeholder="5", max_length=3
    )
    circuit_minutes = discord.ui.TextInput(
        label="Circuit Breaker (menit)", placeholder="10", max_length=2
    )

    def __init__(self):
        super().__init__(title="Runtime Tuning", timeout=300)
        row = get_runtime_tuning()
        self.monitor_concurrency.default = str(row["monitor_concurrency"])
        self.notification_retries.default = str(row["notification_max_retries"])
        self.error_threshold.default = str(row["error_alert_threshold"])
        self.circuit_minutes.default = str(row["circuit_breaker_minutes"])

    async def on_submit(self, interaction):
        if not await require_owner_level(interaction, "super_owner"):
            return
        values = [
            self.monitor_concurrency.value,
            self.notification_retries.value,
            self.error_threshold.value,
            self.circuit_minutes.value,
        ]
        if not all(str(v).strip().isdigit() for v in values):
            await safe_reply(interaction, "❌ Semua nilai harus berupa angka.")
            return

        saved = update_runtime_tuning(
            monitor_concurrency=int(self.monitor_concurrency.value),
            notification_max_retries=int(self.notification_retries.value),
            error_alert_threshold=int(self.error_threshold.value),
            circuit_breaker_minutes=int(self.circuit_minutes.value),
            actor_id=interaction.user.id
        )
        await safe_reply(
            interaction,
            (
                "✅ Runtime tuning diperbarui.\n"
                f"Concurrency **{saved['monitor_concurrency']}** • "
                f"Retry **{saved['notification_max_retries']}** • "
                f"Threshold **{saved['error_alert_threshold']}** • "
                f"Circuit **{saved['circuit_breaker_minutes']}m**"
            )
        )


def runtime_tuning_embed():
    row = get_runtime_tuning()
    return discord.Embed(
        title="⚙️ Runtime Tuning",
        description=(
            f"Monitor concurrency: **{row['monitor_concurrency']}**\n"
            f"Notification retries: **{row['notification_max_retries']}**\n"
            f"Error threshold: **{row['error_alert_threshold']}**\n"
            f"Circuit breaker: **{row['circuit_breaker_minutes']} menit**"
        ),
        color=discord.Color.blurple()
    )


class OwnerRuntimeTuningView(OwnerBasicBackView):
    @discord.ui.button(label="Edit", emoji="⚙️", style=discord.ButtonStyle.primary, row=0)
    async def edit(self, interaction, button):
        if not await self.valid(interaction):
            return
        if not await require_owner_level(interaction, "super_owner"):
            return
        await interaction.response.send_modal(RuntimeTuningModal())

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=runtime_tuning_embed(),
            view=OwnerRuntimeTuningView(self.viewer_id)
        )


def sanitize_backup_for_new_server(data: dict) -> dict:
    payload = json.loads(json.dumps(data, ensure_ascii=False))
    cfg = payload.get("guild_config") or {}
    cfg["youtube_channel_id"] = None
    cfg["tiktok_channel_id"] = None
    cfg["mention_role_id"] = None
    cfg["log_channel_id"] = None

    for host in payload.get("hosts") or []:
        host["channel_id"] = None
        host["role_id"] = None
        host["extra_channel_ids"] = None
        host["extra_role_ids"] = None
        host["webhook_url"] = None

    return payload


def migrate_server_configuration(source_guild_id: int, target_guild_id: int, actor_id: int) -> int:
    if int(source_guild_id) == int(target_guild_id):
        raise ValueError("Source dan target tidak boleh sama.")

    source = bot.get_guild(int(source_guild_id))
    target = bot.get_guild(int(target_guild_id))
    if not source or not target:
        raise ValueError("Source/target server harus sedang terhubung ke bot.")

    create_rollback_snapshot(int(target_guild_id), "before_server_migration", actor_id)
    data = sanitize_backup_for_new_server(export_guild_backup(int(source_guild_id)))
    return restore_guild_backup(data, int(target_guild_id))


class ServerMigrationModal(discord.ui.Modal):
    source_id = discord.ui.TextInput(label="Source Server ID", max_length=24)
    target_id = discord.ui.TextInput(label="Target Server ID", max_length=24)
    confirm_text = discord.ui.TextInput(
        label="Konfirmasi", placeholder="Ketik MIGRATE", max_length=20
    )

    def __init__(self):
        super().__init__(title="Server Migration", timeout=300)

    async def on_submit(self, interaction):
        if not await require_owner_level(interaction, "server_admin"):
            return
        if not (self.source_id.value.strip().isdigit() and self.target_id.value.strip().isdigit()):
            await safe_reply(interaction, "❌ Server ID harus angka.")
            return
        if self.confirm_text.value.strip().upper() != "MIGRATE":
            await safe_reply(interaction, "❌ Ketik `MIGRATE` untuk konfirmasi.")
            return
        try:
            restored = migrate_server_configuration(
                int(self.source_id.value), int(self.target_id.value), interaction.user.id
            )
        except Exception as exc:
            await safe_reply(interaction, f"❌ Migration gagal: `{type(exc).__name__}: {exc}`")
            return
        await safe_reply(
            interaction,
            (
                f"✅ Server migration selesai. **{restored} host** dipindahkan.\n"
                "Channel/role/webhook sengaja dikosongkan karena ID Discord "
                "tidak dapat dipakai lintas server."
            )
        )


class HostCloneModal(discord.ui.Modal):
    target_guild_id = discord.ui.TextInput(label="Target Server ID", max_length=24)

    def __init__(self, source_host_id: int, actor_id: int):
        super().__init__(title="Clone Host", timeout=300)
        self.source_host_id = int(source_host_id)
        self.actor_id = int(actor_id)

    async def on_submit(self, interaction):
        if int(interaction.user.id) != self.actor_id:
            await safe_reply(interaction, "🔒 Modal ini bukan milikmu.")
            return
        raw = self.target_guild_id.value.strip()
        if not raw.isdigit():
            await safe_reply(interaction, "❌ Server ID harus angka.")
            return

        source = get_host(self.source_host_id)
        if not source:
            await safe_reply(interaction, "❌ Host sumber tidak ditemukan.")
            return

        target_guild_id = int(raw)
        target = bot.get_guild(target_guild_id)
        if not target:
            await safe_reply(interaction, "❌ Target server tidak ditemukan.")
            return

        if not is_global_owner(interaction.user.id) and int(target.owner_id) != int(interaction.user.id):
            await safe_reply(interaction, "🔒 Kamu hanya dapat clone ke server milikmu sendiri.")
            return

        try:
            add_host(
                target_guild_id,
                str(source["platform"]),
                str(source["target"]),
                source["display_name"],
                source["extra"]
            )
            with closing(db()) as conn:
                cloned = conn.execute("""
                    SELECT id FROM hosts
                    WHERE guild_id=? AND platform=? AND target=?
                """, (
                    target_guild_id, source["platform"], source["target"]
                )).fetchone()
            if not cloned:
                raise RuntimeError("Clone host tidak ditemukan setelah dibuat.")
            clone_id = int(cloned["id"])
            with closing(db()) as conn:
                conn.execute("""
                    UPDATE hosts SET
                        custom_live_message=?, custom_post_message=?, custom_end_message=?,
                        notify_live_end=?, check_interval=?, schedule_days=?,
                        quiet_start=?, quiet_end=?, timezone=?, language=?,
                        embed_title=?, embed_footer=?, embed_color=?,
                        auto_pause_threshold=?, channel_id=NULL, role_id=NULL,
                        extra_channel_ids=NULL, extra_role_ids=NULL, webhook_url=NULL
                    WHERE id=?
                """, (
                    source["custom_live_message"], source["custom_post_message"],
                    source["custom_end_message"], source["notify_live_end"],
                    source["check_interval"], source["schedule_days"],
                    source["quiet_start"], source["quiet_end"],
                    source["timezone"], source["language"], source["embed_title"],
                    source["embed_footer"], source["embed_color"],
                    source["auto_pause_threshold"], clone_id
                ))
                conn.commit()
        except Exception as exc:
            await safe_reply(interaction, f"❌ Clone gagal: `{type(exc).__name__}: {exc}`")
            return

        await safe_reply(interaction, f"✅ Host berhasil di-clone sebagai Host **#{clone_id}**.")


class OwnerOpsHomeView(discord.ui.View):
    def __init__(self, viewer_id: int):
        super().__init__(timeout=900)
        self.viewer_id = int(viewer_id)

    async def valid(self, interaction, minimum="read_only"):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel ini bukan milikmu.")
            return False
        return await require_owner_level(interaction, minimum)

    @discord.ui.button(label="Self Test", emoji="🧪", style=discord.ButtonStyle.primary, row=0)
    async def self_test(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_self_test_embed(),
            view=OwnerSelfTestView(self.viewer_id)
        )

    @discord.ui.button(label="Error Center", emoji="🚨", style=discord.ButtonStyle.danger, row=0)
    async def errors(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_error_center_embed(),
            view=OwnerErrorCenterView(self.viewer_id)
        )

    @discord.ui.button(label="Notification", emoji="🔔", style=discord.ButtonStyle.secondary, row=0)
    async def notifications(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_notification_center_embed(),
            view=OwnerNotificationCenterView(self.viewer_id)
        )

    @discord.ui.button(label="API / Quota", emoji="📡", style=discord.ButtonStyle.secondary, row=1)
    async def quota(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_quota_embed(),
            view=OwnerQuotaView(self.viewer_id)
        )

    @discord.ui.button(label="Audit Log", emoji="🧾", style=discord.ButtonStyle.secondary, row=1)
    async def audit(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_audit_embed(),
            view=OwnerAuditView(self.viewer_id)
        )

    @discord.ui.button(label="Backup", emoji="🗄️", style=discord.ButtonStyle.secondary, row=1)
    async def backup(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_backup_center_embed(),
            view=OwnerBackupCenterView(self.viewer_id)
        )

    @discord.ui.button(label="Platform", emoji="🌐", style=discord.ButtonStyle.secondary, row=2)
    async def platform_health(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_platform_health_embed(),
            view=OwnerPlatformHealthView(self.viewer_id)
        )

    @discord.ui.button(label="Risk", emoji="🛡️", style=discord.ButtonStyle.secondary, row=2)
    async def risk(self, interaction, button):
        if not await self.valid(interaction, "server_admin"):
            return
        await interaction.response.edit_message(
            embed=owner_risk_embed(),
            view=OwnerRiskView(self.viewer_id)
        )

    @discord.ui.button(label="Emergency", emoji="🚨", style=discord.ButtonStyle.danger, row=2)
    async def emergency(self, interaction, button):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel ini bukan milikmu.")
            return
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "🔒 Emergency hanya untuk **Primary Global Owner**.")
            return
        await interaction.response.edit_message(
            embed=owner_emergency_embed(),
            view=OwnerEmergencyView(self.viewer_id)
        )

    @discord.ui.button(label="Integrity", emoji="🧰", style=discord.ButtonStyle.secondary, row=3)
    async def integrity(self, interaction, button):
        if not await self.valid(interaction, "server_admin"):
            return
        await interaction.response.edit_message(
            embed=owner_integrity_embed(),
            view=OwnerIntegrityView(self.viewer_id)
        )

    @discord.ui.button(label="Verification", emoji="✅", style=discord.ButtonStyle.secondary, row=3)
    async def verification(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=verification_dashboard_embed(),
            view=OwnerVerificationDashboardView(self.viewer_id)
        )

    @discord.ui.button(label="DLQ", emoji="📮", style=discord.ButtonStyle.secondary, row=3)
    async def dlq(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=dead_letter_embed(),
            view=OwnerDeadLetterView(self.viewer_id)
        )

    @discord.ui.button(label="Advanced", emoji="⚙️", style=discord.ButtonStyle.primary, row=4)
    async def advanced(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⚙️ Advanced Operations",
                description="Payment • Incident • Runtime • Migration • Diagnostics",
                color=discord.Color.blurple()
            ),
            view=OwnerOpsAdvancedView(self.viewer_id)
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView(self.viewer_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=4)
    async def home(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView(self.viewer_id)
        )


class OwnerOpsAdvancedView(discord.ui.View):
    def __init__(self, viewer_id: int):
        super().__init__(timeout=900)
        self.viewer_id = int(viewer_id)

    async def valid(self, interaction, minimum="read_only"):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel ini bukan milikmu.")
            return False
        return await require_owner_level(interaction, minimum)

    @discord.ui.button(label="Payment", emoji="💳", style=discord.ButtonStyle.secondary, row=0)
    async def payment(self, interaction, button):
        if not await self.valid(interaction, "payment_admin"):
            return
        await interaction.response.edit_message(
            embed=payment_health_embed(),
            view=PaymentCenterView(self.viewer_id)
        )

    @discord.ui.button(label="Incidents", emoji="🚨", style=discord.ButtonStyle.secondary, row=0)
    async def incidents(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=incident_center_embed(),
            view=OwnerIncidentCenterView(self.viewer_id)
        )

    @discord.ui.button(label="Runtime", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0)
    async def runtime_tuning(self, interaction, button):
        if not await self.valid(interaction, "server_admin"):
            return
        await interaction.response.edit_message(
            embed=runtime_tuning_embed(),
            view=OwnerRuntimeTuningView(self.viewer_id)
        )

    @discord.ui.button(label="Migration", emoji="🚚", style=discord.ButtonStyle.secondary, row=0)
    async def migration(self, interaction, button):
        if not await self.valid(interaction, "server_admin"):
            return
        await interaction.response.send_modal(ServerMigrationModal())

    @discord.ui.button(label="Diagnostics", emoji="📦", style=discord.ButtonStyle.secondary, row=0)
    async def diagnostics(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="📦 Diagnostics",
                description="Buat bundle diagnosis tanpa secret untuk debugging Railway.",
                color=discord.Color.blurple()
            ),
            view=OwnerDiagnosticsView(self.viewer_id)
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🧰 Owner Operations",
                description="Operasional, keamanan, monitoring, dan maintenance bot.",
                color=discord.Color.blurple()
            ),
            view=OwnerOpsHomeView(self.viewer_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView(self.viewer_id)
        )


class OwnerSelfTestView(OwnerBasicBackView):
    @discord.ui.button(label="Jalankan Lagi", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def rerun(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_self_test_embed(),
            view=OwnerSelfTestView(self.viewer_id)
        )


class OwnerNotificationCenterView(OwnerBasicBackView):
    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_notification_center_embed(),
            view=OwnerNotificationCenterView(self.viewer_id)
        )


def owner_integrity_embed():
    report = database_integrity_report()
    total = sum(report.values())
    return discord.Embed(
        title="🧰 Integrity & Repair",
        description=(
            "✅ Tidak ada masalah terdeteksi."
            if total == 0
            else f"⚠️ Ditemukan **{total}** item."
        ),
        color=discord.Color.green() if total == 0 else discord.Color.orange()
    ).add_field(
        name="Detail",
        value=(
            f"Orphan Host Manager: **{report['orphan_managers']}**\n"
            f"Request Access stuck: **{report['stuck_access']}**\n"
            f"Request Host stuck: **{report['stuck_hosts']}**"
        ),
        inline=False
    )


def dead_letter_embed():
    rows = recent_dead_letters()
    lines = [
        f"• **#{row['id']}** Host `{row['host_id']}` • "
        f"{row['event_type'] or '-'} • retry {row['retry_count']}\n"
        f"  `{str(row['failure_reason'] or '-')[:120]}`"
        for row in rows
    ]
    return discord.Embed(
        title="📮 Dead Letter Queue",
        description="\n".join(lines) if lines else "Tidak ada notifikasi gagal permanen.",
        color=discord.Color.orange()
    ).add_field(
        name="Total Open",
        value=str(dead_letter_count()),
        inline=True
    )


def diagnostic_bundle_bytes() -> bytes:
    import zipfile as _zipfile
    from io import BytesIO

    payload = BytesIO()
    integrity = database_integrity_report()
    platform_health = platform_health_summary()

    non_secret = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "db_path": str(DB_PATH),
        "server_count": len(bot.guilds),
        "started_at": STARTED_AT,
        "safe_mode": SAFE_MODE,
        "safe_mode_reason": SAFE_MODE_REASON,
        "required_guild_id": REQUIRED_GUILD_ID,
        "free_host_limit": FREE_HOST_LIMIT,
        "premium_host_limit": PREMIUM_HOST_LIMIT,
        "verification_retention_days": VERIFICATION_RETENTION_DAYS,
        "notification_max_retries": NOTIFICATION_MAX_RETRIES,
    }

    loops = {
        "monitor": monitor_loop.is_running(),
        "premium": premium_expiry_loop.is_running(),
        "backup": auto_backup_loop.is_running(),
        "invoice": invoice_expiry_loop.is_running(),
        "pending_notification": pending_notification_loop.is_running(),
        "verification_cleanup": verification_retention_cleanup_loop.is_running(),
        "host_validation": host_target_validation_loop.is_running(),
    }

    with _zipfile.ZipFile(payload, "w", _zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "config-non-secret.json",
            json.dumps(non_secret, indent=2, ensure_ascii=False)
        )
        z.writestr(
            "integrity.json",
            json.dumps(integrity, indent=2, ensure_ascii=False)
        )
        z.writestr(
            "platform-health.json",
            json.dumps(platform_health, indent=2, ensure_ascii=False)
        )
        z.writestr(
            "loops.json",
            json.dumps(loops, indent=2, ensure_ascii=False)
        )

    return payload.getvalue()


class OwnerVerificationDashboardView(OwnerBasicBackView):
    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=verification_dashboard_embed(),
            view=OwnerVerificationDashboardView(self.viewer_id)
        )


class OwnerDeadLetterView(OwnerBasicBackView):
    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=dead_letter_embed(),
            view=OwnerDeadLetterView(self.viewer_id)
        )


class OwnerDiagnosticsView(OwnerBasicBackView):
    @discord.ui.button(label="Buat Bundle", emoji="📦", style=discord.ButtonStyle.primary, row=0)
    async def bundle(self, interaction, button):
        if not await self.valid(interaction):
            return

        data = diagnostic_bundle_bytes()

        await interaction.response.send_message(
            content=(
                "📦 Diagnostic bundle tanpa token/API key/password."
            ),
            file=discord.File(
                io.BytesIO(data),
                filename="hi-notifku-diagnostics.zip"
            ),
            ephemeral=True
        )




class OwnerIntegrityView(OwnerBasicBackView):
    @discord.ui.button(label="Scan", emoji="🔎", style=discord.ButtonStyle.secondary, row=0)
    async def scan(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_integrity_embed(),
            view=OwnerIntegrityView(self.viewer_id)
        )

    @discord.ui.button(label="Repair Aman", emoji="🧹", style=discord.ButtonStyle.danger, row=0)
    async def repair(self, interaction, button):
        if not await self.valid(interaction):
            return
        if not await require_owner_level(interaction, "server_admin"):
            return

        report = repair_database_integrity()
        add_activity(
            None,
            interaction.user.id,
            "Database Safe Repair",
            json.dumps(report)
        )

        await interaction.response.edit_message(
            embed=owner_integrity_embed(),
            view=OwnerIntegrityView(self.viewer_id)
        )




class OwnerPlatformHealthView(OwnerBasicBackView):
    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_platform_health_embed(),
            view=OwnerPlatformHealthView(self.viewer_id)
        )




class OwnerQuotaView(OwnerBasicBackView):
    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_quota_embed(),
            view=OwnerQuotaView(self.viewer_id)
        )


class OwnerAuditView(OwnerBasicBackView):
    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_audit_embed(),
            view=OwnerAuditView(self.viewer_id)
        )


class OwnerErrorHostSelect(discord.ui.Select):
    def __init__(self, viewer_id: int):
        self.viewer_id = int(viewer_id)
        hosts = []
        for guild in bot.guilds:
            try:
                hosts.extend(get_hosts(guild.id))
            except Exception:
                pass

        problems = [
            h for h in hosts
            if h["last_error"] or int(h["error_count"] or 0) > 0 or not h["enabled"]
        ][:25]

        options = [
            discord.SelectOption(
                label=(
                    f"#{h['id']} • {platform_display_name(h['platform'])} • "
                    f"{h['display_name'] or h['target']}"
                )[:100],
                description=(
                    f"Health {host_health_score(h)}% • "
                    f"error {int(h['error_count'] or 0)}"
                )[:100],
                value=str(h["id"]),
                emoji="🚨"
            )
            for h in problems
        ]

        if not options:
            options = [
                discord.SelectOption(
                    label="Tidak ada host bermasalah",
                    value="0",
                    emoji="✅"
                )
            ]

        super().__init__(
            placeholder="Pilih host untuk recovery",
            options=options,
            row=0
        )

    async def callback(self, interaction):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel ini bukan milikmu.")
            return
        if not await require_owner_level(interaction, "server_admin"):
            return

        host_id = int(self.values[0])
        if not host_id:
            await safe_reply(interaction, "✅ Tidak ada host bermasalah.")
            return

        host = get_host(host_id)
        if not host:
            await safe_reply(interaction, "❌ Host tidak ditemukan.")
            return

        await interaction.response.edit_message(
            embed=host_embed(host),
            view=OwnerErrorHostActionView(
                self.viewer_id,
                host_id
            )
        )


class OwnerErrorCenterView(OwnerBasicBackView):
    def __init__(self, viewer_id: int):
        super().__init__(viewer_id)
        self.add_item(OwnerErrorHostSelect(viewer_id))

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_error_center_embed(),
            view=OwnerErrorCenterView(self.viewer_id)
        )


class OwnerErrorHostActionView(OwnerBasicBackView):
    def __init__(self, viewer_id: int, host_id: int):
        super().__init__(viewer_id)
        self.host_id = int(host_id)

    @discord.ui.button(label="Recheck", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def recheck(self, interaction, button):
        if not await self.valid(interaction):
            return
        if not await require_owner_level(interaction, "server_admin"):
            return

        host = get_host(self.host_id)
        if not host:
            await safe_reply(interaction, "❌ Host tidak ditemukan.")
            return

        await defer_if_needed(interaction)
        try:
            await host_manager_recheck(host)
            await interaction.followup.send("✅ Recheck selesai.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Recheck gagal: `{type(exc).__name__}: {exc}`",
                ephemeral=True
            )

    @discord.ui.button(label="Reset Error", emoji="🧹", style=discord.ButtonStyle.secondary, row=0)
    async def reset_error(self, interaction, button):
        if not await self.valid(interaction):
            return
        if not await require_owner_level(interaction, "server_admin"):
            return

        reset_host_error_state(self.host_id)
        add_activity(
            None,
            interaction.user.id,
            "Global Owner Reset Host Error",
            f"host_id={self.host_id}"
        )
        await safe_reply(interaction, "✅ Error/cooldown host direset.")


class OwnerRiskModal(discord.ui.Modal):
    guild_id_input = discord.ui.TextInput(
        label="Server ID",
        placeholder="123456789012345678",
        max_length=25
    )
    state = discord.ui.TextInput(
        label="Status",
        placeholder="allowed / warning / suspended / blacklist / whitelist",
        max_length=20
    )

    reason = discord.ui.TextInput(
        label="Alasan (opsional)",
        placeholder="Contoh: abuse / spam / investigasi",
        required=False,
        max_length=300
    )
    duration_hours = discord.ui.TextInput(
        label="Durasi jam (opsional)",
        placeholder="24 • kosong = tanpa expiry",
        required=False,
        max_length=6
    )

    def __init__(self, viewer_id: int):
        super().__init__(title="Atur Risiko Server", timeout=300)
        self.viewer_id = int(viewer_id)

    async def on_submit(self, interaction):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Form ini bukan milikmu.")
            return
        if not await require_owner_level(interaction, "server_admin"):
            return

        raw = self.guild_id_input.value.strip()
        state = self.state.value.strip().lower()

        if not raw.isdigit():
            await safe_reply(interaction, "❌ Server ID harus angka.")
            return

        if state not in {"allowed", "warning", "suspended", "blacklist", "whitelist"}:
            await safe_reply(interaction, "❌ Status tidak valid.")
            return

        guild_id = int(raw)
        if not bot.get_guild(guild_id):
            await safe_reply(interaction, "❌ Server tidak ditemukan di bot.")
            return

        hours_raw = self.duration_hours.value.strip()
        expires_at = None

        if hours_raw:
            if not hours_raw.isdigit():
                await safe_reply(interaction, "❌ Durasi harus angka jam.")
                return
            expires_at = int(time.time()) + int(hours_raw) * 3600

        set_access_state(guild_id, state)
        set_server_risk_meta(
            guild_id,
            reason=self.reason.value.strip(),
            expires_at=expires_at,
            actor_id=interaction.user.id
        )
        add_activity(
            guild_id,
            interaction.user.id,
            "Global Risk State Changed",
            state
        )
        await safe_reply(
            interaction,
            f"✅ Server `{guild_id}` → **{access_state_label(state)}**"
        )


class OwnerRiskView(OwnerBasicBackView):
    @discord.ui.button(label="Atur Status", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def set_state(self, interaction, button):
        if not await self.valid(interaction):
            return
        if not await require_owner_level(interaction, "server_admin"):
            return
        await interaction.response.send_modal(
            OwnerRiskModal(self.viewer_id)
        )

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_risk_embed(),
            view=OwnerRiskView(self.viewer_id)
        )


class OwnerEmergencyConfirmView(discord.ui.View):
    def __init__(self, viewer_id: int, setting: str, enabled: bool):
        super().__init__(timeout=120)
        self.viewer_id = int(viewer_id)
        self.setting = setting
        self.enabled = bool(enabled)

    @discord.ui.button(label="Konfirmasi", emoji="✅", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel ini bukan milikmu.")
            return
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "🔒 Hanya Primary Global Owner.")
            return

        set_runtime_setting(
            self.setting,
            self.enabled,
            interaction.user.id
        )
        add_activity(
            None,
            interaction.user.id,
            "Emergency Setting",
            f"{self.setting}={self.enabled}"
        )
        await interaction.response.edit_message(
            embed=owner_emergency_embed(),
            view=OwnerEmergencyView(self.viewer_id)
        )

    @discord.ui.button(label="Batal", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel ini bukan milikmu.")
            return
        await interaction.response.edit_message(
            embed=owner_emergency_embed(),
            view=OwnerEmergencyView(self.viewer_id)
        )


class OwnerEmergencyView(OwnerBasicBackView):
    async def toggle(self, interaction, setting):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel ini bukan milikmu.")
            return
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "🔒 Hanya Primary Global Owner.")
            return

        current = runtime_setting_enabled(setting)
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⚠️ Konfirmasi Emergency",
                description=(
                    f"Ubah `{setting}` menjadi **{'ON' if not current else 'OFF'}**?"
                ),
                color=discord.Color.red()
            ),
            view=OwnerEmergencyConfirmView(
                self.viewer_id,
                setting,
                not current
            )
        )

    @discord.ui.button(label="Pause Checker", emoji="⏸️", style=discord.ButtonStyle.danger, row=0)
    async def checker(self, interaction, button):
        await self.toggle(interaction, "monitor_paused")

    @discord.ui.button(label="Stop Notif", emoji="🔕", style=discord.ButtonStyle.danger, row=0)
    async def notif(self, interaction, button):
        await self.toggle(interaction, "notifications_paused")

    @discord.ui.button(label="Stop Request", emoji="🛑", style=discord.ButtonStyle.danger, row=1)
    async def requests(self, interaction, button):
        await self.toggle(interaction, "requests_paused")

    @discord.ui.button(label="Maintenance Global", emoji="🚧", style=discord.ButtonStyle.danger, row=1)
    async def maintenance(self, interaction, button):
        await self.toggle(interaction, "maintenance_all")


BACKUP_MAGIC = b"HINOTIFENC1"


def encrypt_backup_bytes(raw: bytes, password: str) -> bytes:
    if not password:
        return raw
    if AESGCM is None:
        raise RuntimeError("cryptography belum tersedia. Install requirements terbaru.")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 250000, dklen=32
    )
    encrypted = AESGCM(key).encrypt(nonce, raw, BACKUP_MAGIC)
    return BACKUP_MAGIC + salt + nonce + encrypted


def decrypt_backup_bytes(raw: bytes, password: str) -> bytes:
    if not raw.startswith(BACKUP_MAGIC):
        return raw
    if AESGCM is None:
        raise RuntimeError("cryptography belum tersedia.")
    if not password:
        raise ValueError("Password backup diperlukan.")
    offset = len(BACKUP_MAGIC)
    salt = raw[offset:offset + 16]
    nonce = raw[offset + 16:offset + 28]
    encrypted = raw[offset + 28:]
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 250000, dklen=32
    )
    return AESGCM(key).decrypt(nonce, encrypted, BACKUP_MAGIC)


def system_backup_export_bytes() -> tuple[bytes, str]:
    raw = create_full_system_backup_zip()
    if BACKUP_ENCRYPTION_PASSWORD:
        return encrypt_backup_bytes(raw, BACKUP_ENCRYPTION_PASSWORD), "hnbak"
    return raw, "zip"


def system_backup_schedule_state():
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM system_backup_schedule_state WHERE id=1"
        ).fetchone()


async def run_scheduled_system_backup():
    now = int(time.time())
    data, ext = await asyncio.to_thread(system_backup_export_bytes)
    folder = Path(AUTO_BACKUP_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"hi-notifku-system-{now}.{ext}"
    path.write_bytes(data)

    sent = 0
    if len(data) <= 24 * 1024 * 1024:
        for owner_id in primary_owner_ids():
            try:
                owner = bot.get_user(owner_id) or await bot.fetch_user(owner_id)
                await owner.send(
                    content=(
                        "📦 **Scheduled Full System Backup**\n"
                        f"Encrypted: **{'YES' if ext == 'hnbak' else 'NO'}**"
                    ),
                    file=discord.File(io.BytesIO(data), filename=path.name)
                )
                sent += 1
            except Exception:
                log.exception("Scheduled system backup gagal dikirim owner_id=%s", owner_id)

    with closing(db()) as conn:
        conn.execute("""
            UPDATE system_backup_schedule_state
            SET last_export_at=?, last_path=?, last_error=NULL
            WHERE id=1
        """, (now, str(path)))
        conn.commit()

    return path, sent


@tasks.loop(hours=1)
async def scheduled_system_backup_loop():
    state = system_backup_schedule_state()
    last = int(state["last_export_at"] or 0) if state else 0
    now = int(time.time())
    if last and now - last < FULL_BACKUP_HOURS * 3600:
        return

    try:
        await run_scheduled_system_backup()
    except Exception as exc:
        log.exception("Scheduled system backup gagal")
        with closing(db()) as conn:
            conn.execute("""
                UPDATE system_backup_schedule_state SET last_error=? WHERE id=1
            """, (f"{type(exc).__name__}: {exc}"[:1000],))
            conn.commit()


@scheduled_system_backup_loop.before_loop
async def before_scheduled_system_backup_loop():
    await bot.wait_until_ready()


def create_full_system_backup_zip() -> bytes:
    payload, config_raw = manual_backup_payload_and_bytes()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_copy = tmp_path / "live_notifier.db"

        source = sqlite3.connect(str(Path(DB_PATH).expanduser()), timeout=30)
        try:
            dest = sqlite3.connect(str(db_copy))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("config-backup.json", config_raw)
            z.write(db_copy, "database/live_notifier.db")

            qris_dir = Path(QRIS_STORAGE_DIR)
            if qris_dir.exists():
                for item in qris_dir.rglob("*"):
                    if item.is_file():
                        z.write(
                            item,
                            Path("qris") / item.relative_to(qris_dir)
                        )

            env_template = Path(__file__).with_name("railway-variables.env")
            if env_template.exists():
                z.write(env_template, "railway-variables.env")

            z.writestr(
                "RESTORE-NOTE.txt",
                (
                    "Hi Notifku full system backup.\n"
                    "Database: database/live_notifier.db\n"
                    "QRIS: qris/\n"
                    "Restore hanya saat bot dihentikan. "
                    "Jangan menimpa DB aktif saat proses bot berjalan.\n"
                )
            )

        return output.getvalue()


def restore_center_embed():
    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT *
            FROM restore_audit
            ORDER BY created_at DESC
            LIMIT 8
        """).fetchall()

    history = "\n".join(
        f"• <t:{int(row['created_at'])}:R> guild `{row['guild_id']}` • "
        f"{str(row['summary'])[:100]}"
        for row in rows
    ) or "Belum ada restore."

    return discord.Embed(
        title="♻️ Restore Center",
        description=(
            "Kirim file backup **JSON server** ke DM bot untuk preview otomatis.\n"
            "Bot akan meminta konfirmasi sebelum restore.\n\n"
            "Full System ZIP/backup terenkripsi dipulihkan saat bot dihentikan "
            "agar SQLite tidak korup."
        ),
        color=discord.Color.orange()
    ).add_field(
        name="Riwayat",
        value=history[:1024],
        inline=False
    )


class OwnerRestoreCenterView(OwnerBasicBackView):
    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=restore_center_embed(),
            view=OwnerRestoreCenterView(self.viewer_id)
        )

    @discord.ui.button(label="Panduan", emoji="📘", style=discord.ButtonStyle.primary, row=0)
    async def guide(self, interaction, button):
        if not await self.valid(interaction):
            return
        await safe_reply(
            interaction,
            (
                "**Restore server:** kirim file `.json` hasil backup ke DM bot.\n"
                "Bot menampilkan preview → tekan **Konfirmasi Restore**.\n\n"
                "**Full-system restore:** hentikan service Railway, ambil "
                "`database/live_notifier.db` dari System ZIP, lalu pulihkan ke Volume `/data`."
            )
        )


class OwnerBackupCenterView(OwnerBasicBackView):
    @discord.ui.button(label="Backup Sekarang", emoji="💾", style=discord.ButtonStyle.primary, row=0)
    async def backup_now(self, interaction, button):
        if not await self.valid(interaction):
            return
        if not await require_owner_level(interaction, "server_admin"):
            return

        payload, raw = manual_backup_payload_and_bytes()
        ok, detail = backup_restore_smoke_test(payload)
        if not ok:
            await safe_reply(
                interaction,
                f"❌ Backup/restore smoke-test gagal: {detail}"
            )
            return

        ts = int(time.time())
        folder = Path(AUTO_BACKUP_DIR)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"hi-notifku-manual-{ts}.json"
        path.write_bytes(raw)

        with closing(db()) as conn:
            conn.execute("""
                INSERT INTO backup_log(path, created_at, guild_count, ok, error)
                VALUES(?,?,?,?,NULL)
            """, (
                str(path),
                ts,
                len(payload.get("guilds", [])),
                1
            ))
            conn.commit()

        await interaction.response.send_message(
            content=f"✅ Manual backup valid. {detail}",
            file=discord.File(
                io.BytesIO(raw),
                filename=f"hi-notifku-manual-{ts}.json"
            ),
            ephemeral=True
        )

    @discord.ui.button(label="Verify Terakhir", emoji="✅", style=discord.ButtonStyle.secondary, row=0)
    async def verify_last(self, interaction, button):
        if not await self.valid(interaction):
            return

        folder = Path(AUTO_BACKUP_DIR)
        files = sorted(
            list(folder.glob("hi-notifku-*.json")),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if not files:
            await safe_reply(interaction, "ℹ️ Belum ada file backup.")
            return

        try:
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            ok, detail = verify_backup_payload(payload)
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"

        await safe_reply(
            interaction,
            f"{'✅' if ok else '❌'} `{files[0].name}`\n{detail}"
        )

    @discord.ui.button(label="System ZIP", emoji="📦", style=discord.ButtonStyle.success, row=1)
    async def system_zip(self, interaction, button):
        if not await self.valid(interaction):
            return
        if not await require_owner_level(interaction, "server_admin"):
            return

        await defer_if_needed(interaction, ephemeral=True)
        try:
            data, ext = await asyncio.to_thread(system_backup_export_bytes)
            await interaction.followup.send(
                content=(
                    "📦 Full system backup dibuat. "
                    f"Encrypted: **{'YES' if ext == 'hnbak' else 'NO'}**"
                ),
                file=discord.File(
                    io.BytesIO(data),
                    filename=f"hi-notifku-system-{int(time.time())}.{ext}"
                ),
                ephemeral=True
            )
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Full system backup gagal: `{type(exc).__name__}: {exc}`",
                ephemeral=True
            )

    @discord.ui.button(label="Restore Center", emoji="♻️", style=discord.ButtonStyle.secondary, row=1)
    async def restore_center(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=restore_center_embed(),
            view=OwnerRestoreCenterView(self.viewer_id)
        )

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def refresh(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_backup_center_embed(),
            view=OwnerBackupCenterView(self.viewer_id)
        )




class OwnerPaymentMenuView(discord.ui.View):
    def __init__(self, viewer_id: int):
        super().__init__(timeout=900)
        self.viewer_id = int(viewer_id)

    async def valid(self, interaction, minimum="read_only"):
        if int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel ini bukan milikmu.")
            return False
        return await require_owner_level(interaction, minimum)

    @discord.ui.button(label="Request", emoji="💳", style=discord.ButtonStyle.secondary, row=0)
    async def requests(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=premium_queue_embed(),
            view=PremiumOrdersView()
        )

    @discord.ui.button(label="Riwayat", emoji="🧾", style=discord.ButtonStyle.secondary, row=0)
    async def history(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=transaction_history_embed(),
            view=TransactionHistoryView()
        )

    @discord.ui.button(label="Premium DB", emoji="⭐", style=discord.ButtonStyle.secondary, row=0)
    async def premium_db(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=premium_customer_database_embed(),
            view=PremiumCustomerDatabaseView(self.viewer_id)
        )

    @discord.ui.button(label="Pendapatan", emoji="💰", style=discord.ButtonStyle.secondary, row=0)
    async def revenue(self, interaction, button):
        if not await self.valid(interaction, "payment_admin"):
            return
        await interaction.response.edit_message(
            embed=revenue_embed(),
            view=RevenueReportView()
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView(self.viewer_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction, button):
        if not await self.valid(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView(self.viewer_id)
        )


class OwnerHomeView(discord.ui.View):
    def __init__(self, viewer_id: Optional[int] = None):
        super().__init__(timeout=900)
        self.viewer_id = int(viewer_id) if viewer_id else None
        self.add_item(GuildSelect())

    async def valid_owner(self, interaction: discord.Interaction, minimum: str = "read_only") -> bool:
        if self.viewer_id is not None and int(interaction.user.id) != self.viewer_id:
            await safe_reply(interaction, "🔒 Panel Global Owner ini bukan milikmu.")
            return False
        return await require_owner_level(interaction, minimum)

    @discord.ui.button(label="Plan", emoji="📊", style=discord.ButtonStyle.secondary, row=1)
    async def plan_overview(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.valid_owner(interaction):
            return
        await interaction.response.edit_message(
            embed=plan_overview_embed(),
            view=PlanOverviewView()
        )

    @discord.ui.button(label="Dashboard", emoji="📈", style=discord.ButtonStyle.secondary, row=1)
    async def dashboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.valid_owner(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_dashboard_embed(),
            view=OwnerDashboardView()
        )

    @discord.ui.button(label="Payment", emoji="💳", style=discord.ButtonStyle.secondary, row=1)
    async def payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.valid_owner(interaction):
            return
        await interaction.response.edit_message(
            embed=owner_payment_menu_embed(),
            view=OwnerPaymentMenuView(interaction.user.id)
        )

    @discord.ui.button(label="Global Owner", emoji="🛡️", style=discord.ButtonStyle.secondary, row=2)
    async def owners(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya **Primary Global Owner Bot** dari `OWNER_IDS` yang dapat membuka menu ini.")
            return
        all_owners = OWNER_IDS | db_owner_ids()
        embed = discord.Embed(
            title="🛡️ Global Owner Bot",
            description="\n".join(f"• <@{x}> (`{x}`)" for x in sorted(all_owners)) or "Tidak ada",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=OwnerManagementView())

    @discord.ui.button(label="Security", emoji="🔐", style=discord.ButtonStyle.primary, row=2)
    async def security(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.valid_owner(interaction):
            return
        await interaction.response.edit_message(
            embed=global_owner_access_embed(interaction.user.id),
            view=OwnerAccessCenterView(interaction.user.id)
        )

    @discord.ui.button(label="Operations", emoji="🧰", style=discord.ButtonStyle.primary, row=2)
    async def operations(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.valid_owner(interaction):
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🧰 Owner Operations",
                description="Operasional, keamanan, monitoring, dan maintenance bot.",
                color=discord.Color.blurple()
            ),
            view=OwnerOpsHomeView(interaction.user.id)
        )

    @discord.ui.button(label="Server", emoji="🔎", style=discord.ButtonStyle.secondary, row=3)
    async def browse_servers(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.valid_owner(interaction):
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🔎 Browser Server",
                description=f"Total server: **{len(bot.guilds)}**",
                color=discord.Color.blue()
            ),
            view=ServerBrowserView(0, "")
        )


class BackHomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )



def coupon_admin_embed():
    now = int(time.time())
    with closing(db()) as conn:
        rows = conn.execute("""
            SELECT *
            FROM premium_coupons
            ORDER BY created_at DESC
            LIMIT 15
        """).fetchall()

    lines = []
    for row in rows:
        active = bool(row["enabled"]) and (
            not row["expires_at"] or int(row["expires_at"]) > now
        )
        value = (
            f"{row['discount_value']}%"
            if row["discount_type"] == "percent"
            else rupiah(int(row["discount_value"]))
        )
        lines.append(
            f"{'🟢' if active else '⚪'} `{row['code']}` • "
            f"**{value}** • {int(row['used_count'] or 0)}x"
        )

    return discord.Embed(
        title="🎟️ Promo Premium",
        description="\n".join(lines) if lines else "Belum ada kode promo.",
        color=discord.Color.gold()
    )


class CouponCreateModal(discord.ui.Modal):
    code_input = discord.ui.TextInput(
        label="Kode",
        placeholder="HINOTIF10",
        max_length=40
    )
    type_input = discord.ui.TextInput(
        label="Tipe",
        placeholder="percent / fixed",
        max_length=10
    )
    value_input = discord.ui.TextInput(
        label="Nilai",
        placeholder="10 atau 5000",
        max_length=12
    )
    max_uses_input = discord.ui.TextInput(
        label="Maks. penggunaan (opsional)",
        required=False,
        max_length=8
    )
    days_input = discord.ui.TextInput(
        label="Berlaku berapa hari (opsional)",
        required=False,
        max_length=5
    )

    def __init__(self):
        super().__init__(title="Buat / Update Promo", timeout=300)

    async def on_submit(self, interaction):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "🔒 Hanya Primary Global Owner.")
            return

        raw_value = self.value_input.value.strip()
        if not raw_value.isdigit():
            await safe_reply(interaction, "❌ Nilai promo harus angka.")
            return

        max_uses = (
            int(self.max_uses_input.value.strip())
            if self.max_uses_input.value.strip().isdigit()
            else None
        )
        expires_at = None
        if self.days_input.value.strip():
            if not self.days_input.value.strip().isdigit():
                await safe_reply(interaction, "❌ Hari berlaku harus angka.")
                return
            expires_at = (
                int(time.time())
                + int(self.days_input.value.strip()) * 86400
            )

        create_coupon(
            self.code_input.value,
            self.type_input.value,
            int(raw_value),
            expires_at=expires_at,
            max_uses=max_uses,
            actor_id=interaction.user.id
        )

        await safe_reply(
            interaction,
            f"✅ Promo `{self.code_input.value.strip().upper()}` disimpan."
        )


class CouponToggleModal(discord.ui.Modal):
    code_input = discord.ui.TextInput(
        label="Kode Promo",
        max_length=40
    )

    def __init__(self):
        super().__init__(title="Aktif / Nonaktif Promo", timeout=300)

    async def on_submit(self, interaction):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "🔒 Hanya Primary Global Owner.")
            return

        code_value = self.code_input.value.strip().upper()
        row = coupon_get(code_value)

        if not row:
            await safe_reply(interaction, "❌ Promo tidak ditemukan.")
            return

        with closing(db()) as conn:
            conn.execute(
                "UPDATE premium_coupons SET enabled=? WHERE code=?",
                (0 if row["enabled"] else 1, code_value)
            )
            conn.commit()

        await safe_reply(
            interaction,
            f"✅ Promo `{code_value}` sekarang "
            f"{'NONAKTIF' if row['enabled'] else 'AKTIF'}."
        )


class CouponAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(label="Buat / Edit", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def create(self, interaction, button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "🔒 Hanya Primary Global Owner.")
            return
        await interaction.response.send_modal(CouponCreateModal())

    @discord.ui.button(label="Aktif / Nonaktif", emoji="⏯️", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction, button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "🔒 Hanya Primary Global Owner.")
            return
        await interaction.response.send_modal(CouponToggleModal())

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
    async def refresh(self, interaction, button):
        await interaction.response.edit_message(
            embed=coupon_admin_embed(),
            view=CouponAdminView()
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="💰 Harga Paket Premium",
                description=premium_packages_text(),
                color=discord.Color.gold()
            ),
            view=PremiumPriceManagementView()
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction, button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )




class PremiumPriceManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(
        label="Tambah / Ubah Paket",
        emoji="💰",
        style=discord.ButtonStyle.success
    )
    async def edit_package(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(
                interaction,
                "❌ Hanya OWNER_IDS utama yang dapat mengatur harga."
            )
            return

        await interaction.response.send_modal(
            PremiumPackageModal()
        )

    @discord.ui.button(
        label="Hapus Paket",
        emoji="🗑️",
        style=discord.ButtonStyle.danger
    )
    async def delete_package(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(
                interaction,
                "❌ Hanya OWNER_IDS utama yang dapat mengatur harga."
            )
            return

        await interaction.response.send_modal(
            DeletePremiumPackageModal()
        )

    @discord.ui.button(
        label="Promo",
        emoji="🎟️",
        style=discord.ButtonStyle.secondary
    )
    async def promo(self, interaction, button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "🔒 Hanya Primary Global Owner.")
            return
        await interaction.response.edit_message(
            embed=coupon_admin_embed(),
            view=CouponAdminView()
        )

    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.secondary
    )
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="💰 Harga Paket Premium",
            description=premium_packages_text(),
            color=discord.Color.gold()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=PremiumPriceManagementView()
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        all_owners = OWNER_IDS | db_owner_ids()

        embed = discord.Embed(
            title="👑 Kelola Owner",
            description=(
                "\n".join(
                    f"• <@{x}> (`{x}`) • **{owner_role(x)}**"
                    for x in sorted(all_owners)
                ) or "Tidak ada"
            ),
            color=discord.Color.gold()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=OwnerManagementView()
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



class OwnerRoleModal(discord.ui.Modal):
    user_id = discord.ui.TextInput(
        label="User ID Owner",
        placeholder="Contoh: 123456789012345678",
        max_length=25
    )
    role = discord.ui.TextInput(
        label="Role",
        placeholder="super_owner / payment_admin / server_admin / read_only",
        max_length=30
    )

    def __init__(self):
        super().__init__(title="Atur Role Owner", timeout=300)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return

        if not self.user_id.value.strip().isdigit():
            await safe_reply(interaction, "❌ User ID harus angka.")
            return

        role_value = self.role.value.strip().lower()

        if role_value not in OWNER_ROLE_LEVELS:
            await safe_reply(
                interaction,
                "❌ Role: super_owner / payment_admin / server_admin / read_only"
            )
            return

        uid = int(self.user_id.value.strip())
        set_owner_role(uid, role_value, interaction.user.id)

        await safe_reply(
            interaction,
            f"✅ <@{uid}> sekarang role **{role_value}**."
        )


class UserBlacklistModal(discord.ui.Modal):
    user_id = discord.ui.TextInput(
        label="User ID",
        placeholder="Discord User ID",
        max_length=25
    )
    reason = discord.ui.TextInput(
        label="Alasan",
        placeholder="Contoh: spam / penyalahgunaan pembayaran",
        max_length=500,
        required=False
    )

    def __init__(self, remove: bool = False):
        super().__init__(
            title="Hapus Blacklist User" if remove else "Blacklist User",
            timeout=300
        )
        self.remove = remove

    async def on_submit(self, interaction: discord.Interaction):
        if not owner_has_level(interaction.user.id, "server_admin"):
            await safe_reply(interaction, "❌ Akses Server Admin diperlukan.")
            return

        raw = self.user_id.value.strip()

        if not raw.isdigit():
            await safe_reply(interaction, "❌ User ID harus angka.")
            return

        uid = int(raw)

        if self.remove:
            unblacklist_user(uid)
            await safe_reply(interaction, f"✅ <@{uid}> dihapus dari blacklist.")
        else:
            blacklist_user(
                uid,
                self.reason.value or "Tidak ada alasan",
                interaction.user.id
            )
            await safe_reply(interaction, f"✅ <@{uid}> diblacklist.")


class AdvancedSecurityView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(label="Role Owner", emoji="🛡️", style=discord.ButtonStyle.secondary)
    async def role_owner(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return
        await interaction.response.send_modal(OwnerRoleModal())

    @discord.ui.button(label="Blacklist User", emoji="🚫", style=discord.ButtonStyle.danger)
    async def blacklist(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_owner_level(interaction, "server_admin"):
            return
        await interaction.response.send_modal(UserBlacklistModal(False))

    @discord.ui.button(label="Hapus Blacklist", emoji="✅", style=discord.ButtonStyle.secondary)
    async def unblacklist(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_owner_level(interaction, "server_admin"):
            return
        await interaction.response.send_modal(UserBlacklistModal(True))

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        all_owners = OWNER_IDS | db_owner_ids()
        embed = discord.Embed(
            title="👑 Kelola Owner",
            description="\n".join(
                f"• <@{x}> (`{x}`) • **{owner_role(x)}**"
                for x in sorted(all_owners)
            ) or "Tidak ada",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(
            embed=embed,
            view=OwnerManagementView()
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class OwnerManagementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    @discord.ui.button(label="Tambah", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def add_owner(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return
        await interaction.response.send_modal(OwnerIdModal("add"))

    @discord.ui.button(label="Hapus", emoji="➖", style=discord.ButtonStyle.danger, row=0)
    async def remove_owner(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return
        await interaction.response.send_modal(OwnerIdModal("remove"))

    @discord.ui.button(
        label="Harga",
        emoji="💰",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def premium_prices(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(
                interaction,
                "❌ Hanya OWNER_IDS utama yang dapat mengatur harga."
            )
            return

        embed = discord.Embed(
            title="💰 Harga Paket Premium",
            description=premium_packages_text(),
            color=discord.Color.gold()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=PremiumPriceManagementView()
        )

    @discord.ui.button(
        label="Pembayaran",
        emoji="💳",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def payment_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(
                interaction,
                "❌ Hanya OWNER_IDS utama yang dapat mengatur pembayaran."
            )
            return

        await interaction.response.edit_message(
            embed=payment_methods_overview_embed(),
            view=PaymentSettingsView()
        )

    @discord.ui.button(
        label="Keamanan",
        emoji="🛡️",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def security_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_primary_owner(interaction.user.id):
            await safe_reply(interaction, "❌ Hanya OWNER_IDS utama.")
            return

        embed = discord.Embed(
            title="🛡️ Keamanan & Role Owner",
            description=(
                "**super_owner** — akses penuh\n"
                "**payment_admin** — pembayaran & Premium\n"
                "**server_admin** — server/host\n"
                "**read_only** — lihat saja"
            ),
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(
            embed=embed,
            view=AdvancedSecurityView()
        )

    @discord.ui.button(label="Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=2)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=3
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class PlanGuildSelect(discord.ui.Select):
    def __init__(self, plan: str):
        self.plan = "premium" if plan == "premium" else "free"
        guilds = guilds_by_plan(self.plan)

        options = [
            discord.SelectOption(
                label=g.name[:100],
                value=str(g.id),
                description=f"{self.plan.upper()} • ID {g.id}"[:100]
            )
            for g in guilds[:25]
        ]

        if not options:
            options = [
                discord.SelectOption(
                    label=f"Tidak ada server {self.plan.upper()}",
                    value="0"
                )
            ]

        super().__init__(
            placeholder=f"Pilih server {self.plan.upper()}...",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return

        guild_id = int(self.values[0])

        if guild_id == 0:
            await safe_reply(
                interaction,
                f"Belum ada server **{self.plan.upper()}**."
            )
            return

        guild = bot.get_guild(guild_id)

        if guild is None:
            await safe_reply(
                interaction,
                "❌ Server tidak ditemukan."
            )
            return

        await interaction.response.edit_message(
            embed=server_embed(guild),
            view=PlanServerManageView(guild.id)
        )


class PlanListView(discord.ui.View):
    def __init__(self, plan: str):
        super().__init__(timeout=900)
        self.plan = "premium" if plan == "premium" else "free"
        self.add_item(PlanGuildSelect(self.plan))

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=plan_overview_embed(),
            view=PlanOverviewView()
        )


class PlanServerManageView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id

        settings = get_guild_settings(guild_id)

        if premium_access_effective(guild_id):
            extend = discord.ui.Button(
                label="Perpanjang Premium",
                emoji="⏳",
                style=discord.ButtonStyle.success
            )
            extend.callback = self.extend_premium
            self.add_item(extend)

            downgrade = discord.ui.Button(
                label="Jadikan Free",
                emoji="🆓",
                style=discord.ButtonStyle.secondary
            )
            downgrade.callback = self.make_free
            self.add_item(downgrade)
        else:
            upgrade = discord.ui.Button(
                label="Jadikan Premium",
                emoji="⭐",
                style=discord.ButtonStyle.success
            )
            upgrade.callback = self.make_premium
            self.add_item(upgrade)

        open_server = discord.ui.Button(
            label="Kelola Server",
            emoji="⚙️",
            style=discord.ButtonStyle.primary
        )
        open_server.callback = self.open_server
        self.add_item(open_server)

        back = discord.ui.Button(
            label="Kembali",
            emoji="⬅️",
            style=discord.ButtonStyle.secondary
        )
        back.callback = self.back
        self.add_item(back)

        home = discord.ui.Button(
            label="Menu Awal",
            emoji="🏠",
            style=discord.ButtonStyle.secondary
        )
        home.callback = self.home
        self.add_item(home)

    async def make_premium(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return

        await interaction.response.send_modal(
            PremiumDurationModal(
                self.guild_id,
                "activate"
            )
        )

    async def extend_premium(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return

        await interaction.response.send_modal(
            PremiumDurationModal(
                self.guild_id,
                "extend"
            )
        )

    async def make_free(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return

        set_plan(self.guild_id, "free")

        await log_action(
            self.guild_id,
            interaction.user.id,
            "Ubah Plan",
            "PREMIUM → FREE"
        )

        guild = bot.get_guild(self.guild_id)

        if guild:
            try:
                owner = guild.owner or await guild.fetch_member(guild.owner_id)
                await owner.send(
                    f"🆓 Premium untuk server **{guild.name}** telah dinonaktifkan oleh owner Hi Notifku."
                )
            except Exception:
                pass

        await safe_reply(
            interaction,
            "🆓 Server berhasil dikembalikan ke **FREE**."
        )

    async def open_server(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return

        guild = bot.get_guild(self.guild_id)

        if guild:
            await interaction.response.edit_message(
                embed=server_embed(guild),
                view=ServerOwnerView(self.guild_id)
            )

    async def back(self, interaction: discord.Interaction):
        guild = bot.get_guild(self.guild_id)

        if guild:
            await interaction.response.edit_message(
                embed=server_embed(guild),
                view=ServerOwnerView(self.guild_id)
            )
        else:
            await safe_reply(interaction, "❌ Server tidak ditemukan.")

    async def home(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )




class HostDeliveryModal(discord.ui.Modal):
    extra_channels = discord.ui.TextInput(
        label="Channel Tambahan (ID, koma)",
        required=False,
        max_length=800
    )
    extra_roles = discord.ui.TextInput(
        label="Role Tambahan (ID, koma)",
        required=False,
        max_length=800
    )
    everyone = discord.ui.TextInput(
        label="Mention @everyone? yes/no",
        required=False,
        max_length=10
    )
    webhook_url = discord.ui.TextInput(
        label="Webhook URL (opsional)",
        required=False,
        max_length=1000
    )

    def __init__(self, host_id: int):
        self.host_id = int(host_id)
        host = get_host(self.host_id)
        super().__init__(title="Delivery Host", timeout=300)

        if host:
            self.extra_channels.default = host["extra_channel_ids"] or ""
            self.extra_roles.default = host["extra_role_ids"] or ""
            self.everyone.default = "yes" if host["mention_everyone"] else "no"
            self.webhook_url.default = host["webhook_url"] or ""

    async def on_submit(self, interaction: discord.Interaction):
        host = get_host(self.host_id)
        if not host:
            await safe_reply(interaction, "❌ Host tidak ditemukan.")
            return

        if not await require_premium_feature(
            interaction, int(host["guild_id"]), "extra_channels", "Delivery lanjutan"
        ):
            return

        channels = ",".join(
            str(x) for x in parse_id_csv(self.extra_channels.value)
        )
        roles = ",".join(
            str(x) for x in parse_id_csv(self.extra_roles.value)
        )
        everyone = self.everyone.value.strip().lower() in {
            "yes", "y", "1", "true", "on"
        }

        webhook = self.webhook_url.value.strip()
        if webhook and not webhook.startswith(
            ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")
        ):
            await safe_reply(interaction, "❌ Webhook URL Discord tidak valid.")
            return

        with closing(db()) as conn:
            conn.execute("""
                UPDATE hosts
                SET extra_channel_ids=?, extra_role_ids=?,
                    mention_everyone=?, webhook_url=?
                WHERE id=?
            """, (
                channels or None,
                roles or None,
                1 if everyone else 0,
                webhook or None,
                self.host_id
            ))
            conn.commit()

        await safe_reply(interaction, "✅ Delivery host diperbarui.")


class HostScheduleModal(discord.ui.Modal):
    timezone_name = discord.ui.TextInput(
        label="Timezone",
        placeholder="Asia/Jakarta",
        max_length=64
    )
    schedule_days = discord.ui.TextInput(
        label="Hari Aktif 0=Senin ... 6=Minggu",
        placeholder="0,1,2,3,4,5,6",
        max_length=30
    )
    quiet_start = discord.ui.TextInput(
        label="Quiet Start HH:MM",
        placeholder="23:00",
        required=False,
        max_length=5
    )
    quiet_end = discord.ui.TextInput(
        label="Quiet End HH:MM",
        placeholder="06:00",
        required=False,
        max_length=5
    )

    def __init__(self, host_id: int):
        self.host_id = int(host_id)
        host = get_host(self.host_id)
        super().__init__(title="Jadwal Host", timeout=300)

        if host:
            self.timezone_name.default = host["timezone"] or "Asia/Jakarta"
            self.schedule_days.default = host["schedule_days"] or "0,1,2,3,4,5,6"
            self.quiet_start.default = host["quiet_start"] or ""
            self.quiet_end.default = host["quiet_end"] or ""

    async def on_submit(self, interaction: discord.Interaction):
        host = get_host(self.host_id)
        if not host:
            await safe_reply(interaction, "❌ Host tidak ditemukan.")
            return
        if not await require_premium_feature(
            interaction, int(host["guild_id"]), "advanced_schedule", "Jadwal & quiet hours"
        ):
            return

        try:
            ZoneInfo(self.timezone_name.value.strip())
        except Exception:
            await safe_reply(interaction, "❌ Timezone tidak valid.")
            return

        days = []
        for raw in self.schedule_days.value.split(","):
            raw = raw.strip()
            if raw.isdigit() and 0 <= int(raw) <= 6:
                days.append(str(int(raw)))

        if not days:
            await safe_reply(interaction, "❌ Hari aktif tidak valid.")
            return

        for value in (self.quiet_start.value.strip(), self.quiet_end.value.strip()):
            if value and not _parse_hhmm(value):
                await safe_reply(interaction, "❌ Format quiet hours harus HH:MM.")
                return

        with closing(db()) as conn:
            conn.execute("""
                UPDATE hosts
                SET timezone=?, schedule_days=?,
                    quiet_start=?, quiet_end=?
                WHERE id=?
            """, (
                self.timezone_name.value.strip(),
                ",".join(sorted(set(days))),
                self.quiet_start.value.strip() or None,
                self.quiet_end.value.strip() or None,
                self.host_id
            ))
            conn.commit()

        await safe_reply(interaction, "✅ Jadwal host diperbarui.")


class HostBrandingModal(discord.ui.Modal):
    title = discord.ui.TextInput(
        label="Judul Embed Override",
        required=False,
        max_length=256
    )
    footer = discord.ui.TextInput(
        label="Footer Embed",
        required=False,
        max_length=500
    )
    color = discord.ui.TextInput(
        label="Warna HEX",
        placeholder="#5865F2",
        required=False,
        max_length=10
    )
    language = discord.ui.TextInput(
        label="Bahasa id/en",
        placeholder="id",
        required=False,
        max_length=5
    )

    def __init__(self, host_id: int):
        self.host_id = int(host_id)
        host = get_host(self.host_id)
        super().__init__(title="Branding Host", timeout=300)

        if host:
            self.title.default = host["embed_title"] or ""
            self.footer.default = host["embed_footer"] or ""
            self.color.default = (
                f"#{int(host['embed_color']):06X}"
                if host["embed_color"] else ""
            )
            self.language.default = host["language"] or "id"

    async def on_submit(self, interaction: discord.Interaction):
        host = get_host(self.host_id)
        if not host:
            await safe_reply(interaction, "❌ Host tidak ditemukan.")
            return
        if not await require_premium_feature(
            interaction, int(host["guild_id"]), "custom_branding", "Custom branding"
        ):
            return

        color_value = None
        raw_color = self.color.value.strip().lstrip("#")

        if raw_color:
            try:
                color_value = int(raw_color, 16)
                if not 0 <= color_value <= 0xFFFFFF:
                    raise ValueError
            except ValueError:
                await safe_reply(interaction, "❌ Warna HEX tidak valid.")
                return

        language = self.language.value.strip().lower() or "id"
        if language not in {"id", "en"}:
            language = "id"

        with closing(db()) as conn:
            conn.execute("""
                UPDATE hosts
                SET embed_title=?, embed_footer=?,
                    embed_color=?, language=?
                WHERE id=?
            """, (
                self.title.value.strip() or None,
                self.footer.value.strip() or None,
                color_value,
                language,
                self.host_id
            ))
            conn.commit()

        await safe_reply(interaction, "✅ Branding host diperbarui.")


class HostAdvancedView(discord.ui.View):
    def __init__(self, guild_id: int, host_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)
        self.host_id = int(host_id)

    @discord.ui.button(label="Delivery", emoji="📣", style=discord.ButtonStyle.secondary, row=0)
    async def delivery(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            HostDeliveryModal(self.host_id)
        )

    @discord.ui.button(label="Jadwal", emoji="🕒", style=discord.ButtonStyle.secondary, row=0)
    async def schedule(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            HostScheduleModal(self.host_id)
        )

    @discord.ui.button(label="Branding", emoji="🎨", style=discord.ButtonStyle.secondary, row=0)
    async def branding(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            HostBrandingModal(self.host_id)
        )

    @discord.ui.button(label="Recheck", emoji="🔄", style=discord.ButtonStyle.primary, row=1)
    async def recheck(self, interaction: discord.Interaction, button: discord.ui.Button):
        host = get_host(self.host_id)
        if not host:
            await safe_reply(interaction, "❌ Host tidak ditemukan.")
            return

        await defer_if_needed(interaction)

        try:
            if host["platform"] == "youtube":
                try:
                    await check_youtube_live(host)
                except Exception:
                    await check_youtube_live_fallback(host)

            elif host["platform"] == "tiktok":
                await check_tiktok_live(host)
                await check_tiktok_post(host)

            elif host["platform"] in {"twitch", "kick"}:
                await check_generic_live(host)

            elif host["platform"] in {"instagram", "facebook"}:
                await check_generic_content(host)

            set_host_health(host["id"], success=True)
            await interaction.followup.send(
                "✅ Recheck selesai.",
                ephemeral=True
            )
        except Exception as exc:
            set_host_health(host["id"], str(exc))
            await interaction.followup.send(
                f"❌ Recheck gagal: `{type(exc).__name__}: {exc}`",
                ephemeral=True
            )

    @discord.ui.button(label="Preview", emoji="👁️", style=discord.ButtonStyle.secondary, row=1)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        host = get_host(self.host_id)
        if not host:
            await safe_reply(interaction, "❌ Host tidak ditemukan.")
            return

        url = host_public_url(
            host,
            live=host["platform"] in {"youtube", "tiktok", "twitch", "kick"}
        )

        embed = discord.Embed(
            title="🔔 Preview Notifikasi",
            description=f"Contoh notifikasi untuk `{host['target']}`",
            url=url,
            color=discord.Color.blue()
        )
        apply_host_embed_branding(host, embed)

        await safe_reply(
            interaction,
            render_template(
                premium_host_template(host, "custom_live_message"),
                creator=host["display_name"] or host["target"],
                url=url,
                platform=host["platform"].title()
            ) or "Preview pesan default.",
            embed=embed
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        host = get_host(self.host_id)
        if not host:
            await safe_reply(interaction, "❌ Host tidak ditemukan.")
            return

        await interaction.response.edit_message(
            embed=host_embed(host),
            view=HostCardView(self.guild_id, self.host_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=2)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class FeatureFlagsModal(discord.ui.Modal):
    features = discord.ui.TextInput(
        label="Fitur aktif (pisahkan koma)",
        placeholder="tiktok_live,tiktok_post,youtube_live,twitch_live,kick_live,instagram_post,facebook_post,live_end",
        style=discord.TextStyle.paragraph,
        max_length=300
    )

    def __init__(self, guild_id: int):
        self.guild_id = int(guild_id)
        flags = feature_flags_for_guild(self.guild_id)
        super().__init__(title="Feature Flags", timeout=300)
        self.features.default = ",".join(
            key for key, enabled in flags.items()
            if enabled
        )

    async def on_submit(self, interaction: discord.Interaction):
        set_feature_flags(
            self.guild_id,
            self.features.value.split(",")
        )
        await safe_reply(interaction, "✅ Feature flags diperbarui.")


class ServerNotifierSettingsModal(discord.ui.Modal):
    timezone_name = discord.ui.TextInput(
        label="Timezone Server",
        placeholder="Asia/Jakarta",
        max_length=64
    )
    language = discord.ui.TextInput(
        label="Bahasa id/en",
        placeholder="id",
        max_length=5
    )

    def __init__(self, guild_id: int):
        self.guild_id = int(guild_id)
        settings = get_guild_settings(self.guild_id)
        super().__init__(title="Pengaturan Notifier", timeout=300)
        self.timezone_name.default = settings["timezone"] or "Asia/Jakarta"
        self.language.default = settings["language"] or "id"

    async def on_submit(self, interaction: discord.Interaction):
        try:
            set_guild_notifier_settings(
                self.guild_id,
                timezone_name=self.timezone_name.value.strip(),
                language=self.language.value.strip()
            )
        except ValueError as exc:
            await safe_reply(interaction, f"❌ {exc}")
            return

        await safe_reply(interaction, "✅ Pengaturan notifier diperbarui.")


class CloneConfigModal(discord.ui.Modal):
    target_guild_id = discord.ui.TextInput(
        label="Target Server ID",
        placeholder="123456789...",
        max_length=25
    )

    def __init__(self, source_guild_id: int):
        self.source_guild_id = int(source_guild_id)
        super().__init__(title="Clone Config", timeout=300)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.target_guild_id.value.strip()

        if not raw.isdigit():
            await safe_reply(interaction, "❌ Server ID harus angka.")
            return

        target = bot.get_guild(int(raw))
        if not target:
            await safe_reply(interaction, "❌ Target server tidak ditemukan.")
            return

        clone_notifier_config(
            self.source_guild_id,
            target.id
        )
        await safe_reply(
            interaction,
            f"✅ Config notifier dicopy ke **{target.name}**."
        )


class HostCSVImportModal(discord.ui.Modal):
    rows = discord.ui.TextInput(
        label="CSV: platform,target",
        placeholder="tiktok,username\nyoutube,UCxxxx",
        style=discord.TextStyle.paragraph,
        max_length=4000
    )

    def __init__(self, guild_id: int):
        self.guild_id = int(guild_id)
        super().__init__(title="Import Host CSV", timeout=600)

    async def on_submit(self, interaction: discord.Interaction):
        create_config_snapshot(
            self.guild_id,
            "before CSV import"
        )

        added = 0
        errors = 0

        for line in self.rows.value.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("platform,"):
                continue

            parts = [x.strip() for x in line.split(",")]
            if len(parts) < 2:
                errors += 1
                continue

            platform, target = parts[0].lower(), parts[1]

            if platform not in SUPPORTED_PLATFORMS or not target:
                errors += 1
                continue

            try:
                add_host(
                    self.guild_id,
                    platform,
                    normalize_social_target(platform, target)
                )
                added += 1
            except Exception:
                errors += 1

        await safe_reply(
            interaction,
            f"✅ Import selesai: **{added} berhasil**, **{errors} gagal**."
        )


class NotificationHistorySelect(discord.ui.Select):
    def __init__(self, guild_id: int):
        self.guild_id = int(guild_id)
        rows = recent_notifications(self.guild_id, 25)

        options = [
            discord.SelectOption(
                label=f"#{row['id']} • {row['event_type']} • {row['status']}"[:100],
                value=str(row["id"]),
                description=(
                    f"Host #{row['host_id']} • "
                    f"{datetime.fromtimestamp(row['created_at']).strftime('%d/%m %H:%M')}"
                )[:100]
            )
            for row in rows
        ]

        if not options:
            options = [
                discord.SelectOption(
                    label="Belum ada history",
                    value="0"
                )
            ]

        super().__init__(
            placeholder="Pilih notifikasi...",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        record_id = int(self.values[0])
        if not record_id:
            await safe_reply(interaction, "Belum ada history.")
            return

        row = get_notification_record(record_id)

        embed = discord.Embed(
            title=f"🧾 Notification #{record_id}",
            description=(
                f"Status **{row['status']}**\n"
                f"Event **{row['event_type']}**\n"
                f"Host **#{row['host_id']}**\n"
                f"Latency **{row['latency_ms'] or 0} ms**"
            ),
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(
            embed=embed,
            view=NotificationHistoryDetailView(
                self.guild_id,
                record_id
            )
        )


class NotificationHistoryView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)
        self.add_item(NotificationHistorySelect(self.guild_id))

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)
        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"🔔 Notifier • {guild.name if guild else self.guild_id}",
                color=discord.Color.blue()
            ),
            view=NotifierToolsView(self.guild_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class NotificationHistoryDetailView(discord.ui.View):
    def __init__(self, guild_id: int, record_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)
        self.record_id = int(record_id)

    @discord.ui.button(label="Kirim Ulang", emoji="🔁", style=discord.ButtonStyle.primary)
    async def resend(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok = await resend_notification_record(self.record_id)
        await safe_reply(
            interaction,
            "✅ Notifikasi dikirim ulang." if ok else "❌ Gagal mengirim ulang."
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🧾 Notification History",
                color=discord.Color.blue()
            ),
            view=NotificationHistoryView(self.guild_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class BulkNotifierView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)

    async def _set_all(self, enabled: bool):
        with closing(db()) as conn:
            conn.execute(
                "UPDATE hosts SET enabled=? WHERE guild_id=?",
                (1 if enabled else 0, self.guild_id)
            )
            conn.commit()

    @discord.ui.button(label="Resume Semua", emoji="▶️", style=discord.ButtonStyle.success, row=0)
    async def resume_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_all(True)
        await safe_reply(interaction, "✅ Semua host diaktifkan.")

    @discord.ui.button(label="Pause Semua", emoji="⏸️", style=discord.ButtonStyle.danger, row=0)
    async def pause_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._set_all(False)
        await safe_reply(interaction, "✅ Semua host dipause.")

    @discord.ui.button(label="Reset Error", emoji="♻️", style=discord.ButtonStyle.secondary, row=0)
    async def reset_errors(self, interaction: discord.Interaction, button: discord.ui.Button):
        with closing(db()) as conn:
            conn.execute("""
                UPDATE hosts
                SET last_error=NULL, error_count=0, cooldown_until=NULL
                WHERE guild_id=?
            """, (self.guild_id,))
            conn.commit()
        await safe_reply(interaction, "✅ Semua error host direset.")

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(title="🔔 Notifier Tools"),
            view=NotifierToolsView(self.guild_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class NotifierToolsView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)

    @discord.ui.button(label="Diagnostics", emoji="🩺", style=discord.ButtonStyle.primary, row=0)
    async def diagnostics(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)
        if not guild:
            await safe_reply(interaction, "❌ Server tidak ditemukan.")
            return
        await interaction.response.edit_message(
            embed=diagnostics_embed(guild),
            view=NotifierToolsView(self.guild_id)
        )

    @discord.ui.button(label="Statistik", emoji="📈", style=discord.ButtonStyle.secondary, row=0)
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=notifier_stats_embed(self.guild_id),
            view=NotifierToolsView(self.guild_id)
        )

    @discord.ui.button(label="History", emoji="🧾", style=discord.ButtonStyle.secondary, row=0)
    async def history(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🧾 Notification History",
                color=discord.Color.blue()
            ),
            view=NotificationHistoryView(self.guild_id)
        )

    @discord.ui.button(label="Bulk", emoji="📦", style=discord.ButtonStyle.secondary, row=0)
    async def bulk(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="📦 Bulk Action",
                description="Pause/resume/reset semua host.",
                color=discord.Color.blue()
            ),
            view=BulkNotifierView(self.guild_id)
        )

    @discord.ui.button(label="CSV", emoji="📄", style=discord.ButtonStyle.secondary, row=1)
    async def csv_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = host_csv_bytes(self.guild_id)
        await interaction.response.send_message(
            content="📄 Export host CSV. Untuk import tekan tombol **Import CSV**.",
            file=discord.File(
                io.BytesIO(data),
                filename=f"hosts-{self.guild_id}.csv"
            ),
            view=CSVImportButtonView(self.guild_id),
            ephemeral=True
        )

    @discord.ui.button(label="Clone", emoji="🧬", style=discord.ButtonStyle.secondary, row=1)
    async def clone(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            CloneConfigModal(self.guild_id)
        )

    @discord.ui.button(label="Settings", emoji="⚙️", style=discord.ButtonStyle.secondary, row=1)
    async def settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=server_notifier_settings_embed(self.guild_id),
            view=ServerNotifierSettingsView(self.guild_id)
        )

    @discord.ui.button(label="Snapshot", emoji="📸", style=discord.ButtonStyle.secondary, row=1)
    async def snapshot(self, interaction: discord.Interaction, button: discord.ui.Button):
        snapshot_id = create_config_snapshot(
            self.guild_id,
            "manual"
        )
        await safe_reply(
            interaction,
            f"✅ Snapshot **#{snapshot_id}** dibuat."
        )

    @discord.ui.button(label="Rollback", emoji="↩️", style=discord.ButtonStyle.secondary, row=2)
    async def rollback(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = latest_config_snapshot(self.guild_id)

        if not row:
            await safe_reply(interaction, "Belum ada snapshot.")
            return

        data = json.loads(row["payload"])
        restore_guild_backup(
            data,
            self.guild_id
        )
        await safe_reply(
            interaction,
            f"✅ Rollback snapshot **#{row['id']}** selesai."
        )

    @discord.ui.button(label="Changelog", emoji="🆕", style=discord.ButtonStyle.secondary, row=2)
    async def changelog(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safe_reply(
            interaction,
            (
                "**Notifier Pro 2026.10**\n"
                "Multi-channel/role • quiet hours • history/resend • "
                "fallback checker • diagnostics • CSV • clone • rollback • "
                "feature flags • maintenance • queue protection."
            )
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)
        if not guild:
            await safe_reply(interaction, "❌ Server tidak ditemukan.")
            return
        await interaction.response.edit_message(
            embed=server_embed(guild),
            view=ServerOwnerView(self.guild_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=3)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class CSVImportButtonView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=600)
        self.guild_id = int(guild_id)

    @discord.ui.button(label="Import CSV", emoji="📥", style=discord.ButtonStyle.primary)
    async def import_csv(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            HostCSVImportModal(self.guild_id)
        )


def server_notifier_settings_embed(guild_id: int):
    settings = get_guild_settings(guild_id)
    flags = feature_flags_for_guild(guild_id)

    embed = discord.Embed(
        title="⚙️ Notifier Settings",
        description=(
            f"Timezone **{settings['timezone'] or 'Asia/Jakarta'}**\n"
            f"Bahasa **{settings['language'] or 'id'}**\n"
            f"Maintenance **{'ON' if settings['maintenance_mode'] else 'OFF'}**"
        ),
        color=discord.Color.blue()
    )
    embed.add_field(
        name="Feature Flags",
        value="\n".join(
            f"{'✅' if value else '⛔'} {key}"
            for key, value in flags.items()
        ),
        inline=False
    )
    return embed


class ServerNotifierSettingsView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)

    @discord.ui.button(label="Timezone/Bahasa", emoji="🌐", style=discord.ButtonStyle.secondary, row=0)
    async def locale(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            ServerNotifierSettingsModal(self.guild_id)
        )

    @discord.ui.button(label="Feature Flags", emoji="🚩", style=discord.ButtonStyle.secondary, row=0)
    async def flags(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            FeatureFlagsModal(self.guild_id)
        )

    @discord.ui.button(label="Maintenance", emoji="🛠️", style=discord.ButtonStyle.danger, row=0)
    async def maintenance(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = get_guild_settings(self.guild_id)
        enabled = not bool(settings["maintenance_mode"])

        set_guild_notifier_settings(
            self.guild_id,
            maintenance_mode=enabled
        )

        guild = bot.get_guild(self.guild_id)
        text = (
            "🛠️ Hi Notifku sedang **maintenance konfigurasi**. "
            "Monitoring host tetap berjalan."
            if enabled
            else "✅ Maintenance Hi Notifku selesai."
        )

        if guild:
            cfg = get_config(guild.id)
            channel = await resolve_channel(
                cfg["log_channel_id"] or (
                    guild.system_channel.id if guild.system_channel else None
                )
            )
            if channel:
                try:
                    await channel.send(text)
                except Exception:
                    pass

        await interaction.response.edit_message(
            embed=server_notifier_settings_embed(self.guild_id),
            view=ServerNotifierSettingsView(self.guild_id)
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(title="🔔 Notifier Tools"),
            view=NotifierToolsView(self.guild_id)
        )

    @discord.ui.button(label="Menu Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class ServerOwnerView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)

    async def valid(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return None

        guild = bot.get_guild(self.guild_id)

        if guild is None:
            await safe_reply(interaction, "❌ Server tidak ditemukan.")
            return None

        return guild

    @discord.ui.button(
        label="Host",
        emoji="📡",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def hosts(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = await self.valid(interaction)
        if not guild:
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"📡 Host • {guild.name}",
                description=f"Total **{len(get_hosts(guild.id))}** host.",
                color=discord.Color.blue()
            ),
            view=HostMenuView(guild.id)
        )

    @discord.ui.button(
        label="Default",
        emoji="⚙️",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def defaults(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = await self.valid(interaction)
        if not guild:
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"⚙️ Default • {guild.name}",
                description="Atur channel, role, dan log.",
                color=discord.Color.blue()
            ),
            view=DefaultConfigView(guild.id)
        )

    @discord.ui.button(
        label="Wizard",
        emoji="🧭",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def wizard(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = await self.valid(interaction)
        if not guild:
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"🧭 Setup • {guild.name}",
                description="Atur 4 langkah utama.",
                color=discord.Color.blue()
            ),
            view=WizardView(guild.id)
        )

    @discord.ui.button(
        label="Notif",
        emoji="🔔",
        style=discord.ButtonStyle.primary,
        row=1
    )
    async def notifier_tools(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = await self.valid(interaction)
        if not guild:
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"🔔 Notifier • {guild.name}",
                description="Diagnostics, statistik, history, bulk, CSV, clone, dan settings.",
                color=discord.Color.blue()
            ),
            view=NotifierToolsView(guild.id)
        )

    @discord.ui.button(
        label="Plan",
        emoji="⭐",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def plan(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = await self.valid(interaction)
        if not guild:
            return

        settings = get_guild_settings(guild.id)
        effective_plan = "premium" if premium_access_effective(guild.id) else "free"

        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"⭐ Plan • {guild.name}",
                description=(
                    f"Plan **{effective_plan.upper()}**\n"
                    f"{premium_expiry_text(guild.id) if effective_plan=='premium' else 'FREE'}"
                ),
                color=discord.Color.gold()
            ),
            view=PlanServerManageView(guild.id)
        )

    @discord.ui.button(
        label="Backup",
        emoji="💾",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def backup(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = await self.valid(interaction)
        if not guild:
            return

        payload = export_guild_backup(guild.id)
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2
        ).encode("utf-8")

        await interaction.response.send_message(
            content=f"💾 Backup **{guild.name}**",
            file=discord.File(
                io.BytesIO(raw),
                filename=f"hi-notifku-{guild.id}.json"
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="Refresh",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = await self.valid(interaction)
        if not guild:
            return

        await interaction.response.edit_message(
            embed=server_embed(guild),
            view=ServerOwnerView(guild.id)
        )

    @discord.ui.button(
        label="Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_global_owner(interaction):
            return

        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🔎 Browser Server",
                description=f"Total server: **{len(bot.guilds)}**",
                color=discord.Color.blue()
            ),
            view=ServerBrowserView(0, "")
        )


class HostSearchModal(discord.ui.Modal):
    query = discord.ui.TextInput(
        label="Host ID / Username / Channel ID",
        placeholder="Contoh: 12 / creator123 / UC...",
        max_length=120
    )

    def __init__(self, guild_id: int):
        super().__init__(title="Cari Host", timeout=300)
        self.guild_id = int(guild_id)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🔎 Host",
                description=f"Hasil untuk `{self.query.value.strip()}`",
                color=discord.Color.blue()
            ),
            view=HostBrowserView(
                self.guild_id,
                page=0,
                query=self.query.value.strip()
            )
        )


class HostAdminSelect(discord.ui.Select):
    def __init__(self, guild_id: int, page: int = 0, query: str = ""):
        self.guild_id = int(guild_id)
        self.page = max(0, int(page))
        self.query = query.strip().lower()

        hosts = list(get_hosts(self.guild_id))

        if self.query:
            hosts = [
                h for h in hosts
                if self.query in str(h["id"]).lower()
                or self.query in str(h["target"]).lower()
                or self.query in str(h["display_name"] or "").lower()
            ]

        start = self.page * 25
        current = hosts[start:start + 25]

        options = [
            discord.SelectOption(
                label=(
                    f"#{h['id']} • "
                    f"{platform_display_name(h['platform'])} • "
                    f"{h['target']}"
                )[:100],
                value=str(h["id"]),
                description=host_status_text(h)[:100]
            )
            for h in current
        ]

        if not options:
            options = [
                discord.SelectOption(
                    label="Tidak ada host",
                    value="0"
                )
            ]

        super().__init__(
            placeholder=f"Pilih host • Halaman {self.page + 1}",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if not await require_global_owner(interaction):
            return

        host_id = int(self.values[0])

        if host_id == 0:
            await safe_reply(interaction, "Host tidak ditemukan.")
            return

        host = get_host(host_id)

        if not host or int(host["guild_id"]) != self.guild_id:
            await safe_reply(interaction, "❌ Host tidak ditemukan.")
            return

        await interaction.response.edit_message(
            embed=host_embed(host),
            view=HostCardView(self.guild_id, host_id)
        )


class HostBrowserView(discord.ui.View):
    def __init__(self, guild_id: int, page: int = 0, query: str = ""):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)
        self.page = max(0, int(page))
        self.query = query
        self.add_item(
            HostAdminSelect(
                self.guild_id,
                self.page,
                self.query
            )
        )

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            view=HostBrowserView(
                self.guild_id,
                max(0, self.page - 1),
                self.query
            )
        )

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        hosts = list(get_hosts(self.guild_id))

        if self.query:
            q = self.query.lower()
            hosts = [
                h for h in hosts
                if q in str(h["id"]).lower()
                or q in str(h["target"]).lower()
                or q in str(h["display_name"] or "").lower()
            ]

        max_page = max(0, (len(hosts) - 1) // 25)

        await interaction.response.edit_message(
            view=HostBrowserView(
                self.guild_id,
                min(max_page, self.page + 1),
                self.query
            )
        )

    @discord.ui.button(label="Cari", emoji="🔎", style=discord.ButtonStyle.secondary, row=1)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            HostSearchModal(self.guild_id)
        )

    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="📡 Host",
                description=f"Total **{len(get_hosts(self.guild_id))}** host.",
                color=discord.Color.blue()
            ),
            view=HostMenuView(self.guild_id)
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


class HostMenuView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.guild_id = guild_id

    @discord.ui.button(label="Tambah", emoji="➕", style=discord.ButtonStyle.success)
    async def add_host_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_global_owner(interaction):
            return
        await interaction.response.send_modal(
            AddHostModal(self.guild_id)
        )

    @discord.ui.button(label="Import", emoji="📥", style=discord.ButtonStyle.secondary)
    async def bulk(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_global_owner(interaction):
            return
        await interaction.response.send_modal(
            BulkImportModal(self.guild_id)
        )

    @discord.ui.button(label="Host", emoji="📋", style=discord.ButtonStyle.primary)
    async def list_hosts_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_global_owner(interaction):
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="📋 Browser Host",
                description=f"Total **{len(get_hosts(self.guild_id))}** host.",
                color=discord.Color.blue()
            ),
            view=HostBrowserView(self.guild_id)
        )


    @discord.ui.button(label="Kembali", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)

        if not guild:
            await safe_reply(interaction, "❌ Server tidak ditemukan.")
            return

        await interaction.response.edit_message(
            embed=server_embed(guild),
            view=ServerOwnerView(self.guild_id)
        )

    @discord.ui.button(label="Awal", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
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

        with closing(db()) as conn:
            conn.execute(
                "UPDATE guild_settings SET setup_completed=1 WHERE guild_id=?",
                (self.guild_id,)
            )
            conn.commit()

        if guild:
            await interaction.response.edit_message(
                embed=server_embed(guild),
                view=ServerOwnerView(self.guild_id)
            )

    @discord.ui.button(
        label="Kembali",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = bot.get_guild(self.guild_id)

        if not guild:
            await safe_reply(interaction, "❌ Server tidak ditemukan.")
            return

        await interaction.response.edit_message(
            embed=server_embed(guild),
            view=ServerOwnerView(self.guild_id)
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=owner_home_embed(),
            view=OwnerHomeView()
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
            ("Lanjutan", "🛠️", discord.ButtonStyle.primary, 4, self.advanced),
            ("Manager Host", "🎙️", discord.ButtonStyle.primary, 4, self.managers),
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
            premium_host_template(host, "custom_live_message"),
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
            premium_host_template(host, "custom_post_message"),
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
            premium_host_template(host, "custom_live_message"),
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

    async def managers(self, interaction):
        host = await self.valid_host(interaction)
        if not host:
            return

        managers = list_host_managers(self.host_id)

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🎙️ Owner • Host Manager",
                description=(
                    f"Host: **{platform_display_name(host['platform'])} • "
                    f"{host['display_name'] or host['target']}**\n"
                    f"Manager terdaftar: **{len(managers)}**\n\n"
                    "Panel ini khusus Owner untuk assign/revoke Host Manager. "
                    "Host Manager tidak dapat masuk ke panel Owner."
                ),
                color=discord.Color.blue()
            ),
            view=OwnerHostManagerView(
                self.guild_id,
                self.host_id
            )
        )

    async def advanced(self, interaction):
        host = await self.valid_host(interaction)
        if not host:
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"🛠️ Lanjutan • #{self.host_id}",
                description=(
                    "Multi-channel/role, webhook, jadwal, quiet hours, "
                    "branding, preview, dan manual recheck."
                ),
                color=discord.Color.blue()
            ),
            view=HostAdvancedView(
                self.guild_id,
                self.host_id
            )
        )

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




class RestoreConfirmView(discord.ui.View):
    def __init__(self, actor_id: int):
        super().__init__(timeout=600)
        self.actor_id = actor_id

    @discord.ui.button(
        label="Konfirmasi Restore",
        emoji="✅",
        style=discord.ButtonStyle.danger
    )
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.actor_id:
            await safe_reply(interaction, "❌ Ini bukan restore milikmu.")
            return

        item = pending_restore_previews.pop(self.actor_id, None)

        if not item:
            await safe_reply(interaction, "⌛ Preview restore sudah kedaluwarsa.")
            return

        data = item["data"]
        guild_id = item["guild_id"]

        restore_guild_backup(
            data,
            guild_id
        )

        with closing(db()) as conn:
            conn.execute("""
                INSERT INTO restore_audit(
                    guild_id, actor_id, created_at, summary
                )
                VALUES(?,?,?,?)
            """, (
                guild_id,
                interaction.user.id,
                int(time.time()),
                f"Restore confirmed; hosts={len(data.get('hosts') or [])}"
            ))
            conn.commit()

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ Restore Selesai",
                description=f"Backup diterapkan ke server `{guild_id}`.",
                color=discord.Color.green()
            ),
            view=None
        )

    @discord.ui.button(
        label="Batal",
        emoji="✖️",
        style=discord.ButtonStyle.secondary
    )
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        pending_restore_previews.pop(self.actor_id, None)
        await interaction.response.edit_message(
            content="Restore dibatalkan.",
            embed=None,
            view=None
        )

    @discord.ui.button(
        label="Menu Awal",
        emoji="🏠",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        pending_restore_previews.pop(self.actor_id, None)
        await interaction.response.edit_message(
            content=None,
            embed=owner_home_embed(),
            view=OwnerHomeView()
        )


# ============================================================
# ONE GLOBAL SLASH COMMAND
# ============================================================

async def require_dm_command(
    interaction: discord.Interaction
) -> bool:
    """
    All slash-command control surfaces are DM-only.

    The bot may stay in any guild and continue sending notifications,
    but users cannot operate slash commands from guild channels.
    """
    if interaction.guild is None:
        return True

    await safe_reply(
        interaction,
        (
            "📩 **Command Hi Notifku hanya dapat digunakan melalui DM bot.**\n"
            "Bot boleh berada di server ini untuk menjalankan notifier, "
            "tetapi panel/command tidak dapat dijalankan dari channel server.\n\n"
            "Buka profil **Hi Notifku** → **Message/Kirim Pesan**."
        )
    )
    return False


@discord.app_commands.allowed_contexts(
    guilds=False,
    dms=True,
    private_channels=True
)
@bot.tree.command(
    name="ping",
    description="Cek status, latency, database, dan storage Hi Notifku."
)
async def ping_command(interaction: discord.Interaction):
    if not await require_dm_command(interaction):
        return

    try:
        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        ip_info = await current_ip_info()
        embed = bot_status_embed()
        apply_ip_fields(
            embed,
            ip_info
        )

        await interaction.edit_original_response(
            embed=embed,
            view=PingView(
                interaction.user.id
            )
        )

    except Exception as exc:
        log.exception("/ping error")

        try:
            await interaction.followup.send(
                f"❌ Gagal membaca status bot: `{type(exc).__name__}: {exc}`",
                ephemeral=True
            )
        except Exception:
            pass


@discord.app_commands.allowed_contexts(
    guilds=False,
    dms=True,
    private_channels=True
)
@bot.tree.command(
    name="start",
    description="Verifikasi join server resmi Hi Notifku."
)
async def start_command(interaction: discord.Interaction):
    if not await require_dm_command(interaction):
        return

    if SAFE_MODE:
        await safe_reply(
            interaction,
            "🛠️ Hi Notifku sedang **Safe Mode**. Hanya `/owner` untuk diagnosis."
        )
        return

    if is_user_blacklisted(interaction.user.id):
        await safe_reply(
            interaction,
            "🚫 Akunmu dibatasi dari penggunaan Hi Notifku. Hubungi owner."
        )
        return

    if action_rate_limited(interaction.user.id, "start"):
        await safe_reply(
            interaction,
            "⏳ Terlalu cepat. Tunggu beberapa detik lalu coba lagi."
        )
        return

    try:
        if is_global_owner(interaction.user.id):
            verified_count, owned_count = await verify_owned_guilds_for_user(
                interaction.user.id
            )
            embed = start_verify_embed(
                interaction.user.id,
                True
            )
            if owned_count:
                embed.add_field(
                    name="Server Milikmu",
                    value=(
                        f"✅ {verified_count}/{owned_count} server diverifikasi.\n"
                        "`/start` hanya refresh manual; auto-verifikasi tetap berjalan."
                    ),
                    inline=False
                )
            await safe_reply(
                interaction,
                "",
                embed=embed
            )
            return

        if not REQUIRED_GUILD_ID:
            await safe_reply(
                interaction,
                "⚠️ Server Resmi Owner/Support belum dikonfigurasi oleh owner bot."
            )
            return

        verified = await refresh_user_verification(
            interaction.user.id,
            source="start_command",
            mark_active=True
        )

        if verified:
            verified_count, owned_count = await verify_owned_guilds_for_user(
                interaction.user.id
            )
            embed = start_verify_embed(
                interaction.user.id,
                True
            )
            if owned_count:
                embed.add_field(
                    name="Server Milikmu",
                    value=(
                        f"✅ **{verified_count}/{owned_count}** server "
                        "berhasil diverifikasi.\n"
                        "`/start` hanya refresh manual; auto-verifikasi tetap berjalan."
                    ),
                    inline=False
                )
            embed.add_field(
                name="Verifikasi User",
                value=user_verification_status_text(
                    interaction.user.id
                ),
                inline=False
            )

            await safe_reply(
                interaction,
                "",
                embed=embed
            )
        else:
            await safe_reply(
                interaction,
                "",
                embed=start_verify_embed(
                    interaction.user.id,
                    False
                ),
                view=StartVerifyView()
            )

    except Exception as exc:
        log.exception("/start error")
        await safe_reply(
            interaction,
            f"❌ Gagal melakukan verifikasi: `{type(exc).__name__}: {exc}`"
        )


@discord.app_commands.allowed_contexts(
    guilds=False,
    dms=True,
    private_channels=True
)
@bot.tree.command(
    name="menu",
    description="Buka menu pengguna Hi Notifku melalui DM."
)
async def menu_command(interaction: discord.Interaction):
    if not await require_dm_command(interaction):
        return

    if SAFE_MODE:
        await safe_reply(
            interaction,
            "🛠️ Hi Notifku sedang **Safe Mode**. Hanya `/owner` untuk diagnosis."
        )
        return

    if is_user_blacklisted(interaction.user.id):
        await safe_reply(
            interaction,
            "🚫 Akunmu dibatasi dari penggunaan Hi Notifku. Hubungi owner."
        )
        return

    if action_rate_limited(interaction.user.id, "menu"):
        await safe_reply(
            interaction,
            "⏳ Terlalu cepat. Tunggu beberapa detik lalu coba lagi."
        )
        return

    try:
        # Global owners may use /owner for administration.
        # /menu remains the normal user/server-owner interface.
        if not is_global_owner(interaction.user.id):
            if not REQUIRED_GUILD_ID:
                await safe_reply(
                    interaction,
                    "⚠️ Server Resmi Owner/Support belum dikonfigurasi."
                )
                return

            verified = user_verification_is_active(
                interaction.user.id
            )

            if not verified:
                # Recovery path: if cache expired/missing but user is still
                # a Support member, verify automatically without manual approval.
                verified = await refresh_user_verification(
                    interaction.user.id,
                    source="menu_auto_refresh",
                    mark_active=True
                )
            else:
                touch_user_verification_activity(
                    interaction.user.id
                )

            if verified:
                await verify_owned_guilds_for_user(
                    interaction.user.id
                )

            if not verified:
                await safe_reply(
                    interaction,
                    (
                        "🔒 Kamu belum terverifikasi.\n"
                        "Join **Server Owner/Support** terlebih dahulu. "
                        "Verifikasi akan aktif otomatis. Setelah terverifikasi, status user disimpan hingga 30 hari sejak aktivitas terakhir."
                    ),
                    embed=start_verify_embed(
                        interaction.user.id,
                        False
                    ),
                    view=StartVerifyView()
                )
                return

        guilds = user_owned_guilds(interaction.user.id)
        managed_hosts = host_manager_rows(interaction.user.id)
        managed_guilds = host_manager_guild_ids(interaction.user.id)

        if not guilds and not managed_guilds:
            mutual = await user_mutual_guilds(
                interaction.user.id
            )
            guild_ids = [
                int(guild.id)
                for guild in mutual
            ]

            if not guild_ids:
                await safe_reply(
                    interaction,
                    (
                        "ℹ️ Kamu belum memiliki server atau akses Host Manager, "
                        "dan tidak ditemukan server mutual yang memakai Hi Notifku."
                    )
                )
                return

            await interaction.response.send_message(
                embed=server_owner_contact_embed(
                    interaction.user.id,
                    guild_ids
                ),
                view=ServerOwnerContactView(
                    interaction.user.id,
                    guild_ids
                ),
                ephemeral=False
            )
            return

        await interaction.response.send_message(
            embed=dm_menu_home_embed(interaction.user.id),
            view=MenuRoleChoiceView(interaction.user.id),
            ephemeral=False
        )

    except Exception as exc:
        log.exception("/menu error")

        if interaction.response.is_done():
            await interaction.followup.send(
                f"❌ Gagal membuka menu: `{type(exc).__name__}: {exc}`"
            )
        else:
            await interaction.response.send_message(
                f"❌ Gagal membuka menu: `{type(exc).__name__}: {exc}`"
            )


@discord.app_commands.allowed_contexts(
    guilds=False,
    dms=True,
    private_channels=True
)
@bot.tree.command(
    name="owner",
    description="Buka panel khusus Global Owner Bot Hi Notifku."
)
async def owner_command(interaction: discord.Interaction):
    if not await require_dm_command(interaction):
        return

    if not is_global_owner(interaction.user.id):
        owned = user_owned_guilds(
            interaction.user.id
        )
        managed = host_manager_guild_ids(
            interaction.user.id
        )

        if owned and managed:
            route = (
                "Kamu terdeteksi sebagai **Pemilik Server + Host Manager**.\n"
                "Gunakan `/menu` lalu pilih peran yang sesuai."
            )
        elif owned:
            route = (
                "Kamu terdeteksi sebagai **Pemilik Server**.\n"
                "Gunakan `/menu → 👑 Pemilik Server`."
            )
        elif managed:
            route = (
                "Kamu terdeteksi sebagai **Host Manager**.\n"
                "Gunakan `/menu → 🎙️ Host Manager`."
            )
        else:
            route = (
                "Akunmu bukan Global Owner Bot. Gunakan `/menu` "
                "untuk fitur pengguna."
            )

        await safe_reply(
            interaction,
            "🔒 `/owner` khusus **Global Owner Bot Hi Notifku**.\n\n" + route
        )
        return

    try:
        dm = interaction.user.dm_channel

        if dm is None:
            dm = await interaction.user.create_dm()

        await dm.send(
            embed=owner_home_embed(),
            view=OwnerHomeView(interaction.user.id)
        )

        await audit_webhook(
            "Owner Panel Opened",
            "Global owner membuka panel /owner.",
            actor_id=interaction.user.id
        )

        await safe_reply(
            interaction,
            "✅ Panel khusus Owner sudah dikirim ke DM kamu."
        )

    except discord.Forbidden:
        await safe_reply(
            interaction,
            "❌ Saya tidak bisa mengirim DM ke akunmu. Aktifkan DM lalu jalankan `/owner` lagi."
        )

    except Exception as exc:
        log.exception("/owner error")
        await safe_reply(
            interaction,
            f"❌ Gagal membuka panel owner: `{type(exc).__name__}: {exc}`"
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

        pending_restore_previews[message.author.id] = {
            "data": data,
            "guild_id": guild_id,
            "created_at": int(time.time()),
        }

        await message.channel.send(
            embed=backup_preview_embed(data),
            view=RestoreConfirmView(message.author.id)
        )

    except Exception as exc:
        await message.channel.send(
            f"❌ Preview restore gagal: `{type(exc).__name__}: {exc}`"
        )

    return True


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.guild is None:
        # Payment proof upload from any user, including Global Owner.
        # Proof handling must run before the Global Owner QRIS-upload flow so
        # owners can also test/buy Premium without their proof being skipped.
        if message.attachments:
            order = latest_waiting_proof_order(message.author.id)

            if order:
                if len(message.attachments) != 1:
                    await message.channel.send(
                        "❌ Kirim tepat **1 screenshot bukti transfer** dalam satu pesan "
                        "agar screening otomatis dapat dijalankan."
                    )
                    return

                attachment = message.attachments[0]
                proof_url = attachment.url
                scan_notice = await message.channel.send(
                    "🔎 Bukti diterima. Sedang melakukan **screening otomatis**..."
                )

                try:
                    proof_bytes = await attachment.read()
                    proof_hash_value = hashlib.sha256(
                        proof_bytes
                    ).hexdigest()

                    scan = await asyncio.to_thread(
                        scan_payment_proof_bytes,
                        proof_bytes,
                        filename=attachment.filename or "",
                        content_type=attachment.content_type or ""
                    )

                    save_payment_proof(
                        int(order["id"]),
                        proof_url,
                        int(message.id),
                        proof_hash_value,
                        scan=scan
                    )
                except ValueError as exc:
                    try:
                        await scan_notice.edit(content=f"❌ Screening gagal: {exc}")
                    except Exception:
                        await message.channel.send(f"❌ Screening gagal: {exc}")
                    return
                except Exception as exc:
                    log.exception("Screening bukti pembayaran gagal")
                    try:
                        await scan_notice.edit(
                            content=(
                                "❌ Screening bukti gagal diproses. "
                                f"`{type(exc).__name__}`. Silakan kirim ulang bukti."
                            )
                        )
                    except Exception:
                        await message.channel.send(
                            "❌ Screening bukti gagal diproses. Silakan kirim ulang bukti."
                        )
                    return

                updated_order = get_premium_order(int(order["id"]))

                # Forward proof details to all primary owners.
                embed = premium_order_embed(updated_order)
                embed.title = f"📎 Bukti Pembayaran #{order['id']}"
                embed.description = (
                    f"Bukti pembayaran baru dari <@{message.author.id}>.\n"
                    f"{payment_proof_scan_label(updated_order)}"
                )

                for owner_id in primary_owner_ids():
                    try:
                        owner = bot.get_user(owner_id) or await bot.fetch_user(owner_id)
                        await owner.send(
                            embed=embed,
                            view=PremiumOrderManageView(int(order["id"]))
                        )
                    except Exception:
                        log.exception(
                            "Gagal meneruskan bukti pembayaran ke owner_id=%s",
                            owner_id
                        )

                invoice_ref = (
                    updated_order["invoice_ref"]
                    or ensure_invoice_ref(updated_order["id"])
                )

                await send_payment_admin_log(
                    "📎 Bukti Pembayaran Baru",
                    (
                        f"Invoice: `{invoice_ref}`\n"
                        f"User: <@{message.author.id}>\n"
                        f"Nominal wajib: **{rupiah(int(updated_order['expected_amount'] or updated_order['price']))}**"
                    ),
                    guild_id=int(updated_order["guild_id"])
                )

                auto_ok = False
                auto_message = ""

                try:
                    auto_ok, auto_message = await maybe_auto_activate_verified_order(
                        int(updated_order["id"]),
                        actor_id=(
                            int(updated_order["processed_by"])
                            if updated_order["processed_by"]
                            else 0
                        ),
                        source="proof_uploaded_after_payment_verification"
                    )
                except Exception:
                    log.exception("Auto aktivasi setelah upload bukti gagal")

                scan_text = payment_proof_scan_label(updated_order)

                final_scan_message = (
                    f"✅ Bukti `{invoice_ref}` sudah diterima dan selesai discan.\n"
                    f"Screening: {scan_text}\n"
                    + (
                        "⭐ Pembayaran sebelumnya sudah terverifikasi, "
                        "jadi Premium otomatis diaktifkan."
                        if auto_ok
                        else (
                            "⏳ Menunggu verifikasi pembayaran/nominal masuk.\n"
                            "Pastikan screenshot yang dikirim sudah mengikuti instruksi "
                            "agar tidak masuk REVIEW/DITOLAK."
                        )
                    )
                )
                try:
                    await scan_notice.edit(content=final_scan_message)
                except Exception:
                    await message.channel.send(final_scan_message)
                return

        if is_global_owner(message.author.id):
            # QRIS image upload flow.
            pending_upload = get_pending_upload(message.author.id)
            pending_method_id = (
                pending_qris_uploads.get(message.author.id)
                or (
                    int(pending_upload["target_id"])
                    if pending_upload and pending_upload["upload_type"] == "qris"
                    else None
                )
            )

            if pending_method_id and message.attachments:
                method_id = int(pending_method_id)
                method = get_payment_method(method_id)

                if not method:
                    pending_qris_uploads.pop(message.author.id, None)
                    clear_pending_upload(message.author.id)
                    await message.channel.send(
                        "❌ Data QRIS tidak ditemukan. Silakan ulangi dari `/owner`."
                    )
                    return

                attachment = message.attachments[0]

                content_type = (attachment.content_type or "").lower()
                filename = (attachment.filename or "").lower()

                is_image = (
                    content_type.startswith("image/")
                    or filename.endswith((".png", ".jpg", ".jpeg", ".webp"))
                )

                if not is_image:
                    await message.channel.send(
                        "❌ File harus berupa gambar QRIS (PNG/JPG/JPEG/WEBP)."
                    )
                    return

                try:
                    stored_path = await save_qris_attachment(
                        method_id,
                        attachment
                    )
                except ValueError as exc:
                    await message.channel.send(
                        f"❌ {exc}"
                    )
                    return
                except Exception as exc:
                    log.exception("Gagal menyimpan gambar QRIS permanen")
                    await message.channel.send(
                        f"❌ Gagal menyimpan gambar QRIS: `{type(exc).__name__}`"
                    )
                    return

                pending_qris_uploads.pop(message.author.id, None)
                clear_pending_upload(message.author.id)

                method = get_payment_method(method_id)

                embed = payment_method_embed(method)
                embed.title = f"✅ QRIS #{method_id} Tersimpan"
                embed.description = (
                    f"Gambar disimpan permanen di storage bot.\n"
                    f"`{stored_path}`"
                )

                qris_file = apply_qris_attachment_image(
                    embed,
                    method
                )

                if qris_file:
                    await message.channel.send(
                        embed=embed,
                        file=qris_file
                    )
                else:
                    await message.channel.send(
                        embed=embed
                    )
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

        try:
            await message.channel.send(
                "📩 Gunakan **`/menu` di DM ini** untuk membuka menu Hi Notifku.\n"
                "Menu pengguna tidak lagi dibuka dari channel server."
            )
        except Exception:
            pass
        return

    bot_mentioned = bot.user is not None and bot.user in message.mentions

    if bot_mentioned:
        try:
            embed = discord.Embed(
                title="📩 Hi Notifku",
                description=(
                    "Gunakan **`/start`** untuk verifikasi join Server Support.\n"
                    "Lalu buka **DM bot** dan gunakan **`/menu`** untuk paket FREE/PREMIUM.\n"
                    "Global Owner menggunakan **`/owner`** untuk pengaturan lengkap."
                ),
                color=discord.Color.blue()
            )

            await message.reply(
                embed=embed,
                mention_author=False
            )
        except Exception:
            log.exception("Redirect command gagal")

        return

    await bot.process_commands(message)


@bot.listen("on_interaction")
async def track_verified_user_activity(
    interaction: discord.Interaction
):
    try:
        user = interaction.user
        if not user or getattr(user, "bot", False):
            return

        if is_global_owner(user.id):
            return

        if user_verification_is_active(user.id):
            touch_user_verification_activity(user.id)

    except Exception:
        log.exception("Gagal memperbarui aktivitas verifikasi user")




@bot.event
async def on_member_join(member: discord.Member):
    try:
        if not REQUIRED_GUILD_ID:
            return

        if int(member.guild.id) != int(REQUIRED_GUILD_ID):
            return

        if not is_global_owner(member.id):
            set_user_verification(
                member.id,
                True,
                source="support_member_join",
                reason="User join Server Owner/Support.",
                mark_active=True
            )

        updated = await auto_verify_owned_guilds_for_member(
            member.id,
            verified=True
        )

        if updated:
            log.info(
                "Auto-verifikasi owner user_id=%s untuk %s guild",
                member.id,
                updated
            )

            await notify_owner_auto_verification(
                member.id,
                verified=True,
                guild_count=updated
            )

            try:
                await audit_webhook(
                    "Owner Auto Verified",
                    (
                        f"User {member.id} join Server Owner/Support dan "
                        f"{updated} server otomatis diverifikasi."
                    ),
                    actor_id=member.id
                )
            except Exception:
                pass

    except Exception:
        log.exception(
            "on_member_join auto owner verification error"
        )


@bot.event
async def on_member_remove(member: discord.Member):
    try:
        if not REQUIRED_GUILD_ID:
            return

        if int(member.guild.id) != int(REQUIRED_GUILD_ID):
            return

        if not is_global_owner(member.id):
            set_user_verification(
                member.id,
                False,
                source="support_member_remove",
                reason="User keluar dari Server Owner/Support.",
                mark_active=False
            )

        updated = await auto_verify_owned_guilds_for_member(
            member.id,
            verified=False
        )

        if updated:
            log.info(
                "Auto-cabut verifikasi owner user_id=%s untuk %s guild",
                member.id,
                updated
            )

            await notify_owner_auto_verification(
                member.id,
                verified=False,
                guild_count=updated
            )

            try:
                await audit_webhook(
                    "Owner Verification Revoked",
                    (
                        f"User {member.id} keluar Server Owner/Support dan "
                        f"{updated} server kembali belum terverifikasi."
                    ),
                    actor_id=member.id
                )
            except Exception:
                pass

    except Exception:
        log.exception(
            "on_member_remove auto owner verification error"
        )




@bot.event
async def on_guild_update(
    before: discord.Guild,
    after: discord.Guild
):
    try:
        if int(before.owner_id) == int(after.owner_id):
            return

        verified = await refresh_guild_owner_verification(
            after,
            source="owner_transfer"
        )

        try:
            new_owner = (
                after.owner
                or await after.fetch_member(after.owner_id)
            )

            if verified:
                await new_owner.send(
                    embed=discord.Embed(
                        title="✅ Kepemilikan Server Terdeteksi",
                        description=(
                            f"Kamu sekarang menjadi Pemilik Server **{after.name}**.\n"
                            "Karena akunmu sudah berada di Server Owner/Support, "
                            "verifikasi server otomatis **AKTIF**."
                        ),
                        color=discord.Color.green()
                    )
                )
            else:
                await new_owner.send(
                    embed=discord.Embed(
                        title="🔒 Verifikasi Owner Diperlukan",
                        description=(
                            f"Kamu sekarang menjadi Pemilik Server **{after.name}**.\n"
                            "Join Server Owner/Support agar verifikasi server "
                            "aktif otomatis. Tidak perlu approval manual atau `/start`."
                        ),
                        color=discord.Color.orange()
                    )
                )
        except Exception:
            pass

        log.info(
            "Guild owner berubah guild=%s old=%s new=%s verified=%s",
            after.id,
            before.owner_id,
            after.owner_id,
            verified
        )

    except Exception:
        log.exception(
            "on_guild_update owner verification error"
        )




@bot.event
async def on_guild_join(guild: discord.Guild):
    try:
        ensure_guild(guild.id)

        verified = await refresh_guild_owner_verification(
            guild,
            source="bot_invited",
            user_active=True
        )

        if REQUIRED_GUILD_ID and not verified:
            channel = guild.system_channel

            if channel is None:
                for candidate in guild.text_channels:
                    perms = candidate.permissions_for(guild.me)
                    if perms.view_channel and perms.send_messages:
                        channel = candidate
                        break

            if channel:
                embed = discord.Embed(
                    title="🔒 Hi Notifku • Verifikasi Pemilik Server Wajib",
                    description=(
                        required_join_text()
                        + "\n\n⛔ **Notifier server belum aktif.**"
                        + "\nPemilik Server wajib join Server Owner/Support, "
                        + "dan bot akan **otomatis memverifikasi** server ini tanpa approval manual."
                        + "\n\n📩 Semua command/pengaturan dilakukan melalui DM bot."
                    ),
                    color=discord.Color.orange()
                )

                await channel.send(
                    content=f"<@{guild.owner_id}>",
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(users=True)
                )

        try:
            owner_user = guild.owner or await guild.fetch_member(guild.owner_id)
            if verified:
                await owner_user.send(
                    "✅ **Hi Notifku berhasil masuk ke servermu.**\n"
                    "Status Pemilik Server: **TERVERIFIKASI**.\n"
                    "Gunakan `/menu` di DM untuk mengatur server."
                )
            else:
                await owner_user.send(
                    "🔒 **Verifikasi Pemilik Server Wajib**\n"
                    f"Server: **{guild.name}** (`{guild.id}`)\n\n"
                    + required_join_text()
                    + "\n\nSetelah join Server Owner/Support, gunakan `/start` hanya jika ingin refresh manual "
                    "di DM Hi Notifku. Notifier belum aktif sebelum verifikasi berhasil."
                )
        except Exception:
            pass

        for owner_id in primary_owner_ids():
            try:
                global_owner = bot.get_user(owner_id) or await bot.fetch_user(owner_id)
                await global_owner.send(
                    f"🆕 Server baru: **{guild.name}** (`{guild.id}`). "
                    "Buka `/owner` untuk menjalankan Wizard setup."
                )
            except Exception:
                pass

    except Exception:
        log.exception("on_guild_join error")


@bot.event
async def on_guild_remove(guild: discord.Guild):
    try:
        delete_guild_data(guild.id)
        with closing(db()) as conn:
            conn.execute(
                "DELETE FROM guild_owner_verification WHERE guild_id=?",
                (guild.id,)
            )
            conn.commit()
        log.info("Data guild %s dibersihkan.", guild.id)
    except Exception:
        log.exception("Guild cleanup gagal")


def validate_storage_paths_before_db():
    path = Path(DB_PATH).expanduser()
    parent = path.parent

    if path.is_absolute() and not parent.exists():
        if str(path).startswith("/data/"):
            raise RuntimeError(
                "DB_PATH memakai /data tetapi folder /data tidak tersedia. "
                "Pasang Railway Volume dengan mount path /data, atau ubah "
                "DB_PATH menjadi live_notifier.db."
            )
        parent.mkdir(parents=True, exist_ok=True)

    probe = parent / ".hi-notifku-db-write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        raise RuntimeError(
            f"Folder database tidak writable: {parent} "
            f"({type(exc).__name__}: {exc})"
        )


def startup_integrity_results() -> list[tuple[str, bool, str]]:
    results = []

    required_tables = {
        "guild_config", "guild_settings", "hosts", "premium_orders",
        "server_host_access_requests", "host_creation_requests",
        "guild_owner_verification", "user_verifications",
        "pending_notifications", "notification_dead_letter",
        "payment_callback_events", "payment_event_dead_letter",
        "premium_coupons", "premium_coupon_redemptions", "schema_meta",
    }

    try:
        with closing(db()) as conn:
            actual = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        missing = sorted(required_tables - actual)
        results.append((
            "Database schema",
            not missing,
            "OK" if not missing else "Missing: " + ", ".join(missing)
        ))
    except Exception as exc:
        results.append((
            "Database schema",
            False,
            f"{type(exc).__name__}: {exc}"
        ))

    try:
        path = Path(DB_PATH).expanduser()
        parent = path.parent
        probe = parent / ".startup-db-write"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        results.append(("DB writable", path.exists(), str(path)))
    except Exception as exc:
        results.append(("DB writable", False, str(exc)))

    try:
        qris = Path(QRIS_STORAGE_DIR)
        qris.mkdir(parents=True, exist_ok=True)
        probe = qris / ".startup-check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        results.append(("QRIS storage", True, str(qris)))
    except Exception as exc:
        results.append(("QRIS storage", False, str(exc)))

    try:
        folder = Path(AUTO_BACKUP_DIR)
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".startup-check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        results.append(("Backup storage", True, str(folder)))
    except Exception as exc:
        results.append(("Backup storage", False, str(exc)))

    if REQUIRED_GUILD_ID:
        results.append((
            "Owner/Support server",
            bot.get_guild(REQUIRED_GUILD_ID) is not None,
            str(REQUIRED_GUILD_ID)
        ))
    else:
        results.append((
            "Owner/Support server",
            False,
            "REQUIRED_GUILD_ID kosong"
        ))

    results.append((
        "Members Intent",
        bool(bot.intents.members),
        "ON" if bot.intents.members else "OFF"
    ))

    return results


async def notify_startup_integrity():
    results = startup_integrity_results()
    failed = [
        item for item in results
        if not item[1]
    ]

    lines = [
        f"{'✅' if ok else '❌'} **{name}** — {detail}"
        for name, ok, detail in results
    ]

    log.info(
        "Startup integrity: %s",
        " | ".join(
            f"{name}={'OK' if ok else 'FAIL'}"
            for name, ok, _ in results
        )
    )

    if not failed:
        return

    embed = discord.Embed(
        title="🚨 Startup Integrity Warning",
        description="\n".join(lines),
        color=discord.Color.red()
    )

    for owner_id in primary_owner_ids():
        try:
            user = bot.get_user(owner_id) or await bot.fetch_user(owner_id)
            await user.send(embed=embed)
        except Exception:
            pass




def register_pending_persistent_views() -> int:
    registered = 0

    with closing(db()) as conn:
        access_rows = conn.execute("""
            SELECT id, user_id, guild_id
            FROM server_host_access_requests
            WHERE status='pending'
        """).fetchall()
        host_rows = conn.execute("""
            SELECT id, guild_id, requester_id
            FROM host_creation_requests
            WHERE status='pending'
        """).fetchall()
        direct_rows = conn.execute("""
            SELECT id, host_id, user_id
            FROM host_access_requests
            WHERE status='pending'
        """).fetchall() if table_exists(conn, "host_access_requests") else []

    for row in access_rows:
        bot.add_view(ServerOwnerAccessRequestView(
            int(row["id"]), int(row["user_id"]), int(row["guild_id"])
        ))
        registered += 1

    for row in host_rows:
        bot.add_view(ServerOwnerHostCreationApprovalView(
            int(row["id"]), int(row["guild_id"]), int(row["requester_id"])
        ))
        registered += 1

    for row in direct_rows:
        host = get_host(int(row["host_id"]))
        if not host:
            continue
        bot.add_view(HostAccessRequestDecisionView(
            int(row["id"]), int(host["guild_id"])
        ))
        registered += 1

    return registered


def evaluate_safe_mode() -> tuple[bool, str]:
    try:
        required = {
            "guild_settings",
            "hosts",
            "user_verifications",
            "notification_history",
            "pending_notifications",
        }

        with closing(db()) as conn:
            actual = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

        missing = sorted(required - actual)
        if missing:
            return True, "Missing tables: " + ", ".join(missing)

        return False, ""

    except Exception as exc:
        return True, f"{type(exc).__name__}: {exc}"




@bot.event
async def on_ready():
    global http, SAFE_MODE, SAFE_MODE_REASON

    if http is None or http.closed:
        http = aiohttp.ClientSession()

    log.info(
        "Login sebagai %s (%s)",
        bot.user,
        bot.user.id
    )

    SAFE_MODE, SAFE_MODE_REASON = evaluate_safe_mode()

    if SAFE_MODE:
        log.error(
            "SAFE MODE aktif: %s",
            SAFE_MODE_REASON
        )
    try:
        bot.add_view(StartVerifyView())
        persistent_count = register_pending_persistent_views()
        log.info("Persistent request views registered: %s", persistent_count)
    except Exception:
        log.exception("Persistent view gagal didaftarkan")


    # Sync exactly four global slash commands: /ping, /start, /menu and /owner.
    try:
        synced = await bot.tree.sync()
        log.info(
            "Slash commands synced: %s (/ping + /start + /menu + /owner)",
            len(synced)
        )
    except Exception:
        log.exception("Slash command sync gagal")

    try:
        await notify_startup_integrity()
    except Exception:
        log.exception("Startup integrity check gagal")

    try:
        await start_payment_webhook_server()
    except Exception:
        log.exception("Payment webhook server gagal start")

    if not monitor_loop.is_running():
        monitor_loop.start()

    if not host_auto_recovery_loop.is_running():
        host_auto_recovery_loop.start()

    if not server_owner_health_alert_loop.is_running():
        server_owner_health_alert_loop.start()

    if not host_target_validation_loop.is_running():
        host_target_validation_loop.start()

    if not platform_outage_detection_loop.is_running():
        platform_outage_detection_loop.start()

    if not host_manager_expiry_warning_loop.is_running():
        host_manager_expiry_warning_loop.start()

    if not pending_request_recovery_loop.is_running():
        pending_request_recovery_loop.start()

    if not pending_request_reminder_loop.is_running():
        pending_request_reminder_loop.start()

    try:
        await recover_pending_request_views()
    except Exception:
        log.exception("Recovery pending request gagal")

    if not owner_verification_reconcile_loop.is_running():
        owner_verification_reconcile_loop.start()

    if not user_verification_reconcile_loop.is_running():
        user_verification_reconcile_loop.start()

    if not verification_retention_cleanup_loop.is_running():
        verification_retention_cleanup_loop.start()

    if not verification_expiry_warning_loop.is_running():
        verification_expiry_warning_loop.start()

    if not premium_expiry_loop.is_running():
        premium_expiry_loop.start()

    if not auto_backup_loop.is_running():
        auto_backup_loop.start()

    if not scheduled_system_backup_loop.is_running():
        scheduled_system_backup_loop.start()

    if not payment_reconciliation_loop.is_running():
        payment_reconciliation_loop.start()

    if not payment_event_retry_loop.is_running():
        payment_event_retry_loop.start()

    if not invoice_expiry_loop.is_running():
        invoice_expiry_loop.start()
    if not db_maintenance_loop.is_running():
        db_maintenance_loop.start()

    if not sqlite_wal_monitor_loop.is_running():
        sqlite_wal_monitor_loop.start()

    if not pending_notification_loop.is_running():
        pending_notification_loop.start()

    if not event_cleanup_loop.is_running():
        event_cleanup_loop.start()

    if not loop_lag_metrics.is_running():
        loop_lag_metrics.start()


# ============================================================
# MAIN
# ============================================================

async def main():
    global http

    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN belum diisi.")

    log.info("DB_PATH aktif: %s", DB_PATH)
    log.info("DB parent: %s", Path(DB_PATH).expanduser().parent)

    validate_storage_paths_before_db()
    migrate_database()

    try:
        await bot.start(DISCORD_TOKEN)
    finally:
        log.info("Graceful shutdown: menghentikan loop dan flush resource.")

        loops = [
            monitor_loop,
            host_auto_recovery_loop,
            server_owner_health_alert_loop,
            host_target_validation_loop,
            platform_outage_detection_loop,
            host_manager_expiry_warning_loop,
            pending_request_reminder_loop,
            pending_request_recovery_loop,
            owner_verification_reconcile_loop,
            user_verification_reconcile_loop,
            verification_expiry_warning_loop,
            verification_retention_cleanup_loop,
            premium_expiry_loop,
            auto_backup_loop,
            scheduled_system_backup_loop,
            payment_reconciliation_loop,
            payment_event_retry_loop,
            invoice_expiry_loop,
            db_maintenance_loop,
            sqlite_wal_monitor_loop,
            pending_notification_loop,
            event_cleanup_loop,
            loop_lag_metrics,
        ]

        for loop in loops:
            try:
                if loop.is_running():
                    loop.cancel()
            except Exception:
                pass

        try:
            with closing(db()) as conn:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                conn.commit()
        except Exception:
            log.exception("DB flush saat shutdown gagal")

        try:
            await stop_payment_webhook_server()
        except Exception:
            log.exception("Payment webhook shutdown gagal")

        if http and not http.closed:
            await http.close()


if __name__ == "__main__":
    asyncio.run(main())

