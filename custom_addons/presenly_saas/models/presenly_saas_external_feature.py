import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class PresenlySaasExternalFeature(models.Model):
    """Katalog fitur Presenly yang tersedia lewat API eksternal.

    Ini **bukan** daftar hak paket. Nama yang mirip memang disengaja dibedakan
    di sini supaya tidak tertukar:

    - `presenly.saas.external.feature` (model ini): katalog **endpoint** yang
      disediakan server, beserta status `available` atau `planned`.
    - `plan_features` pada langganan: **hak paket**, yaitu fitur apa yang boleh
      dipakai tenant menurut `plan_type`.

    Yang pertama menjawab "apa yang bisa ditarik", yang kedua menjawab "apa yang
    boleh dipakai". Menggabungkan keduanya akan membuat dua pertanyaan berbeda
    terlihat sama.
    """

    _name = 'presenly.saas.external.feature'
    _description = 'Presenly External Feature Catalog'
    _order = 'sequence, code'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
        index=True,
    )
    code = fields.Char(string='Feature', required=True)
    path = fields.Char(required=True)
    status = fields.Selection(
        [('available', 'Tersedia'), ('planned', 'Direncanakan')],
        required=True,
        default='planned',
    )
    web_page = fields.Char(string='Halaman Web')
    description = fields.Char()
    sequence = fields.Integer(default=100)
    fetched_at = fields.Datetime(readonly=True)

    _company_code_uniq = models.Constraint(
        'unique(company_id, code)',
        'Satu kode fitur hanya boleh muncul sekali per company.',
    )

    @api.depends('code', 'description')
    def _compute_display_name(self):
        for feature in self:
            feature.display_name = feature.description or feature.code

    @api.model
    def _sync_from_payload(self, config, features):
        """Ganti katalog company ini dengan hasil tarikan terbaru.

        Mengganti, bukan menambah: ini cermin dari katalog server, bukan arsip.
        Kalau server menghapus sebuah fitur, cerminnya juga harus ikut hilang,
        supaya daftar di Odoo tidak menampilkan fitur yang sudah tidak ada.
        """
        Feature = self.sudo()
        now = fields.Datetime.now()

        incoming = []
        seen = set()
        for item in features or []:
            if not isinstance(item, dict):
                continue
            code = (item.get('feature') or '').strip()
            if not code or code in seen:
                continue
            seen.add(code)
            incoming.append({
                'company_id': config.company_id.id,
                'code': code,
                'path': item.get('path') or '',
                'status': 'available' if item.get('status') == 'available' else 'planned',
                'web_page': item.get('web_page') or False,
                'description': item.get('description') or False,
                'sequence': len(incoming) * 10,
                'fetched_at': now,
            })

        existing = Feature.search([('company_id', '=', config.company_id.id)])
        by_code = {feature.code: feature for feature in existing}

        for values in incoming:
            feature = by_code.pop(values['code'], None)
            if feature:
                feature.write(values)
            else:
                Feature.create(values)

        # Sisa berarti tidak ada lagi di katalog server.
        if by_code:
            Feature.browse([f.id for f in by_code.values()]).unlink()

        return Feature.search([('company_id', '=', config.company_id.id)])

    def _available_codes(self):
        self.ensure_one()
        return self.search([
            ('company_id', '=', self.company_id.id),
            ('status', '=', 'available'),
        ]).mapped('code')
