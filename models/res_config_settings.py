# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    bn_sales_20_tax_ids = fields.Many2many(
        related='company_id.bn_sales_20_tax_ids', readonly=False,
        string='BN Sales 20% Taxes')
    bn_sales_9_tax_ids = fields.Many2many(
        related='company_id.bn_sales_9_tax_ids', readonly=False,
        string='BN Sales 9% Taxes')
    bn_last_flag = fields.Char(
        related='company_id.bn_last_flag', readonly=False)
    bn_advance_product_code = fields.Char(
        related='company_id.bn_advance_product_code', readonly=False)
    bn_sales_20_filename_prefix = fields.Char(
        related='company_id.bn_sales_20_filename_prefix', readonly=False)
    bn_sales_9_filename_prefix = fields.Char(
        related='company_id.bn_sales_9_filename_prefix', readonly=False)
    bn_purchase_filename_prefix = fields.Char(
        related='company_id.bn_purchase_filename_prefix', readonly=False)
