from odoo import models, fields, api

class KsgSalesProjectInherit(models.Model):
    _inherit = 'ksg.sales.project'

    # Rencana Kebutuhan Proyek
    manpower_plan_ids = fields.One2many(
        'ksg.operational.manpower.plan', 'project_id', string='Rencana Manpower'
    )
    equipment_plan_ids = fields.One2many(
        'ksg.operational.equipment.plan', 'project_id', string='Rencana Perlengkapan'
    )
    material_plan_ids = fields.One2many(
        'ksg.operational.material.plan', 'project_id', string='Rencana Alat & Bahan'
    )
    assignment_ids = fields.One2many(
        'ksg.operational.assignment', 'project_id', string='Tenaga Kerja Aktif'
    )
    billing_doc_ids = fields.One2many(
        'ksg.operational.billing.document', 'project_id', string='Dokumen Tagihan'
    )

    # Indikator Dokumen
    bapbast_ops_ready = fields.Boolean(
        string='Dokumen Ops Siap Tagih',
        compute='_compute_bapbast_ops_ready',
        store=True,
    )
    total_estimasi_biaya_rencana = fields.Float(
        string='Total Estimasi Biaya Rencana',
        compute='_compute_total_estimasi_biaya',
        store=True,
    )

    @api.depends('manpower_plan_ids.total_biaya', 'equipment_plan_ids.total_biaya')
    def _compute_total_estimasi_biaya(self):
        for rec in self:
            total_mp = sum(rec.manpower_plan_ids.mapped('total_biaya'))
            total_eq = sum(rec.equipment_plan_ids.mapped('total_biaya'))
            rec.total_estimasi_biaya_rencana = total_mp + total_eq

    @api.depends('billing_doc_ids.jenis_dokumen', 'billing_doc_ids.attachment_id')
    def _compute_bapbast_ops_ready(self):
        for rec in self:
            docs = rec.billing_doc_ids.filtered(lambda d: d.attachment_id)
            has_presensi = any(d.jenis_dokumen == 'presensi' for d in docs)
            has_bast = any(d.jenis_dokumen == 'bast' for d in docs)
            rec.bapbast_ops_ready = has_presensi and has_bast

    # --- SINKRONISASI OTOMATIS TANPA SYARAT DI LATAR BELAKANG ---
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._auto_sync_to_operational()
        return records

    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            rec._auto_sync_to_operational()
        return res

    def _auto_sync_to_operational(self):
        """Mengecek seluruh rencana dan memastikan dokumen di Operasional terbuat"""
        for rec in self:
            # 1. Manpower Plan -> Permohonan Manpower HC
            for mp in rec.manpower_plan_ids:
                if not mp.role:
                    continue
                req = self.env['ksg.operational.manpower.request'].search([
                    ('project_id', '=', rec.id),
                    ('kriteria', '=', mp.role),
                ], limit=1)

                if not req:
                    self.env['ksg.operational.manpower.request'].create({
                        'project_id': rec.id,
                        'kriteria': mp.role,
                        'jumlah_dibutuhkan': int(mp.jumlah),
                        'catatan': f"Kebutuhan otomatis dari Proyek {rec.display_name or ''}",
                        'state': 'draft',
                    })
                elif req.state == 'draft':
                    req.write({'jumlah_dibutuhkan': int(mp.jumlah)})

            # 2. Perlengkapan & Material -> Pengadaan BoQ
            if rec.equipment_plan_ids or rec.material_plan_ids:
                procurement = self.env['ksg.operational.procurement.request'].search([
                    ('project_id', '=', rec.id),
                    ('state', '=', 'draft'),
                ], limit=1)

                if not procurement:
                    procurement = self.env['ksg.operational.procurement.request'].create({
                        'project_id': rec.id,
                        'state': 'draft',
                    })

                # Perlengkapan
                for eq in rec.equipment_plan_ids:
                    if not eq.name:
                        continue
                    line = procurement.boq_line_ids.filtered(lambda l: l.item == eq.name)
                    if line:
                        line.write({'jumlah': eq.jumlah})
                    else:
                        self.env['ksg.operational.boq.line'].create({
                            'procurement_id': procurement.id,
                            'item': eq.name,
                            'spesifikasi': 'Perlengkapan Lapangan',
                            'satuan': 'Unit',
                            'jumlah': eq.jumlah,
                        })

                # Material / Alat & Bahan
                for mat in rec.material_plan_ids:
                    if not mat.name:
                        continue
                    line = procurement.boq_line_ids.filtered(lambda l: l.item == mat.name)
                    if line:
                        line.write({
                            'jumlah': mat.jumlah,
                            'spesifikasi': mat.spesifikasi or 'Material Proyek',
                            'satuan': mat.satuan or 'Pcs',
                        })
                    else:
                        self.env['ksg.operational.boq.line'].create({
                            'procurement_id': procurement.id,
                            'item': mat.name,
                            'spesifikasi': mat.spesifikasi or 'Material Proyek',
                            'satuan': mat.satuan or 'Pcs',
                            'jumlah': mat.jumlah,
                        })