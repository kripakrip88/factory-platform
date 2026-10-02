# -*- coding: utf-8 -*-
"""Раскрой: расчёт в шапке, клиент и хлысты из прайса, «В наличии», отход
словом — разбор UX, шаг 35 (02.10.2026), с доводкой по находкам проверки.

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).
⚠️ Хлысты из прайса проверяются, только если на базе стоит мост pmk_bridge:
связь раскроя с ним мягкая (pmk_cut от моста не зависит), и без моста эти
тесты пропускаются с пометкой «нужен pmk_bridge». Ставить вместе:
-i pmk_cut,pmk_bridge (или -i pmk_flow — он тянет оба).

Разметка — собранная, как её получает браузер (get_views). Глазами
(основной агент, широкий экран, обе темы): «Расчёт» во всю ширину шапки,
одна залитая кнопка в каждом состоянии, серая строка «Нет длины хлыста в
прайсе», «Хлыст 12 м (из прайса)» в колонке «Название» и очерёдность 100,
подпись «В наличии, шт / (0 — сколько нужно)» в две строки, жёлтая карточка
«Отход, %», плашка «много» во вкладке «Результат» и в списке раскроев.

Числа проверяются в уме:
  • расчёт: изделие «Навес» × 2; стойки 100x100x3 по 5000 × 2 → 4 отрезка,
    прогоны 60x60x3 по 2900 × 4 → 8, раскосы 80x80x4 по 1450 × 3 → 6;
  • прайс: 100x100x3 — хлыст 12 м, 60x60x3 — 11,7 м, у 80x80x4 строка без
    длины, 40x40x2 в прайсах нет вовсе («в городе нет»).
"""
import json
from collections import Counter
from datetime import timedelta
from unittest.mock import patch

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.modules.module import get_manifest
from odoo.tests import Form, TransactionCase, tagged
from odoo.tools.misc import file_open
from odoo.tools.safe_eval import safe_eval

from ..models.cut_plan import PRICE_BAR_PRIORITY
from ..models.cutting import WASTE_WARN_PCT, bar_name, waste_label

NBSP = " "


@tagged("post_install", "-at_install")
class TestCutStep35(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.Plan = cls.env["pmk.cut.plan"]
        # Мост (pmk_bridge) — мягкая связь: без него длины хлыста нет, и
        # карточки товара с прайсом заводить не к чему.
        cls.bridge = cls.Plan._pmk_price_bars_ready()
        today = fields.Date.context_today(cls.env["res.partner"])
        old = today - timedelta(days=30)
        Partner = cls.env["res.partner"]
        cls.client = Partner.create({"name": "ООО «Навес» (тест 35)", "is_company": True})
        cls.other = Partner.create({"name": "ООО «Другой» (тест 35)", "is_company": True})
        if cls.bridge:
            cls.metal = Partner.create({
                "name": "Металлсервис (тест 35)", "is_company": True, "pmk_supplier_rank": 1})
        ptype = cls.env["pmk.metal.profile.type"].create({"name": "Труба (тест 35)"})

        def profile(size, mass, length=None, priced=True):
            values = {
                "type_id": ptype.id, "profile_type": "Труба (тест 35)",
                "gost": "ГОСТ тест", "size_label": size, "mass_per_meter": mass}
            if cls.bridge:
                tmpl = cls.env["product.template"].create({"name": "Труба %s (тест 35)" % size})
                values["product_tmpl_id"] = tmpl.id
            prof = cls.env["pmk.metal.profile"].create(values)
            if cls.bridge and priced:
                cls.env["product.supplierinfo"].create({
                    "partner_id": cls.metal.id, "product_tmpl_id": tmpl.id,
                    "price": 100.0, "date_start": old,
                    "pmk_bar_length_mm": length or 0.0})
            return prof

        cls.p100 = profile("100x100x3", 9.0, 12000.0)
        cls.p60 = profile("60x60x3", 5.0, 11700.0)
        cls.p80 = profile("80x80x4", 9.4)                    # строка прайса без длины
        cls.p40 = profile("40x40x2", 2.3, priced=False)      # в прайсах нет

        cls.spec = cls.env["pmk.metal.spec"].create({
            "partner_id": cls.client.id,
            "product_ids": [Command.create({
                "name": "Навес", "qty": 2,
                "line_ids": [
                    Command.create({"calc_mode": "linear", "profile_id": cls.p100.id,
                                    "length_mm": 5000.0, "qty": 2, "detail_name": "Стойка"}),
                    Command.create({"calc_mode": "linear", "profile_id": cls.p60.id,
                                    "length_mm": 2900.0, "qty": 4, "detail_name": "Прогон"}),
                    Command.create({"calc_mode": "linear", "profile_id": cls.p80.id,
                                    "length_mm": 1450.0, "qty": 3, "detail_name": "Раскос"}),
                ]})],
        })

    # ─── помощники ──────────────────────────────────────────────────────
    def _need_bridge(self):
        if not self.bridge:
            self.skipTest("нужен pmk_bridge: хлыст из прайса берёт длину у моста")

    def _form(self):
        view = self.env.ref("pmk_cut.view_cut_plan_form")
        views = self.Plan.get_views([(view.id, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def _list(self):
        view = self.env.ref("pmk_cut.view_cut_plan_list")
        views = self.Plan.get_views([(view.id, "list")])
        return etree.fromstring(views["views"]["list"]["arch"])

    def _one(self, arch, expr):
        nodes = arch.xpath(expr)
        self.assertEqual(len(nodes), 1, expr)
        return nodes[0]

    @staticmethod
    def _stocks(plan, profile=None):
        stocks = plan.stock_ids
        if profile:
            stocks = stocks.filtered(lambda s: s.profile_id == profile)
        return {(s.profile_id, s.length_mm, s.qty) for s in stocks}

    def _price_bar(self, plan, profile):
        return plan.stock_ids.filtered(
            lambda s: s.profile_id == profile and "(из прайса)" in (s.name or ""))

    def _parts_plan(self, *parts, **values):
        return self.Plan.create(dict(values, part_ids=[
            Command.create({"profile_id": profile.id, "length_mm": length, "qty": qty})
            for profile, length, qty in parts]))

    @staticmethod
    def _used(result):
        """Сколько заготовок каждого названия ушло в дело — из сохранённого расчёта."""
        return Counter(bar["stock_name"] for bar in json.loads(result.result_json)["bars"])

    # ─── клиент из расчёта ──────────────────────────────────────────────
    def test_partner_comes_from_spec(self):
        plan = self.Plan.create({"spec_id": self.spec.id})
        self.assertEqual(plan.partner_id, self.client, "Клиент — из расчёта, сам.")
        manual = self.Plan.create({"spec_id": self.spec.id, "partner_id": self.other.id})
        self.assertEqual(manual.partner_id, self.other, "Заданный руками — не перетирается.")
        self.assertEqual(manual.copy().partner_id, self.other,
                         "Копия — с тем же клиентом, как до шага 35.")
        # Сменили на расчёт без клиента — прежний клиент остаётся.
        plan.spec_id = self.env["pmk.metal.spec"].create({})
        self.assertEqual(plan.partner_id, self.client)

    def test_partner_in_form_before_save(self):
        """Как в форме: выбрали расчёт — клиент подставился ещё до сохранения."""
        with Form(self.Plan) as form:
            form.spec_id = self.spec
            self.assertEqual(form.partner_id, self.client)

    # ─── «Заполнить из расчёта» ─────────────────────────────────────────
    def test_fill_parts_client_and_price_bars(self):
        self._need_bridge()
        plan = self.Plan.create({"spec_id": self.spec.id})
        plan.partner_id = False
        plan.action_fill_from_spec()
        self.assertEqual(plan.partner_id, self.client, "Пустой клиент — из расчёта.")
        self.assertEqual(
            {(p.profile_id, p.length_mm, p.qty) for p in plan.part_ids},
            {(self.p100, 5000.0, 4), (self.p60, 2900.0, 8), (self.p80, 1450.0, 6)},
            "Количество — на все изделия.")
        self.assertEqual(
            self._stocks(plan), {(self.p100, 12000.0, 0), (self.p60, 11700.0, 0)},
            "Хлыст по длине из прайса, «В наличии» 0 — сколько нужно.")
        self.assertEqual(set(plan.stock_ids.mapped("name")),
                         {"Хлыст 12 м (из прайса)", "Хлыст 11,7 м (из прайса)"})
        self.assertEqual(set(plan.stock_ids.mapped("priority")), {PRICE_BAR_PRIORITY},
                         "Докупка — в дело последней.")
        self.assertEqual(PRICE_BAR_PRIORITY, 100)
        self.assertGreater(PRICE_BAR_PRIORITY,
                           self.env["pmk.cut.stock"].default_get(["priority"])["priority"],
                           "После своих заготовок с очерёдностью по умолчанию.")
        self.assertEqual(plan.stock_missing_text, self.p80.display_name,
                         "Длины в прайсе нет — заготовку вводят руками, и это видно.")

    def test_fill_again_keeps_manual_stock_and_drops_old_result(self):
        self._need_bridge()
        plan = self.Plan.create({"spec_id": self.spec.id})
        plan.action_fill_from_spec()
        offcut = self.env["pmk.cut.stock"].create({
            "plan_id": plan.id, "profile_id": self.p80.id, "length_mm": 1800.0,
            "qty": 2, "priority": 1, "name": "Обрезок"})
        self.assertFalse(plan.stock_missing_text, "Заготовка есть — сигнал ушёл.")
        plan.action_compute()
        self.assertTrue(plan.result_ids)
        plan.action_fill_from_spec()
        self.assertFalse(plan.result_ids, "Результат прежних отрезков сброшен.")
        self.assertIn(offcut, plan.stock_ids, "Обрезок, заведённый руками, остался.")
        self.assertEqual(len(plan.stock_ids), 3, "Хлыст той же длины второй раз не добавлен.")

    def test_refill_does_not_bring_back_deleted_price_bar(self):
        """Цех режет только 6 м: хлыст из прайса удалили, свой оставили.
        Повторное заполнение его не возвращает — «свой набор не трогаем»."""
        self._need_bridge()
        plan = self.Plan.create({"spec_id": self.spec.id})
        plan.action_fill_from_spec()
        self._price_bar(plan, self.p100).unlink()
        self.env["pmk.cut.stock"].create({
            "plan_id": plan.id, "profile_id": self.p100.id, "length_mm": 6000.0,
            "qty": 5, "name": "Хлыст 6 м"})
        plan.action_fill_from_spec()
        self.assertEqual(self._stocks(plan, self.p100), {(self.p100, 6000.0, 5)},
                         "12 м из прайса не вернулся.")
        self.assertTrue(self._price_bar(plan, self.p60), "У 60x60x3 хлыст из прайса остался.")

    def test_refill_keeps_own_set_limited(self):
        """Свой набор «только эти 5 хлыстов» заполнение не расширяет: что не
        влезло — видно в «Не размещено», а не докупается молча."""
        self._need_bridge()
        plan = self.Plan.create({"spec_id": self.spec.id, "stock_ids": [Command.create({
            "profile_id": self.p60.id, "length_mm": 6000.0, "qty": 1, "name": "Хлыст 6 м"})]})
        plan.action_fill_from_spec()
        self.assertEqual(self._stocks(plan, self.p60), {(self.p60, 6000.0, 1)},
                         "У 60x60x3 свой набор — хлыст из прайса не добавлен.")
        self.assertTrue(self._price_bar(plan, self.p100), "Типоразмеру без заготовок — добавлен.")
        plan.action_compute()
        result = plan.result_ids.filtered(lambda r: r.profile_id == self.p60)
        self.assertEqual(result.bars_used, 1)
        self.assertTrue(result.unplaced_text, "Не влезло — видно.")
        self.assertNotIn("нет заготовок", result.unplaced_text, "Заготовка есть — её не хватило.")
        self.assertTrue(plan.has_unplaced)

    def test_fill_messages(self):
        with self.assertRaisesRegex(UserError, "Не выбран расчёт"):
            self.Plan.create({}).action_fill_from_spec()
        empty = self.env["pmk.metal.spec"].create({"partner_id": self.client.id})
        with self.assertRaisesRegex(UserError, "В расчёте нет линейного проката"):
            self.Plan.create({"spec_id": empty.id}).action_fill_from_spec()

    def test_spec_supplier_decides_the_bar(self):
        """Поставщик расчёта — его строка прайса: у него длины нет — ручной ввод."""
        self._need_bridge()
        other_supplier = self.env["res.partner"].create({
            "name": "Другой поставщик (тест 35)", "is_company": True})
        spec = self.spec.copy({"supplier_id": other_supplier.id})
        plan = self.Plan.create({"spec_id": spec.id})
        plan.action_fill_from_spec()
        self.assertFalse(plan.stock_ids, "У поставщика расчёта этих позиций нет.")
        self.assertIn(self.p100.display_name, plan.stock_missing_text)

    # ─── «Рассчитать»: хлыст из прайса для отрезков, введённых руками ────
    def test_compute_adds_price_bar_for_manual_parts(self):
        self._need_bridge()
        plan = self._parts_plan((self.p100, 4000.0, 3))
        self.assertFalse(plan.stock_missing_text, "Длина в прайсе есть — хлыст добавится сам.")
        plan.action_compute()
        self.assertEqual(self._stocks(plan), {(self.p100, 12000.0, 0)})
        self.assertEqual(plan.stock_ids.priority, PRICE_BAR_PRIORITY)
        self.assertEqual(len(plan.result_ids), 1)
        self.assertFalse(plan.has_unplaced)

    def test_compute_respects_existing_stock(self):
        """У типоразмера уже есть заготовки — их набор решает человек."""
        plan = self._parts_plan((self.p100, 4000.0, 3), stock_ids=[Command.create({
            "profile_id": self.p100.id, "length_mm": 6000.0, "qty": 1})])
        plan.action_compute()
        self.assertEqual(self._stocks(plan), {(self.p100, 6000.0, 1)})
        self.assertTrue(plan.has_unplaced, "Один хлыст 6 м — не всё влезло, и это видно.")

    def test_own_stock_goes_first_price_bar_last(self):
        """Находка проверки: при общей очерёдности расчёт брал хлыст из прайса
        вместо складских (меньше лома) — докупка вместо своего металла."""
        self._need_bridge()
        Stock = self.env["pmk.cut.stock"]
        cases = [
            # (свой хлыст, «В наличии», отрезок, штук, сколько своих уйдёт, из прайса)
            (6000.0, 5, 5000.0, 6, 5, 1),    # было: 3 хлыста 12 м из прайса, свои лежат
            (12000.0, 2, 5000.0, 8, 2, 2),   # та же длина: свои — первыми
            (11700.0, 5, 3800.0, 9, 3, 0),   # было: 3 хлыста 12 м, 11,7 м не тронуты
        ]
        for length, have, part, count, own_used, price_used in cases:
            with self.subTest(own=length, part=part):
                plan = self._parts_plan((self.p100, part, count))
                plan.action_compute()          # хлыст из прайса добавился сам
                Stock.create({
                    "plan_id": plan.id, "profile_id": self.p100.id, "length_mm": length,
                    "qty": have, "name": "Свой со склада"})
                plan.action_compute()
                used = self._used(plan.result_ids)
                self.assertEqual(used["Свой со склада"], own_used)
                self.assertEqual(used["Хлыст 12 м (из прайса)"], price_used)
                self.assertFalse(plan.has_unplaced)

    def test_compute_goes_on_without_length(self):
        """«В городе нет» — сигнал, а не запрет: типоразмеры без длины в
        прайсе не останавливают расчёт остальных."""
        self._need_bridge()
        plan = self._parts_plan((self.p80, 1000.0, 1), (self.p40, 1000.0, 2),
                                (self.p100, 1000.0, 1))
        self.assertEqual(plan.stock_missing_text,
                         ", ".join((self.p80 | self.p40).mapped("display_name")))
        plan.action_compute()                                   # без ошибки
        by_profile = {r.profile_id: r for r in plan.result_ids}
        self.assertEqual(set(by_profile), {self.p80, self.p40, self.p100})
        self.assertEqual(by_profile[self.p100].bars_used, 1, "У 100x100x3 длина есть — посчитан.")
        self.assertFalse(by_profile[self.p100].unplaced_text)
        for profile, text in ((self.p80, "нет заготовок: 1000 мм — 1 шт"),
                              (self.p40, "нет заготовок: 1000 мм — 2 шт")):
            with self.subTest(profile=profile.display_name):
                self.assertEqual(by_profile[profile].unplaced_text, text)
                self.assertEqual(by_profile[profile].bars_used, 0)
        self.assertTrue(plan.has_unplaced, "Плашка над вкладками — видно.")
        self.assertTrue(plan.stock_missing_text, "Серая строка во вкладке «Заготовки» — на месте.")
        self.assertIn("НЕ РАЗМЕЩЕНО: нет заготовок", plan._sheet_html(),
                      "Лист раскроя говорит то же.")

    def test_without_bridge_manual_input(self):
        """Мост — мягкая связь: в зависимостях его нет, без него длины нет —
        заготовку вводят руками, расчёт идёт."""
        self.assertNotIn("pmk_bridge", get_manifest("pmk_cut")["depends"],
                         "Удаление модуля под мостом не должно сносить раскрои.")
        plan = self._parts_plan((self.p100, 4000.0, 3))
        with patch.object(type(self.Plan), "_pmk_price_bars_ready", return_value=False):
            plan.invalidate_recordset(["stock_missing_text"])
            self.assertEqual(plan.stock_missing_text, self.p100.display_name)
            plan.action_compute()
            self.assertFalse(plan.stock_ids, "Без моста хлыст из прайса не добавляется.")
            self.assertEqual(plan.result_ids.unplaced_text, "нет заготовок: 4000 мм — 3 шт")
        # Заготовку ввели руками — считается как обычно.
        self.env["pmk.cut.stock"].create({
            "plan_id": plan.id, "profile_id": self.p100.id, "length_mm": 12000.0, "qty": 0})
        with patch.object(type(self.Plan), "_pmk_price_bars_ready", return_value=False):
            plan.action_compute()
        self.assertFalse(plan.has_unplaced)

    # ─── «В наличии»: 0 — сколько нужно ─────────────────────────────────
    def test_zero_in_stock_means_as_many_as_needed(self):
        """Так считает расчёт: 0 → не ограничено (докупим), число → не больше."""
        def result(qty):
            plan = self._parts_plan((self.p100, 1000.0, 20), stock_ids=[Command.create({
                "profile_id": self.p100.id, "length_mm": 6000.0, "qty": qty})])
            plan.action_compute()
            return plan.result_ids

        unlimited = result(0)
        self.assertFalse(unlimited.unplaced_text, "0 — сколько нужно: размещено всё.")
        self.assertEqual(unlimited.bars_used, 4)
        limited = result(2)
        self.assertEqual(limited.bars_used, 2, "Число — не больше стольких штук.")
        self.assertTrue(limited.unplaced_text)

    def test_in_stock_labels(self):
        field = self.env["pmk.cut.stock"]._fields["qty"]
        self.assertEqual(field.string, "В наличии, шт")
        self.assertIn("0 — сколько нужно", field.help)
        self.assertNotIn("Пусто или 0", field.help)
        arch = self._form()
        column = self._one(arch, "//field[@name='stock_ids']/list/field[@name='qty']")
        self.assertEqual(column.get("string").replace(NBSP, " "),
                         "В наличии, шт (0 — сколько нужно)")
        self.assertIn("(0" + NBSP + "—" + NBSP + "сколько" + NBSP + "нужно)", column.get("string"),
                      "Скобка не рвётся: вторая строка подписи целиком.")
        # Целое поле Odoo держит колонку 71 px — подпись вставала в 4 строки.
        self.assertEqual(column.get("width"), "150px")
        text = " ".join(" ".join(arch.xpath("//page[@name='stock']/p//text()")).split())
        self.assertIn("«В наличии» 0 — сколько нужно", text)
        self.assertIn("последним (100)", text, "Докупка — последней, и это сказано.")
        self.assertNotIn("не ограничено", text)
        missing = self._one(arch, "//page[@name='stock']/div[field[@name='stock_missing_text']]")
        self.assertIn("text-muted", missing.get("class").split(), "Серым словом, не красным.")
        self.assertEqual(missing.get("invisible"), "not stock_missing_text")
        name = self._one(arch, "//field[@name='stock_ids']/list/field[@name='name']")
        self.assertEqual(name.get("optional"), "show", "«(из прайса)» — на виду.")
        self.assertIn("100", self.env["pmk.cut.stock"]._fields["priority"].help)

    # ─── шапка и кнопки ─────────────────────────────────────────────────
    def test_spec_first_in_head_not_in_tab(self):
        arch = self._form()
        head = self._one(arch, "//div[contains(concat(' ', @class, ' '), ' pmk-doc-head__fields ')]")
        blocks = [b for b in head if b.tag == "div"]
        self.assertEqual([b.get("name") for b in blocks],
                         ["pmk_f_spec", "pmk_f_partner", "pmk_f_date",
                          "pmk_f_kerf", "pmk_f_min_useful", "pmk_f_note"])
        spec = blocks[0]
        self.assertIn("pmk-field--wide", spec.get("class").split(), "Номер СМ- не обрезается.")
        self.assertEqual(spec[0].tag, "label", "Подпись первой — стиль шага 27.")
        self.assertEqual(spec[1].get("name"), "spec_id")
        self.assertEqual(self.Plan._fields["spec_id"].string, "Расчёт")
        self.assertFalse(arch.xpath("//notebook//field[@name='spec_id']"), "Во вкладке поля нет.")
        self.assertFalse(arch.xpath("//notebook//button"), "Кнопка — в шапке.")

    def test_one_filled_button_in_every_state(self):
        header = self._one(self._form(), "//header")
        buttons = list(header.iter("button"))
        primary = [b for b in buttons if "btn-primary" in (b.get("class") or "").split()]
        self.assertEqual(sorted(b.get("name") for b in primary),
                         ["action_compute", "action_fill_from_spec"])
        refill = [b for b in buttons if b.get("name") == "action_fill_from_spec"
                  and b not in primary]
        self.assertEqual(len(refill), 1)
        confirm = refill[0].get("confirm") or ""
        self.assertIn("Отрезки заменятся", confirm, "Отрезки заменятся — спрашиваем.")
        self.assertIn("только типоразмерам, у которых заготовок нет", confirm,
                      "Вопрос честно называет, что добавится.")
        for spec_id in (False, 7):
            for part_ids in ([], [1, 2]):
                ctx = {"spec_id": spec_id, "part_ids": part_ids}
                with self.subTest(**ctx):
                    shown = [b.get("name") for b in primary
                             if not safe_eval(b.get("invisible") or "False", ctx)]
                    self.assertEqual(len(shown), 1, "Залита одна кнопка — следующий шаг.")
                    expected = ("action_fill_from_spec" if spec_id and not part_ids
                                else "action_compute")
                    self.assertEqual(shown[0], expected)

    def test_search_and_empty_screen(self):
        views = self.Plan.get_views([(self.env.ref("pmk_cut.view_cut_plan_search").id, "search")])
        search = etree.fromstring(views["views"]["search"]["arch"])
        self.assertEqual(self._one(search, "//field[@name='spec_id']").get("string"), "Расчёт")
        action = self.env.ref("pmk_cut.action_cut_plan")
        self.assertIn("Заполнить из расчёта", action.help)
        self.assertNotIn("спецификаци", action.help)

    # ─── отход ──────────────────────────────────────────────────────────
    def test_waste_label_and_bar_name(self):
        self.assertEqual(WASTE_WARN_PCT, 10.0, "Тот же порог, что у фильтра поиска.")
        cases = [
            (0.0, "0" + NBSP + "%", "zero"),
            (0.004, "0" + NBSP + "%", "zero"),
            (0.34, "0,34" + NBSP + "%", "ok"),
            (10.0, "10" + NBSP + "%", "ok"),
            (12.4, "12,4" + NBSP + "% · много", "high"),
            (41.67, "41,67" + NBSP + "% · много", "high"),
        ]
        for pct, text, level in cases:
            with self.subTest(pct=pct):
                self.assertEqual(waste_label(pct), (text, level))
        self.assertEqual(bar_name(12000), "Хлыст 12 м")
        self.assertEqual(bar_name(11700), "Хлыст 11,7 м")

    def test_high_waste_is_flagged(self):
        # Хлыст 12 м, отрезок 7000: остаток 5000 короче годного (6000) — в
        # лом, отход 41,67 %. Хлыст заведён руками: мост для этого не нужен.
        def plan_with(part, count, **values):
            return self._parts_plan((self.p100, part, count), stock_ids=[Command.create({
                "profile_id": self.p100.id, "length_mm": 12000.0, "qty": 0})], **values)

        plan = plan_with(7000.0, 1, min_useful_mm=6000.0)
        plan.action_compute()
        self.assertEqual(plan.result_ids.waste_level, "high")
        self.assertTrue(plan.result_ids.waste_label.endswith("· много"))
        self.assertTrue(plan.waste_high, "Карточка «Отход, %» в шапке — жёлтая.")
        self.assertEqual(plan.waste_label, "41,67" + NBSP + "% · много", "И в списке раскроев.")
        calm = plan_with(4000.0, 3)
        calm.action_compute()
        self.assertFalse(calm.waste_high)
        self.assertNotEqual(calm.result_ids.waste_level, "high")
        self.assertFalse(calm.waste_label.endswith("много"))

    def test_result_column_and_card(self):
        arch = self._form()
        label = self._one(arch, "//field[@name='result_ids']/list/field[@name='waste_label']")
        self.assertEqual(label.get("widget"), "badge")
        self.assertIn("pmk-cut-waste", label.get("class").split())
        self.assertEqual(label.get("decoration-warning"), "waste_level == 'high'")
        self.assertEqual(label.get("decoration-secondary"), "waste_level == 'zero'",
                         "Не muted: его ядро превращает в ту же плашку, что норма.")
        level = self._one(arch, "//field[@name='result_ids']/list/field[@name='waste_level']")
        self.assertIn(level.get("column_invisible"), ("1", "True"))
        number = self._one(arch, "//field[@name='result_ids']/list/field[@name='waste_ratio']")
        self.assertEqual(number.get("optional"), "hide", "Число — в меню колонок (⚙).")
        cards = arch.xpath("//div[contains(@class, 'pmk-kpi__card')][.//field[@name='waste_ratio']]")
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0].get("invisible"), "waste_high")
        self.assertIn("pmk-kpi__card--warn", cards[1].get("class").split())
        self.assertEqual(cards[1].get("invisible"), "not waste_high")
        self.assertIn("много", "".join(cards[1].itertext()), "Цвет повторён словом.")
        self.assertTrue(arch.xpath("//field[@name='waste_high']"))
        alert = self._one(arch, "//div[contains(@class, 'alert-warning')]")
        self.assertEqual(alert.get("invisible"), "not has_unplaced")
        self.assertIn("их нет совсем", " ".join("".join(alert.itertext()).split()),
                      "Плашка называет и типоразмер без заготовок.")

    def test_plan_list_waste_word(self):
        """Сигнал — и в списке раскроев, не только внутри документа."""
        arch = self._list()
        names = [f.get("name") for f in arch.xpath("/list/field")]
        label = self._one(arch, "/list/field[@name='waste_label']")
        self.assertEqual(label.get("widget"), "badge")
        self.assertIn("pmk-cut-waste", label.get("class").split())
        self.assertEqual(label.get("optional"), "show")
        self.assertIsNone(label.get("decoration-secondary"),
                          "Самостоятельный список: из decoration-* — только восемь штатных.")
        condition = label.get("decoration-warning")
        for pct in (0.0, 10.0, 10.01, 41.67):
            with self.subTest(pct=pct):
                self.assertEqual(safe_eval(condition, {"waste_ratio": pct}),
                                 waste_label(pct)[1] == "high",
                                 "Цвет и слово «много» — по одному порогу.")
        number = self._one(arch, "/list/field[@name='waste_ratio']")
        self.assertEqual(number.get("optional"), "hide", "Число — в ⚙, по нему сортируют.")
        self.assertEqual(names.index("waste_ratio"), names.index("waste_label") + 1)
        flt = etree.fromstring(self.Plan.get_views(
            [(self.env.ref("pmk_cut.view_cut_plan_search").id, "search")]
        )["views"]["search"]["arch"]).xpath("//filter[@name='wasteful']")[0]
        self.assertEqual(safe_eval(flt.get("domain")), [("waste_ratio", ">", WASTE_WARN_PCT)],
                         "Фильтр «Отход больше 10%» — тот же порог.")
        self.assertFalse(self.Plan.create({}).waste_label, "Не посчитан — пусто, а не «0 %».")

    def test_waste_styles_live_and_paired(self):
        path = "pmk_cut/static/src/scss/cut.scss"
        self.assertIn(path, get_manifest("pmk_cut")["assets"]["web.assets_backend"],
                      "Стили модуля подключены манифестом — на стенде живые.")
        with file_open(path) as f:
            scss = f.read()
        for cls in ("text-bg-300", "text-bg-secondary"):
            with self.subTest(badge=cls):
                self.assertIn(".o_list_renderer .o_field_badge.pmk-cut-waste > .badge.%s" % cls, scss)
        with file_open("pmk_theme/static/src/scss/dark.scss") as f:
            dark = f.read()
        self.assertIn("body.o_nexus_dark .o_list_renderer .o_field_badge.pmk-cut-waste"
                      " > .badge.text-bg-secondary", dark, "Тёмная пара серого нуля.")
