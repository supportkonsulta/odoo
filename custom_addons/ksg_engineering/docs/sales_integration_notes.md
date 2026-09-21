# Catatan Integrasi dengan ksg_sales

## Field Mapping

| Engineering Butuh | Field Sales Riil | Tipe | Catatan |
|---|---|---|---|
| `name` (Kode Project) | `kode_proyek` | Char | Sales menggunakan `_rec_name = 'kode_proyek'`. Tidak ada field `name`. |
| `partner_id` | `klien` | Many2one res.partner | Engineering membuat related field `partner_id = fields.Many2one(related='klien')` |
| `state` | `status` | Selection (aktif/selesai/batal) | Mapping via `_is_active_state()` — cek `self.status in ('aktif',)` |
| `awal_kontrak` | `awal_kontrak` | Date | Sama persis |
| `akhir_kontrak` | `akhir_kontrak` | Date | Sama persis |
| `nilai_kontrak_terkini` | `nilai_kontrak_terkini` | Monetary (computed) | Sama persis. Computed dari addendum. |
| `currency_id` | `currency_id` | Many2one res.currency | Sama persis |
| `checklist_dokumen_ids` | `checklist_dokumen_ids` | Many2many ksg.sales.document.checklist | Sama persis (tipe Many2many, bukan One2many) |
| `document_ids` | **TIDAK ADA** | — | Ditambahkan di `ksg_sales_project_ext.py` sebagai Many2many ir.attachment. TODO: pindahkan ke ksg_sales. |

## Checklist Dokumen

Model `ksg.sales.document.checklist` di Sales hanya memiliki:
- `name` (Char) — Nama dokumen
- `active` (Boolean)

**Tidak ada field `tipe` dan `status`** yang diharapkan oleh engineering plan.

### Solusi:
- `working_permit_ok` dan `safety_induction_ok` dihitung berdasarkan **nama dokumen** di checklist (contains 'working permit' / 'safety induction').
- Pendekatan ini bersifat sementara sampai ksg_sales menambahkan field `tipe` dan `status`.

## External ID View

- Form project: `ksg_sales.view_ksg_sales_project_form`
- List project: `ksg_sales.view_ksg_sales_project_list`

## Group Reuse

- `group_penagihan`: **TIDAK ADA** di ksg_sales. Dibuat sendiri di ksg_engineering.
- ksg_sales hanya memiliki: `group_sales_user`, `group_sales_manager`

## Rule Existing

- **TIDAK ADA** ir.rule di ksg_sales. Semua akses via ACL saja.
- Engineering membuat rule sendiri tanpa risiko konflik.

## Addendum

- Model: `ksg.sales.project.addendum`
- Field: `project_id`, `nama_addendum`, `nilai_addendum`, `tanggal_addendum`
- `nilai_kontrak_terkini` di-compute dari `nilai_kontrak_awal + sum(addendum_ids.nilai_addendum)`
- `@api.depends('project_id.nilai_kontrak_terkini')` di WBS sudah menangkap perubahan.

## Model Tambahan Sales

| Model | Keterangan |
|---|---|
| `ksg.sales.project` | Model utama project |
| `ksg.sales.category` | Kategori project |
| `ksg.sales.document.checklist` | Master checklist (hanya nama + active) |
| `ksg.sales.project.addendum` | Addendum kontrak |
| `ksg.sales.project.term` | Termin penagihan |
| `ksg.sales.rab` + `.line` | RAB |
| `ksg.sales.hpp` + `.line` | HPP |
| `account.move` (inherited) | Invoice link |

## Catatan Penting

1. ksg_sales menggunakan Odoo **19.0**, bukan 17/18 seperti di plan awal.
2. Field `kategori` di Sales adalah `Many2one` ke `ksg.sales.category`, bukan `Char`.
3. Engineering **TIDAK memodifikasi** file apapun di ksg_sales.
