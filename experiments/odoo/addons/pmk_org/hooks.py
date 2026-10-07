# -*- coding: utf-8 -*-
"""Установка справочника «Наши организации» (шаг 58).

Вызывается ТОЛЬКО при установке модуля (-i pmk_org): post_init_hook при -u
не запускается. Повторный вызов ничего не делает — первая проверка выходит,
если организация уже есть. Итого — ровно один раз.

Что делает:
  1. Налоги режимов в компании Odoo: «НДС 22%» — уже заведённый (на боевой
     базе id 7) получает ТОЛЬКО пометку режима: его группа («Налог 15%») и
     «Включён в цену» (пусто = по настройке компании, цена без налога) не
     меняются. «Без НДС», «НДС 5%», «НДС 7%» заводятся копией с него (та же
     страна налога, счета и «Включён в цену»), каждый в своей группе
     налогов. Налог с тем же названием уже есть (переустановка после
     удаления модуля) — он и помечается, копия не заводится.
  2. Первая организация — из текущей компании (ИП Чулков): её карточка
     контрагента, ОГРНИП, банковский счёт, режим «НДС 22%» с 01.01.2026,
     флажок «по умолчанию».
  3. Все существующие сделки (и архивные), расчёты и счета покупателям
     (sale.order) — этой организацией. SQL-ом: без строк «Наша
     организация: → ИП Чулков» в истории каждой сделки.

Откат: удалить модуль (Приложения → «ПМК: наши организации»). Налоги
останутся (у них нет xmlid модуля, только колонка-пометка уходит); новые
три налога — в архив руками, если не нужны. Повторная установка их найдёт
по названию и снова пометит.

«Цена с налогом» (решение ждёт Антона): не здесь. Включать осознанно
отдельным шагом и сразу у компании (account_price_include) и у налогов —
иначе у товара с ценой 1000 итог станет 1000 вместо 1220.
"""

import datetime
import logging

from odoo.tools import SQL, float_compare
from odoo.tools.sql import column_exists

from odoo.addons.pmk_bridge.tools import seller

from .tools import regime as rg

_logger = logging.getLogger(__name__)

FIRST_REGIME = "vat22"
FIRST_REGIME_FROM = datetime.date(2026, 1, 1)


def post_init_hook(env):
    Org = env["pmk.org"].with_context(active_test=False)
    if Org.search_count([]):
        _logger.info("pmk_org: организации уже есть — установка ничего не меняет")
        return
    company = env.ref("base.main_company", raise_if_not_found=False) or env.company
    ensure_taxes(env, company)
    org = create_first_org(env, company)
    backfill_documents(env, org)


# ─── 1. Налоги режимов ────────────────────────────────────────────────────
def ensure_taxes(env, company):
    """Налог продаж на каждый режим, с пометкой pmk_regime. Возвращает {режим: налог}.

    Уже заведённые налоги НЕ меняются: только пометка режима (новая колонка
    этого модуля). Группа и «Включён в цену» у налога 7 («НДС 22%
    (продажа)», стоит у всех 753 товаров) остаются как были — смена
    «включён в цену» молча поменяла бы смысл всех цен (доводка шага 58).
    """
    Tax = env["account.tax"].sudo().with_context(active_test=False)
    taxes = {}
    for regime, _label in rg.REGIMES:
        taxes[regime] = Tax.search([
            ("pmk_regime", "=", regime), ("type_tax_use", "=", "sale"),
            ("company_id", "=", company.id)], limit=1)

    base = taxes["vat22"] or _find_vat22(Tax, company)
    if base and not base.pmk_regime:
        base.pmk_regime = "vat22"
    taxes["vat22"] = base

    # Страна налога — как у «НДС 22%» (на боевой — страна плана счетов, US):
    # группа налога обязана быть той же страны (account.tax
    # validate_tax_group_id). Налога нет вовсе (чистая база) — страна
    # компании, иначе Россия.
    country = base.country_id or company.account_fiscal_country_id or company.country_id \
        or env.ref("base.ru")

    for regime, _label in rg.REGIMES:
        if taxes[regime]:
            continue
        name, label, _group = rg.TAXES[regime]
        # Переустановка после удаления модуля: колонка пометки ушла вместе с
        # модулем, а налоги с этими названиями остались. Копия с тем же
        # названием упала бы на «Tax names must be unique!» (account.tax
        # _constrains_name: активные налоги той же компании, типа и страны) —
        # находим и снова помечаем.
        found = Tax.with_context(active_test=True).search([
            ("name", "=", name), ("type_tax_use", "=", "sale"),
            ("company_id", "child_of", company.root_id.id),
            ("country_id", "=", country.id), ("pmk_regime", "=", False)], limit=1)
        if found:
            found.pmk_regime = regime
            taxes[regime] = found
            continue
        vals = {
            "name": name,
            "amount": rg.RATES[regime],
            "amount_type": "percent",
            "type_tax_use": "sale",
            "description": label,
            "invoice_label": label,
            "pmk_regime": regime,
            "tax_group_id": _ensure_group(env, company, country, regime).id,
            "active": True,
        }
        if base:
            # Копия «НДС 22%»: та же компания, страна налога, счета
            # распределения и «Включён в цену» (сейчас пусто = по настройке
            # компании, «без налога») — налог сразу пригоден для счёта и
            # считает цену так же, как налог товаров.
            vals["price_include_override"] = base.price_include_override
            tax = base.copy(vals)
        else:
            vals.update(company_id=company.id, country_id=country.id)
            tax = Tax.create(vals)
        taxes[regime] = tax
    return taxes


def _find_vat22(Tax, company):
    """Уже заведённый «НДС 22%» продаж: налог продаж компании, иначе поиск."""
    def is_22(tax):
        return (tax and tax.type_tax_use == "sale" and tax.amount_type == "percent"
                and float_compare(tax.amount, 22.0, precision_digits=4) == 0)

    if is_22(company.account_sale_tax_id):
        return company.account_sale_tax_id
    for tax in Tax.search([("company_id", "=", company.id), ("type_tax_use", "=", "sale"),
                           ("amount_type", "=", "percent")]):
        if is_22(tax):
            return tax
    return Tax.browse()


def _ensure_group(env, company, country, regime):
    """Группа налогов режима — по имени, в стране налога; только для
    налогов, которые заводит хук: группу уже заведённого налога не трогаем."""
    Group = env["account.tax.group"].sudo()
    name = rg.TAXES[regime][2]
    group = Group.search([("company_id", "=", company.id), ("country_id", "=", country.id)]) \
        .filtered(lambda g: g.name == name)[:1]
    if not group:
        group = Group.create({
            "name": name,
            "company_id": company.id,
            "country_id": country.id,
            "sequence": 10,
        })
    return group


# ─── 2. Первая организация ────────────────────────────────────────────────
def create_first_org(env, company):
    partner = company.partner_id.sudo()
    # ОГРНИП у компании лежит в «company_registry», а поле контрагента ogrn
    # пустое. Переносим в карточку: «Заполнить по ИНН» и печать смотрят туда.
    if "ogrn" in partner._fields and not partner.ogrn and company.company_registry:
        partner.ogrn = company.company_registry
    org_type = seller.org_type_by_inn(partner.vat or company.vat)
    if org_type == "ip":
        signer = company.chief_id.name if "chief_id" in company._fields and company.chief_id else \
            rg.signer_from_name(company.name)
        position = "Индивидуальный предприниматель"
    else:
        signer = company.chief_id.name if "chief_id" in company._fields and company.chief_id else False
        position = "Директор" if signer else False
    accountant = False
    if "accountant_id" in company._fields and company.accountant_id:
        accountant = company.accountant_id.name
    vals = {
        "partner_id": partner.id,
        "org_type": org_type,
        "is_default": True,
        "sequence": 1,
        "bank_id": partner.bank_ids[:1].id or False,
        "signer_name": signer or False,
        "signer_position": position,
        "accountant_name": accountant,
        "regime_ids": [(0, 0, {"date_from": FIRST_REGIME_FROM, "regime": FIRST_REGIME})],
    }
    # Логотип — только свой: стандартный значок Odoo в справочник не тянем.
    if not company.uses_default_logo and company.logo:
        vals["logo"] = company.logo
    org = env["pmk.org"].sudo().with_context(mail_create_nolog=True).create(vals)
    _logger.info("pmk_org: заведена организация %s (id %s)", org.name, org.id)
    return org


# ─── 3. Существующие документы ────────────────────────────────────────────
def backfill_documents(env, org):
    for table in ("crm_lead", "pmk_metal_spec", "sale_order"):
        if not column_exists(env.cr, table, "pmk_org_id"):
            continue
        env.cr.execute(SQL(
            "UPDATE %s SET pmk_org_id = %s WHERE pmk_org_id IS NULL",
            SQL.identifier(table), org.id))
        _logger.info("pmk_org: %s — организация проставлена в %s строк", table, env.cr.rowcount)
    env.invalidate_all()
