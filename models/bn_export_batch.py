# -*- coding: utf-8 -*-
import base64
import hashlib

from odoo import api, fields, models


class BusinessNavigatorExportBatch(models.Model):
    _name = 'business.navigator.export.batch'
    _description = 'Business Navigator Export Batch'
    _order = 'requested_at desc, id desc'

    name = fields.Char(required=True, copy=False, readonly=True, default='New')
    company_id = fields.Many2one('res.company', required=True, readonly=True,
                                  default=lambda self: self.env.company)
    date_from = fields.Date(required=True, readonly=True)
    date_to = fields.Date(required=True, readonly=True)
    state = fields.Selection(
        [('validating', 'Validating'), ('done', 'Done'), ('failed', 'Failed')],
        required=True, default='validating', readonly=True)
    requested_by = fields.Many2one('res.users', required=True, readonly=True,
                                    default=lambda self: self.env.user)
    requested_at = fields.Datetime(required=True, readonly=True,
                                    default=fields.Datetime.now)
    finished_at = fields.Datetime(readonly=True)
    selection_json = fields.Text(readonly=True)
    document_count = fields.Integer(readonly=True)
    line_count = fields.Integer(readonly=True)
    warning_count = fields.Integer(readonly=True)
    warning_details = fields.Text(readonly=True)
    error_message = fields.Text(readonly=True)
    result_message = fields.Text(readonly=True)
    file_ids = fields.One2many('business.navigator.export.file', 'batch_id', readonly=True)
    zip_attachment_id = fields.Many2one('ir.attachment', readonly=True)
    note = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'business.navigator.export.batch') or 'New'
        return super().create(vals_list)

    def action_download_zip(self):
        self.ensure_one()
        if not self.zip_attachment_id:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % self.zip_attachment_id.id,
            'target': 'self',
        }


class BusinessNavigatorExportFile(models.Model):
    _name = 'business.navigator.export.file'
    _description = 'Business Navigator Export File'
    _order = 'id'

    batch_id = fields.Many2one('business.navigator.export.batch', required=True,
                                ondelete='cascade')
    file_type = fields.Selection(
        [('sales_20', 'Sales 20%'), ('sales_9', 'Sales 9%'),
         ('purchases', 'Purchases')],
        required=True)
    filename = fields.Char(required=True)
    attachment_id = fields.Many2one('ir.attachment', required=True)
    document_count = fields.Integer()
    line_count = fields.Integer()
    amount_total = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', related='batch_id.company_id.currency_id')
    byte_size = fields.Integer()
    sha256 = fields.Char()

    def action_download(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % self.attachment_id.id,
            'target': 'self',
        }

    @api.model
    def _create_from_payload(self, batch, file_type, filename, payload_bytes,
                              document_count, line_count, amount_total):
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(payload_bytes),
            'res_model': 'business.navigator.export.file',
            'mimetype': 'text/plain',
        })
        sha256 = hashlib.sha256(payload_bytes).hexdigest()
        export_file = self.create({
            'batch_id': batch.id,
            'file_type': file_type,
            'filename': filename,
            'attachment_id': attachment.id,
            'document_count': document_count,
            'line_count': line_count,
            'amount_total': amount_total,
            'byte_size': len(payload_bytes),
            'sha256': sha256,
        })
        # Bind the attachment to its history record after the record exists,
        # so Odoo's standard attachment access checks follow the export-file
        # ACLs and multi-company record rule.
        attachment.res_id = export_file.id
        return export_file
