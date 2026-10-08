# -*- coding: utf-8 -*-
"""Установка справочника «Наши организации» (шаг 58).

Вызывается ТОЛЬКО при установке модуля (-i pmk_org): post_init_hook при -u
не запускается. Повторный вызов ничего не делает — первая проверка выходит,
если организация уже есть. Итого — ровно один раз.

Что делает:
  1. Налоги режимов в компании Odoo: «НДС 22%» — уже заведённый (на боевой
     базе id 7) получает ТОЛЬКО пометку режима: «Включён в цену» (пусто = по
     настройке компании; с шага З-2 — в цене) не меняется, группа («Налог
     15%») — до шага З-9 (дальше — ensure_tax_groups). «Без НДС», «НДС 5%», «НДС 7%» заводятся копией с него (та же
     страна налога, счета и «Включён в цену»), каждый в своей группе
     налогов. Налог с тем же названием уже есть (переустановка после
     удаления модуля) — он и помечается, копия не заводится.
     Затем (шаг З-9) налог «НДС 22%» — в группу «НДС 22%» вместо «Налог 15%»
     (ensure_tax_groups), и (шаг З-2) компания — «цены включают налог»:
     ensure_company_price_included.
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

«Цена с налогом» (шаг З-2, решение Антона 08.10.2026): цены ВСЕГДА с НДС.
Включается у компании Odoo целиком (account_price_include = tax_included),
налоги следуют компании: отдельных налогов «… (в цене)» нет, налог 7 и его
пометка режима не тронуты. Подробно — ensure_company_price_included.
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
    ensure_tax_groups(env, company)
    ensure_company_price_included(env, company)
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
            # компании, с шага З-2 «в цене») — налог сразу пригоден для счёта и
            # считает цену так же, как налог товаров.
            vals["price_include_override"] = base.price_include_override
            tax = base.copy(vals)
        else:
            vals.update(company_id=company.id, country_id=country.id)
            tax = Tax.create(vals)
        taxes[regime] = tax
    return taxes


def ensure_tax_groups(env, company):
    """Группа налога режима — словом режима (шаг З-9, 09.10.2026).

    Налог 7 «НДС 22% (продажа)» на боевой стоит в группе плана счетов
    «Налог 15%» (её делят ещё 15-процентные налоги 1–2 и закупочный 6). Группа —
    это подпись строки налога в итогах заказа и в штатной печати: в счёте
    покупателю было «Налог 15%: 9 918,03» при ставке 22%. Группу НЕ
    переименовываем (она чужая и общая) — налог режима переводим в свою
    группу с именем режима («НДС 22%», «Без НДС», «НДС 5%», «НДС 7%»: та же
    страна налога, заводится, если её нет — _ensure_group). Ставки, «Включён в
    цену», счета налога и пометки режимов не меняются; проводок на боевой нет.
    Счета группы (к уплате, к возмещению, авансовый — для закрытия периода по
    налогу) переходят из прежней группы в новую, где они пусты.

    Повторный вызов ничего не меняет (группа уже с именем режима). Вернуть:
    Настройки → Учёт → Налоги → «НДС 22% (продажа)» → «Группа налогов» →
    «Налог 15%». Возвращает {режим: (старая группа, новая группа)} — что
    перевели.
    """
    Tax = env["account.tax"].sudo().with_context(active_test=False)
    moved = {}
    for regime, _label in rg.REGIMES:
        tax = Tax.search([
            ("pmk_regime", "=", regime), ("type_tax_use", "=", "sale"),
            ("company_id", "=", company.id)], limit=1)
        if not tax:
            continue
        name = rg.TAXES[regime][2]
        group = tax.tax_group_id
        names = {group.with_context(lang=lang).name for lang in ("en_US", "ru_RU")} if group else set()
        if name in names:
            continue
        country = tax.country_id or company.account_fiscal_country_id or company.country_id
        new_group = _ensure_group(env, company, country, regime)
        _copy_group_accounts(group, new_group)
        tax.tax_group_id = new_group
        moved[regime] = (group, new_group)
        _logger.info("pmk_org: налог «%s» — группа «%s» вместо «%s»",
                     tax.name, new_group.name, group.name if group else "—")
    return moved


# Счета группы налогов: закрытие периода по налогу (сводная проводка) берёт
# их у группы. На боевой у «Налог 15%» заданы «к уплате» и «к возмещению»,
# у новых групп — пусто: при переводе налога переносим, чего у новой нет.
TAX_GROUP_ACCOUNTS = ("tax_payable_account_id", "tax_receivable_account_id",
                      "advance_tax_payment_account_id")


def _copy_group_accounts(old_group, new_group):
    """Счета прежней группы — в новую, если там пусто (своё не трогаем)."""
    if not old_group or not new_group:
        return
    vals = {}
    for name in TAX_GROUP_ACCOUNTS:
        if name in new_group._fields and not new_group[name] and old_group[name]:
            vals[name] = old_group[name].id
    if vals:
        new_group.write(vals)
        _logger.info("pmk_org: группе «%s» — счета из «%s»: %s",
                     new_group.name, old_group.name, ", ".join(sorted(vals)))


def ensure_company_price_included(env, company):
    """Компания Odoo — «цены включают налог» (решение Антона 08.10.2026).

    Цены на заводе ВСЕГДА с НДС: в расчёте, в КП («в том числе НДС 22%»), в
    будущем справочнике типовых изделий. Изделие за 150 ₽ от ИП Чулкова —
    150 ₽, в т. ч. НДС 22% (27,05); от ООО на УСН — те же 150 ₽, «Без НДС».
    Поэтому не отдельные налоги «в цене», а режим компании целиком:
    res.company.account_price_include = tax_included. Налоги, у которых
    «Включён в цену» не задан (price_include_override пусто: 7 «НДС 22%
    (продажа)», 8–10 режимов, 6 «НДС 22% (покупка)»), следуют компании —
    имена, группы и пометки налогов не меняются. Налоги режимов и налоги
    компании по умолчанию с явным «Не включён» (на боевой таких нет)
    возвращаются к «по настройке компании», чтобы одна цена не считалась
    двумя способами.

    Что это значит для расчётов Odoo: в строке счёта покупателю цена — та,
    что в расчёте, налог выделяется из неё (150 → без налога 122,95 + НДС
    27,05). Смена организации (налог строки по её режиму) цену не трогает:
    цена строки зависит только от товара, единицы и количества, а пересчёт
    цены под другой налог ядро делает лишь через налоговую позицию (её для
    режимов не используем). Закупка: цена поставщика (supplierinfo) в строке
    заказа поставщику — уже с НДС, итог заказа = сумме по прайсу. Себестоимость
    расчёта (pmk_bridge) берёт цены поставщиков напрямую, мимо налогов.

    Идемпотентно: компания уже в этом режиме — ничего не делает. Ядро не
    даёт сменить режим компании с проводками (account
    _check_set_account_price_include) — тогда ничего не меняем, в журнал
    ошибка, вернёт False (на боевой проводок нет: 1 черновик без строк).

    Откат (пока нет проводок): Настройки → Учёт → Налоги → «Цены» → «Без
    налога» или SQL UPDATE res_company SET account_price_include =
    'tax_excluded' WHERE id = 1 — docs/disabled-features.md, шаг З-2.
    """
    company = company.sudo()
    if company.account_price_include != "tax_included":
        if company._existing_accounting():
            _logger.error(
                "pmk_org: у компании %s уже есть проводки — режим «цены включают налог» "
                "не включён (ядро запрещает). Решить с бухгалтером руками.", company.name)
            return False
        company.account_price_include = "tax_included"
        _logger.info("pmk_org: компания %s — цены включают налог", company.name)
    Tax = env["account.tax"].sudo().with_context(active_test=False)
    taxes = Tax.search([("pmk_regime", "!=", False), ("company_id", "=", company.id)])
    taxes |= company.account_sale_tax_id | company.account_purchase_tax_id
    explicit = taxes.filtered(lambda tax: tax.price_include_override == "tax_excluded")
    if explicit:
        explicit.price_include_override = False
        _logger.info("pmk_org: налоги %s — «Включён в цену» по настройке компании",
                     explicit.mapped("name"))
    # price_include налога вычисляется от price_include_override, а смену
    # режима компании кэш не видит.
    env.invalidate_all()
    return True


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
