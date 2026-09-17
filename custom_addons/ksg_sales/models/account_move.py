import base64
from pathlib import Path

from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    def ksg_logo_data_uri(self):
        self.ensure_one()

        # Lokasi:
        # ksg_sales/models/account_move.py
        # naik 1 folder -> models
        # naik 1 folder -> ksg_sales
        # lalu masuk static/src/img/ksg_logo.png
        logo_path = (
            Path(__file__).resolve().parent.parent
            / "static"
            / "src"
            / "img"
            / "ksg_logo.png"
        )

        if not logo_path.exists():
            return False

        try:
            logo_data = base64.b64encode(
                logo_path.read_bytes()
            ).decode("utf-8")

            return f"data:image/png;base64,{logo_data}"

        except Exception:
            return False