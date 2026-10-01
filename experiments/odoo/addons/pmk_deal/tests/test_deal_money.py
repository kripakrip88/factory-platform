# -*- coding: utf-8 -*-
"""Сделка и расчёт (разбор UX, шаг 31): деньги, кнопка, заводские данные.

Гонять ТОЛЬКО на одноразовой базе (см. tests/__init__.py).
"""
from datetime import timedelta

from markupsafe import Markup

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged

from .. import hooks

NB = " "


@tagged("post_install", "-at_install")
class TestDealMoney(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.partner"].create({
            "name": "ООО «Арестак-Строй»", "is_company": True})
        cls.person = cls.env["res.partner"].create({
            "name": "Цыганов Михаил", "parent_id": cls.company.id})
        cls.Lead = cls.env["crm.lead"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)
        cls.lead = cls.Lead.create({
            "name": "МК п. Горный", "type": "opportunity",
            "partner_id": cls.person.id,
        })
        cls.Spec = cls.env["pmk.metal.spec"]

    def _spec(self, price=0.0, date=None, lead=None, **values):
        products = []
        if price:
            products.append(Command.create({
                "name": "Каркас", "qty": 1, "price_customer_unit": price}))
        return self.Spec.create({
            "opportunity_id": (lead or self.lead).id,
            "partner_id": self.company.id,
            "date": date or fields.Date.today(),
            "product_ids": products,
            **values,
        })

    # ─── деньги из расчёта ───────────────────────────────────────────────
    def test_without_spec_nothing_invented(self):
        self.assertFalse(self.lead.pmk_spec_id)
        self.assertFalse(self.lead.pmk_spec_summary)
        self.assertFalse(self.lead.pmk_spec_card)
        self.assertFalse(self.lead.pmk_no_price_label)
        self.assertEqual(self.lead.expected_revenue, 0.0)

    def test_revenue_and_line_come_from_the_spec(self):
        spec = self._spec(price=9500000.0)
        self.assertEqual(self.lead.pmk_spec_id, spec)
        self.assertEqual(self.lead.expected_revenue, 9500000.0)
        summary = self.lead.pmk_spec_summary.replace(NB, " ")
        self.assertTrue(summary.startswith(spec.name + " · "), summary)
        self.assertIn("цена 9 500 000 ₽", summary)
        self.assertIn("металл 0 ₽", summary)
        self.assertIn("маржа 100 %", summary)
        self.assertIn("9,5 млн ₽", self.lead.pmk_spec_card.replace(NB, " "))
        self.assertFalse(self.lead.pmk_no_price_label)
        # Карточки под названием (приёмка 01.10.2026, R1).
        self.assertEqual(self.lead.pmk_kpi_weight.replace(NB, " "), "0 кг")
        self.assertEqual(self.lead.pmk_kpi_price.replace(NB, " "), "9 500 000 ₽")
        self.assertEqual(self.lead.pmk_kpi_metal.replace(NB, " "), "0 ₽")
        self.assertEqual(self.lead.pmk_kpi_margin.replace(NB, " "), "100 %")

    def test_kpi_cards_empty_without_spec(self):
        for name in ("pmk_kpi_weight", "pmk_kpi_price", "pmk_kpi_metal", "pmk_kpi_margin"):
            with self.subTest(field=name):
                self.assertFalse(self.lead[name])
        spec = self._spec()
        self.assertEqual(self.lead.pmk_spec_id, spec)
        self.assertEqual(self.lead.pmk_kpi_price, "не назначена")
        self.assertEqual(self.lead.pmk_kpi_margin, "—", "Без цены клиенту маржи нет.")

    def test_price_change_moves_revenue(self):
        spec = self._spec(price=1000.0)
        self.assertEqual(self.lead.expected_revenue, 1000.0)
        spec.product_ids.price_customer_unit = 2500.0
        self.assertEqual(self.lead.expected_revenue, 2500.0)
        # Запись смены дохода в историю сделки (mail.tracking.value) здесь не
        # проверяем: доход меняет пересчёт от расчёта, а не правка сделки, и в
        # тестовой транзакции значение истории не появлялось даже после
        # precommit.run() (30.09.2026). На копии базы смотреть глазами.

    def test_latest_spec_is_the_main_one(self):
        today = fields.Date.today()
        old = self._spec(price=1000.0, date=today - timedelta(days=5))
        new = self._spec(price=2000.0, date=today)
        self.assertEqual(self.lead.pmk_spec_id, new)
        self.assertEqual(self.lead.expected_revenue, 2000.0)
        # Старый расчёт передатировали — главным стал он.
        old.date = today + timedelta(days=1)
        self.assertEqual(self.lead.pmk_spec_id, old)
        self.assertEqual(self.lead.expected_revenue, 1000.0)
        # Тот же день — побеждает более поздний номер (как в списке расчётов).
        old.date = today
        self.assertEqual(self.lead.pmk_spec_id, max(old, new, key=lambda s: s.id))

    def test_copy_stays_in_the_deal_and_becomes_main(self):
        """Приёмка 01.10.2026, R4: копия расчёта — в той же сделке, на
        сегодня, и она теперь главный расчёт (новый заменяет старый). Раньше
        сделка переносилась только из формы, открытой кнопкой «Расчёт и КП»."""
        today = fields.Date.context_today(self.lead)
        spec = self._spec(price=1000.0, date=today - timedelta(days=3))
        self.assertEqual(self.lead.pmk_spec_id, spec)
        copy = spec.copy()
        self.assertEqual(copy.opportunity_id, self.lead)
        self.assertEqual(copy.date, today)
        self.assertEqual(self.lead.pmk_spec_id, copy)
        self.assertEqual(self.lead.expected_revenue, 1000.0)
        self.assertEqual(self.lead.spec_count, 2)

    def test_detached_spec_leaves_the_deal(self):
        spec = self._spec(price=5000.0)
        self.assertEqual(self.lead.expected_revenue, 5000.0)
        spec.opportunity_id = False
        self.assertFalse(self.lead.pmk_spec_id)
        self.assertEqual(self.lead.expected_revenue, 0.0)
        other = self.Lead.create({"name": "Другая", "type": "opportunity"})
        spec.opportunity_id = other
        self.assertEqual(other.pmk_spec_id, spec)
        self.assertEqual(other.expected_revenue, 5000.0)

    def test_revenue_stays_writable(self):
        """sale_crm и быстрое создание пишут в доход — запись не падает."""
        lead = self.Lead.create({"name": "Без расчёта", "type": "opportunity",
                                 "expected_revenue": 777.0})
        self.assertEqual(lead.expected_revenue, 777.0)
        lead.expected_revenue = 888.0
        self.assertEqual(lead.expected_revenue, 888.0)

    def test_no_price_is_a_red_signal_not_a_block(self):
        profile = self.env["pmk.metal.profile"].search([("mass_per_meter", ">", 0)], limit=1)
        if not profile:
            self.skipTest("Нет сортамента в справочнике pmk_calc")
        # Позиция без карточки товара — «без цены» (price_state = no_link).
        profile.sudo().product_tmpl_id = False
        spec = self._spec()
        spec.product_ids = [Command.create({
            "name": "Балка", "qty": 1, "price_customer_unit": 1000.0,
            "line_ids": [Command.create({
                "calc_mode": "linear", "profile_id": profile.id,
                "length_mm": 6000.0, "qty": 1,
            })],
        })]
        self.assertEqual(spec.no_price_count, 1)
        self.assertEqual(self.lead.pmk_no_price_label, "без цены: 1")
        # Сигнал ничего не запрещает: доход — цена клиенту, как обычно.
        self.assertEqual(self.lead.expected_revenue, 1000.0)
        # Карточка «Маржа» — верхняя граница: металл занижен (R1).
        self.assertTrue(self.lead.pmk_price_incomplete)
        self.assertTrue(self.lead.pmk_kpi_margin.startswith("≤"), self.lead.pmk_kpi_margin)
        self.assertEqual(self.lead.pmk_no_price_count, 1)

    # ─── кнопка «Расчёт и КП» ────────────────────────────────────────────
    def test_button_without_spec_opens_new_form_with_defaults(self):
        action = self.lead.action_open_specs()
        self.assertEqual(action["res_model"], "pmk.metal.spec")
        self.assertEqual(action["views"], [(False, "form")])
        self.assertFalse(action.get("res_id"))
        ctx = action["context"]
        self.assertEqual(ctx["default_opportunity_id"], self.lead.id)
        self.assertEqual(ctx["default_partner_id"], self.company.id, "Клиент — компания.")
        self.assertEqual(ctx["default_contact_id"], self.person.id, "Человек — контакт.")
        self.assertEqual(ctx["default_note"], self.lead.name)
        # Форма открывается на новом расчёте — и он встаёт на сделку.
        spec = self.Spec.with_context(ctx).create({})
        self.assertEqual(spec.opportunity_id, self.lead)
        self.assertEqual(spec.partner_id, self.company)
        self.assertEqual(self.lead.pmk_spec_id, spec)

    def test_button_with_one_spec_opens_it(self):
        spec = self._spec()
        action = self.lead.action_open_specs()
        self.assertEqual(action["res_id"], spec.id)
        self.assertEqual(action["views"], [(False, "form")])

    def test_button_with_several_specs_opens_the_list(self):
        self._spec()
        self._spec()
        action = self.lead.action_open_specs()
        self.assertEqual(action["views"], [(False, "list"), (False, "form")])
        self.assertEqual(action["domain"], [("opportunity_id", "=", self.lead.id)])
        self.assertFalse(action.get("res_id"))

    def test_button_does_not_move_the_stage(self):
        stage = self.lead.stage_id
        self.lead.action_open_specs()
        self._spec()
        self.assertEqual(self.lead.stage_id, stage, "Без автоперехода.")

    # ─── клиент на карточке воронки ──────────────────────────────────────
    def test_client_for_person_company_and_private(self):
        """Штатное commercial_partner_id пусто у сделки на компанию и на
        частное лицо — наше «Клиент» заполнено всегда, когда клиент выбран."""
        private = self.env["res.partner"].create({"name": "Иванов Пётр"})
        cases = [
            (self.person, self.company, "человек из компании — компания"),
            (self.company, self.company, "компания — она сама"),
            (private, private, "частное лицо — он сам"),
        ]
        for partner, client, why in cases:
            with self.subTest(why):
                lead = self.Lead.create({"name": why, "type": "opportunity",
                                         "partner_id": partner.id})
                self.assertEqual(lead.pmk_client_id, client)
        self.assertFalse(self.Lead.create({"name": "Без клиента"}).pmk_client_id)

    # ─── объединение с прежней сделкой клиента ───────────────────────────
    def _merge_setup(self, old_source=False):
        """Прежняя сделка клиента (стадия дальше — она главная), вторая
        сделка-дубль с расчётом новее и заявка из письма."""
        today = fields.Date.today()
        old = self.Lead.create({
            "name": "Прежняя сделка", "type": "opportunity",
            "partner_id": self.company.id, "pmk_source": old_source,
            "stage_id": self.env.ref("crm.stage_lead2").id,
        })
        old_spec = self._spec(price=1000.0, date=today - timedelta(days=5), lead=old)
        twin = self.Lead.create({
            "name": "Дубль", "type": "opportunity", "partner_id": self.company.id,
            "stage_id": self.env.ref("crm.stage_lead1").id,
        })
        new_spec = self._spec(price=2000.0, date=today, lead=twin)
        letter = self.Lead.create({
            "name": "Запрос КП из письма", "type": "lead",
            "partner_id": self.company.id, "pmk_source": "mail",
        })
        return old, twin, letter, old_spec, new_spec

    def test_merge_keeps_mail_source_specs_and_revenue(self):
        old, twin, letter, old_spec, new_spec = self._merge_setup()
        merged = (old | twin | letter).merge_opportunity()
        self.assertEqual(merged, old, "Главная — прежняя сделка (как у ядра).")
        self.assertFalse(twin.exists())
        self.assertFalse(letter.exists())
        self.assertEqual(merged.pmk_source, "mail", "Пусто у прежней — «Почта» из письма.")
        self.assertEqual(new_spec.opportunity_id, merged,
                         "Расчёт удалённой сделки не остаётся без сделки.")
        self.assertEqual(merged.spec_ids, old_spec | new_spec)
        self.assertEqual(merged.pmk_spec_id, new_spec)
        self.assertEqual(merged.expected_revenue, 2000.0,
                         "Доход — цена главного расчёта, в согласии со строкой денег.")

    def test_merge_keeps_source_already_set(self):
        old, twin, letter, _old_spec, _new_spec = self._merge_setup(old_source="call")
        merged = (old | twin | letter).merge_opportunity()
        self.assertEqual(merged.pmk_source, "call", "Выбранное у прежней сделки остаётся.")

    def test_merge_without_specs_keeps_revenue(self):
        """Без расчётов — как у ядра: первая непустая сумма."""
        first = self.Lead.create({"name": "А", "type": "opportunity",
                                  "expected_revenue": 500.0,
                                  "stage_id": self.env.ref("crm.stage_lead2").id})
        second = self.Lead.create({"name": "Б", "type": "lead"})
        merged = (first | second).merge_opportunity()
        self.assertEqual(merged, first)
        self.assertEqual(merged.expected_revenue, 500.0)

    # ─── «зависла» ───────────────────────────────────────────────────────
    def test_rotting_after_stage_threshold(self):
        stage = self.env.ref("crm.stage_lead1")
        stage.rotting_threshold_days = 1
        self.lead.stage_id = stage
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE crm_lead SET date_last_stage_update = now() at time zone 'UTC' - interval '3 days' "
            "WHERE id = %s", [self.lead.id])
        self.lead.invalidate_recordset(["date_last_stage_update", "is_rotting", "rotting_days"])
        self.assertTrue(self.lead.is_rotting)
        self.assertEqual(self.lead.rotting_days, 3)
        self.assertIn(self.lead, self.env["crm.lead"].search([("is_rotting", "=", True)]),
                      "Штатный фильтр «Зависшие» её находит.")


@tagged("post_install", "-at_install")
class TestFactoryDefaults(TransactionCase):
    """hooks.py: сроки стадий, причины проигрыша, «Откуда пришёл», admin."""

    def test_stage_thresholds_only_where_empty(self):
        lead1 = self.env.ref("crm.stage_lead1")
        lead2 = self.env.ref("crm.stage_lead2")
        lead3 = self.env.ref("crm.stage_lead3")
        won = self.env.ref("crm.stage_lead4")
        (lead1 | lead3 | won).rotting_threshold_days = 0
        lead2.rotting_threshold_days = 5  # поменяли руками — не трогаем
        hooks.set_stage_thresholds(self.env)
        self.assertEqual(lead1.rotting_threshold_days, 1)
        self.assertEqual(lead2.rotting_threshold_days, 5)
        self.assertEqual(lead3.rotting_threshold_days, 7)
        self.assertEqual(won.rotting_threshold_days, 0, "Выиграно — без срока.")

    def test_lost_reasons_six_factory_ones(self):
        stock = [self.env.ref(x) for x in hooks.STOCK_LOST_REASONS]
        used = stock[0]
        for reason in stock:
            reason.active = True
        lead = self.env["crm.lead"].create({"name": "Проиграна", "type": "opportunity"})
        lead.action_set_lost(lost_reason_id=used.id)
        hooks.archive_stock_lost_reasons(self.env)
        self.assertTrue(used.active, "Причину старой сделки не прячем.")
        self.assertFalse(stock[1].active)
        self.assertFalse(stock[2].active)
        names = set(self.env["crm.lost.reason"].search([]).mapped("name"))
        self.assertLessEqual({
            "Цена выше конкурента", "Не устроил срок", "Нет металла в городе",
            "Клиент не ответил", "Не наш профиль", "Проект отложен",
        }, names)

    def test_backfill_source_only_mail_and_only_empty(self):
        Lead = self.env["crm.lead"].with_context(
            mail_create_nolog=True, tracking_disable=True)
        from_mail = Lead.create({"name": "Письмо", "type": "lead"})
        from_mail.message_post(body="Прошу посчитать", message_type="email")
        manual = Lead.create({"name": "Звонок", "type": "lead", "pmk_source": "call"})
        manual.message_post(body="Письмо после звонка", message_type="email")
        noted = Lead.create({"name": "Руками", "type": "lead"})
        noted.message_post(body="Заметка", message_type="comment",
                           subtype_xmlid="mail.mt_note")
        self.env.flush_all()
        hooks.backfill_source(self.env)
        self.assertEqual(from_mail.pmk_source, "mail")
        self.assertEqual(manual.pmk_source, "call", "Выбранное руками не трогаем.")
        self.assertFalse(noted.pmk_source, "Догадок нет — пусто.")

    def test_recompute_revenue_of_old_deals(self):
        lead = self.env["crm.lead"].create({"name": "№12", "type": "opportunity"})
        spec = self.env["pmk.metal.spec"].create({
            "opportunity_id": lead.id,
            "product_ids": [Command.create({"name": "Каркас", "qty": 1,
                                            "price_customer_unit": 9500000.0})],
        })
        self.env.flush_all()
        # Как на боевой базе до выкладки: доход вписан руками.
        self.env.cr.execute("UPDATE crm_lead SET expected_revenue = 1000 WHERE id = %s", [lead.id])
        lead.invalidate_recordset(["expected_revenue"])
        self.assertEqual(lead.expected_revenue, 1000.0)
        hooks.recompute_deal_money(self.env)
        lead.invalidate_recordset(["expected_revenue", "pmk_spec_id"])
        self.assertEqual(lead.pmk_spec_id, spec)
        self.assertEqual(lead.expected_revenue, 9500000.0)

    def test_rename_admin_keeps_login_and_is_idempotent(self):
        user = self.env.ref("base.user_admin")
        user.partner_id.name = "Administrator"
        user.signature = Markup("<div>Administrator</div>")
        hooks.rename_admin(self.env)
        self.assertEqual(user.name, "Антон Карнеев")
        self.assertEqual(user.login, "admin")
        self.assertIn("Антон Карнеев", str(user.signature))
        hooks.rename_admin(self.env)
        self.assertEqual(user.name, "Антон Карнеев")
        # Переименованного руками не трогаем.
        user.partner_id.name = "Иван Петров"
        hooks.rename_admin(self.env)
        self.assertEqual(user.name, "Иван Петров")
