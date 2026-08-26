# -*- coding: utf-8 -*-
{
    "name": "Business Navigator Export",
    "version": "19.0.1.0.0",
    "category": "Accounting/Accounting",
    "summary": "Manual export of posted sales/purchase invoices to Business Navigator TXT files",
    "description": """
Business Navigator Export
==========================

Manual export of posted account.move / account.move.line data into
CP1251 / TAB / CRLF TXT files compatible with the existing Business
Navigator import filters:

* Sales 20% VAT TXT file
* Sales 9% VAT TXT file
* One combined Purchases TXT file (Bulgaria + foreign suppliers)
* Optional ZIP package of all non-empty files
* Export batch history with checksums and warnings

The module is a pure export layer on top of standard Odoo accounting
models. It does not duplicate invoices, does not change posting logic,
and does not perform any automatic (cron/SFTP) transfer to Business
Navigator.

Out of scope: scheduled/automatic export, direct connection to Business
Navigator, BGN export, payments/reconciliation, draft/cancelled moves.
""",
    "author": "Mihail Denev",
    "website": "https://iaxus.com",
    "license": "LGPL-3",
    "depends": [
        "account",
        "base_setup",
    ],
    "data": [
        # 1. Security — must load before views
        "security/bn_export_security.xml",
        "security/ir.model.access.csv",
        # 2. Data
        "data/bn_export_sequence.xml",
        # 3. Views
        "views/res_config_settings_views.xml",
        "views/bn_export_wizard_views.xml",
        "views/bn_export_batch_views.xml",
        "views/bn_export_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
