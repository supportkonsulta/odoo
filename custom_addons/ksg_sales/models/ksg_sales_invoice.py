from decimal import Decimal, ROUND_HALF_UP

from odoo import api, fields, models


def _terbilang_id(number):
    angka = [
        "nol",
        "satu",
        "dua",
        "tiga",
        "empat",
        "lima",
        "enam",
        "tujuh",
        "delapan",
        "sembilan",
        "sepuluh",
        "sebelas",
    ]

    number = int(number)

    if number < 12:
        return angka[number]

    if number < 20:
        return _terbilang_id(number - 10) + " belas"

    if number < 100:
        hasil = _terbilang_id(number // 10) + " puluh"

        if number % 10:
            hasil += " " + _terbilang_id(number % 10)

        return hasil

    if number < 200:
        hasil = "seratus"

        if number - 100:
            hasil += " " + _terbilang_id(number - 100)

        return hasil

    if number < 1000:
        hasil = _terbilang_id(number // 100) + " ratus"

        if number % 100:
            hasil += " " + _terbilang_id(number % 100)

        return hasil

    if number < 2000:
        hasil = "seribu"

        if number - 1000:
            hasil += " " + _terbilang_id(number - 1000)

        return hasil

    if number < 1_000_000:
        hasil = _terbilang_id(number // 1000) + " ribu"

        if number % 1000:
            hasil += " " + _terbilang_id(number % 1000)

        return hasil

    if number < 1_000_000_000:
        hasil = _terbilang_id(number // 1_000_000) + " juta"

        if number % 1_000_000:
            hasil += " " + _terbilang_id(number % 1_000_000)

        return hasil

    if number < 1_000_000_000_000:
        hasil = _terbilang_id(number // 1_000_000_000) + " miliar"

        if number % 1_000_000_000:
            hasil += " " + _terbilang_id(
                number % 1_000_000_000
            )

        return hasil

    if number < 1_000_000_000_000_000:
        hasil = _terbilang_id(number // 1_000_000_000_000) + " triliun"

        if number % 1_000_000_000_000:
            hasil += " " + _terbilang_id(
                number % 1_000_000_000_000
            )

        return hasil

    return str(number)


def _terbilang_rupiah(amount):
    amount = Decimal(str(amount or 0)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    negatif = amount < 0
    amount = abs(amount)

    rupiah = int(amount)
    sen = int((amount - Decimal(rupiah)) * 100)

    hasil = _terbilang_id(rupiah).title() + " Rupiah"

    if sen:
        hasil += (
            " dan "
            + _terbilang_id(sen).title()
            + " Sen"
        )

    if negatif:
        hasil = "Minus " + hasil

    return hasil


class AccountMove(models.Model):
    _inherit = "account.move"

    ksg_term_id = fields.Many2one(
        "ksg.sales.project.term",
        string="Termin Penagihan",
        copy=False,
        readonly=True,
    )

    ksg_project_id = fields.Many2one(
        "ksg.sales.project",
        string="Proyek KSG",
        related="ksg_term_id.project_id",
        store=True,
        readonly=True,
    )

    ksg_terbilang = fields.Char(
        string="Terbilang KSG",
        compute="_compute_ksg_terbilang",
    )

    @api.depends("amount_total")
    def _compute_ksg_terbilang(self):
        for move in self:
            move.ksg_terbilang = _terbilang_rupiah(
                move.amount_total
            )

    def ksg_format_idr(self, amount):
        """
        Format nominal Indonesia tanpa widget monetary
        agar tidak muncul karakter Â.
        """

        amount = Decimal(str(amount or 0)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        formatted = f"{amount:,.2f}"

        formatted = (
            formatted
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

        return f"Rp {formatted}"


class AccountMoveSend(models.AbstractModel):
    _inherit = "account.move.send"

    @api.model
    def _get_default_pdf_report_id(self, move):
        """
        Gunakan template Invoice KSG untuk invoice
        yang dibuat dari Termin Penagihan KSG.

        Invoice biasa tetap menggunakan report bawaan Odoo.
        """

        if move.ksg_term_id:
            ksg_report = self.env.ref(
                "ksg_sales.action_report_ksg_invoice",
                raise_if_not_found=False,
            )

            if ksg_report:
                return ksg_report

        return super()._get_default_pdf_report_id(move)


class ResCompany(models.Model):
    _inherit = "res.company"

    ksg_director_name = fields.Char(
        string="Nama Direktur KSG",
        help=(
            "Nama direktur yang ditampilkan "
            "pada Invoice KSG."
        ),
    )