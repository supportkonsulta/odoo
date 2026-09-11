"""
SIFNEXT Operational REST Controller — Scaffold Referensi

Salin file ini ke:
  custom_addons/sifnext_operational/controllers/operational_api.py

Daftarkan di:
  custom_addons/sifnext_operational/controllers/__init__.py
    from . import operational_api

Endpoint base: /api/sifnext/v1/operational
Auth: session cookie Odoo (type='jsonrpc', auth='user')
"""

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request


class SifnextOperationalApiController(http.Controller):

    # =========================================================
    # HELPERS
    # =========================================================

    def _payload(self, params):
        if not isinstance(params, dict):
            raise ValidationError("params harus JSON object.")
        return params

    def _require_ga(self):
        user = request.env.user
        has_ga = (
            user.has_group("sifnext_operational.group_sifnext_operational_ga")
            or user.has_group("sifnext_operational.group_sifnext_operational_manager")
            or user.has_group("base.group_system")
        )
        if not has_ga:
            raise UserError("Akun ini tidak memiliki hak akses General Affair.")
        if hasattr(user, "sifnext_active_role") and user.sifnext_active_role != "ga":
            user.sudo().write({"sifnext_active_role": "ga"})

    def _serialize_room(self, room):
        return {
            "id": room.id,
            "name": room.name,
            "location": room.location or False,
            "capacity": room.capacity or 0,
            "facilities": room.facilities or False,
            "active": room.active,
        }

    def _serialize_vehicle(self, vehicle):
        return {
            "id": vehicle.id,
            "name": vehicle.name,
            "license_plate": vehicle.license_plate or False,
            "vehicle_type": vehicle.vehicle_type or False,
            "brand": vehicle.brand or False,
            "capacity": vehicle.capacity or 0,
            "description": vehicle.description or False,
            "active": vehicle.active,
        }

    def _serialize_booking(self, booking):
        return {
            "id": booking.id,
            "name": booking.name,
            "applicant_id": booking.applicant_id.id or False,
            "applicant_name": booking.applicant_id.name or False,
            "borrower_unit": booking.borrower_unit or False,
            "room_id": booking.room_id.id if hasattr(booking, "room_id") and booking.room_id else False,
            "room_name": booking.room_id.name if hasattr(booking, "room_id") and booking.room_id else False,
            "room_location": booking.room_id.location if hasattr(booking, "room_id") and booking.room_id else False,
            "vehicle_id": booking.vehicle_id.id if hasattr(booking, "vehicle_id") and booking.vehicle_id else False,
            "vehicle_name": booking.vehicle_id.name if hasattr(booking, "vehicle_id") and booking.vehicle_id else False,
            "vehicle_license_plate": booking.vehicle_id.license_plate if hasattr(booking, "vehicle_id") and booking.vehicle_id else False,
            "destination": getattr(booking, "destination", False) or False,
            "purpose": booking.purpose or False,
            "participant_count": getattr(booking, "participant_count", 0) or 0,
            "passenger_count": getattr(booking, "passenger_count", 0) or 0,
            "start_datetime": str(booking.start_datetime) if booking.start_datetime else False,
            "end_datetime": str(booking.end_datetime) if booking.end_datetime else False,
            "availability": booking.availability or False,
            "rejection_reason": booking.rejection_reason or False,
            "state": booking.state,
        }

    def _ok(self, data):
        return {"success": True, "data": data, "error": None}

    def _fail(self, message):
        return {"success": False, "data": None, "error": message}

    # =========================================================
    # MASTER: RUANGAN
    # =========================================================

    @http.route(
        "/api/sifnext/v1/operational/rooms",
        type="jsonrpc", auth="user", methods=["POST"], readonly=True,
    )
    def list_rooms(self, **params):
        rooms = request.env["sifnext.operational.room"].search(
            [("active", "=", True)], order="name asc"
        )
        return self._ok([self._serialize_room(r) for r in rooms])

    # =========================================================
    # MASTER: KENDARAAN
    # =========================================================

    @http.route(
        "/api/sifnext/v1/operational/vehicles",
        type="jsonrpc", auth="user", methods=["POST"], readonly=True,
    )
    def list_vehicles(self, **params):
        vehicles = request.env["sifnext.operational.vehicle"].search(
            [("active", "=", True)], order="name asc"
        )
        return self._ok([self._serialize_vehicle(v) for v in vehicles])

    # =========================================================
    # PENGAJUAN RUANGAN
    # =========================================================

    @http.route(
        "/api/sifnext/v1/operational/room-bookings",
        type="jsonrpc", auth="user", methods=["POST"],
    )
    def submit_room_booking(self, **params):
        payload = self._payload(params)
        room_id = payload.get("room_id")
        borrower_unit = (payload.get("borrower_unit") or "").strip()
        purpose = (payload.get("purpose") or "").strip()
        participant_count = int(payload.get("participant_count") or 0)
        start_datetime = payload.get("start_datetime")
        end_datetime = payload.get("end_datetime")

        if not room_id:
            raise ValidationError("room_id wajib diisi.")
        if not purpose:
            raise ValidationError("Keperluan wajib diisi.")
        if not start_datetime or not end_datetime:
            raise ValidationError("Waktu mulai dan selesai wajib diisi.")

        booking = request.env["sifnext.operational.room.booking"].create({
            "room_id": int(room_id),
            "borrower_unit": borrower_unit or request.env.user.employee_id.department_id.name or "-",
            "purpose": purpose,
            "participant_count": participant_count,
            "start_datetime": start_datetime,
            "end_datetime": end_datetime,
        })
        booking.action_submit()
        booking.action_check_availability()
        return self._ok(self._serialize_booking(booking))

    @http.route(
        "/api/sifnext/v1/operational/room-bookings/list",
        type="jsonrpc", auth="user", methods=["POST"], readonly=True,
    )
    def list_room_bookings(self, **params):
        user = request.env.user
        if params.get("scope") == "all" or params.get("all"):
            domain = [("state", "in", ["waiting_approval", "approved", "booked", "done"])]
        else:
            domain = [("applicant_id", "=", user.id)]
        bookings = request.env["sifnext.operational.room.booking"].search(
            domain, order="start_datetime desc, create_date desc"
        )
        return self._ok([self._serialize_booking(b) for b in bookings])

    @http.route(
        "/api/sifnext/v1/operational/room-bookings/ga-queue",
        type="jsonrpc", auth="user", methods=["POST"], readonly=True,
    )
    def ga_room_queue(self, **params):
        self._require_ga()
        bookings = request.env["sifnext.operational.room.booking"].search(
            [("state", "=", "waiting_approval")], order="create_date desc"
        )
        return self._ok([self._serialize_booking(b) for b in bookings])

    @http.route(
        "/api/sifnext/v1/operational/room-bookings/<int:booking_id>/approve",
        type="jsonrpc", auth="user", methods=["POST"],
    )
    def approve_room_booking(self, booking_id, **params):
        self._require_ga()
        booking = request.env["sifnext.operational.room.booking"].browse(booking_id).exists()
        if not booking:
            raise UserError("Pengajuan ruangan tidak ditemukan.")
        booking.action_approve()
        booking.action_book()
        return self._ok(self._serialize_booking(booking))

    @http.route(
        "/api/sifnext/v1/operational/room-bookings/<int:booking_id>/reject",
        type="jsonrpc", auth="user", methods=["POST"],
    )
    def reject_room_booking(self, booking_id, **params):
        self._require_ga()
        payload = self._payload(params)
        reason = (payload.get("reason") or "").strip()
        if not reason:
            raise ValidationError("Alasan penolakan wajib diisi.")
        booking = request.env["sifnext.operational.room.booking"].browse(booking_id).exists()
        if not booking:
            raise UserError("Pengajuan ruangan tidak ditemukan.")
        booking.write({"rejection_reason": reason})
        booking.action_reject()
        return self._ok(self._serialize_booking(booking))

    # =========================================================
    # PENGAJUAN KENDARAAN
    # =========================================================

    @http.route(
        "/api/sifnext/v1/operational/vehicle-bookings",
        type="jsonrpc", auth="user", methods=["POST"],
    )
    def submit_vehicle_booking(self, **params):
        payload = self._payload(params)
        vehicle_id = payload.get("vehicle_id")
        borrower_unit = (payload.get("borrower_unit") or "").strip()
        destination = (payload.get("destination") or "").strip()
        purpose = (payload.get("purpose") or "").strip()
        passenger_count = int(payload.get("passenger_count") or 0)
        start_datetime = payload.get("start_datetime")
        end_datetime = payload.get("end_datetime")

        if not vehicle_id:
            raise ValidationError("vehicle_id wajib diisi.")
        if not destination:
            raise ValidationError("Tujuan perjalanan wajib diisi.")
        if not purpose:
            raise ValidationError("Keperluan wajib diisi.")
        if not start_datetime or not end_datetime:
            raise ValidationError("Waktu berangkat dan pulang wajib diisi.")

        booking = request.env["sifnext.operational.vehicle.booking"].create({
            "vehicle_id": int(vehicle_id),
            "borrower_unit": borrower_unit or request.env.user.employee_id.department_id.name or "-",
            "destination": destination,
            "purpose": purpose,
            "passenger_count": passenger_count,
            "start_datetime": start_datetime,
            "end_datetime": end_datetime,
        })
        booking.action_submit()
        booking.action_check_availability()
        return self._ok(self._serialize_booking(booking))

    @http.route(
        "/api/sifnext/v1/operational/vehicle-bookings/list",
        type="jsonrpc", auth="user", methods=["POST"], readonly=True,
    )
    def list_vehicle_bookings(self, **params):
        user = request.env.user
        if params.get("scope") == "all" or params.get("all"):
            domain = [("state", "in", ["waiting_approval", "approved", "booked", "done"])]
        else:
            domain = [("applicant_id", "=", user.id)]
        bookings = request.env["sifnext.operational.vehicle.booking"].search(
            domain, order="start_datetime desc, create_date desc"
        )
        return self._ok([self._serialize_booking(b) for b in bookings])

    @http.route(
        "/api/sifnext/v1/operational/vehicle-bookings/ga-queue",
        type="jsonrpc", auth="user", methods=["POST"], readonly=True,
    )
    def ga_vehicle_queue(self, **params):
        self._require_ga()
        bookings = request.env["sifnext.operational.vehicle.booking"].search(
            [("state", "=", "waiting_approval")], order="create_date desc"
        )
        return self._ok([self._serialize_booking(b) for b in bookings])

    @http.route(
        "/api/sifnext/v1/operational/vehicle-bookings/<int:booking_id>/approve",
        type="jsonrpc", auth="user", methods=["POST"],
    )
    def approve_vehicle_booking(self, booking_id, **params):
        self._require_ga()
        booking = request.env["sifnext.operational.vehicle.booking"].browse(booking_id).exists()
        if not booking:
            raise UserError("Pengajuan kendaraan tidak ditemukan.")
        booking.action_approve()
        booking.action_book()
        return self._ok(self._serialize_booking(booking))

    @http.route(
        "/api/sifnext/v1/operational/vehicle-bookings/<int:booking_id>/reject",
        type="jsonrpc", auth="user", methods=["POST"],
    )
    def reject_vehicle_booking(self, booking_id, **params):
        self._require_ga()
        payload = self._payload(params)
        reason = (payload.get("reason") or "").strip()
        if not reason:
            raise ValidationError("Alasan penolakan wajib diisi.")
        booking = request.env["sifnext.operational.vehicle.booking"].browse(booking_id).exists()
        if not booking:
            raise UserError("Pengajuan kendaraan tidak ditemukan.")
        booking.write({"rejection_reason": reason})
        booking.action_reject()
        return self._ok(self._serialize_booking(booking))
