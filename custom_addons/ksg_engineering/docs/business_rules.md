# Business Rules — KSG Engineering

| Rule ID | Ketentuan | Enforcement | File |
|---|---|---|---|
| RULE-01 | Akses hanya project sesuai assignment | ir.rule domain `user.assigned_project_ids` | `security/ksg_engineering_security.xml` |
| RULE-01A | Tidak duplikasi data project | `_inherit ksg.sales.project` only | `models/ksg_sales_project_ext.py` |
| RULE-02 | Submit daily report wajib permit lengkap | `action_submit()` raise ValidationError | `models/ksg_engineering_daily_report.py` |
| RULE-03 | WBS dalam periode PO/kontrak | `@api.constrains` | `models/ksg_engineering_wbs.py` |
| RULE-04 | Bobot recompute saat addendum | `@api.depends('project_id.nilai_kontrak_terkini')` | `models/ksg_engineering_wbs.py` |
| RULE-05 | Approval berjenjang tidak dilompati | State machine (draft → waiting → approved/revisi) | `models/ksg_engineering_report_consolidation.py` |
| RULE-05A | Approval berhenti di Kepala Unit | Group restriction di XML + ACL | `security/ksg_engineering_security.xml` |
| RULE-06 | Weekly/Monthly otomatis | ir.cron | `data/ir_cron_data.xml` |
| RULE-07 | Kurva-S real-time | computed store=True | `models/ksg_sales_project_ext.py` |
| RULE-08 | Hanya Supervisor/Kepala Unit write BAP/BAST | ACL di ir.model.access.csv | `security/ir.model.access.csv` |
| RULE-09 | Status BAP/BAST hanya via approval resmi | `action_approve()` only, state check | `models/ksg_engineering_bapbast.py` |
| RULE-10 | Audit trail Chatter | `mail.thread` inherit | Semua model custom |
