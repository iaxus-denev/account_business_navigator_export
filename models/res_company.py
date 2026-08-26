# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    bn_sales_20_tax_ids = fields.Many2many(
        comodel_name='account.tax',
        relation='bn_export_company_sales_20_tax_rel',
        column1='company_id',
        column2='tax_id',
        string='BN Sales 20% Taxes',
        domain=[('type_tax_use', '=', 'sale')],
        help='Taxes that classify a sales invoice line into the "Продажби 20%" export file.',
    )
    bn_sales_9_tax_ids = fields.Many2many(
        comodel_name='account.tax',
        relation='bn_export_company_sales_9_tax_rel',
        column1='company_id',
        column2='tax_id',
        string='BN Sales 9% Taxes',
        domain=[('type_tax_use', '=', 'sale')],
        help='Taxes that classify a sales invoice line into the "Продажби 9%" export file.',
    )
    bn_last_flag = fields.Char(
        string='BN Last Column Flag',
        default='Не',
        help='Constant value written to column 13 (Флаг) of every exported row.',
    )
    bn_advance_product_code = fields.Char(
        string='BN Advance Product Code',
        default='**',
        help='Product default_code value that identifies an advance-payment invoice line.',
    )
    bn_sales_20_filename_prefix = fields.Char(
        string='BN Sales 20% Filename Prefix',
        default='Продажби 20',
    )
    bn_sales_9_filename_prefix = fields.Char(
        string='BN Sales 9% Filename Prefix',
        default='Продажби 9',
    )
    bn_purchase_filename_prefix = fields.Char(
        string='BN Purchase Filename Prefix',
        default='Покупки',
    )
