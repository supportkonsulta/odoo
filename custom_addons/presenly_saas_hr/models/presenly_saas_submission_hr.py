"""Tautan pengajuan ke model native: pegawai Odoo dan lokasi kerja Odoo.

Payroll menyaring lembur dengan empat kunci, dan itu terbaca di
`presenly_payroll/models/custom_payroll_slip.py`: pegawai (`hr.employee`),
status disetujui, rentang tanggal, dan lokasi kerja (`hr.work.location`). Tiga
di antaranya sudah ada di cermin pengajuan; yang belum adalah dua tautan itu.

Tautan ini disiapkan supaya penyambungan payroll nanti hanya perlu mengganti nama
model dan satu baris domain, bukan mengerjakan datanya lagi. Yang **tidak**
dikerjakan di sini: mengubah modul payrollnya sendiri.

Diletakkan di modul ini, bukan di `presenly_saas`, karena `presenly_saas` dipakai
juga oleh tenant tanpa `hr`. Pengisiannya lewat hook `_mirror_fill_links` yang
disediakan mixin cermin, sehingga modul itu tidak perlu tahu tentang `hr`.
"""

from odoo import _, api, fields, models


class PresenlySaasSubmissionHrMixin(models.AbstractModel):
    """Dua tautan native yang dipakai payroll, untuk kelima jenis pengajuan."""

    _name = 'presenly.saas.submission.hr.mixin'
    _description = 'Presenly SaaS Submission: native links'

    hr_employee_id = fields.Many2one(
        'hr.employee',
        string='Odoo Employee',
        index=True,
        ondelete='set null',
        readonly=True,
        help='The Odoo employee this request belongs to, matched on nopeg like '
             'the rest of the sync. Kept as a relation so payroll can filter by '
             'employee without matching numbers by hand.',
    )
    hr_work_location_id = fields.Many2one(
        'hr.work.location',
        string='Odoo Work Location',
        index=True,
        ondelete='set null',
        readonly=True,
        help='The Odoo work location this request happened at, matched on the '
             'Presenly location id. Payroll already filters payslips by this '
             'field, so the mirror answers the same key.',
    )

    @api.model
    def _mirror_fill_links(self, company):
        """Isi tautan pegawai dan lokasi untuk baris yang belum punya.

        Dipanggil hook dari `presenly.saas.mirror.mixin` setiap kali cerminnya
        ditulis. Pencariannya dibatch: satu untuk semua pegawai, satu untuk semua
        lokasi, bukan satu per baris.

        Hanya kolom yang masih kosong yang diisi, dengan alasan yang sama seperti
        cabang: pengajuan adalah catatan masa lalu, dan tautan yang sudah benar
        tidak ditulis ulang.
        """
        if 'hr_employee_id' not in self._fields or 'location_id' not in self._fields:
            return 0

        pending = self.sudo().search([
            ('company_id', '=', company.id),
            '|', ('hr_employee_id', '=', False), ('hr_work_location_id', '=', False),
        ])
        if not pending:
            return 0

        # Pegawai: lewat cermin pegawai, kunci yang sama dengan sinkronisasi.
        peta_pegawai = {}
        nopegs = [nopeg for nopeg in pending.mapped('employee_nopeg') if nopeg]
        if nopegs:
            cermin = self.env['presenly.saas.employee'].sudo().search([
                ('company_id', '=', company.id),
                ('nopeg', 'in', nopegs),
            ])
            peta_pegawai = {
                baris.nopeg: baris.hr_employee_id
                for baris in cermin if baris.hr_employee_id
            }

        # Lokasi: lewat id lokasi di sisi Presenly, bukan lewat namanya. Bisa ada
        # lebih dari satu kandidat bila dua tenant memakai id yang sama, jadi
        # pilihannya disimpan sebagai daftar dan dipilih per baris.
        peta_lokasi = {}
        lokasi_ids = [nilai for nilai in pending.mapped('location_id') if nilai]
        if lokasi_ids:
            for lokasi in self.env['hr.work.location'].sudo().search([
                ('presenly_external_id', 'in', lokasi_ids),
            ]):
                peta_lokasi.setdefault(lokasi.presenly_external_id, []).append(lokasi)

        diisi = 0
        for baris in pending:
            nilai = {}
            if not baris.hr_employee_id:
                pegawai = peta_pegawai.get(baris.employee_nopeg)
                if pegawai:
                    nilai['hr_employee_id'] = pegawai.id
            if not baris.hr_work_location_id:
                kandidat = peta_lokasi.get(baris.location_id) or []
                lokasi = self._pilih_lokasi(kandidat, baris)
                if lokasi:
                    nilai['hr_work_location_id'] = lokasi.id
            if not nilai:
                continue
            baris.write(nilai)
            diisi += 1
        return diisi

    # ------------------------------------------------------------------
    # Memberi tahu layar yang sedang terbuka
    # ------------------------------------------------------------------
    # Yang dipantau hanya dua kolom: statusnya, dan level yang sedang berjalan.
    # Keduanya berubah tepat saat pengajuannya bergerak - dan hanya saat itu layar
    # pengguna perlu diberi tahu.
    _PANTAU_PERUBAHAN = ('status', 'approval_current_level')

    def write(self, values):
        sebelum = None
        if any(kunci in values for kunci in self._PANTAU_PERUBAHAN):
            sebelum = {
                baris.id: (baris.status, baris.approval_current_level)
                for baris in self
            }
        hasil = super().write(values)
        if sebelum:
            self._presenly_notify_change(sebelum)
        return hasil

    def _presenly_notify_change(self, sebelum):
        """Beri tahu pengguna yang berkepentingan lewat bus Odoo.

        Yang diberi tahu hanya dua orang: pemohonnya, dan pemegang level yang
        sedang berjalan. Keduanya memang menunggu kabar ini; menyiarkannya ke
        semua pengguna berarti memberi tahu bahwa pengajuan itu ada, lengkap
        dengan statusnya.

        Isinya data, bukan kalimat yang sudah dirangkai: kalimatnya disusun di
        sisi klien, supaya bahasanya bahasa penerima, bukan bahasa proses
        sinkronisasi yang kebetulan sedang berjalan.
        """
        for baris in self:
            if sebelum.get(baris.id) == (
                baris.status, baris.approval_current_level,
            ):
                continue

            penerima = (
                baris.hr_employee_id.user_id | baris._presenly_approver_user()
            ).filtered('active')
            if not penerima:
                continue

            pesan = {
                'model': baris._name,
                'id': baris.id,
                'res_name': baris.display_name,
                'status': baris.status or '',
                'level': baris.approval_current_level or 0,
                'total_levels': baris.approval_total_levels or 0,
                'waiting_for': baris.approval_waiting_for or '',
            }
            for pengguna in penerima:
                self.env['bus.bus'].sudo()._sendone(
                    pengguna.partner_id, 'presenly_saas_submission', pesan,
                )

    @staticmethod
    def _pilih_lokasi(kandidat, baris):
        """Pilih lokasi yang perusahaannya cocok dengan cabang barisnya.

        Lokasi kerja native dimiliki perusahaan cabangnya, bukan perusahaan
        tempat integrasi dipasang, jadi kecocokan itu yang dipakai lebih dulu.
        Kalau tidak ada yang cocok, kandidat pertama dipakai, dan yang penting
        jumlahnya satu.
        """
        if not kandidat:
            return False
        if len(kandidat) == 1:
            return kandidat[0]
        cabang = baris.tenant_client_company_id
        if cabang:
            for lokasi in kandidat:
                if lokasi.company_id == cabang:
                    return lokasi
        return kandidat[0]


class PresenlySaasLeave(models.Model):
    _name = 'presenly.saas.leave'
    _inherit = ['presenly.saas.leave', 'presenly.saas.submission.hr.mixin']


class PresenlySaasOvertime(models.Model):
    _name = 'presenly.saas.overtime'
    _inherit = ['presenly.saas.overtime', 'presenly.saas.submission.hr.mixin']


class PresenlySaasMedicalCertificate(models.Model):
    _name = 'presenly.saas.medical.certificate'
    _inherit = [
        'presenly.saas.medical.certificate',
        'presenly.saas.submission.hr.mixin',
    ]


class PresenlySaasAttendanceCorrection(models.Model):
    _name = 'presenly.saas.attendance.correction'
    _inherit = [
        'presenly.saas.attendance.correction',
        'presenly.saas.submission.hr.mixin',
    ]


class PresenlySaasShiftSwap(models.Model):
    _name = 'presenly.saas.shift.swap'
    _inherit = ['presenly.saas.shift.swap', 'presenly.saas.submission.hr.mixin']
