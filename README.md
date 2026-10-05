# Hi Notifku v1.25.7

Paket tanpa folder untuk upload dari iPhone. Semua helper yang dibutuhkan bot
sudah digabung ke `bot.py`. Tidak perlu membuat folder `hi_notifku_core`.

## File utama untuk GitHub

Ganti `bot.py` di root repository. Pastikan `requirements.txt` dan `Procfile`
tersedia. `.python-version` dan `.gitignore` disertakan; jika sulit memilih file
berawalan titik di iPhone, file utama tetap dapat di-upload terlebih dahulu.
Folder `hi_notifku_core` lama boleh dibiarkan; bot baru tidak menggunakannya.

## File tambahan

- Dokumentasi: `README.md`, `CHANGELOG.md`, `RAILWAY-MIGRATION.txt`.
- Template variabel: `railway-variables.env`; jangan isi secret asli di GitHub.
- Pengujian opsional: `test_reliability.py`, `preflight_test.py`,
  `smoke_test.py`, `self_test.py`.

Semua file tersebut berada sejajar. Workflow GitHub tidak disertakan dalam
paket ini karena membutuhkan folder `.github/workflows`.

## Update Railway

1. Simpan backup database lama sebelum update.
2. Ganti source di GitHub, lalu tunggu redeploy Railway.
3. Pertahankan Volume /data dan semua variable/secret lama.
4. Tidak ada variable baru; schema 36 menambah index riwayat pengiriman.
5. Cek `/ping`, `/owner` > System Health, Test LIVE dan backup.

Untuk deployment baru, pasang Volume /data dan isi secret di Railway.
Gunakan DB_PATH=/data/live_notifier.db, QRIS_STORAGE_DIR=/data/qris dan
AUTO_BACKUP_DIR=/data/backups.

## Pengujian

```bash
pip install "discord.py>=2.5,<3" aiohttp "Pillow>=11,<13"
python test_reliability.py
python preflight_test.py
```

Tes regresi memakai SQLite sementara dan fake untuk Discord/jaringan.
Pasang `requirements.txt` sebelum menjalankan `python smoke_test.py`.
Hasil offline tidak membuktikan koneksi Discord, Railway atau API platform.

## Pembayaran dan verifikasi v1.25.7

Panel checkout menampilkan total tepat, metode, status dan tahap pembayaran
terpisah dari aktivasi Premium. Tombol tersedia: Metode/Bayar, Saya Sudah Bayar,
Cek Status, Invoice, Kuitansi, Bantuan. Transaksi Terakhir di menu Premium
membuka kembali panel setelah view lama habis. Cek Status membaca database;
bukan permintaan baru ke provider. Kuitansi tersedia hanya untuk transaksi
terkonfirmasi, dapat diunduh dan dikirim otomatis dengan PNG saat aktivasi.

Metode pembayaran dan detail bukti tidak dapat diubah setelah invoice diproses
atau kedaluwarsa. Panel invoice dibatasi pada requester invoice tersebut.

Saat Add to Server, bot mengirim tombol Join Server Support dan Verifikasi Join
ke channel yang bisa ditulisi dan DM owner. Tombol verifikasi channel hanya
untuk pemilik server saat ini; pesan verifikasi persisten setelah restart.
Setup, checkout baru dan pengiriman notifier ditahan sampai server terverifikasi.
Keanggotaan diperiksa melalui API, bukan cache member / catatan aktif 30 hari.
Antrean notifikasi yang belum terverifikasi ditahan tanpa menghabiskan retry.
Trial baru dimulai setelah verifikasi berhasil, bukan saat undangan belum lolos.

Wajib isi REQUIRED_GUILD_ID dan REQUIRED_GUILD_INVITE di Railway. Invite harus
berupa HTTPS Discord invite yang menuju server tersebut. Bot harus sudah ada
pada server support dan bisa fetch member; konfigurasi kosong / akses API gagal
tidak meloloskan verifikasi. Global Owner tetap memiliki akses administrasi.
Discord mengendalikan halaman OAuth Add to Server; bot menahan penggunaan
setelah instalasi, bukan mencegah instalasi melalui halaman Discord.

53 tes offline dan preflight lolos. Discord/Railway dan pembayaran nyata belum
diuji. View pembayaran berlaku 15 menit; buka Transaksi Terakhir untuk panel baru.
Gambar invoice/kuitansi preview memakai data fiktif dan tidak perlu diupload.

## Invoice v1.25.6

Tombol Invoice menghasilkan PNG 1200x1560 dengan tema navy/cyan, rincian
pesanan/pemesan/server, status, harga, kode unik, total tepat, metode bayar,
nominal diterima, tanggal dibuat dan deadline WIB. Petunjuk mengikuti status
pesanan. Data diambil dari database; gambar tidak mengaktifkan pembayaran.
Font sistem digunakan jika tersedia, dengan fallback bawaan Pillow.
invoice-preview.png adalah contoh desain dengan data fiktif; tidak perlu
upload ke GitHub. Setelah deploy buka ulang tombol Invoice untuk gambar baru.
32 tes offline dan preflight lolos; pengiriman attachment Discord belum diuji.

## Notifikasi LIVE v1.25.5

Kartu TikTok LIVE menyediakan tombol Tonton LIVE/Profil TikTok, tautan
cadangan di field Tautan, dan link profil pada author. Uji pada pesan baru
setelah deploy. Link cadangan tidak memperbaiki pesan lama secara otomatis.
URL tombol sudah diuji dengan serialisasi discord.py asli tanpa koneksi
Discord; masalah klik pada iPhone belum direproduksi dan penyebabnya belum
terkonfirmasi. Jangan menganggap hasil offline membuktikan klik di perangkat.

## Perbaikan

URL tombol Profil TikTok, nama berulang pada kartu LIVE, dan teks bawaan
diperbaiki di v1.25.6. Kirim Test LIVE baru setelah deploy; pesan lama tetap.
32 tes offline dan preflight lolos; klik iPhone belum diuji langsung.


Backup penuh/retensi, restore tanggal Premium dalam satu transaksi, callback
pembayaran, retry channel yang gagal, antrean Emergency Mode, dan kunci sesi
LIVE TikTok. Detail dan rencana berikutnya tersedia di `CHANGELOG.md`.
