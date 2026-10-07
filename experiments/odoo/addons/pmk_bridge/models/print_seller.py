# -*- coding: utf-8 -*-
"""Продавец и налог в печати КП (разбор UX, шаг 58, 08.10.2026).

Шаблон КП (report/quotation_report.xml) больше не лезет в компанию сам: он
спрашивает у расчёта две вещи — pmk_print_seller() (шапка, банк, подпись) и
pmk_print_tax() (строка налога под итогом).

ЗДЕСЬ — ЗАПАСНОЙ ПУТЬ: компания Odoo расчёта, как печаталось до шага 58,
только без зашитых «22%» и «ОГРНИП». Справочник «Наши организации» (модуль
pmk_org) переопределяет оба метода и печатает выбранную в расчёте
организацию с её налоговым режимом на дату КП. Мост от pmk_org не зависит —
не установлен справочник, КП печатается как раньше.
"""

from odoo import models

from ..tools import seller


class MetalSpecPrintSeller(models.Model):
    _inherit = "pmk.metal.spec"

    def pmk_print_seller(self):
        """Реквизиты продавца для печати — словарём (tools/seller.py)."""
        self.ensure_one()
        # sudo: менеджер без прав на банковские счета компании тоже печатает
        # КП; читаем только то, что и так уходит клиенту на бумаге.
        company = self.company_id.sudo()
        partner = company.partner_id
        inn = partner.vat or company.vat
        bank = partner.bank_ids[:1]
        return seller.seller_info(
            name=company.name,
            inn=inn,
            kpp="kpp" in partner._fields and partner.kpp or False,
            org_type=seller.org_type_by_inn(inn),
            reg_number=("ogrn" in partner._fields and partner.ogrn) or company.company_registry,
            address=seller.address_line(False, company.city, company.street),
            phone=company.phone,
            email=company.email,
            bank=self._pmk_bank_info(bank),
        )

    def pmk_print_tax(self, total):
        """Строка налога: (подпись, сумма или None) — по налогу продаж компании."""
        self.ensure_one()
        tax = self.company_id.sudo().account_sale_tax_id
        rate = tax.amount if tax and tax.amount_type == "percent" else 0.0
        return seller.tax_line(rate, total)

    def _pmk_bank_info(self, bank):
        """Банковский счёт → словарь для строки «Реквизиты для оплаты»."""
        if not bank:
            return None
        bank = bank.sudo()
        return {
            "acc": bank.acc_number or "",
            "bank": bank.bank_id.name or "",
            "bic": bank.bank_id.bic or "",
            "corr": ("corr_acc" in bank.bank_id._fields and bank.bank_id.corr_acc) or "",
        }
