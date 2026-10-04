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

FREE_HOST_LIMIT=3
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
FREE_HOST_LIMIT=3
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

## Pengelolaan FREE / PREMIUM

Global Owner sekarang memiliki dua menu langsung di DM:

- 🆓 **Server Free**
- ⭐ **Server Premium**

Dari menu tersebut owner dapat memilih server lalu:

- mengubah FREE → PREMIUM,
- mengubah PREMIUM → FREE,
- membuka pengaturan lengkap server.

### Pengguna FREE

Pengguna menjalankan:

```text
/menu
```

Bot mengirim status server ke DM.

Jika server masih FREE, tersedia tombol:

```text
⭐ Upgrade Premium
```

Saat ditekan, permintaan upgrade otomatis dikirim ke `OWNER_IDS` utama beserta nama server, Server ID, owner server, dan user yang meminta.

Owner kemudian dapat membuka:

```text
DM Hi Notifku → Server Free → pilih server → Jadikan Premium
```

Setelah Premium diaktifkan, bot mencoba mengirim pemberitahuan ke owner server.

## Masa Aktif Premium

Saat Global Owner memilih **Jadikan Premium**, bot meminta jumlah hari.

Contoh:

```text
30
```

Artinya Premium aktif selama 30 hari.

Server Premium menampilkan tanggal:

```text
Premium Aktif Sampai
```

Global Owner juga mendapat tombol:

```text
⏳ Perpanjang Premium
```

Jika Premium diperpanjang sebelum habis, jumlah hari ditambahkan ke tanggal berakhir yang sudah ada.

### Reminder otomatis

Railway variable:

```env
PREMIUM_WARNING_DAYS=3
```

Dengan nilai `3`, bot akan mengirim DM ke owner server ketika masa Premium masuk 3 hari terakhir.

Saat Premium habis:

- server otomatis berubah ke FREE,
- host limit kembali mengikuti paket FREE,
- owner server mendapat DM bahwa Premium sudah berakhir.

Premium lama yang sudah ada sebelum fitur expiry dibuat dan belum memiliki tanggal expiry tidak akan tiba-tiba dinonaktifkan. Global Owner dapat membuka server Premium tersebut lalu menekan **Perpanjang Premium** untuk mulai menetapkan masa aktif.


## Warna Tombol / Submenu

- Abu-abu: submenu, navigasi, refresh, kembali, menu awal, pilihan netral.
- Hijau: tambah, upgrade Premium, perpanjang Premium.
- Merah: hapus dan blacklist.
- Biru: aksi membuka/kelola pilihan utama.

Menu `📊 Daftar Plan` menampilkan server FREE dan PREMIUM beserta ID dan expiry Premium.

## Command Baru

Bot sekarang memiliki 2 command:

```text
/menu
```

Untuk pengguna/server:
- melihat status FREE/PREMIUM,
- melihat pilihan paket Premium dan harga,
- memilih paket,
- mengirim permintaan Premium langsung ke DM owner.

```text
/owner
```

Khusus Global Owner:
- seluruh pengaturan bot,
- Server Free / Premium,
- aktifkan atau perpanjang Premium,
- host, channel, role, backup, health, dan lainnya.

## Harga Paket Premium

Atur melalui Railway:

```env
PREMIUM_PACKAGES=7:10000,30:25000,90:60000
```

Artinya:

- 7 hari = Rp10.000
- 30 hari = Rp25.000
- 90 hari = Rp60.000

Harga dapat diubah tanpa mengubah `bot.py`.

## Harga Premium dari Kelola Owner

Harga Premium tidak perlu diubah melalui Railway lagi.

Buka:

```text
/owner
→ Kelola Owner
→ Harga Premium
```

Tersedia:

- 💰 Tambah / Ubah Paket
- 🗑️ Hapus Paket
- 🔄 Refresh

Untuk mengubah harga paket yang sudah ada, masukkan jumlah hari yang sama dengan harga baru.

Contoh:

```text
Hari: 30
Harga: 30000
```

Paket 30 hari otomatis berubah menjadi Rp30.000.

Paket yang tampil di `/menu` pengguna selalu mengikuti harga terbaru dari database.

## /start — Verifikasi Server Support

Hi Notifku sekarang memiliki 3 command:

```text
/start
/menu
/owner
```

### `/start`

Dipakai pengguna untuk verifikasi bahwa akun Discord sudah bergabung ke:

**Server Resmi Owner/Support Hi Notifku**

Jika belum join:
- bot menampilkan tombol `Join Server Support`,
- setelah join tekan `Verifikasi Join`.

Jika sudah terverifikasi:
- pengguna dapat memakai `/menu`.

### `/menu`

Menu pengguna untuk:
- status FREE/PREMIUM,
- pilihan paket Premium,
- permintaan upgrade ke owner.

Pengguna non-owner wajib lolos `/start` terlebih dahulu.

### `/owner`

Khusus Global Owner untuk seluruh pengaturan bot.

Global Owner otomatis bypass verifikasi `/start`.


## Input Harga Premium

Pada `/owner` → `Kelola Owner` → `Harga Premium` → `Tambah / Ubah Paket`,
input dibuat menjadi dua bagian terpisah:

- `Hari`
- `Isi Harga (Rp)`

Contoh:

```text
Hari: 30
Isi Harga: 25000
```

Hasilnya menjadi paket 30 hari dengan harga Rp25.000.

## /ping — Status Bot

Gunakan:

```text
/ping
```

Untuk melihat:

- latency/ping Discord,
- uptime bot,
- status online,
- jumlah server,
- host aktif/total,
- jumlah server FREE/PREMIUM,
- ukuran database,
- storage terpakai/total/sisa,
- versi Python dan discord.py.

Respons `/ping` dibuat ephemeral sehingga hanya pengguna yang menjalankan command yang melihat hasilnya.


## /ping Ringkas

`/ping` sekarang hanya menampilkan ringkasan:

- status bot,
- ping,
- uptime,
- jumlah server,
- host aktif/total,
- storage terpakai/total.

## Upgrade Besar Sistem Premium & Monitoring

### Premium Order
Alur baru:

```text
User /menu
→ pilih paket
→ request Pending
→ owner /owner
→ Permintaan Premium
→ Tandai Dibayar
→ Aktifkan Premium
→ expiry otomatis
```

Request menyimpan:
- server,
- user peminta,
- jumlah hari,
- harga,
- status,
- waktu dibuat,
- owner yang memproses,
- tanggal aktivasi,
- tanggal expiry.

### Renewal
Server Premium tetap mendapat pilihan paket. Paket yang dipilih menjadi request perpanjangan. Saat diaktifkan owner, hari ditambahkan ke masa aktif yang masih tersisa.

### Reminder
Bot mengirim reminder ke DM owner server pada:
- H-7,
- H-3,
- H-1,
- saat Premium berakhir.

Setiap reminder disimpan agar tidak dikirim berulang.

### Dashboard Owner
`/owner` memiliki:
- Dashboard,
- Permintaan Premium,
- Riwayat Premium.

Dashboard berisi server FREE/PREMIUM, request pending/dibayar, Premium yang akan habis, host TikTok/YouTube, error host, dan storage.

### Auto Backup
Backup otomatis dibuat berkala.

Railway variables opsional:

```env
AUTO_BACKUP_HOURS=48
AUTO_BACKUP_KEEP=7
AUTO_BACKUP_DIR=/data/backups
MONITOR_CONCURRENCY=5
```

Gunakan `/data/backups` hanya jika Railway Volume sudah terpasang di `/data`.

### Monitor Concurrent
Host dicek secara concurrent dengan batas `MONITOR_CONCURRENCY`, sehingga jumlah host yang banyak tidak terlalu memperlambat satu siklus monitor.

### Status Host
Panel host menampilkan:
- Normal,
- Cooldown,
- Error,
- Paused,
- check terakhir,
- error count,
- error terakhir.

## Pembayaran Premium

Owner mengatur pembayaran dari:

```text
/owner
→ Kelola Owner
→ Pembayaran Premium
```

Data yang dapat diatur:
- Metode Pembayaran
- Atas Nama
- Nomor / Rekening
- Instruksi
- Link QRIS opsional

Alur user:

```text
/menu
→ pilih paket
→ lihat metode pembayaran
→ bayar
→ tekan Saya Sudah Bayar
→ kirim screenshot/bukti pembayaran ke DM bot
```

Bot menyimpan bukti ke request Premium dan meneruskannya ke DM owner.

Owner kemudian dapat membuka request dan memilih:

```text
Terima Bukti & Aktifkan
Tandai Dibayar
Aktifkan Premium
Tolak
```

Jika `Terima Bukti & Aktifkan` ditekan, Premium langsung aktif sesuai paket dan masa aktif otomatis dihitung.

## Kode Unik Nominal Pembayaran

Setiap Premium request mendapat kode unik 3 digit.

Contoh:

```text
Harga paket: Rp25.000
Kode unik: 137
Transfer tepat: Rp25.137
```

User wajib transfer sesuai nominal tepat tersebut.

Di `/owner` → `Permintaan Premium`, owner dapat melihat:

- harga paket,
- kode unik,
- nominal transfer yang seharusnya,
- nominal yang benar-benar masuk,
- status SESUAI / TIDAK SESUAI.

Owner menggunakan tombol:

```text
Cek Nominal Transfer
```

Kemudian memasukkan jumlah uang yang benar-benar masuk.

Jika sama:
```text
✅ SESUAI
```

Jika berbeda:
```text
❌ TIDAK SESUAI
```

Bot juga menampilkan selisih kurang atau lebih.

Premium tidak dapat diaktifkan melalui proses pembayaran sebelum nominal dinyatakan SESUAI.

## Multi Metode Pembayaran + QRIS Gambar

Owner dapat memiliki beberapa metode pembayaran sekaligus:

```text
/owner
→ Kelola Owner
→ Pembayaran Premium
```

Tersedia:

- `Tambah Rekening / E-Wallet`
- `Tambah QRIS`
- `Hapus Metode`
- `Refresh`

### QRIS

QRIS tidak memakai link manual lagi.

Alurnya:

```text
Tambah QRIS
→ isi nama QRIS / atas nama / instruksi
→ kirim gambar QRIS ke DM bot
→ bot menyimpan gambar tersebut
```

Saat user memilih QRIS, gambar QRIS tampil langsung di embed pembayaran.

### Rekening / E-Wallet

Owner dapat menambahkan beberapa metode, misalnya:

- DANA
- GoPay
- BCA
- BRI
- SeaBank

Setiap metode memiliki nama, atas nama, nomor/rekening, dan instruksi.

### Alur User

```text
/menu
→ pilih paket Premium
→ pilih metode pembayaran
→ lihat detail rekening / gambar QRIS
→ bayar sesuai nominal unik
→ Saya Sudah Bayar
→ kirim bukti pembayaran
```

Metode pembayaran yang dipilih user tersimpan di request Premium dan terlihat oleh owner.

## Mega Upgrade Operasional

Fitur lanjutan yang ditambahkan:

### Invoice Premium
- Invoice ID otomatis
- deadline pembayaran
- kode unik anti-bentrok
- harga dasar + kode unik + nominal transfer tepat
- invoice kedaluwarsa otomatis

Status transaksi:
- Menunggu Pembayaran
- Bukti Dikirim
- Nominal Tidak Sesuai
- Nominal Sesuai
- Dibayar
- Aktif
- Ditolak
- Invoice Kedaluwarsa
- Premium Selesai

### Anti Duplikasi Bukti
Bukti pembayaran disimpan dengan hash sehingga bukti yang sama tidak dapat digunakan pada request berbeda.

### Laporan Owner
`/owner` sekarang memiliki:
- pendapatan hari ini
- pendapatan 30 hari
- total pendapatan
- paket terlaris
- metode pembayaran terpopuler
- Export CSV transaksi

### Role Owner
- `super_owner`
- `payment_admin`
- `server_admin`
- `read_only`

### Security
- blacklist user
- anti-spam `/start` dan `/menu`
- invoice expiry
- audit activity

### Monitoring
- error alert setelah error berulang
- exponential cooldown/recovery
- health detail
- host error list

### Backup
- backup Railway Volume
- opsional kirim backup JSON ke channel Discord private dengan `BACKUP_CHANNEL_ID`

### Premium Grace Period
Setelah expiry, Premium dapat tetap aktif sementara selama grace period sebelum turun ke FREE.

### Pagination & Search
Server browser memiliki Previous / Next / Search agar tidak mentok limit 25 opsi Discord.

### Variable Opsional

```env
INVOICE_EXPIRE_MINUTES=60
PREMIUM_GRACE_HOURS=24
USER_RATE_LIMIT_SECONDS=5
ERROR_ALERT_THRESHOLD=5
BACKUP_CHANNEL_ID=0
```


### Restore Preview Aktif
File backup JSON yang dikirim ke DM owner tidak langsung diterapkan.
Bot menampilkan preview server, plan, dan jumlah host terlebih dahulu.
Owner harus menekan `Konfirmasi Restore`.

### Bukti Pembayaran Anti-Duplikat
Bot menghitung SHA-256 dari isi file bukti pembayaran.
Screenshot/file bukti yang sama tidak dapat digunakan pada request berbeda.

## /menu DM Only

`/menu` sekarang hanya membuka menu ketika dijalankan melalui DM Hi Notifku.

Jika `/menu` dijalankan di channel server, bot hanya memberikan petunjuk untuk membuka DM.

Alur pengguna:

```text
DM Hi Notifku
→ /start (verifikasi support server bila diperlukan)
→ /menu
→ pilih server milik pengguna
→ status FREE/PREMIUM
→ paket / perpanjangan
→ pembayaran
```

Di DM, bot menampilkan selector server yang dimiliki user dan yang sudah memasang Hi Notifku.

`/owner` tetap menjadi panel administrasi khusus Global Owner.

## Compact UI + Runtime Fix

Menu utama dibuat lebih ringkas:
- `/menu` DM: hanya pilih server + status inti
- `/owner`: tombol dipersingkat
- panel server: ringkasan plan/host/channel
- panel host: status inti tanpa field duplikat

Perbaikan runtime:
- `ServerOwnerView` dipulihkan karena sebelumnya direferensikan tetapi tidak ada.
- callback pilih server sekarang mempunyai target view yang valid.
- static scan memastikan tidak ada custom `*View` yang direferensikan tetapi belum didefinisikan.

## Production Stability Pack

Fitur yang ditambahkan:
- global slash-command error handler dengan Error ID
- global View error handler agar tombol error tidak diam/timeout
- defer untuk proses lambat
- persistent tombol verifikasi `/start`
- host search + pagination + pilih host detail
- edit, aktif/nonaktif, dan ganti gambar QRIS
- reference invoice `INV-YYYYMMDD-XXXXXX`
- invoice PNG yang bisa dikirim ke user
- payment log ke channel admin
- optional audit webhook
- database retention + VACUUM maintenance
- upload QRIS restart-safe melalui SQLite
- atomic Premium activation lock
- proteksi double activation dan tombol transaksi lama
- health detail untuk semua background loops
- flag setup selesai + onboarding server baru
- UI mobile yang lebih ringkas
- `self_test.py` untuk cek struktur bot sebelum deploy

### Variable baru

```env
PAYMENT_LOG_CHANNEL_ID=0
AUDIT_WEBHOOK_URL=
TRANSACTION_RETENTION_DAYS=365
ACTIVITY_RETENTION_DAYS=90
EXPIRED_INVOICE_RETENTION_DAYS=30
DB_MAINTENANCE_HOURS=24
```

### Test sebelum deploy

```bash
python self_test.py
```

Hasil yang diharapkan:

```text
SELF TEST: PASS
```

## QRIS Permanent Storage

QRIS sekarang tidak bergantung pada URL attachment Discord.

Alur:

```text
/owner
→ Owner
→ Pembayaran
→ QRIS / Ganti QRIS
→ kirim gambar ke DM bot
→ bot menyimpan file permanen
```

Path default QRIS berada di folder `qris` yang sejajar dengan database.

Untuk Railway Volume `/data`, gunakan:

```env
DB_PATH=/data/live_notifier.db
QRIS_STORAGE_DIR=/data/qris
```

Saat user memilih metode QRIS, bot membaca file lokal tersebut dan mengirimnya sebagai attachment Discord dengan `attachment://qris.png`/JPG/WEBP.

Format yang diterima:
- PNG
- JPG/JPEG
- WEBP
- maksimal 10 MB

Menghapus metode QRIS juga menghapus file QRIS terkait dari storage bot.

## Standard Navigation

Submenu sekarang memakai navigasi konsisten:

- `⬅️ Kembali` untuk kembali ke menu induk sebelumnya.
- `🏠 Menu Awal` untuk kembali langsung ke menu utama.

Navigasi ditambahkan pada submenu user, Premium, pembayaran, server, host, plan, wizard, laporan, health, owner, security, dan restore.

## Notifier Pro 2026.10

Upgrade notifier:
- multi-channel per host
- multi-role mention + optional `@everyone`
- Discord webhook mode
- custom embed title/footer/color
- timezone dan bahasa per host/server
- schedule hari aktif
- quiet hours + antrean notifikasi
- anti-duplicate event tahan restart
- notification history + resend
- delivery status + latency
- statistik notifikasi
- YouTube API-call dashboard
- TikTok LIVE fallback melalui yt-dlp
- YouTube LIVE fallback melalui yt-dlp
- retry/cooldown lama tetap dipertahankan
- auto-pause host setelah error berulang
- manual recheck
- preview template
- bulk pause/resume/reset error
- CSV export/import host
- clone notifier config antar-server
- permission diagnostics
- config snapshot + rollback
- maintenance mode tanpa mematikan monitor
- feature flags TikTok LIVE/Post/YouTube LIVE/Live End
- status broadcast maintenance
- optional AutoShardedBot
- notification send concurrency/rate-limit protection
- event-loop/runtime metrics
- changelog panel

Menu:
`/owner → pilih server → Notif`

Host:
`/owner → pilih server → Host → pilih host → Lanjutan`

Variable opsional:
```env
AUTO_PAUSE_ERRORS=20
NOTIFICATION_SEND_CONCURRENCY=3
NOTIFICATION_MIN_DELAY_MS=250
EVENT_RETENTION_DAYS=30
USE_AUTO_SHARDING=false
```

## Railway SQLite Path Fix

Jika memakai Railway Volume:

```env
DB_PATH=/data/live_notifier.db
QRIS_STORAGE_DIR=/data/qris
AUTO_BACKUP_DIR=/data/backups
```

Railway Volume harus benar-benar di-mount ke:

```text
/data
```

Versi ini membuat parent directory database secara otomatis dan memberikan pesan error yang lebih jelas bila mount/path tidak tersedia.

## Auto Backup ke DM Owner

Setiap auto backup sekarang:
1. disimpan ke `AUTO_BACKUP_DIR`;
2. dikirim ke DM seluruh **primary owner** yang terdaftar di `OWNER_IDS`;
3. opsional tetap dikirim ke `BACKUP_CHANNEL_ID` jika variable tersebut diisi.

Kegagalan DM satu owner tidak menggagalkan backup lokal maupun pengiriman ke owner lain.

Contoh:

```env
AUTO_BACKUP_HOURS=48
AUTO_BACKUP_KEEP=7
AUTO_BACKUP_DIR=/data/backups
BACKUP_CHANNEL_ID=0
```

`BACKUP_CHANNEL_ID=0` tidak mematikan DM backup owner. Nilai `0` hanya mematikan salinan tambahan ke channel Discord.

## Multi Social Host

Platform host yang didukung:

- YouTube — LIVE
- TikTok — LIVE + post terbaru
- Twitch — LIVE
- Kick — LIVE
- Instagram — konten terbaru (best-effort)
- Facebook — konten terbaru (best-effort)

Tambah dari:

```text
/owner
→ pilih server
→ Host
→ Tambah
```

Contoh bulk import:

```text
tiktok,username
youtube,UCxxxxxxxx
twitch,username
kick,username
instagram,username
facebook,https://www.facebook.com/namapage
```

Catatan:
Instagram dan Facebook sering membatasi extractor tanpa login/cookies. Karena itu monitoring kedua platform bersifat best-effort dan akun privat/halaman login-protected dapat gagal.

## Host Self-Service (Terpisah dari Owner)

Host Manager dan Global Owner menggunakan jalur akses yang berbeda.

### Global Owner
`/owner` tetap hanya dapat dibuka oleh `is_global_owner()`. Dari kartu host:
`Host → Manager Host` untuk menambah, memperbarui, melihat, atau mencabut manager.

### Host Manager
Host Manager **tidak** masuk ke `/owner` dan **tidak** dimasukkan ke tabel `bot_owners`.
Aksesnya hanya:
`DM bot → /menu → 🎙️ Host Saya`

Fitur Host Manager:
- status dan statistik 7 hari;
- edit pesan notifikasi;
- jadwal aktif + quiet hours + timezone;
- preview;
- test notification;
- manual recheck;
- pause/resume jika diberi izin;
- history 10 notifikasi terakhir;
- izin per host;
- akses sementara dengan masa kedaluwarsa;
- activity log terpisah.

Permission Host Manager:
`edit_messages,schedule,pause,recheck,history,test`

Host Manager tidak dapat:
- membuka `/owner`;
- mengelola premium, pembayaran, QRIS, revenue, backup, owner, atau server lain;
- menghapus host;
- assign/revoke manager;
- melihat host yang tidak ditugaskan kepadanya.

## FREE Server Owner — Tambah Host Sendiri

Server owner sekarang dapat menambah host tanpa membuka `/owner`:

```text
DM bot
→ /menu
→ pilih server milik sendiri
→ 📡 Kelola Host
→ ➕ Tambah Host
```

Berlaku untuk:
- FREE: maksimal sesuai `FREE_HOST_LIMIT` (default 3)
- PREMIUM: maksimal sesuai `PREMIUM_HOST_LIMIT` (default 100)

Saat menambah host, server owner mengisi:
- platform;
- username / Channel ID / URL;
- ID channel Discord tujuan;
- ID role mention opsional.

Server owner hanya dapat melihat, pause/resume, recheck, dan menghapus host pada server yang benar-benar dimilikinya. Fitur ini terpisah dari Global Owner `/owner` dan juga terpisah dari `🎙️ Host Saya` milik Host Manager.

## Host Manager — Lihat Semua Host Server

Host Manager membuka host yang ditugaskan terlebih dahulu, lalu memilih:

```text
DM bot
→ /menu
→ 🎙️ Host Saya
→ pilih host
→ 🌐 Semua Host Server
```

Aturan akses:
- host yang ditugaskan langsung kepada user dapat dikelola sesuai permission;
- host lain pada server yang sama dapat dilihat dalam mode **read-only**;
- read-only menampilkan platform, target, status, channel, role, last check, dan error;
- Host Manager tidak dapat mengedit, pause, test, recheck, menghapus, atau mengubah host lain;
- fitur ini tetap terpisah dari `/owner`.


### Isolasi per server

Menu `🌐 Semua Host Server` selalu menggunakan `guild_id` dari host yang sedang dibuka. Host dari server lain tidak digabung dan tidak ditampilkan pada daftar yang sama, meskipun user kebetulan menjadi Host Manager di beberapa server.

## /menu Host Manager v2

`/menu` sekarang role-aware dan Host Manager tetap terisolasi dari `/owner`.

Alur Host Manager:
```text
/menu
→ 🎙️ Host Saya
→ pilih server
→ pilih host
→ Quick Action
```

Peningkatan:
- pemilih server agar host antar-server tidak tercampur;
- pagination 25 host per halaman;
- pencarian host;
- favorit/pin host;
- Health: Healthy / Warning / Error / Paused;
- permission indicator;
- Notifikasi Terakhir;
- Error Center / Masalah Host;
- Aktivitas Saya;
- Bantuan Host dan onboarding;
- template preset + reset default;
- timezone alias WIB/WITA/WIT;
- konfirmasi Pause/Resume;
- request akses untuk host read-only;
- owner server dapat approve/deny request tanpa masuk `/owner`;
- warning error ke Host Manager;
- warning H-3 sebelum akses Host Manager berakhir.

Global Owner tetap menggunakan `/owner`. Host Manager tidak memperoleh akses ke payment, premium admin, backup, restore, revenue, owner management, atau konfigurasi global.

## User Belum Punya Host — Hubungi Pemilik Server

Jika `/menu` mendeteksi user bukan server owner dan belum memiliki Host Manager assignment, bot tidak lagi menyuruh user menghubungi "owner bot".

Alur baru:
```text
/menu
→ pilih server mutual
→ 👑 Pemilik Server
atau
→ 📨 Minta Akses Host
```

`👑 Pemilik Server` menampilkan mention owner Discord dari server yang dipilih. Mention dapat ditekan untuk membuka profilnya.

`📨 Minta Akses Host` mengirim DM ke pemilik server. Pemilik server kemudian dapat memilih salah satu host di servernya untuk diberikan kepada user sebagai Host Manager. Proses ini tidak memberikan akses `/owner` dan tidak melibatkan Global Owner bot.

### Request akses ketika server belum punya host

Tombol `📨 Minta Akses Host` tetap mengirim DM ke pemilik server walaupun server belum mempunyai host. Owner menerima pemberitahuan siapa yang meminta akses dan instruksi membuat host melalui:

`/menu → pilih server → Kelola Host → Tambah Host`

Jika server sudah mempunyai host, owner menerima selector host untuk langsung memberikan akses Host Manager.

### Auto backup tidak reset saat redeploy

Auto backup tetap mengikuti interval `AUTO_BACKUP_HOURS` (saat ini 48 jam / 2 hari), tetapi scheduler mengecek jatuh tempo setiap 1 jam. Timestamp backup terakhir disimpan melalui `backup_log` dan marker `.last_auto_backup` di `AUTO_BACKUP_DIR`.

Artinya:
- mengganti `bot.py`;
- push GitHub;
- restart Railway;
- redeploy Railway;

tidak otomatis mengirim backup baru ke DM owner jika belum 48 jam sejak backup otomatis terakhir.

Agar jadwal tetap bertahan melewati restart, gunakan Railway Volume pada `/data` dan `AUTO_BACKUP_DIR=/data/backups`.

## Pemisahan Akses: Global Owner Bot vs Pemilik Server

### 🛡️ Global Owner Bot
Masuk melalui `/owner`. Hak akses:
- semua server;
- premium admin dan transaksi;
- payment/QRIS/revenue;
- backup/restore;
- owner management;
- audit/health/maintenance;
- konfigurasi global.

### 👑 Pemilik Server
Masuk melalui `/menu → pilih server miliknya`. Hak akses hanya pada server tersebut:
- melihat plan server sendiri;
- request/upgrade Premium untuk server sendiri;
- tambah host sesuai limit plan;
- pause/resume/recheck/hapus host server sendiri;
- menerima request Host Manager;
- Setujui/Tolak request Host Manager;
- memilih host yang akan diberikan ke Host Manager.

Pemilik Server tidak dapat membuka `/owner`, melihat server lain, revenue, QRIS admin, backup/restore global, atau owner management.

### 🎙️ Host Manager
Masuk melalui `/menu → Host Saya` dan hanya dapat mengakses host/server yang diberikan sesuai permission.

### Approval Host Manager
Request dari user disimpan sebagai pending. DM Pemilik Server mempunyai tombol `✅ Setujui` dan `❌ Tolak`. Saat Setujui dipilih, Pemilik Server memilih host dari servernya sendiri. Jika belum ada host, request tetap pending sampai host dibuat.

## /menu — Dua Pilihan Peran

Root `/menu` sekarang hanya menampilkan dua jalur utama:

```text
📩 /menu
├── 👑 Pemilik Server
└── 🎙️ Host Manager
```

### 👑 Pemilik Server
Menampilkan server yang benar-benar dimiliki user. Dari sana user dapat mengatur plan dan host servernya sendiri sesuai batas plan.

### 🎙️ Host Manager
Menampilkan dashboard Host Manager dan hanya host/server yang diberikan kepadanya. Jika belum memiliki assignment, menu ini mengarahkan user ke flow permintaan akses kepada Pemilik Server.

`🛡️ Global Owner Bot` tidak ditampilkan sebagai pilihan `/menu`; akses global tetap hanya melalui `/owner`.

## Host Manager Tingkat Server + Approval Host Baru

Persetujuan Host Manager sekarang tidak membutuhkan host yang sudah ada.

Alur akses:
```text
User → Minta Akses Host Manager
→ DM Pemilik Server
→ ✅ Setujui
→ user mendapat akses Host Manager tingkat server
```

Setelah disetujui:
```text
/menu
→ 🎙️ Host Manager
→ pilih server
→ ➕ Ajukan Host
→ isi platform + target + channel + role
→ PENDING
→ DM Pemilik Server
→ ✅ Setujui Host / ❌ Tolak Host
```

Host baru tidak dimasukkan ke tabel `hosts` dan tidak dipantau notifier sebelum Pemilik Server menyetujuinya. Saat disetujui, limit FREE/PREMIUM diperiksa lagi, channel dan role divalidasi ulang, lalu host dibuat dan requester otomatis diberi assignment untuk host tersebut.

Ini menjaga pemisahan:
- Host Manager boleh mengajukan;
- Pemilik Server memegang keputusan;
- Global Owner Bot tidak diperlukan;
- `/owner` tetap terpisah.

## /menu Stability Batch 2

Peningkatan:
- semua tombol Menu Awal kembali ke `MenuRoleChoiceView`;
- Pemilik Server memiliki `📨 Request` center untuk request Host Manager dan host baru;
- request tetap dapat diproses dari `/menu` walaupun DM owner lama terlewat;
- dashboard server menampilkan jumlah request pending;
- Hapus Host memerlukan konfirmasi;
- approval/deny kritis memakai anti-double-click;
- Riwayat Request Host Manager menampilkan PENDING/APPROVED/DENIED/CANCELLED;
- jalur lama Host Manager tetap dibersihkan agar tidak duplikat.

## /menu Batch 3

- navigasi role diperbaiki: `Pemilik Server` masuk daftar server, `Menu Pengguna` Host Manager kembali ke pemilih peran;
- Request Center Pemilik Server mempunyai pagination 25 item per halaman;
- Pemilik Server dapat mencari request berdasarkan ID, user ID, platform, atau target;
- Host Manager dapat membatalkan request host miliknya selama masih `PENDING`;
- Host Manager mempunyai panel `🔐 Akses Saya` per server;
- semua aksi cancel/approve tetap diverifikasi ulang berdasarkan user, guild, dan status request.

## /owner — Global Owner Bot v2

`/owner` sepenuhnya dipisahkan dari `/menu`.

Akses:
- `🛡️ Global Owner Bot` → `/owner`
- `👑 Pemilik Server` → `/menu → Pemilik Server`
- `🎙️ Host Manager` → `/menu → Host Manager`

Pemilik Server dan Host Manager ditolak jika mencoba `/owner`.

Panel Global Owner sekarang memiliki `🔐 Security`:
- jumlah Primary/Global Owner;
- jumlah Pemilik Server dan Host Manager;
- request akses/host baru pending;
- blacklist count;
- audit request global read-only;
- status auto backup;
- pengelolaan Global Owner hanya untuk Primary Owner.

Global Owner dapat memantau request Host Manager/host baru secara global, tetapi approval request tersebut tetap wajib dilakukan oleh Pemilik Server.
