# -*- coding: utf-8 -*-
"""Pure, side-effect-free formatting helpers for the Business Navigator export.

These functions intentionally know nothing about Odoo recordsets so they can
be unit tested in isolation (spec §19.4 "Testability").
"""
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

from . import bn_constants as C

# Characters that must be normalized to a CP1251-safe equivalent instead of
# triggering a hard encoding failure (spec §8.4 "Unicode hyphens/quotes").
_UNICODE_NORMALIZE_MAP = {
    '\u2010': '-', '\u2011': '-', '\u2012': '-', '\u2013': '-', '\u2014': '-',
    '\u2015': '-', '\u2212': '-',
    '\u2018': "'", '\u2019': "'", '\u201a': "'", '\u201b': "'",
    '\u201c': '"', '\u201d': '"', '\u201e': '"', '\u201f': '"',
    '\u00a0': ' ',  # NBSP
    '\u2007': ' ', '\u2009': ' ', '\u200b': '',
}

# Control characters that must become a single space before any further
# processing (TAB / CR / LF and other C0 control codes, spec §8.4).
_CONTROL_CHARS_RE = re.compile(r'[\t\r\n\x0b\x0c\x00-\x08\x0e-\x1f]')
_MULTI_SPACE_RE = re.compile(r' {2,}')


def normalize_unicode(value):
    """Replace unicode punctuation/space variants with CP1251-safe chars."""
    if not value:
        return ''
    for src, dst in _UNICODE_NORMALIZE_MAP.items():
        if src in value:
            value = value.replace(src, dst)
    return value


def sanitize_text(value):
    """Apply the full §8.4 text normalization pipeline.

    Order: control chars -> space, unicode normalize, collapse spaces, trim.
    Does NOT truncate - callers apply length limits explicitly so that a
    warning/error code can be attached to the right field.
    """
    if value is None:
        return ''
    text = str(value)
    text = _CONTROL_CHARS_RE.sub(' ', text)
    text = normalize_unicode(text)
    text = unicodedata.normalize('NFC', text)
    text = _MULTI_SPACE_RE.sub(' ', text)
    return text.strip()


def truncate_text(value, max_len):
    """Hard-truncate (no ellipsis) and report whether truncation happened."""
    if value is None:
        return '', False
    if len(value) <= max_len:
        return value, False
    return value[:max_len], True


def check_cp1251_encodable(value):
    """Return the first character in ``value`` that cannot be encoded as
    CP1251, or ``None`` if the whole string is encodable."""
    if not value:
        return None
    try:
        value.encode(C.ENCODING, errors='strict')
    except UnicodeEncodeError as exc:
        return value[exc.start:exc.start + 1]
    return None


def format_money(value):
    """Format a monetary Decimal per §15.3: 2-decimal rounding, trailing
    '.00' stripped (whole numbers have no decimal point), otherwise both
    decimal digits are kept even if the second is a zero (e.g. '27.50').
    Returns '' for ``None`` (blank column)."""
    if value is None:
        return ''
    quantized = Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    text = f'{quantized:.2f}'
    if text.endswith('.00'):
        text = text[:-3]
    elif text.endswith('-0.00'):
        text = text[:-3]
    if text in ('0', '-0'):
        text = '0'
    return text


def format_quantity(value, precision=2):
    """Format a quantity Decimal per §15.3: UoM precision, trailing zeros
    fully stripped, no scientific notation (e.g. '-1', '2', '-0.5')."""
    if value is None:
        return ''
    quant = Decimal(1).scaleb(-precision)
    quantized = Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)
    text = f'{quantized:.{precision}f}'
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    if text in ('', '-0', '-'):
        text = '0'
    return text


def format_date(value):
    """DD-MM-YYYY per spec §9 column 1."""
    if not value:
        return ''
    return value.strftime('%d-%m-%Y')


def encode_rows(rows):
    """Build the final CP1251 byte payload for a list of rows.

    ``rows`` is a list of lists/tuples with exactly ``FIELD_COUNT`` string
    values already formatted. Raises ``UnicodeEncodeError`` if strict
    CP1251 encoding fails (should never happen if callers already ran
    ``check_cp1251_encodable`` on every field).
    """
    lines = []
    for row in rows:
        if len(row) != C.FIELD_COUNT:
            raise ValueError(
                'Expected %d fields per row, got %d' % (C.FIELD_COUNT, len(row))
            )
        lines.append('\t'.join(row) + '\t\r\n')
    payload = ''.join(lines)
    return payload.encode(C.ENCODING, errors='strict')
