# -*- coding: utf-8 -*-
"""Centralized business constants for the Business Navigator export.

Keeping every magic string / limit here avoids scattering literals across
the service, formatter and wizard layers (see functional spec §19.4
"Поддръжка — Бизнес константите са централизирани").
"""

# Document type text mapping (spec §10.1)
MOVE_TYPE_TEXT = {
    'out_invoice': 'фак.към продажба',
    'out_refund': 'кр.изв.към връщане към нас',
    'in_invoice': 'фак.към доставка',
    'in_refund': 'кр.изв.към връщане от нас',
}

SALE_MOVE_TYPES = ('out_invoice', 'out_refund')
PURCHASE_MOVE_TYPES = ('in_invoice', 'in_refund')
ALL_MOVE_TYPES = SALE_MOVE_TYPES + PURCHASE_MOVE_TYPES

# Fallback sign for zero-value lines (spec §10.4), applied to abs(quantity)
ZERO_LINE_QUANTITY_SIGN = {
    'out_invoice': -1,
    'out_refund': 1,
    'in_invoice': 1,
    'in_refund': -1,
}

FILE_TYPE_SALES_20 = 'sales_20'
FILE_TYPE_SALES_9 = 'sales_9'
FILE_TYPE_PURCHASES = 'purchases'
FILE_TYPES = (FILE_TYPE_SALES_20, FILE_TYPE_SALES_9, FILE_TYPE_PURCHASES)

# Export scope selection modes (addendum v1.1 §2-§3)
SCOPE_MODE_DATE_RANGE = 'date_range'
SCOPE_MODE_DOCUMENT_NUMBERS = 'document_numbers'
SCOPE_MODES = (SCOPE_MODE_DATE_RANGE, SCOPE_MODE_DOCUMENT_NUMBERS)

ADVANCE_DESCRIPTION = 'Авансово плащане'

# Physical format limits (spec §3.1, §9)
FIELD_COUNT = 13
MAX_DESCRIPTION_LEN = 48
MAX_PARTNER_NAME_LEN = 48
MAX_PRODUCT_CODE_LEN = 13
MAX_SALES_NUMBER_LEN = 10
MAX_PURCHASE_REF_LEN = 15
MAX_PARTNER_REF_LEN = 4

ENCODING = 'cp1251'

# Blocking validation messages (spec §16.1)
VAL_MESSAGES = {
    'VAL-01': 'Началната дата не може да е след крайната дата.',
    'VAL-02': 'Експортът за Business Navigator е разрешен само за компания с основна валута EUR.',
    'VAL-03': 'Липсва invoice_date.',
    'VAL-04': 'Документът няма валиден sales number.',
    'VAL-05': 'Липсва номер на документа на доставчика.',
    'VAL-06': 'Контрагентът няма Business Navigator reference.',
    'VAL-07': 'Контрагентът няма регистрационен идентификатор.',
    'VAL-08': 'Не може да се нормализира supplier identification (липсва държава на контрагента).',
    'VAL-09': 'Кодът на продукта надвишава 13 символа.',
    'VAL-10': 'Номерът на документа надвишава допустимата дължина.',
    'VAL-11': 'Кодът на контрагента (BN reference) надвишава допустимата дължина.',
    'VAL-12': 'Невалиден transaction line (quantity = 0).',
    'VAL-13': 'Редът не може да бъде класифициран в 20% или 9% ДДС.',
    'VAL-14': 'Конфликтна ДДС конфигурация: редът е едновременно 20% и 9%.',
    'VAL-15': 'Неподдържан CP1251 символ.',
    'VAL-16': 'Невалиден контролен символ след нормализация.',
    'VAL-17': 'Advance product code не е уникален сред активните продукти.',
    # Export scope selection validations (addendum v1.1 §8)
    'VAL-18': 'Моля, попълнете начална и крайна дата.',
    'VAL-19': 'Въведете поне един номер на фактура/документ.',
    'VAL-20': 'Не са намерени следните документи.',
    'VAL-21': 'Документът не е осчетоводен (posted).',
    'VAL-22': 'Номерът съответства на повече от една покупна фактура.',
}

# Warning messages (spec §16.2)
WRN_MESSAGES = {
    'WRN-01': 'Празен product.default_code.',
    'WRN-02': 'Описанието е съкратено до 48 символа.',
    'WRN-03': 'Името на контрагента е съкратено до 48 символа.',
    'WRN-04': 'Повторен период — вече съществува успешен export batch.',
    'WRN-05': 'Нулева цена и стойност — редът е включен с празни колони 6 и 8.',
    'WRN-06': 'Fallback от VAT към company registry.',
}
