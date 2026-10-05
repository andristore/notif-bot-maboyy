# Hi Notifku v1.25.7

- Checkout terpadu, tahap pembayaran/aktivasi, Cek Status, Kuitansi dan Bantuan.
- Transaksi Terakhir membuka kembali panel milik requester pada server terkait.
- Kuitansi navy/cyan berupa embed + PNG, hanya untuk pembayaran terkonfirmasi;
  pengiriman otomatis memiliki receipt_sent_at agar tidak dikirim ulang normal.
- Perubahan metode dan detail bukti memakai guard status/deadline dalam transaksi.
- Verifikasi Join menyimpan hasil user dan memverifikasi server milik user,
  bukan hanya mengganti pesan tampilan. Public button dibatasi current owner.
- Onboarding channel/DM memiliki tombol join dan verifikasi persisten. Kegagalan
  kirim channel tidak mencegah percobaan DM owner. Trial menunggu verifikasi.
- Keanggotaan REST diperiksa ulang pada akses, tidak memakai cache lama.
  REQUIRED_GUILD_ID kosong tidak meloloskan owner/notifier. Bot harus berada
  di server support. Invite wajib berupa URL HTTPS Discord yang valid.
- Polling, pengiriman langsung, resend dan antrean notifikasi dilindungi gate.
  Antrean tertahan tanpa memakai retry bila membership belum terkonfirmasi.
- 53 tes offline dan preflight lolos. Pengujian Discord/Railway/payment nyata
  belum dijalankan. Gangguan API membership menahan akses sampai check berhasil.
- Tidak ada dependency/variable/schema baru; konfigurasi required server lama
  kini wajib benar. OAuth Add to Server sendiri dikendalikan Discord.

## Perubahan sebelumnya — v1.25.6

- Desain invoice navy/cyan, panel detail, hierarki tipografi dan total besar.
- Detail mencakup nomor invoice/order, server/pemesan Discord ID, paket,
  harga, kode unik, total, metode, nominal diterima, status serta tanggal WIB.
- Nilai tagihan mengikuti database, termasuk expected_amount; tidak menghitung
  ulang nominal pembayaran. Nomor invoice panjang dibungkus ke baris baru.
- Petunjuk pembayaran mengikuti status; invoice aktif tidak meminta bayar lagi.
- Font scalable dengan fallback bawaan Pillow. Tidak perlu file font/folder baru.
- Contoh invoice-preview.png berisi data fiktif. 32 tes offline serta preflight
  lolos. Pengiriman attachment pada Discord/Railway belum diuji langsung.
- Tidak ada dependency, variable, atau schema baru. Upload bot.py dan redeploy;
  klik Invoice lagi untuk mengunduh tampilan baru. Gambar lama tetap sama.

## Perubahan sebelumnya — v1.25.5

- Kartu LIVE menambahkan field Tautan berisi Tonton LIVE dan Profil TikTok
  agar pengguna punya jalur tambahan selain tombol di bawah pesan.
- 29 tes lolos, termasuk serialisasi View/Embed dengan discord.py asli:
  link style 5, URL profil kanonis, disabled=false, tanpa custom_id.
- Preflight lolos. Tidak ada variable atau migrasi schema baru.
- GitHub yang diperiksa sudah menggunakan v1.25.4. Payload tombol valid
  secara lokal; penyebab gagal klik di iPhone belum direproduksi.
- Uji Test LIVE baru setelah versi v1.25.5 berjalan. Pesan lama tidak diubah.

## Perubahan sebelumnya — v1.25.4

- Tombol Profil TikTok: target berupa username, tautan www/m, dan path
  terenkode dibentuk menjadi URL profil kanonis; tombol link aktif dan tidak
  memerlukan callback bot. Profil tetap tersedia jika source URL kosong.
- Nama akun: judul bawaan seperti @username LIVE diganti TikTok LIVE;
  author tidak menambahkan username lagi setelah display name.
- Teks LIVE bawaan yang mengulang nama disembunyikan, termasuk username
  berunderscore. Teks khusus dan judul siaran asli tetap dipertahankan.
- Gambar besar ditampilkan jika metadata TikTok menyediakan thumbnail;
  tanpa metadata, notifikasi tetap terkirim sebagai teks.
- 27 tes regresi offline dan preflight lolos. Klik Discord iPhone, koneksi
  TikTok, serta deployment Railway belum diuji langsung.
- Setelah deploy, cek versi v1.25.4 dan kirim Test LIVE baru. Pesan lama
  tidak diperbarui otomatis.

## Perubahan sebelumnya — v1.25.3

Versi ini membawa perubahan v1.25.2 dari ZIP ke repository dan memperbaiki
keandalan backup, pembayaran, dan pengiriman notifikasi.

- Backup sistem: import yang hilang diperbaiki; penyimpanan melalui file
  sementara; retensi ZIP/HNBAK mengikuti AUTO_BACKUP_KEEP.
- Restore konfigurasi: tanggal mulai/expiry/grace Premium dipertahankan;
  seluruh perubahan dilakukan dalam satu transaksi SQLite; host dinormalisasi;
  batas host aktif FREE tetap diterapkan. Host di luar snapshot tidak dihapus.
- Pembayaran: callback tidak menurunkan invoice aktif atau membuka kembali
  invoice ditolak/refund/expired; validasi ID/nominal; pemeriksaan transisi
  status; aktivasi otomatis menghormati AUTO_ACTIVATE_VERIFIED_PAYMENTS.
- Callback dengan event ID sama dan isi berbeda ditolak. Callback yang sudah
  tercatat sebelum crash tetapi belum selesai dapat dilanjutkan saat dikirim ulang.
- Notifikasi: kegagalan sebagian channel masuk antrean; retry melewati tujuan
  yang sudah tercatat sukses, termasuk webhook. Riwayat sukses untuk antrean
  aktif dipertahankan saat pembersihan data lama.
- Emergency Mode: event baru disimpan untuk dikirim nanti; antrean ditahan
  tanpa menghabiskan retry hingga mode jeda dinonaktifkan.
- TikTok: sesi LIVE tanpa room ID memiliki kunci sesi baru sehingga LIVE
  berikutnya tidak ditahan sebagai duplikat sesi sebelumnya.
- Schema 36: index tambahan untuk pencarian riwayat pengiriman per event.
- Pengujian regresi offline menggunakan fungsi produksi dan database sementara.

## Paket tanpa folder untuk upload dari iPhone

Semua file ZIP berada sejajar. Helper inti digabung ke bot.py; tidak ada
ketergantungan pada folder hi_notifku_core. Tes regresi bernama test_reliability.py
dan dijalankan dengan python test_reliability.py. Workflow GitHub tidak disertakan
karena memerlukan folder .github/workflows; jalankan pemeriksaan secara manual.
Versi aplikasi tetap 1.25.3 dan schema tetap 36.

## Batas pengujian

Pengujian offline mengganti batas jaringan/Discord dengan fake. Tidak ada
pengujian terhubung ke Discord, API media sosial, payment provider atau Railway.
Pengiriman Discord dan pencatatan SQLite bukan satu transaksi: crash setelah
Discord menerima pesan tetapi sebelum receipt tersimpan masih dapat menyebabkan
duplikat. Receipt antrean lama tanpa event key tidak dapat dipakai untuk melewati
channel yang sudah berhasil. Jangan menjalankan dua replica bot untuk satu DB.

## Tahap berikutnya

1. Tambahkan pengujian staging Discord/Railway dan pemantauan loop yang mati.
2. Pisahkan database, pembayaran, notifier platform dan panel Discord secara
   bertahap dari bot.py dengan pengujian perilaku sebelum/sesudah.
3. Jalankan operasi SQLite/backup berat di luar event loop dan gunakan worker
   terbatas untuk yt-dlp agar polling tidak mengganggu interaksi Discord.
4. Tambahkan pemulihan callback 'received' saat startup tanpa menunggu provider
   mengirim ulang, serta retry per destination untuk event tanpa receipt.
5. Tambahkan pengujian provider per platform, timeout dan pengukuran waktu
   deteksi LIVE sebelum mengubah interval polling.
