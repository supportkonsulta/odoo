from odoo import models, fields, api

class KsgSalesProjectInherit(models.Model):
    _inherit = 'ksg.sales.project'

    # Relasi Operasional
    assignment_ids = fields.One2many(
        'ksg.operational.assignment', 
        'project_id', 
        string='Daftar Penugasan'
    )
    attendance_report_ids = fields.One2many(
        'ksg.operational.attendance.report', 
        'project_id', 
        string='Laporan Presensi'
    )
    monthly_report_ids = fields.One2many(
        'ksg.operational.monthly.report', 
        'project_id', 
        string='Laporan Bulanan'
    )
    billing_document_ids = fields.One2many(
        'ksg.operational.billing.document', 
        'project_id', 
        string='Dokumen Penagihan'
    )
    bapbast_ops_ready = fields.Boolean(
        string='Dokumen Ops Siap Tagih', 
        default=False
    )

    manpower_request_ids = fields.One2many(
        'ksg.operational.manpower.request', 
        'project_id', 
        string='Permintaan SDM'
    )
    supply_request_ids = fields.One2many(
        'ksg.operational.supply.request', 
        'project_id', 
        string='Permintaan Perlengkapan'
    )
    hpp_ids = fields.One2many(
        'ksg.operational.hpp', 
        'project_id', 
        string='Lembar HPP Operasional'
    )

    # Format Tampilan Proyek: "26001 (Instalasi RS)"
    @api.depends('kode_proyek')
    def _compute_display_name(self):
        for rec in self:
            code = rec.kode_proyek or ''
            name = ''
            for f in ['nama_pekerjaan', 'nama_proyek', 'name', 'deskripsi_pekerjaan', 'judul_proyek']:
                val = getattr(rec, f, False)
                if val and str(val).strip() and str(val).strip() != str(code).strip():
                    name = str(val).strip()
                    break
            if code and name:
                rec.display_name = f"{code} ({name})"
            elif code:
                rec.display_name = code
            elif name:
                rec.display_name = name
            else:
                rec.display_name = f"Proyek #{rec.id}"

    # Pencarian Dropdown Bisa Menggunakan Kode Maupun Nama Pekerjaan
    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, order=None):
        args = args or []
        domain = []
        if name:
            subdomains = [('kode_proyek', operator, name)]
            for f in ['nama_pekerjaan', 'nama_proyek', 'name']:
                if f in self._fields:
                    subdomains.append((f, operator, name))
            if len(subdomains) > 1:
                or_domain = []
                for _ in range(len(subdomains) - 1):
                    or_domain.append('|')
                or_domain.extend(subdomains)
                domain = or_domain
            else:
                domain = subdomains
        return self._search(domain + args, limit=limit, order=order)