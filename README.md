# Discord Live Notifier — Button Dashboard

Versi ini dibuat agar pengelolaan bot dilakukan lewat **Discord buttons / select menu / modal**, bukan banyak slash command.

## Menu Utama

Jalankan:

`/live_panel`

Bot menampilkan dashboard dengan tombol:

- ➕ **Tambah Host**
- 📋 **Daftar Host**
- 📣 **Channel & Role**
- 🔄 **Refresh**
- 📺 **Test YouTube**
- 🎵 **Test TikTok**

Ada juga:

`/live_panel_private`

untuk membuka dashboard secara ephemeral/private.

## Tampilan Host

Setiap host ditampilkan sebagai kartu dengan informasi:

- Account Name
- Target
- Status Running / Paused

Tombol di setiap kartu:

- ✏️ **Edit**
- 📣 **Notif**
- 🖱️ **Test**
- ⏯️ **Pause / Resume**
- 🗑️ **Hapus**

Alurnya menyerupai dashboard NotifyMe, tetapi seluruh kontrol berada langsung di Discord.

## Owner/Admin Only

Semua button callback memeriksa permission ulang.

Yang boleh mengubah:

- User ID di `OWNER_IDS`
- Administrator
- Permission `Manage Server`

Member biasa tidak dapat menggunakan tombol walaupun pesan panel terlihat.

## Tambah Host

Tekan:

`➕ Tambah Host`

Modal akan muncul.

Isi:

Platform:
- `tiktok`
- `youtube`

Target:
- TikTok: username tanpa @
- YouTube: Channel ID diawali `UC...`

## Atur Channel

Tekan:

`📣 Channel & Role`

Akan muncul select menu:

- Channel YouTube Live
- Channel TikTok Live
- Role yang ingin di-mention

## Notifikasi

YouTube:
- Hanya dikirim saat stream benar-benar LIVE
- Scheduled stream tidak dikirim sebelum mulai

TikTok:
- Dikirim saat status berubah dari offline -> LIVE
- Tidak spam selama live yang sama

## Setup

Rename `.env.example` menjadi `.env`.

```env
DISCORD_TOKEN=TOKEN_BOT
OWNER_IDS=DISCORD_USER_ID_OWNER
YOUTUBE_API_KEY=YOUTUBE_API_KEY
CHECK_INTERVAL=120
```

Install:

```bash
pip install -r requirements.txt
python bot.py
```

## Catatan

TikTok menggunakan library `TikTokLive`, bukan endpoint publik resmi TikTok. Jika TikTok mengubah sistem internalnya, library mungkin perlu diperbarui.
