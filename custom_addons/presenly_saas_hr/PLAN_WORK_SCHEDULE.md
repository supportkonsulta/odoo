# Rencana: satu pegawai, satu mode jadwal

Status: **rencana**. Belum ada perubahan kode dari rencana ini.

---

## 1. Kenapa rancu

Satu hari bisa diisi dengan dua cara, dan keduanya bisa hidup berdampingan:

- **Mode mingguan** — hari → lokasi + shift. Toleransi datang dari shift.
- **Mode slot** — hari → satu atau beberapa slot, masing-masing lokasi + jam,
  dan sekarang toleransinya sendiri.

Yang membuatnya rancu bukan keberadaan dua mode itu, melainkan bahwa keduanya
**saling mengisi**. Di form slot ada baris ini:

```js
const fromColumns = segments.length === 0 && Boolean(existing.location_id) && Boolean(existing.shift_id);
```

Kalau sebuah hari hanya punya kolom, form slot **mengarang satu slot** dari shift
hari itu. Jadi membuka tab slot menampilkan data yang sebenarnya tidak pernah
diisi sebagai slot — dan menyimpannya akan mengubah mode hari itu tanpa ada yang
meminta.

Akibat lanjutannya sudah kita alami: penyimpanan slot menulis ulang hari-hari yang
tidak dikirim, dan jadwal mingguannya kosong. Itu bug, tetapi akarnya adalah
pencampuran dua mode ini.

---

## 2. Aturannya

> **Satu pegawai memakai satu mode. Mode yang lain tidak dipakai.**

| | Mode mingguan | Mode slot |
|---|---|---|
| Yang diisi | hari → lokasi + shift | hari → slot (lokasi + jam + toleransi) |
| Toleransi | dari shift | dari slot, dengan fallback shift lalu 0 |
| Tab slot | **tidak dipakai** | dipakai |
| Lokasi biasa pegawai | dari penempatan | dari penempatan |

Modenya **disimpulkan dari data**, bukan dipilih dan disimpan: kalau pegawai itu
punya slot pada hari mana pun, ia di mode slot. Kalau tidak, ia di mode mingguan.
Menyimpulkan lebih aman daripada menyimpan pilihan yang bisa berbeda dari isinya.

---

## 3. Yang berubah di aplikasi

### 3a. Berhenti mengarang slot

`fromColumns` dihapus. Hari yang hanya punya kolom tidak lagi muncul sebagai slot
— tab slot menampilkannya kosong, dan itu memang keadaannya.

### 3b. Tab yang tidak dipakai dinonaktifkan

Saat pegawai berada di mode mingguan, tab "Jadwal Per Slot" tidak bisa dibuka:
tombolnya mati, dengan keterangan singkat kenapa dan apa yang harus dilakukan
kalau memang ingin pindah mode. Berlaku sebaliknya.

Ini yang Anda minta, dan efeknya lebih besar daripada sekadar kerapian: tab yang
mati **tidak bisa** dipakai untuk mengubah mode secara tidak sengaja.

### 3c. Berpindah mode harus disengaja

Kalau pegawai yang sudah punya jadwal mingguan ingin memakai slot, mode mingguan
itu harus dikosongkan lebih dulu — atau disediakan tombol "Ubah ke mode slot" yang
menyatakan akibatnya: jadwal mingguan yang ada akan digantikan slot.

Saran: tombol dengan konfirmasi, bukan otomatis. Mengganti mode berarti
meninggalkan data lama, dan itu tidak boleh terjadi karena seseorang membuka tab.

### 3d. Validasi jam

Aturan yang sudah ada tetap: mulai ≠ selesai, tidak tumpang tindih, toleransi
0–120 menit. Rentang shift **tidak** lagi mengikat di mode slot — karena shift
tidak dipilih di sana. Yang mengikat hanya aturan slotnya sendiri.

---

## 4. Yang berubah di Odoo

### 4a. Tampilan mengikuti mode

Tab **Work Slots** menampilkan bagian yang relevan saja:

| Bagian | Mode mingguan | Mode slot |
|---|---|---|
| Usual Work Location | tampil | tampil |
| Work Location by Day | tampil: hari, lokasi, shift, jam dari shift | tampil sebagai wadah hari saja; kolom lokasi dan shift kosong |
| Slots | kosong | tampil: jam, lokasi, toleransi |

Kalau mode mingguan dipakai, bagian Slots tetap ditampilkan tetapi kosong — supaya
terlihat bahwa memang tidak ada slotnya, bukan tersembunyi.

### 4b. Toleransi slot ikut disinkronkan

API sudah mengirim `late_index` pada slot. Yang belum: cermin slot di Odoo belum
punya kolomnya, jadi nilainya berhenti di perjalanan.

- Kolom `late_index` di cermin slot, dan kolomnya di daftar Slot.
- Ikut dibandingkan seperti kolom lain, sehingga perbedaan terlihat.
- Tidak dikirim balik: toleransi dimiliki aplikasi, sama seperti kolom lain yang
  bertanda milik Presenly.

### 4c. Yang tidak berubah

- Penemuan pegawai, penempatan, dan lokasi biasa: tetap.
- Aturan hapus berskop, dan hanya baris `active` yang disimpan: tetap.
- Pengisian lokasi biasa dari pola kerja: tetap, dan tetap mati secara bawaan.

---

## 5. Data yang sudah ada

Tenant ini sekarang berada di keadaan **campur**: jadwal mingguan terisi untuk
semua pegawai, dan beberapa slot sudah ada. Karena modenya disimpulkan, keadaan itu
membaca sebagai "mode slot" untuk pegawai yang punya slot, dan "mode mingguan" untuk
yang tidak — padahal jadwal mingguannya juga terisi.

Langkah yang saya sarankan, berurutan dan bisa diperiksa hasilnya:

1. Jalankan perbaikan 3a lebih dulu (berhenti mengarang slot).
2. Periksa berapa pegawai yang berada di keadaan campur.
3. Untuk tiap pegawai yang campur, putuskan modenya — dan itu keputusan Anda,
   bukan sesuatu yang bisa saya simpulkan dari data: jadwal mingguan yang terisi
   bisa berarti mode mingguan yang dipakai, atau sisa sebelum pindah ke slot.
4. Sesudah diputuskan, baru aktifkan penonaktifan tab (3b).

Saya pisahkan langkah 4 dari langkah 1 dengan sengaja: kalau tabnya dinonaktifkan
sementara datanya masih campur, pegawai yang campur bisa terjebak di mode yang
salah dan tidak bisa memperbaikinya sendiri.

---

## 6. Pertanyaan yang perlu dijawab dulu

1. **Mode ditentukan per pegawai atau per hari?**
   Saran: per pegawai. Per hari berarti satu orang bisa punya Senin mode mingguan
   dan Selasa mode slot, dan itu mengembalikan kerancuan yang sama di tingkat lain.

2. **Apakah pegawai boleh berpindah mode?**
   Saran: boleh, lewat tombol dengan konfirmasi. Kalau tidak boleh, kesalahan saat
   pertama menyiapkan jadwal jadi permanen.

3. **Kalau pindah mode, data lama diapungkan atau dinonaktifkan?**
   Saran: dinonaktifkan (status `inactive`), tidak dihapus — sama seperti pola lama
   sekarang. Biayanya kecil dan bisa dilihat kembali.

4. **Toleransi di mode mingguan tetap dari shift, kan?**
   Saran: ya. Slot punya toleransi sendiri; hari yang tidak dipecah tidak punya
   tempat lain untuk menyimpannya.

---

## 7. Urutan pengerjaan

| # | Yang | Di mana | Kenapa urutannya di sini |
|---|---|---|---|
| 1 | Berhenti mengarang slot | frontend | memperbaiki kerancuannya lebih dulu, tanpa mengubah perilaku lain |
| 2 | Kolom toleransi di cermin Odoo + kolomnya di daftar Slot | Odoo | melengkapi sinkronisasi yang sudah setengah jalan |
| 3 | Tab yang tidak dipakai dinonaktifkan | frontend | setelah data campur dibereskan |
| 4 | Tombol pindah mode + konfirmasi | frontend | menyusul, setelah 3 terbukti tidak mengunci siapa pun |
| 5 | Tampilan Odoo mengikuti mode | Odoo | terakhir, setelah modenya pasti |

Langkah 1 dan 2 bisa dikerjakan sekarang. Langkah 3 menunggu keputusan bagian 5,
dan 4–5 menunggu jawaban bagian 6.
