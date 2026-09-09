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

    # ============================================================
    # CUSTOM CONTROLLER: Cetak Beban Usaha (tanpa wkhtmltopdf)
    # ============================================================
    @http.route(
        "/sif_rka/print_beban_usaha/<int:record_id>",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def print_beban_usaha(self, record_id=None):
        """Render laporan beban usaha langsung sebagai HTML.

        Solusi ini bypass report system Odoo (qweb-pdf/qweb-html)
        yang membutuhkan wkhtmltopdf untuk PDF. Dengan controller ini:

        - HTML langsung di-render dengan styling lengkap
        - Print CSS untuk Ctrl+P yang sempurna
        - Tidak perlu wkhtmltopdf sama sekali
        - Bisa disimpan sebagai PDF dari browser (Ctrl+P -> Save as PDF)
        """
        record = request.env["sif.rka.budget"].browse(record_id)

        if not record.exists():
            return request.not_found("Record tidak ditemukan.")

        # Ambil data laporan
        report_data = record._get_beban_usaha_report_data()

        if not report_data["rows"]:
            return request.not_found(
                f"Tidak ada data beban usaha untuk tahun "
                f"{report_data['tahun']}."
            )

        # Format currency helper
        def fmt(val):
            return f"{val:,.2f}"

        rows_html = ""
        for row in report_data["rows"]:
            rows_html += f"""
            <tr>
                <td style="text-align: left;">{row['code']}</td>
                <td>{row['name']}</td>
                <td style="text-align: right;">{fmt(row['current_amount'])}</td>
                <td style="text-align: right;">{fmt(row['previous_amount'])}</td>
            </tr>
            """

        total_rows_html = f"""
        <tr style="font-weight: bold; background-color: #f0f0f0;">
            <td colspan="2" style="text-align: left;">Total Beban Usaha</td>
            <td style="text-align: right;">{fmt(report_data['total_current_realization'])}</td>
            <td style="text-align: right;">{fmt(report_data['total_previous_realization'])}</td>
        </tr>
        """

        company = request.env.company

        html = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<title>Laporan Beban Usaha - {report_data['tahun']}</title>
<style>
    /* ===== RESET & BASE ===== */
    *, *::before, *::after {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}
    body {{
        font-family: 'DejaVu Sans', 'Segoe UI', Arial, sans-serif;
        font-size: 11pt;
        color: #222;
        line-height: 1.5;
        padding: 20px;
    }}

    /* ===== HEADER ===== */
    .header {{
        text-align: center;
        margin-bottom: 25px;
        padding-bottom: 15px;
        border-bottom: 2px solid #1a237e;
    }}
    .header h1 {{
        font-size: 18pt;
        color: #1a237e;
        margin-bottom: 5px;
        text-transform: uppercase;
        letter-spacing: 1px;
    }}
    .header p {{
        font-size: 11pt;
        color: #555;
    }}
    .header .company-name {{
        font-size: 13pt;
        font-weight: bold;
        color: #333;
        margin-bottom: 3px;
    }}

    /* ===== TABLE ===== */
    table {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 10px;
    }}
    thead th {{
        background-color: #1a237e;
        color: white;
        padding: 10px 8px;
        text-align: center;
        font-size: 10pt;
        border: 1px solid #1a237e;
    }}
    thead th:first-child {{
        text-align: left;
    }}
    tbody td {{
        padding: 7px 8px;
        border: 1px solid #ccc;
        vertical-align: top;
        font-size: 10pt;
    }}
    tbody tr:nth-child(even) {{
        background-color: #f9f9f9;
    }}
    tbody tr:hover {{
        background-color: #e8eaf6;
    }}

    /* ===== TITLE INFO ===== */
    .info-section {{
        margin-bottom: 15px;
    }}
    .info-section table.infotable {{
        width: auto;
        border: none;
        margin: 0;
    }}
    .info-section table.infotable td {{
        border: none;
        padding: 2px 10px 2px 0;
        font-size: 10pt;
    }}
    .info-section table.infotable td.label {{
        font-weight: bold;
        color: #555;
        width: 100px;
    }}

    /* ===== PRINT STYLES (Ctrl+P) ===== */
    @media print {{
        @page {{
            size: A4 landscape;
            margin: 15mm 10mm 15mm 10mm;
        }}
        body {{
            padding: 0;
            font-size: 10pt;
        }}
        .header {{
            margin-bottom: 15px;
            padding-bottom: 10px;
        }}
        .header h1 {{
            font-size: 16pt;
        }}
        thead th {{
            background-color: #1a237e !important;
            color: white !important;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}
        tbody tr:nth-child(even) {{
            background-color: #f9f9f9 !important;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}
        tbody tr:hover {{
            background-color: inherit;
        }}
        table {{
            page-break-inside: auto;
        }}
        tr {{
            page-break-inside: avoid;
            page-break-after: auto;
        }}
        thead {{
            display: table-header-group;
        }}
        tfoot {{
            display: table-footer-group;
        }}
        .no-print {{
            display: none !important;
        }}
    }}

    /* ===== FOOTER ===== */
    .footer {{
        margin-top: 30px;
        text-align: center;
        font-size: 9pt;
        color: #999;
        border-top: 1px solid #ddd;
        padding-top: 10px;
    }}
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
    <div class="company-name">{company.name or 'Perusahaan'}</div>
    <h1>Laporan Beban Usaha</h1>
    <p>Tahun <strong>{report_data['tahun']}</strong> vs <strong>{report_data['tahun_sebelumnya']}</strong></p>
</div>

<!-- INFO -->
<div class="info-section">
    <table class="infotable">
        <tr>
            <td class="label">Tahun:</td>
            <td><strong>{report_data['tahun']}</strong></td>
        </tr>
        <tr>
            <td class="label">Tahun Lalu:</td>
            <td><strong>{report_data['tahun_sebelumnya']}</strong></td>
        </tr>
    </table>
</div>

<!-- TABLE -->
<table>
    <thead>
        <tr>
            <th style="width: 12%;">Kode</th>
            <th style="width: 38%;">Nama Akun</th>
            <th style="width: 25%;">{report_data['tahun']}</th>
            <th style="width: 25%;">{report_data['tahun_sebelumnya']}</th>
        </tr>
    </thead>
    <tbody>
        {rows_html}
        {total_rows_html}
    </tbody>
</table>

<!-- FOOTER -->
<div class="footer">
    <p>Laporan ini digenerate otomatis oleh sistem pada {request.env.user.display_name} - {request.env.company.name}</p>
    <p class="no-print" style="margin-top: 10px;">
        <button onclick="window.print()"
                style="padding: 8px 20px; background: #1a237e; color: white;
                       border: none; border-radius: 4px; cursor: pointer;
                       font-size: 11pt;">
            Cetak / Simpan PDF (Ctrl+P)
        </button>
    </p>
</div>

</body>
</html>"""

        return request.make_response(
            html,
            headers=[
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Disposition",
                 f'inline; filename="beban_usaha_{report_data["tahun"]}.html"'),
            ],
        )