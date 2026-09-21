import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


def parse_datetime(value):
    """Konversi ISO-8601 dari API menjadi datetime UTC naive."""
    from .presenly_saas_subscription import parse_datetime as _parse
    return _parse(value)


class PresenlySaasAttendanceLog(models.Model):
    """Cermin log presensi dari `GET /v1/presenly/attendance-logs`.

    Ini **cermin**, bukan arsip. Setiap penarikan mengganti baris untuk periode
    yang sama, sehingga tidak menumpuk dan tidak mencampur data basi dengan data
    baru. Field bersarang dari API disimpan pada `raw_payload` supaya tidak ada
    informasi yang hilang, sementara kolom yang dipakai menampilkan diringkas di
    sini.

    Modul ini tidak menyentuh `hr.attendance`. Data ini hanya untuk dilihat dan
    diekspor dari Odoo, sumber kebenarannya tetap Presenly SaaS.
    """

    _name = 'presenly.saas.attendance.log'
    _description = 'Presenly Attendance Log (mirror)'
    _order = 'work_date desc, check_in_time desc, id desc'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
        index=True,
    )
    external_id = fields.Integer(string='ID Sesi', required=True, index=True)
    session_key = fields.Char(index=True)
    work_date = fields.Date(index=True)

    user_id = fields.Integer(string='ID Pegawai (SaaS)')
    employee_name = fields.Char(string='Pegawai')
    employee_nopeg = fields.Char(string='Nopeg')
    project_name = fields.Char(string='Proyek')

    location_id = fields.Integer(string='ID Lokasi (SaaS)')
    location_name = fields.Char(string='Lokasi')
    tenant_client_name = fields.Char(string='Perusahaan Internal')

    shift_id = fields.Integer(string='ID Shift (SaaS)')
    shift_name = fields.Char(string='Shift')

    schedule_id = fields.Integer()
    schedule_segment_id = fields.Integer()
    schedule_source = fields.Char()

    status = fields.Selection(
        [('open', 'Terbuka'), ('closed', 'Selesai'), ('alpha', 'Alpha')],
        string='Status',
    )
    late_minutes = fields.Integer(string='Terlambat (menit)')
    is_overtime = fields.Boolean(string='Sesi Lembur')

    check_in_time = fields.Datetime()
    check_out_time = fields.Datetime()
    check_in_latitude = fields.Float(digits=(10, 7))
    check_in_longitude = fields.Float(digits=(10, 7))
    check_in_distance_meters = fields.Float()
    check_in_allowed_radius_meters = fields.Float()
    check_in_mode_id = fields.Integer()
    check_in_mode_name = fields.Char(string='Mode Masuk')
    check_out_latitude = fields.Float(digits=(10, 7))
    check_out_longitude = fields.Float(digits=(10, 7))
    check_out_distance_meters = fields.Float()
    check_out_allowed_radius_meters = fields.Float()
    check_out_mode_id = fields.Integer()
    check_out_mode_name = fields.Char(string='Mode Keluar')

    source_created_at = fields.Datetime(string='Dibuat di SaaS')
    source_updated_at = fields.Datetime(string='Diubah di SaaS')
    fetched_at = fields.Datetime(readonly=True, index=True)

    # Field bersarang dari API disimpan apa adanya, sehingga tidak ada yang
    # hilang hanya karena belum dibuatkan kolomnya.
    raw_payload = fields.Json(string='Payload Mentah')

    _company_external_uniq = models.Constraint(
        'unique(company_id, external_id)',
        'Satu sesi hanya boleh tercermin sekali per company.',
    )

    @api.depends('employee_name', 'work_date')
    def _compute_display_name(self):
        for log in self:
            log.display_name = '%s - %s' % (log.employee_name or '?', log.work_date or '?')

    # ------------------------------------------------------------------
    # Penarikan
    # ------------------------------------------------------------------
    @api.model
    def _values_from_payload(self, company, row):
        """Petakan satu baris API ke kolom cermin."""
        if not isinstance(row, dict) or not row.get('id'):
            return None

        employee = row.get('employee') if isinstance(row.get('employee'), dict) else {}
        location = row.get('location') if isinstance(row.get('location'), dict) else {}
        shift = row.get('shift') if isinstance(row.get('shift'), dict) else {}
        in_mode = row.get('checkInMode') if isinstance(row.get('checkInMode'), dict) else {}
        out_mode = row.get('checkOutMode') if isinstance(row.get('checkOutMode'), dict) else {}
        tenant_client = location.get('tenantClient') if isinstance(location.get('tenantClient'), dict) else {}

        status = row.get('status')
        if status not in ('open', 'closed', 'alpha'):
            status = False

        return {
            'company_id': company.id,
            'external_id': int(row['id']),
            'session_key': row.get('session_key') or False,
            'work_date': row.get('work_date') or False,
            'user_id': int(row.get('user_id') or 0),
            'employee_name': employee.get('name') or False,
            'employee_nopeg': employee.get('nopeg') or False,
            'project_name': employee.get('project') or False,
            'location_id': int(row.get('location_id') or 0),
            'location_name': location.get('name') or False,
            'tenant_client_name': tenant_client.get('name') or False,
            'shift_id': int(row.get('shift_id') or 0),
            'shift_name': shift.get('shift_name') or False,
            'schedule_id': int(row.get('schedule_id') or 0),
            'schedule_segment_id': int(row.get('schedule_segment_id') or 0),
            'schedule_source': row.get('schedule_source') or False,
            'status': status,
            'late_minutes': int(row.get('late_minutes') or 0),
            'is_overtime': bool(row.get('is_overtime')),
            'check_in_time': parse_datetime(row.get('check_in_time')),
            'check_out_time': parse_datetime(row.get('check_out_time')),
            'check_in_latitude': float(row.get('check_in_latitude') or 0.0),
            'check_in_longitude': float(row.get('check_in_longitude') or 0.0),
            'check_in_distance_meters': float(row.get('check_in_distance_meters') or 0.0),
            'check_in_allowed_radius_meters': float(row.get('check_in_allowed_radius_meters') or 0.0),
            'check_in_mode_id': int(row.get('check_in_mode_id') or 0),
            'check_in_mode_name': in_mode.get('name') or False,
            'check_out_latitude': float(row.get('check_out_latitude') or 0.0),
            'check_out_longitude': float(row.get('check_out_longitude') or 0.0),
            'check_out_distance_meters': float(row.get('check_out_distance_meters') or 0.0),
            'check_out_allowed_radius_meters': float(row.get('check_out_allowed_radius_meters') or 0.0),
            'check_out_mode_id': int(row.get('check_out_mode_id') or 0),
            'check_out_mode_name': out_mode.get('name') or False,
            'source_created_at': parse_datetime(row.get('created_at')),
            'source_updated_at': parse_datetime(row.get('updated_at')),
            'fetched_at': fields.Datetime.now(),
            'raw_payload': row,
        }

    @api.model
    def _replace_scope(self, company, work_date_from, work_date_to):
        """Hapus cermin pada rentang tanggal sebelum menulis hasil tarikan baru.

        Mengganti per rentang, bukan menghapus semuanya, supaya penarikan satu
        bulan tidak menghapus bulan lain yang sudah ditarik sebelumnya.
        """
        domain = [('company_id', '=', company.id)]
        if work_date_from:
            domain.append(('work_date', '>=', work_date_from))
        if work_date_to:
            domain.append(('work_date', '<=', work_date_to))
        stale = self.sudo().search(domain)
        if stale:
            stale.unlink()
        return len(stale)

    @api.model
    def _upsert_rows(self, company, rows):
        Log = self.sudo()
        seen = set()
        written = 0
        for row in rows:
            values = self._values_from_payload(company, row)
            if not values:
                continue
            # Halaman bisa tumpang tindih bila data berubah di antara dua
            # permintaan. Dedupe menjaga jumlah yang dilaporkan tetap benar dan
            # mencegah penulisan berulang pada baris yang sama.
            key = values['external_id']
            if key in seen:
                continue
            seen.add(key)
            existing = Log.search([
                ('company_id', '=', company.id),
                ('external_id', '=', values['external_id']),
            ], limit=1)
            if existing:
                existing.write(values)
            else:
                Log.create(values)
            written += 1
        return written
