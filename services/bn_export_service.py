# -*- coding: utf-8 -*-
"""Extraction, classification, row preparation and orchestration for the
Business Navigator export (functional spec §4, §6, §9-§16, §20).

This module knows about Odoo recordsets but keeps all string/byte-level
formatting delegated to :mod:`bn_formatter`, and all business constants in
:mod:`bn_constants`, per §19.4 "Testability" / "Maintainability".
"""
import io
import zipfile
from datetime import date as date_cls
from decimal import Decimal

from . import bn_constants as C
from . import bn_formatter as F


class BnValidationIssue:
    """A single blocking (VAL-xx) or warning (WRN-xx) issue."""

    __slots__ = ('code', 'message', 'document', 'field', 'detail')

    def __init__(self, code, message, document='', field='', detail=''):
        self.code = code
        self.message = message
        self.document = document
        self.field = field
        self.detail = detail

    def to_dict(self):
        return {
            'code': self.code,
            'message': self.message,
            'document': self.document,
            'field': self.field,
            'detail': self.detail,
        }


class BnExportService:
    """One instance per export run (validate-only or generate)."""

    def __init__(self, env, company, date_from, date_to, options=None):
        self.env = env
        self.company = company
        self.date_from = date_from
        self.date_to = date_to
        options = options or {}
        self.export_sales_20 = options.get('export_sales_20', True)
        self.export_sales_9 = options.get('export_sales_9', True)
        self.export_purchases = options.get('export_purchases', True)
        self.include_zero_value_lines = options.get('include_zero_value_lines', True)
        self.selection_mode = options.get('selection_mode', C.SCOPE_MODE_DATE_RANGE)
        self.document_numbers = options.get('document_numbers', [])
        self.effective_date_from = date_from
        self.effective_date_to = date_to

        self.errors = []
        self.warnings = []
        # bucket -> list of typed row dicts (order §20.3)
        self._typed_rows = {ft: [] for ft in C.FILE_TYPES}
        self._partner_cache = {}
        self._sales_20_tax_ids = set(self.company.bn_sales_20_tax_ids.ids)
        self._sales_9_tax_ids = set(self.company.bn_sales_9_tax_ids.ids)

    # ------------------------------------------------------------------
    # Top-level entry points
    # ------------------------------------------------------------------

    def validate(self):
        """Run the full pipeline without producing any file payloads."""
        self._check_preconditions()
        if not self.errors:
            self._build_rows()
        return self._result_summary(with_payloads=False)

    def generate(self):
        """Run the full pipeline and, if no blocking errors, build the
        per-bucket TXT payloads (bytes) ready to be stored as attachments.
        """
        self._check_preconditions()
        if not self.errors:
            self._build_rows()
        result = self._result_summary(with_payloads=False)
        if not self.errors:
            result['payloads'] = self._build_payloads()
        return result

    # ------------------------------------------------------------------
    # Preconditions (§13.1, §7.2)
    # ------------------------------------------------------------------

    def _check_preconditions(self):
        eur = self.env.ref('base.EUR', raise_if_not_found=False)
        if self.selection_mode == C.SCOPE_MODE_DATE_RANGE:
            if not self.date_from or not self.date_to:
                self._add_error('VAL-18', field='Период')
            elif self.date_from > self.date_to:
                self._add_error('VAL-01')
        elif self.selection_mode == C.SCOPE_MODE_DOCUMENT_NUMBERS:
            if not self.document_numbers:
                self._add_error('VAL-19', field='Номера')
        if not eur or self.company.currency_id.id != eur.id:
            self._add_error('VAL-02')
        self._check_advance_code_uniqueness()

    def _check_advance_code_uniqueness(self):
        """§14.3 / VAL-17: the advance product code must uniquely identify
        (at most) one active product for the company, otherwise the ``**``
        recognition rule in :meth:`_is_advance_line` would be ambiguous.
        """
        code = self.company.bn_advance_product_code
        if not code:
            return
        products = self.env['product.product'].search([
            ('default_code', '=', code),
            ('active', '=', True),
            # Product codes may be reused by a product belonging exclusively
            # to another company. Only products usable in this export company
            # can make the advance marker ambiguous.
            ('company_id', 'in', [False, self.company.id]),
        ])
        if len(products) > 1:
            self._add_error('VAL-17', field='Код за аванс', detail=code)

    # ------------------------------------------------------------------
    # §6.1 domain / §8.1 ordering
    # ------------------------------------------------------------------

    def _allowed_move_types(self):
        move_types = []
        if self.export_sales_20 or self.export_sales_9:
            move_types += list(C.SALE_MOVE_TYPES)
        if self.export_purchases:
            move_types += list(C.PURCHASE_MOVE_TYPES)
        return move_types

    def _get_moves_by_date_range(self):
        move_types = self._allowed_move_types()
        if not move_types:
            return self.env['account.move']
        domain = [
            ('company_id', '=', self.company.id),
            ('state', '=', 'posted'),
            ('move_type', 'in', move_types),
            # Include missing invoice dates explicitly so they are reported as
            # VAL-03 rather than silently disappearing from the export.
            '|',
            ('invoice_date', '=', False),
            '&',
            ('invoice_date', '>=', self.date_from),
            ('invoice_date', '<=', self.date_to),
        ]
        return self.env['account.move'].search(domain, order='invoice_date, id')

    def _get_moves_by_document_numbers(self, numbers):
        """Addendum v1.1 §4: resolve each entered document number to a
        posted account.move, restricted to the move types allowed by the
        currently selected export options (§4 "Ако wizard-ът е конфигуриран
        за конкретен вид export..."). Sales documents are matched by
        ``move.name``, purchase documents by ``move.ref`` (§4 table).
        Any unresolved/ambiguous/unposted number blocks the ENTIRE export
        (§4.2) - no partial results are ever returned.
        """
        move_types = self._allowed_move_types()
        sale_types = [t for t in move_types if t in C.SALE_MOVE_TYPES]
        purchase_types = [t for t in move_types if t in C.PURCHASE_MOVE_TYPES]
        found = self.env['account.move']
        for number in numbers:
            matches = self.env['account.move']
            if sale_types:
                matches |= self.env['account.move'].search([
                    ('company_id', '=', self.company.id),
                    ('move_type', 'in', sale_types),
                    ('name', '=', number),
                ])
            if purchase_types:
                matches |= self.env['account.move'].search([
                    ('company_id', '=', self.company.id),
                    ('move_type', 'in', purchase_types),
                    ('ref', '=', number),
                ])
            if not matches:
                self._add_error('VAL-20', document=number, field='Номер')
                continue
            posted_matches = matches.filtered(lambda m: m.state == 'posted')
            if not posted_matches:
                self._add_error('VAL-21', document=number, field='Номер')
                continue
            if len(posted_matches) > 1:
                self._add_error(
                    'VAL-22', document=number, field='Номер',
                    detail=', '.join('%s (%s, %s)' % (
                        m.display_name, m.invoice_date, m.commercial_partner_id.name)
                        for m in posted_matches))
                continue
            found |= posted_matches
        return found

    def _get_export_moves(self):
        if self.selection_mode == C.SCOPE_MODE_DOCUMENT_NUMBERS:
            return self._get_moves_by_document_numbers(self.document_numbers)
        return self._get_moves_by_date_range()

    def _get_exportable_lines(self, move):
        lines = move.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        return lines.sorted(key=lambda l: (l.sequence, l.id))

    # ------------------------------------------------------------------
    # §11.3 sales VAT classification
    # ------------------------------------------------------------------

    def _classify_sales_line(self, line):
        tax_ids = set(line.tax_ids.ids)
        in_20 = bool(tax_ids & self._sales_20_tax_ids)
        in_9 = bool(tax_ids & self._sales_9_tax_ids)
        if in_20 and in_9:
            return None, 'VAL-14'
        if in_20:
            return C.FILE_TYPE_SALES_20, None
        if in_9:
            return C.FILE_TYPE_SALES_9, None
        return None, 'VAL-13'

    # ------------------------------------------------------------------
    # §9.1 document number
    # ------------------------------------------------------------------

    def _get_document_number(self, move):
        is_sale = move.move_type in C.SALE_MOVE_TYPES
        if is_sale:
            number = (move.name or '').strip()
            if not number or number == '/':
                self._add_error('VAL-04', document=move.display_name, field='Номер')
                return ''
            if len(number) > C.MAX_SALES_NUMBER_LEN:
                self._add_error('VAL-10', document=move.display_name, field='Номер',
                                 detail=number)
                return ''
        else:
            number = (move.ref or '').strip()
            if not number:
                self._add_error('VAL-05', document=move.display_name, field='Номер')
                return ''
            if len(number) > C.MAX_PURCHASE_REF_LEN:
                self._add_error('VAL-10', document=move.display_name, field='Номер',
                                 detail=number)
                return ''
        return F.sanitize_text(number)

    # ------------------------------------------------------------------
    # §9.2 / §12.2 partner identifiers (cached per commercial partner)
    # ------------------------------------------------------------------

    def _get_partner_identifiers(self, partner, move, is_purchase):
        cache_key = (partner.id, is_purchase)
        if cache_key in self._partner_cache:
            return self._partner_cache[cache_key]

        doc_name = move.display_name
        ref = (partner.ref or '').strip()
        if not ref:
            self._add_error('VAL-06', document=doc_name, field='Контрагент код')
        elif len(ref) > C.MAX_PARTNER_REF_LEN:
            self._add_error('VAL-11', document=doc_name, field='Контрагент код', detail=ref)

        company_registry = (partner.company_registry or '').strip()
        vat = (partner.vat or '').strip()
        registry_out = company_registry
        if not registry_out:
            if vat:
                is_bg = bool(partner.country_id) and partner.country_id.code == 'BG'
                normalized_vat = vat.upper().replace(' ', '')
                if is_bg and normalized_vat.startswith('BG'):
                    registry_out = normalized_vat[2:]
                else:
                    registry_out = normalized_vat
                self._add_warning('WRN-06', document=doc_name, field='ЕИК/рег.№',
                                   detail=registry_out)
            else:
                self._add_error('VAL-07', document=doc_name, field='ЕИК/рег.№')

        if is_purchase and not partner.country_id:
            self._add_error('VAL-08', document=doc_name, field='Държава')

        vat_out = vat.upper().replace(' ', '') if vat else ''

        partner_name, truncated = F.truncate_text(
            F.sanitize_text(partner.name or ''), C.MAX_PARTNER_NAME_LEN)
        if truncated:
            self._add_warning('WRN-03', document=doc_name, field='Контрагент',
                               detail=partner_name)

        result = {
            'partner_name': partner_name,
            'partner_ref': F.sanitize_text(ref),
            'company_registry': F.sanitize_text(registry_out),
            'vat': F.sanitize_text(vat_out),
        }
        self._partner_cache[cache_key] = result
        return result

    # ------------------------------------------------------------------
    # §10.2 / §10.3 amount and quantity sign
    # ------------------------------------------------------------------

    def _compute_export_amount(self, line):
        rounded = self.company.currency_id.round(-line.balance)
        return Decimal(str(rounded))

    def _compute_export_quantity(self, line, amount):
        qty = Decimal(str(abs(line.quantity)))
        if amount > 0:
            return -qty
        if amount < 0:
            return qty
        sign = C.ZERO_LINE_QUANTITY_SIGN.get(line.move_id.move_type, 1)
        return Decimal(sign) * qty

    # ------------------------------------------------------------------
    # §9 / §14 row assembly
    # ------------------------------------------------------------------

    def _is_advance_line(self, line):
        product = line.product_id
        code = self.company.bn_advance_product_code or ''
        return bool(product and code and product.default_code == code)

    def _prepare_row(self, move, line, partner_ids):
        doc_name = move.display_name
        is_purchase = move.move_type in C.PURCHASE_MOVE_TYPES
        is_advance = (not is_purchase) and self._is_advance_line(line)

        if line.quantity == 0:
            self._add_error('VAL-12', document=doc_name, field='Количество')
            return None

        amount_eur = self._compute_export_amount(line)
        quantity = self._compute_export_quantity(line, amount_eur)

        zero_value = amount_eur == 0
        unit_price = None
        if zero_value:
            if not self.include_zero_value_lines:
                return None
            self._add_warning('WRN-05', document=doc_name, field='Цена/Стойност')
            unit_price = None
        else:
            magnitude = abs(amount_eur) / abs(quantity) if quantity else Decimal('0')
            unit_price = -magnitude if is_advance else magnitude

        # Description (§9 col 4)
        if is_advance:
            description = C.ADVANCE_DESCRIPTION
        else:
            raw_desc = line.name or (line.product_id.name if line.product_id else '')
            description = F.sanitize_text(raw_desc)
        description, desc_truncated = F.truncate_text(description, C.MAX_DESCRIPTION_LEN)
        if desc_truncated:
            self._add_warning('WRN-02', document=doc_name, field='Описание',
                               detail=description)

        # Product code (§9 col 5)
        if is_advance:
            item_code = self.company.bn_advance_product_code or ''
        else:
            item_code = line.product_id.default_code if line.product_id else ''
            if not item_code:
                self._add_warning('WRN-01', document=doc_name, field='Код')
        if item_code and len(item_code) > C.MAX_PRODUCT_CODE_LEN:
            self._add_error('VAL-09', document=doc_name, field='Код', detail=item_code)
        item_code = F.sanitize_text(item_code)

        row = {
            'date': move.invoice_date,
            'document_type': C.MOVE_TYPE_TEXT.get(move.move_type, ''),
            'document_number': self._document_number_cache.get(move.id, ''),
            'item_name': description,
            'item_code': item_code,
            'unit_price_eur': unit_price,
            'quantity': quantity,
            'amount_eur': None if zero_value else amount_eur,
            'partner_name': partner_ids['partner_name'],
            'partner_ref': partner_ids['partner_ref'],
            'company_registry': partner_ids['company_registry'],
            'vat': partner_ids['vat'],
            'flag': F.sanitize_text(self.company.bn_last_flag or ''),
            '_move_id': move.id,
            '_move_name_sort': move.name if not is_purchase else (move.ref or ''),
        }

        # CP1251 encodability check (§8.4, §16.1 VAL-15) on every text field.
        for field_name in ('document_type', 'document_number', 'item_name',
                            'item_code', 'partner_name', 'partner_ref',
                            'company_registry', 'vat', 'flag'):
            bad_char = F.check_cp1251_encodable(row[field_name])
            if bad_char:
                self._add_error('VAL-15', document=doc_name, field=field_name,
                                 detail=repr(bad_char))

        return row

    # ------------------------------------------------------------------
    # Orchestration (§20.2)
    # ------------------------------------------------------------------

    def _build_rows(self):
        moves = self._get_export_moves()
        if self.errors:
            # Scope resolution already failed (VAL-20/21/22) - do not proceed
            # to row-building on a partial/ambiguous move set (§4.2).
            return
        moves = moves.sorted(key=lambda m: (m.invoice_date or date_cls.min, m.id))
        dated_moves = moves.filtered(lambda m: m.invoice_date)
        if dated_moves:
            self.effective_date_from = min(dated_moves.mapped('invoice_date'))
            self.effective_date_to = max(dated_moves.mapped('invoice_date'))
        self._document_number_cache = {}
        # Explicit prefetching keeps the 10k-line export on O(1)-ish query
        # counts instead of progressively loading relations inside the loop.
        invoice_lines = moves.mapped('invoice_line_ids')
        invoice_lines.mapped('tax_ids')
        moves.mapped('commercial_partner_id').mapped('country_id')

        for move in moves:
            is_purchase = move.move_type in C.PURCHASE_MOVE_TYPES
            if not move.invoice_date:
                self._add_error('VAL-03', document=move.display_name, field='Дата')
            self._document_number_cache[move.id] = self._get_document_number(move)

            partner = move.commercial_partner_id
            partner_ids = self._get_partner_identifiers(partner, move, is_purchase)

            for line in self._get_exportable_lines(move):
                row = self._prepare_row(move, line, partner_ids)
                if row is None:
                    continue
                if is_purchase:
                    if not self.export_purchases:
                        continue
                    bucket = C.FILE_TYPE_PURCHASES
                else:
                    bucket, err_code = self._classify_sales_line(line)
                    if err_code:
                        self._add_error(err_code, document=move.display_name,
                                         field='ДДС')
                        continue
                    if bucket == C.FILE_TYPE_SALES_20 and not self.export_sales_20:
                        continue
                    if bucket == C.FILE_TYPE_SALES_9 and not self.export_sales_9:
                        continue
                self._typed_rows[bucket].append(row)

    # ------------------------------------------------------------------
    # Formatting / payload building (§15)
    # ------------------------------------------------------------------

    def _sort_key(self, row):
        return (row['date'], row['document_number'], row['_move_id'])

    def _format_row(self, row):
        return [
            F.format_date(row['date']),
            row['document_type'],
            row['document_number'],
            row['item_name'],
            row['item_code'],
            F.format_money(row['unit_price_eur']),
            F.format_quantity(row['quantity']),
            F.format_money(row['amount_eur']),
            row['partner_name'],
            row['partner_ref'],
            row['company_registry'],
            row['vat'],
            row['flag'],
        ]

    def _build_payloads(self):
        payloads = {}
        for file_type, rows in self._typed_rows.items():
            if not rows:
                continue
            rows_sorted = sorted(rows, key=self._sort_key)
            formatted = [self._format_row(r) for r in rows_sorted]
            payload_bytes = F.encode_rows(formatted)
            amount_total = sum(
                (r['amount_eur'] for r in rows_sorted if r['amount_eur'] is not None),
                Decimal('0'))
            payloads[file_type] = {
                'bytes': payload_bytes,
                'line_count': len(rows_sorted),
                'document_count': len({r['_move_id'] for r in rows_sorted}),
                'amount_total': amount_total,
            }
        return payloads

    @staticmethod
    def build_zip(file_payloads_by_name):
        """file_payloads_by_name: dict filename -> bytes."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for filename, data in file_payloads_by_name.items():
                zf.writestr(filename, data)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Result summary
    # ------------------------------------------------------------------

    def _result_summary(self, with_payloads=False):
        total_errors = len(self.errors)
        return {
            'ok': total_errors == 0,
            'error_count': total_errors,
            'errors': [e.to_dict() for e in self.errors[:100]],
            'warnings': [w.to_dict() for w in self.warnings],
            'warning_count': len(self.warnings),
            'effective_date_from': self.effective_date_from,
            'effective_date_to': self.effective_date_to,
        }

    # ------------------------------------------------------------------
    # Issue collection helpers
    # ------------------------------------------------------------------

    def _add_error(self, code, document='', field='', detail=''):
        message = C.VAL_MESSAGES.get(code, code)
        self.errors.append(BnValidationIssue(code, message, document, field, detail))

    def _add_warning(self, code, document='', field='', detail=''):
        message = C.WRN_MESSAGES.get(code, code)
        self.warnings.append(BnValidationIssue(code, message, document, field, detail))
