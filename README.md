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
AUTO_BACKUP_HOURS=12
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
