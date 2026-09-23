# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

MONTH_SELECTIONS = [
    ('01', 'Januari'),
    ('02', 'Februari'),
    ('03', 'Maret'),
    ('04', 'April'),
    ('05', 'Mei'),
    ('06', 'Juni'),
    ('07', 'Juli'),
    ('08', 'Agustus'),
    ('09', 'September'),
    ('10', 'Oktober'),
    ('11', 'November'),
    ('12', 'Desember'),
]

SEMESTER_SELECTIONS = [
    ('ganjil', 'Semester Ganjil'),
    ('genap', 'Semester Genap'),
    ('1', 'Semester 1'),
    ('2', 'Semester 2'),
    ('3', 'Semester 3'),
    ('4', 'Semester 4'),
    ('5', 'Semester 5'),
    ('6', 'Semester 6'),
    ('7', 'Semester 7'),
    ('8', 'Semester 8'),
]


class EducationBillGenerateWizard(models.TransientModel):
    _name = 'education.bill.generate.wizard'
    _description = 'Wizard Generate Tagihan Massal'

    school_id = fields.Many2one(
        'education.school',
        string='Sekolah / Kampus',
        required=True
    )
    level = fields.Selection(
        related='school_id.level',
        string='Jenjang',
        readonly=True
    )
    class_id = fields.Many2one(
        'education.class',
        string='Kelas Tertentu (Opsional)',
        domain="[('school_id', '=', school_id)]",
        help='Kosongkan jika ingin men-generate tagihan untuk seluruh siswa di institusi ini.'
    )

    bill_type = fields.Selection([
        ('spp', 'SPP Bulanan (Sekolah)'),
        ('ukt', 'UKT Semesteran (Universitas)'),
    ], string='Tipe Tagihan', required=True, default='spp')

    month = fields.Selection(
        MONTH_SELECTIONS,
        string='Bulan Tagihan',
        default=lambda self: str(fields.Date.today().month).zfill(2)
    )
    year = fields.Integer(
        string='Tahun',
        default=lambda self: fields.Date.today().year,
        required=True
    )
    semester = fields.Selection(
        SEMESTER_SELECTIONS,
        string='Semester Tagihan',
        default='ganjil'
    )
    academic_year_id = fields.Many2one(
        'education.academic.year',
        string='Tahun Ajaran',
        default=lambda self: self.env['education.academic.year'].search([('is_current', '=', True)], limit=1),
        required=True
    )

    bill_date = fields.Date(
        string='Tanggal Tagihan',
        required=True,
        default=fields.Date.context_today
    )
    due_date = fields.Date(
        string='Tanggal Jatuh Tempo',
        required=True,
        default=fields.Date.context_today
    )
    auto_publish = fields.Boolean(
        string='Langsung Terbitkan (Status Belum Dibayar)',
        default=True,
        help='Jika dicentang, status tagihan langsung "Belum Dibayar" sehingga siap diverifikasi / ditagihkan.'
    )

    @api.onchange('school_id')
    def _onchange_school_id(self):
        if self.school_id:
            if self.school_id.level == 'univ':
                self.bill_type = 'ukt'
            else:
                self.bill_type = 'spp'

    def action_generate_bills(self):
        self.ensure_one()
        Student = self.env['education.student']
        Bill = self.env['education.bill']

        domain = [
            ('school_id', '=', self.school_id.id),
            ('active', '=', True)
        ]
        if self.class_id:
            domain.append(('class_id', '=', self.class_id.id))

        students = Student.search(domain)
        if not students:
            raise UserError(_('Tidak ditemukan siswa/mahasiswa aktif untuk kriteria yang dipilih.'))

        month_dict = dict(MONTH_SELECTIONS)
        semester_dict = dict(SEMESTER_SELECTIONS)

        created_bills = self.env['education.bill']
        skipped_count = 0

        for student in students:
            amount = student.effective_amount
            if amount <= 0:
                continue

            # Periksa tagihan duplikat untuk periode ini
            dup_domain = [
                ('student_id', '=', student.id),
                ('bill_type', '=', self.bill_type),
                ('state', '!=', 'cancelled'),
            ]
            if self.bill_type == 'spp':
                dup_domain.extend([('month', '=', self.month), ('year', '=', self.year)])
            else:
                dup_domain.extend([('semester', '=', self.semester), ('academic_year_id', '=', self.academic_year_id.id)])

            existing = Bill.search(dup_domain, limit=1)
            if existing:
                skipped_count += 1
                continue

            vals = {
                'student_id': student.id,
                'school_id': self.school_id.id,
                'class_id': student.class_id.id if student.class_id else False,
                'major_id': student.major_id.id if student.major_id else False,
                'bill_type': self.bill_type,
                'month': self.month if self.bill_type == 'spp' else False,
                'year': self.year,
                'semester': self.semester if self.bill_type == 'ukt' else False,
                'academic_year_id': self.academic_year_id.id,
                'bill_date': self.bill_date,
                'due_date': self.due_date,
                'amount': amount,
                'company_id': self.school_id.company_id.id,
                'category_id': self.school_id.category_id.id if self.school_id.category_id else False,
                'state': 'unpaid' if self.auto_publish else 'draft',
            }

            bill = Bill.create(vals)
            created_bills |= bill

        if not created_bills and skipped_count > 0:
            raise UserError(_('Semua siswa (%d) sudah memiliki tagihan untuk periode ini.') % skipped_count)

        return {
            'name': _('Hasil Generate Tagihan (%d Dibuat, %d Dilewati)') % (len(created_bills), skipped_count),
            'type': 'ir.actions.act_window',
            'res_model': 'education.bill',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_bills.ids)],
            'target': 'current',
        }
