# Plan: Setup Guide Presenly + Auto-Generate Approval Routes + Nested View

> **Status:** Plan — belum implementasi.
> **Tanggal:** 2026-09-08
> **Modul:** presenly (saat ini 19.0.14.2.0, target 19.0.15.0.0)

---

## 1. Kondisi Saat Ini (hasil riset terverifikasi)

### 1.1 Menu Settings attendance native
- `hr_attendance.menu_hr_attendance_settings` sudah `active=False` (id 159) sejak
  rollout FIX_APPROVAL_MENU_SETTINGS 19.0.14.1.0.
- Block `kiosk_mode_setting_container`, "Kiosk Settings", dan `overtime_settings`
  di `res.config.settings` sudah di-hide (`res_config_settings_kiosk_hidden_presenly`,
  `res_config_settings_overtime_hidden_presenly`).
- `hr_attendance.menu_hr_attendance_onboarding`, `menu_action_open_form` (Kiosk),
  `menu_hr_attendance_view_attendances_management`, `menu_hr_attendance_overtime_rulesets`
  juga `active=False`.
- **Gap:** tidak ada panduan/setup-checklist di UI yang menjelaskan urutan setup
  Company → Work Location → Schedule → Employee → Type → Approval Routes → siap submit.

### 1.2 Approval Routes saat ini
- Model `presenly.approval.rule` — 1 record = 1 langkah approval (Order otomatis
  10, 20, 30 ... dari rollout 19.0.14.2.0).
- Field unik scope: company + work_location + permission/leave type + overtime
  + sequence (`_check_unique_level_scope`).
- Approval resolver `_get_rules()` membaca rule aktif & complete per scope;
  submit diblokir bila route tidak lengkap (permission/timeoff/overtime).
- Tidak ada fitur generate massal.

**Data riil database `odoo`:**
| Kategori | Total | Punya route |
|---|---|---|
| Leave types aktif | **73** | 2 |
| Permission types | 3 | 1 (id 1) |
| Overtime route | 1 | 1 |
| Rule total | 5 | — |
| Rule tidak complete (41, 42) | 2 | — |

→ Hampir semua leave type & permission type BELUM punya route: submit akan
gagal ("No complete Presenly Approval Route is configured").

### 1.3 Opsi "nested" di Odoo 19
- List view Odoo 19 **tidak** memiliki atribut `nested` native (diverifikasi di
  `addons/web/static/src/views/list/list_arch_parser.js`).
- Yang tersedia secara native: **grouping** — `default_group_by` pada `<list>`
  menghasilkan hirarki ber-pill (grup + count), cocok sebagai "nested view".
- Field `permission_type_id` dan `leave_type_id` tidak bisa di-union dalam satu
  grup; dibutuhkan field stored `request_group` (Selection) untuk grouping bersih.

---

## 2. Objektif

1. **Setup/Panduan:** Sediakan halaman "Presenly Setup" berisi langkah-langkah
   bernomor + status kesiapan tiap langkah + tombol pintasan, sehingga admin tahu
   persis apa yang harus diisi sampai request Time Off / Permission / Overtime
   bisa disubmit.
2. **Auto-generate Approval Routes:** Wizard yang me-generate route untuk semua
   (atau pilihan) Leave Type, Permission Type, dan Overtime sekaligus, idempotent
   (skip yang sudah punya route), dengan approver default + urutan otomatis.
3. **Nested view:** List Approval Routes dikelompokkan berhirarki
   Company → Request Group (Overtime/Permission/Time Off) → Work Location,
   dengan badge count, agar tracking lebih mudah.

---

## 3. Desain Solusi

### Task 1 — Hapus/pertahankan menu Settings + Setup Guide UI

**1a. Verifikasi penghapusan menu Settings (tanpa perubahan kode)**
- Pastikan `MENU_SETTINGS inactive` di manifest/data tetap konsisten (sudah).
- Hanya ditambah test regression (lihat Task 5).

**1b. Model `presenly.setup.guide` — halaman setup/knowledge (TransientModel)**
File: `models/presenly_setup_guide.py` (+ registrasi `models/__init__.py`)

Field komputasi (per company di env):
- `company_count`, `company_ready` (ada company nontemplate)
- `location_total`, `location_ready` (jumlah work location, jumlah
  `presenly_is_geofence_ready=True`)
- `schedule_count` (jumlah `presenly.work.location.schedule` aktif)
- `employee_total`, `employee_with_location` (employee dgn work_location)
- `permission_type_total`, `permission_type_ready` (is_complete)
- `leave_type_total`, `leave_type_with_route` (aktif + punya route)
- `overtime_route_count` (rule is_overtime_route active & complete)
- `approval_rule_total`, `approval_rule_complete`
- `step_done` (integer 0–8), `all_ready` (boolean) — untuk progress bar

Method pintasan (open action yang sudah ada):
- `action_open_companies` → `base.action_res_company_form`
- `action_open_locations` → `hr.hr_work_location_action`
- `action_open_schedules` → `action_presenly_work_location_schedule`
- `action_open_permission_types` → `action_presenly_permission_type`
- `action_open_approval_routes` → `action_presenly_approval_rule`
- `action_open_generate_wizard` → wizard `presenly.approval.route.generate.wizard`

**1c. View + menu**
- `views/presenly_setup_guide_views.xml`: form transien berisi 8 langkah
  bernomor dengan status (✓ / ⚠ / jumlah), progress bar `web_progress`,
  dan tombol "Open" per langkah.
- `action_presenly_setup_guide` (act_window list) + menuitem
  `menu_presenly_setup_guide` = **"Presenly Setup"**, parent
  `hr_attendance.menu_hr_attendance_configuration`, sequence 10,
  groups `presenly.group_presenly_manager`.
- Daftarkan file di `__manifest__.py` data.

### Task 2 — Wizard Auto-Generate Approval Routes

**2a. Model `presenly.approval.route.generate.wizard` (+Line)**
File: `wizard/presenly_approval_route_generate.py` (+ `wizard/__init__.py`)

Wizard fields:
- `company_id` (required, default env company)
- `approver_type` (Selection sama dengan rule: user/employee_manager/
  unit_manager/hr/group, default `employee_manager`)
- `approver_user_id` (visible bila type=user)
- `approver_group_id` (visible bila type=group)
- `apply_to` (Selection):
  - `all` — semua leave type aktif + semua permission type aktif + overtime
  - `leave` — hanya leave type terpilih (`leave_type_ids` m2m)
  - `permission` — hanya permission type terpilih (`permission_type_ids` m2m)
  - `overtime` — hanya overtime
- `work_location_id` (opsional; kosong = company-default route)
- `start_sequence` (default 10), `sequence_step` (default 10)
- `skip_existing` (Boolean default True) — idempotent
- `line_ids` One2many `presenly.approval.route.generate.wizard.line`
- `line_count`, compute

Line model fields:
- `wizard_id`, `request_kind` (overtime/permission/leave), `request_name`
  (display), `request_id` (int), `work_location_id`, `sequence`, `status`
  (Selection: to_create / skipped_existing / invalid)

Method:
- `_candidates()` — cross product target request types (sesuai apply_to,
  dibatasi company) × (work location kosong) dengan langkah tunggal; baris
  `skipped_existing` bila scope sudah punya ≥1 route aktif-complete
  (atau bila `skip_existing`). Urutan otomatis 10, 20, ...
- `_onchange_*` → `_prepare_lines()` refresh preview.
- `action_generate()` — validasi input; create `presenly.approval.rule` untuk
  semua baris `to_create` (one rule per target scope, sequence sesuai urutan);
  return action Approval Routes (filter company).

**2b. View + menu**
- `wizard/presenly_approval_route_generate_views.xml`: form wizard + list line.
- `action_presenly_approval_route_generate` (act_window form) + menuitem
  **"Generate Approval Routes"** parent Configuration, sequence 15, manager.

### Task 3 — Nested view Approval Routes

**3a. Field `request_group` (stored) di `presenly.approval.rule`**
- `request_group = fields.Selection([('overtime','Overtime'),('permission','Permission'),('leave','Time Off'),('unassigned','Unassigned')], compute=..., store=True, index=True)`
- depends: `is_overtime_route`, `permission_type_id`, `leave_type_id`

**3b. List view grouping** (`views/presenly_approval_views.xml`)
- `<list ... default_group_by="company_id,request_group,work_location_id">`
- Tambahkan field `request_group` (dengan badge color), pertahankan sequence,
  request_type_display, scope_display, approver_display, is_complete.
- Filter yang ada (`overtime`, `complete`, `incomplete`, `active`, `archived`)
  tetap; tambah filter `permission`, `leave`, `unassigned`.
- Search: tambah `request_group` field + group_by `request_group`.

Catatan: grouping native memberi efek "nested" (pill Company > Request Group >
Work Location) dengan count; tidak perlu JS custom.

### Task 4 — README & docs
- Update `README.md`: tambah bagian "Presenly Setup (panduan langkah)" dan
  "Generate Approval Routes" + "Approval Routes nested view".

### Task 5 — Test & validasi
File test baru:
- `tests/test_setup_guide.py`:
  - setup guide action/menu terbuka utk manager, tidak untuk employee;
  - field komputasi konsisten (location_ready, leave_type_with_route, dsb).
- `tests/test_approval_route_generate.py`:
  - generate `apply_to=overtime` membuat 1 rule aktif-complete;
  - generate `apply_to=leave` (2 leave type) → 2 rule, sequence 10/20;
  - idempotent: generate ulang dgn `skip_existing=True` → tidak duplikat;
  - `skip_existing=False` → menambah rule kedua di scope sama (sequence +10);
  - user non-manager tidak bisa memanggil wizard action.
- `tests/test_approval_auto_order.py` existing tetap hijau.
- `tests/test_menu_settings.py` existing tetap hijau.

Prosedur:
- Bump versi `19.0.15.0.0`, kloning DB
  `odoo_presenly_setup_generate_test_YYYYMMDD_HHMMSS` + filestore,
  `-u presenly --test-tags /presenly`.
- Fingerprint data (attendance 5/42, evidence 58/1837, rule 5/92, journey 8/102,
  leave 7/139, overtime 3/11) identik — upgrade TIDAK mengubah data; generate
  hanya lewat wizard (uji di clone).
- Upgrade DB utama, restart, HTTP 200, kiosk 404, dokumen post-check
  `docs/SETUP_GUIDE_AUTO_GENERATE_NESTED_POSTCHECK_YYYYMMDD.txt`.

---

## 4. File yang Diubah

| File | Perubahan |
|---|---|
| `models/presenly_setup_guide.py` (baru) | Model transien setup guide + metode pintasan |
| `models/presenly_approval.py` | Field `request_group` stored di PresenlyApprovalRule |
| `models/__init__.py` | Import setup guide |
| `wizard/presenly_approval_route_generate.py` (baru) | Wizard generate |
| `wizard/__init__.py` | Import wizard |
| `views/presenly_setup_guide_views.xml` (baru) | Form + action + menuitem Setup |
| `wizard/presenly_approval_route_generate_views.xml` (baru) | Form wizard |
| `views/presenly_approval_views.xml` | grouping + request_group + filter |
| `views/presenly_menus.xml` | menuitem Presenly Setup & Generate |
| `__manifest__.py` | Bump 19.0.15.0.0 + data baru |
| `README.md` | Dokumentasi |
| `tests/*` | 2 file test baru |

---

## 5. Matriks Akses

| Fitur | Employee | Approver | HR Officer | Manager |
|---|---|---|---|---|
| Menu Presenly Setup | ❌ | ❌ | ❌ read-only opsional | ✅ (config) |
| Wizard Generate Routes | ❌ | ❌ | ❌ | ✅ |
| Approval Routes nested list | ❌ | ❌ | ❌ (action manager) | ✅ |
| Submit Permission/TimeOff/Overtime | ✅ (bila route ada) | — | — | — |

---

## 6. Keputusan yang Perlu Konfirmasi

1. **Approver default untuk generate**: `employee_manager` (recommended, sama
   dgn setup eksisting) — atau HR Officer / group / user tertentu?
2. **Lokasi override**: generate hanya route **company-default** (work_location
   kosong) dulu, atau juga salinan per work location? → recommended company-default
   (lokasi di-override manual via ready steps bila perlu).
3. **Ruang urutan**: pertahankan +10 (10, 20, 30) untuk konsistensi dgn order
   otomatis sebelumnya — setuju?
4. **Setup guide**: cukup form checklist + pintasan (tanpa onboarding framework
   Odoo) — setuju? (lebih ringan & tanpa JS baru)
5. **Nested**: grouping native (pill) sudah cukup, atau mau kanban per company
   dengan card per request type?