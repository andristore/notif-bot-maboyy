# Hi Notifku Complete V4 — DM Only

Versi ini menggabungkan seluruh 15 pengembangan ke satu kode agar tidak ada patch/fitur ganda.

## 15 Pengembangan

1. ✅ Channel & role per host
2. ✅ Custom pesan per host (`{creator}`, `{url}`, `{platform}`)
3. ✅ Panel host lengkap
4. ✅ Retry/error count/cooldown otomatis
5. ✅ Railway Volume / database persisten
6. ✅ Activity log + log channel
7. ✅ Free/Premium host limit
8. ✅ Owner management + blacklist/whitelist dari DM
9. ✅ Auto cleanup saat bot keluar server
10. ✅ Health/status panel
11. ✅ Notifikasi LIVE selesai
12. ✅ Interval pengecekan per host
13. ✅ Import host massal
14. ✅ Backup/restore JSON
15. ✅ Setup Wizard

## DM Only

Tidak ada slash command konfigurasi di server.

Global Owner cukup DM bot dengan pesan apa saja.

Jika bot dimention di server, bot hanya mengarahkan pengguna ke DM.

## Railway Variables

```env
DISCORD_TOKEN=...
OWNER_IDS=...
YOUTUBE_API_KEY=...

CHECK_INTERVAL=120
BASE_MONITOR_TICK=30

DB_PATH=/data/live_notifier.db

REQUIRED_GUILD_ID=...
REQUIRED_GUILD_INVITE=https://discord.gg/...

FREE_HOST_LIMIT=5
PREMIUM_HOST_LIMIT=100
```

## Railway Volume

Mount Volume ke:

```text
/data
```

dan gunakan:

```env
DB_PATH=/data/live_notifier.db
```

Ini sangat disarankan supaya database host/config tidak hilang.

## Discord Developer Portal

Bot → Privileged Gateway Intents:

- ✅ Server Members Intent

Bot permissions:

- View Channels
- Send Messages
- Embed Links
- Read Message History
- Mention @everyone, @here and All Roles jika memakai ping role

Tidak perlu Administrator.

## Free / Premium

Default:

- FREE: 5 host
- PREMIUM: 100 host

Bisa diubah melalui Railway:

```env
FREE_HOST_LIMIT=5
PREMIUM_HOST_LIMIT=100
```

Global Owner dapat mengubah plan setiap server melalui DM.

## Custom Pesan

Placeholder:

```text
{creator}
{url}
{platform}
```

Contoh:

```text
🔥 {creator} lagi LIVE di {platform}!
{url}
```

## Import Massal

Format:

```text
tiktok,username1
tiktok,username2
youtube,UCxxxxxxxxxxxxxxxx
```

## Backup / Restore

Tekan tombol **Backup** di panel server DM.

Bot mengirim file `.json`.

Untuk restore, kirim file JSON tersebut kembali ke DM bot.

## Activity Log

Atur **Log Channel** pada Default Notif.

Perubahan penting dapat dicatat ke channel tersebut.

## Setup Wizard

DM → pilih server → **Setup Wizard**

Urutan:

1. TikTok Channel
2. YouTube Channel
3. Mention Role
4. Tambah Host

## Upgrade

Replace:

- `bot.py`
- `requirements.txt`

Database lama akan dimigrasikan otomatis.

Setelah update GitHub, lakukan Redeploy Railway.

## Command

Hi Notifku hanya memiliki **1 slash command**:

```text
/menu
```

Fungsi `/menu`:
- hanya Global Owner yang dapat membuka panel lengkap,
- panel lengkap dikirim ke DM,
- pengaturan tidak dilakukan di channel server,
- semua akses tetap melalui panel DM.

