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
log = logging.getLogger("live-button-dashboard")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
http: Optional[aiohttp.ClientSession] = None


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(db()) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            youtube_channel_id INTEGER,
            tiktok_channel_id INTEGER,
            mention_role_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS hosts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            platform TEXT NOT NULL CHECK(platform IN ('youtube','tiktok')),
            target TEXT NOT NULL,
            display_name TEXT,
            extra TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            UNIQUE(guild_id, platform, target)
        );

        CREATE TABLE IF NOT EXISTS live_state (
            guild_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            target TEXT NOT NULL,
            is_live INTEGER NOT NULL DEFAULT 0,
            live_key TEXT,
            PRIMARY KEY(guild_id, platform, target)
        );
        """)
        # Migration for older DB
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(hosts)").fetchall()]
        if "enabled" not in cols:
            conn.execute("ALTER TABLE hosts ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
        conn.commit()


def ensure_guild(guild_id: int):
    with closing(db()) as conn:
        conn.execute("INSERT OR IGNORE INTO guild_config(guild_id) VALUES(?)", (guild_id,))
        conn.commit()


def get_config(guild_id: int):
    ensure_guild(guild_id)
    with closing(db()) as conn:
        return conn.execute(
            "SELECT * FROM guild_config WHERE guild_id=?",
            (guild_id,)
        ).fetchone()


def set_platform_channel(guild_id: int, platform: str, channel_id: int):
    ensure_guild(guild_id)
    column = "youtube_channel_id" if platform == "youtube" else "tiktok_channel_id"
    with closing(db()) as conn:
        conn.execute(
            f"UPDATE guild_config SET {column}=? WHERE guild_id=?",
            (channel_id, guild_id)
        )
        conn.commit()


def set_role(guild_id: int, role_id: Optional[int]):
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
            INSERT INTO hosts(guild_id, platform, target, display_name, extra, enabled)
            VALUES(?,?,?,?,?,1)
            ON CONFLICT(guild_id, platform, target)
            DO UPDATE SET
                display_name=excluded.display_name,
                extra=excluded.extra,
                enabled=1
        """, (guild_id, platform, target, display_name, extra))

        conn.execute("""
            INSERT OR IGNORE INTO live_state(guild_id, platform, target, is_live, live_key)
            VALUES(?,?,?,0,NULL)
        """, (guild_id, platform, target))
        conn.commit()


def update_host(host_id: int, target: str, display_name: Optional[str] = None):
    with closing(db()) as conn:
        row = conn.execute("SELECT * FROM hosts WHERE id=?", (host_id,)).fetchone()
        if not row:
            return False

        old_target = row["target"]
        conn.execute("""
            UPDATE hosts
            SET target=?, display_name=COALESCE(?, display_name), extra=NULL
            WHERE id=?
        """, (target, display_name, host_id))

        if old_target != target:
            conn.execute("""
                DELETE FROM live_state
                WHERE guild_id=? AND platform=? AND target=?
            """, (row["guild_id"], row["platform"], old_target))
            conn.execute("""
                INSERT OR REPLACE INTO live_state(guild_id, platform, target, is_live, live_key)
                VALUES(?,?,?,0,NULL)
            """, (row["guild_id"], row["platform"], target))
        conn.commit()
        return True


def delete_host(host_id: int):
    with closing(db()) as conn:
        row = conn.execute("SELECT * FROM hosts WHERE id=?", (host_id,)).fetchone()
        if not row:
            return
        conn.execute("DELETE FROM hosts WHERE id=?", (host_id,))
        conn.execute("""
            DELETE FROM live_state
            WHERE guild_id=? AND platform=? AND target=?
        """, (row["guild_id"], row["platform"], row["target"]))
        conn.commit()


def toggle_host(host_id: int):
    with closing(db()) as conn:
        row = conn.execute("SELECT * FROM hosts WHERE id=?", (host_id,)).fetchone()
        if not row:
            return None
        new_value = 0 if row["enabled"] else 1
        conn.execute("UPDATE hosts SET enabled=? WHERE id=?", (new_value, host_id))
        conn.commit()
        return bool(new_value)


def get_host(host_id: int):
    with closing(db()) as conn:
        return conn.execute("SELECT * FROM hosts WHERE id=?", (host_id,)).fetchone()


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
        """, (guild_id, platform, target)).fetchone()


def update_state(guild_id: int, platform: str, target: str, is_live: bool, live_key=None):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO live_state(guild_id, platform, target, is_live, live_key)
            VALUES(?,?,?,?,?)
            ON CONFLICT(guild_id, platform, target)
            DO UPDATE SET
                is_live=excluded.is_live,
                live_key=excluded.live_key
        """, (guild_id, platform, target, int(is_live), live_key))
        conn.commit()


# ============================================================
# PERMISSIONS
# ============================================================

def is_owner_or_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.id in OWNER_IDS:
        return True
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    perms = interaction.user.guild_permissions
    return perms.administrator or perms.manage_guild


async def require_owner_or_admin(interaction: discord.Interaction) -> bool:
    if is_owner_or_admin(interaction):
        return True
    if interaction.response.is_done():
        await interaction.followup.send(
            "❌ Menu ini hanya untuk **Owner/Admin**.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "❌ Menu ini hanya untuk **Owner/Admin**.",
            ephemeral=True
        )
    return False


# ============================================================
# API HELPERS
# ============================================================

async def yt_api(endpoint: str, params: dict):
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY belum diisi.")

    params = dict(params)
    params["key"] = YOUTUBE_API_KEY
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}"

    async with http.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as r:
        data = await r.json()
        if r.status != 200:
            raise RuntimeError(data.get("error", {}).get("message", f"HTTP {r.status}"))
        return data


async def resolve_youtube_channel(channel_id: str):
    data = await yt_api("channels", {
        "part": "snippet,contentDetails",
        "id": channel_id
    })
    items = data.get("items", [])
    if not items:
        raise ValueError("Channel ID YouTube tidak ditemukan.")

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
    except Exception:
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
    channel_id = (
        config["youtube_channel_id"]
        if platform == "youtube"
        else config["tiktok_channel_id"]
    )

    channel = await resolve_discord_channel(channel_id)
    if not channel:
        return False

    mention = None
    allowed_mentions = discord.AllowedMentions.none()
    if config["mention_role_id"]:
        mention = f"<@&{config['mention_role_id']}>"
        allowed_mentions = discord.AllowedMentions(roles=True)

    if platform == "youtube":
        embed = discord.Embed(
            title="🔴 YouTube LIVE STREAM",
            description=f"**{creator}** sedang live sekarang!",
            url=url,
            color=discord.Color.red()
        )
        embed.add_field(name="Judul Live", value=title or "Live sekarang", inline=False)
        embed.add_field(name="Tonton", value=f"[Buka YouTube Live]({url})", inline=False)
    else:
        embed = discord.Embed(
            title="🔴 TikTok LIVE",
            description=f"**@{creator}** sedang LIVE di TikTok!",
            url=url,
            color=discord.Color.from_rgb(255, 0, 80)
        )
        embed.add_field(name="Tonton", value=f"[Buka TikTok Live]({url})", inline=False)

    if thumbnail:
        embed.set_image(url=thumbnail)

    embed.set_footer(text="Live Notifier • Automatic")
    await channel.send(content=mention, embed=embed, allowed_mentions=allowed_mentions)
    return True


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
            conn.execute(
                "UPDATE hosts SET display_name=?, extra=? WHERE id=?",
                (name, uploads, row["id"])
            )
            conn.commit()

    playlist = await yt_api("playlistItems", {
        "part": "contentDetails",
        "playlistId": uploads,
        "maxResults": 8
    })

    ids = [
        x.get("contentDetails", {}).get("videoId")
        for x in playlist.get("items", [])
        if x.get("contentDetails", {}).get("videoId")
    ]

    if not ids:
        update_state(guild_id, "youtube", channel_id, False, None)
        return

    videos = await yt_api("videos", {
        "part": "snippet,liveStreamingDetails",
        "id": ",".join(ids)
    })

    live_video = next(
        (
            item for item in videos.get("items", [])
            if item.get("snippet", {}).get("liveBroadcastContent") == "live"
        ),
        None
    )

    previous = get_state(guild_id, "youtube", channel_id)

    if not live_video:
        update_state(guild_id, "youtube", channel_id, False, None)
        return

    vid = live_video["id"]
    snippet = live_video["snippet"]

    if not previous or not previous["is_live"] or previous["live_key"] != vid:
        thumbs = snippet.get("thumbnails", {})
        thumbnail = (
            thumbs.get("maxres", {})
            or thumbs.get("standard", {})
            or thumbs.get("high", {})
            or thumbs.get("medium", {})
        ).get("url")

        await send_live_notification(
            guild_id,
            "youtube",
            snippet.get("channelTitle", name),
            snippet.get("title", "Live sekarang"),
            f"https://www.youtube.com/watch?v={vid}",
            thumbnail
        )

    update_state(guild_id, "youtube", channel_id, True, vid)


async def check_tiktok_host(row):
    username = row["target"].lstrip("@")
    previous = get_state(row["guild_id"], "tiktok", username)

    client = TikTokLiveClient(unique_id=f"@{username}")
    is_live = await asyncio.wait_for(client.is_live(), timeout=25)

    if is_live:
        if not previous or not previous["is_live"]:
            await send_live_notification(
                row["guild_id"],
                "tiktok",
                username,
                "Live sekarang",
                f"https://www.tiktok.com/@{username}/live"
            )
        update_state(row["guild_id"], "tiktok", username, True, username)
    else:
        update_state(row["guild_id"], "tiktok", username, False, None)


@tasks.loop(seconds=CHECK_INTERVAL)
async def live_checker():
    for row in get_all_enabled_hosts():
        try:
            if row["platform"] == "youtube":
                await check_youtube_host(row)
            else:
                await check_tiktok_host(row)
        except Exception as e:
            log.warning("Check failed %s %s: %s", row["platform"], row["target"], e)
        await asyncio.sleep(1)


@live_checker.before_loop
async def before_checker():
    await bot.wait_until_ready()


# ============================================================
# BUTTON DASHBOARD
# ============================================================

def dashboard_embed(guild_id: int):
    cfg = get_config(guild_id)
    hosts = get_hosts(guild_id)

    yt_count = len([h for h in hosts if h["platform"] == "youtube"])
    tt_count = len([h for h in hosts if h["platform"] == "tiktok"])
    active_count = len([h for h in hosts if h["enabled"]])

    embed = discord.Embed(
        title="📡 Live Notification Dashboard",
        description=(
            "Kelola notifikasi **YouTube Live Stream** dan **TikTok LIVE** "
            "langsung menggunakan tombol di bawah."
        ),
        color=discord.Color.blurple()
    )
    embed.add_field(name="YouTube Hosts", value=str(yt_count), inline=True)
    embed.add_field(name="TikTok Hosts", value=str(tt_count), inline=True)
    embed.add_field(name="Running", value=str(active_count), inline=True)

    yt_ch = f"<#{cfg['youtube_channel_id']}>" if cfg["youtube_channel_id"] else "Belum diatur"
    tt_ch = f"<#{cfg['tiktok_channel_id']}>" if cfg["tiktok_channel_id"] else "Belum diatur"
    role = f"<@&{cfg['mention_role_id']}>" if cfg["mention_role_id"] else "Tidak ada"

    embed.add_field(name="📺 Channel YouTube", value=yt_ch, inline=False)
    embed.add_field(name="🎵 Channel TikTok", value=tt_ch, inline=False)
    embed.add_field(name="🔔 Mention Role", value=role, inline=False)
    embed.set_footer(text="Owner/Admin Panel • tombol hanya bekerja untuk admin")
    return embed


def host_embed(row):
    platform_label = "YouTube" if row["platform"] == "youtube" else "TikTok"
    icon = "📺" if row["platform"] == "youtube" else "🎵"
    status = "🟢 Running" if row["enabled"] else "🔴 Paused"

    embed = discord.Embed(
        title=f"{icon} {platform_label} Host",
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
    embed.set_footer(text=f"Host ID: {row['id']}")
    return embed


class AddHostModal(discord.ui.Modal):
    platform = discord.ui.TextInput(
        label="Platform",
        placeholder="tiktok atau youtube",
        max_length=10
    )
    target = discord.ui.TextInput(
        label="Username / YouTube Channel ID",
        placeholder="TikTok: username | YouTube: UCxxxxxxxx",
        max_length=100
    )

    def __init__(self):
        super().__init__(title="Tambah Host")

    async def on_submit(self, interaction: discord.Interaction):
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

        if platform == "tiktok":
            username = target.lstrip("@").rstrip("/")
            add_host(interaction.guild_id, "tiktok", username, f"@{username}", None)
            await interaction.response.send_message(
                f"✅ TikTok **@{username}** berhasil ditambahkan.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            name, uploads = await resolve_youtube_channel(target)
            add_host(interaction.guild_id, "youtube", target, name, uploads)
            await interaction.followup.send(
                f"✅ YouTube **{name}** berhasil ditambahkan.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)


class EditHostModal(discord.ui.Modal):
    target_input = discord.ui.TextInput(
        label="Target Baru",
        placeholder="Username TikTok / Channel ID YouTube",
        max_length=100
    )

    def __init__(self, host_id: int):
        super().__init__(title="Edit Host")
        self.host_id = host_id
        row = get_host(host_id)
        if row:
            self.target_input.default = row["target"]

    async def on_submit(self, interaction: discord.Interaction):
        if not await require_owner_or_admin(interaction):
            return

        row = get_host(self.host_id)
        if not row:
            await interaction.response.send_message("Host tidak ditemukan.", ephemeral=True)
            return

        new_target = self.target_input.value.strip()

        if row["platform"] == "tiktok":
            new_target = new_target.lstrip("@").rstrip("/")
            update_host(self.host_id, new_target, f"@{new_target}")
            await interaction.response.send_message(
                f"✅ Host diubah menjadi **@{new_target}**.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            name, uploads = await resolve_youtube_channel(new_target)
            update_host(self.host_id, new_target, name)
            with closing(db()) as conn:
                conn.execute(
                    "UPDATE hosts SET extra=? WHERE id=?",
                    (uploads, self.host_id)
                )
                conn.commit()
            await interaction.followup.send(
                f"✅ Host YouTube diubah menjadi **{name}**.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)


class ChannelSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

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
        set_platform_channel(interaction.guild_id, "youtube", channel.id)
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
        set_platform_channel(interaction.guild_id, "tiktok", channel.id)
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
        set_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ Mention role diatur ke {role.mention}.",
            ephemeral=True
        )


class HostCardView(discord.ui.View):
    def __init__(self, host_id: int):
        super().__init__(timeout=600)
        self.host_id = host_id

    @discord.ui.button(label="Edit", emoji="✏️", style=discord.ButtonStyle.secondary)
    async def edit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_owner_or_admin(interaction):
            return
        await interaction.response.send_modal(EditHostModal(self.host_id))

    @discord.ui.button(label="Notif", emoji="📣", style=discord.ButtonStyle.primary)
    async def notif_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_owner_or_admin(interaction):
            return
        row = get_host(self.host_id)
        cfg = get_config(interaction.guild_id)
        if not row:
            await interaction.response.send_message("Host tidak ditemukan.", ephemeral=True)
            return

        channel_id = (
            cfg["youtube_channel_id"]
            if row["platform"] == "youtube"
            else cfg["tiktok_channel_id"]
        )
        text = f"<#{channel_id}>" if channel_id else "Belum diatur"
        await interaction.response.send_message(
            f"📣 Channel notifikasi host ini: {text}",
            ephemeral=True
        )

    @discord.ui.button(label="Test", emoji="🖱️", style=discord.ButtonStyle.success)
    async def test_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_owner_or_admin(interaction):
            return

        row = get_host(self.host_id)
        if not row:
            await interaction.response.send_message("Host tidak ditemukan.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

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

        if ok:
            await interaction.followup.send("✅ Test notifikasi berhasil dikirim.", ephemeral=True)
        else:
            await interaction.followup.send(
                "❌ Channel notifikasi belum diatur / tidak dapat diakses.",
                ephemeral=True
            )

    @discord.ui.button(label="Pause", emoji="⏯️", style=discord.ButtonStyle.secondary)
    async def pause_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_owner_or_admin(interaction):
            return

        enabled = toggle_host(self.host_id)
        row = get_host(self.host_id)
        if row:
            try:
                await interaction.message.edit(embed=host_embed(row), view=HostCardView(self.host_id))
            except Exception:
                pass

        status = "Running" if enabled else "Paused"
        await interaction.response.send_message(
            f"✅ Status host: **{status}**.",
            ephemeral=True
        )

    @discord.ui.button(label="Hapus", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_owner_or_admin(interaction):
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


class DashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    @discord.ui.button(label="Tambah Host", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def add_host_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_owner_or_admin(interaction):
            return
        await interaction.response.send_modal(AddHostModal())

    @discord.ui.button(label="Daftar Host", emoji="📋", style=discord.ButtonStyle.primary, row=0)
    async def hosts_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
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
            f"📋 Menampilkan **{len(rows)} host** di bawah.",
            ephemeral=True
        )
        for row in rows:
            await interaction.channel.send(
                embed=host_embed(row),
                view=HostCardView(row["id"])
            )

    @discord.ui.button(label="Channel & Role", emoji="📣", style=discord.ButtonStyle.secondary, row=0)
    async def config_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_owner_or_admin(interaction):
            return

        await interaction.response.send_message(
            "Pilih channel dan role dari menu berikut:",
            view=ChannelSetupView(),
            ephemeral=True
        )

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_owner_or_admin(interaction):
            return
        await interaction.response.edit_message(
            embed=dashboard_embed(interaction.guild_id),
            view=DashboardView()
        )

    @discord.ui.button(label="Test YouTube", emoji="📺", style=discord.ButtonStyle.danger, row=1)
    async def test_youtube_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_owner_or_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        ok = await send_live_notification(
            interaction.guild_id,
            "youtube",
            "Test Creator",
            "Test YouTube Live Stream",
            "https://www.youtube.com/"
        )
        await interaction.followup.send(
            "✅ Test YouTube dikirim." if ok else "❌ Atur channel YouTube terlebih dahulu.",
            ephemeral=True
        )

    @discord.ui.button(label="Test TikTok", emoji="🎵", style=discord.ButtonStyle.danger, row=1)
    async def test_tiktok_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await require_owner_or_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        ok = await send_live_notification(
            interaction.guild_id,
            "tiktok",
            "testcreator",
            "Test TikTok LIVE",
            "https://www.tiktok.com/"
        )
        await interaction.followup.send(
            "✅ Test TikTok dikirim." if ok else "❌ Atur channel TikTok terlebih dahulu.",
            ephemeral=True
        )


# ============================================================
# ONLY MAIN SLASH COMMAND
# ============================================================

@bot.tree.command(
    name="live_panel",
    description="Buka dashboard tombol Live Notifier."
)
async def live_panel(interaction: discord.Interaction):
    if not await require_owner_or_admin(interaction):
        return

    await interaction.response.send_message(
        embed=dashboard_embed(interaction.guild_id),
        view=DashboardView(),
        ephemeral=False
    )


# Optional: compact private panel
@bot.tree.command(
    name="live_panel_private",
    description="Buka dashboard Live Notifier secara private."
)
async def live_panel_private(interaction: discord.Interaction):
    if not await require_owner_or_admin(interaction):
        return

    await interaction.response.send_message(
        embed=dashboard_embed(interaction.guild_id),
        view=DashboardView(),
        ephemeral=True
    )


# ============================================================
# EVENTS
# ============================================================

@bot.event
async def on_ready():
    global http

    if http is None or http.closed:
        http = aiohttp.ClientSession()

    log.info("Login sebagai %s (%s)", bot.user, bot.user.id)

    try:
        synced = await bot.tree.sync()
        log.info("Slash commands synced: %s", len(synced))
    except Exception:
        log.exception("Slash command sync gagal")

    if not live_checker.is_running():
        live_checker.start()


async def main():
    global http

    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN belum diisi.")

    init_db()

    try:
        await bot.start(DISCORD_TOKEN)
    finally:
        if http and not http.closed:
            await http.close()


if __name__ == "__main__":
    asyncio.run(main())
