# Hi Notifku v1.24.0

File repository siap upload ke GitHub dan deploy ke Railway.

## Update repository lama
1. Ganti `bot.py` dengan versi terbaru.
2. Jika `requirements.txt`, `Procfile`, `.python-version`, `.gitignore`, atau `railway-variables.env` berubah pada update berikutnya, ikut ganti file tersebut.
3. Commit/push ke GitHub dan tunggu Railway redeploy.
4. Jangan hapus Railway Volume/database lama saat update biasa.

## Setup Railway baru
1. Upload seluruh isi folder ini ke repository GitHub.
2. Buat project/service Railway dari repository tersebut.
3. Tambahkan Railway Volume dan mount ke `/data`.
4. Buka `railway-variables.env`, lalu salin variable yang dibutuhkan ke Railway > Variables.
5. Isi secret utama sendiri: `DISCORD_TOKEN`, `OWNER_IDS`, `YOUTUBE_API_KEY`, dan variable server/support yang digunakan.
6. Pastikan `DB_PATH=/data/live_notifier.db`, `QRIS_STORAGE_DIR=/data/qris`, dan `AUTO_BACKUP_DIR=/data/backups` agar data berada di Volume.
7. Deploy dan cek `/ping`, `/owner`, lalu lakukan Test LIVE.

## Penting
- Jangan upload token/API key asli ke GitHub.
- `railway-variables.env` hanya template; isi secret dilakukan di Railway.
- Database SQLite tidak disertakan dalam repository/ZIP.
- Saat pindah Railway dan ingin mempertahankan data lama, restore/migrasikan backup database ke Volume baru sebelum penggunaan normal.
