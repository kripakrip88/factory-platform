# -*- coding: utf-8 -*-
"""Цвет печатных форм и писем: фиолетовый Odoo → чёрный завода (разбор UX, шаг 30).

Боевая база, 02.10.2026 (SELECT res_company): основной цвет макета документов
#5e4766 (мастер «Настроить макет документа» взял его из штатного логотипа
Odoo), цвет кнопки в письмах #875A7B (умолчание модуля mail). Второй цвет
макета #010101 и текст кнопки #FFFFFF — уже чёрный и белый, их не трогаем.

ГДЕ ЭТО ВИДНО. Основной цвет действует только на внешних макетах печати
(web.styles_company_report, класс o_company_<id>_layout): заголовок и итог
«Запроса КП» и «Заказа на покупку», заказа на производство, накладных,
счетов. Цвет кнопки — кнопка «Открыть» и ссылка «Odoo» в уведомлениях
(mail.mail_notification_layout), приглашения календаря. КП (печать расчёта,
pmk_bridge/report/quotation_report.xml) собрано на web.basic_layout со своей
палитрой — его это не касается; письмо с КП внешнему получателю идёт без
кнопки и подвала.

Перекрашиваем только то, что ещё стоит фиолетовым: цвет, выбранный руками,
миграция не перебьёт. Запись — через ORM: write основного цвета пересобирает
стили отчётов (web: res.company._update_asset_style). Как вернуть —
docs/disabled-features.md, шаг 30.
"""

BLACK = "#16191c"
# Значения, которые считаем «фиолетовым Odoo», в нижнем регистре.
PURPLE = {
    "primary_color": {"#5e4766"},
    # Пусто — шаблоны писем подставят тот же #875A7B сами.
    "email_secondary_color": {"#875a7b", ""},
}


def make_black(env):
    """{id компании: {поле: прежнее значение}} — что перекрашено."""
    changed = {}
    companies = env["res.company"].sudo().with_context(active_test=False).search([])
    for company in companies:
        vals = {name: BLACK for name, old in PURPLE.items()
                if (company[name] or "").lower() in old}
        if vals:
            changed[company.id] = {name: company[name] or "" for name in vals}
            company.write(vals)
    return changed
