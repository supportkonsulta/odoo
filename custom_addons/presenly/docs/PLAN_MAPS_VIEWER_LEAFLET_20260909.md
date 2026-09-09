# Plan: Attendance Map Widget dengan Leaflet + OpenStreetMap

> **Status:** Plan — belum implementasi.
> **Tanggal:** 2026-09-09
> **Modul:** presenly (saat ini 19.0.16.4.0, target 19.0.17.0.0)

---

## 1. Tujuan

Menampilkan koordinat absensi dalam bentuk **peta interaktif** yang memuat:
1. **UI batas radius** geofence (lingkaran `presenly_radius_meters`) —
   yang TIDAK bisa dicapai dengan Google Maps URL biasa.
2. **UI posisi kantor** (marker Work Location: `latitude/longitude`).
3. **UI posisi pegawai absen** (marker check-in/out: `in_latitude/in_longitude`
   atau `presenly.attendance.event`).

Pendekatan: **Leaflet.js + OpenStreetMap** (gratis, tanpa API key) — pola yang
sudah dipakai modul resmi `delivery` Odoo 19 (load via CDN unpkg
`leaflet@1.9.4`).

---

## 2. Riset (terverifikasi)

- `addons/delivery/static/src/js/location_selector/map/map.js` memakai Leaflet
  dengan:
  ```js
  loadJS('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js')
  loadCSS('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css')
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 })
  ```
- Modul presenly sudah punya pola widget field custom:
  `static/src/fields/attachment_image_viewer/` (JS OWL + XML template +
  asset di `web.assets_backend`).
- Data yang tersedia:
  - Work Location: `latitude`, `longitude`, `presenly_radius_meters`,
    `presenly_gps_accuracy_limit_meters`, `presenly_is_geofence_ready`.
  - Attendance: `in_latitude`, `in_longitude`, `out_latitude`,
    `out_longitude`, `presenly_work_location_id`, `presenly_check_in_distance`,
    `presenly_check_out_distance`, `presenly_attendance_mode`.
  - Event: `latitude`, `longitude`, `accuracy`, `distance_from_location`,
    `event_type`, `attendance_mode`.

---

## 3. Desain

### 3.1 Widget field Map — `presenly_map_viewer`
- Lokasi: `static/src/fields/map_viewer/map_viewer.js` + `map_viewer.xml` +
  `map_viewer.scss`.
- Tipe: **Char/readonly field widget** — menempel pada field kecil di form
  (mis. `in_latitude`) atau dipakai sebagai field sintetis per view.
- Render Leaflet map (`height: 360px`), OSM tile, default zoom 15, auto-fit
  bounds ke semua marker.
- Layer:
  - 🔵 Marker **check-in** (icon default blue) + popup: koordinat, jarak,
    akurasi, waktu.
  - 🟣 Marker **check-out** (icon purple/magenta) bila ada.
  - 🟢 Marker **kantor** (ikon `L.divIcon` dengan class `fa fa-building` /
    warna hijau) + popup: nama lokasi, radius, accuracy limit.
  - ⭕ **Circle radius** work location (`presenly_radius_meters`) dengan
    stroke hijau + fill transparan (opsi toggle via checkbox kecil di atas
    map: "Tampilkan radius geofence").
  - 📍 Bila GPS pegawai dan radius tersedia, tampilkan juga **garis hubung**
    (polyline putus-putus) kantor→pegawai + label jarak.

### 3.2 Tempat pemasangan
1. **Form Attendance** (`hr_attendance_view_form`): tambahkan row/group baru
   "Presenly Map" (`colspan=2`) berisi widget map pada field `in_latitude`
   (widget map, readonly) — render peta check-in/out + kantor. Ini dipasang
   di `views/hr_attendance_integration_views.xml` (inherit view presenly).
2. **Form Attendance Evidence** (`presenly.attendance.event`): tambah field
   dengan widget map pada `latitude` — render marker event + lokasi terkait.
3. **Form Work Location** (`hr.work.location`): tambah widget map pada
   `latitude` — render marker kantor + radius geofence sebagai preview
   konfigurasi (berguna saat mengatur geofence).

### 3.3 Cara kerja widget
- Gren `props` (dari field record):
  - `latitude`, `longitude` (field utama tempat widget menempel)
  - `map_locations` (Char JSON opsional, diisi view) — daftar
    `[{kind:'office'|'check_in'|'check_out', lat, lon, label, radius}]`
  - `map_readonly="1"`
- Simpel: gunakan satu field JSON (Char/Text) per model sebagai sumber data
  marker, dan widget cukup membaca `props.record.data[props.name]`.
  - Untuk menghindari JS kompleks, view menyediakan **Char JSON**
    `presenly_map_data` (compute di Python per model) yang berisi semua marker
    & radius. Widget map membaca JSON itu dan menggambar semuanya. Field dapat
    di-`invisible` di tempat lain.

Keputusan arsitektur: **field compute `presenly_map_data` (Char, JSON)** di:
- `hr.attendance` → marker check-in/out + work location + radius.
- `presenly.attendance.event` → marker event + work location + radius.
- `hr.work.location` → marker kantor + radius.

Widget `presenly_map_viewer` dipasang pada field tersebut (readonly,
`create=0`), memakai `JSON.parse(props.record.data[...])`. Ini meminimalkan
JS (tanpa dependensi eksternal di OWL props) dan tetap reaktif.

### 3.4 Asset
```python
'assets': {
    'web.assets_backend': [
        ...existing...,
        'presenly/static/src/fields/map_viewer/map_viewer.js',
        'presenly/static/src/fields/map_viewer/map_viewer.xml',
        'presenly/static/src/fields/map_viewer/map_viewer.scss',
        # Leaflet via CDN dimuat di dalam komponen (loadJS/loadCSS)
    ],
}
```

---

## 4. File yang Diubah

| File | Perubahan |
|---|---|
| `models/presenly_location.py` | field compute `presenly_map_data` (JSON marker kantor+radius) |
| `models/presenly_attendance.py` | field compute `presenly_map_data` (attendance: check-in/out + kantor) + di `presenly.attendance.event` |
| `static/src/fields/map_viewer/map_viewer.js` (baru) | Komponen OWL Leaflet + loadJS/loadCSS CDN |
| `static/src/fields/map_viewer/map_viewer.xml` (baru) | Template map + toggle radius + legenda |
| `static/src/fields/map_viewer/map_viewer.scss` (baru) | Styling |
| `views/hr_attendance_integration_views.xml` | Tambah field `presenly_map_data` + widget map di form attendance |
| `views/presenly_attendance_views.xml` | Widget map di form evidence |
| `views/presenly_location_views.xml` | Widget map di form work location |
| `__manifest__.py` | Bump 19.0.17.0.0 + assets |
| `README.md` | Dokumentasi |

---

## 5. Keamanan & Performa

- Marker data hanya dari field yang sudah ada (tidak ada endpoint baru).
- JSON di-compute dengan sudo sesuai hak akses record saat ini (tidak
  membocorkan data antar company — record rules tetap berlaku).
- Map dimuat lazy via `loadJS`; hanya render saat field terlihat.
- Tidak ada API key; tile OSM gratis dengan atribusi.

---

## 6. Test

1. `test_map_data_attendance`: `hr.attendance` yang punya work location +
   check-in/out menghasilkan `presenly_map_data` JSON berisi marker
   office/check_in/check_out + radius + jarak.
2. `test_map_data_wfa`: attendance mode WFA tanpa lokasi → JSON hanya berisi
   marker yang ada (tidak crash, koordinat absen tetap).
3. `test_map_data_location`: `hr.work.location` → JSON berisi marker kantor +
   radius.
4. `test_map_data_event`: `presenly.attendance.event` → JSON berisi marker
   event + kantor (bila ada).
5. Static: py compile, XML parse, git diff --check.
6. Regression: `/presenly` suite penuh (110+ tests).

---

## 7. Validasi & Rollout (pola sama)

1. Bump versi `19.0.17.0.0`.
2. Backup `odoo-before-map-viewer-YYYYMMDD_HHMMSS.dump`.
3. Clone DB + filestore → test di instance 8071 (server utama 8069 tetap jalan;
   polling `kill -0`, tanpa sleep buta).
4. Fingerprint data identik (map_data hanya field compute, tidak mengubah data).
5. Upgrade DB utama, restart, HTTP 200, kiosk 404.
6. Dokumen `docs/MAP_VIEWER_ROLLOUT_POSTCHECK_YYYYMMDD.txt`.

---

## 8. Keputusan yang Perlu Konfirmasi

1. **Jangkauan peta**: Attendance form + Evidence form + Work Location form
   (rekomendasi) — cukup, atau tambah halaman peta terpisah (map full-screen)?
2. **Sumber tile**: OpenStreetMap (default, gratis) — ada preferensi tile lain
   (mis. CARTO/Esri)?
3. **Toggle radius**: checkbox kecil "Tampilkan radius" di atas map —
   setuju, atau radius selalu tampil?
4. **Garis hubung kantor→pegawai** dengan label jarak — ditampilkan atau
   cukup marker + popup saja?