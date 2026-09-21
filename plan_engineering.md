# Engineering Plan — Modul `ksg_engineering` (ERP KSG)

**AI Builder Execution Plan — Full Context & Build Guide**
**Sumber:** BRD-ENG-001 v1.0 & FSD-ENG-001 v1.0
**Platform:** Odoo 17/18 (Community/Enterprise)
**Nama Addon:** `ksg_engineering`
**Status:** Ready to Build
**Versi Plan:** 2.0

---

## 0. Konteks Lengkap Modul (BACA DULU SEBELUM APAPUN)

### 0.1 Apa Itu Modul Engineering Ini

Modul Engineering (`ksg_engineering`) adalah **custom addon Odoo** yang menangani seluruh proses bisnis Fungsi Engineering KSG, dimulai sejak **data Proyek & PO disetujui di modul Penjualan** sampai dengan **BAP/BAST disetujui** sebagai dasar validasi penagihan.

Modul ini **bukan aplikasi terpisah**. Ia adalah **lapisan Engineering di atas `ksg.sales.project`** — model project milik Penjualan di-`_inherit` (extend), bukan dibuat ulang.

### 0.2 Alur Bisnis End-to-End (Konteks untuk AI)

```
[Penjualan/ksg_sales]
   │  Project & PO disetujui (state=aktif)
   │  Data: klien, nilai kontrak, periode kontrak, dokumen teknis, checklist
   ▼
[Engineering/ksg_engineering]  ← MODUL INI
   │
   ├─ 1. Terima data project otomatis (via ORM, bukan input ulang)
   ├─ 2. Validasi prasyarat: Working Permit & Safety Induction
   ├─ 3. Susun WBS hierarkis (headline + sub-pekerjaan)
   ├─ 4. Bangun Master Schedule (periode, minggu, bobot, planned progress)
   ├─ 5. Pelaksana isi Daily Report + evidence
   ├─ 6. Pengawas konsolidasi → Supervisor approve/revisi
   ├─ 7. Agregasi otomatis: Daily → Weekly → Monthly
   ├─ 8. Hitung Planned vs Actual + Kurva-S + indikator keterlambatan
   └─ 9. Terbitkan BAP/BAST + digital signature
   │
   ▼
[Penagihan/ksg_billing]  ← downstream, read-only
   │  Konsumsi status "BAP/BAST Disetujui" via ORM
   ▼
[Invoice & Cost Control]  ← di luar scope Engineering
```

### 0.3 Prinsip Arsitektur (WAJIB Dipatuhi AI)

| Prinsip | Konsekuensi |
|---|---|
| **Native-first** | Pakai fitur Odoo bawaan (mail.thread, ir.attachment, res.groups, ir.rule, ir.cron, mail.activity) — jangan bikin ulang |
| **Single source of truth** | Data project HANYA dari `ksg.sales.project`. Engineering tidak duplikasi |
| **Extend, not recreate** | `_inherit ksg.sales.project`, bukan model baru |
| **Store computed lintas modul** | `store=True` untuk `bobot`, `bapbast_approved`, `kurva_s_*` |
| **Approval berhenti di Kepala Unit** | Tidak ada tahap Direktur/eksternal |
| **No core override** | Tidak boleh override modul core Odoo |
| **Audit trail otomatis** | Semua model custom inherit `mail.thread` |

### 0.4 Aktor & Role (Konteks RBAC)

| Aktor | Peran | Akses |
|---|---|---|
| Pelaksana | Buat & submit Daily Report | Project sesuai assignment |
| Engineer / Design Engineer | Kelola WBS & dokumen teknis | Project sesuai assignment |
| Pengawas | Konsolidasi Daily Report | Project sesuai assignment |
| Supervisor / Kepala Regu | Approve/revisi laporan | Multi-project |
| Kepala Unit / PM / Team Leader | Approve BAP/BAST | Tertinggi internal |
| Penjualan | Sumber data | Upstream |
| Operasional | Konsumen paralel | Tanpa dependency langsung |
| Penagihan | Konsumen downstream | **Read-only** BAP/BAST & progress |

### 0.5 Ruang Lingkup

**In-Scope:** WBS, Master Schedule, Daily/Weekly/Monthly Report, Approval berjenjang, Kurva-S, Assignment, BAP/BAST digital.

**Out-of-Scope:** Tender, Invoice, Cost Control, Manpower planning, BoQ, Presensi (SIDAC/Presenly), Master Tenaga Kerja, Accounting config.

---

## 1. Instruksi untuk AI Builder

Dokumen ini adalah **satu-satunya blueprint**. Jangan improvisasi.

**Aturan wajib:**
1. Ikuti **urutan Fase 1 → 12**. Jangan lompat.
2. **Cek dulu apakah `ksg_sales` sudah ada** (Section 2). Jika sudah ada → **sesuaikan** (Section 2.5). Jika belum → buat placeholder (Section 2.1).
3. Setiap file/model/field/method merujuk ke **FR-ID / BR-ID / RULE-ID**.
4. Gunakan **native Odoo**.
5. **Jangan buat model project baru.** Selalu `_inherit ksg.sales.project`.
6. Semua model custom **wajib** inherit `mail.thread` + `mail.activity.mixin`.
7. Computed field lintas modul **wajib** `store=True`.
8. Notifikasi default = `mail.activity`. Email hanya jika `notify_email_enabled = True`.
9. Approval berhenti di **Kepala Unit**.
10. Tidak override modul core.

---

## 2. Fase 1 — Deteksi & Penyesuaian Modul `ksg_sales`

### 2.1 Skenario A: `ksg_sales` BELUM Ada → Buat Placeholder

**Struktur:**
```
ksg_sales/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── ksg_sales_project.py
│   └── ksg_sales_document_checklist.py
├── views/
│   └── ksg_sales_project_views.xml
└── security/
    └── ir.model.access.csv
```

**`__manifest__.py`:**
```python
{
    'name': 'KSG Sales (Placeholder)',
    'version': '17.0.1.0.0',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/ksg_sales_project_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
```

**Model `ksg.sales.project` — field MINIMAL yang WAJIB ada:**

| Field | Tipe | Dipakai Engineering untuk |
|---|---|---|
| `name` | Char | Kode Project |
| `partner_id` | Many2one res.partner | Referensi klien |
| `kategori` | Char | Kategorisasi |
| `state` | Selection draft/aktif/selesai | Trigger serah terima FR-001 |
| `awal_kontrak` | Date | Validasi FR-004A, kalender FR-011 |
| `akhir_kontrak` | Date | Validasi FR-004A, kalender FR-011 |
| `nilai_kontrak_terkini` | Monetary | Basis bobot FR-005 |
| `currency_id` | Many2one res.currency | Format monetary |
| `checklist_dokumen_ids` | One2many ksg.sales.document.checklist | Prasyarat FR-002A |
| `document_ids` | Many2many ir.attachment | Referensi FR-002 |

**Model `ksg.sales.document.checklist`:**

| Field | Tipe | Catatan |
|---|---|---|
| `project_id` | Many2one ksg.sales.project | Parent |
| `nama_dokumen` | Char | Nama dokumen |
| `tipe` | Selection working_permit/safety_induction/lainnya | Jenis |
| `status` | Selection belum/terlampir | Kelengkapan |

> Beri komentar `# PLACEHOLDER: sinkronkan dengan ksg_sales riil saat tersedia`.

### 2.2 Skenario B: `ksg_sales` SUDAH Ada → Sesuaikan (WAJIB DIBACA)

Jika `ksg_sales` sudah terimplementasi (riil), **JANGAN buat placeholder**. Lakukan **penyesuaian** berikut:

#### 2.2.1 Langkah 1 — Audit Field `ksg.sales.project`

Buka model `ksg.sales.project` di modul riil. Verifikasi field berikut **ADA** dengan **nama & tipe sama persis**:

| Field yang Dibutuhkan Engineering | Jika Ada | Jika Tidak Ada |
|---|---|---|
| `name` (Kode Project) | Pakai | Minta ke tim Sales; jangan bikin sendiri |
| `partner_id` | Pakai | Minta ke tim Sales |
| `state` (draft/aktif/selesai) | Pakai; verifikasi nilai Selection | Sesuaikan mapping state di `_inherit` |
| `awal_kontrak` | Pakai | Minta ke tim Sales |
| `akhir_kontrak` | Pakai | Minta ke tim Sales |
| `nilai_kontrak_terkini` | Pakai | Minta ke tim Sales (wajib untuk bobot) |
| `currency_id` | Pakai | Fallback `res.company.currency_id` |
| `checklist_dokumen_ids` | Pakai | Minta ke tim Sales |
| `document_ids` | Pakai | Minta ke tim Sales |

**Aturan:**
- **JANGAN rename field Sales.** Jika nama berbeda (mis. `nilai_kontrak` bukan `nilai_kontrak_terkini`), **buat field related** di `_inherit`:
  ```python
  nilai_kontrak_terkini = fields.Monetary(
      related='nilai_kontrak', store=True, readonly=True)
  ```
- **JANGAN modifikasi file `ksg_sales`.** Semua penyesuaian di `ksg_engineering/models/ksg_sales_project_ext.py`.

#### 2.2.2 Langkah 2 — Audit Checklist `ksg.sales.document.checklist`

Verifikasi field `tipe` dan `status` ada. Jika nama/selection berbeda:

```python
# Di ksg_sales_project_ext.py — mapping ke field Sales riil
working_permit_ok = fields.Boolean(
    compute='_compute_document_prerequisites', store=True)

@api.depends('checklist_dokumen_ids.status', 'checklist_dokumen_ids.tipe')
def _compute_document_prerequisites(self):
    for rec in self:
        wp = rec.checklist_dokumen_ids.filtered(
            lambda c: c.tipe == 'working_permit')  # sesuaikan nilai riil
        si = rec.checklist_dokumen_ids.filtered(
            lambda c: c.tipe == 'safety_induction')
        rec.working_permit_ok = bool(wp) and all(
            c.status == 'terlampir' for c in wp)   # sesuaikan nilai riil
        rec.safety_induction_ok = bool(si) and all(
            c.status == 'terlampir' for c in si)
```

#### 2.2.3 Langkah 3 — Audit View Sales

Cari **external ID view form project** di `ksg_sales` (mis. `ksg_sales.view_ksg_sales_project_form`). Ini yang di-`inherit` oleh `ksg_engineering`:

```xml
<record id="view_ksg_sales_project_engineering_tab" model="ir.ui.view">
  <field name="inherit_id" ref="ksg_sales.view_ksg_sales_project_form"/>
  <!-- Sesuaikan ref sesuai external ID riil -->
</record>
```

Jika external ID berbeda, cari dengan:
```
SELECT * FROM ir_model_data WHERE module='ksg_sales' AND model='ir.ui.view';
```

#### 2.2.4 Langkah 4 — Audit Security Sales

Verifikasi:
- Apakah `ksg_sales` sudah punya group `ksg_sales.group_penagihan`?
  - Jika **ya** → `ksg_engineering` **reuse/extend** group tersebut untuk Penagihan.
  - Jika **tidak** → `ksg_engineering` bikin group sendiri `group_penagihan`.
- Apakah `ksg_sales` sudah punya record rule di `ksg.sales.project`?
  - Jika **ya** → **JANGAN timpa**. Tambah rule baru khusus Engineering, atau extend dengan `ir.rule` terpisah per group.
  - Jika **tidak** → buat rule baru di `ksg_engineering`.

#### 2.2.5 Langkah 5 — Audit Model Tambahan Sales

Jika `ksg_sales` punya model tambahan yang relevan (mis. `ksg.sales.worker`, `ksg.sales.contract`), **jangan duplikasi**. Untuk assignment personel Engineering:
- Gunakan `res.users` langsung (sesuai FSD FR-012).
- Jangan bikin `ksg.engineering.worker` — itu di luar scope.

#### 2.2.6 Langkah 6 — Mapping State Project

FSD menyebut: "Begitu status project = **Aktif** pada `ksg_sales`, seluruh data dasar otomatis terbaca."

Jika `ksg_sales` menggunakan nilai Selection berbeda (mis. `confirmed` bukan `aktif`), tambahkan **mapping** di `_inherit`:

```python
def _is_active_state(self):
    """Mapping state Sales riil ke konsep 'aktif' Engineering."""
    return self.state in ('aktif', 'confirmed', 'in_progress')
    # sesuaikan dengan nilai riil ksg_sales
```

Gunakan method ini di automated action / trigger notifikasi FR-001B.

#### 2.2.7 Langkah 7 — Verifikasi Addendum Kontrak

FSD FR-005: "perubahan akibat **adendum** pada modul Penjualan otomatis memicu recompute lintas modul."

Cek di `ksg_sales`:
- Apakah `nilai_kontrak_terkini` berubah saat adendum disetujui?
- Apakah ada model `ksg.sales.addendum`?

Jika ada, pastikan `@api.depends('project_id.nilai_kontrak_terkini')` di `ksg.engineering.wbs` menangkap perubahan. Jika field di-update via `write()` biasa, `@api.depends` sudah cukup. Jika via mekanisme khusus, tambahkan trigger manual.

#### 2.2.8 Langkah 8 — Dokumentasi Penyesuaian

Buat file `ksg_engineering/docs/sales_integration_notes.md` berisi:

```markdown
# Catatan Integrasi dengan ksg_sales

## Field Mapping
| Engineering Butuh | Field Sales Riil | Catatan |
|---|---|---|
| nilai_kontrak_terkini | nilai_kontrak_terkini | Sama |
| state 'aktif' | 'confirmed' | Mapping di _is_active_state() |

## External ID View
- Form project: ksg_sales.view_ksg_sales_project_form

## Group Reuse
- group_penagihan: reuse dari ksg_sales.group_penagihan

## Rule Existing
- rule_project_sales_own: JANGAN timpa; Engineering tambah rule terpisah

## Addendum
- Model: ksg.sales.addendum; trigger via write() pada project
```

### 2.3 Skenario C: `ksg_sales` Ada Sebagian (Partial)

Jika sebagian field ada, sebagian tidak:
1. **Field yang ada** → pakai langsung.
2. **Field yang tidak ada** → tambahkan via `_inherit` di `ksg_engineering` **DENGAN CATATAN** bahwa field ini idealnya milik Sales. Beri komentar:
   ```python
   # TODO: Pindahkan field ini ke ksg_sales saat modul Sales diupdate.
   # Sementara disediakan di sini agar Engineering bisa berjalan.
   ```
3. Laporkan ke tim Sales untuk sinkronisasi jangka panjang.

### 2.4 Skenario D: `ksg_sales` Akan Di-upgrade

Jika `ksg_sales` akan di-refactor di masa depan:
- Bangun `ksg_engineering` dengan **abstraction layer**: method `_get_sales_field()` yang membaca field Sales secara terpusat.
- Jika field Sales berubah, cukup ubah satu method, bukan seluruh modul.

```python
class KsgSalesProject(models.Model):
    _inherit = 'ksg.sales.project'

    def _get_nilai_kontrak(self):
        """Abstraction: baca nilai kontrak dari Sales.
        Ubah di sini jika nama field Sales berubah."""
        return self.nilai_kontrak_terkini
```

### 2.5 Ringkasan Keputusan: Placeholder vs Sesuaikan

| Kondisi `ksg_sales` | Aksi |
|---|---|
| Belum ada sama sekali | Buat placeholder (Section 2.1) |
| Sudah ada, field lengkap & nama sama | Langsung `_inherit`, tidak perlu mapping |
| Sudah ada, sebagian field beda nama | Buat related field di `_inherit` |
| Sudah ada, view/group berbeda | Sesuaikan external ID & reuse group |
| Akan di-upgrade | Buat abstraction layer |
| Partial | Pakai yang ada, tambah yang kurang dengan TODO |

### 2.6 Placeholder `ksg_billing`

Sama seperti Section 2.1, buat placeholder minimal:

```
ksg_billing/
├── __init__.py
├── __manifest__.py
└── models/
    ├── __init__.py
    └── ksg_billing_invoice.py
```

**Model `ksg.billing.invoice` (placeholder):**
- Field `project_id` (Many2one `ksg.sales.project`)
- Field `bapbast_approved` (related ke `project_id.bapbast_approved`, read-only)
- Tidak ada logic — hanya konsumsi ORM.

**Jika `ksg_billing` sudah ada:** sesuaikan dengan cara yang sama seperti `ksg_sales` — verifikasi field `bapbast_approved` bisa dibaca, jangan modifikasi modul Billing.

### 2.7 Fallback Native

| Dependency | Jika Tidak Ada | Fallback |
|---|---|---|
| `documents` | Tidak dilisensi | `ir.attachment` native |
| `sign` | Tidak dilisensi | Field `signature_image` (Binary) |
| `hr` | Tidak ada | `res.users` langsung |
| `ksg_operational` | Belum ada | Tanpa dependency (paralel) |

---

## 3. Fase 2 — Fondasi Addon `ksg_engineering`

### 3.1 Struktur Direktori Final

```
ksg_engineering/
├── __init__.py
├── __manifest__.py
├── README.md
├── docs/
│   ├── sales_integration_notes.md   # diisi saat audit ksg_sales
│   └── business_rules.md
├── models/
│   ├── __init__.py
│   ├── ksg_sales_project_ext.py
│   ├── res_users_ext.py
│   ├── ksg_engineering_wbs.py
│   ├── ksg_engineering_schedule_week.py
│   ├── ksg_engineering_daily_report.py
│   ├── ksg_engineering_daily_report_line.py
│   ├── ksg_engineering_report_consolidation.py
│   ├── ksg_engineering_weekly_report.py
│   ├── ksg_engineering_monthly_report.py
│   ├── ksg_engineering_assignment.py
│   └── ksg_engineering_bapbast.py
├── views/
│   ├── ksg_sales_project_views.xml
│   ├── ksg_engineering_wbs_views.xml
│   ├── ksg_engineering_daily_report_views.xml
│   ├── ksg_engineering_consolidation_views.xml
│   ├── ksg_engineering_weekly_monthly_views.xml
│   ├── ksg_engineering_assignment_views.xml
│   ├── ksg_engineering_bapbast_views.xml
│   ├── ksg_engineering_dashboard_views.xml
│   └── ksg_engineering_menus.xml
├── security/
│   ├── ksg_engineering_security.xml
│   └── ir.model.access.csv
├── data/
│   ├── ir_cron_data.xml
│   ├── mail_activity_type_data.xml
│   ├── mail_template_data.xml
│   └── sequence_data.xml
├── report/
│   ├── bapbast_report.xml
│   └── bapbast_report_template.xml
├── static/
│   └── src/
│       ├── js/kurva_s_widget.js
│       └── scss/ksg_engineering.scss
└── tests/
    ├── __init__.py
    ├── test_wbs.py
    ├── test_daily_report.py
    ├── test_approval.py
    └── test_bapbast.py
```

### 3.2 `__manifest__.py`

```python
{
    'name': 'KSG Engineering',
    'version': '17.0.1.0.0',
    'category': 'Operations/Project',
    'summary': 'Modul Engineering ERP KSG',
    'description': """
Modul Engineering ERP KSG.
Menangani WBS, Master Schedule, Daily/Weekly/Monthly Report,
Approval berjenjang, Kurva-S, dan BAP/BAST digital.
Depends ke ksg_sales (single source of truth data project).
    """,
    'author': 'Tim ERP KSG',
    'depends': ['base', 'mail', 'ksg_sales'],
    'data': [
        'security/ksg_engineering_security.xml',
        'security/ir.model.access.csv',
        'data/mail_activity_type_data.xml',
        'data/ir_cron_data.xml',
        'data/sequence_data.xml',
        'views/ksg_sales_project_views.xml',
        'views/ksg_engineering_wbs_views.xml',
        'views/ksg_engineering_daily_report_views.xml',
        'views/ksg_engineering_consolidation_views.xml',
        'views/ksg_engineering_weekly_monthly_views.xml',
        'views/ksg_engineering_assignment_views.xml',
        'views/ksg_engineering_bapbast_views.xml',
        'views/ksg_engineering_dashboard_views.xml',
        'views/ksg_engineering_menus.xml',
        'report/bapbast_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ksg_engineering/static/src/js/kurva_s_widget.js',
            'ksg_engineering/static/src/scss/ksg_engineering.scss',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
```

---

## 4. Fase 3 — Security (Groups + Rules + ACL)

### 4.1 Groups (`security/ksg_engineering_security.xml`)

| Group ID | Nama | Implied | Catatan |
|---|---|---|---|
| `group_pelaksana` | Engineering / Pelaksana | — | |
| `group_engineer` | Engineering / Engineer | — | |
| `group_pengawas` | Engineering / Pengawas | — | |
| `group_supervisor` | Engineering / Supervisor | — | |
| `group_kepala_unit` | Engineering / Kepala Unit | `group_supervisor` | |
| `group_penagihan` | Engineering / Penagihan (Read-only) | — | **Reuse dari `ksg_sales` jika ada** |

**Jika `ksg_sales` sudah punya group Penagihan:**
```xml
<record id="group_penagihan" model="res.groups">
    <field name="name">Engineering / Penagihan (Read-only)</field>
    <field name="implied_ids" eval="[(4, ref('ksg_sales.group_penagihan'))]"/>
</record>
```

### 4.2 Record Rules

| Rule ID | Model | Domain | Catatan |
|---|---|---|---|
| `rule_project_by_assignment` | `ksg.sales.project` | `[('id', 'in', user.assigned_project_ids.ids)]` | Jangan timpa rule Sales |
| `rule_wbs_by_assignment` | `ksg.engineering.wbs` | `[('project_id', 'in', user.assigned_project_ids.ids)]` | |
| `rule_daily_by_assignment` | `ksg.engineering.daily.report` | idem | |
| `rule_consolidation_by_assignment` | `ksg.engineering.report.consolidation` | idem | |
| `rule_bapbast_by_assignment` | `ksg.engineering.bapbast` | idem | |

**Group yang dikecualikan:** `group_penagihan` (read-only global), `base.group_system` (admin).

**Jika `ksg_sales` sudah punya rule di `ksg.sales.project`:**
- Jangan timpa. Buat rule **tambahan** dengan domain Engineering-specific.
- Jika rule Sales sudah membatasi akses dengan cara lain (mis. `user_id`), pastikan rule Engineering **tidak konflik**. Rule Odoo bersifat **AND** — jika Sales sudah membatasi, Engineering tinggal menambah.

### 4.3 `ir.model.access.csv` (inti)

| Model | Pelaksana | Engineer | Pengawas | Supervisor | Kepala Unit | Penagihan |
|---|---|---|---|---|---|---|
| `ksg.engineering.wbs` | R/W/C | R/W/C/U | R/W/C/U | R/W/C/U | R/W/C/U | — |
| `ksg.engineering.daily.report` | R/W/C | R/W/C/U | R/W/C/U | R | R | — |
| `ksg.engineering.daily.report.line` | R/W/C | R/W/C/U | R/W/C/U | R | R | — |
| `ksg.engineering.report.consolidation` | R | R | R/W/C/U | R/W | R/W | — |
| `ksg.engineering.weekly.report` | R | R | R | R | R/W | R |
| `ksg.engineering.monthly.report` | R | R | R | R | R/W | R |
| `ksg.engineering.bapbast` | R | R | R | R/W | R/W/C/U | R |
| `ksg.engineering.assignment` | R | R | R | R/W/C/U | R/W/C/U | — |
| `ksg.engineering.schedule.week` | R | R/W/C | R/W/C | R/W/C | R/W/C/U | R |

Keterangan: R=read, W=write, C=create, U=unlink.

---

## 5. Fase 4 — Models (Urutan Build)

### 5.1 `ksg.sales.project` Extended

**File:** `models/ksg_sales_project_ext.py`
**Inherit:** `ksg.sales.project`

**Field:**

| Field | Tipe | FR Ref | Keterangan |
|---|---|---|---|
| `working_permit_ok` | Boolean (computed, store) | FR-002A | True jika semua checklist `working_permit` = `terlampir` |
| `safety_induction_ok` | Boolean (computed, store) | FR-002A | True jika semua checklist `safety_induction` = `terlampir` |
| `checklist_status_ids` | One2many (related) | FR-002B | Status per item |
| `schedule_week_ids` | One2many `ksg.engineering.schedule.week` | FR-011 | Kalender minggu |
| `wbs_ids` | One2many `ksg.engineering.wbs` | FR-003 | WBS |
| `assignment_ids` | One2many `ksg.engineering.assignment` | FR-012 | Assignment |
| `bapbast_ids` | One2many `ksg.engineering.bapbast` | FR-014 | BAP/BAST |
| `bapbast_approved` | Boolean (computed, store) | FR-014A | True jika ada BAP/BAST approved |
| `notify_email_enabled` | Boolean | FR-001B | Default False |
| `kurva_s_planned` | Float (computed, store) | FR-010 | Cache planned |
| `kurva_s_actual` | Float (computed, store) | FR-010 | Cache actual |
| `kurva_s_variance` | Float (computed, store) | FR-010 | Cache variance |

**Method:**
- `_compute_document_prerequisites()` — @api.depends checklist
- `_compute_bapbast_approved()` — @api.depends bapbast_ids.state
- `_compute_kurva_s()` — @api.depends wbs planned/actual
- `_compute_calendar_weeks()` — @api.depends awal_kontrak, akhir_kontrak → buat/hapus `schedule.week`
- `_cron_check_kurva_s_alert()` — dipanggil ir.cron
- `_is_active_state()` — abstraction mapping state Sales

### 5.2 `res.users` Extended (FR-012A)

**File:** `models/res_users_ext.py`
**Field:** `assigned_project_ids` (Many2many, computed)

**Method:** `_compute_assigned_projects()` — search `ksg.engineering.assignment` aktif.

### 5.3 `ksg.engineering.schedule.week` (FR-011)

**File:** `models/ksg_engineering_schedule_week.py`

**Field:** `project_id`, `no_minggu` (Integer), `tanggal_mulai`, `tanggal_selesai`.

**SQL Constraint:** `unique(project_id, no_minggu)`.

### 5.4 `ksg.engineering.wbs` (FR-003, FR-004, FR-004A, FR-005, FR-010)

**File:** `models/ksg_engineering_wbs.py`
**Inherit:** `mail.thread`, `mail.activity.mixin`
**Order:** `parent_id, id`

**Field:**

| Field | Tipe | FR Ref |
|---|---|---|
| `project_id` | Many2one ksg.sales.project (required, cascade) | FR-003 |
| `parent_id` | Many2one self (cascade) | FR-003 |
| `child_ids` | One2many self | FR-003 |
| `nama_pekerjaan` | Char (required) | FR-003 |
| `nilai_pekerjaan` | Monetary (required) | FR-003, FR-005 |
| `currency_id` | Many2one (related project) | — |
| `volume` | Float | FR-003 |
| `satuan` | Char | FR-003 |
| `durasi` | Integer | FR-003 |
| `tanggal_mulai` | Date (required) | FR-003, FR-004A |
| `tanggal_selesai` | Date (required) | FR-003, FR-004A |
| `bobot` | Float (computed, store) | FR-005 |
| `periode_minggu_ids` | Many2many schedule.week | FR-004 |
| `planned_progress_mingguan` | Float (computed, store) | FR-004 |
| `planned_progress_kumulatif` | Float (computed, store) | FR-004 |
| `actual_progress_kumulatif` | Float (computed, store) | FR-010 |
| `otorisasi_luar_periode` | Boolean (group_kepala_unit) | FR-004A |
| `alasan_luar_periode` | Text | FR-004A |

**Method:**
- `_check_periode()` — @api.constrains → RULE-03
- `_compute_bobot()` — @api.depends nilai_pekerjaan, nilai_kontrak_terkini → RULE-04
- `_compute_planned()` — bagi bobot per minggu + kumulatif
- `_compute_actual()` — dari weekly.report approved × bobot

### 5.5 `ksg.engineering.assignment` (FR-012)

**File:** `models/ksg_engineering_assignment.py`
**Inherit:** `mail.thread`

**Field:** `project_id`, `user_id`, `peran` (Selection), `tanggal_mulai_tugas`, `tanggal_selesai_tugas`, `active`.

**Selection peran:** `pelaksana`, `engineer`, `design_engineer`, `pengawas`, `supervisor`, `kepala_unit`.

### 5.6 `ksg.engineering.daily.report` + `.line` (FR-006, FR-006A, FR-007)

**File:** `models/ksg_engineering_daily_report.py`, `..._line.py`
**Inherit:** `mail.thread`, `mail.activity.mixin`

**Header `daily.report`:**

| Field | Tipe |
|---|---|
| `project_id` | Many2one (required) |
| `tanggal` | Date (required, default today) |
| `pelaksana_id` | Many2one res.users (default env.user) |
| `line_ids` | One2many |
| `state` | Selection draft/submitted |

**Line `daily.report.line`:**

| Field | Tipe |
|---|---|
| `report_id` | Many2one (cascade) |
| `jam_mulai`, `jam_selesai` | Float |
| `personel_ids` | Many2many res.users |
| `wbs_id` | Many2one ksg.engineering.wbs (required) |
| `progress` | Float |
| `deskripsi` | Text |
| `evidence_ids` | One2many ir.attachment |

**Method:**
- `action_submit()` — cek `working_permit_ok` & `safety_induction_ok` → RULE-02
- `_cron_check_late_report()` — FR-006A, kirim activity H+1

### 5.7 `ksg.engineering.report.consolidation` (FR-008, FR-008A)

**File:** `models/ksg_engineering_report_consolidation.py`
**Inherit:** `mail.thread`, `mail.activity.mixin`

**Field:** `project_id`, `daily_report_ids`, `pengawas_id`, `periode_minggu_id`, `state` (draft/waiting_approval/approved/revisi), `catatan_revisi`.

**Method:**
- `action_ajukan()` — state → waiting_approval → activity ke Supervisor
- `action_approve()` — state → approved → trigger agregasi
- `action_revisi()` — wajib `catatan_revisi` → RULE-05

### 5.8 `ksg.engineering.weekly.report` + `monthly.report` (FR-009, FR-010, FR-010A)

**File:** `models/ksg_engineering_weekly_report.py`, `..._monthly_report.py`
**Inherit:** `mail.thread`

**Weekly field:** `project_id`, `periode_minggu_id`, `consolidation_ids`, `planned_progress`, `actual_progress`, `actual_progress_kumulatif`, `variance` (computed), `state`.

**Monthly field:** analog, agregasi dari weekly.

**Method:**
- `_cron_generate_weekly()` — ir.cron mingguan → RULE-06
- `_cron_generate_monthly()` — ir.cron bulanan → RULE-06

### 5.9 `ksg.engineering.bapbast` (FR-014, FR-014A)

**File:** `models/ksg_engineering_bapbast.py`
**Inherit:** `mail.thread`, `mail.activity.mixin`

**Field:** `name` (sequence), `project_id`, `periode`, `progress_ref_id` (weekly.report), `state` (draft/waiting_approval/approved), `signature_image` (Binary), `signature_id` (opsional Sign), `approver_id`, `tanggal_approve`.

**Method:**
- `action_ajukan()` — activity ke Kepala Unit
- `action_approve(signature)` — set approved + signature + recompute `bapbast_approved`
- Validasi: hanya state `waiting_approval` bisa di-approve

---

## 6. Fase 5 — Views, Menus, Dashboard

### 6.1 Views Wajib

| View | Model | Tipe | FR Ref |
|---|---|---|---|
| `view_ksg_sales_project_engineering_tab` | ksg.sales.project | Form (inherit) | FR-001, FR-002B |
| `view_wbs_tree` | ksg.engineering.wbs | Tree hierarkis | FR-003 |
| `view_wbs_form` | ksg.engineering.wbs | Form | FR-003, FR-004 |
| `view_daily_report_form` | daily.report | Form | FR-006, FR-007 |
| `view_daily_report_tree` | daily.report | Tree | FR-006 |
| `view_consolidation_form` | consolidation | Form + tombol approve/revisi | FR-008 |
| `view_weekly_report_tree` | weekly.report | Tree | FR-009 |
| `view_assignment_tree` | assignment | Tree | FR-012 |
| `view_bapbast_form` | bapbast | Form + tombol approve | FR-014 |
| `view_engineering_dashboard_kanban` | ksg.sales.project | Kanban | FR-001B, FR-002B |

**Catatan inherit view:** External ID `ksg_sales.view_ksg_sales_project_form` **harus disesuaikan** dengan yang riil ada di `ksg_sales`. Lihat Section 2.2.3.

### 6.2 Tombol & Group Restriction

| Tombol | Model | Group | FR Ref |
|---|---|---|---|
| Submit Daily Report | daily.report | Pelaksana | FR-008 |
| Buat Konsolidasi | consolidation | Pengawas | FR-008 |
| Approve Konsolidasi | consolidation | Supervisor | FR-008A |
| Revisi Konsolidasi | consolidation | Supervisor | FR-008A |
| Ajukan BAP/BAST | bapbast | Supervisor | FR-014 |
| Approve BAP/BAST | bapbast | Kepala Unit | FR-014, RULE-08 |

### 6.3 Dashboard

- **Kanban project** dengan badge: `working_permit_ok`, `safety_induction_ok`, `bapbast_approved`.
- **Filter default:** hanya `assigned_project_ids`.
- **Tab Kurva-S** pada form project: chart line planned vs actual.
- **Smart button** "Project Aktif" di profil user (FR-012).

### 6.4 Menus

```
Engineering (root)
├── Dashboard
├── Projects (filtered by assignment)
├── WBS & Master Schedule
├── Daily Reports
├── Consolidations
├── Weekly Reports
├── Monthly Reports
├── BAP/BAST
├── Assignment
└── Configuration
    ├── Schedule Weeks
    └── Activity Types
```

---

## 7. Fase 6 — Otomasi (ir.cron), Notifikasi, Reports

### 7.1 Scheduled Actions (`data/ir_cron_data.xml`)

| Cron ID | Model | Fungsi | Interval | FR Ref |
|---|---|---|---|---|
| `cron_late_report` | daily.report | Cek keterlambatan H+1 | Harian | FR-006A |
| `cron_weekly_report` | weekly.report | Agregasi weekly | Mingguan | FR-009 |
| `cron_monthly_report` | monthly.report | Agregasi monthly | Bulanan | FR-009 |
| `cron_kurva_s_alert` | ksg.sales.project | Cek variance < ambang | Mingguan | FR-010A |

### 7.2 Mail Activity Types (`data/mail_activity_type_data.xml`)

| ID | Nama | Model |
|---|---|---|
| `activity_late_report` | Keterlambatan Daily Report | daily.report |
| `activity_pending_approval` | Menunggu Approval | consolidation |
| `activity_kurva_s_alert` | Peringatan Keterlambatan | ksg.sales.project |
| `activity_bapbast_approval` | Menunggu Approval BAP/BAST | bapbast |

### 7.3 Report BAP/BAST (`report/bapbast_report.xml`)

QWeb report menampilkan:
- Header project, periode, progress ref
- Tabel progress approved
- `signature_image` (jika ada)
- Footer audit trail

### 7.4 Kurva-S Widget (`static/src/js/kurva_s_widget.js`)

Gunakan Chart.js bawaan Odoo. Render line chart planned vs actual per minggu.

### 7.5 Konfigurasi Ambang (ir.config_parameter)

| Parameter | Default | Keterangan |
|---|---|---|
| `ksg_engineering.variance_threshold` | -5.0 | Ambang variance Kurva-S (%) |
| `ksg_engineering.late_report_sla_days` | 1 | SLA keterlambatan Daily Report (hari) |
| `ksg_engineering.approval_sla_days` | 2 | SLA approval Supervisor (hari) |

Dibuat via `data/ir_config_parameter_data.xml`. Bisa diubah tanpa deploy.

---

## 8. Fase 7 — Testing (Acceptance Criteria)

**Perintah:** `odoo --test-enable --test-tags ksg_engineering`

| Test | AC Ref | Skenario |
|---|---|---|
| `test_project_auto_visible` | AC-001 | Project aktif muncul untuk user ter-assign; project lain tidak |
| `test_daily_report_blocked_without_permit` | AC-002B | Submit ditolak jika `working_permit_ok=False` |
| `test_daily_report_success` | AC-002 | Submit berhasil jika permit OK |
| `test_consolidation_approve` | AC-003 | State → approved, weekly ter-update |
| `test_consolidation_revisi_requires_note` | AC-003B | Revisi tanpa catatan → error |
| `test_bapbast_approved_readonly` | AC-004 | Penagihan baca OK, write ditolak |
| `test_wbs_outside_period_raises` | FR-004A | Tanggal di luar periode → ValidationError |
| `test_wbs_otorisasi_luar_periode` | FR-004A | Dengan otorisasi + alasan → OK |
| `test_bobot_recompute_on_addendum` | FR-005, RULE-04 | Ubah nilai kontrak → bobot recompute |
| `test_cron_weekly_aggregation` | FR-009, RULE-06 | Cron buat weekly dari consolidation approved |
| `test_record_rule_assignment` | RULE-01 | User tidak bisa akses project luar assignment |
| `test_bapbast_readonly_for_penagihan` | FR-013A, RULE-08 | Penagihan read-only |
| `test_calendar_weeks` | FR-011 | Kalender minggu terbentuk otomatis |
| `test_kurva_s` | FR-010 | Planned/actual/variance terhitung |
| `test_assignment` | FR-012 | Assignment tercatat & aktif |
| `test_bapbast_approval` | FR-014 | Workflow approval BAP/BAST |

---

## 9. Fase 8 — Traceability Matrix (FR → File → Test)

| FR ID | BR Ref | File Implementasi | Test |
|---|---|---|---|
| FR-001 | BR-001 | `ksg_sales_project_ext.py`, view inherit | `test_project_auto_visible` |
| FR-001A | BR-001A | `ksg_engineering_security.xml`, `res_users_ext.py` | `test_record_rule_assignment` |
| FR-001B | BR-001B | `mail_activity_type_data.xml` | manual |
| FR-002 | BR-002 | view inherit (smart button) | manual |
| FR-002A | BR-002A | `ksg_sales_project_ext.py`, `action_submit()` | `test_daily_report_blocked_without_permit` |
| FR-002B | BR-002B | dashboard kanban badge | manual |
| FR-003 | BR-003 | `ksg_engineering_wbs.py` | `test_wbs_hierarchy` |
| FR-004 | BR-004 | `_compute_planned()` | `test_wbs_planned` |
| FR-004A | BR-004A | `_check_periode()` | `test_wbs_outside_period_raises` |
| FR-005 | BR-005 | `_compute_bobot()` | `test_bobot_recompute_on_addendum` |
| FR-006 | BR-006 | `daily.report` + `.line` | `test_daily_report_success` |
| FR-006A | BR-006A | `_cron_check_late_report()` | `test_cron_late_report` |
| FR-007 | BR-007 | `evidence_ids` | manual |
| FR-008 | BR-008 | `consolidation` state machine | `test_consolidation_approve` |
| FR-008A | BR-008A | Tombol approve group-restricted | `test_consolidation_revisi_requires_note` |
| FR-009 | BR-009 | `_cron_generate_weekly/monthly()` | `test_cron_weekly_aggregation` |
| FR-010 | BR-010 | `_compute_kurva_s()`, widget JS | `test_kurva_s` |
| FR-010A | BR-010A | `_cron_check_kurva_s_alert()` | `test_kurva_s_alert` |
| FR-011 | BR-011 | `_compute_calendar_weeks()` | `test_calendar_weeks` |
| FR-012 | BR-012 | `ksg_engineering_assignment.py` | `test_assignment` |
| FR-012A | BR-012A | `res_users_ext.py` | `test_record_rule_assignment` |
| FR-013 | BR-013 | `ksg_engineering_security.xml` | manual |
| FR-013A | BR-013A | `ir.model.access.csv` | `test_bapbast_readonly_for_penagihan` |
| FR-014 | BR-014 | `ksg_engineering_bapbast.py` | `test_bapbast_approval` |
| FR-014A | BR-014A | `_compute_bapbast_approved()` | `test_bapbast_approved_readonly` |

---

## 10. Fase 9 — Business Rules Enforcement

| Rule ID | Ketentuan | Enforcement | File |
|---|---|---|---|
| RULE-01 | Akses hanya project sesuai assignment | ir.rule domain | `ksg_engineering_security.xml` |
| RULE-01A | Tidak duplikasi data project | `_inherit` only | `ksg_sales_project_ext.py` |
| RULE-02 | Submit daily report wajib permit lengkap | `action_submit()` raise | `ksg_engineering_daily_report.py` |
| RULE-03 | WBS dalam periode PO/kontrak | `@api.constrains` | `ksg_engineering_wbs.py` |
| RULE-04 | Bobot recompute saat addendum | `@api.depends` | `ksg_engineering_wbs.py` |
| RULE-05 | Approval berjenjang tidak dilompati | State machine | `consolidation.py` |
| RULE-05A | Approval berhenti di Kepala Unit | Group restriction | `ksg_engineering_security.xml` |
| RULE-06 | Weekly/Monthly otomatis | ir.cron | `ir_cron_data.xml` |
| RULE-07 | Kurva-S real-time | computed store=True | `ksg_sales_project_ext.py` |
| RULE-08 | Hanya Supervisor/Kepala Unit write BAP/BAST | ACL | security |
| RULE-09 | Status BAP/BAST hanya via approval resmi | `action_approve()` only | `bapbast.py` |
| RULE-10 | Audit trail Chatter | `mail.thread` inherit | semua model custom |

---

## 11. Fase 10 — Integrasi Lintas Modul

### 11.1 Ke `ksg_sales` (Upstream)

| Mekanisme | Detail |
|---|---|
| Inherit model | `_inherit ksg.sales.project` |
| Baca field | Via ORM relasi / related field |
| Trigger notifikasi | Automated action saat `state` = aktif |
| Addendum | `@api.depends('project_id.nilai_kontrak_terkini')` |

### 11.2 Ke `ksg_billing` (Downstream)

| Mekanisme | Detail |
|---|---|
| Field yang dikonsumsi | `bapbast_approved` (read-only) |
| Dokumen pendukung | `bapbast_ids`, `weekly.report`, evidence |
| Cara akses | ORM langsung (bukan REST API) |
| Hak akses | `group_penagihan` read-only via ACL |

**Jika `ksg_billing` belum ada:** buat placeholder (Section 2.6) untuk verifikasi integrasi.

**Jika `ksg_billing` sudah ada:** verifikasi field `bapbast_approved` bisa dibaca. Jangan modifikasi `ksg_billing`; jika perlu field tambahan, minta ke tim Billing.

### 11.3 Ke `ksg_operational` (Paralel)

| Mekanisme | Detail |
|---|---|
| Dependency | Tidak ada dependency langsung |
| Akses | `ksg.sales.project` (sudah memuat field Engineering) dibaca paralel |
| Catatan | Engineering tidak push data ke Operasional |

### 11.4 Notifikasi

| Kanal | Default | Opt-in |
|---|---|---|
| `mail.activity` (in-app) | ✅ Selalu | — |
| Email (`mail.template`) | ❌ | `notify_email_enabled = True` per project |

---

## 12. Fase 11 — Build Order Checklist

### Fase 1 — Deteksi & Penyesuaian Sales
- [ ] 1.1 Cek apakah `ksg_sales` sudah ada di environment
- [ ] 1.2 Jika belum → buat placeholder (Section 2.1)
- [ ] 1.3 Jika sudah → audit field, view, group, rule (Section 2.2)
- [ ] 1.4 Buat `docs/sales_integration_notes.md`
- [ ] 1.5 Sesuaikan mapping jika nama field berbeda
- [ ] 1.6 Verifikasi `ksg_sales` install
- [ ] 1.7 Cek `ksg_billing` → placeholder atau sesuaikan

### Fase 2 — Fondasi
- [ ] 2.1 Skeleton `ksg_engineering`
- [ ] 2.2 Set dependency ke `ksg_sales`

### Fase 3 — Security
- [ ] 3.1 Buat 6 `res.groups` (reuse Penagihan jika ada)
- [ ] 3.2 Buat 5 `ir.rule` (jangan timpa rule Sales)
- [ ] 3.3 Buat `ir.model.access.csv`

### Fase 4 — Models
- [ ] 4.1 `_inherit ksg.sales.project` + field Engineering
- [ ] 4.2 `res.users.assigned_project_ids` computed
- [ ] 4.3 `ksg.engineering.schedule.week` + `_compute_calendar_weeks()`
- [ ] 4.4 `ksg.engineering.wbs` + compute bobot + planned
- [ ] 4.5 `ksg.engineering.assignment`
- [ ] 4.6 `daily.report` + `.line` + `action_submit()`
- [ ] 4.7 `report.consolidation` + workflow approval
- [ ] 4.8 `weekly.report` + `monthly.report`
- [ ] 4.9 `bapbast` + approval + recompute `bapbast_approved`

### Fase 5 — Views & Menus
- [ ] 5.1 Views semua model (10 view)
- [ ] 5.2 Menus
- [ ] 5.3 Dashboard kanban + tab Kurva-S

### Fase 6 — Otomasi & Reports
- [ ] 6.1 ir.cron (4 cron)
- [ ] 6.2 mail.activity types + templates
- [ ] 6.3 QWeb report BAP/BAST
- [ ] 6.4 Kurva-S widget (JS)
- [ ] 6.5 ir.config_parameter (ambang)

### Fase 7 — Testing
- [ ] 7.1 Unit test semua AC (16 test)
- [ ] 7.2 Test integrasi dengan placeholder `ksg_billing`
- [ ] 7.3 Verifikasi record rule lintas project
- [ ] 7.4 Verifikasi integrasi dengan `ksg_sales` riil

### Fase 12 — DoD
- [ ] 12.1 Verifikasi Definition of Done (Section 13)

---

## 13. Definition of Done

Modul dinyatakan selesai jika:

1. `ksg_engineering` install tanpa error.
2. **Integrasi dengan `ksg_sales` terverifikasi** — baik placeholder maupun riil.
3. Semua FR-ID dari FSD terimplementasi & ter-trace (Section 9).
4. Semua RULE-ID ter-enforce (Section 10).
5. Semua unit test lulus (`--test-enable --test-tags ksg_engineering`).
6. Record rule terbukti membatasi akses lintas project.
7. `bapbast_approved` terbaca dari `ksg_billing` (placeholder/riil) via ORM.
8. Tidak ada override pada modul core Odoo.
9. Chatter aktif di semua model custom (audit trail / RULE-10).
10. Approval berhenti di Kepala Unit.
11. Notifikasi default in-app (`mail.activity`); email opt-in.
12. `docs/sales_integration_notes.md` terisi lengkap.
13. Ambang konfigurasi tersimpan di `ir.config_parameter`.

---

## 14. Risiko & Mitigasi

| Risiko | Mitigasi |
|---|---|
| `ksg_sales` belum ada | Placeholder Section 2.1 |
| `ksg_sales` field beda nama | Related field / abstraction Section 2.2 |
| `ksg_sales` rule konflik | Jangan timpa; tambah rule terpisah |
| `ksg_sales` di-upgrade | Abstraction layer Section 2.4 |
| `ksg_billing` belum ada | Placeholder Section 2.6 |
| Modul Sign tidak dilisensi | Fallback `signature_image` Binary |
| Documents app tidak ada | Fallback `ir.attachment` |
| Kustomisasi berlebihan | Ikuti Section 5 ketat |
| Recompute lintas modul berat | `store=True` + `@api.depends` tepat |
| Record rule bocor | Test lintas project Fase 7.3 |

---

## 15. Ringkasan Fase

| Fase | Nama | Output |
|---|---|---|
| 1 | Deteksi & Penyesuaian Sales | Placeholder atau mapping |
| 2 | Fondasi | Skeleton `ksg_engineering` |
| 3 | Security | Groups, rules, ACL |
| 4 | Models | 10 model + extended project & user |
| 5 | Views | Form, tree, kanban, menu, dashboard |
| 6 | Otomasi | ir.cron, mail.activity, report, widget, config |
| 7 | Testing | Unit test AC + integrasi + record rule |
| 8-10 | Traceability & Rules | Matrix FR & RULE |
| 11 | Integrasi Lintas Modul | Sales, Billing, Operasional |
| 12 | DoD | Checklist final |

**Total estimasi file:** ~35 file kode + 4 test + 2 report + 2 docs.

**Urutan eksekusi:** Section 12 (Build Order Checklist).

---

## 16. Catatan Akhir untuk AI Builder

1. **Selalu cek dulu `ksg_sales`** sebelum menulis kode. Jangan asumsi belum ada.
2. **Jangan modifikasi `ksg_sales` atau `ksg_billing`.** Semua penyesuaian di `ksg_engineering`.
3. **Gunakan abstraction layer** untuk field Sales yang mungkin berubah.
4. **Dokumentasikan mapping** di `docs/sales_integration_notes.md`.
5. **Test integrasi** dengan modul riil sebelum DoD.
6. **Jangan lompat fase.** Ikuti Section 12 berurutan.
7. **Verifikasi Section 13** sebelum menyatakan selesai.

---

**Akhir dokumen.** AI Builder wajib mengikuti Section 12 secara berurutan, memverifikasi Section 13, dan mendokumentasikan penyesuaian `ksg_sales` di `docs/sales_integration_notes.md`.
