"""Rekonsiliasi untuk data yang ditangani modul bridge.

Modul inti membandingkan klien; di sini ditambahkan lokasi kerja dan pegawai,
karena keduanya baru ada setelah modul ini dipasang.

Pegawai bisa dibedakan lebih tajam daripada lokasi. Sinkronisasi pegawai
menyimpan **snapshot** nilai yang terakhir disepakati (`presenly_synced_values`),
sehingga bisa dikatakan dengan pasti apakah sebuah kolom berubah di Odoo, di
Presenly, atau di keduanya. Lokasi tidak punya snapshot, jadi untuk lokasi yang
bisa dikatakan hanya "berbeda" — mana yang lebih baru diserahkan kepada waktu
perubahan yang ditampilkan, bukan kepada tebakan.
"""

import logging

from odoo import _, models

from odoo.addons.presenly_saas.models.presenly_saas_reconciliation import teks

_logger = logging.getLogger(__name__)


class PresenlySaasConfig(models.Model):
    """Pemeriksa tambahan untuk lokasi kerja dan pegawai."""

    _inherit = 'presenly.saas.config'

    # Kolom lokasi yang ada di kedua sisi, berpasangan: (cermin, native).
    PASANGAN_LOKASI = [
        ('name', 'name'),
        ('address', 'address_id.street'),
        ('latitude', 'presenly_latitude'),
        ('longitude', 'presenly_longitude'),
        ('radius_meters', 'presenly_radius_meters'),
        ('timezone', 'presenly_timezone'),
        ('attendance_type', 'presenly_attendance_type'),
        ('is_active', 'active'),
    ]

    def _reconcile_datasets(self):
        """Tambahkan lokasi kerja dan pegawai ke dataset yang diperiksa.

        Datasets digabung dengan milik modul inti, bukan menggantikannya, supaya
        modul lain yang menambah dataset tetap ikut diperiksa.
        """
        return dict(super()._reconcile_datasets(), **{
            'work_location': self._reconcile_work_locations,
            'employee': self._reconcile_employees,
        })

    @staticmethod
    def _nilai_native(native, kolom):
        """Baca satu kolom native, termasuk jalur bertitik seperti `address_id.street`.

        `native['address_id.street']` **tidak** didukung Odoo — saya sempat
        mengira didukung, dan galatnya menelan seluruh dataset lokasi sehingga
        tidak ada satu pun temuan yang muncul. Jalurnya ditelusuri sendiri.
        """
        nilai = native
        for bagian in kolom.split('.'):
            if not nilai:
                return False
            nilai = nilai[bagian]
        return nilai

    # ------------------------------------------------------------------
    # Lokasi kerja
    # ------------------------------------------------------------------
    def _reconcile_work_locations(self, keys):
        """Bandingkan cermin lokasi dengan `hr.work.location`."""
        # Kalau penyalinan ke model native dimatikan, seluruh lokasi akan
        # dilaporkan hilang — dan itu bukan temuan, itu setelan. Jadi datasetnya
        # dilewati, bukan dibanjiri keluhan yang tidak bisa ditindaklanjuti.
        if not self.sync_work_locations:
            return 0

        Cermin = self.env['presenly.saas.work.location'].sudo()
        Lokasi = self.env['hr.work.location'].sudo().with_context(active_test=False)
        jumlah = 0

        for cermin in Cermin.search([]):
            kunci_lokasi = str(cermin.external_id)
            native = Lokasi.search([('presenly_external_id', '=', cermin.external_id)], limit=1)
            if not native:
                self._upsert({
                    'dataset': 'work_location', 'presenly_key': kunci_lokasi,
                    'record_label': cermin.name, 'res_model': 'hr.work.location',
                    'res_id': 0, 'field_name': 'presenly_external_id',
                    'presenly_value': kunci_lokasi, 'odoo_value': '',
                    'nature': 'missing_in_odoo',
                    'presenly_seen_at': cermin.write_date,
                })
                keys.add(('work_location', kunci_lokasi, 'presenly_external_id'))
                jumlah += 1
                continue

            for kolom_cermin, kolom_native in self.PASANGAN_LOKASI:
                nilai_presenly = teks(getattr(cermin, kolom_cermin))
                nilai_odoo = teks(self._nilai_native(native, kolom_native))
                if nilai_presenly == nilai_odoo:
                    continue
                self._upsert({
                    'dataset': 'work_location', 'presenly_key': kunci_lokasi,
                    'record_label': native.name, 'res_model': 'hr.work.location',
                    'res_id': native.id, 'field_name': kolom_cermin,
                    'presenly_value': nilai_presenly, 'odoo_value': nilai_odoo,
                    # Tidak ada snapshot untuk lokasi, jadi tidak ada dasar untuk
                    # mengatakan siapa yang berubah lebih dulu. Yang ditampilkan
                    # waktunya; yang memutuskan manusia.
                    'nature': 'differs',
                    'odoo_changed_at': native.write_date,
                    'presenly_seen_at': cermin.write_date,
                })
                keys.add(('work_location', kunci_lokasi, kolom_cermin))
                jumlah += 1

        # Lokasi native yang mengaku cermin tetapi lokasinya sudah tidak ada.
        terlihat = {cermin.external_id for cermin in Cermin.search([])}
        for native in Lokasi.search([('presenly_external_id', '!=', False)]):
            if native.presenly_external_id in terlihat:
                continue
            kunci_lokasi = str(native.presenly_external_id)
            self._upsert({
                'dataset': 'work_location', 'presenly_key': kunci_lokasi,
                'record_label': native.name, 'res_model': 'hr.work.location',
                'res_id': native.id, 'field_name': 'presenly_external_id',
                'presenly_value': '', 'odoo_value': kunci_lokasi,
                'nature': 'missing_in_presenly', 'odoo_changed_at': native.write_date,
            })
            keys.add(('work_location', kunci_lokasi, 'presenly_external_id'))
            jumlah += 1

        return jumlah

    # ------------------------------------------------------------------
    # Pegawai
    # ------------------------------------------------------------------
    def _reconcile_employees(self, keys):
        """Bandingkan cermin pegawai dengan `hr.employee`.

        Snapshot dipakai untuk memisahkan dua hal yang berbeda artinya:
        "berbeda" dan "berubah di kedua sisi". Yang kedua itulah yang berbahaya —
        sinkronisasi memilih nilai Presenly, dan tanpa laporan ini suntingan Odoo
        hilang tanpa jejak.
        """
        Cermin = self.env['presenly.saas.employee'].sudo()
        jumlah = 0

        for cermin in Cermin.search([('company_id', '=', self.company_id.id)]):
            if not cermin.nopeg:
                continue
            hr = cermin.hr_employee_id
            if not hr:
                self._upsert({
                    'dataset': 'employee', 'presenly_key': cermin.nopeg or str(cermin.id),
                    'record_label': cermin.name or '', 'res_model': 'hr.employee',
                    'res_id': 0, 'field_name': 'hr_employee_id',
                    'presenly_value': cermin.nopeg or '', 'odoo_value': '',
                    'nature': 'missing_in_odoo',
                })
                keys.add(('employee', cermin.nopeg or str(cermin.id), 'hr_employee_id'))
                jumlah += 1
                continue

            sisi_presenly = Cermin._mirror_values_for(cermin, Cermin.SHARED_FIELDS)
            sisi_odoo = Cermin._odoo_values(hr, Cermin.SHARED_FIELDS)
            snapshot = hr.presenly_synced_values or {}

            for kolom in Cermin.SHARED_FIELDS:
                nilai_presenly = teks(sisi_presenly.get(kolom))
                nilai_odoo = teks(sisi_odoo.get(kolom))
                if nilai_presenly == nilai_odoo:
                    continue

                sifat = 'differs'
                if kolom in snapshot:
                    dasar = teks(snapshot[kolom])
                    if dasar != nilai_presenly and dasar != nilai_odoo:
                        sifat = 'both_changed'

                self._upsert({
                    'dataset': 'employee', 'presenly_key': cermin.nopeg,
                    'record_label': hr.name or cermin.name or '', 'res_model': 'hr.employee',
                    'res_id': hr.id, 'field_name': kolom,
                    'presenly_value': nilai_presenly, 'odoo_value': nilai_odoo,
                    'nature': sifat,
                    'odoo_changed_at': hr.write_date,
                    'presenly_seen_at': cermin.write_date,
                })
                keys.add(('employee', cermin.nopeg, kolom))
                jumlah += 1

        return jumlah
