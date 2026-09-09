# Plan: Approval Routes Nested Level UI + Add Next Level

> **Status:** Plan — belum implementasi.
> **Tanggal:** 2026-09-09
> **Modul:** presenly (saat ini 19.0.15.3.0, target 19.0.16.0.0)

---

## 1. Kondisi Saat Ini (hasil riset terverifikasi)

1. **Model** `presenly.approval.rule`: 1 record = 1 step (level). Field
   `sequence` (Order, auto +10), `request_group` (stored: overtime/permission/
   leave/unassigned), `work_location_id` (kosong = company default),
   `approver_type`, `is_complete`.
2. **View global** (`view_presenly_approval_rule_list`): read-only,
   `default_group_by="request_group,work_location_id"` — hanya 2 tingkat
   (Jenis Request → Lokasi), baris **tidak diurutkan eksplisit per level**,
   dan tidak menunjukkan label request type (mis. "Sick Time Off") sebagai
   header — hanya badge request_group.
3. **View editable per-modul** (`view_presenly_approval_rule_list_editable`):
   flat, `default_order="sequence, id"`, create aktif. Digunakan action
   leave/permission/overtime + smart button "Ready Steps".
4. **Create baru**: context smart button sudah mengirim `default_leave_type_id`
   / `default_permission_type_id` → form create otomatis terisi type yang
   sama. **Namun** tidak ada cara *langsung dari baris/level yang sedang
   dilihat* untuk menambah level berikutnya — user harus kembali ke smart
   button / membuka form & menambah manual.
5. **Order otomatis** `_default_sequence()` sudah membaca context
   `default_*` dan menghitung `max+10` → konsisten untuk "level berikutnya".

**Gap yang diminta user:**
- Tampilan Approval Routes **sesuai levelling (Order)** dan **nested** —
  header per request type, baris per level urut 10, 20, 30.
- Saat **add**, langsung bisa menambahkan level **di bawahnya** dengan
  **type yang sama** (tanpa mengisi ulang type).

---

## 2. Desain Solusi

### Task 1 — Model: field `route_scope_label` (kunci nesting)

`models/presenly_approval.py` — tambah field stored computed:

```python
route_scope_label = fields.Char(
    string='Request Type Scope', compute='_compute_route_scope_label',
    store=True, index=True,
)
```

Logika (depend: is_overtime_route, permission_type_id, leave_type_id):
- leave → `Time Off: {leave_type.display_name}`
- permission → `Permission: {permission_type.display_name}`
- overtime → `Overtime`
- unassigned → `Unassigned`

Fungsinya sebagai **taggal grouping level 2** yang menyatukan
leave/permission/overtime dalam satu kolom grup (tidak bisa dicapai dengan
group-by field relasi karena 3 field berbeda).

### Task 2 — View global: nested level UI

`views/presenly_approval_views.xml` — `view_presenly_approval_rule_list`:

```xml
<list string="Approval Routes"
      create="0" edit="0" delete="0" duplicate="false"
      default_group_by="company_id,request_group,route_scope_label,work_location_id"
      default_order="sequence, id"
      ...>
```

Efek tampilan (nested, 4 tingkat):
```
▶ PT KONSULTA SEMEN GRESIK                      (company)
  ▶ Time Off                                    (request_group, badge)
    ▶ Time Off: Sick Time Off                   (route_scope_label)
      ▶ All Work Locations (Company Default)    (work_location_id)
        10 | Manager Review      | Employee Manager   (baris per level)
        20 | HR Officer Check    | HR Officer
```
- Baris dalam grup otomatis urut `sequence` (levelling terlihat jelas).
- Kolom: `sequence` (Order, badge), `name`, `approver_display`, `is_complete`,
  `active`.
- Tombol per baris: **"Add Next Level"** (kolom action) — lihat Task 4.

### Task 3 — View editable per-modul: tetap ringkas + add selaras

`view_presenly_approval_rule_list_editable`:
- `default_group_by="work_location_id"` — saat membuka via smart button
  (domain sudah type tertentu), baris tinggal diurutkan per lokasi & per level.
- `default_order="sequence, id"`, `widget="handle"` tetap di sequence
  (drag-reorder), create tetap aktif.
- Tambah tombol per baris "Add Next Level" juga di sini.

### Task 4 — "Add Next Level" (menambah level di bawahnya, type sama)

**Model** — method di `PresenlyApprovalRule`:

```python
def action_add_next_level(self):
    """Open a create form for the next level of the SAME scope."""
    self.ensure_one()
    action = self.env['ir.actions.actions']._for_xml_id(
        'presenly.action_presenly_approval_rule'
    )
    action['name'] = f'Add Next Level — {self.name or self.display_name}'
    action['view_mode'] = 'form'
    action['views'] = [(self.env.ref(
        'presenly.view_presenly_approval_rule_form').id, 'form')]
    action['target'] = 'new'
    action['context'] = {
        'default_company_id': self.company_id.id,
        'default_work_location_id': self.work_location_id.id,
        'default_leave_type_id': self.leave_type_id.id,
        'default_permission_type_id': self.permission_type_id.id,
        'default_is_overtime_route': self.is_overtime_route,
        'default_approver_type': 'employee_manager',
        'default_name': f'{self.name} — Next Level'
                         if self.name else False,
        'active_test': True,
    }
    return action
```

- `default_get`/`_default_sequence()` yang sudah ada otomatis memberi preview
  **Order = max+10** untuk scope yang sama → "level di bawahnya" benar.
- Context mengisi semua dimensi scope (company + location + type) → user
  cukup pilih approver.

**View** — tombol dipasang di dua tempat:
1. **List row button** (di list global & editable):
   ```xml
   <button name="action_add_next_level" type="object" string="Add Next Level"
           icon="fa-plus" groups="presenly.group_presenly_manager"/>
   ```
2. **Form header** (`view_presenly_approval_rule_form`):
   ```xml
   <header>
     <button name="action_add_next_level" type="object"
             string="Add Next Level" class="btn-primary" icon="fa-plus"/>
   </header>
   ```
   (Form saat ini belum punya `<header>` — tambahkan yang baru.)

### Task 5 — README + docs

- README: jelaskan tampilan nested (Company → Request Group → Request Type →
  Location → Level 10/20/30) dan tombol "Add Next Level".

### Task 6 — Test (`tests/test_approval_nested_levels.py`)

1. `test_route_scope_label_computed` — label benar untuk leave/permission/
   overtime/unassigned; stored & index.
2. `test_list_view_nested_grouping` — arch list global mengandung
   `default_group_by="company_id,request_group,route_scope_label,work_location_id"`
   dan `default_order="sequence, id"`.
3. `test_form_has_add_next_level_button` — arch form mengandung button
   `action_add_next_level`.
4. `test_add_next_level_context_same_type` — rule leave → action context
   berisi `default_leave_type_id` sama & `default_work_location_id` sama,
   `default_permission_type_id=False`; rule permission → kebalikannya.
5. `test_add_next_level_previews_next_order` — context method → `default_get
   (['sequence'])` pada form create (simulasi Form) menghasilkan `max+10`
   (10 → 20 → 30), dan tidak bentrok constraint.
6. Regression: seluruh suite `/presenly` (97 tests) tetap hijau.

### Task 7 — Validasi & rollout (pola sama)

1. Bump versi `19.0.16.0.0`.
2. Backup `odoo-before-nested-levels-YYYYMMDD_HHMMSS.dump`.
3. Clone DB + filestore → `-u presenly --test-tags /presenly` di port 8071
   (server utama 8069 tetap jalan; polling `kill -0`, tanpa sleep buta).
4. Fingerprint data identik (rules 34/17 aktif, journeys 8/102, dst.) —
   `route_scope_label` hanya kolom komputasi, tidak mengubah data.
5. Upgrade DB utama, restart, HTTP 200, kiosk 404.
6. Dokumen `docs/NESTED_LEVELS_ROLLOUT_POSTCHECK_YYYYMMDD.txt`.

---

## 3. File yang Diubah

| File | Perubahan |
|---|---|
| `models/presenly_approval.py` | Field `route_scope_label` (stored) + method `action_add_next_level` |
| `views/presenly_approval_views.xml` | List global nested grouping; list editable group by lokasi; button row + header form |
| `README.md` | Dokumentasi nested view & Add Next Level |
| `tests/test_approval_nested_levels.py` (baru) | 5–6 test |
| `tests/__init__.py` | Registrasi |
| `__manifest__.py` | Bump 19.0.16.0.0 |

---

## 4. Matriks Akses (tidak berubah)

| Fitur | Employee | Approver | HR | Manager |
|---|---|---|---|---|
| Lihat Approval Routes nested | ❌ | ❌ | ❌ | ✅ |
| Add Next Level / create rule | ❌ | ❌ | ❌ | ✅ |
| Reorder (drag) | ❌ | ❌ | ❌ | ✅ |

---

## 5. Keputusan yang Perlu Konfirmasi

1. **Level grouping**: 4 tingkat `Company → Request Group → Request Type →
   Work Location` + baris per Order — cukup, atau mau 3 tingkat saja (tanpa
   company bila single-company)?
2. **Tombol Add Next Level**: pasang di **list row + form header** (rekomendasi)
   atau cukup salah satu?
3. **Nama default** step baru: `"{parent.name} — Next Level"` atau kosong
   (placeholder "e.g. Manager Review")?
4. **Approver default** form baru: `employee_manager` (rekomendasi, konsisten
   dengan wizard generate) — setuju?
5. **Drag-reorder** tetap dipertahankan di view editable — setuju?