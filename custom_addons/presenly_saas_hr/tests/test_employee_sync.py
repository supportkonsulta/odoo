from unittest.mock import patch

from odoo import _
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.presenly_saas.services.saas_client import PresenlySaasClient, SaasClientError

EMPTY_PAGE = {'data': [], 'meta': {'total': 0, 'total_pages': 0}}


def employee_row(**overrides):
    row = {
        'id': 5,
        'nopeg': 'iksg-rangga',
        'name': 'rangga',
        'email': 'rangga@example.com',
        'phone': '081234567890',
        'is_active': True,
        'bagian': 'Operasional',
        'grup': 'Grup 1',
        'address': 'Jl. Merdeka 10',
        'birth_date': '1995-04-17',
        'birth_place': 'Surabaya',
        'can_approve': True,
        'role': {'id': 3, 'name': 'Supervisor'},
        'internal_company': {'id': 2, 'name': 'PT KONSULTA SEMEN GRESIK'},
        'created_at': '2026-01-05T02:00:00.000Z',
        'updated_at': '2026-09-20T02:00:00.000Z',
    }
    row.update(overrides)
    return row


@tagged('post_install', '-at_install')
class TestPresenlyEmployeeSyncBase(TransactionCase):
    """Dasar bersama: cermin pegawai bersih, dan `hr.employee` bersih."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['presenly.saas.config']._get_or_create(cls.company)

    def setUp(self):
        super().setUp()
        self.config.write({
            'enabled': True, 'base_url': 'https://x', 'tenant_code': 'demo',
            'api_key': 'k', 'retry_count': 0,
        })
        self.Mirror = self.env['presenly.saas.employee']
        self.Hr = self.env['hr.employee']
        # Keduanya dibersihkan, bukan hanya hr.employee. Data yang tertinggal
        # dari percobaan sebelumnya pernah membuat tes ini gagal karena sebab
        # yang tidak ada hubungannya dengan kode yang sedang diuji.
        self.Mirror.search([]).unlink()
        self.Hr.with_context(active_test=False).search([]).unlink()

    def _tarik(self, rows):
        """Tarik pegawai dengan jaringan dipalsukan di kedua arah.

        Arah kirim juga dipalsukan, bukan hanya arah tarik: kalau tidak, satu
        perubahan kecil di logika bisa membuat tes ini menghubungi server
        sungguhan tanpa ada yang menyadarinya.
        """
        def fake_resource(resource, params=None):
            if resource != 'employees':
                return EMPTY_PAGE
            return {'data': rows, 'meta': {'total': len(rows), 'total_pages': 1}}

        def fake_update(nopeg, payload=None):
            dikirim.append({'nopeg': nopeg, 'payload': payload})
            return {'data': {'nopeg': nopeg, 'updated_at': '2026-09-21T03:00:00.000Z'}, 'meta': {}}

        dikirim = []
        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource), \
             patch.object(PresenlySaasClient, 'update_employee', side_effect=fake_update):
            summary, error = self.config._pull_employees()
        self.terkirim = dikirim
        return summary, error

    def _hr(self, nopeg):
        return self.Hr.with_context(active_test=False).search(
            [('presenly_nopeg', '=', nopeg)], limit=1
        )


@tagged('post_install', '-at_install')
class TestPresenlyEmployeeMirror(TestPresenlyEmployeeSyncBase):
    """Cermin menyimpan seluruh payload, termasuk yang tak punya rumah di Odoo."""

    def test_memeta_seluruh_payload(self):
        self._tarik([employee_row()])
        row = self.Mirror.search([])

        self.assertEqual(row.nopeg, 'iksg-rangga')
        self.assertEqual(row.name, 'rangga')
        self.assertEqual(row.email, 'rangga@example.com')
        self.assertEqual(row.role_name, 'Supervisor')
        self.assertEqual(row.internal_company_name, 'PT KONSULTA SEMEN GRESIK')
        self.assertEqual(str(row.birth_date), '1995-04-17')

    def test_kolom_tanpa_rumah_di_odoo_tetap_disimpan(self):
        self._tarik([employee_row()])
        row = self.Mirror.search([])

        self.assertEqual(row.bagian, 'Operasional')
        self.assertEqual(row.grup, 'Grup 1')
        self.assertTrue(row.can_approve)

    def test_menarik_dua_kali_tidak_menumpuk(self):
        self._tarik([employee_row()])
        self._tarik([employee_row(name='rangga diperbarui')])

        self.assertEqual(self.Mirror.search_count([]), 1)
        self.assertEqual(self.Mirror.search([]).name, 'rangga diperbarui')

    def test_pegawai_yang_hilang_dari_server_tidak_dihapus(self):
        self._tarik([employee_row()])
        self._tarik([])

        # Menghapus baris pegawai berdasarkan satu tarikan berisiko membuang
        # data kepegawaian yang masih dipakai.
        self.assertEqual(self.Mirror.search_count([]), 1)

    def test_tanpa_nopeg_tidak_dibuatkan_pegawai_odoo(self):
        summary, error = self._tarik([employee_row(nopeg=None)])

        self.assertFalse(error)
        self.assertEqual(self.Hr.with_context(active_test=False).search_count([]), 0)
        self.assertEqual(len(summary['skipped']), 1)
        self.assertEqual(self.Mirror.search([]).synced_state, 'no_nopeg')


@tagged('post_install', '-at_install')
class TestPresenlyEmployeeToHr(TestPresenlyEmployeeSyncBase):
    """Penerapan ke `hr.employee`: hanya kolom yang ada di kedua sisi."""

    def test_membuat_pegawai_baru(self):
        summary, error = self._tarik([employee_row()])

        self.assertFalse(error)
        self.assertEqual(summary['created'], 1)
        hr = self._hr('iksg-rangga')
        self.assertTrue(hr)
        self.assertEqual(hr.name, 'rangga')
        self.assertEqual(hr.work_email, 'rangga@example.com')
        self.assertEqual(hr.work_phone, '081234567890')
        self.assertEqual(str(hr.birthday), '1995-04-17')
        self.assertEqual(hr.place_of_birth, 'Surabaya')
        self.assertEqual(hr.private_street, 'Jl. Merdeka 10')

    def test_kolom_tanpa_padanan_tidak_ditulis_ke_hr(self):
        self._tarik([employee_row()])
        hr = self._hr('iksg-rangga')

        # `bagian` kini dipetakan ke jabatan — keputusan sadar (permintaan
        # integrasi native), jadi penahannya di sini diperbarui.
        self.assertEqual(hr.job_title, 'Operasional')
        # `grup`, `can_approve`, dan `department_id` tetap tanpa padanan. Kalau
        # suatu saat dipetakan, itu keputusan sadar dan baris ini yang menahannya.
        self.assertFalse(hr.department_id)

    def test_memperbarui_pegawai_yang_sudah_ada(self):
        self._tarik([employee_row()])
        summary, _error = self._tarik([employee_row(name='rangga baru', email='baru@example.com')])

        self.assertEqual(summary['updated'], 1)
        self.assertEqual(self.Hr.with_context(active_test=False).search_count([]), 1)
        hr = self._hr('iksg-rangga')
        self.assertEqual(hr.name, 'rangga baru')
        self.assertEqual(hr.work_email, 'baru@example.com')

    def test_tidak_menulis_bila_tidak_ada_yang_berubah(self):
        self._tarik([employee_row()])
        summary, _error = self._tarik([employee_row()])

        self.assertEqual(summary['updated'], 0)
        self.assertEqual(summary['unchanged'], 1)

    def test_mencocokkan_pegawai_yang_sudah_ada_lewat_nopeg(self):
        # Pegawai sudah ada di Odoo dengan data lain; harus dipakai, bukan
        # dibuatkan yang baru.
        ada = self.Hr.create({'name': 'nama lama di odoo', 'presenly_nopeg': 'iksg-rangga'})

        summary, _error = self._tarik([employee_row()])

        self.assertEqual(summary['created'], 0)
        self.assertEqual(self.Hr.with_context(active_test=False).search_count([]), 1)
        ada.invalidate_recordset()
        self.assertEqual(ada.name, 'rangga')

    def test_mencatat_jejak_sinkronisasi(self):
        self._tarik([employee_row()])
        hr = self._hr('iksg-rangga')

        self.assertTrue(hr.presenly_synced_at)
        self.assertEqual(
            hr.presenly_source_updated_at,
            self.Mirror.search([]).source_updated_at,
        )

    def test_menautkan_cermin_ke_pegawai_odoo(self):
        self._tarik([employee_row()])
        row = self.Mirror.search([])

        self.assertEqual(row.hr_employee_id, self._hr('iksg-rangga'))
        self.assertEqual(row.synced_state, 'linked')

    def test_nopeg_ganda_tidak_dipilihkan_salah_satu(self):
        self.Hr.create({'name': 'orang pertama', 'presenly_nopeg': 'iksg-rangga'})
        self.Hr.create({'name': 'orang kedua', 'presenly_nopeg': 'iksg-rangga'})

        summary, _error = self._tarik([employee_row()])

        self.assertEqual(summary['created'], 0)
        self.assertEqual(summary['updated'], 0)
        # Dibandingkan lewat `_()` yang sama dengan modul, bukan teks Inggris
        # langsung: tes tidak boleh bergantung pada bahasa pengguna. Di
        # lingkungan tes `env.lang` kosong, jadi `self.env._()` akan
        # mengembalikan teks sumber dan gagal di bahasa lain.
        self.assertEqual(
            summary['skipped'],
            [_('%(name)s (nopeg %(nopeg)s): more than one Odoo employee carries '
               'this nopeg, so none was touched.',
               name='rangga', nopeg='iksg-rangga')],
        )


@tagged('post_install', '-at_install')
class TestPresenlyEmployeeActive(TestPresenlyEmployeeSyncBase):
    """Status aktif: satu aturan, dan satu pengecualian yang disengaja."""

    def test_menonaktifkan_pegawai_tanpa_akun_pengguna(self):
        self._tarik([employee_row()])
        self._tarik([employee_row(is_active=False)])

        hr = self._hr('iksg-rangga')
        self.assertFalse(hr.active)

    def test_menolak_menonaktifkan_pegawai_yang_punya_akun(self):
        pengguna = self.env['res.users'].create({
            'name': 'Rangga', 'login': 'rangga.uji',
        })
        self._tarik([employee_row()])
        self._hr('iksg-rangga').write({'user_id': pengguna.id})

        summary, _error = self._tarik([employee_row(is_active=False)])

        # Menonaktifkan berarti mencabut akses orang itu tanpa peringatan di
        # Odoo. Itu harus keputusan di Odoo, bukan efek samping tarikan.
        self.assertTrue(self._hr('iksg-rangga').active)
        self.assertEqual(len(summary['refused']), 1)

    def test_pegawai_baru_yang_tidak_aktif_di_presenly(self):
        # Dibuat dulu (selalu aktif), lalu aturan aktif diterapkan.
        summary, _error = self._tarik([employee_row(is_active=False)])

        self.assertEqual(summary['created'], 1)
        self.assertFalse(self._hr('iksg-rangga').active)

    def test_aktifkan_kembali(self):
        self._tarik([employee_row(is_active=False)])
        self._tarik([employee_row(is_active=True)])

        self.assertTrue(self._hr('iksg-rangga').active)


@tagged('post_install', '-at_install')
class TestPresenlyEmployeePull(TestPresenlyEmployeeSyncBase):
    """Penarikan lewat tombol: galat dilaporkan, bukan dilempar."""

    def test_galat_koneksi_dikembalikan_sebagai_nilai(self):
        failure = SaasClientError('down', code='NETWORK_ERROR')
        with patch.object(PresenlySaasClient, 'get_resource', side_effect=failure):
            summary, error = self.config._pull_employees()

        self.assertTrue(error)
        self.assertEqual(summary, {})
        log = self.env['presenly.saas.sync.log'].search([], order='id desc', limit=1)
        self.assertFalse(log.success)

    def test_notifikasi_melaporkan_jumlah(self):
        def fake_resource(resource, params=None):
            return {'data': [employee_row()], 'meta': {'total': 1, 'total_pages': 1}}

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource):
            result = self.config.action_pull_employees()

        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(result['params']['type'], 'success')
        self.assertIn(_('Employee pull finished'), result['params']['title'])

    def test_notifikasi_memperingatkan_yang_ditolak(self):
        pengguna = self.env['res.users'].create({'name': 'R', 'login': 'r.uji'})
        self._tarik([employee_row()])
        self._hr('iksg-rangga').write({'user_id': pengguna.id})

        def fake_resource(resource, params=None):
            return {'data': [employee_row(is_active=False)], 'meta': {'total': 1, 'total_pages': 1}}

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource):
            result = self.config.action_pull_employees()

        self.assertEqual(result['params']['type'], 'warning')
        self.assertIn(
            _('Needs a decision in Odoo:\n%s',
              _('%(name)s: Presenly marks this employee inactive, but the Odoo '
                'employee has a user account. Deactivate it in Odoo if that is '
                'really intended.', name='rangga')),
            result['params']['message'],
        )

    def test_terpasang_di_cron_sendiri(self):
        # Sinkronisasi pegawai menyentuh hr.employee, jadi ia punya cron
        # terpisah: kegagalannya tidak boleh menghentikan penarikan presensi,
        # dan sebaliknya.
        crons = self.env['ir.cron'].search([('name', '=', 'Presenly SaaS: Sync Employees')])
        self.assertEqual(len(crons), 1)
        self.assertIn('_cron_sync_employees_all', crons.code)

    def test_cron_tidak_melempar_saat_galat(self):
        failure = SaasClientError('down', code='NETWORK_ERROR')
        with patch.object(PresenlySaasClient, 'get_resource', side_effect=failure):
            self.assertTrue(self.env['presenly.saas.config']._cron_sync_employees_all())

    def test_cron_melewati_koneksi_nonaktif(self):
        self.config.write({'enabled': False})
        with patch.object(PresenlySaasClient, 'get_resource') as panggil:
            self.env['presenly.saas.config']._cron_sync_employees_all()
        panggil.assert_not_called()


@tagged('post_install', '-at_install')
class TestPresenlyEmployeePush(TestPresenlyEmployeeSyncBase):
    """Arah balik: suntingan di Odoo dikirim ke Presenly."""

    def test_suntingan_odoo_dikirim_balik(self):
        self._tarik([employee_row()])
        hr = self._hr('iksg-rangga')
        hr.write({'work_phone': '0899999999'})

        summary, _error = self._tarik([employee_row()])

        self.assertEqual(len(self.terkirim), 1)
        self.assertEqual(self.terkirim[0]['nopeg'], 'iksg-rangga')
        # Hanya kolom yang berubah yang dikirim. Mengirim seluruh objek akan
        # menghapus kolom yang tidak dikirim di sisi server.
        self.assertEqual(self.terkirim[0]['payload'], {'phone': '0899999999'})
        self.assertEqual(summary['push']['pushed'], 1)

    def test_tanpa_suntingan_tidak_mengirim_apa_pun(self):
        self._tarik([employee_row()])
        self.terkirim = []

        summary, _error = self._tarik([employee_row()])

        self.assertEqual(self.terkirim, [])
        self.assertEqual(summary['push']['pushed'], 0)

    def test_tanggal_lahir_tidak_memicu_kiriman_palsu(self):
        # Snapshot disimpan sebagai JSON, dan JSON tidak mengenal tipe tanggal.
        # Tanpa penyeragaman, setiap tarikan akan mengira tanggalnya berubah.
        self._tarik([employee_row()])
        self.terkirim = []

        self._tarik([employee_row()])
        self._tarik([employee_row()])

        self.assertEqual(self.terkirim, [])

    def test_is_active_tidak_pernah_dikirim_balik(self):
        self._tarik([employee_row()])
        hr = self._hr('iksg-rangga')
        hr.write({'active': False})

        self._tarik([employee_row()])

        for kiriman in self.terkirim:
            self.assertNotIn('is_active', kiriman['payload'])
        # Status aktif dimiliki Presenly; menonaktifkan di Odoo tidak boleh
        # mencabut akses pegawai di aplikasi Presenly.
        self.assertIn('is_active', self.env['presenly.saas.employee']._fields)

    def test_snapshot_diperbarui_setelah_kirim(self):
        self._tarik([employee_row()])
        hr = self._hr('iksg-rangga')
        hr.write({'work_phone': '08111'})
        self._tarik([employee_row()])
        self.terkirim = []

        # Kiriman pertama sudah memperbarui snapshot, jadi tarikan berikutnya
        # tidak boleh mengirim ulang hal yang sama.
        self._tarik([employee_row()])

        self.assertEqual(self.terkirim, [])

    def test_kegagalan_satu_pegawai_dilaporkan_dan_tidak_menghentikan_yang_lain(self):
        self._tarik([employee_row(), employee_row(id=6, nopeg='iksg-yusril', name='yusril')])
        for hr in self.env['hr.employee'].with_context(active_test=False).search([]):
            hr.write({'work_phone': '08000'})

        def fake_update(nopeg, payload=None):
            if nopeg == 'iksg-rangga':
                raise SaasClientError('ditolak', code='HTTP_ERROR', http_status=400)
            return {'data': {'nopeg': nopeg, 'updated_at': '2026-09-21T03:00:00.000Z'}, 'meta': {}}

        def fake_resource(resource, params=None):
            return {'data': [employee_row(), employee_row(id=6, nopeg='iksg-yusril', name='yusril')],
                    'meta': {'total': 2, 'total_pages': 1}}

        with patch.object(PresenlySaasClient, 'get_resource', side_effect=fake_resource), \
             patch.object(PresenlySaasClient, 'update_employee', side_effect=fake_update):
            summary, error = self.config._pull_employees()

        self.assertFalse(error)
        self.assertEqual(summary['push']['pushed'], 1)
        self.assertEqual(len(summary['push']['failed']), 1)
        self.assertIn('iksg-rangga', summary['push']['failed'][0])

    def test_pegawai_yang_sama_berubah_di_kedua_sisi(self):
        self._tarik([employee_row()])
        self.terkirim = []
        hr = self._hr('iksg-rangga')
        hr.write({'work_phone': '08777'})

        # Presenly juga berubah: nopeg sama, `updated_at` baru, dan namanya beda.
        summary, _error = self._tarik([
            employee_row(name='rangga dari presenly', updated_at='2026-09-21T05:00:00.000Z'),
        ])

        # Tidak ada cara andal membandingkan jam dua server, jadi Presenly
        # menang dan bentroknya dilaporkan — bukan diabaikan diam-diam.
        self.assertEqual(len(summary['conflicts']), 1)
        self.terkirim = []
        self.assertEqual(self._hr('iksg-rangga').name, 'rangga dari presenly')


@tagged('post_install', '-at_install')
class TestPresenlyEmployeeTrigger(TestPresenlyEmployeeSyncBase):
    """Kirim balik saat disimpan, bukan menunggu jadwal."""

    def _pasang(self, terkirim):
        def fake_update(nopeg, payload=None):
            terkirim.append({'nopeg': nopeg, 'payload': payload})
            return {'data': {'nopeg': nopeg, 'updated_at': '2026-09-21T03:00:00.000Z'}, 'meta': {}}

        return patch.object(PresenlySaasClient, 'update_employee', side_effect=fake_update)

    def _jalankan_tertunda(self):
        """Jalankan pekerjaan pasca-commit secara manual.

        Di dalam tes transaksinya tidak pernah commit, jadi antreannya tidak
        pernah berjalan sendiri. Yang diuji di sini isi antrean itu.
        """
        self.env.cr.postcommit.run()

    def test_menyimpan_pegawai_langsung_mengirim(self):
        self._tarik([employee_row()])
        hr = self._hr('iksg-rangga')
        terkirim = []

        with self._pasang(terkirim):
            hr.write({'work_phone': '0899'})
            self._jalankan_tertunda()

        self.assertEqual(len(terkirim), 1)
        self.assertEqual(terkirim[0]['payload'], {'phone': '0899'})

    def test_menyimpan_kolom_yang_tidak_disinkronkan_tidak_mengirim(self):
        self._tarik([employee_row()])
        hr = self._hr('iksg-rangga')
        terkirim = []

        with self._pasang(terkirim):
            hr.write({'job_title': 'Manajer'})
            self._jalankan_tertunda()

        self.assertEqual(terkirim, [])

    def test_sinkronisasi_tidak_memicu_kiriman_berulang(self):
        # Ini penjagaan terpenting: tarikan menulis ke model yang sama dengan
        # yang dipakai pengguna, jadi tanpa penanda setiap tarikan akan
        # mengirim balik nilai yang baru saja diterima dari Presenly.
        self._tarik([employee_row()])
        terkirim = []

        with self._pasang(terkirim):
            self._tarik([employee_row(name='berubah di presenly',
                                      updated_at='2026-09-21T06:00:00.000Z')])
            self._jalankan_tertunda()

        self.assertEqual(terkirim, [])
        self.assertEqual(self._hr('iksg-rangga').name, 'berubah di presenly')

    def test_kegagalan_kirim_tidak_menggagalkan_penyimpanan(self):
        self._tarik([employee_row()])
        hr = self._hr('iksg-rangga')

        def gagal(_nopeg, payload=None):
            raise SaasClientError('down', code='NETWORK_ERROR')

        with patch.object(PresenlySaasClient, 'update_employee', side_effect=gagal):
            hr.write({'work_phone': '0877'})
            self._jalankan_tertunda()   # tidak boleh melempar

        self.assertEqual(hr.work_phone, '0877')

    def test_pegawai_tanpa_nopeg_dilewati(self):
        hr = self.Hr.create({'name': 'Tanpa Nopeg'})
        terkirim = []

        with self._pasang(terkirim):
            hr.write({'work_phone': '0812'})
            self._jalankan_tertunda()

        self.assertEqual(terkirim, [])

    def test_koneksi_nonaktif_tidak_mengirim(self):
        self._tarik([employee_row()])
        self.config.write({'enabled': False})
        hr = self._hr('iksg-rangga')
        terkirim = []

        with self._pasang(terkirim):
            hr.write({'work_phone': '0813'})
            self._jalankan_tertunda()

        self.assertEqual(terkirim, [])


class TestPresenlyEmployeeManualLink(TestPresenlyEmployeeSyncBase):
    """Nopeg yang diketik di form pegawai menautkan dan menerapkan datanya.

    Ini bagian dari keputusan identitas persetujuan: nopeg adalah satu-satunya
    kunci yang dipakai, jadi pegawai Odoo harus bisa ditautkan ke nopeg yang
    benar walaupun tarikan tidak menemukannya sendiri.
    """

    def _cermin_belum_tertaut(self, nopeg, nama='rangga'):
        """Baris cermin yang belum punya padanan `hr.employee`.

        Dibuat langsung, bukan lewat tarikan: tarikan akan membuat sendiri
        pegawainya, sehingga nopeg-nya sudah terpakai dan kasus yang mau diuji
        tidak pernah terjadi. Keadaan ini nyata — cermin sudah memuat pegawai
        sementara Odoo belum punya padanannya, misalnya karena pegawai di Odoo
        dibuat lebih dulu dengan nomor yang keliru.
        """
        return self.env['presenly.saas.employee'].create({
            'external_id': abs(hash(nopeg)) % 100000,
            'nopeg': nopeg,
            'name': nama,
            'email': '%s@example.com' % nopeg,
            'is_active': True,
            'company_id': self.config.company_id.id,
        })

    def test_nopeg_yang_diketik_menautkan_dan_menerapkan_data(self):
        cermin = self._cermin_belum_tertaut('uji-bebas')
        hr = self.env['hr.employee'].create({'name': 'Pegawai Lokal'})

        hr.write({'presenly_nopeg': 'uji-bebas'})

        self.assertEqual(
            hr.name, 'rangga',
            'data cermin untuk nopeg itu langsung diterapkan',
        )
        self.assertEqual(
            cermin.hr_employee_id, hr, 'cerminnya menunjuk balik ke pegawai ini',
        )

    def test_nopeg_saat_pembuatan_tidak_diperiksa(self):
        """Pegawai Odoo boleh dibuat lebih dulu, sebelum cerminnya ada.

        Tarikan berikutnya yang mencocokkannya lewat nopeg (lihat
        `test_mencocokkan_pegawai_yang_sudah_ada_lewat_nopeg`). Kalau pembuatan
        ikut diperiksa, alur yang sah itu jadi terblokir.
        """
        hr = self.env['hr.employee'].create({
            'name': 'Pegawai Odoo Lebih Dulu', 'presenly_nopeg': 'uji-nanti',
        })

        self.assertEqual(hr.name, 'Pegawai Odoo Lebih Dulu')
        self.assertEqual(hr.presenly_nopeg, 'uji-nanti')
        self.assertFalse(
            self.env['presenly.saas.employee'].search([('nopeg', '=', 'uji-nanti')]),
            'belum ada cerminnya, dan itu bukan kesalahan',
        )

    def test_nopeg_yang_sudah_dipakai_pegawai_lain_ditolak(self):
        """Dua pegawai dengan nopeg sama membuat sinkronisasi menolak menyentuh
        keduanya, jadi nomor itu tidak boleh disimpan di sini."""
        from odoo.exceptions import UserError

        self._cermin_belum_tertaut('uji-rebutan')
        pertama = self.env['hr.employee'].create({
            'name': 'Pegawai Pertama', 'presenly_nopeg': 'uji-rebutan',
        })
        kedua = self.env['hr.employee'].create({'name': 'Pegawai Kedua'})

        with self.assertRaises(UserError):
            kedua.write({'presenly_nopeg': 'uji-rebutan'})
        self.assertEqual(kedua.presenly_nopeg, False, 'nomornya tidak tersimpan')
        self.assertEqual(pertama.presenly_nopeg, 'uji-rebutan')

    def test_nopeg_yang_belum_ditarik_ditolak(self):
        """Nopeg tanpa pasangan di cermin akan membuat duplikat saat tarikan
        berikutnya, jadi penyimpanannya ditolak — bukan disimpan diam-diam."""
        from odoo.exceptions import UserError

        # Lewat `write`, bukan `create`: pemeriksaannya memang di situ — saat
        # nopeg pegawai yang sudah ada diubah, bukan saat pegawai baru dibuat.
        hr = self.env['hr.employee'].create({'name': 'Pegawai Lokal'})
        with self.assertRaises(UserError):
            hr.write({'presenly_nopeg': 'tidak-ada-di-cermin'})

    def test_sinkronisasi_sendiri_tidak_memicu_penautan_ulang(self):
        """Penulisan dari tarikan dilewati, supaya tidak berputar."""
        self._tarik([employee_row()])
        hr = self._hr('iksg-rangga')

        # Menuliskan nopeg yang sama di dalam konteks sinkronisasi tidak melempar.
        hr.with_context(presenly_skip_push=True).write({'presenly_nopeg': 'iksi-tidak-ada'})
        self.assertEqual(hr.presenly_nopeg, 'iksi-tidak-ada')


class TestPresenlyEmployeeManager(TestPresenlyEmployeeSyncBase):
    """Atasan langsung dari Presenly, untuk mencocokkan level `direct_manager`.

    Server tidak mengirim siapa atasan seorang pemohon — itu bergantung pada
    pemohonnya. Tetapi tiap pegawai membawa atasannya sendiri di payload, jadi
    hubungannya disalin dari sana. Dengan begitu level persetujuan bertipe atasan
    langsung bisa dicocokkan ke pengguna Odoo tanpa aturan baru.
    """

    def _bawahan(self, manager_nopeg, nopeg='bawahan-1'):
        return employee_row(
            id=12, nopeg=nopeg, name='Bawahan',
            manager={'id': 11, 'nopeg': manager_nopeg, 'name': 'Atasan'},
        )

    def test_atasan_diterapkan_dari_cermin(self):
        self._tarik([employee_row(id=11, nopeg='atasan-1', name='Atasan', manager=None)])
        atasan = self._hr('atasan-1')

        self._tarik([self._bawahan('atasan-1')])

        self.assertEqual(
            self._hr('bawahan-1').parent_id, atasan,
            'atasan dari payload disalin ke pegawai native',
        )

    def test_atasan_yang_belum_tertaut_dibiarkan_kosong(self):
        """Menebak dari nama akan salah orang, jadi dibiarkan kosong."""
        self._tarik([self._bawahan('atasan-yang-belum-ada')])

        self.assertFalse(self._hr('bawahan-1').parent_id)

    def test_suntingan_atasan_di_odoo_tidak_ditimpa(self):
        """Selama atasannya tidak berubah di Presenly, yang di Odoo dibiarkan.

        Sama seperti kolom lain: yang menimpa suntingan pengguna tanpa jejak
        adalah kelalaian yang justru dihindari di modul ini.
        """
        self._tarik([employee_row(id=11, nopeg='atasan-1', name='Atasan', manager=None)])
        self._tarik([self._bawahan('atasan-1')])
        bawahan = self._hr('bawahan-1')

        atasan_pilihan = self.env['hr.employee'].create({'name': 'Atasan Pilihan HR'})
        bawahan.write({'parent_id': atasan_pilihan.id})

        # Tarikan berikutnya, isi Presenly tidak berubah.
        self._tarik([employee_row(id=11, nopeg='atasan-1', name='Atasan', manager=None)])
        self._tarik([self._bawahan('atasan-1')])

        self.assertEqual(
            self._hr('bawahan-1').parent_id, atasan_pilihan,
            'suntingan atasan di Odoo tidak boleh ditimpa selama Presenly tidak berubah',
        )

    def test_atasan_yang_berubah_di_presenly_diterapkan(self):
        self._tarik([employee_row(id=11, nopeg='atasan-1', name='Atasan', manager=None)])
        self._tarik([employee_row(id=13, nopeg='atasan-2', name='Atasan Baru', manager=None)])
        self._tarik([self._bawahan('atasan-1')])

        self._tarik([self._bawahan('atasan-2')])

        self.assertEqual(self._hr('bawahan-1').parent_id, self._hr('atasan-2'))

    def test_perubahan_atasan_saja_tetap_diterapkan(self):
        """Tanpa pemeriksaan terpisah, perubahan atasan saja tidak akan pernah
        diterapkan — karena atasan tidak termasuk kolom bersama."""
        self._tarik([employee_row(id=11, nopeg='atasan-1', name='Atasan', manager=None)])
        self._tarik([self._bawahan('atasan-1')])
        bawahan = self._hr('bawahan-1')
        self.assertEqual(bawahan.parent_id, self._hr('atasan-1'))

        self._tarik([employee_row(id=13, nopeg='atasan-2', name='Atasan Baru', manager=None)])
        self._tarik([self._bawahan('atasan-2')])

        self.assertEqual(bawahan.parent_id, self._hr('atasan-2'))


class TestPresenlyEmployeeFullMapping(TestPresenlyEmployeeSyncBase):
    """Kolom yang tadinya hanya ada di cermin kini punya rumah di `hr.employee`.

    Arahnya sesuai kesepakatan: Presenly pemilik data kepegawaian, Odoo
    mencerminkannya. Yang dijaga tes ini adalah dua keputusan yang mahal kalau
    dilanggar — `role` bukan hak akses, dan PII tidak terhapus oleh tarikan yang
    tidak memintanya.
    """

    def _tarik_lengkap(self, **overrides):
        row = employee_row(shift={'id': 2, 'name': 'Normal 2'}, **overrides)
        self._tarik([row])
        return self._hr(row['nopeg'])

    def test_kolom_tanpa_padanan_native_ikut_diterapkan(self):
        hr = self._tarik_lengkap()

        self.assertEqual(hr.presenly_group, 'Grup 1')
        self.assertTrue(hr.presenly_can_approve)
        self.assertEqual(hr.presenly_role, 'Supervisor')
        self.assertEqual(hr.presenly_shift, 'Normal 2')

    def test_role_adalah_kolom_biasa_bukan_hak_akses(self):
        """Kalau peran dari aplikasi menjadi grup Odoo, satu perubahan di sana
        bisa memberi orang izin yang tidak pernah disetujui siapa pun di Odoo."""
        bidang = self.env['hr.employee']._fields['presenly_role']

        self.assertEqual(
            bidang.type, 'char',
            'peran dari Presenly harus tetap kolom biasa, bukan relasi ke grup',
        )

    def test_bentrok_kolom_baru_dilaporkan(self):
        hr = self._tarik_lengkap()
        hr.write({'presenly_group': 'Grup dari Odoo'})

        ringkas, _error = self._tarik([employee_row(
            shift={'id': 2, 'name': 'Normal 2'}, grup='Grup dari Presenly',
        )])

        self.assertEqual(len(ringkas['conflicts']), 1)
        self.assertEqual(hr.presenly_group, 'Grup dari Presenly', 'Presenly yang dipakai')

    def test_pii_tidak_terhapus_tarikan_tanpa_include_pii(self):
        """Tarikan yang tidak meminta PII tidak memuat kolomnya. Menulisnya
        sebagai kosong akan menghapus data yang sudah ada — bukan karena berubah,
        hanya karena tidak ditanyakan."""
        hr = self._tarik_lengkap()
        hr.write({'presenly_no_npwp': '09.123.456.7-890.000'})

        # Tarikan berikutnya tanpa PII di payload.
        self._tarik([employee_row(shift={'id': 2, 'name': 'Normal 2'})])

        self.assertEqual(hr.presenly_no_npwp, '09.123.456.7-890.000')

    def test_pii_terisi_bila_memang_dikirim(self):
        hr = self._tarik_lengkap(no_npwp='09.999.888.7-777.000')

        self.assertEqual(hr.presenly_no_npwp, '09.999.888.7-777.000')
