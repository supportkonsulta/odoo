from odoo import http
from odoo.http import request
import json


class SifRkaDashboardController(http.Controller):

    @http.route(
        "/sif_rka/chart_data",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def get_chart_data(self, tahun=None, coa_id=None):
        """Return chart data for the dashboard bar chart."""
        if not tahun:
            from odoo import fields
            tahun = str(fields.Date.today().year)

        domain = [("tahun", "=", tahun)]
        if coa_id:
            domain.append(("account_id", "=", int(coa_id)))

        monthly_records = request.env["sif.rka.budget.month"].search(
            domain, order="month asc"
        )

        month_names = [
            "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
            "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
        ]

        # Initialize all months with 0
        month_data = {}
        for i in range(1, 13):
            key = str(i).zfill(2)
            month_data[key] = {
                "month": key,
                "label": month_names[i - 1],
                "budget": 0.0,
                "realisasi": 0.0,
            }

        for rec in monthly_records:
            if rec.month in month_data:
                month_data[rec.month]["budget"] += rec.budget_amount or 0.0
                month_data[rec.month]["realisasi"] += rec.realisasi or 0.0

        sorted_months = sorted(month_data.values(), key=lambda x: x["month"])

        labels = [m["label"] for m in sorted_months]
        budget_data = [m["budget"] for m in sorted_months]
        realisasi_data = [m["realisasi"] for m in sorted_months]

        return {
            "success": True,
            "data": {
                "labels": labels,
                "datasets": [
                    {
                        "label": "Anggaran / Pendapatan",
                        "data": budget_data,
                        "backgroundColor": "rgba(41, 98, 255, 0.85)",
                        "borderColor": "rgba(41, 98, 255, 1)",
                        "borderWidth": 1,
                        "borderRadius": 4,
                    },
                    {
                        "label": "Realisasi / Pengeluaran",
                        "data": realisasi_data,
                        "backgroundColor": "rgba(255, 159, 0, 0.85)",
                        "borderColor": "rgba(255, 159, 0, 1)",
                        "borderWidth": 1,
                        "borderRadius": 4,
                    },
                ],
                "tahun": tahun,
                "monthly_details": sorted_months,
            },
        }

    @http.route(
        "/sif_rka/coa_list",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def get_coa_list(self):
        """Return list of COAs for the chart filter."""
        coas = request.env["sif.coa"].search_read(
            [], ["id", "code", "name", "display_name"], order="code asc"
        )
        return {
            "success": True,
            "data": [
                {"id": "", "display_name": "-- Semua COA --"},
            ]
            + [
                {
                    "id": c["id"],
                    "display_name": c["display_name"]
                    or f"[{c['code']}] {c['name']}",
                }
                for c in coas
            ],
        }