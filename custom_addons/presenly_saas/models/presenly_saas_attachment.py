"""Lampiran berkas pengajuan.

Tiga jenis pengajuan melampirkan berkas di Presenly: cuti (surat keterangan),
surat dokter, dan timesheet (foto). API-nya mengirim **jalur** berkasnya saja,
dan berkasnya sendiri hanya bisa diambil lewat endpoint unduh berautentikasi.

Odoo baru bisa menampilkan berkas kalau berkasnya ada di dalam Odoo, sebagai
`ir.attachment`. Dua hal yang membuat itu tidak boros:

- **Filestore Odoo mendeduplikasi isi yang sama** (namanya diturunkan dari sha1),
  jadi beberapa lampiran dengan isi identik hanya memakan satu berkas di disk.
- **Unduhan dicache per jalur**, bukan per baris cermin. Cermin pengajuan diganti
  per rentang setiap kali ditarik, sehingga barisnya dibuat ulang — tanpa cache,
  berkas yang tidak berubah akan diunduh lagi setiap 15 menit.
"""

import base64
import logging
import os

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Model cermin yang punya berkas, beserta field jalurnya di API.
ATTACHMENT_FIELDS = {
    'presenly.saas.leave': 'certificate_file',
    'presenly.saas.medical.certificate': 'certificate_file',
    'presenly.saas.timesheet': 'photo_file',
}

# Batas ukuran berkas yang disimpan. Foto timesheet dari ponsel bisa besar, dan
# menyimpannya tanpa batas berarti menyalin seluruh galeri ke database.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

MIMETYPES = {
    '.pdf': 'application/pdf',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.heic': 'image/heic',
    '.heif': 'image/heif',
}

# Penanda baris cache. Nilainya sengaja bukan nama model yang ada: baris ini tidak
# menunjuk record mana pun, ia hanya menyimpan isi berkas per jalur.
CACHE_RES_MODEL = 'presenly.saas.file.cache'


def mimetype_for(path):
    return MIMETYPES.get(os.path.splitext(path)[1].lower(), 'application/octet-stream')


class PresenlySaasAttachmentMixin(models.AbstractModel):
    """Field berkas, dipakai cermin yang punya lampiran."""

    _name = 'presenly.saas.attachment.mixin'
    _description = 'Presenly SaaS Attachment Mixin'

    file_path = fields.Char(
        string='File on SaaS',
        readonly=True,
        help='Path of the attached file as stored by Presenly. Kept so the file '
             'is only downloaded again when it actually changes.',
    )
    attachment_id = fields.Many2one(
        'ir.attachment',
        string='Attachment',
        readonly=True,
        ondelete='set null',
    )
    has_file = fields.Boolean(
        string='Has File',
        compute='_compute_has_file',
        help='True when a file is attached to this request on the SaaS side, '
             'whether or not it has been pulled into Odoo yet.',
    )

    @api.depends('file_path')
    def _compute_has_file(self):
        for record in self:
            record.has_file = bool(record.file_path)


class PresenlySaasAttachmentSync(models.AbstractModel):
    """Radas penarikan lampiran, dipanggil setelah cerminnya ditulis."""

    _name = 'presenly.saas.attachment.sync'
    _description = 'Presenly SaaS Attachment Sync'

    @api.model
    def sync_attachments(self, company, model_name, rows, download):
        """Pastikan berkas tiap baris ada di Odoo sebagai lampiran.

        `rows` adalah baris API. `download` adalah pemanggil yang mengembalikan
        isi berkas dalam byte untuk satu jalur — dipisah begini supaya bagian ini
        bisa diuji tanpa jaringan.

        Mengembalikan jumlah lampiran yang ditulis atau diperbarui.
        """
        field_name = ATTACHMENT_FIELDS.get(model_name)
        if not field_name:
            return 0

        Mirror = self.env[model_name].sudo()
        Attachment = self.env['ir.attachment'].sudo()
        ditulis = 0

        for row in rows:
            path = (row.get(field_name) or '').strip() if isinstance(row, dict) else ''
            if not path:
                continue
            external_id = int(row.get('id') or 0)
            if not external_id:
                continue

            record = Mirror.search([
                ('company_id', '=', company.id),
                ('external_id', '=', external_id),
            ], limit=1)
            if not record:
                continue

            # Berkas yang sama sudah terpasang: tidak perlu diunduh lagi.
            if record.file_path == path and record.attachment_id:
                continue

            isi = self._cached_content(path, download)
            if not isi:
                continue

            # `exists()` wajib: cermin bisa menyimpan rujukan ke lampiran yang
            # sudah terhapus, dan membacanya melempar MissingError.
            if record.attachment_id.exists():
                record.attachment_id.unlink()
            record.attachment_id = Attachment.create({
                'name': os.path.basename(path),
                'datas': base64.b64encode(isi),
                'res_model': model_name,
                'res_id': record.id,
                'mimetype': mimetype_for(path),
            })
            record.file_path = path
            ditulis += 1

        return ditulis

    @api.model
    def _cached_content(self, path, download):
        """Isi berkas dari cache, kalau tidak ada baru diunduh.

        Cache-nya sengaja bertahan antar penarikan: cermin berperiode dibuat ulang
        setiap kali ditarik, jadi tanpa ini berkas yang tidak berubah ikut terunduh
        lagi setiap 15 menit.
        """
        Attachment = self.env['ir.attachment'].sudo()
        cache = Attachment.search([
            ('name', '=', path),
            ('res_model', '=', CACHE_RES_MODEL),
            ('res_id', '=', 0),
        ], limit=1)
        if cache:
            return base64.b64decode(cache.datas or b'')

        try:
            isi = download(path)
        except Exception as exc:                # noqa: BLE001 - dilaporkan, bukan menggagalkan
            _logger.warning(
                "Presenly SaaS: berkas %s tidak bisa diunduh: %s", path, exc,
            )
            return b''

        if not isi:
            return b''
        if len(isi) > MAX_ATTACHMENT_BYTES:
            # Dilaporkan, bukan didiamkan: berkasnya ada di Presenly, hanya tidak
            # ikut disimpan di sini.
            _logger.warning(
                "Presenly SaaS: berkas %s berukuran %s byte, melewati batas %s byte "
                "sehingga tidak disimpan.", path, len(isi), MAX_ATTACHMENT_BYTES,
            )
            return b''

        Attachment.create({
            'name': path,
            'datas': base64.b64encode(isi),
            'res_model': CACHE_RES_MODEL,
            'res_id': 0,
            'mimetype': mimetype_for(path),
        })
        return isi

    @api.model
    def prune_file_cache(self):
        """Buang cache berkas yang jalurnya tidak dipakai cermin mana pun.

        Dipanggil oleh pembersihan terjadwal. Tanpa ini, berkas yang pengajuannya
        sudah lewat jendela penyimpanan tetap menempati filestore.
        """
        Attachment = self.env['ir.attachment'].sudo()
        dipakai = set()
        for model_name in ATTACHMENT_FIELDS:
            dipakai.update(
                self.env[model_name].sudo().search([]).mapped('file_path')
            )

        cache = Attachment.search([('res_model', '=', CACHE_RES_MODEL)])
        dibuang = cache.filtered(lambda a: a.name not in dipakai)

        # Lampiran yang menunjuk baris cermin yang sudah tidak ada. Bisa terjadi
        # pada data yang tercermin sebelum `unlink` di atas ada.
        for model_name in ATTACHMENT_FIELDS:
            yatim = Attachment.search([('res_model', '=', model_name)])
            hidup = set(self.env[model_name].sudo().search([]).ids)
            dibuang |= yatim.filtered(lambda a: a.res_id not in hidup)

        # Sisa rujukan ke lampiran yang sudah hilang disaring lebih dulu.
        dibuang = dibuang.exists()
        jumlah = len(dibuang)
        if jumlah:
            dibuang.unlink()
            _logger.info("Presenly SaaS: %s lampiran/cache berkas dibuang", jumlah)
        return jumlah
