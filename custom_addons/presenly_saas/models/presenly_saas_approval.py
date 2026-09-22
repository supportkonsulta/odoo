"""Kosakata bersama pengajuan: status dan alur persetujuan berjenjang.

Lima jenis pengajuan yang dicerminkan modul ini — cuti, lembur, surat dokter,
koreksi presensi, dan tukar shift — punya dua hal yang sama di sisi Presenly.
Keduanya dikumpulkan di sini supaya tidak berbeda antar jenis.

**Status.** Presenly memakai dua kosakata. Lembur memakai penanda lama
`Y`/`N`/`T` (ya, tidak, tunggu) karena datanya lebih tua; empat jenis lainnya
memakai `pending`/`approved`/`rejected`. Kalau nilai mentahnya diteruskan apa
adanya, penyaring `status = 'approved'` pada lembur tidak pernah cocok — dan itu
memang ada di modul ini sebelum statusnya diseragamkan.

**Alur persetujuan berjenjang.** Satu pengajuan punya satu instance alur di
Presenly, dengan satu baris per level. Tiap level mencatat siapa yang seharusnya
menyetujui dan siapa yang sudah memutuskan. Tanpa itu, yang terlihat hanya status
akhirnya, sehingga tidak ada cara mengetahui level mana yang belum bergerak.
"""

import logging

from odoo import _, api, fields, models

from .presenly_saas_attendance_log import parse_datetime

_logger = logging.getLogger(__name__)

# Kosakata status yang dipakai sebagai bahasa bersama modul ini. Sengaja pendek:
# hanya nilai yang benar-benar dikirim Presenly. Nilai lain tidak ditebak.
SUBMISSION_STATUSES = [
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
]

# Kosakata Presenly yang berbeda dari kosakata di atas, dipetakan ke sini.
#
# `t` adalah "tunggu", bukan "tidak": pengajuan lembur dibuat dengan
# `approval_status = 'T'`, dan kode Presenly sendiri mengomentari nilai itu
# sebagai "Reset to Pending". Karena itu `t` dipetakan ke `pending`, bukan ke
# `rejected`.
STATUS_ALIASES = {
    'y': 'approved',
    'n': 'rejected',
    't': 'pending',
    'pending': 'pending',
    'approved': 'approved',
    'rejected': 'rejected',
}

APPROVER_TYPES = [
    ('direct_manager', 'Direct Manager'),
    ('role', 'Role'),
    ('permission', 'Permission'),
    ('user', 'Selected User'),
]


def normalize_status(raw):
    """Petakan satu nilai status dari Presenly ke kosakata modul ini.

    Mengembalikan `(status, status_raw)`. Nilai yang belum dikenal tidak
    ditebak: `status` dibiarkan kosong sementara nilai aslinya tetap disimpan,
    sehingga kosakata baru di sisi server muncul sebagai ketidaktahuan yang
    terlihat — bukan sebagai status yang kebetulan mirip.
    """
    if raw in (None, False, ''):
        return False, False
    teks = str(raw).strip()
    return STATUS_ALIASES.get(teks.lower(), False), teks


def _canonical_status(raw):
    """Status alur, yang kosakatanya sudah sama di kedua sisi.

    Tetap disaring: `Selection` menolak nilai di luar daftarnya, dan satu nilai
    baru dari server tidak boleh menggagalkan penarikan seluruh halaman.
    """
    return raw if raw in dict(SUBMISSION_STATUSES) else False


def _to_int(value):
    """Angka dari payload, tanpa melempar galat kalau isinya bukan angka."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def approval_summary_values(row):
    """Ringkasan alur satu pengajuan, siap dipakai sebagai nilai kolom."""
    approval = row.get('approval')
    if not isinstance(approval, dict) or not approval.get('has_workflow'):
        return {
            'approval_has_workflow': False,
            'approval_flow_status': False,
            'approval_current_level': 0,
            'approval_total_levels': 0,
        }
    return {
        'approval_has_workflow': True,
        'approval_flow_status': _canonical_status(approval.get('status')),
        'approval_current_level': _to_int(approval.get('current_level')),
        'approval_total_levels': _to_int(approval.get('total_levels')),
    }


def approval_step_values(step, level):
    """Satu level persetujuan, dipetakan ke kolom model langkah."""
    diharapkan = step.get('expected') if isinstance(step.get('expected'), dict) else {}
    orang = diharapkan.get('user') if isinstance(diharapkan.get('user'), dict) else {}
    pemutus = step.get('acted_by') if isinstance(step.get('acted_by'), dict) else {}
    return {
        'level': level,
        'step_status': _canonical_status(step.get('status')),
        'approver_type': diharapkan.get('type') or False,
        'approver_value': diharapkan.get('value') or False,
        'expected_name': orang.get('name') or False,
        'expected_nopeg': orang.get('nopeg') or False,
        'acted_by_name': pemutus.get('name') or False,
        'acted_by_nopeg': pemutus.get('nopeg') or False,
        'acted_at': parse_datetime(step.get('acted_at')),
        'rejection_reason': step.get('rejection_reason') or False,
    }


def approval_step_commands(row):
    """Perintah One2many yang menulis ulang langkah persetujuan satu pengajuan.

    Dipakai sebagai nilai kolom saat cerminnya dibuat, sehingga induk dan
    langkah-langkahnya ditulis dalam satu operasi.
    """
    approval = row.get('approval')
    langkah = approval.get('steps') if isinstance(approval, dict) else None
    if not langkah:
        return []

    perintah = []
    for step in langkah:
        level = _to_int(step.get('level'))
        if not level:
            # Level adalah urutan sekaligus penandanya; baris tanpa level tidak
            # bisa diletakkan di urutan mana pun. Dilewati dan dilaporkan, bukan
            # menggagalkan seluruh halaman.
            _logger.warning(
                'presenly_saas: langkah persetujuan tanpa level dilewati: %s', step,
            )
            continue
        perintah.append((0, 0, approval_step_values(step, level)))
    return perintah


class PresenlySaasApprovalStepMixin(models.AbstractModel):
    """Isi satu level persetujuan, dipakai bersama kelima jenis pengajuan."""

    _name = 'presenly.saas.approval.step.mixin'
    _description = 'Presenly SaaS Approval Step Mixin'
    _order = 'level, id'

    level = fields.Integer(string='Level', required=True, index=True, readonly=True)
    step_status = fields.Selection(
        SUBMISSION_STATUSES, string='Step Status', index=True, readonly=True,
    )
    approver_type = fields.Selection(
        APPROVER_TYPES, string='Approver Type', readonly=True,
        help='Who is expected to decide this level, as configured in Presenly.',
    )
    approver_value = fields.Char(
        string='Approver Reference', readonly=True,
        help='Role or permission name. Empty for the other approver types: a '
             'selected user is named by their own field, and a direct manager '
             'needs no reference at all.',
    )
    expected_name = fields.Char(string='Expected Approver Name', readonly=True)
    expected_nopeg = fields.Char(string='Expected Approver Nopeg', readonly=True)
    approver_label = fields.Char(
        string='Expected Approver', compute='_compute_approver_label',
    )
    acted_by_name = fields.Char(string='Decided By', readonly=True)
    acted_by_nopeg = fields.Char(string='Decided By Nopeg', readonly=True)
    acted_at = fields.Datetime(string='Decided At', readonly=True)
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True)

    @api.depends('approver_type', 'approver_value', 'expected_name')
    def _compute_approver_label(self):
        """Bentuk teks dari siapa yang seharusnya menyetujui level ini.

        Id mentah tidak pernah ditampilkan: untuk approver bertipe pengguna,
        namanya datang dari server sebagai orang, bukan sebagai angka.

        Kalimatnya dirakit di sini, jadi `_()` dipakai per pola — bukan menempel
        label pilihan field apa adanya, yang akan tetap berbahasa Inggris.
        """
        label = dict(APPROVER_TYPES)
        for step in self:
            if step.approver_type == 'role' and step.approver_value:
                teks = _('Role %s', step.approver_value)
            elif step.approver_type == 'permission' and step.approver_value:
                teks = _('Permission %s', step.approver_value)
            elif step.approver_type == 'user' and step.expected_name:
                teks = step.expected_name
            else:
                teks = _(label.get(step.approver_type) or '')
            step.approver_label = teks or False


class PresenlySaasApprovalStepLeave(models.Model):
    """Satu level persetujuan pada pengajuan cuti."""

    _name = 'presenly.saas.approval.step.leave'
    _inherit = ['presenly.saas.approval.step.mixin']
    _description = 'Presenly Leave Approval Step (mirror)'

    leave_id = fields.Many2one(
        'presenly.saas.leave', string='Leave Request',
        required=True, ondelete='cascade', index=True, readonly=True,
    )


class PresenlySaasApprovalStepOvertime(models.Model):
    """Satu level persetujuan pada pengajuan lembur."""

    _name = 'presenly.saas.approval.step.overtime'
    _inherit = ['presenly.saas.approval.step.mixin']
    _description = 'Presenly Overtime Approval Step (mirror)'

    overtime_id = fields.Many2one(
        'presenly.saas.overtime', string='Overtime Request',
        required=True, ondelete='cascade', index=True, readonly=True,
    )


class PresenlySaasApprovalStepMedicalCertificate(models.Model):
    """Satu level persetujuan pada surat keterangan dokter."""

    _name = 'presenly.saas.approval.step.medical.certificate'
    _inherit = ['presenly.saas.approval.step.mixin']
    _description = 'Presenly Medical Certificate Approval Step (mirror)'

    certificate_id = fields.Many2one(
        'presenly.saas.medical.certificate', string='Medical Certificate',
        required=True, ondelete='cascade', index=True, readonly=True,
    )


class PresenlySaasApprovalStepAttendanceCorrection(models.Model):
    """Satu level persetujuan pada koreksi presensi."""

    _name = 'presenly.saas.approval.step.attendance.correction'
    _inherit = ['presenly.saas.approval.step.mixin']
    _description = 'Presenly Attendance Correction Approval Step (mirror)'

    correction_id = fields.Many2one(
        'presenly.saas.attendance.correction', string='Attendance Correction',
        required=True, ondelete='cascade', index=True, readonly=True,
    )


class PresenlySaasApprovalStepShiftSwap(models.Model):
    """Satu level persetujuan pada permintaan tukar shift."""

    _name = 'presenly.saas.approval.step.shift.swap'
    _inherit = ['presenly.saas.approval.step.mixin']
    _description = 'Presenly Shift Swap Approval Step (mirror)'

    swap_id = fields.Many2one(
        'presenly.saas.shift.swap', string='Shift Swap Request',
        required=True, ondelete='cascade', index=True, readonly=True,
    )


class PresenlySaasSubmissionMixin(models.AbstractModel):
    """Hal yang dimiliki bersama kelima jenis pengajuan.

    Isinya dua hal yang tidak boleh berbeda antar jenis: kolom status beserta
    kosakatanya, dan ringkasan alur persetujuannya.

    Model yang memakai mixin ini menyediakan `approval_step_ids` sebagai
    One2many ke model langkahnya masing-masing; sisanya dihitung dari sana.
    """

    _name = 'presenly.saas.submission.mixin'
    _description = 'Presenly SaaS Submission Mixin'

    status = fields.Selection(
        SUBMISSION_STATUSES, string='Status', index=True, readonly=True,
        help='Decision status, in this module\'s vocabulary. Presenly sends '
             'overtime with an older Y/N/T vocabulary; it is mapped here so the '
             'same filters work on every request type.',
    )
    status_raw = fields.Char(
        string='Status on SaaS', readonly=True,
        help='Value exactly as sent by Presenly, kept so a status this module '
             'does not recognise stays visible instead of silently becoming '
             'an empty status.',
    )

    approval_has_workflow = fields.Boolean(
        string='Has Approval Flow', readonly=True,
        help='True when Presenly has an approval flow for this request. False '
             'means no flow is configured for its type, so there are no levels '
             'to show.',
    )
    approval_flow_status = fields.Selection(
        SUBMISSION_STATUSES, string='Approval Flow Status', index=True, readonly=True,
    )
    approval_current_level = fields.Integer(string='Current Level', readonly=True)
    approval_total_levels = fields.Integer(string='Total Levels', readonly=True)
    approval_waiting_for = fields.Char(
        string='Waiting For', compute='_compute_approval_waiting_for',
        help='Who is expected to decide the level this request sits at now.',
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
