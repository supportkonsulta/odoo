import pathlib
import re

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.presenly_saas_approval import SUBMISSION_STATUSES, normalize_status

# Lima cermin pengajuan dan model langkah persetujuannya. Ditulis sebagai daftar
# supaya tes bisa memeriksa kelimanya dengan aturan yang sama — justru
# kesamaannya yang ingin dijaga di sini.
PENGAJUAN = [
    ('presenly.saas.leave', 'presenly.saas.approval.step.leave'),
    ('presenly.saas.overtime', 'presenly.saas.approval.step.overtime'),
    ('presenly.saas.medical.certificate', 'presenly.saas.approval.step.medical.certificate'),
    ('presenly.saas.attendance.correction', 'presenly.saas.approval.step.attendance.correction'),
    ('presenly.saas.shift.swap', 'presenly.saas.approval.step.shift.swap'),
]

# Field yang harus ada di setiap cermin pengajuan, apa pun jenisnya.
FIELD_BERSAMA = (
    'status',
    'status_raw',
    'approval_has_workflow',
    'approval_flow_status',
    'approval_current_level',
    'approval_total_levels',
    'approval_waiting_for',
    'approval_step_ids',
)


def approval_block(**overrides):
    """Blok `approval` seperti yang dikirim resource pengajuan."""
    blok = {
        'has_workflow': True,
        'status': 'pending',
        'current_level': 2,
        'total_levels': 2,
        'steps': [
            {
                'level': 1,
                'status': 'approved',
                'expected': {'type': 'direct_manager', 'value': None, 'user': None},
                'acted_by': {'id': 9, 'nopeg': 'iksg-boss', 'name': 'boss'},
                'acted_at': '2026-09-21T01:00:00.000Z',
                'rejection_reason': None,
            },
            {
                'level': 2,
                'status': 'pending',
                'expected': {'type': 'role', 'value': 'hrd', 'user': None},
                'acted_by': None,
                'acted_at': None,
                'rejection_reason': None,
            },
        ],
    }
    blok.update(overrides)
    return blok


def leave_row(**overrides):
    row = {
        'id': 11,
        'reference_number': 'CT/2026/00001',
        'leave_date': '2026-09-21',
        'start_date': '2026-09-22',
        'end_date': '2026-09-24',
        'total_days': 3.0,
        'status': 'pending',
        'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
        'approval': approval_block(),
    }
    row.update(overrides)
    return row


@tagged('post_install', '-at_install')
class TestPresenlySubmissionStatus(TransactionCase):
    """Satu kosakata status untuk kelima jenis pengajuan.

    Presenly memakai dua kosakata: lembur mengirim `Y`/`N`/`T` (ya, tidak,
    tunggu), sedangkan empat jenis lain mengirim `pending`/`approved`/`rejected`.
    Sebelum diseragamkan, penyaring `status = 'approved'` pada lembur tidak
    pernah cocok karena kolomnya berisi `Y` — dan itu tidak terlihat sebagai
    galat, hanya sebagai daftar yang selalu kosong.
    """

    def test_kosakata_lembur_dipetakan(self):
        self.assertEqual(normalize_status('Y'), ('approved', 'Y'))
        self.assertEqual(normalize_status('N'), ('rejected', 'N'))
        # `T` adalah "tunggu", bukan "tidak".
        self.assertEqual(normalize_status('T'), ('pending', 'T'))

    def test_kosakata_baru_dipetakan_ke_dirinya_sendiri(self):
        for status in ('pending', 'approved', 'rejected'):
            self.assertEqual(normalize_status(status), (status, status))

    def test_huruf_besar_dan_spasi_diabaikan(self):
        self.assertEqual(normalize_status(' y '), ('approved', 'y'))

    def test_status_asing_tidak_ditebak(self):
        status, mentah = normalize_status('menunggu-hrd')
        self.assertIs(status, False)
        self.assertEqual(mentah, 'menunggu-hrd')

    def test_status_kosong(self):
        self.assertEqual(normalize_status(None), (False, False))
        self.assertEqual(normalize_status(''), (False, False))

    def test_setiap_pengajuan_punya_kolom_yang_sama(self):
        for model_name, _ in PENGAJUAN:
            model = self.env[model_name]
            for nama in FIELD_BERSAMA:
                self.assertIn(
                    nama, model._fields,
                    '%s tidak punya field %s; kelima jenis pengajuan harus sama '
                    'bentuknya supaya penyaring dan laporan bisa dipakai ulang'
                    % (model_name, nama),
                )
            self.assertEqual(
                model._fields['status'].selection, SUBMISSION_STATUSES,
                '%s memakai kosakata status yang berbeda' % model_name,
            )

    def test_lembur_menyimpan_status_yang_sudah_dinormalkan(self):
        model = self.env['presenly.saas.overtime']
        values = model._mirror_values(self.env.company, {
            'id': 21,
            'overtime_date': '2026-09-18',
            'approval_status': 'Y',
            'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
        })
        self.assertEqual(values['status'], 'approved')
        # Nilai aslinya tidak dibuang: yang mengaudit masih bisa melihatnya.
        self.assertEqual(values['status_raw'], 'Y')

        lembur = model.create(values)
        # Penyaring yang dulu tidak pernah cocok sekarang cocok.
        self.assertEqual(
            model.search_count([
                ('id', '=', lembur.id), ('status', '=', 'approved'),
            ]),
            1,
        )

    def test_status_asing_tetap_terlihat(self):
        model = self.env['presenly.saas.leave']
        values = model._mirror_values(self.env.company, leave_row(status='ditinjau'))
        self.assertIs(values['status'], False)
        self.assertEqual(values['status_raw'], 'ditinjau')

        cuti = model.create(values)
        self.assertFalse(cuti.status)
        self.assertEqual(cuti.status_raw, 'ditinjau')


@tagged('post_install', '-at_install')
class TestPresenlyApprovalSteps(TransactionCase):
    """Alur persetujuan berjenjang tercermin beserta levelnya."""

    def _mirror(self, model_name, row):
        model = self.env[model_name]
        values = model._mirror_values(self.env.company, row)
        self.assertTrue(values, '%s menolak baris: %r' % (model_name, row))
        return model.create(values)

    def test_ringkasan_alur_tercermin(self):
        cuti = self._mirror('presenly.saas.leave', leave_row())

        self.assertTrue(cuti.approval_has_workflow)
        self.assertEqual(cuti.approval_flow_status, 'pending')
        self.assertEqual(cuti.approval_current_level, 2)
        self.assertEqual(cuti.approval_total_levels, 2)
        # Yang dibutuhkan pengguna sehari-hari: siapa yang sedang ditunggu.
        self.assertEqual(cuti.approval_waiting_for, 'Role hrd')

    def test_setiap_level_tercermin_dengan_urutannya(self):
        cuti = self._mirror('presenly.saas.leave', leave_row())

        self.assertEqual(len(cuti.approval_step_ids), 2)
        pertama, kedua = cuti.approval_step_ids
        self.assertEqual([pertama.level, kedua.level], [1, 2])

        self.assertEqual(pertama.step_status, 'approved')
        self.assertEqual(pertama.approver_label, 'Direct Manager')
        self.assertEqual(pertama.acted_by_name, 'boss')
        self.assertEqual(pertama.acted_by_nopeg, 'iksg-boss')
        self.assertTrue(pertama.acted_at)

        self.assertEqual(kedua.step_status, 'pending')
        self.assertEqual(kedua.approver_type, 'role')
        self.assertEqual(kedua.approver_value, 'hrd')
        self.assertFalse(kedua.acted_by_name)
        # Level yang belum dikerjakan tidak boleh tampak sudah diputus.
        self.assertFalse(kedua.acted_at)

    def test_urutan_level_tidak_mengikuti_urutan_payload(self):
        blok = approval_block()
        blok['steps'] = list(reversed(blok['steps']))
        cuti = self._mirror('presenly.saas.leave', leave_row(approval=blok))

        # Dibaca ulang dari database: urutannya ditentukan `_order` model, dan
        # urutan di cache masih mengikuti urutan perintah pembuatannya.
        cuti.invalidate_recordset()
        self.assertEqual(cuti.approval_step_ids.mapped('level'), [1, 2])

    def test_pengajuan_tanpa_alur_tidak_punya_level(self):
        baris = leave_row()
        baris.pop('approval')
        cuti = self._mirror('presenly.saas.leave', baris)

        self.assertFalse(cuti.approval_has_workflow)
        self.assertFalse(cuti.approval_step_ids)
        self.assertFalse(cuti.approval_waiting_for)

    def test_alur_yang_menyatakan_dirinya_kosong_diperlakukan_sama(self):
        cuti = self._mirror('presenly.saas.leave', leave_row(approval={
            'has_workflow': False, 'status': None, 'current_level': None,
            'total_levels': None, 'steps': [],
        }))
        self.assertFalse(cuti.approval_has_workflow)
        self.assertFalse(cuti.approval_step_ids)

    def test_status_level_asing_tidak_menggagalkan_penarikan(self):
        blok = approval_block()
        blok['steps'][1]['status'] = 'ditinjau'
        cuti = self._mirror('presenly.saas.leave', leave_row(approval=blok))

        kedua = cuti.approval_step_ids.filtered(lambda step: step.level == 2)
        self.assertFalse(kedua.step_status)
        # Levelnya tetap ada: yang tidak dikenal hanya statusnya.
        self.assertEqual(len(cuti.approval_step_ids), 2)

    def test_level_tanpa_nomor_dilewati(self):
        blok = approval_block()
        blok['steps'].append({'level': None, 'status': 'pending'})
        cuti = self._mirror('presenly.saas.leave', leave_row(approval=blok))
        self.assertEqual(cuti.approval_step_ids.mapped('level'), [1, 2])

    def test_approver_bertipe_pengguna_memakai_nama_bukan_id(self):
        blok = approval_block()
        blok['steps'] = [{
            'level': 1,
            'status': 'pending',
            'expected': {
                'type': 'user',
                'value': None,
                'user': {'id': 7, 'nopeg': 'iksg-yusril', 'name': 'yusril'},
            },
            'acted_by': None,
            'acted_at': None,
            'rejection_reason': None,
        }]
        cuti = self._mirror('presenly.saas.leave', leave_row(approval=blok))
        langkah = cuti.approval_step_ids

        self.assertEqual(langkah.expected_name, 'yusril')
        self.assertEqual(langkah.expected_nopeg, 'iksg-yusril')
        self.assertEqual(langkah.approver_label, 'yusril')
        # Id pengguna Presenly tidak punya arti di sini, jadi tidak disimpan.
        self.assertFalse(langkah.approver_value)

    def test_penolakan_membawa_alasan_dan_pemutusnya(self):
        blok = approval_block(status='rejected', current_level=1)
        blok['steps'] = [{
            'level': 1,
            'status': 'rejected',
            'expected': {'type': 'permission', 'value': 'approve_leave', 'user': None},
            'acted_by': {'id': 3, 'nopeg': 'iksg-yusril', 'name': 'yusril'},
            'acted_at': '2026-09-21T02:00:00.000Z',
            'rejection_reason': 'Beban tim sedang tinggi',
        }]
        cuti = self._mirror('presenly.saas.leave', leave_row(approval=blok))
        langkah = cuti.approval_step_ids

        self.assertEqual(cuti.approval_flow_status, 'rejected')
        self.assertEqual(langkah.approver_label, 'Permission approve_leave')
        self.assertEqual(langkah.rejection_reason, 'Beban tim sedang tinggi')
        self.assertEqual(langkah.acted_by_name, 'yusril')

    def test_setiap_pengajuan_punya_model_langkah_sendiri(self):
        for model_name, step_model_name in PENGAJUAN:
            model = self.env[model_name]
            field = model._fields['approval_step_ids']
            self.assertEqual(
                field.comodel_name, step_model_name,
                '%s menunjuk ke model langkah yang salah' % model_name,
            )
            # Setiap model langkah harus terdaftar dan punya hak akses; menu dan
            # daftarnya hilang tanpa itu.
            self.assertTrue(
                self.env['ir.model.access'].search_count([
                    ('model_id.model', '=', step_model_name),
                ]),
                'model langkah %s tidak punya hak akses' % step_model_name,
            )

    def test_langkah_ikut_terhapus_bersama_induknya(self):
        cuti = self._mirror('presenly.saas.leave', leave_row())
        langkah = cuti.approval_step_ids
        self.assertTrue(langkah)

        cuti.unlink()
        # Cermin berperiode mengganti isinya dengan menghapus lalu membuat ulang;
        # langkah yang tertinggal akan menumpuk tanpa terlihat.
        self.assertFalse(langkah.exists())

# Action yang membuka daftar pengajuan. `form` wajib ada di `view_mode` masing-
# masing; lihat catatan di kelas pengujinya.
ACTIONS = (
    'action_presenly_saas_leave',
    'action_presenly_saas_overtime',
    'action_presenly_saas_medical_certificate',
    'action_presenly_saas_attendance_correction',
    'action_presenly_saas_shift_swap',
)

# Kolom keputusan yang tercatat pada pengajuannya sendiri, per jenis.
KOLOM_KEPUTUSAN = {
    'presenly.saas.leave': ('approver_name', 'approved_at'),
    'presenly.saas.overtime': ('approver_name',),
    'presenly.saas.medical.certificate': ('approver_name', 'approved_at'),
    'presenly.saas.attendance.correction': (
        'tl_approver_name', 'tl_approved_at', 'manager_approver_name',
        'manager_approved_at', 'rejecter_name', 'rejected_at', 'rejection_reason',
    ),
    'presenly.saas.shift.swap': (
        'approver_name', 'approved_at', 'rejecter_name', 'rejected_at', 'rejection_reason',
    ),
}


@tagged('post_install', '-at_install')
class TestPresenlyApprovalIsVisible(TransactionCase):
    """Bagian Persetujuan harus terlihat di setiap detail pengajuan.

    Dua kesalahan pernah membuatnya tidak terlihat sama sekali, dan keduanya
    tidak memunculkan galat apa pun:

    1. Seluruh bagian disembunyikan saat jenis pengajuannya belum punya alur
       berjenjang (`invisible="not approval_has_workflow"`). Tenant yang belum
       menyiapkan alur karena itu tidak pernah melihat siapa yang memutuskan —
       padahal jawabannya ada di kolom keputusan pengajuannya sendiri.
    2. Action lembur tidak memasang `form` di `view_mode`-nya, sehingga formnya
       tidak bisa dibuka: mengeklik baris di daftar hanya mengembalikan ke daftar.
    """

    def test_setiap_action_pengajuan_bisa_membuka_form(self):
        for xmlid in ACTIONS:
            action = self.env.ref('presenly_saas.%s' % xmlid)
            mode = [m.strip() for m in (action.view_mode or '').split(',')]
            self.assertIn(
                'form', mode,
                '%s tidak punya form di view_mode (%s), jadi detail pengajuannya '
                'tidak bisa dibuka sama sekali' % (xmlid, action.view_mode),
            )

    def test_setiap_form_pengajuan_menampilkan_bagian_persetujuan(self):
        for model_name in KOLOM_KEPUTUSAN:
            arch = self.env[model_name].get_view(view_type='form')['arch']

            self.assertIn(
                'string="Approval"', arch,
                '%s tidak punya bagian Approval di formnya' % model_name,
            )
            self.assertIn(
                'name="approval_step_ids"', arch,
                '%s tidak menampilkan daftar level persetujuannya' % model_name,
            )

            # Tanpa alur, isinya benar-benar kosong, jadi seluruh bagiannya
            # disembunyikan: judul kosong lebih membingungkan daripada tidak ada
            # judul.
            kepala = re.search(r'<group string="Approval"[^>]*>', arch)
            self.assertTrue(kepala, '%s: kepala grup Approval tidak terbaca' % model_name)
            self.assertIn(
                'not approval_has_workflow', kepala.group(0),
                '%s menampilkan bagian Approval walau tidak ada alurnya' % model_name,
            )

            # Ringkasan alur dan kolom keputusan tidak ditampilkan lagi: yang
            # dibaca orang di form hanya rangkaian langkahnya. Datanya tetap ada
            # di model, jadi yang diperiksa di sini adalah tampilannya.
            for kolom in ('approval_flow_status', 'approval_current_level',
                          'approval_total_levels', 'approval_waiting_for'):
                self.assertNotIn(
                    'name="%s"' % kolom, arch,
                    '%s masih menampilkan %s; bagian Persetujuan seharusnya hanya '
                    'rangkaian langkahnya' % (model_name, kolom),
                )
            # `rejection_reason` dikecualikan: ia juga kolom pada tiap langkah,
            # dan keterangan per langkah itu bagian dari rangkaiannya.
            for kolom in KOLOM_KEPUTUSAN[model_name]:
                if kolom == 'rejection_reason':
                    continue
                self.assertNotIn(
                    'name="%s"' % kolom, arch,
                    '%s masih menampilkan kolom keputusan %s' % (model_name, kolom),
                )


@tagged('post_install', '-at_install')
class TestPresenlyApprovalTimestamps(TransactionCase):
    """Waktu keputusan tiap level ikut dicerminkan.

    Nama penyetujunya saja tidak cukup untuk disebut riwayat: tanpa waktunya,
    urutan keputusan tidak bisa dipastikan. Dua kolom ini sempat tertinggal —
    server mengirimnya, cerminnya tidak menyimpannya.
    """

    def setUp(self):
        super().setUp()
        self.company = self.env.company

    def test_koreksi_presensi_mencatat_waktu_tiap_level(self):
        model = self.env['presenly.saas.attendance.correction']
        values = model._mirror_values(self.company, {
            'id': 41,
            'date': '2026-09-21',
            'status': 'approved',
            'tl_approved_at': '2026-09-21T02:00:00.000Z',
            'manager_approved_at': '2026-09-21T04:30:00.000Z',
            'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
            'tl_approver': {'id': 3, 'nopeg': 'iksg-yusril', 'name': 'yusril'},
            'manager_approver': {'id': 4, 'nopeg': 'iksg-boss', 'name': 'boss'},
        })
        self.assertTrue(values['tl_approved_at'])
        self.assertTrue(values['manager_approved_at'])
        self.assertLess(values['tl_approved_at'], values['manager_approved_at'])

    def test_tukar_shift_mencatat_waktu_persetujuan(self):
        model = self.env['presenly.saas.shift.swap']
        values = model._mirror_values(self.company, {
            'id': 51,
            'requester_date': '2026-09-21',
            'status': 'approved',
            'approved_at': '2026-09-21T03:00:00.000Z',
            'requester': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
            'target': {'id': 3, 'nopeg': 'iksg-yusril', 'name': 'yusril'},
        })
        self.assertTrue(values['approved_at'])

    def test_waktu_yang_tidak_dikirim_tetap_kosong(self):
        # Tidak semua jenis pengajuan punya kolom waktunya di server; yang tidak
        # ada jangan diisi dengan waktu lain, mis. waktu tarikan.
        model = self.env['presenly.saas.overtime']
        values = model._mirror_values(self.company, {
            'id': 21,
            'overtime_date': '2026-09-18',
            'approval_status': 'Y',
            'employee': {'id': 2, 'nopeg': 'iksg-rangga', 'name': 'rangga'},
        })
        self.assertNotIn('approved_at', values)

BERKAS_WIDGET = (
    pathlib.Path(__file__).resolve().parent.parent
    / 'static' / 'src' / 'approval' / 'presenly_approval_steps'
)


@tagged('post_install', '-at_install')
class TestPresenlyApprovalStepsWidget(TransactionCase):
    """Widget langkah persetujuan: pendaftaran dan syarat pemuatan datanya.

    Mengganti daftar One2many dengan widget punya satu jebakan yang tidak
    memunculkan galat apa pun: Odoo menentukan field anak mana yang perlu dimuat
    dari subview di dalam field itu, dan kalau daftarnya dihapus dari arch,
    widgetnya menerima baris tanpa isi — rangkaian langkah yang kosong, tanpa
    satu pun pesan kesalahan.
    """

    NAMA_WIDGET = 'presenly_approval_steps'

    def test_widget_terdaftar_di_javascript(self):
        sumber = BERKAS_WIDGET.with_suffix('.js').read_text()
        self.assertIn(
            '"%s"' % self.NAMA_WIDGET, sumber,
            'widget %s tidak didaftarkan di JavaScript' % self.NAMA_WIDGET,
        )
        self.assertIn('"one2many"', sumber, 'widget langkah tidak menyebut tipe one2many')

    def test_setiap_pemakaian_widget_menyertakan_daftar_field_anak(self):
        dipakai = 0
        for view in self.env['ir.ui.view'].search([]):
            arch = view.arch_db or ''
            for pemakaian in re.finditer(
                r'<field[^>]*widget="%s"[^>]*>(.*?)</field>' % self.NAMA_WIDGET, arch, re.S
            ):
                dipakai += 1
                self.assertIn(
                    '<list', pemakaian.group(1),
                    '%s: field langkah tidak menyertakan daftar field anak, jadi '
                    'widgetnya akan menerima baris tanpa isi' % view.name,
                )
                for kolom in ('level', 'step_status', 'approver_label', 'acted_by_name'):
                    self.assertIn(
                        'name="%s"' % kolom, pemakaian.group(1),
                        '%s: kolom %s tidak dimuat, padahal dipakai widget'
                        % (view.name, kolom),
                    )
        self.assertTrue(dipakai, 'tidak ada pemakaian widget langkah')

    def test_templat_tidak_memakai_operator_python(self):
        # Ekspresi templat OWL diperiksa dengan JavaScript. `and`, `or`, dan `not`
        # tidak dikenali di sana, dan kegagalannya tidak menyebut barisnya.
        templat = re.sub(r'<!--.*?-->', '', BERKAS_WIDGET.with_suffix('.xml').read_text(), flags=re.S)
        ekspresi = re.findall(r'\bt-(?:if|elif|esc|out|att-[\w-]+)="([^"]*)"', templat)
        bersalah = [
            teks for teks in ekspresi
            if re.search(r'(?<![\w.])(and|or|not)(?![\w])', teks)
        ]
        self.assertEqual(bersalah, [], 'ekspresi templat memakai operator Python: %s' % bersalah)
