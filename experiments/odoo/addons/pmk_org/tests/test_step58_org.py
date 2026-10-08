# -*- coding: utf-8 -*-
"""Наши организации и налоговый режим (разбор UX, шаг 58, 08.10.2026).

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
    odoo -d pmk58_test -i pmk_org --test-enable \\
         --test-tags /pmk_org --stop-after-init --http-port 8099

Что проверяем:
  • установка: первая организация из компании Odoo, налоги режимов, ровно
    один раз (повторный хук ничего не делает), заполнение старых документов;
    уже заведённый «НДС 22%» не меняется (группа, «Включён в цену»), копии
    берут его «Включён в цену»; переустановка после удаления не дублирует
    налоги-копии (находит по названию);
    у ИП — тип «ИП», ОГРНИП перенесён из «company_registry», подписант;
  • шаг З-2: компания — «цены включают налог», налоги следуют ей (имена и
    пометки прежние, копий нет); при проводках режим не меняется;
  • режим на дату: до и после смены, раньше первой строки — самый ранний;
    без режима — понятная ошибка; одна дата — одна строка; флажок «по
    умолчанию» — у одной организации;
  • поле на документах: сделка по умолчанию, расчёт со сделки (и не
    переписывается сменой на сделке), без сделки — по умолчанию;
  • налог строк счёта покупателю — по организации и дате;
  • печать КП: ООО на УСН — «Без НДС (УСН)» и «ОГРН», без «ОГРНИП»; ИП на
    НДС — «в том числе НДС 22%: …» и «ОГРНИП»; ставка — по дате КП;
  • права: менеджер видит и выбирает, правит справочник только админ, пункт
    меню — только в «Настройках» у админа;
  • новая организация сохраняется из формы (Form) без карточки
    контрагента — её заводит create(); «Режим сегодня» не выдаёт будущую
    строку за действующую; кнопка «Расчёт и КП» у сделки без организации
    даёт расчёту организацию по умолчанию;
  • виды: «Наша организация» вместо «Организации» в шапке расчёта, в
    группе сделки под «Менеджером», в «Деталях заказа».

Глазами (форма справочника в светлой и тёмной теме, шапка расчёта, сделка,
печать КП) — основной агент на копии.
"""
import datetime
import re

from lxml import etree
from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, TransactionCase, new_test_user, tagged
from odoo.tools import SQL, mute_logger

from .. import hooks
from ..tools import regime as rg

D = datetime.date


@tagged("post_install", "-at_install")
class TestStep58Org(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("ru_RU")
        cls.company = cls.env.company
        cls.Org = cls.env["pmk.org"]
        cls.main_org = cls.Org._pmk_default()
        cls.manager = new_test_user(
            cls.env, login="pmk58_manager", name="Менеджер (шаг 58)",
            groups="base.group_user,sales_team.group_sale_salesman")
        cls.admin = new_test_user(
            cls.env, login="pmk58_admin", name="Админ (шаг 58)",
            groups="base.group_user,base.group_system,sales_team.group_sale_manager")
        cls.client = cls.env["res.partner"].create({
            "name": "ООО «Тайга-Металл» (шаг 58)", "is_company": True})
        bank = cls.env["res.bank"].create({"name": "Тестбанк (шаг 58)", "bic": "044525999"})
        cls.org_usn = cls.Org.create({
            "name": "ООО «Ромашка» (шаг 58)",
            "org_type": "ooo",
            "inn": "2721000057",  # контрольная сумма верна: base_vat проверяет ИНН у RU
            "kpp": "272101001",
            "ogrn": "1022700000058",
            "city": "Хабаровск",
            "street": "ул. Тестовая, 1",
            "signer_name": "Петров Пётр Петрович",
            "signer_position": "Директор",
            "regime_ids": [Command.create({"date_from": D(2026, 1, 1), "regime": "usn0"})],
        })
        cls.usn_account = cls.env["res.partner.bank"].create({
            "acc_number": "40702810000000000058",
            "partner_id": cls.org_usn.partner_id.id,
            "bank_id": bank.id,
        })
        cls.org_usn.bank_id = cls.usn_account
        cls.org_ip = cls.Org.create({
            "name": "ИП Сидоров Сидор Сидорович (шаг 58)",
            "org_type": "ip",
            "inn": "272100005888",
            "ogrn": "319272400000058",
            "signer_name": "Сидоров Сидор Сидорович",
            "signer_position": "Индивидуальный предприниматель",
            "regime_ids": [
                Command.create({"date_from": D(2026, 1, 1), "regime": "vat22"}),
                Command.create({"date_from": D(2027, 1, 1), "regime": "usn0"}),
            ],
        })
        # На чистой тестовой базе план счетов грузится ПОСЛЕ установки модуля
        # и налоги, заведённые хуком, не доживают до тестов; на боевой налоги
        # уже есть. ensure_taxes идемпотентен — вызываем явно. Следом —
        # компания «цены включают налог» (шаг З-2), как на боевой после
        # миграции 19.0.1.1.0 (при установке это уже сделал хук — повтор
        # ничего не меняет).
        hooks.ensure_taxes(cls.env, cls.company)
        hooks.ensure_company_price_included(cls.env, cls.company)
        cls.taxes = {
            regime: cls.env["account.tax"].search([
                ("pmk_regime", "=", regime), ("type_tax_use", "=", "sale"),
                ("company_id", "=", cls.company.id)])
            for regime, _label in rg.REGIMES
        }

    # ─── помощники ──────────────────────────────────────────────────────
    def _deal(self, user=None, **values):
        vals = {"name": "Каркас склада (шаг 58)", "type": "opportunity",
                "partner_id": self.client.id}
        vals.update(values)
        return self.env["crm.lead"].with_user(user or self.manager).create(vals)

    def _spec(self, user=None, **values):
        vals = {
            "partner_id": self.client.id,
            "note": "Каркас навеса",
            "product_ids": [Command.create({"name": "Каркас", "qty": 1,
                                            "price_customer_unit": 5000.0})],
        }
        vals.update(values)
        return self.env["pmk.metal.spec"].with_user(user or self.manager).with_context(
            mail_create_nolog=True).create(vals)

    def _print_html(self, spec, user=None):
        report = self.env["ir.actions.report"].with_user(user or self.manager)
        html, _fmt = report._render_qweb_html(
            "pmk_bridge.action_report_metal_spec_quotation", spec.ids)
        # Текст без разметки: «ОГРН <span>1022…</span>» → «ОГРН 1022…».
        text = re.sub(r"<[^>]+>", " ", html.decode().replace("\xa0", " "))
        return re.sub(r"\s+", " ", text)

    def _arch(self, model, view_type="form", view=None):
        view_id = self.env.ref(view).id if view else False
        views = self.env[model].with_user(self.manager).get_views([(view_id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    # ─── установка ──────────────────────────────────────────────────────
    def test_install_first_org_from_company(self):
        org = self.main_org
        self.assertTrue(org, "Установка завела первую организацию.")
        self.assertTrue(org.is_default)
        self.assertEqual(org.partner_id, self.company.partner_id,
                         "Организация — карточка контрагента текущей компании.")
        self.assertEqual(org.name, self.company.name)
        self.assertEqual([(r.date_from, r.regime) for r in org.regime_ids],
                         [(D(2026, 1, 1), "vat22")])
        vat22 = self.taxes["vat22"]
        for regime, _label in rg.REGIMES:
            with self.subTest(regime=regime):
                self.assertEqual(len(self.taxes[regime]), 1, "Ровно один налог продаж на режим.")
                tax = self.taxes[regime]
                self.assertAlmostEqual(tax.amount, rg.RATES[regime])
                self.assertEqual(tax.type_tax_use, "sale")
                self.assertEqual(tax.price_include_override, vat22.price_include_override,
                                 "«Включён в цену» — как у «НДС 22%»: цены считаются одинаково.")
                self.assertTrue(tax.price_include,
                                "Шаг З-2: компания «цены включают налог», налог следует ей.")
                if regime != "vat22":
                    self.assertEqual(tax.tax_group_id.name, rg.TAXES[regime][2],
                                     "Новый налог — в своей группе.")

    def test_install_keeps_existing_vat22(self):
        """Уже заведённый «НДС 22%» (на боевой — налог 7 у всех товаров)
        получает только пометку: группа и «Включён в цену» прежние."""
        ru = self.env.ref("base.ru")
        company = self.env["res.company"].create({"name": "ООО «Налоги» (шаг 58)",
                                                  "country_id": ru.id})
        group = self.env["account.tax.group"].create({
            "name": "Налог 15%", "company_id": company.id, "country_id": ru.id})
        vat22 = self.env["account.tax"].create({
            "name": "НДС 22% (продажа)", "amount": 22.0, "amount_type": "percent",
            "type_tax_use": "sale", "company_id": company.id, "country_id": ru.id,
            "tax_group_id": group.id})
        self.assertFalse(vat22.price_include_override, "Посылка: как на боевой — пусто.")
        taxes = hooks.ensure_taxes(self.env, company)
        self.assertEqual(taxes["vat22"], vat22)
        self.assertEqual(vat22.pmk_regime, "vat22")
        self.assertEqual(vat22.tax_group_id, group, "Группа налога 22% не тронута.")
        self.assertFalse(vat22.price_include_override, "«Включён в цену» не тронут.")
        for regime in ("usn0", "usn5", "usn7"):
            with self.subTest(regime=regime):
                self.assertFalse(taxes[regime].price_include_override)
                self.assertEqual(taxes[regime].company_id, company)
                self.assertEqual(taxes[regime].tax_group_id.name, rg.TAXES[regime][2])

    def test_company_price_included(self):
        """Шаг З-2 (решение Антона 08.10.2026): цены ВСЕГДА с НДС — режим
        компании, а не отдельные налоги. Налоги с пустым «Включён в цену»
        (как 6, 7–10 на боевой) следуют компании: имена, группы, пометки и
        число налогов прежние. Явное «Не включён» у налога режима
        возвращается к настройке компании. Повтор ничего не меняет."""
        ru = self.env.ref("base.ru")
        company = self.env["res.company"].create({"name": "ООО «В цене» (шаг З-2)",
                                                  "country_id": ru.id})
        self.assertEqual(company.account_price_include, "tax_excluded", "Посылка: как было на боевой.")
        group = self.env["account.tax.group"].create({
            "name": "Налог 15%", "company_id": company.id, "country_id": ru.id})
        vat22 = self.env["account.tax"].create({
            "name": "НДС 22% (продажа)", "amount": 22.0, "amount_type": "percent",
            "type_tax_use": "sale", "company_id": company.id, "country_id": ru.id,
            "tax_group_id": group.id})
        buy = self.env["account.tax"].create({
            "name": "НДС 22% (покупка)", "amount": 22.0, "amount_type": "percent",
            "type_tax_use": "purchase", "company_id": company.id, "country_id": ru.id,
            "tax_group_id": group.id})
        company.account_purchase_tax_id = buy
        taxes = hooks.ensure_taxes(self.env, company)
        self.assertFalse(vat22.price_include, "Посылка: налог сверху цены.")
        taxes["usn5"].price_include_override = "tax_excluded"
        names = {tax.id: tax.name for tax in taxes.values()}
        count = self.env["account.tax"].with_context(active_test=False).search_count([])

        self.assertTrue(hooks.ensure_company_price_included(self.env, company))
        self.assertEqual(company.account_price_include, "tax_included")
        self.assertEqual(taxes["vat22"], vat22)
        for regime, tax in taxes.items():
            with self.subTest(regime=regime):
                self.assertTrue(tax.price_include, "Налог режима следует компании — в цене.")
                self.assertFalse(tax.price_include_override)
                self.assertEqual(tax.pmk_regime, regime, "Пометка режима не переезжает.")
                self.assertEqual(tax.name, names[tax.id], "Имя налога не меняется.")
        self.assertEqual(vat22.tax_group_id, group)
        self.assertTrue(buy.price_include, "Налог закупки — тоже в цене (прайс поставщика с НДС).")
        self.assertFalse(buy.price_include_override)
        self.assertEqual(self.env["account.tax"].with_context(active_test=False).search_count([]),
                         count, "Копий «(в цене)» нет.")
        self.assertTrue(hooks.ensure_company_price_included(self.env, company), "Повтор — то же.")
        self.assertEqual(company.account_price_include, "tax_included")

    def test_company_price_included_blocked_by_entries(self):
        """Есть проводки — ядро не даёт сменить режим: ничего не меняем,
        сохранение не падает (миграция не роняет обновление)."""
        company = self.env["res.company"].create({"name": "ООО «С проводками» (шаг З-2)"})
        self.patch(type(company), "_existing_accounting", lambda self: True)
        with mute_logger("odoo.addons.pmk_org.hooks"):
            self.assertFalse(hooks.ensure_company_price_included(self.env, company))
        self.assertEqual(company.account_price_include, "tax_excluded")

    def test_reinstall_finds_taxes_by_name(self):
        """После удаления модуля колонка пометки уходит, налоги остаются:
        повторная установка находит их по названию, а не копирует заново
        (копия упала бы на «Tax names must be unique!»)."""
        before = {r: t.id for r, t in self.taxes.items()}
        self.env.flush_all()
        self.env.cr.execute(SQL("UPDATE account_tax SET pmk_regime = NULL WHERE id = ANY(%s)",
                                [t.id for r, t in self.taxes.items() if r != "vat22"]))
        self.env.invalidate_all()
        count = self.env["account.tax"].with_context(active_test=False).search_count([])
        again = hooks.ensure_taxes(self.env, self.company)
        self.assertEqual({r: t.id for r, t in again.items()}, before)
        self.assertEqual(self.env["account.tax"].with_context(active_test=False).search_count([]),
                         count, "Новых налогов нет.")
        for regime, tax in again.items():
            self.assertEqual(tax.pmk_regime, regime)

    def test_install_hook_runs_once(self):
        orgs = self.Org.with_context(active_test=False).search([])
        taxes = self.env["account.tax"].with_context(active_test=False).search([])
        hooks.post_init_hook(self.env)
        self.assertEqual(self.Org.with_context(active_test=False).search([]), orgs,
                         "Повторный вызов не заводит вторую организацию.")
        self.assertEqual(self.env["account.tax"].with_context(active_test=False).search([]), taxes)
        # Налоги режимов — тоже идемпотентно.
        again = hooks.ensure_taxes(self.env, self.company)
        self.assertEqual({r: t.id for r, t in again.items()},
                         {r: t.id for r, t in self.taxes.items()})

    def test_install_backfills_documents(self):
        deal = self._deal()
        spec = self._spec(opportunity_id=deal.id)
        self.env.flush_all()
        for table, rec in (("crm_lead", deal), ("pmk_metal_spec", spec)):
            self.env.cr.execute(SQL("UPDATE %s SET pmk_org_id = NULL WHERE id = %s",
                                    SQL.identifier(table), rec.id))
        self.env.invalidate_all()
        self.assertFalse(deal.pmk_org_id)
        hooks.backfill_documents(self.env, self.main_org)
        self.assertEqual(deal.pmk_org_id, self.main_org)
        self.assertEqual(spec.pmk_org_id, self.main_org)

    def test_install_from_ip_company(self):
        """ИП: тип по ИНН, ОГРНИП из «company_registry» в карточку, подписант
        из названия, режим «НДС 22%» с 01.01.2026, флажок — у неё одной."""
        company = self.env["res.company"].create({
            "name": "ИП Петров Пётр Петрович (шаг 58)",
            "company_registry": "319272400000059",
        })
        company.partner_id.vat = "272100005951"
        org = hooks.create_first_org(self.env, company)
        self.assertEqual(org.org_type, "ip")
        self.assertEqual(org.reg_label, "ОГРНИП")
        self.assertEqual(org.ogrn, "319272400000059")
        self.assertEqual(company.partner_id.ogrn, "319272400000059")
        self.assertEqual(org.signer_name, "Петров Пётр Петрович (шаг 58)")
        self.assertEqual(org.signer_position, "Индивидуальный предприниматель")
        self.assertEqual(org.regime_ids.regime, "vat22")
        self.assertTrue(org.is_default)
        self.assertFalse(self.main_org.is_default, "Флажок «по умолчанию» — один.")
        self.assertFalse(org.logo, "Стандартный значок Odoo в справочник не тянем.")

    # ─── режим на дату ──────────────────────────────────────────────────
    def test_regime_at_date(self):
        org = self.org_ip
        self.assertEqual(org._pmk_regime_at(D(2026, 12, 31)).regime, "vat22")
        self.assertEqual(org._pmk_regime_at(D(2027, 1, 1)).regime, "usn0", "С даты смены — новый.")
        self.assertEqual(org._pmk_regime_at(D(2025, 3, 1)).regime, "vat22",
                         "Раньше первой строки — самый ранний режим, не «без налога».")
        self.assertEqual(org._pmk_sale_tax_at(D(2026, 6, 1)), self.taxes["vat22"])
        self.assertEqual(org._pmk_sale_tax_at(D(2027, 6, 1)), self.taxes["usn0"])
        rows = {r.date_from: r for r in org.regime_ids}
        with self.subTest("tax column"):
            self.assertEqual(rows[D(2027, 1, 1)].tax_id, self.taxes["usn0"])

    def test_org_without_regime_is_refused(self):
        with self.assertRaisesRegex(ValidationError, "налоговый режим"):
            self.Org.create({"name": "ООО «Без режима» (шаг 58)"})
        with self.assertRaisesRegex(ValidationError, "налоговый режим"):
            self.org_usn.write({"regime_ids": [Command.clear()]})

    def test_replace_last_regime_in_one_save(self):
        """Удалил старую строку и добавил новую одним сохранением — можно."""
        old = self.org_usn.regime_ids
        self.org_usn.write({"regime_ids": [
            Command.delete(old.id),
            Command.create({"date_from": D(2026, 2, 1), "regime": "usn5"}),
        ]})
        self.assertEqual(self.org_usn.regime_ids.regime, "usn5")

    def test_one_row_per_date(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.org_usn.write({"regime_ids": [
                    Command.create({"date_from": D(2026, 1, 1), "regime": "usn7"})]})
                self.env.flush_all()

    def test_single_default(self):
        self.org_usn.is_default = True
        self.assertFalse(self.main_org.is_default)
        self.assertEqual(self.Org._pmk_default(), self.org_usn)
        self.Org.search([]).write({"is_default": False})
        self.assertEqual(self.Org._pmk_default(), self.Org.search([], limit=1),
                         "Без флажка — первая активная по порядку.")

    def test_regime_today_label(self):
        self.assertEqual(self.org_usn.regime_today, "УСН без НДС")
        self.assertEqual(self.org_ip.regime_today,
                         rg.REGIME_LABELS[self.org_ip._pmk_regime_at(datetime.date.today()).regime])

    def test_regime_today_not_from_future_row(self):
        """Единственная строка «будет» — «Режим сегодня» не выдаёт её за
        действующую (печать задним числом по-прежнему берёт самую раннюю)."""
        start = D(datetime.date.today().year + 1, 1, 1)
        org = self.Org.create({
            "name": "ООО «Будущее» (шаг 58)",
            "regime_ids": [Command.create({"date_from": start, "regime": "usn0"})]})
        self.assertEqual(org.regime_ids.state, "future")
        self.assertEqual(org.regime_today,
                         "не задан (с %s — УСН без НДС)" % start.strftime("%d.%m.%Y"))
        self.assertEqual(org._pmk_regime_at(datetime.date.today()).regime, "usn0",
                         "Печать задним числом — по самой ранней строке, как и было.")

    # ─── поле на документах ─────────────────────────────────────────────
    def test_deal_default_and_spec_from_deal(self):
        deal = self._deal()
        self.assertEqual(deal.pmk_org_id, self.main_org, "Новая сделка — организация по умолчанию.")
        deal.pmk_org_id = self.org_usn
        self.assertEqual(deal._pmk_spec_defaults()["default_pmk_org_id"], self.org_usn.id)
        spec = self._spec(opportunity_id=deal.id)
        self.assertEqual(spec.pmk_org_id, self.org_usn, "Расчёт берёт организацию сделки.")
        deal.pmk_org_id = self.main_org
        self.assertEqual(spec.pmk_org_id, self.org_usn,
                         "Смена на сделке не переписывает уже посчитанный расчёт.")
        alone = self._spec()
        self.assertEqual(alone.pmk_org_id, self.main_org, "Без сделки — по умолчанию.")
        alone.opportunity_id = deal
        self.assertEqual(alone.pmk_org_id, self.main_org, "Привязали к сделке — организация сделки.")
        self.assertEqual(alone.copy().pmk_org_id, self.main_org, "Копия — с той же организацией.")

    def test_spec_from_deal_without_org_gets_default(self):
        """Сделка без организации: кнопка «Расчёт и КП» не кладёт пустую
        организацию в контекст — расчёт получает организацию по умолчанию."""
        deal = self._deal()
        deal.pmk_org_id = False
        ctx = deal.action_open_specs()["context"]
        self.assertNotIn("default_pmk_org_id", ctx)
        spec = self.env["pmk.metal.spec"].with_user(self.manager).with_context(ctx).create({})
        self.assertEqual(spec.pmk_org_id, self.main_org)

    def test_spec_from_deal_button_context(self):
        deal = self._deal(pmk_org_id=self.org_ip.id)
        ctx = deal.action_open_specs()["context"]
        spec = self.env["pmk.metal.spec"].with_user(self.manager).with_context(ctx).create({})
        self.assertEqual(spec.pmk_org_id, self.org_ip)

    def test_lead_gets_default_org(self):
        lead = self.env["crm.lead"].with_user(self.manager).create(
            {"name": "Заявка с почты (шаг 58)", "type": "lead"})
        self.assertEqual(lead.pmk_org_id, self.main_org)

    def test_sale_order_from_deal(self):
        deal = self._deal(pmk_org_id=self.org_usn.id)
        order = self.env["sale.order"].with_user(self.manager).create({
            "partner_id": self.client.id, "opportunity_id": deal.id})
        self.assertEqual(order.pmk_org_id, self.org_usn)
        plain = self.env["sale.order"].with_user(self.manager).create({"partner_id": self.client.id})
        self.assertEqual(plain.pmk_org_id, self.main_org)

    # ─── налог строк счёта покупателю ───────────────────────────────────
    def test_sale_line_tax_by_org_and_date(self):
        product = self.env["product.product"].create({
            "name": "Каркас (шаг 58)", "list_price": 1000.0,
            "taxes_id": [Command.set(self.taxes["vat22"].ids)]})

        def order(org, day):
            return self.env["sale.order"].create({
                "partner_id": self.client.id,
                "pmk_org_id": org.id,
                "date_order": datetime.datetime.combine(day, datetime.time(12, 0)),
                "order_line": [Command.create({"product_id": product.id, "product_uom_qty": 1})],
            })

        self.assertEqual(order(self.org_ip, D(2026, 6, 1)).order_line.tax_ids, self.taxes["vat22"])
        self.assertEqual(order(self.org_ip, D(2027, 2, 1)).order_line.tax_ids, self.taxes["usn0"],
                         "С 2027 года у фирмы УСН — налог строки «Без НДС».")
        usn = order(self.org_usn, D(2026, 6, 1))
        self.assertEqual(usn.order_line.tax_ids, self.taxes["usn0"],
                         "Налог режима — поверх налога товара «НДС 22%».")
        self.assertAlmostEqual(usn.amount_tax, 0.0)
        usn.pmk_org_id = self.org_ip
        self.assertEqual(usn.order_line.tax_ids, self.taxes["vat22"], "Сменили организацию — сменился налог.")
        # С шага З-2 цены включают налог (режим компании): итог = цене строки
        # (1000, из них НДС 180,33), как в КП «в том числе НДС». Смена
        # организации цену не трогает.
        self.assertAlmostEqual(usn.order_line.price_unit, 1000.0)
        self.assertAlmostEqual(usn.amount_total, 1000.0)
        self.assertAlmostEqual(usn.amount_tax, 180.33)

    # ─── печать КП ──────────────────────────────────────────────────────
    def test_print_usn_ooo(self):
        html = self._print_html(self._spec(pmk_org_id=self.org_usn.id))
        self.assertIn("ООО «Ромашка» (шаг 58)", html)
        self.assertIn("Без НДС (УСН)", html)
        self.assertNotIn("в том числе НДС", html)
        self.assertNotIn("ОГРНИП", html, "У ООО — ОГРН.")
        self.assertIn("ОГРН 1022700000058", html)
        self.assertIn("КПП 272101001", html)
        self.assertIn("р/с 40702810000000000058", html)
        self.assertIn("Хабаровск, ул. Тестовая, 1", html)
        self.assertIn("Директор", html)
        self.assertIn("Петров П. П.", html)

    def test_print_ip_vat(self):
        html = self._print_html(self._spec(pmk_org_id=self.org_ip.id, date=D(2026, 10, 8)))
        self.assertIn("ИП Сидоров Сидор Сидорович (шаг 58)", html)
        self.assertIn("ОГРНИП 319272400000058", html)
        self.assertIn("в том числе НДС 22%:", html)
        self.assertIn("901,64", html, "5 000 × 22 / 122 — «в том числе», а не сверху.")
        self.assertNotIn("Без НДС", html)
        self.assertIn("Сидоров С. С.", html)

    def test_print_tax_by_kp_date(self):
        before = self._spec(pmk_org_id=self.org_ip.id, date=D(2026, 12, 31))
        after = self._spec(pmk_org_id=self.org_ip.id, date=D(2027, 1, 10))
        self.assertEqual(before.pmk_print_tax(12200.0)[0], "в том числе НДС 22%:")
        self.assertAlmostEqual(before.pmk_print_tax(12200.0)[1], 2200.0)
        self.assertEqual(after.pmk_print_tax(12200.0), ("Без НДС (УСН)", None))

    def test_print_without_org_falls_back_to_company(self):
        spec = self._spec()
        spec.pmk_org_id = False
        info = spec.pmk_print_seller()
        self.assertEqual(info["name"], self.company.name, "Пусто — компания Odoo, как до шага 58.")
        label, _amount = spec.pmk_print_tax(100.0)
        self.assertTrue(label == "Без НДС" or label.startswith("в том числе НДС "),
                        "Ставка — из налога продаж компании, не зашитая.")

    # ─── права и меню ───────────────────────────────────────────────────
    def test_manager_reads_and_chooses_but_cannot_edit(self):
        Org = self.Org.with_user(self.manager)
        self.assertIn(self.org_usn, Org.search([]))
        self.assertEqual(Org.browse(self.org_usn.id).regime_ids.regime, "usn0")
        deal = self._deal()
        deal.with_user(self.manager).pmk_org_id = self.org_usn
        self.assertEqual(deal.pmk_org_id, self.org_usn)
        with self.assertRaises(AccessError):
            Org.browse(self.org_usn.id).write({"signer_name": "Чужой"})
        with self.assertRaises(AccessError):
            Org.create({"name": "ООО «Самоуправство»",
                        "regime_ids": [Command.create({"regime": "vat22"})]})
        with self.assertRaises(AccessError):
            self.env["pmk.org.regime"].with_user(self.manager).create(
                {"org_id": self.org_usn.id, "date_from": D(2028, 1, 1), "regime": "vat22"})

    def test_admin_edits(self):
        org = self.org_usn.with_user(self.admin)
        org.write({"signer_name": "Иванов Иван Иванович",
                   "regime_ids": [Command.create({"date_from": D(2028, 1, 1), "regime": "usn7"})]})
        self.assertEqual(self.org_usn._pmk_regime_at(D(2028, 5, 1)).regime, "usn7")

    def test_menu_admin_only(self):
        menu = self.env.ref("pmk_org.menu_pmk_org")
        self.assertEqual(menu.parent_id, self.env.ref("base.menu_administration"))
        self.assertEqual(menu.group_ids, self.env.ref("base.group_system"))
        Menu = self.env["ir.ui.menu"]
        self.assertIn(menu.id, Menu.with_user(self.admin)._visible_menu_ids())
        self.assertNotIn(menu.id, Menu.with_user(self.manager)._visible_menu_ids())

    def test_manager_prints_with_org(self):
        html = self._print_html(self._spec(pmk_org_id=self.org_usn.id), user=self.manager)
        self.assertIn("р/с 40702810000000000058", html, "Банк печатается и без прав на счета.")

    # ─── виды ───────────────────────────────────────────────────────────
    def test_spec_head_has_our_org(self):
        arch = self._arch("pmk.metal.spec")
        org = arch.xpath("//div[@name='pmk_f_org']")
        self.assertEqual(len(org), 1)
        self.assertIsNotNone(org[0].find("field[@name='pmk_org_id']"))
        company = arch.xpath("//div[@name='pmk_f_company']")
        if company:  # у пользователя одной компании блока нет вовсе (groups)
            self.assertEqual(company[0].get("invisible"), "1")
        blocks = [d.get("name") for d in arch.xpath(
            "//div[contains(concat(' ', @class, ' '), ' pmk-doc-head__fields ')]/div[@name]")]
        after = [b for b in blocks[blocks.index("pmk_f_price_date") + 1:] if b != "pmk_f_company"]
        self.assertEqual(after[:1], ["pmk_f_org"], "Вторая половина строки «Цены на дату».")
        self.assertEqual(self.env["pmk.metal.spec"].fields_get(["company_id"])["company_id"]["string"],
                         "Компания (служебное)")

    def test_deal_form_field_under_manager(self):
        arch = self._arch("crm.lead")
        deal = arch.xpath("/form/sheet/group/group[label[@for='date_deadline']]")[0]
        names = [f.get("name") for f in deal.findall("field")]
        self.assertEqual(names[names.index("user_id") + 1], "pmk_org_id")
        lead_group = arch.xpath("//group[@name='lead_partner']")[0]
        self.assertIsNone(lead_group.find("field[@name='pmk_org_id']"), "У лида поля нет.")

    def test_sale_order_form_field(self):
        arch = self._arch("sale.order")
        details = arch.xpath("//group[@name='order_details']")[0]
        names = [f.get("name") for f in details.findall("field")]
        self.assertIn("pmk_org_id", names)
        if "validity_date" in names:
            self.assertEqual(names[names.index("validity_date") - 1], "pmk_org_id",
                             "Над «Сроком действия».")
        # С шага З-9 (pmk_orders) организация счёта из расчёта меняется в
        # расчёте: поле закрыто ещё и при pmk_spec_id / у прежней редакции.
        readonly = details.find("field[@name='pmk_org_id']").get("readonly")
        self.assertIn("state in ['cancel', 'sale']", readonly)

    def test_org_form(self):
        arch = self._arch("pmk.org")
        self.assertIn("pmk-form", arch.get("class"))
        self.assertIsNone(arch.find(".//notebook"), "Без вкладок.")
        self.assertFalse(arch.xpath("//button[contains(@class, 'btn-primary') or contains(@class, 'oe_highlight')]"),
                         "Залитой кнопки нет: у справочника нет следующего шага.")
        labels = {f.get("id"): f.get("string") for f in arch.xpath("//field[@name='ogrn']")}
        self.assertEqual(labels, {"ogrn_ooo": "ОГРН", "ogrn_ip": "ОГРНИП"})
        requisites = arch.xpath("//group[@name='pmk_org_requisites']")[0]
        names = [f.get("name") for f in requisites.findall("field")]
        self.assertEqual(names[:2], ["org_type", "is_default"], "«По умолчанию» — под типом.")
        self.assertEqual(names[-1], "partner_id", "Служебная карточка — последней.")
        self.assertEqual(requisites.find("field[@name='partner_id']").get("invisible"), "not id")
        sign = arch.xpath("//group[@name='pmk_org_sign']")[0]
        self.assertEqual([f.get("name") for f in sign.findall("field")],
                         ["bank_id", "signer_name", "signer_position", "accountant_name", "active"])

    def test_new_org_saved_from_form(self):
        """Настройки → Наши организации → Создать: без карточки контрагента
        сохраняется (её заводит create()), как в браузере — Form проверяет
        обязательные видимые поля так же, как клиент."""
        form = Form(self.env["pmk.org"])
        form.name = "ООО «Из формы» (шаг 58)"
        form.city = "Хабаровск"
        with form.regime_ids.new() as row:
            row.date_from = D(2026, 1, 1)
            row.regime = "usn0"
        org = form.save()
        self.assertTrue(org.partner_id, "Карточку контрагента завёл create().")
        self.assertEqual(org.partner_id.name, "ООО «Из формы» (шаг 58)")
        self.assertEqual(org.partner_id.city, "Хабаровск", "Реквизиты — в карточку контрагента.")
        self.assertEqual(org.regime_ids.regime, "usn0")
