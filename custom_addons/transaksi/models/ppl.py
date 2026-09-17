# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError, AccessError


class SifnextPPL(models.Model):
    _inherit = "sifnext.ppl"

    transaction_id = fields.Many2one(
        "transaksi.transaction",
        string="Transaksi Transfer Bank",
        readonly=True,
        copy=False,
        ondelete="set null",
        help="Tautan ke dokumen transaksi transfer bank yang memproses pembayaran ini.",
    )
    transaction_state = fields.Selection(
        related="transaction_id.state",
        string="Status Transfer Bank",
        store=True,
    )

    def _check_group(self, xmlid, message):
        if self.env.context.get("from_bank_transfer_approval"):
            return
        return super()._check_group(xmlid, message)

    def action_create_bank_transfer(self):
        """Membuat dokumen transaksi transfer tunggal dari PPL."""
        self.ensure_one()
        if not (
            self.env.user.has_group("transaksi.group_transaksi_finance")
            or self.env.user.has_group("transaksi.group_transaksi_manager")
            or self.env.user.has_group("sifnext_ppl.group_ppl_finance")
        ):
            raise AccessError(_("Hanya Bagian Keuangan atau Super User yang dapat mengajukan transfer bank."))

        if self.state != "approved":
            raise UserError(_("Pengajuan transfer bank hanya dapat dibuat untuk PPL yang telah disetujui."))
        if self.payment_method != "bank":
            raise UserError(_("Pengajuan transfer bank hanya berlaku untuk PPL dengan metode pembayaran Bank."))
        if not self.payment_dest_bank or not self.payment_dest_account_number:
            raise ValidationError(_("Nama bank tujuan dan nomor rekening penerima pada PPL wajib diisi sebelum mengajukan transfer."))
        if self.total_amount <= 0:
            raise ValidationError(_("Nominal pembayaran PPL harus lebih dari Rp 0."))
        if self.transaction_id and self.transaction_id.state not in ("rejected", "failed"):
            raise UserError(
                _("PPL ini sudah terhubung dengan transaksi transfer bank (%s) dengan status %s.")
                % (self.transaction_id.name, self.transaction_id.state)
            )

        tx_vals = {
            "transfer_type": "single",
            "source_account_id": self.payment_source_account_id.id if self.payment_source_account_id else False,
            "single_bank_name": self.payment_dest_bank,
            "single_destination_account": self.payment_dest_account_number,
            "single_account_holder_name": self.payment_dest_account_name or False,
            "single_rupiah": self.total_amount,
            "ref_number": (self.name or "")[:19],
            "remark": f"Bayar PPL {self.name}: {self.title or ''}"[:200],
            "ppl_id": self.id,
            "unit_id": self.unit_id.id if self.unit_id else False,
        }
        tx = self.env["transaksi.transaction"].create(tx_vals)
        self.write({"transaction_id": tx.id})
        self.message_post(
            body=_(
                "Dibuatkan pengajuan transfer bank tunggal: "
                "<a href='#' data-oe-model='transaksi.transaction' data-oe-id='%d'>%s</a>."
            )
            % (tx.id, tx.name)
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Transaksi Transfer Bank"),
            "res_model": "transaksi.transaction",
            "res_id": tx.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_create_batch_bank_transfer(self):
        """Membuat transaksi transfer massal dari pilihan recordset PPL."""
        if not (
            self.env.user.has_group("transaksi.group_transaksi_finance")
            or self.env.user.has_group("transaksi.group_transaksi_manager")
            or self.env.user.has_group("sifnext_ppl.group_ppl_finance")
        ):
            raise AccessError(_("Hanya Bagian Keuangan atau Super User yang dapat membuat transfer kolektif."))

        if not self:
            raise UserError(_("Pilih minimal satu dokumen PPL untuk membuat transfer kolektif."))

        invalid_state = self.filtered(lambda p: p.state != "approved")
        if invalid_state:
            raise UserError(
                _("Seluruh PPL harus berstatus Disetujui (Approved). Dokumen belum disetujui: %s")
                % ", ".join(invalid_state.mapped("name"))
            )

        invalid_method = self.filtered(lambda p: p.payment_method != "bank")
        if invalid_method:
            raise UserError(
                _("Seluruh PPL harus menggunakan metode pembayaran Bank. Dokumen tidak valid: %s")
                % ", ".join(invalid_method.mapped("name"))
            )

        invalid_bank = self.filtered(lambda p: not p.payment_dest_bank or not p.payment_dest_account_number)
        if invalid_bank:
            raise ValidationError(
                _("Seluruh PPL harus memiliki informasi bank dan nomor rekening tujuan. Dokumen belum lengkap: %s")
                % ", ".join(invalid_bank.mapped("name"))
            )

        invalid_amount = self.filtered(lambda p: p.total_amount <= 0)
        if invalid_amount:
            raise ValidationError(
                _("Nominal pembayaran setiap PPL harus lebih dari Rp 0. Dokumen tidak valid: %s")
                % ", ".join(invalid_amount.mapped("name"))
            )

        active_tx = self.filtered(lambda p: p.transaction_id and p.transaction_id.state not in ("rejected", "failed"))
        if active_tx:
            raise UserError(
                _("Dokumen berikut sudah terhubung dengan transaksi bank aktif: %s")
                % ", ".join(active_tx.mapped("name"))
            )

        lines = []
        seq = 1
        for ppl in self:
            lines.append((0, 0, {
                "sequence": seq,
                "bank_name": ppl.payment_dest_bank,
                "destination_account": ppl.payment_dest_account_number,
                "account_holder_name": ppl.payment_dest_account_name or False,
                "transfer_method": "bi_fast",
                "rupiah": ppl.total_amount,
                "line_notes": f"PPL {ppl.name}"[:100],
                "ppl_id": ppl.id,
            }))
            seq += 1

        source_accounts = self.mapped("payment_source_account_id")
        source_account_id = source_accounts[0].id if len(source_accounts) == 1 else False

        tx_vals = {
            "transfer_type": "multiple",
            "remark": f"Pembayaran Kolektif {len(self)} Dokumen PPL"[:200],
            "ppl_ids": [(6, 0, self.ids)],
            "line_ids": lines,
            "source_account_id": source_account_id,
        }
        tx = self.env["transaksi.transaction"].create(tx_vals)
        self.write({"transaction_id": tx.id})
        for ppl in self:
            ppl.message_post(
                body=_(
                    "Didaftarkan ke pengajuan transfer bank kolektif: "
                    "<a href='#' data-oe-model='transaksi.transaction' data-oe-id='%d'>%s</a>."
                )
                % (tx.id, tx.name)
            )

        return {
            "type": "ir.actions.act_window",
            "name": _("Transaksi Transfer Bank Kolektif"),
            "res_model": "transaksi.transaction",
            "res_id": tx.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_view_bank_transfer(self):
        """Membuka form transaksi transfer bank yang terhubung."""
        self.ensure_one()
        if not self.transaction_id:
            raise UserError(_("Tidak ada transaksi transfer bank yang terhubung."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Transaksi Transfer Bank"),
            "res_model": "transaksi.transaction",
            "res_id": self.transaction_id.id,
            "view_mode": "form",
            "target": "current",
        }
