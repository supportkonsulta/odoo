import logging

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PresenlySaasMirrorMixin(models.AbstractModel):
    """Dasar untuk cermin resource referensi dari Presenly SaaS.

    Resource referensi (lokasi kerja, shift, mode absen, hari libur, setup hari
    kerja) tidak punya periode: isinya adalah keadaan terkini. Karena itu
    penarikannya **mengganti seluruh isi** untuk company tersebut, bukan
    menumpuk. Tabelnya kecil, jadi ini sederhana dan selalu konsisten dengan
    server.

    Hal yang sama tidak berlaku untuk data berperiode (log presensi, rekap),
    yang mengganti per rentang tanggal saja.

    Setiap model yang memakai mixin ini mengisi:

    - `_mirror_resource`: nama resource di API, mis. `work-locations`
    - `_mirror_values(company, row)`: petakan satu baris API ke kolom model
    """

    _name = 'presenly.saas.mirror.mixin'
    _description = 'Presenly SaaS Mirror Mixin'

    _mirror_resource = None

    # Diisi oleh cermin berperiode (pengajuan). Kalau kosong, model dianggap
    # resource referensi dan penarikannya mengganti seluruh isi.
    _mirror_date_field = None

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
        index=True,
    )
    # `external_id` menyimpan id baris di sisi Presenly dan hanya dipakai
    # sinkronisasi untuk mencocokkan. Sengaja tanpa label yang enak dibaca dan
    # tanpa tampilan: bagi pengguna itu angka yang tidak bisa dipakai untuk apa pun.
    external_id = fields.Integer(
        string='Presenly Row ID',
        required=True,
        index=True,
        # `aggregator=False` membuat Odoo TIDAK menawarkannya sebagai ukuran
        # pivot. Tanpa ini, seluruh kolom id mentah muncul di daftar "Measures"
        # pada view pivot: angka yang tidak bisa dipakai untuk apa pun, tapi ikut
        # terdaftar di antarmuka pengguna.
        aggregator=False,
        help='Row id on the Presenly side. Used by the sync to match records. Not '
             'shown in any view: for a user it is a number that cannot be used for '
             'anything.',
    )
    fetched_at = fields.Datetime(string='Last Pulled', readonly=True, index=True)
    source_created_at = fields.Datetime(string='Created on SaaS')
    source_updated_at = fields.Datetime(string='Updated on SaaS')

    # Field bersarang dari API disimpan apa adanya, supaya tidak ada informasi
    # yang hilang hanya karena belum dibuatkan kolomnya.
    raw_payload = fields.Json(string='Raw Payload')

    # Relasi ke cermin lokasinya, bukan hanya id. Dipakai menyaring per lokasi,
    # dan menjadi kunci untuk menautkan ke `hr.work.location` (di modul yang
    # memang punya `hr`).
    tenant_location_id = fields.Many2one(
        'presenly.saas.work.location',
        string='Work Location (mirror)',
        index=True,
        ondelete='set null',
        readonly=True,
        help='The mirrored work location this row happened at. Kept as a '
             'relation, not only as an id, so rows can be filtered and grouped '
             'per location without comparing names.',
    )

    _mirror_company_external_uniq = models.Constraint(
        'unique(company_id, external_id)',
        'A row may only be mirrored once per company.',
    )

    @api.model
    def _mirror_values(self, company, row):
        raise NotImplementedError(
            'Model %s harus mengisi _mirror_values().' % self._name
        )

    @api.model
    def _mirror_replace(self, company, rows):
        """Ganti seluruh isi cermin untuk company ini.

        Seluruh baris dipetakan lebih dulu, baru tabel lama dihapus. Dengan
        begitu kegagalan di tengah pemetaan tidak meninggalkan cermin kosong.
        """
        return self._mirror_write(company, rows, domain=[('company_id', '=', company.id)])

    @api.model
    def _mirror_replace_range(self, company, rows, date_from, date_to):
        """Ganti cermin hanya untuk rentang tanggal tertentu.

        Dipakai data berperiode seperti pengajuan cuti atau lembur: menarik
        September tidak boleh menghapus isi Agustus. Baris di luar rentang
        dibiarkan apa adanya.

        Baris **tanpa tanggal** diperlakukan sebagai bagian dari rentang, tetapi
        hanya kalau server memang mengirimkannya. Sebuah baris yang tidak punya
        tanggal tidak bisa dikatakan berada di luar rentang mana pun, jadi
        membiarkannya di luar berarti ia tidak pernah ikut diganti — dan ketika
        pengajuannya dihapus di aplikasi, salinannya tertinggal selamanya.

        Syaratnya "kalau server mengirimkannya" dan bukan sekadar selalu: server
        yang belum menyertakan baris tanpa tanggal akan kehilangan baris itu
        kalau di sini ia dihapus tanpa penggantinya. Yang dipakai sebagai tanda
        adalah isi tarikannya sendiri, bukan versi server.
        """
        if not self._mirror_date_field:
            raise UserError(
                'Model %s belum mengisi _mirror_date_field, jadi tidak bisa '
                'mengganti per rentang.' % self._name
            )
        medan = self._mirror_date_field
        domain = [('company_id', '=', company.id)]
        ada_kosong = any(
            not (self._mirror_values(company, row) or {}).get(medan)
            for row in rows
        )
        if ada_kosong:
            # (tanggal di dalam rentang) ATAU (tanggal kosong)
            domain += [
                '|',
                '&', (medan, '>=', date_from), (medan, '<=', date_to),
                (medan, '=', False),
            ]
        else:
            domain += [(medan, '>=', date_from), (medan, '<=', date_to)]
        return self._mirror_write(company, rows, domain=domain)

    def unlink(self):
        """Hapus lampiran bersama barisnya, tanpa menabrak lampiran yang sudah hilang.

        Lampiran yang menunjuk baris ini **sudah** ikut terhapus oleh Odoo:
        `BaseModel.unlink` membuang `ir.attachment` yang `res_model`/`res_id`-nya
        menunjuk baris yang dihapus. Karena itu di sini hanya sisa yang benar-
        benar masih ada yang perlu dibuang.

        Penyaring `exists()` bukan kehati-hatian berlebihan: memanggil `unlink`
        pada recordset yang barisnya sudah hilang melempar `MissingError`, dan
        galat itu membatalkan **seluruh** penarikan — bukan sekadar
        meninggalkan lampiran yatim. Akibatnya data yang sudah dihapus di
        Presenly tidak pernah ikut hilang di sini, dan tombol tarik manual gagal
        dengan pesan yang tidak menyebut sebabnya.
        """
        lampiran = self.mapped('attachment_id') if 'attachment_id' in self._fields else self.browse()
        hasil = super().unlink()
        sisa = lampiran.exists()
        if sisa:
            sisa.unlink()
        return hasil

    @api.model
    def _mirror_upsert(self, company, rows):
        """Tambahkan atau perbarui baris, **tanpa menghapus apa pun**.

        Dipakai penarikan tambahan, yang hanya mengambil baris yang berubah sejak
        penanda waktu terakhir. Karena itu ia tidak boleh menghapus seperti
        penggantian per rentang: baris yang tidak ikut terambil bukan baris basi,
        melainkan baris yang memang tidak berubah.

        Pencocokannya memakai `external_id`, penanda yang sama yang dipakai
        sinkronisasi untuk mengenali baris — dan yang dijaga constraint
        `(company_id, external_id)`.
        """
        Mirror = self.sudo()
        values_list = []
        for row in rows:
            values = self._mirror_values(company, row)
            if values:
                values_list.append(values)
        if not values_list:
            return 0

        existing = {
            baris.external_id: baris
            for baris in Mirror.search([
                ('company_id', '=', company.id),
                ('external_id', 'in', [values['external_id'] for values in values_list]),
            ])
        }

        ditulis = 0
        for values in values_list:
            baris = existing.get(values['external_id'])
            if baris:
                baris.write(values)
            else:
                Mirror.create(values)
            ditulis += 1
        self._mirror_fill_branches(company)
        return ditulis

    @api.model
    def _mirror_fill_location_ids_from_payload(self, company):
        """Isi id lokasi baris lama dari payload yang tersimpan.

        Dipakai migrasi, bukan penarikan: baris yang ditarik sebelum kolom
        `location_id` ada tidak punya id lokasinya, padahal payloadnya disimpan
        utuh. Mengisinya dari sana berarti tidak perlu memanggil API sama sekali.

        Model yang tidak punya kolom itu dilewati tanpa biaya. Mengembalikan
        jumlah baris yang diisi.
        """
        if 'location_id' not in self._fields or 'raw_payload' not in self._fields:
            return 0
        baris = self.sudo().search([
            ('company_id', '=', company.id),
            ('location_id', '=', 0),
            ('raw_payload', '!=', False),
        ])
        diisi = 0
        for record in baris:
            lokasi = (record.raw_payload or {}).get('location')
            if not isinstance(lokasi, dict) or not lokasi.get('id'):
                continue
            record.sudo().write({'location_id': int(lokasi['id'])})
            diisi += 1
        return diisi

    @staticmethod
    def _payload_client(record):
        """Klien dari payload, bila server mengirimnya.

        Sejak server menyertakan `location.internal_company` pada pengajuan,
        kliennya bisa dibaca langsung dari sana. Itu lebih pasti daripada
        menurunkannya dari cermin lokasi, yang bisa belum tersegarkan, jadi ia
        didahulukan. Bentuk yang tidak terduga diabaikan, bukan ditebak.
        """
        payload = record.raw_payload
        if not isinstance(payload, dict):
            return {}
        lokasi = payload.get('location')
        if not isinstance(lokasi, dict):
            return {}
        klien = lokasi.get('internal_company')
        if not isinstance(klien, dict) or not klien.get('id'):
            return {}
        return {'id': int(klien['id']), 'name': klien.get('name') or False}

    # Catatan: hook `_mirror_fill_links` sengaja TIDAK didefinisikan di sini,
    # melainkan hanya di `presenly_saas_hr`. Definisi kosong di modul ini akan
    # muncul lebih dulu di urutan warisan model, dan menutupi definisi aslinya —
    # persis yang terjadi saat ia masih ada di sini.

    @api.model
    def _mirror_fill_branches(self, company):
        """Isi turunan baris cermin: cabang, lokasi, dan tautan native.

        Dua bagian, dengan sengaja dipisah:

        1. **kolom cabang**, hanya untuk model yang memilikinya (cermin
           pengajuan). Kliennya dibaca dari dua tempat, berurutan: dari payload
           (`location.internal_company`) bila server mengirimnya, karena itu yang
           paling pasti; kalau tidak, diturunkan dari cermin lokasinya lewat id
           lokasi, bukan lewat namanya.
        2. **tautan native** (`hr.employee`, `hr.work.location`), lewat hook yang
           diisi modul pemilik `hr`. Bagian ini dipanggil untuk semua model, dan
           tidak bergantung pada kolom cabang.

        Hanya kolom yang masih kosong yang diisi, dan itu disengaja: sebuah
        pengajuan adalah catatan masa lalu, jadi kalau lokasinya suatu saat
        berpindah klien, mengisi ulang akan menulis kembali sejarahnya.
        """
        diisi = 0
        if 'tenant_client_name' in self._fields and 'location_id' in self._fields:
            diisi = self._mirror_fill_branch_columns(company)
        # Dipanggil hanya bila ada yang mendefinisikannya, yaitu modul pemilik `hr`.
        fill_links = getattr(self, '_mirror_fill_links', None)
        if fill_links:
            fill_links(company)
        return diisi

    @api.model
    def _mirror_fill_branch_columns(self, company):
        """Bagian kolom cabang, dan lokasinya, untuk satu perusahaan."""
        ada_perusahaan = 'tenant_client_company_id' in self._fields
        # Baris dicari bila salah satu kolom turunannya masih kosong: baris lama
        # bisa sudah punya cabangnya tetapi belum punya perusahaannya atau
        # tautan lokasinya.
        domain = [
            ('company_id', '=', company.id),
            ('location_id', '!=', 0),
            '|', '|', ('tenant_client_name', '=', False),
            ('tenant_location_id', '=', False),
        ]
        if ada_perusahaan:
            domain += [('tenant_client_company_id', '=', False)]
        pending = self.sudo().search(domain)
        if not pending:
            return 0

        peta = {
            lokasi.external_id: lokasi
            for lokasi in self.env['presenly.saas.work.location'].sudo().search([
                ('company_id', '=', company.id),
                ('external_id', 'in', pending.mapped('location_id')),
            ])
        }

        # Klien yang muncul, entah dari payload atau dari cermin lokasinya.
        klien_ids = set()
        for baris in pending:
            klien = self._payload_client(baris)
            if klien.get('id'):
                klien_ids.add(klien['id'])
                continue
            lokasi = peta.get(baris.location_id)
            if lokasi and lokasi.internal_company_id:
                klien_ids.add(lokasi.internal_company_id)
        # Perusahaan cabangnya dicari sekali untuk semua klien itu, bukan sekali
        # per baris.
        perusahaan = {}
        if ada_perusahaan and klien_ids:
            perusahaan = {
                baris.presenly_client_id: baris
                for baris in self.env['res.company'].sudo().search([
                    ('presenly_client_id', 'in', sorted(klien_ids)),
                ])
            }

        diisi = 0
        for baris in pending:
            lokasi = peta.get(baris.location_id)
            klien = self._payload_client(baris)
            if not lokasi and not klien:
                # Lokasinya belum tercermin dan payloadnya tidak membawa kliennya:
                # dilaporkan di bawah, tidak ditebak.
                continue
            klien_id = klien.get('id') or (lokasi.internal_company_id if lokasi else 0)
            klien_nama = klien.get('name') or (
                lokasi.internal_company_name if lokasi else False
            )
            nilai = {}
            if not baris.tenant_client_id:
                nilai['tenant_client_id'] = klien_id or 0
            if not baris.tenant_client_name:
                nilai['tenant_client_name'] = klien_nama or False
            if not baris.tenant_location_id and lokasi:
                nilai['tenant_location_id'] = lokasi.id
            if ada_perusahaan and not baris.tenant_client_company_id and klien_id:
                cabang = perusahaan.get(klien_id)
                if cabang:
                    nilai['tenant_client_company_id'] = cabang.id
            if not nilai:
                continue
            baris.write(nilai)
            diisi += 1

        if diisi < len(pending):
            # Dilaporkan, tidak ditebak: cabang yang salah lebih berbahaya daripada
            # cabang yang kosong, karena yang salah tidak terlihat.
            _logger.info(
                'Presenly SaaS: %s dari %s baris %s belum punya cabang karena '
                'lokasinya belum tercermin dan payloadnya tidak membawanya.',
                len(pending) - diisi, len(pending), self._name,
            )
        return diisi

    @api.model
    def _mirror_write(self, company, rows, domain):
        """Petakan semua baris, hapus yang lama pada `domain`, lalu buat baru.

        Penghapusan dan penulisannya dijadikan satu savepoint dengan sengaja.
        Urutannya memang hapus dulu, baru tulis — baris lama memakai
        `external_id` yang sama, jadi menulis lebih dulu akan menabrak
        constraint-nya. Tanpa savepoint, kegagalan di tengah (galat Python
        sebelum penulisan sempat berjalan) meninggalkan penghapusan yang sudah
        jadi, dan transaksi yang akhirnya di-commit menyimpan kehilangan itu:
        barisnya hilang tanpa penggantinya, tanpa satu pun catatan gagal.
        """
        Mirror = self.sudo()
        values_list = []
        for row in rows:
            values = self._mirror_values(company, row)
            if values:
                values_list.append(values)

        with self.env.cr.savepoint():
            stale = Mirror.search(domain)
            if stale:
                stale.unlink()

            if values_list:
                Mirror.create(values_list)
        # Cabang diturunkan setelah barisnya ada, dalam satu langkah untuk semua
        # baris: satu pencarian per tarikan, bukan satu per baris.
        self._mirror_fill_branches(company)
        return len(values_list)

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None,
                        count_limit=None):
        """Segarkan cermin sebelum daftarnya dibaca.

        Dipasang di mixin yang diwarisi hampir seluruh cermin. Yang memicu hanya
        pembacaan daftar: pivot, grafik, dan laporan tidak menyentuh jaringan.

        Model yang tidak mewarisi mixin ini — log presensi dan rekap, yang punya
        radas penulisan sendiri — memasang penimpaan yang sama dan memanggil
        `_refresh_from_page()` yang sama.
        """
        # Hanya halaman pertama. Menggulir, mengurutkan ulang, dan mencari juga
        # memanggil metode ini; tanpa syarat ini satu kali membuka daftar yang
        # panjang bisa memicu belasan penarikan.
        if not offset:
            self.env['presenly.saas.config']._refresh_from_page(self._mirror_resource)
        return super().web_search_read(
            domain, specification, offset=offset, limit=limit, order=order,
            count_limit=count_limit,
        )

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None,
                    **read_kwargs):
        """Segarkan cermin referensi sebelum kalender membacanya.

        Kalender memakai `search_read`, bukan `web_search_read` yang dipakai
        daftar. Tanpa penimpaan ini, halaman kalender — Public Holidays — hanya
        segar saat cron kebetulan berjalan.

        Hanya cermin referensi yang memicunya: yang berperiode sudah punya jalur
        sendiri di `web_search_read`, dan `search_read` juga dipakai hal lain
        yang tidak sedang membuka halaman.
        """
        config = self.env['presenly.saas.config']
        if self._mirror_resource in config._reference_resource_names():
            config._refresh_from_page(self._mirror_resource)
        return super().search_read(
            domain=domain, fields=fields, offset=offset, limit=limit, order=order,
            **read_kwargs,
        )
    @api.depends(
        'approval_has_workflow',
        'approval_current_level',
        'approval_step_ids.level',
        'approval_step_ids.approver_label',
    )
    def _compute_approval_waiting_for(self):
        for request in self:
            if not request.approval_has_workflow or not request.approval_current_level:
                request.approval_waiting_for = False
                continue
            langkah = request.approval_step_ids.filtered(
                lambda step: step.level == request.approval_current_level
            )
            request.approval_waiting_for = langkah[:1].approver_label or False
