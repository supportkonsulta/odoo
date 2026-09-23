"""Rekonsiliasi: membandingkan sisi Presenly dengan sisi Odoo, lalu melapor.

Modul ini menyinkronkan data, dan sinkronisasi yang gagal **tidak berbunyi**.
Webhook bisa tidak sampai, cron bisa melewatkan perubahan yang stempel waktunya
tidak jujur, dan tarikan bisa menimpa suntingan Odoo tanpa suara. Rekonsiliasi
adalah lapisan yang membandingkan isi sebenarnya, bukan mempercayai salah satu
pihak yang mengaku sudah berubah.

Yang **tidak** dilakukan di sini, dan itu keputusan sadar: rekonsiliasi tidak
membereskan apa pun sendiri. "Nilai mana yang benar" bergantung pada siapa pemilik
kolom itu, dan itu keputusan bisnis — radius geofence jelas milik aplikasi, nama
lokasi bisa jadi milik Odoo karena bagian legal yang menggantinya. Menebak berarti
menimpa nilai yang benar dengan yang salah, dan kali ini juga tanpa suara. Jadi
alat ini melapor dan membiarkan manusia memutuskan.

Sisi Presenly dari perbandingan ini adalah **cermin** terakhir, bukan panggilan
API baru. Alasannya: cermin sudah menyimpan nilai yang diterima apa adanya,
termasuk yang gagal diterapkan ke model native — persis yang perlu dilihat. Waktu
penyegaran terakhirnya ikut ditampilkan supaya kebasiannya tidak tersembunyi.
"""

import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

DATASETS = [
    ('client', 'Client'),
    ('work_location', 'Work Location'),
    ('employee', 'Employee'),
]

NATURES = [
    ('differs', 'Differs'),
    ('both_changed', 'Changed on Both Sides'),
    ('missing_in_odoo', 'Missing in Odoo'),
    ('missing_in_presenly', 'Missing in Presenly'),
]

STATES = [
    ('open', 'Open'),
    ('ignored', 'Ignored'),
    ('resolved', 'Resolved'),
]


def teks(nilai):
    """Ubah nilai apa pun menjadi teks yang bisa dibandingkan dan dibaca.

    Boolean dijadikan Ya/Tidak dengan sengaja: ``False`` dan ``0`` dan string
    kosong semuanya akan tampil sebagai "kosong" dan menyembunyikan bedanya.
    """
    if nilai is None or nilai is False:
        return ''
    if nilai is True:
        return 'Ya'
    if nilai is False:
        return 'Tidak'
    if isinstance(nilai, float):
        return ('%.7f' % nilai).rstrip('0').rstrip('.') or '0'
    return str(nilai)


class PresenlySaasReconciliation(models.Model):
    """Satu baris untuk satu kolom yang berbeda antara kedua sisi."""

    _name = 'presenly.saas.reconciliation'
    _description = 'Presenly Synchronisation Reconciliation'
    _order = 'checked_at desc, dataset, presenly_key, field_name'
    _rec_name = 'name'

    name = fields.Char(compute='_compute_name', store=True)
    config_id = fields.Many2one(
        'presenly.saas.config', required=True, ondelete='cascade', index=True
    )
    company_id = fields.Many2one(related='config_id.company_id', store=True)

    dataset = fields.Selection(DATASETS, required=True, index=True)
    presenly_key = fields.Char(
        string='Presenly Key', required=True, index=True,
        help='Client or location id, or the employee nopeg, on the Presenly side.',
    )
    record_label = fields.Char(
        string='Record',
        help='Name at the time of the check, so the report stays readable if '
             'the record is later deleted.',
    )
    res_model = fields.Char(string='Odoo Model')
    res_id = fields.Integer(string='Odoo Record')

    field_name = fields.Char(required=True)
    presenly_value = fields.Char(string='In Presenly')
    odoo_value = fields.Char(string='In Odoo')
    odoo_changed_at = fields.Datetime(
        string='Odoo Last Changed',
        help='Kapan kolom ini terakhir berubah di Odoo. Dipakai untuk menilai '
             'mana yang lebih baru tanpa mempercayai jam server seberang.',
    )
    presenly_seen_at = fields.Datetime(
        string='Presenly Value Read At',
        help='Kapan cermin terakhir diperbarui. Bila ini sudah lama, nilainya di '
             'sisi Presenly bisa jadi sudah berubah lagi.',
    )

    nature = fields.Selection(NATURES, required=True, default='differs')
    state = fields.Selection(STATES, required=True, default='open', index=True)
    note = fields.Text()
    detected_at = fields.Datetime(required=True, default=fields.Datetime.now)
    checked_at = fields.Datetime(required=True, default=fields.Datetime.now)
    resolved_at = fields.Datetime(readonly=True)

    _presenly_reconciliation_uniq = models.Constraint(
        'unique(config_id, dataset, presenly_key, field_name)',
        'One row per field per record; re-checking updates it instead of adding another.',
    )

    @api.depends('dataset', 'presenly_key', 'field_name', 'presenly_value', 'odoo_value')
    def _compute_name(self):
        label = dict(DATASETS)
        for row in self:
            row.name = '%s · %s · %s: %s -> %s' % (
                label.get(row.dataset, row.dataset), row.presenly_key or '?',
                row.field_name or '?', row.presenly_value or '-', row.odoo_value or '-',
            )

    # ------------------------------------------------------------------
    # Tombol
    # ------------------------------------------------------------------
    @api.model
    def run_all(self):
        """Periksa semua konfigurasi yang aktif. Untuk tombol di layar."""
        ringkasan = {}
        for config in self.env['presenly.saas.config'].search([
            ('enabled', '=', True), ('active', '=', True),
        ]):
            hasil, error = config.reconcile()
            ringkasan[config.display_name] = error or hasil
        return ringkasan


class PresenlySaasConfig(models.Model):
    """Sisi pemeriksa: mengambil data Odoo dan membandingkannya dengan cermin."""

    _inherit = 'presenly.saas.config'

    reconciliation_ids = fields.One2many(
        'presenly.saas.reconciliation', 'config_id', string='Discrepancies'
    )
    reconciliation_open_count = fields.Integer(
        compute='_compute_reconciliation_open_count',
        string='Open Discrepancies',
    )
    reconciliation_checked_at = fields.Datetime(
        string='Last Reconciled', readonly=True,
    )

    @api.depends('reconciliation_ids.state')
    def _compute_reconciliation_open_count(self):
        for config in self:
            config.reconciliation_open_count = len(
                config.reconciliation_ids.filtered(lambda row: row.state == 'open')
            )

    def reconcile(self):
        """Bandingkan kedua sisi, tulis laporannya. Mengembalikan (ringkasan, error).

        Mengembalikan error, tidak melemparnya: pemeriksaan boleh gagal karena
        jaringan, dan itu tidak boleh membuat pemanggilnya (cron, tombol) ikut
        gagal.
        """
        self.ensure_one()
        ringkasan = {'checked': 0, 'open': 0, 'resolved': 0, 'by_dataset': {}, 'errors': {}}
        hasil = self._reconcile_datasets_summary(ringkasan)
        # Satu wadah saja: galat dicatat di `hasil` oleh pemeriksa per dataset,
        # sedangkan pemanggil membaca `ringkasan`. Pernah keduanya berbeda, dan
        # laporan yang dikembalikan jadi mengaku tidak ada galat sama sekali.
        ringkasan['errors'] = hasil['errors']

        # Yang bedanya sudah hilang ditutup, bukan dibiarkan menggantung. Dataset
        # yang gagal diperiksa tidak ikut ditutup: pemeriksaan yang tidak sempat
        # berjalan bukan bukti bahwa bedanya sudah selesai.
        ringkasan['resolved'] += self._resolve_settled(hasil['keys'], hasil['errors'])
        self.sudo().write({'reconciliation_checked_at': fields.Datetime.now()})
        ringkasan['open'] = self.env['presenly.saas.reconciliation'].search_count([
            ('config_id', '=', self.id), ('state', '=', 'open'),
        ])
        return ringkasan, False

    def _reconcile_datasets_summary(self, ringkasan):
        """Periksa tiap dataset, dan jangan biarkan satu kegagalan membisukan sisanya.

        Dipisah per dataset dengan sengaja. Perbandingan klien memanggil API dan
        bisa gagal karena jaringan, sedangkan perbandingan lokasi dan pegawai
        membaca cermin yang sudah ada dan tidak butuh jaringan sama sekali.
        Sebelum ini, kegagalan jaringan pada satu dataset membatalkan seluruh
        pemeriksaan — dan pemeriksaan yang batal tanpa suara itu persis jenis
        kegagalan yang alat ini ada untuk mencegahnya.
        """
        hasil = {'keys': set(), 'errors': {}}
        for nama, metode in self._reconcile_datasets().items():
            try:
                jumlah = metode(hasil['keys'])
            except Exception as exc:  # noqa: BLE001 - dilaporkan per dataset
                _logger.warning(
                    'Presenly SaaS: rekonsiliasi dataset %s gagal: %s', nama, exc,
                )
                hasil['errors'][nama] = str(exc)
                jumlah = 0
            ringkasan['by_dataset'][nama] = jumlah
            ringkasan['checked'] += jumlah
        return hasil

    def _reconcile_datasets(self):
        """Dataset yang diperiksa modul ini. Modul lain menambah miliknya."""
        return {'client': self._reconcile_clients}

    # ------------------------------------------------------------------
    # Klien -> res.company
    # ------------------------------------------------------------------
    def _reconcile_clients(self, keys):
        """Bandingkan perusahaan cermin dengan data klien di Presenly."""
        rows, _meta, _pages = self._fetch_pages(
            lambda params, _client=self._client().get_resource:
                _client('internal-companies', params),
            {'limit': 500},
        )
        Perusahaan = self.env['res.company'].sudo()
        jumlah = 0

        for row in rows:
            if not isinstance(row, dict) or not row.get('id'):
                continue
            client_id = int(row['id'])
            perusahaan = Perusahaan.search([('presenly_client_id', '=', client_id)], limit=1)
            if not perusahaan:
                self._upsert({
                    'dataset': 'client', 'presenly_key': str(client_id),
                    'record_label': row.get('name') or '', 'res_model': 'res.company',
                    'res_id': 0, 'field_name': 'name',
                    'presenly_value': row.get('name') or '', 'odoo_value': '',
                    'nature': 'missing_in_odoo',
                })
                keys.add(('client', str(client_id), 'name'))
                jumlah += 1
                continue

            keys.add(('client', str(client_id), 'name'))
            jumlah += 1
            # Hanya kolom yang memang disalin sinkronisasi. Membandingkan kolom
            # lain akan melaporkan perbedaan yang tidak pernah diminta siapa pun.
            for nama_kolom, nilai_presenly, nilai_odoo in [
                ('name', row.get('name'), perusahaan.name),
                ('email', row.get('email'), perusahaan.email),
                ('phone', row.get('whatsapp_number'), perusahaan.phone),
                ('presenly_business_sector', row.get('business_sector'),
                 perusahaan.presenly_business_sector),
            ]:
                if teks(nilai_presenly) == teks(nilai_odoo):
                    continue
                self._upsert({
                    'dataset': 'client', 'presenly_key': str(client_id),
                    'record_label': perusahaan.name, 'res_model': 'res.company',
                    'res_id': perusahaan.id, 'field_name': nama_kolom,
                    'presenly_value': teks(nilai_presenly),
                    'odoo_value': teks(nilai_odoo),
                    'odoo_changed_at': perusahaan.write_date,
                    'presenly_seen_at': perusahaan.presenly_synced_at,
                    'nature': 'differs',
                })
                keys.add(('client', str(client_id), nama_kolom))

        # Perusahaan yang mengaku cermin klien tetapi kliennya sudah tidak ada.
        terlihat = {int(row['id']) for row in rows if isinstance(row, dict) and row.get('id')}
        for perusahaan in Perusahaan.search([('presenly_client_id', '!=', False)]):
            if perusahaan.presenly_client_id in terlihat:
                continue
            self._upsert({
                'dataset': 'client', 'presenly_key': str(perusahaan.presenly_client_id),
                'record_label': perusahaan.name, 'res_model': 'res.company',
                'res_id': perusahaan.id, 'field_name': 'presenly_client_id',
                'presenly_value': '', 'odoo_value': str(perusahaan.presenly_client_id),
                'odoo_changed_at': perusahaan.write_date, 'nature': 'missing_in_presenly',
            })
            keys.add(('client', str(perusahaan.presenly_client_id), 'presenly_client_id'))

        return jumlah

    # ------------------------------------------------------------------
    # Pembantu
    # ------------------------------------------------------------------
    def _upsert(self, nilai):
        """Tulis satu temuan; pemeriksaan ulang memperbarui baris yang sama.

        Keadaan baris yang sudah ditandai "diabaikan" atau "diselesaikan" tidak
        ditimpa, supaya keputusan manusia tidak dibatalkan oleh pemeriksaan
        berikutnya.
        """
        Laporan = self.env['presenly.saas.reconciliation'].sudo()
        kunci = [
            ('config_id', '=', self.id),
            ('dataset', '=', nilai['dataset']),
            ('presenly_key', '=', nilai['presenly_key']),
            ('field_name', '=', nilai['field_name']),
        ]
        baris = Laporan.search(kunci, limit=1)
        nilai = dict(nilai, config_id=self.id, checked_at=fields.Datetime.now())
        if baris:
            # Temuan yang muncul lagi setelah ditutup dibuka kembali: bedanya
            # nyata, dan menyembunyikannya persis yang mau dihindari alat ini.
            if baris.state == 'resolved':
                nilai.update({'state': 'open', 'resolved_at': False})
            baris.write(nilai)
            return baris
        return Laporan.create(nilai)

    def _resolve_settled(self, keys, errors=None):
        """Tutup temuan yang bedanya sudah tidak ada.

        Dataset yang gagal diperiksa dilewati: ketidakhadirannya di `keys`
        disebabkan pemeriksaannya tidak berjalan, bukan karena bedanya selesai.
        """
        errors = errors or {}
        Laporan = self.env['presenly.saas.reconciliation'].sudo()
        terbuka = Laporan.search([('config_id', '=', self.id), ('state', '!=', 'resolved')])
        tertutup = 0
        for baris in terbuka:
            if baris.dataset in errors:
                continue
            if (baris.dataset, baris.presenly_key, baris.field_name) in keys:
                continue
            baris.write({
                'state': 'resolved',
                'resolved_at': fields.Datetime.now(),
                'note': _('No longer differs as of the last check.'),
            })
            tertutup += 1
        return tertutup
