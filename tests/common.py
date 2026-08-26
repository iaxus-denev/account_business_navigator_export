# -*- coding: utf-8 -*-
from datetime import date

from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class BnExportTestCommon(AccountTestInvoicingCommon):
    """Reusable posted-invoice fixtures for Business Navigator export tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._use_currency(cls.env.company, 'EUR')
        cls.company = cls.env.company
        cls.bg_country = cls.env.ref('base.bg')

        cls.tax_20 = cls.env['account.tax'].create({
            'name': 'BN Test VAT 20%',
            'amount': 20,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'company_id': cls.company.id,
        })
        cls.tax_9 = cls.env['account.tax'].create({
            'name': 'BN Test VAT 9%',
            'amount': 9,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'company_id': cls.company.id,
        })
        cls.company.write({
            'bn_sales_20_tax_ids': [Command.set(cls.tax_20.ids)],
            'bn_sales_9_tax_ids': [Command.set(cls.tax_9.ids)],
            'bn_last_flag': 'Не',
            'bn_advance_product_code': '**',
        })

        cls.partner_bn = cls.partner_a.copy({
            'name': 'Д-р Уляна Кирякова',
            'ref': '1777',
            'company_registry': '257893427',
            'vat': 'BG257893427',
            'country_id': cls.bg_country.id,
        })
        cls.partner_foreign = cls.partner_b.copy({
            'name': 'Institut Straumann AG',
            'ref': '1780',
            'company_registry': 'CHE-116.331.762',
            'vat': 'CHE-116.331.762',
            'country_id': cls.env.ref('base.ch').id,
        })
        cls.product_bn = cls._create_product(
            name='GM Cover Screw, Titanium',
            default_code='117.021',
            taxes_id=[Command.set(cls.tax_20.ids)],
        )
        cls.product_advance = cls._create_product(
            name='Advance product',
            default_code='**',
            taxes_id=[Command.set(cls.tax_20.ids)],
        )

    @classmethod
    def bn_line(cls, product=None, quantity=1, price_unit=10, taxes=None, **extra):
        """Return a command creating one controlled product invoice line."""
        product = product or cls.product_bn
        values = {
            'product_id': product.id,
            'name': product.name,
            'quantity': quantity,
            'price_unit': price_unit,
            'tax_ids': [Command.set((taxes if taxes is not None else cls.tax_20).ids)],
        }
        values.update(extra)
        return Command.create(values)

    @classmethod
    def bn_invoice(cls, move_type='out_invoice', lines=None, partner=None,
                   invoice_date=date(2026, 7, 16), ref=None, **values):
        """Create and post a BN-compatible invoice/bill with explicit lines."""
        partner = partner or cls.partner_bn
        invoice_values = {
            'partner_id': partner.id,
            'invoice_line_ids': lines or [cls.bn_line()],
        }
        if ref is not None:
            invoice_values['ref'] = ref
        invoice_values.update(values)
        return cls._create_invoice(
            move_type=move_type,
            invoice_date=invoice_date,
            post=True,
            **invoice_values,
        )
