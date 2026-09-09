import json

from odoo.tests.common import TransactionCase


class TestPresenlyMapData(TransactionCase):
    """presenly_map_data JSON feeds the Leaflet map viewer widget."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.address = cls.env['res.partner'].create({
            'name': 'Map Office Address',
            'company_id': cls.company.id,
            'partner_latitude': -6.200000,
            'partner_longitude': 106.816666,
        })
        cls.location = cls.env['hr.work.location'].create({
            'name': 'Map Office',
            'company_id': cls.company.id,
            'address_id': cls.address.id,
            'presenly_radius_meters': 150.0,
            'presenly_gps_accuracy_limit_meters': 50.0,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Map Employee',
            'company_id': cls.company.id,
            'work_location_id': cls.location.id,
        })

    def _attendance(self, **overrides):
        values = {
            'employee_id': self.employee.id,
            'check_in': '2030-05-10 08:00:00',
            'check_out': '2030-05-10 16:00:00',
            'presenly_source': 'mobile',
            'presenly_attendance_mode': 'location',
            'presenly_company_id': self.company.id,
            'presenly_work_location_id': self.location.id,
            'in_latitude': -6.199000,
            'in_longitude': 106.815000,
            'out_latitude': -6.198000,
            'out_longitude': 106.814000,
        }
        values.update(overrides)
        attendance = self.env['hr.attendance']._presenly_mobile_create(values)
        return attendance

    def test_attendance_map_data_contains_markers(self):
        attendance = self._attendance()
        data = json.loads(attendance.presenly_map_data)
        kinds = {m['kind'] for m in data['markers']}
        self.assertIn('office', kinds)
        self.assertIn('check_in', kinds)
        self.assertIn('check_out', kinds)
        self.assertEqual(data['radius_m'], 150.0)
        office = next(m for m in data['markers'] if m['kind'] == 'office')
        self.assertAlmostEqual(office['lat'], -6.2, places=3)
        self.assertAlmostEqual(office['lon'], 106.816666, places=3)
        check_in = next(m for m in data['markers'] if m['kind'] == 'check_in')
        self.assertAlmostEqual(check_in['lat'], -6.199, places=3)
        self.assertEqual(check_in['mode'], 'location')

    def test_wfa_attendance_map_data_without_location(self):
        attendance = self._attendance(
            presenly_attendance_mode='wfa',
            presenly_work_location_id=False,
            in_latitude=False,
            in_longitude=False,
            out_latitude=False,
            out_longitude=False,
        )
        data = json.loads(attendance.presenly_map_data)
        # No coordinates -> no markers, no crash.
        self.assertEqual(data['markers'], [])
        self.assertIsNone(data['radius_m'])

    def test_location_map_data(self):
        data = json.loads(self.location.presenly_map_data)
        self.assertEqual(len(data['markers']), 1)
        office = data['markers'][0]
        self.assertEqual(office['kind'], 'office')
        self.assertEqual(office['radius'], 150.0)
        self.assertTrue(office['geofence_ready'])
        self.assertEqual(data['radius_m'], 150.0)

    def test_event_map_data(self):
        attendance = self._attendance()
        event = self.env['presenly.attendance.event'].create({
            'employee_id': self.employee.id,
            'attendance_id': attendance.id,
            'event_type': 'check_in',
            'latitude': -6.199000,
            'longitude': 106.815000,
            'accuracy': 8.0,
            'distance_from_location': 40.0,
            'work_location_id': self.location.id,
            'attendance_mode': 'location',
            'source': 'mobile',
            'validation_status': 'success',
        })
        data = json.loads(event.presenly_map_data)
        kinds = {m['kind'] for m in data['markers']}
        self.assertIn('check_in', kinds)
        self.assertIn('office', kinds)
        self.assertEqual(data['radius_m'], 150.0)
        marker = next(m for m in data['markers'] if m['kind'] == 'check_in')
        self.assertAlmostEqual(marker['lat'], -6.199, places=3)
        self.assertEqual(marker['distance_m'], 40.0)