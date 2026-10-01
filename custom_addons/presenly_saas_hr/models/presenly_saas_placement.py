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

    # ------------------------------------------------------------------
    # Cabang, dan akses perusahaan bagi pengguna
    # ------------------------------------------------------------------
    def _klien_dari_penempatan(self, rows):
        """Perusahaan cabang per nopeg, dari penempatan yang berlaku hari ini.

        Yang dihitung hanya penempatan yang aktif, sudah mulai, dan belum
        berakhir. Penempatan yang belum mulai tidak memberi akses lebih awal,
        dan penempatan yang sudah berakhir tidak memberi akses lagi.
        """
        hari_ini = fields.Date.to_string(fields.Date.context_today(self))
        klien_ids = {
            int(row['internal_company']['id'])
            for row in rows
            if isinstance(row.get('internal_company'), dict)
            and row['internal_company'].get('id')
        }
        peta = {}
        if klien_ids:
            for perusahaan in self.env['res.company'].sudo().search(
                    [('presenly_client_id', 'in', list(klien_ids))]):
                peta[perusahaan.presenly_client_id] = perusahaan

        per_pegawai = {}
        for row in rows:
            pegawai = row.get('employee') if isinstance(row.get('employee'), dict) else {}
            nopeg = pegawai.get('nopeg')
            if not nopeg:
                continue
            if row.get('status') and row['status'] != 'active':
                continue
            mulai = str(row.get('valid_from') or '')[:10]
            if mulai and mulai > hari_ini:
                continue
            sampai = str(row.get('valid_until') or '')[:10]
            if sampai and sampai < hari_ini:
                continue
            klien = row.get('internal_company') if isinstance(row.get('internal_company'), dict) else {}
            perusahaan = peta.get(int(klien['id'])) if klien.get('id') else None
            if perusahaan:
                per_pegawai.setdefault(nopeg, set()).add(perusahaan.id)
        return per_pegawai

    def _pegawai_dari_nopeg(self, nopeg):
        """`hr.employee` untuk satu nopeg, dibatasi perusahaan integrasi ini."""
        cermin = self.env['presenly.saas.employee'].sudo().search([
            ('nopeg', '=', nopeg),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        return cermin.hr_employee_id

    def _apply_branches(self, rows, ringkasan):
        """Isi daftar cabang tiap pegawai, dan beri akses perusahaannya.

        Daftar cabangnya adalah keadaan **sekarang**: penempatan yang berakhir
        keluar dari daftar. Akses perusahaannya tidak ikut dicabut, dan itu
        keputusan pemilik: yang sudah diberikan dibiarkan, supaya tidak ada yang
        kehilangan perusahaan di tengah pekerjaan tanpa diminta.
        """
        per_pegawai = self._klien_dari_penempatan(rows)
        for nopeg, perusahaan_ids in per_pegawai.items():
            hr = self._pegawai_dari_nopeg(nopeg)
            if not hr:
                continue
            if set(hr.presenly_client_ids.ids) != perusahaan_ids:
                hr.with_context(presenly_skip_push=True).write({
                    'presenly_client_ids': [(6, 0, sorted(perusahaan_ids))],
                })
                ringkasan['branches'] += 1
            ringkasan['access_granted'] += hr._presenly_grant_branch_access()

        # Pegawai yang penempatannya sudah tidak ada: daftar cabangnya
        # dikosongkan, karena daftar itu menjawab "sekarang di cabang mana".
        # Akses perusahaannya sengaja tidak ikut dicabut.
        tertinggal = self.env['hr.employee'].sudo().search([
            ('presenly_saas_config_id', '=', self.id),
            ('presenly_client_ids', '!=', False),
        ])
        for hr in tertinggal:
            if hr.presenly_nopeg and hr.presenly_nopeg in per_pegawai:
                continue
            hr.with_context(presenly_skip_push=True).write(
                {'presenly_client_ids': [(5,)]}
            )
            ringkasan['branches_cleared'] += 1
        return ringkasan

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
            rows, meta, _pages = self._fetch_pages(
                lambda params, _client=self._client().get_resource:
                    _client('placements', params),
                {'limit': 500},
            )
        except SaasClientError as exc:
            self._log_pull(PENEMPATAN_PATH, False, exc, started)
            return {}, redact(exc, self.api_key)

        # Tarikan yang terpotong tidak boleh dipakai untuk menyimpulkan bahwa
        # penempatan seseorang sudah tidak ada: yang tidak terlihat bisa saja
        # hanya belum ikut halaman, dan mengosongkan lokasinya karena itu
        # membuang setelan yang sah.
        terpotong = bool(meta.get('total')) and len(rows) < int(meta['total'])

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
                     'unknown_location': 0, 'conflicts': []}
        for nopeg, (_mulai, row) in terpilih.items():
            mirror = Mirror.search([('nopeg', '=', nopeg)], limit=1)
            hr = mirror.hr_employee_id
            if not hr:
                ringkasan['unknown_employee'] += 1
                continue

            nilai = {}
            klien = row.get('internal_company') if isinstance(row.get('internal_company'), dict) else {}
            perusahaan = Perusahaan.browse()
            if klien and klien.get('id'):
                perusahaan = Perusahaan.search(
                    [('presenly_client_id', '=', int(klien['id']))], limit=1
                )
            if perusahaan:
                nilai['presenly_client_id'] = perusahaan.presenly_client_id
                nilai['presenly_client_name'] = perusahaan.name
            elif klien and klien.get('id'):
                # Klien yang belum ada sebagai perusahaan Odoo dihitung, bukan
                # ditebak. Mengisinya dengan perusahaan utama akan membuat
                # cabangnya salah, dan salahnya tidak terlihat.
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

            if hr.presenly_saas_config_id != self:
                nilai['presenly_saas_config_id'] = self.id
            # Perusahaan pegawai tetap milik integrasi, bukan kliennya — sama
            # seperti yang dilakukan tarikan pegawai, supaya keduanya tidak
            # berebut kolom yang sama.
            if self.company_id and hr.company_id != self.company_id:
                nilai['company_id'] = self.company_id.id

            # Bentrok: nilainya sudah diubah orang di Odoo sejak pemeriksaan
            # terakhir, dan Presenly sekarang mengirim nilai lain. Yang di Odoo
            # akan tertimpa, jadi dilaporkan — sama seperti kolom bersama di
            # sinkronisasi pegawai. Tanpa ini, suntingan lokasi kerja atau
            # perusahaan hilang tanpa satu pun catatan.
            snapshot = hr.presenly_synced_values or {}
            for kolom, kunci in (
                ('presenly_client_id', 'placement_client_id'),
                ('work_location_id', 'placement_work_location_id'),
            ):
                if kolom not in nilai:
                    continue
                dasar = snapshot.get(kunci)
                sekarang = self.env['presenly.saas.employee']._nilai_banding(hr[kolom])
                if dasar and sekarang and dasar != sekarang:
                    ringkasan['conflicts'].append(
                        _('%(name)s (nopeg %(nopeg)s): %(field)s was changed in Odoo '
                          'and is being replaced by the placement value.',
                          name=hr.name or nopeg, nopeg=nopeg, field=kolom)
                    )

            # Pembanding yang sama dengan sinkronisasi pegawai: sebagian kolom di
            # sini relasi (`work_location_id`), sebagian angka biasa
            # (`presenly_client_id`), dan `hr[k].id` gagal untuk yang kedua.
            beda = self.env['presenly.saas.employee']._beda_nilai
            berubah = {k: v for k, v in nilai.items() if beda(hr[k], v)}
            if berubah:
                # Nilai yang baru diterapkan dicatat, supaya pemeriksaan berikutnya
                # bisa membedakan "diubah orang" dari "memang belum pernah diisi".
                snapshot_baru = dict(
                    snapshot,
                    placement_client_id=nilai.get('presenly_client_id', hr.presenly_client_id),
                    placement_work_location_id=nilai.get(
                        'work_location_id', hr.work_location_id.id or False
                    ),
                )
                hr.with_context(presenly_skip_push=True).write(
                    dict(berubah, presenly_synced_values=snapshot_baru)
                )
                ringkasan['applied'] += 1
            else:
                ringkasan['unchanged'] += 1

        # Daftar cabang tiap pegawai, dari SELURUH penempatannya. Penempatan
        # utama hanya satu per pegawai, sedangkan cabangnya bisa beberapa: satu
        # baris `placements` per pegawai dan klien.
        #
        # Tarikan yang terpotong melewatinya: daftar yang belum lengkap akan
        # menghapus cabang yang sah, dan itu justru yang tidak boleh terjadi.
        ringkasan['branches'] = 0
        ringkasan['branches_cleared'] = 0
        ringkasan['access_granted'] = 0
        if not terpotong:
            self._apply_branches(rows, ringkasan)
        else:
            ringkasan['branches_truncated'] = True

        # Penempatan yang sudah tidak ada lagi: lokasi kerja yang dulu dipasang
        # dikembalikan, bukan dibiarkan menunjuk tempat yang bukan penempatan
        # orangnya lagi.
        #
        # Yang dikosongkan hanya nilai yang **masih sama dengan yang dipasang**.
        # Kalau sudah diubah orang di Odoo, perubahan itulah yang dipertahankan,
        # dan keadaannya dilaporkan — bukan dihilangkan tanpa catatan.
        #
        # Tarikan yang terpotong melewatinya sama sekali: daftar yang belum
        # lengkap bukan bukti bahwa penempatannya hilang.
        ringkasan['cleared'] = 0
        ringkasan['truncated'] = terpotong
        Pegawai = self.env['hr.employee'].sudo().with_context(active_test=False)
        if terpotong:
            kandidat = Pegawai.browse()
            _logger.warning(
                'Presenly SaaS: tarikan penempatan terpotong (%s dari %s baris), '
                'jadi lokasi kerja yang penempatannya tidak terlihat dibiarkan.',
                len(rows), meta.get('total'),
            )
        else:
            kandidat = Pegawai.search([('presenly_saas_config_id', '=', self.id)])
        for hr in kandidat:
            if not hr.presenly_nopeg or hr.presenly_nopeg in terpilih:
                continue
            snapshot = hr.presenly_synced_values or {}
            dipasang = snapshot.get('placement_work_location_id')
            if not dipasang:
                continue
            if (hr.work_location_id.id or False) != dipasang:
                ringkasan['conflicts'].append(
                    _('%(name)s (nopeg %(nopeg)s): the placement is gone, but the '
                      'work location was changed in Odoo, so it was left as it is.',
                      name=hr.name or hr.presenly_nopeg, nopeg=hr.presenly_nopeg)
                )
                continue
            hr.with_context(presenly_skip_push=True).write({
                'work_location_id': False,
                'presenly_synced_values': dict(snapshot, placement_work_location_id=False),
            })
            ringkasan['cleared'] += 1

        if ringkasan['conflicts']:
            _logger.warning(
                'Presenly SaaS: %s penempatan menimpa nilai yang sudah diubah di '
                'Odoo (%s).', len(ringkasan['conflicts']), '; '.join(ringkasan['conflicts'][:3]),
            )
        self._log_pull(PENEMPATAN_PATH, True, None, started)
        _logger.info(
            'Presenly SaaS: penempatan pegawai diterapkan (%s diperbarui, %s sama, '
            '%s lokasi dikembalikan, %s dilewati, %s pegawai/perusahaan/lokasi tak '
            'dikenal).',
            ringkasan['applied'], ringkasan['unchanged'], ringkasan['cleared'],
            ringkasan['skipped'],
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
