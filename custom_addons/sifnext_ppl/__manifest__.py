{
    "name": "SIFNEXT PPL",
    "summary": "Permintaan Pembayaran Langsung",
    "author": "SIFNEXT",
    "version": "19.0.1.0.0",
    "category": "Accounting/Accounting",
    "license": "LGPL-3",
    "depends": ["account", "mail"],
    "data": [
        "security/ppl_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/ppl_views.xml",
    ],
    "application": True,
    "installable": True,
}
