# -*- coding: utf-8 -*-
import base64
import json

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services import bn_constants as C
from ..services.bn_export_service import BnExportService


class BusinessNavigatorExportWizard(models.TransientModel):
    _name = 'business.navigator.export.wizard'
    _description = 'Business Navigator Export Wizard'

    company_id = fields.Many2one('res.company', required=True,
                                  default=lambda self: self.env.company)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    export_sales_20 = fields.Boolean(default=True)
    export_sales_9 = fields.Boolean(default=True)
    export_purchases = fields.Boolean(default=True)
    run_validation_only = fields.Boolean()
    include_zero_value_lines = fields.Boolean(default=True)
    note = fields.Text()

    # Result screen state
    state = fields.Selection(
        [('draft', 'Draft'), ('validated', 'Validated'), ('error', 'Error'),
         ('done', 'Done')],
        default='draft')
    result_summary = fields.Text(readonly=True)
    error_count = fields.Integer(readonly=True)
    warning_count = fields.Integer(readonly=True)
    batch_id = fields.Many2one('business.navigator.export.batch', readonly=True)

    def _ensure_allowed_company(self):
        """Do not let a crafted RPC payload export another allowed-by-ACL
        company's accounting data when that company is not enabled for the
        current user (spec §18.2).
        """
        self.ensure_one()
        if self.company_id not in self.env.user.company_ids:
            raise AccessError('Нямате достъп до избраната компания.')

    def _build_service(self):
        self._ensure_allowed_company()
        options = {
            'export_sales_20': self.export_sales_20,
            'export_sales_9': self.export_sales_9,
            'export_purchases': self.export_purchases,
            'include_zero_value_lines': self.include_zero_value_lines,
        }
        return BnExportService(self.env, self.company_id, self.date_from,
                                self.date_to, options)

    def _selection_dict(self):
        return {
            'company_id': self.company_id.id,
            'date_from': str(self.date_from),
            'date_to': str(self.date_to),
            'export_sales_20': self.export_sales_20,
            'export_sales_9': self.export_sales_9,
            'export_purchases': self.export_purchases,
            'include_zero_value_lines': self.include_zero_value_lines,
        }

    def _format_result_text(self, result):
        lines = []
        if result['errors']:
            lines.append('Грешки (%d):' % result['error_count'])
            for e in result['errors']:
                lines.append(' - [%s] %s (%s / %s)' % (
                    e['code'], e['message'], e['document'], e['field']))
            if result['error_count'] > len(result['errors']):
                lines.append(' ... и още %d' % (result['error_count'] - len(result['errors'])))
        if result['warnings']:
            lines.append('Предупреждения (%d):' % result['warning_count'])
            for w in result['warnings']:
                lines.append(' - [%s] %s (%s / %s)' % (
                    w['code'], w['message'], w['document'], w['field']))
        if not lines:
            lines.append('Няма открити проблеми.')
        return '\n'.join(lines)

    def _check_prior_batch_warning(self, result):
        existing = self.env['business.navigator.export.batch'].search([
            ('company_id', '=', self.company_id.id),
            ('date_from', '=', self.date_from),
            ('date_to', '=', self.date_to),
            ('state', '=', 'done'),
        ], limit=1)
        if existing:
            result['warnings'].append({
                'code': 'WRN-04',
                'message': C.WRN_MESSAGES['WRN-04'],
                'document': existing.name,
                'field': '',
            })
            result['warning_count'] += 1

    def action_validate(self):
        self.ensure_one()
        if not (self.export_sales_20 or self.export_sales_9 or self.export_purchases):
            raise UserError('Изберете поне един тип файл за експорт.')
        service = self._build_service()
        result = service.validate()
        self._check_prior_batch_warning(result)
        self.write({
            'state': 'validated' if result['ok'] else 'error',
            'result_summary': self._format_result_text(result),
            'error_count': result['error_count'],
            'warning_count': result['warning_count'],
        })
        return self._reopen_action()

    def action_generate(self):
        self.ensure_one()
        if self.run_validation_only:
            # Defense in depth: the button is hidden in the view when this
            # option is checked, but never allow attachments to be created
            # via a direct server-side/RPC call either (spec §7.2/§20.1).
            raise UserError(
                'Опцията "Само проверка" е активна - изберете Провери вместо Генерирай.')
        if not (self.export_sales_20 or self.export_sales_9 or self.export_purchases):
            raise UserError('Изберете поне един тип файл за експорт.')
        service = self._build_service()
        result = service.generate()
        self._check_prior_batch_warning(result)

        if not result['ok']:
            # A failed *generation* is retained in history (§1, §17), while
            # Validate remains side-effect free and creates no batch.
            batch = self._create_failed_batch(result)
            self.write({
                'state': 'error',
                'result_summary': self._format_result_text(result),
                'error_count': result['error_count'],
                'warning_count': result['warning_count'],
                'batch_id': batch.id,
            })
            return self._reopen_action()

        batch = self._create_batch_with_files(result)
        self.write({
            'state': 'done',
            'result_summary': self._format_result_text(result),
            'error_count': result['error_count'],
            'warning_count': result['warning_count'],
            'batch_id': batch.id,
        })
        return self._open_batch_action(batch)

    def _create_failed_batch(self, result):
        """Persist diagnostics for a failed Generate run without files."""
        return self.env['business.navigator.export.batch'].create({
            'company_id': self.company_id.id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'state': 'failed',
            'selection_json': json.dumps(self._selection_dict()),
            'warning_count': result['warning_count'],
            'warning_details': self._format_result_text({'errors': [], 'error_count': 0,
                                                          'warnings': result['warnings'],
                                                          'warning_count': result['warning_count']}),
            'error_message': self._format_result_text(result),
            'result_message': self._format_result_text(result),
            'finished_at': fields.Datetime.now(),
            'note': self.note,
        })

    def _create_batch_with_files(self, result):
        Batch = self.env['business.navigator.export.batch']
        File = self.env['business.navigator.export.file']
        batch = Batch.create({
            'company_id': self.company_id.id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'state': 'validating',
            'selection_json': json.dumps(self._selection_dict()),
            'warning_count': result['warning_count'],
            'warning_details': self._format_result_text(result),
            'result_message': self._format_result_text(result),
            'note': self.note,
        })

        payloads = result.get('payloads', {})
        filenames = self._build_filenames()
        total_lines = 0
        zip_entries = {}

        for file_type, data in payloads.items():
            filename = filenames[file_type]
            file_rec = File._create_from_payload(
                batch, file_type, filename, data['bytes'],
                data['document_count'], data['line_count'], data['amount_total'])
            total_lines += data['line_count']
            zip_entries[filename] = data['bytes']

        if zip_entries:
            zip_bytes = BnExportService.build_zip(zip_entries)
            zip_filename = self._build_zip_filename()
            zip_attachment = self.env['ir.attachment'].create({
                'name': zip_filename,
                'datas': base64.b64encode(zip_bytes),
                'res_model': 'business.navigator.export.batch',
                'res_id': batch.id,
                'mimetype': 'application/zip',
            })
            batch.zip_attachment_id = zip_attachment.id

        # NOTE: document_count is the sum of the per-file unique-document
        # counts (§7.4 defines document_count as "unique account.move per
        # file"; each business.navigator.export.file record already stores
        # the correct per-file figure). A mixed-VAT invoice split across
        # sales_20 and sales_9 is therefore counted once per file it
        # appears in - this is intentional and matches the per-file metric
        # definition, not a global cross-file unique count.
        batch.write({
            'state': 'done',
            'finished_at': fields.Datetime.now(),
            'document_count': sum(d['document_count'] for d in payloads.values()),
            'line_count': total_lines,
        })
        return batch

    def _company_label(self):
        name = self.company_id.name or ''
        return ''.join(ch for ch in name if ch.isalnum() or ch in (' ', '-', '_')).strip().replace(' ', '_')

    def _build_filenames(self):
        period = '%s-%s' % (self.date_from.strftime('%d.%m'), self.date_to.strftime('%d.%m.%Y'))
        company = self._company_label()
        return {
            C.FILE_TYPE_SALES_20: '%s_%s_%s.txt' % (
                self.company_id.bn_sales_20_filename_prefix, company, period),
            C.FILE_TYPE_SALES_9: '%s_%s_%s.txt' % (
                self.company_id.bn_sales_9_filename_prefix, company, period),
            C.FILE_TYPE_PURCHASES: '%s_%s_%s.txt' % (
                self.company_id.bn_purchase_filename_prefix, company, period),
        }

    def _build_zip_filename(self):
        company = self._company_label()
        return 'BN_Export_%s_%s_%s.zip' % (
            company, self.date_from.strftime('%Y%m%d'), self.date_to.strftime('%Y%m%d'))

    def _reopen_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _open_batch_action(self, batch):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'business.navigator.export.batch',
            'res_id': batch.id,
            'view_mode': 'form',
            'target': 'current',
        }
