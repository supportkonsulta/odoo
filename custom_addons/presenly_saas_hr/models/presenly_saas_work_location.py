"""Lokasi kerja Presenly → `hr.work.location` bawaan Odoo.

Presenly menyimpan setup lokasi (multi lokasi per klien) beserta geofence-nya:
koordinat pusat dan radius yang diizinkan. Odoo punya model native untuk lokasi
kerja, `hr.work.location`, tetapi model itu **tidak punya koordinat maupun
radius** — ia menyimpan nama, perusahaan, tipe, dan alamat (`res.partner`).

Karena itu ada dua lapis:

1. **`res.partner`** untuk alamatnya. `hr.work.location` mewajibkan `address_id`,
   sedangkan Presenly mengirim alamat sebagai teks bebas, jadi yang bisa diisi
   hanya nama partner dan `street`-nya.
2. **`hr.work.location`** untuk lokasinya, ditambah field `presenly_*` untuk
   geofence. Ini melanggar aturan lama modul ("tidak mewarisi model bisnis
   native"), dan pelanggarannya disengaja: aturan itu dibuat supaya presensi tidak
   menyeret Odoo ke ranah HR, sedangkan di sini yang diminta justru integrasi
   native. Semua field tambahannya berawalan `presenly_`, jadi tidak bertabrakan
   dengan field Odoo.

Cermin `presenly.saas.work.location` tetap ada dan tetap menjadi sumber data
mentah; yang ditambahkan di sini adalah pasangan native-nya.
"""

import logging
from functools import partial

from odoo import _, api, fields, models

from odoo.addons.presenly_saas.models.presenly_saas_config import redact
from odoo.addons.presenly_saas.services.saas_client import SaasClientError

_logger = logging.getLogger(__name__)

LOKASI_PATH = '/api/external/v1/work-locations'


class ResPartner(models.Model):
    """Alamat lokasi kerja, ditandai id lokasinya di Presenly."""

    _inherit = 'res.partner'

    presenly_location_id = fields.Integer(
        string='Presenly Work Location ID',
        index=True,
        copy=False,
        aggregator=False,
        help='Work location id on the Presenly side. Used by the sync to reuse '
             'the same address instead of creating a duplicate.',
    )


class HrWorkLocation(models.Model):
    """Lokasi kerja native, ditambah geofence yang tidak dimiliki Odoo."""

    _inherit = 'hr.work.location'

    presenly_external_id = fields.Integer(
        string='Presenly Location ID',
        index=True,
        copy=False,
        aggregator=False,
    )
    presenly_latitude = fields.Float(string='Latitude', digits=(10, 7), aggregator=False)
    presenly_longitude = fields.Float(string='Longitude', digits=(10, 7), aggregator=False)
    presenly_radius_meters = fields.Integer(
        string='Allowed Radius (m)',
        help='Radius the server allows around this location. Odoo itself has no '
             'such field, so it is kept here to stay next to the location it '
             'belongs to.',
    )
    presenly_timezone = fields.Char(string='Timezone')
    presenly_attendance_type = fields.Char(string='Attendance Type')
    presenly_synced_at = fields.Datetime(string='Synced from Presenly At', readonly=True)
    presenly_saas_config_id = fields.Many2one(
        'presenly.saas.config',
        string='Presenly Connection',
        readonly=True,
        copy=False,
        ondelete='set null',
        help='The configuration that owns this location. Recorded on first '
             'successful contact, so later write-backs go to the same Presenly '
             'tenant even when several connections are active.',
    )

    _presenly_location_uniq = models.Constraint(
        'unique(presenly_external_id)',
        'One work location may only mirror one Presenly location.',
    )

    # ------------------------------------------------------------------
    # Kirim balik saat disunting di Odoo
    #
    # Arah ini mati secara bawaan (`push_work_locations`), karena lokasi kerja
    # punya satu sumber kebenaran yang jelas: aplikasi. Nyalakan hanya bila
    # operator memang mengelola lokasi dari Odoo.
    # ------------------------------------------------------------------
    PRESENLY_PUSH_FIELDS = {
        'name': 'name',
        'presenly_latitude': 'latitude',
        'presenly_longitude': 'longitude',
        'presenly_radius_meters': 'radius_meters',
        'presenly_timezone': 'timezone',
        'presenly_attendance_type': 'attendance_type',
        'active': 'is_active',
    }

    def write(self, values):
        result = super().write(values)
        disentuh = set(self.PRESENLY_PUSH_FIELDS) & set(values or {})
        if disentuh:
            self._presenly_queue_push(disentuh)
        return result

    def _presenly_queue_push(self, disentuh):
        """Antrekan kirim balik untuk dijalankan SETELAH commit.

        Alasannya sama dengan kirim balik pegawai: transaksi yang batal tidak
        boleh mengirim apa pun, dan panggilan jaringan tidak boleh memperlambat
        atau menggagalkan simpanan pengguna.
        """
        # Penarikan menulis ke model ini juga; tanpa penanda ini setiap tarikan
        # akan mengirim balik apa yang baru saja diterimanya, tanpa henti.
        if self.env.context.get('presenly_skip_push'):
            return
        tertaut = self.filtered('presenly_external_id')
        if not tertaut:
            return
        self.env.cr.postcommit.add(
            partial(tertaut._presenly_push_after_commit, tertaut.ids, sorted(disentuh))
        )

    @api.model
    def _presenly_push_after_commit(self, ids, disentuh):
        """Kirim lokasi yang tersunting ke Presenly. Tidak pernah melempar.

        Dipanggil setelah commit, jadi transaksinya tidak bisa dibatalkan lagi:
        galat di sini hanya bisa dilaporkan, bukan diperbaiki dengan rollback.
        """
        Config = self.env['presenly.saas.config'].sudo()
        for lokasi in self.sudo().browse(ids).exists():
            if not lokasi.presenly_external_id:
                continue
            # Konfigurasi dicari lewat induk: lokasi ini boleh jadi milik
            # perusahaan hasil cermin klien, sedangkan integrasinya dimiliki
            # perusahaan pemasang.
            config = Config._config_for_record(lokasi)
            if not config or not config.push_work_locations:
                continue
            body = lokasi._presenly_push_values(disentuh)
            if not body:
                continue
            try:
                config._client().update_work_location(lokasi.presenly_external_id, body)
            except Exception as exc:  # noqa: BLE001 - tidak boleh sampai ke pengguna
                _logger.warning(
                    'Presenly SaaS: gagal mengirim lokasi kerja %s ke Presenly (%s).',
                    lokasi.display_name, exc,
                )

    def _presenly_push_values(self, disentuh):
        """Isi yang dikirim: hanya kolom yang benar-benar disunting.

        Endpoint tujuannya memang menerapkan semantik ini, jadi mengirim seluruh
        objek justru berbahaya: kolom yang tidak dikirim tidak disentuh di sana.
        """
        body = {}
        for hr_field in disentuh:
            kunci = self.PRESENLY_PUSH_FIELDS[hr_field]
            if hr_field == 'active':
                body[kunci] = bool(self.active)
            elif hr_field == 'presenly_radius_meters':
                body[kunci] = int(self.presenly_radius_meters or 0)
            elif hr_field in ('presenly_latitude', 'presenly_longitude'):
                body[kunci] = float(self[hr_field] or 0.0)
            else:
                body[kunci] = self[hr_field] or False
        return body


class PresenlySaasConfig(models.Model):
    """Penarikan lokasi kerja milik modul bridge."""

    _inherit = 'presenly.saas.config'

    push_work_locations = fields.Boolean(
        string='Send Work Location Edits to Presenly',
        default=False,
        help='Send name, address, and geofence edits made in Odoo back to '
             'Presenly. Off by default: the app stays the source of truth for '
             'locations unless someone decides otherwise.',
    )
    sync_work_locations = fields.Boolean(
        string='Sync Work Locations to Odoo',
        default=False,
        help='Keep a native hr.work.location (and its address) for every Presenly '
             'work location. Off by default: it creates records in Odoo HR, so it '
             'is a decision, not a side effect.',
    )

    def _pull_reference_data(self):
        """Setelah cermin referensi segar, lokasinya disalin ke model native.

        Dipanggil di sini karena lokasi kerja termasuk cermin referensi: seluruh
        isinya diganti setiap penarikan, jadi ini titik paling murah untuk
        menyusul dengan salinan native-nya.
        """
        summary, error = super()._pull_reference_data()
        if error or not self.sync_work_locations:
            return summary, error

        ringkas, error_lokasi = self._pull_work_locations()
        if error_lokasi:
            return summary, error_lokasi
        summary['work_locations'] = ringkas
        return summary, error

    def _pull_work_locations(self):
        """Selaraskan lokasi kerja Presenly ke `res.partner` + `hr.work.location`.

        Mengembalikan ``(ringkasan, error)``. Lokasi yang tidak punya klien
        dikaitkan ke perusahaan koneksi ini, dan keadaannya dihitung supaya
        terlihat — bukan digagalkan.
        """
        self.ensure_one()
        started = fields.Datetime.now()
        try:
            rows, _meta, _pages = self._fetch_pages(
                lambda params, _client=self._client().get_resource:
                    _client('work-locations', params),
                {'limit': 500},
            )
        except SaasClientError as exc:
            self._log_pull(LOKASI_PATH, False, exc, started)
            return {}, redact(exc, self.api_key)

        Partner = self.env['res.partner'].sudo()
        Lokasi = self.env['hr.work.location'].sudo()
        Perusahaan = self.env['res.company'].sudo()

        ringkasan = {'created': 0, 'updated': 0, 'without_client': 0}
        for row in rows:
            if not isinstance(row, dict) or not row.get('id') or not row.get('name'):
                continue
            external_id = int(row['id'])

            klien = row.get('internal_company') if isinstance(row.get('internal_company'), dict) else {}
            client_id = int(klien.get('id') or 0)
            perusahaan = Perusahaan.search([('presenly_client_id', '=', client_id)], limit=1) if client_id else Perusahaan.browse()
            if not perusahaan:
                # Kliennya belum dibuat sebagai perusahaan (setelannya mati, atau
                # kliennya baru). Lokasinya tetap dibuat, di perusahaan koneksi ini.
                perusahaan = self.company_id
                ringkasan['without_client'] += 1

            nilai_partner = {
                'name': row['name'],
                'street': row.get('address') or False,
                'company_id': perusahaan.id,
            }
            partner = Partner.search([('presenly_location_id', '=', external_id)], limit=1)
            if partner:
                partner.write(nilai_partner)
            else:
                partner = Partner.create(dict(nilai_partner, presenly_location_id=external_id))

            nilai_lokasi = {
                'name': row['name'],
                'company_id': perusahaan.id,
                'address_id': partner.id,
                # Presenly hanya punya lokasi bergeofence, jadi tipenya kantor.
                'location_type': 'office',
                'active': bool(row.get('is_active')),
                'presenly_latitude': float(row.get('latitude') or 0.0),
                'presenly_longitude': float(row.get('longitude') or 0.0),
                'presenly_radius_meters': int(row.get('radius_meters') or 0),
                'presenly_timezone': row.get('timezone') or False,
                'presenly_attendance_type': row.get('attendance_type') or False,
                'presenly_synced_at': fields.Datetime.now(),
                # Pemiliknya dicatat di sini, saat konfigurasinya jelas.
                'presenly_saas_config_id': self.id,
            }
            lokasi = Lokasi.search([('presenly_external_id', '=', external_id)], limit=1)
            # Penanda anti-echo: tanpa ini, lokasi yang baru saja ditarik langsung
            # dikirim balik ke Presenly.
            tertutup = Lokasi.with_context(presenly_skip_push=True)
            if lokasi:
                tertutup.browse(lokasi.id).write(nilai_lokasi)
                ringkasan['updated'] += 1
            else:
                tertutup.create(
                    dict(nilai_lokasi, presenly_external_id=external_id, name=row['name'])
                )
                ringkasan['created'] += 1

        self._log_pull(LOKASI_PATH, True, None, started)
        _logger.info(
            'Presenly SaaS: lokasi kerja disalin ke Odoo (%s baru, %s diperbarui, '
            '%s tanpa klien).',
            ringkasan['created'], ringkasan['updated'], ringkasan['without_client'],
        )
        return ringkasan, False
