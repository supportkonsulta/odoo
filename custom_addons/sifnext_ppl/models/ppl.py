from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class SifnextPPL(models.Model):
    _name = "sifnext.ppl"
    _description = "Permintaan Pembayaran Langsung"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "request_date desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    request_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    applicant_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user,
        readonly=True, tracking=True,
    )
    partner_id = fields.Many2one("res.partner", string="Penerima/Vendor", tracking=True)
    title = fields.Char(required=True, tracking=True)
    description = fields.Text(required=True)
    source_type = fields.Selection(
        [("manual", "Pegawai"), ("finance", "Finance"), ("payroll", "Payroll")],
        required=True, default="manual", tracking=True,
    )
    line_ids = fields.One2many("sifnext.ppl.line", "ppl_id", string="Detail", copy=True)
    total_amount = fields.Monetary(compute="_compute_total_amount", store=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        index=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Diajukan"),
            ("verified", "Diverifikasi"),
            ("approved", "Disetujui"),
            ("paid", "Dibayar"),
            ("done", "Selesai"),
        ],
        required=True, default="draft", copy=False, tracking=True, index=True,
    )
    return_reason = fields.Text(readonly=True, tracking=True)
    payment_method = fields.Selection(
        [("cash", "Kas"), ("bank", "Bank")], string="Metode Pembayaran", tracking=True,
    )
    payment_date = fields.Date(string="Tanggal Pembayaran", tracking=True)
    payment_reference = fields.Char(string="Referensi Pembayaran", tracking=True)
    submitted_by = fields.Many2one("res.users", readonly=True, copy=False)
    submitted_at = fields.Datetime(readonly=True, copy=False)
    verified_by = fields.Many2one("res.users", readonly=True, copy=False)
    verified_at = fields.Datetime(readonly=True, copy=False)
    approved_by = fields.Many2one("res.users", readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    paid_by = fields.Many2one("res.users", readonly=True, copy=False)
    paid_at = fields.Datetime(readonly=True, copy=False)
    done_by = fields.Many2one("res.users", readonly=True, copy=False)
    done_at = fields.Datetime(readonly=True, copy=False)

    @api.depends("line_ids.subtotal")
    def _compute_total_amount(self):
        for record in self:
            record.total_amount = sum(record.line_ids.mapped("subtotal"))

    @api.constrains("line_ids")
    def _check_positive_lines(self):
        for record in self:
            if any(line.subtotal <= 0 for line in record.line_ids):
                raise ValidationError(_("Nilai setiap detail PPL harus lebih dari nol."))

    @api.model_create_multi
    def create(self, vals_list):
        is_finance = self.env.user.has_group("sifnext_ppl.group_ppl_finance")
        for vals in vals_list:
            if not is_finance and vals.get("applicant_id", self.env.user.id) != self.env.user.id:
                raise AccessError(_("Pegawai hanya dapat membuat PPL atas nama sendiri."))
            if not is_finance:
                vals["applicant_id"] = self.env.user.id
                vals["source_type"] = "manual"
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("sifnext.ppl") or "New"
        return super().create(vals_list)

    def write(self, vals):
        if "name" in vals and any(record.name != vals["name"] for record in self):
            raise UserError(_("Nomor PPL tidak dapat diubah."))
        workflow_fields = {
            "state", "return_reason", "submitted_by", "submitted_at", "verified_by", "verified_at",
            "approved_by", "approved_at", "paid_by", "paid_at", "done_by", "done_at",
        }
        if workflow_fields.intersection(vals) and not self.env.context.get("ppl_workflow_write"):
            raise AccessError(_("Status dan audit workflow hanya dapat diubah melalui tindakan PPL."))
        if "applicant_id" in vals and not self.env.user.has_group("sifnext_ppl.group_ppl_finance"):
            if vals["applicant_id"] != self.env.user.id:
                raise AccessError(_("Pegawai tidak dapat mengubah pemohon PPL."))
        protected = {
            "request_date", "applicant_id", "partner_id", "title", "description",
            "source_type", "line_ids",
        }
        if protected.intersection(vals) and any(record.state != "draft" for record in self):
            raise UserError(_("Data pengajuan hanya dapat diubah pada status Draft."))
        payment_fields = {"payment_method", "payment_date", "payment_reference"}
        if payment_fields.intersection(vals):
            if not self.env.user.has_group("sifnext_ppl.group_ppl_finance"):
                raise AccessError(_("Hanya Keuangan yang dapat mengisi data pembayaran."))
            if any(record.state != "approved" for record in self):
                raise UserError(_("Data pembayaran hanya dapat diisi pada PPL Disetujui."))
        return super().write(vals)

    def _workflow_write(self, vals):
        return self.with_context(ppl_workflow_write=True).write(vals)

    def unlink(self):
        if any(record.state != "draft" for record in self):
            raise UserError(_("Hanya PPL Draft yang dapat dihapus."))
        return super().unlink()

    def _check_submit_data(self):
        for record in self:
            if not record.line_ids:
                raise ValidationError(_("PPL harus memiliki minimal satu detail."))
            if any(line.subtotal <= 0 for line in record.line_ids):
                raise ValidationError(_("Nilai setiap detail PPL harus lebih dari nol."))

    def _check_finance_group(self):
        if not self.env.user.has_group("sifnext_ppl.group_ppl_finance"):
            raise AccessError(_("Hanya Finance yang dapat melakukan tindakan ini."))

    def _check_group(self, xmlid, message):
        if not self.env.user.has_group(xmlid):
            raise AccessError(_(message))

    def _prepare_integration_payload(self):
        """Return the versioned, primitive-only contract consumed by downstream addons."""
        self.ensure_one()
        return {
            "schema_version": 1,
            "event": "ppl.paid",
            "idempotency_key": f"ppl.paid:{self.company_id.id}:{self.id}",
            "ppl": {
                "id": self.id,
                "number": self.name,
                "state": self.state,
                "source_type": self.source_type,
                "request_date": fields.Date.to_string(self.request_date),
                "title": self.title,
                "description": self.description,
                "applicant": {
                    "id": self.applicant_id.id,
                    "name": self.applicant_id.name,
                },
                "partner": {
                    "id": self.partner_id.id,
                    "name": self.partner_id.name,
                } if self.partner_id else None,
                "company": {
                    "id": self.company_id.id,
                    "name": self.company_id.name,
                },
                "currency": {
                    "id": self.currency_id.id,
                    "name": self.currency_id.name,
                },
                "total_amount": self.total_amount,
                "payment": {
                    "method": self.payment_method,
                    "date": fields.Date.to_string(self.payment_date),
                    "reference": self.payment_reference,
                    "paid_by_id": self.paid_by.id,
                    "paid_at": fields.Datetime.to_string(self.paid_at),
                },
                "lines": [{
                    "id": line.id,
                    "sequence": line.sequence,
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "amount": line.subtotal,
                    "account": {
                        "id": line.account_id.id,
                        "code": line.account_id.code,
                        "name": line.account_id.name,
                    },
                } for line in self.line_ids.sorted(key=lambda item: (item.sequence, item.id))],
            },
        }

    def _prepare_budget_check_payload(self):
        """Return budget inputs without assuming the technical model used by RKA."""
        self.ensure_one()
        return {
            "schema_version": 1,
            "ppl_id": self.id,
            "ppl_number": self.name,
            "company_id": self.company_id.id,
            "request_date": fields.Date.to_string(self.request_date),
            "currency_id": self.currency_id.id,
            "total_amount": self.total_amount,
            "lines": [{
                "line_id": line.id,
                "account_id": line.account_id.id,
                "amount": line.subtotal,
            } for line in self.line_ids],
        }

    def _validate_rka_budget(self, payload):
        """RKA extension point; raise ValidationError when budget is unavailable."""
        return True

    def _check_budget(self):
        self.ensure_one()
        return self._validate_rka_budget(self._prepare_budget_check_payload())

    def _notify_rka_paid(self, payload):
        """RKA extension point for idempotent realization after payment."""
        return True

    def _notify_general_ledger_paid(self, payload):
        """General Ledger extension point; PPL itself never creates a journal entry."""
        return True

    def _on_ppl_paid(self):
        """Dispatch the paid event in the same transaction as the state transition."""
        self.ensure_one()
        payload = self._prepare_integration_payload()
        self._notify_rka_paid(payload)
        self._notify_general_ledger_paid(payload)
        return True

    def action_submit(self):
        is_finance = self.env.user.has_group("sifnext_ppl.group_ppl_finance")
        for record in self:
            if record.state != "draft":
                raise UserError(_("Hanya PPL Draft yang dapat diajukan."))
        self._check_submit_data()
        submitted_at = fields.Datetime.now()
        values = {
            "state": "submitted",
            "submitted_by": self.env.user.id,
            "submitted_at": submitted_at,
            "return_reason": False,
        }
        if is_finance:
            for record in self:
                if any(not line.account_id for line in record.line_ids):
                    raise ValidationError(_("Keuangan harus memilih COA untuk seluruh detail sebelum mengajukan PPL."))
                record._check_budget()
            values.update({
                "state": "verified",
                "verified_by": self.env.user.id,
                "verified_at": submitted_at,
            })
        self._workflow_write(values)

    def action_verify(self):
        self._check_finance_group()
        for record in self:
            if record.state != "submitted":
                raise UserError(_("Hanya PPL Diajukan yang dapat diverifikasi."))
            if any(not line.account_id for line in record.line_ids):
                raise ValidationError(_("Finance harus memilih COA untuk seluruh detail sebelum verifikasi."))
            record._check_budget()
        self._workflow_write({
            "state": "verified",
            "verified_by": self.env.user.id,
            "verified_at": fields.Datetime.now(),
        })

    def action_approve(self):
        self._check_group("sifnext_ppl.group_ppl_approver", "Hanya Direktur yang dapat menyetujui PPL.")
        for record in self:
            if record.state != "verified":
                raise UserError(_("Hanya PPL Diverifikasi yang dapat disetujui."))
            record._check_budget()
        self._workflow_write({
            "state": "approved",
            "approved_by": self.env.user.id,
            "approved_at": fields.Datetime.now(),
        })

    def action_pay(self):
        self._check_group("sifnext_ppl.group_ppl_finance", "Hanya Keuangan yang dapat mencatat pembayaran.")
        for record in self:
            if record.state != "approved":
                raise UserError(_("Hanya PPL Disetujui yang dapat dibayar."))
            if not record.payment_method or not record.payment_date or not record.payment_reference:
                raise ValidationError(_("Metode, tanggal, dan referensi pembayaran wajib diisi."))
            record._check_budget()
        self._workflow_write({
            "state": "paid",
            "paid_by": self.env.user.id,
            "paid_at": fields.Datetime.now(),
        })
        for record in self:
            record._on_ppl_paid()

    def action_done(self):
        self._check_group("sifnext_ppl.group_ppl_finance", "Hanya Keuangan yang dapat menyelesaikan PPL.")
        for record in self:
            if record.state != "paid":
                raise UserError(_("Hanya PPL Dibayar yang dapat diselesaikan."))
        self._workflow_write({
            "state": "done",
            "done_by": self.env.user.id,
            "done_at": fields.Datetime.now(),
        })

    def action_return_to_draft(self):
        self._check_finance_group()
        reason = self.env.context.get("return_reason")
        if not reason:
            raise ValidationError(_("Alasan revisi wajib diisi."))
        for record in self:
            if record.state not in ("submitted", "verified"):
                raise UserError(_("PPL pada status ini tidak dapat dikembalikan."))
        self._workflow_write({"state": "draft", "return_reason": reason})


class SifnextPPLLine(models.Model):
    _name = "sifnext.ppl.line"
    _description = "Detail Permintaan Pembayaran Langsung"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    ppl_id = fields.Many2one("sifnext.ppl", required=True, ondelete="cascade", index=True)
    description = fields.Char(required=True)
    quantity = fields.Float(required=True, default=1)
    unit_price = fields.Monetary(required=True)
    subtotal = fields.Monetary(compute="_compute_subtotal", store=True)
    currency_id = fields.Many2one(related="ppl_id.currency_id", store=True)
    company_id = fields.Many2one(related="ppl_id.company_id", store=True)
    account_id = fields.Many2one(
        "account.account", string="COA",
        domain="[('company_ids', 'in', company_id)]",
    )
    budget_status = fields.Selection(
        [("unchecked", "Belum Dicek"), ("sufficient", "Cukup"), ("insufficient", "Tidak Cukup")],
        default="unchecked", readonly=True,
    )

    @api.depends("quantity", "unit_price")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.unit_price

    @api.constrains("quantity", "unit_price")
    def _check_positive_amount(self):
        for line in self:
            if line.quantity <= 0 or line.unit_price <= 0:
                raise ValidationError(_("Kuantitas dan harga satuan harus lebih dari nol."))

    @api.onchange("account_id")
    def _onchange_account_id(self):
        self.budget_status = "unchecked"

    def _check_finance_account_access(self, vals):
        if "account_id" not in vals:
            return
        if not self.env.user.has_group("sifnext_ppl.group_ppl_finance"):
            raise AccessError(_("Hanya Finance yang dapat memilih atau mengubah COA."))
        for line in self:
            if line.ppl_id.state not in ("draft", "submitted"):
                raise UserError(_("COA hanya dapat diubah sebelum PPL diverifikasi."))

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get("account_id") for vals in vals_list):
            if not self.env.user.has_group("sifnext_ppl.group_ppl_finance"):
                raise AccessError(_("Hanya Finance yang dapat memilih COA."))
        return super().create(vals_list)

    def write(self, vals):
        self._check_finance_account_access(vals)
        content_fields = {"description", "quantity", "unit_price"}
        if content_fields.intersection(vals) and any(line.ppl_id.state != "draft" for line in self):
            raise UserError(_("Detail kebutuhan hanya dapat diubah pada status Draft."))
        return super().write(vals)

    def unlink(self):
        if any(line.ppl_id.state != "draft" for line in self):
            raise UserError(_("Detail hanya dapat dihapus pada status Draft."))
        return super().unlink()
