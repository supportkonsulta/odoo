"""Penempatan pegawai Presenly → perusahaan dan lokasi kerja di `hr.employee`.

Presenly menyimpan penempatan pegawai sebagai data tersendiri: siapa ditempatkan
di klien mana, di lokasi kerja mana, sejak kapan sampai kapan, dan mana yang
utama. Payload pegawai sendiri tidak membawa klien maupun lokasi — keduanya
hanya ada di resource `placements`.

Satu pegawai bisa punya beberapa penempatan sekaligus (`iksg-rangga` punya dua).
`hr.employee` hanya bisa menunjuk satu perusahaan dan satu lokasi kerja, jadi
yang dipakai adalah penempatan yang **utama** dan masih berlaku. Kalau tidak ada
yang utama, tautannya dibiarkan apa adanya dan keadaannya dicatat — menebak di
antara beberapa penempatan akan menghasilkan tautan yang salah tanpa jejak.

Catatan penamaan: resource ini menamai kliennya `internal_company` dan lokasinya
`location`, bukan `tenantClient`/`workLocation` seperti nama asosiasi di sisi
server. Itu sudah diganti oleh fungsi `map` di `ExternalRawDataService.js`, jadi
yang dibaca di sini adalah nama keluaran API-nya.
"""

import logging

from odoo import _, fields, models

from odoo.addons.presenly_saas.models.presenly_saas_config import redact
from odoo.addons.presenly_saas.services.saas_client import SaasClientError

_logger = logging.getLogger(__name__)

PENEMPATAN_PATH = '/api/external/v1/placements'


class PresenlySaasConfig(models.Model):
    """Penerapan penempatan pegawai milik modul bridge."""

    _inherit = 'presenly.saas.config'

    sync_employee_placements = fields.Boolean(
        string='Apply Employee Placements',
        default=False,
        help='Point each employee at the company and work location from their '
             'primary placement in Presenly. Off by default: it rewrites an '
             'employee field users also edit by hand.',
    )

    def _pull_employees(self):
        """Setelah pegawai ditarik, penempatannya diterapkan.

        Dipanggil di sini karena `hr.employee` baru ada setelah tarikan pegawai;
        penempatan menunjuk ke sana lewat nopeg.
        """
        ringkas, error = super()._pull_employees()
        if error or not self.sync_employee_placements:
            return ringkas, error

        ringkas_tempat, error_tempat = self._pull_placements()
        if error_tempat:
            return ringkas, error_tempat
        ringkas['placements'] = ringkas_tempat
        return ringkas, error

    def _pull_placements(self):
        """Terapkan penempatan utama tiap pegawai ke `hr.employee`.

        Mengembalikan ``(ringkasan, error)``. Yang dilewati dihitung beserta
        alasannya, bukan didiamkan.
        """
        self.ensure_one()
        started = fields.Datetime.now()
        try:
            rows, _meta, _pages = self._fetch_pages(
                lambda params, _client=self._client().get_resource:
                    _client('placements', params),
                {'limit': 500},
            )
        except SaasClientError as exc:
            self._log_pull(PENEMPATAN_PATH, False, exc, started)
            return {}, redact(exc, self.api_key)

        Perusahaan = self.env['res.company'].sudo()
        Lokasi = self.env['hr.work.location'].sudo()
        Mirror = self.env['presenly.saas.employee'].sudo()
        hari_ini = fields.Date.context_today(self)

        # Satu pegawai bisa punya beberapa penempatan. Yang dipakai adalah yang
        # utama dan masih berlaku, dan di antara itu yang paling baru mulai.
        terpilih = {}
        dilewati = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            pegawai = row.get('employee') if isinstance(row.get('employee'), dict) else {}
            nopeg = (pegawai or {}).get('nopeg')
            if not nopeg:
                continue
            if row.get('status') and row['status'] != 'active':
                dilewati += 1
                continue
            if not row.get('is_primary'):
                dilewati += 1
                continue
            sampai = row.get('valid_until')
            if sampai and str(sampai)[:10] < fields.Date.to_string(hari_ini):
                dilewati += 1
                continue
            mulai = str(row.get('valid_from') or '')
            sebelumnya = terpilih.get(nopeg)
            if sebelumnya and sebelumnya[0] >= mulai:
                dilewati += 1
                continue
            terpilih[nopeg] = (mulai, row)

        ringkasan = {'applied': 0, 'unchanged': 0, 'skipped': dilewati,
                     'unknown_employee': 0, 'unknown_company': 0,
                     'unknown_location': 0}
        for nopeg, (_mulai, row) in terpilih.items():
            mirror = Mirror.search([('nopeg', '=', nopeg)], limit=1)
            hr = mirror.hr_employee_id
            if not hr:
                ringkasan['unknown_employee'] += 1
                continue

            nilai = {}
            klien = row.get('internal_company') if isinstance(row.get('internal_company'), dict) else {}
            if klien and klien.get('id'):
                perusahaan = Perusahaan.search(
                    [('presenly_client_id', '=', int(klien['id']))], limit=1
                )
                if perusahaan:
                    nilai['company_id'] = perusahaan.id
                else:
                    ringkasan['unknown_company'] += 1

            tempat = row.get('location') if isinstance(row.get('location'), dict) else {}
            if tempat and tempat.get('id'):
                lokasi = Lokasi.search(
                    [('presenly_external_id', '=', int(tempat['id']))], limit=1
                )
                if lokasi:
                    nilai['work_location_id'] = lokasi.id
                else:
                    ringkasan['unknown_location'] += 1

            berubah = {k: v for k, v in nilai.items() if hr[k].id != v}
            if berubah:
                hr.with_context(presenly_skip_push=True).write(berubah)
                ringkasan['applied'] += 1
            else:
                ringkasan['unchanged'] += 1

        self._log_pull(PENEMPATAN_PATH, True, None, started)
        _logger.info(
            'Presenly SaaS: penempatan pegawai diterapkan (%s diperbarui, %s sama, '
            '%s dilewati, %s pegawai/perusahaan/lokasi tak dikenal).',
            ringkasan['applied'], ringkasan['unchanged'], ringkasan['skipped'],
            ringkasan['unknown_employee'] + ringkasan['unknown_company']
            + ringkasan['unknown_location'],
        )
        if ringkasan['unknown_location']:
            # Penyebab yang paling sering: lokasi kerjanya belum disalin ke
            # `hr.work.location` karena setelan itu mati.
            _logger.warning(
                'Presenly SaaS: %s penempatan menunjuk lokasi kerja yang belum ada '
                'di Odoo. Nyalakan "Sync Work Locations to Odoo" lebih dulu.',
                ringkasan['unknown_location'],
            )
        return ringkasan, False
