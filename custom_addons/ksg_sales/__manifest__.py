{
    "name": "KSG Sales",
    "version": "19.0.1.0.0",
    "summary": "Custom Modul Penjualan ERP KSG",

    "description": """
        Custom Modul Penjualan ERP KSG.

        Scope:
        - Data Proyek
        - Data Kontrak
        - Kategori Pekerjaan
        - Checklist Dokumen Engineering
        - Sistem Penagihan
        - Integrasi dengan Contacts
        - Chatter dan Activity
    """,

    "category": "Sales",
    "author": "KSG / IT",
    "license": "LGPL-3",

    "depends": [
        "base",
        "mail",
        "contacts",
        "account",
    ],

    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",

        "data/sequence.xml",
        "data/ksg_sales_sequence.xml",

        "views/ksg_sales_category_views.xml",
        "views/ksg_sales_document_checklist_views.xml",
        "views/ksg_sales_project_views.xml",
        "views/ksg_sales_project_addendum_views.xml",
        "views/ksg_sales_rab_views.xml",
        "views/ksg_sales_hpp_views.xml",

        "report/invoice_report.xml",
        "report/invoice_template.xml",

        "views/ksg_sales_invoice_views.xml",
    ],

    "installable": True,
    "application": True,
}