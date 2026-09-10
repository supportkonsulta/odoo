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
        """Render laporan beban usaha langsung sebagai HTML profesional.

        Solusi ini bypass report system Odoo (qweb-pdf/qweb-html)
        yang membutuhkan wkhtmltopdf untuk PDF. Dengan controller ini:

        - HTML langsung di-render dengan layout seperti surat resmi perusahaan
        - Kop surat dengan nama, alamat, telepon, email, website perusahaan
        - Tempat logo perusahaan (ambil dari data perusahaan Odoo)
        - Print CSS untuk Ctrl+P yang sempurna
        - Tidak perlu wkhtmltopdf sama sekali
        - Bisa disimpan sebagai PDF dari browser (Ctrl+P -> Save as PDF)

        CARA MENAMBAHKAN LOGO / KOP SURAT:
        ====================================
        1. Buka menu Settings > Companies (atau Pengaturan > Perusahaan)
        2. Pilih perusahaan kamu
        3. Upload logo di field "Company Logo" atau "Logo"
        4. Isi alamat, telepon, email, website di tab General Information
        5. Simpan — logo dan alamat otomatis muncul di laporan ini!

        Jika ingin logo tampil dengan benar di PDF dari browser:
        - Pastikan logo terupload (format PNG/JPG, max 200x100 px ideal)
        - Atau gunakan base64 inline (sudah di-handle oleh controller ini)
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
        row_num = 0
        for row in report_data["rows"]:
            row_num += 1
            rows_html += f"""
            <tr>
                <td style="text-align: center;">{row_num}</td>
                <td style="text-align: left;">{row['code']}</td>
                <td>{row['name']}</td>
                <td style="text-align: right;">{fmt(row['current_amount'])}</td>
                <td style="text-align: right;">{fmt(row['previous_amount'])}</td>
            </tr>
            """

        total_rows_html = f"""
        <tr class="total-row">
            <td colspan="3" style="text-align: left;">Total Beban Usaha</td>
            <td style="text-align: right;">{fmt(report_data['total_current_realization'])}</td>
            <td style="text-align: right;">{fmt(report_data['total_previous_realization'])}</td>
        </tr>
        """

        company = request.env.company

        # Informasi perusahaan
        company_name = company.name or 'Perusahaan'
        company_addr = ', '.join(filter(None, [
            company.street or '',
            company.street2 or '',
            company.city or '',
            company.state_id.name if company.state_id else '',
            company.zip or '',
        ])) if any([company.street, company.city]) else ''
        company_phone = company.phone or ''
        company_email = company.email or ''
        company_website = company.website or ''
        company_vat = company.vat or ''

        # Logo: convert ke base64 inline untuk tampil di print
        logo_html = ''
        if company.logo:
            import base64
            logo_b64 = company.logo.decode('utf-8') if isinstance(company.logo, bytes) else company.logo
            logo_html = f'''
            <div class="logo-col">
                <img src="data:image/png;base64,{logo_b64}"
                     alt="Logo" class="company-logo" />
            </div>
            '''

        # Tanggal sekarang
        from odoo import fields as od_fields
        now = od_fields.Datetime.now()
        day_names = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
        month_names = [
            'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
            'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'
        ]
        tanggal_laporan = f"{company.city or 'Jakarta'}, {now.day} {month_names[now.month - 1]} {now.year}"

        user_name = request.env.user.display_name or 'Admin'

        html = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<title>Laporan Beban Usaha - {report_data['tahun']}</title>
<style>
    /* ==========================================================
               RESET & BASE
            ========================================================== */
    *, *::before, *::after {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}

    body {{
        font-family: 'Times New Roman', 'DejaVu Serif', Georgia, 'Palatino Linotype', serif;
        font-size: 11pt;
        color: #1a1a1a;
        line-height: 1.6;
        padding: 30px 35px;
        background: white;
    }}

    /* ==========================================================
               KOP SURAT (HEADER)
            ========================================================== */
    .kopsurat {{
        display: flex;
        align-items: center;
        justify-content: flex-start;
        gap: 20px;
        padding-bottom: 15px;
        border-bottom: 3px double #1a237e;
        margin-bottom: 20px;
    }}

    .kopsurat .logo-col {{
        flex: 0 0 90px;
        text-align: center;
    }}

    .kopsurat .company-logo {{
        max-width: 90px;
        max-height: 90px;
        object-fit: contain;
    }}

    .kopsurat .kop-text {{
        flex: 1;
    }}

    .kopsurat .kop-text .company-name {{
        font-size: 16pt;
        font-weight: bold;
        color: #1a237e;
        text-transform: uppercase;
        letter-spacing: 2px;
        margin-bottom: 2px;
    }}

    .kopsurat .kop-text .company-tagline {{
        font-size: 9pt;
        color: #555;
        font-style: italic;
        margin-bottom: 4px;
    }}

    .kopsurat .kop-text .company-details {{
        font-size: 8.5pt;
        color: #444;
        line-height: 1.5;
    }}

    .kopsurat .kop-text .company-details span {{
        display: inline-block;
        margin-right: 15px;
    }}

    .kopsurat .kop-text .company-details i {{
        margin-right: 3px;
    }}

    /* ==========================================================
               TITLE SECTION
            ========================================================== */
    .title-section {{
        text-align: center;
        margin: 5px 0 18px 0;
    }}

    .title-section h1 {{
        font-size: 15pt;
        font-weight: bold;
        color: #1a237e;
        text-transform: uppercase;
        letter-spacing: 2px;
        margin-bottom: 3px;
    }}

    .title-section .subtitle {{
        font-size: 10pt;
        color: #555;
        font-style: italic;
    }}

    /* ==========================================================
               INFO BLOCK (Nomor, Tanggal, dll)
            ========================================================== */
    .info-block {{
        margin-bottom: 15px;
        border: 1px solid #ddd;
        padding: 10px 15px;
        background: #fafafa;
        border-radius: 3px;
    }}

    .info-block table.infotable {{
        width: 100%;
        border: none;
        margin: 0;
    }}

    .info-block table.infotable td {{
        border: none;
        padding: 3px 12px 3px 0;
        font-size: 10pt;
        vertical-align: top;
    }}

    .info-block table.infotable td.label {{
        font-weight: bold;
        color: #333;
        width: 120px;
    }}

    .info-block table.infotable td.colon {{
        width: 10px;
        padding: 3px 0;
    }}

    /* ==========================================================
               TABLE PROFESIONAL
            ========================================================== */
    .data-table {{
        width: 100%;
        border-collapse: collapse;
        margin: 5px 0 15px 0;
        font-size: 9.5pt;
    }}

    .data-table thead th {{
        background-color: #1a237e;
        color: white;
        padding: 8px 7px;
        text-align: center;
        font-weight: bold;
        font-size: 9.5pt;
        border: 1px solid #1a237e;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}

    .data-table thead th:first-child {{
        width: 5%;
    }}
    .data-table thead th:nth-child(2) {{
        width: 12%;
    }}
    .data-table thead th:nth-child(3) {{
        width: 35%;
        text-align: left;
    }}
    .data-table thead th:nth-child(4),
    .data-table thead th:nth-child(5) {{
        width: 24%;
    }}

    .data-table tbody td {{
        padding: 6px 7px;
        border: 1px solid #ccc;
        vertical-align: middle;
    }}

    .data-table tbody tr:nth-child(even) {{
        background-color: #f8f9ff;
    }}

    .data-table tbody tr:hover {{
        background-color: #e8eaf6;
    }}

    .data-table .total-row td {{
        font-weight: bold;
        background-color: #e8eaf6;
        border-top: 2px solid #1a237e;
        border-bottom: 2px solid #1a237e;
        font-size: 10pt;
        padding: 8px 7px;
    }}

    .data-table .total-row td:first-child {{
        text-align: left;
    }}

    /* ==========================================================
               SIGNATURE BLOCK
            ========================================================== */
    .signature-section {{
        margin-top: 35px;
        display: flex;
        justify-content: space-between;
    }}

    .signature-box {{
        text-align: center;
        width: 45%;
    }}

    .signature-box .sig-label {{
        font-size: 9pt;
        color: #555;
        margin-bottom: 50px;
    }}

    .signature-box .sig-name {{
        font-weight: bold;
        font-size: 10pt;
        text-decoration: underline;
        margin-top: 5px;
    }}

    .signature-box .sig-title {{
        font-size: 9pt;
        color: #555;
    }}

    /* ==========================================================
               FOOTER
            ========================================================== */
    .footer {{
        margin-top: 25px;
        text-align: center;
        font-size: 8pt;
        color: #999;
        border-top: 1px solid #ddd;
        padding-top: 8px;
    }}

    .footer .page-info {{
        font-style: italic;
    }}

    /* ==========================================================
               PRINT STYLES (Ctrl+P)
            ========================================================== */
    @media print {{
        @page {{
            size: A4 landscape;
            margin: 15mm 12mm 15mm 12mm;
        }}

        body {{
            padding: 0;
            font-size: 10pt;
        }}

        .kopsurat {{
            border-bottom: 3px double #1a237e !important;
        }}

        .kopsurat .company-logo {{
            max-width: 90px;
            max-height: 90px;
        }}

        .info-block {{
            border: 1px solid #ddd;
            background: #fafafa;
        }}

        .data-table thead th {{
            background-color: #1a237e !important;
            color: white !important;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}

        .data-table tbody tr:nth-child(even) {{
            background-color: #f8f9ff !important;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}

        .data-table .total-row td {{
            background-color: #e8eaf6 !important;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}

        .data-table {{
            page-break-inside: auto;
        }}

        tr {{
            page-break-inside: avoid;
            page-break-after: auto;
        }}

        thead {{
            display: table-header-group;
        }}

        .no-print {{
            display: none !important;
        }}
    }}

    /* ==========================================================
               UTILITY
            ========================================================== */
    .clearfix {{ clear: both; }}
    .text-center {{ text-align: center; }}
    .text-right {{ text-align: right; }}
    .text-left {{ text-align: left; }}
    .no-print {{
        margin-top: 15px;
        text-align: center;
    }}
    .no-print button {{
        padding: 10px 30px;
        background: #1a237e;
        color: white;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-size: 11pt;
        font-family: Arial, sans-serif;
    }}
    .no-print button:hover {{
        background: #283593;
    }}

    @media screen {{
        body {{
            max-width: 1100px;
            margin: 20px auto;
            box-shadow: 0 0 20px rgba(0,0,0,0.1);
            border-radius: 4px;
        }}
    }}
</style>
</head>
<body>

<!-- ============ KOP SURAT ============ -->
<div class="kopsurat">
    {logo_html if logo_html else ''}
    <div class="kop-text" style="{'margin-left: 0;' if not logo_html else ''}">
        <div class="company-name">{company_name}</div>
        <div class="company-tagline">Laporan Keuangan &bull; Beban Usaha</div>
        <div class="company-details">
            {'<span><i>&#128205;</i> ' + company_addr + '</span>' if company_addr else ''}
            {'<span><i>&#128222;</i> ' + company_phone + '</span>' if company_phone else ''}
            {'<span><i>&#9993;</i> ' + company_email + '</span>' if company_email else ''}
            {'<span><i>&#127760;</i> ' + company_website + '</span>' if company_website else ''}
            {'<span>NPWP: ' + company_vat + '</span>' if company_vat else ''}
        </div>
    </div>
</div>

<!-- ============ JUDUL LAPORAN ============ -->
<div class="title-section">
    <h1>Laporan Beban Usaha</h1>
    <div class="subtitle">
        Untuk Tahun yang Berakhir {report_data['tahun']} dan {report_data['tahun_sebelumnya']}
    </div>
</div>

<!-- ============ INFO BLOCK ============ -->
<div class="info-block">
    <table class="infotable">
        <tr>
            <td class="label">Nomor</td>
            <td class="colon">:</td>
            <td><strong>001/LBU/{company_name.upper().replace(' ', '')}/{report_data['tahun']}</strong></td>
        </tr>
        <tr>
            <td class="label">Tanggal</td>
            <td class="colon">:</td>
            <td><strong>{tanggal_laporan}</strong></td>
        </tr>
        <tr>
            <td class="label">Tahun Buku</td>
            <td class="colon">:</td>
            <td><strong>{report_data['tahun']}</strong></td>
        </tr>
        <tr>
            <td class="label">Tahun Lalu</td>
            <td class="colon">:</td>
            <td><strong>{report_data['tahun_sebelumnya']}</strong></td>
        </tr>
        <tr>
            <td class="label">Penyusun</td>
            <td class="colon">:</td>
            <td><strong>{user_name}</strong></td>
        </tr>
        <tr>
            <td class="label">Mata Uang</td>
            <td class="colon">:</td>
            <td><strong>Rupiah (IDR)</strong></td>
        </tr>
    </table>
</div>

<!-- ============ TABLE DATA ============ -->
<table class="data-table">
    <thead>
        <tr>
            <th>No</th>
            <th>Kode</th>
            <th style="text-align: left;">Nama Akun</th>
            <th>{report_data['tahun']}<br><span style="font-weight: normal; font-size: 8pt;">(Rp)</span></th>
            <th>{report_data['tahun_sebelumnya']}<br><span style="font-weight: normal; font-size: 8pt;">(Rp)</span></th>
        </tr>
    </thead>
    <tbody>
        {rows_html}
        {total_rows_html}
    </tbody>
</table>

<!-- ============ SIGNATURE ============ -->
<div class="signature-section">
    <div class="signature-box">
        <div class="sig-label">Mengetahui,</div>
        <div class="sig-label" style="margin-top: 10px; font-size: 8pt; color: #888;">Direktur Utama</div>
        <div style="height: 50px;"></div>
        <div class="sig-name">{company_name}</div>
        <div class="sig-title">Direktur Utama</div>
    </div>
    <div class="signature-box">
        <div class="sig-label">{tanggal_laporan}</div>
        <div class="sig-label" style="margin-top: 10px; font-size: 8pt; color: #888;">Penyusun</div>
        <div style="height: 50px;"></div>
        <div class="sig-name">{user_name}</div>
        <div class="sig-title">Penyusun Laporan</div>
    </div>
</div>

<!-- ============ FOOTER ============ -->
<div class="footer">
    <span class="page-info">
        Laporan Beban Usaha {report_data['tahun']} &mdash; {company_name}
        &mdash; Dicetak pada {tanggal_laporan}
    </span>
</div>

<!-- ============ PRINT BUTTON ============ -->
<div class="no-print">
    <button onclick="window.print()">
        Cetak / Simpan PDF (Ctrl+P)
    </button>
    <p style="margin-top: 5px; font-size: 9pt; color: #888;">
        Gunakan Ctrl+P atau tombol di atas, lalu pilih "Save as PDF"
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