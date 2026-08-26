# -*- coding: utf-8 -*-
import hashlib
from datetime import date
from decimal import Decimal
import unittest
import zipfile
from io import BytesIO

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged, new_test_user

from ..services import bn_constants as C
from ..services import bn_formatter as F
from ..services.bn_export_service import BnExportService
from .common import BnExportTestCommon


class TestBnFormatter(unittest.TestCase):
    """Byte-level contract tests for spec §3, §8 and §15 (TC-30..32)."""

    def test_text_normalization_and_cp1251_validation(self):
        self.assertEqual(F.sanitize_text('  A\tB\r\nC\u00a0—\u00a0D  '), 'A B C - D')
        self.assertEqual(F.truncate_text('abcdef', 4), ('abcd', True))
        self.assertIsNone(F.check_cp1251_encodable('Кирилица'))
        self.assertEqual(F.check_cp1251_encodable('Emoji 😀'), '😀')

    def test_number_formatting(self):
        self.assertEqual(F.format_money(Decimal('49.00')), '49')
        self.assertEqual(F.format_money(Decimal('27.5')), '27.50')
        self.assertEqual(F.format_money(Decimal('-262.9')), '-262.90')
        self.assertEqual(F.format_money(None), '')
        self.assertEqual(F.format_quantity(Decimal('-1')), '-1')
        self.assertEqual(F.format_quantity(Decimal('-0.5')), '-0.5')
        self.assertEqual(F.format_quantity(Decimal('2.00')), '2')

    def test_cp1251_tab_trailing_tab_crlf_layout(self):
        row = ['16-07-2026', 'фак.към продажба', '0000081547', 'Артикул',
               '117.021', '6.14', '-9', '55.27', 'Контрагент', '1777',
               '257893427', '', 'Не']
        payload = F.encode_rows([row, row])
        self.assertFalse(payload.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(payload.count(b'\r\n'), 2)
        self.assertTrue(payload.endswith(b'\t\r\n'))
        lines = payload.decode('cp1251').split('\r\n')[:-1]
        self.assertTrue(all(line.count('\t') == 13 for line in lines))
        with self.assertRaises(ValueError):
            F.encode_rows([row[:-1]])


@tagged('post_install', '-at_install')
class TestBnExportService(BnExportTestCommon):

    def _service(self, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31), **options):
        defaults = {
            'export_sales_20': True,
            'export_sales_9': True,
            'export_purchases': True,
            'include_zero_value_lines': True,
        }
        defaults.update(options)
        return BnExportService(self.env, self.company, date_from, date_to, defaults)

    @staticmethod
    def _codes(result, key='errors'):
        return {issue['code'] for issue in result[key]}

    def _single_row(self, result, file_type):
        payload = result['payloads'][file_type]['bytes'].decode('cp1251')
        return payload.rstrip('\r\n').split('\t')[:-1]

    def test_sales_invoice_and_credit_note_signs(self):
        self.bn_invoice(lines=[self.bn_line(quantity=2, price_unit=10)])
        self.bn_invoice(move_type='out_refund', lines=[self.bn_line(quantity=2, price_unit=10)])
        result = self._service(export_sales_9=False, export_purchases=False).generate()
        self.assertTrue(result['ok'])
        rows = [line.split('\t')[:-1] for line in
                result['payloads'][C.FILE_TYPE_SALES_20]['bytes'].decode('cp1251').split('\r\n') if line]
        self.assertEqual([(row[6], row[7]) for row in rows], [('-2', '20'), ('2', '-20')])

    def test_sales_tax_buckets_and_mixed_invoice(self):
        move = self.bn_invoice(lines=[
            self.bn_line(price_unit=10, taxes=self.tax_20),
            self.bn_line(price_unit=10, taxes=self.tax_9),
        ])
        result = self._service(export_purchases=False).generate()
        self.assertTrue(result['ok'])
        self.assertEqual(result['payloads'][C.FILE_TYPE_SALES_20]['line_count'], 1)
        self.assertEqual(result['payloads'][C.FILE_TYPE_SALES_9]['line_count'], 1)
        for bucket in (C.FILE_TYPE_SALES_20, C.FILE_TYPE_SALES_9):
            self.assertIn(move.name, result['payloads'][bucket]['bytes'].decode('cp1251'))

    def test_unmapped_and_conflicting_sales_tax_block_entire_export(self):
        tax_other = self.env['account.tax'].create({
            'name': 'BN Test VAT 0%', 'amount': 0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': self.company.id,
        })
        self.bn_invoice(lines=[self.bn_line(taxes=tax_other)])
        result = self._service(export_sales_9=False, export_purchases=False).validate()
        self.assertIn('VAL-13', self._codes(result))

        self.bn_invoice(lines=[self.bn_line(taxes=self.tax_20 | self.tax_9)])
        result = self._service(export_sales_9=False, export_purchases=False).validate()
        self.assertIn('VAL-14', self._codes(result))

    def test_purchase_bills_credit_notes_and_supplier_reference(self):
        self.bn_invoice(move_type='in_invoice', partner=self.partner_bn, ref='000001',
                        lines=[self.bn_line(quantity=1, price_unit=10)])
        self.bn_invoice(move_type='in_refund', partner=self.partner_foreign, ref='CN-001',
                        lines=[self.bn_line(quantity=1, price_unit=10)])
        result = self._service(export_sales_20=False, export_sales_9=False).generate()
        self.assertTrue(result['ok'])
        rows = [line.split('\t')[:-1] for line in
                result['payloads'][C.FILE_TYPE_PURCHASES]['bytes'].decode('cp1251').split('\r\n') if line]
        self.assertEqual([(row[1], row[6], row[7]) for row in rows], [
            ('фак.към доставка', '1', '-10'),
            ('кр.изв.към връщане от нас', '-1', '10'),
        ])

    def test_validations_date_currency_document_partner_and_quantity(self):
        result = self._service(date_from=date(2026, 8, 1), date_to=date(2026, 7, 1)).validate()
        self.assertIn('VAL-01', self._codes(result))

        original_currency = self.company.currency_id
        self.company.currency_id = self.env.ref('base.USD')
        result = self._service().validate()
        self.assertIn('VAL-02', self._codes(result))
        self.company.currency_id = original_currency

        bad_partner = self.partner_bn.copy({'ref': False})
        self.bn_invoice(partner=bad_partner, lines=[self.bn_line()])
        self.bn_invoice(move_type='in_invoice', partner=self.partner_bn, ref=False,
                        lines=[self.bn_line()])
        self.bn_invoice(lines=[self.bn_line(quantity=0)])
        result = self._service().validate()
        self.assertTrue({'VAL-05', 'VAL-06', 'VAL-12'} <= self._codes(result))

    def test_advance_zero_value_missing_code_and_lengths(self):
        self.bn_invoice(lines=[self.bn_line(product=self.product_advance, quantity=1, price_unit=-10)])
        blank_code_product = self._create_product(name='Free service', default_code=False)
        self.bn_invoice(lines=[self.bn_line(product=blank_code_product, price_unit=5)])
        self.bn_invoice(lines=[self.bn_line(quantity=1, price_unit=0)])
        result = self._service(export_sales_9=False, export_purchases=False).generate()
        self.assertTrue(result['ok'])
        self.assertTrue({'WRN-01', 'WRN-05'} <= self._codes(result, 'warnings'))
        rows = [line.split('\t')[:-1] for line in
                result['payloads'][C.FILE_TYPE_SALES_20]['bytes'].decode('cp1251').split('\r\n') if line]
        advance = next(row for row in rows if row[4] == '**')
        zero = next(row for row in rows if row[5] == '' and row[7] == '')
        self.assertEqual((advance[3], advance[5], advance[6], advance[7]),
                         ('Авансово плащане', '-10', '1', '-10'))
        self.assertEqual(zero[6], '-1')

        long_code = self._create_product(name='Long', default_code='X' * 14)
        self.bn_invoice(lines=[self.bn_line(product=long_code)])
        result = self._service(export_sales_9=False, export_purchases=False).validate()
        self.assertIn('VAL-09', self._codes(result))

    def test_identifier_fallback_cp1251_and_advance_uniqueness(self):
        vat_fallback_partner = self.partner_bn.copy({
            'company_registry': False, 'vat': 'BG203900003', 'country_id': self.bg_country.id,
        })
        self.bn_invoice(partner=vat_fallback_partner, lines=[self.bn_line()])
        result = self._service(export_sales_9=False, export_purchases=False).generate()
        self.assertTrue(result['ok'])
        row = self._single_row(result, C.FILE_TYPE_SALES_20)
        self.assertEqual(row[10], '203900003')
        self.assertIn('WRN-06', self._codes(result, 'warnings'))

        emoji_product = self._create_product(name='Emoji 😀', default_code='EMOJI')
        self.bn_invoice(lines=[self.bn_line(product=emoji_product)])
        result = self._service(export_sales_9=False, export_purchases=False).validate()
        self.assertIn('VAL-15', self._codes(result))

    def test_deterministic_payload_zip_and_empty_buckets(self):
        self.bn_invoice(lines=[self.bn_line(quantity=3, price_unit=6.14)])
        one = self._service(export_sales_9=True, export_purchases=False).generate()
        two = self._service(export_sales_9=True, export_purchases=False).generate()
        self.assertTrue(one['ok'] and two['ok'])
        first = one['payloads'][C.FILE_TYPE_SALES_20]['bytes']
        self.assertEqual(first, two['payloads'][C.FILE_TYPE_SALES_20]['bytes'])
        self.assertEqual(hashlib.sha256(first).hexdigest(),
                         hashlib.sha256(two['payloads'][C.FILE_TYPE_SALES_20]['bytes']).hexdigest())
        self.assertNotIn(C.FILE_TYPE_SALES_9, one['payloads'])
        zipped = BnExportService.build_zip({'Продажби 20.txt': first})
        with zipfile.ZipFile(BytesIO(zipped)) as archive:
            self.assertEqual(archive.namelist(), ['Продажби 20.txt'])
            self.assertEqual(archive.read('Продажби 20.txt'), first)

    def test_draft_is_excluded_and_invoice_date_is_used(self):
        posted = self.bn_invoice(invoice_date=date(2026, 7, 16), lines=[self.bn_line()])
        self._create_invoice(
            move_type='out_invoice', invoice_date=date(2026, 7, 16),
            invoice_line_ids=[self.bn_line()], partner_id=self.partner_bn.id,
        )
        result = self._service(export_sales_9=False, export_purchases=False).generate()
        self.assertTrue(result['ok'])
        self.assertEqual(result['payloads'][C.FILE_TYPE_SALES_20]['document_count'], 1)
        self.assertIn(posted.name, result['payloads'][C.FILE_TYPE_SALES_20]['bytes'].decode('cp1251'))


@tagged('post_install', '-at_install')
class TestBnExportWizard(BnExportTestCommon):

    def test_validation_only_creates_no_batch_or_attachment(self):
        self.bn_invoice(lines=[self.bn_line()])
        wizard = self.env['business.navigator.export.wizard'].create({
            'company_id': self.company.id, 'date_from': date(2026, 7, 1),
            'date_to': date(2026, 7, 31), 'export_sales_9': False,
            'export_purchases': False, 'run_validation_only': True,
        })
        before = self.env['business.navigator.export.batch'].search_count([])
        wizard.action_validate()
        self.assertEqual(wizard.state, 'validated')
        self.assertEqual(self.env['business.navigator.export.batch'].search_count([]), before)
        with self.assertRaises(UserError):
            wizard.action_generate()

    def test_failed_generate_is_retained_without_files(self):
        bad_partner = self.partner_bn.copy({'ref': False})
        self.bn_invoice(partner=bad_partner, lines=[self.bn_line()])
        wizard = self.env['business.navigator.export.wizard'].create({
            'company_id': self.company.id, 'date_from': date(2026, 7, 1),
            'date_to': date(2026, 7, 31), 'export_sales_9': False,
            'export_purchases': False,
        })
        wizard.action_generate()
        self.assertEqual(wizard.state, 'error')
        self.assertEqual(wizard.batch_id.state, 'failed')
        self.assertFalse(wizard.batch_id.file_ids)
        self.assertIn('VAL-06', wizard.batch_id.error_message)

    def test_generate_history_files_zip_and_repeat_warning(self):
        self.bn_invoice(lines=[self.bn_line()])
        values = {
            'company_id': self.company.id, 'date_from': date(2026, 7, 1),
            'date_to': date(2026, 7, 31), 'export_sales_9': False,
            'export_purchases': False,
        }
        wizard = self.env['business.navigator.export.wizard'].create(values)
        wizard.action_generate()
        self.assertEqual(wizard.state, 'done')
        batch = wizard.batch_id
        self.assertEqual(batch.state, 'done')
        self.assertEqual(len(batch.file_ids), 1)
        self.assertTrue(batch.zip_attachment_id)
        self.assertEqual(batch.file_ids.sha256, hashlib.sha256(
            batch.file_ids.attachment_id.raw).hexdigest())

        second = self.env['business.navigator.export.wizard'].create(values)
        second.action_validate()
        self.assertIn('WRN-04', second.result_summary)

    def test_export_access_requires_bn_group(self):
        user = new_test_user(self.env, login='bn_no_access', groups='account.group_account_invoice')
        with self.assertRaises(AccessError):
            self.env['business.navigator.export.wizard'].with_user(user).create({
                'company_id': self.company.id,
                'date_from': date(2026, 7, 1),
                'date_to': date(2026, 7, 31),
            })
