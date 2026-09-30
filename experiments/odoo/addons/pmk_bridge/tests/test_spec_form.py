# -*- coding: utf-8 -*-
"""Форма расчёта, разбор UX, шаг 32: печать КП, сигналы, вкладка «Цены».

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
    odoo -d pmk_bridge_test -i pmk_deal --test-enable \\
         --test-tags /pmk_bridge --stop-after-init --http-port 8099

Цены — свои: болт на двух прайсах одного поставщика (16.06 — 100 ₽,
21.09 — 110 ₽), масса 0,5 кг. Так вся арифметика вкладки проверяется в
уме: 220 000 ₽/т стало, 200 000 было, +100 ₽ на 10 болтах, +10 %.
"""
import datetime

from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, tagged

NB = " "
D = datetime.date


def plain(text):
    return (text or "").replace(NB, " ")


def filled(node):
    return "oe_highlight" in (node.get("class") or "") or "btn-primary" in (node.get("class") or "")


@tagged("post_install", "-at_install")
class TestSpecFormStep32(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.supplier = cls.env["res.partner"].create({
            "name": "АО «Металлсервис» (тест)", "is_company": True})
        cls.tmpl = cls.env["product.template"].create({"name": "Болт М12×40 (тест)"})
        cls.bolt = cls.env["pmk.metal.fastener"].create({
            "name": "Болт М12×40 (тест)", "weight_kg": 0.5,
            "product_tmpl_id": cls.tmpl.id})
        # Как на боевой базе: заливка нового прайса закрывает строки старого
        # (date_end 20.09 у прайса от 16.06), иначе на 27.09 действовали бы
        # оба, и выбор взял бы дешёвый старый.
        for start, end, price in ((D(2026, 6, 16), D(2026, 9, 20), 100.0),
                                  (D(2026, 9, 21), False, 110.0)):
            cls.env["product.supplierinfo"].create({
                "partner_id": cls.supplier.id, "product_tmpl_id": cls.tmpl.id,
                "price": price, "date_start": start, "date_end": end,
            })
        cls.Spec = cls.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)

    def _spec(self, price_date=D(2026, 9, 27), products=None):
        if products is None:
            products = [
                {"name": "Каркас", "qty": 1, "price_customer_unit": 5000.0,
                 "line_ids": [Command.create({
                     "calc_mode": "fastener", "fastener_id": self.bolt.id, "qty": 10})]},
                {"name": "тест", "qty": 19},
            ]
        return self.Spec.create({
            "price_date": price_date,
            "product_ids": [Command.create(vals) for vals in products],
        })

    # ─── «КП (PDF)» и сигнал «не попадут» ──────────────────────────────
    def test_print_button_opens_the_report(self):
        spec = self._spec()
        action = spec.action_print_quotation()
        self.assertEqual(action["type"], "ir.actions.report",
                         "PDF сразу, без мастера макета документов.")
        self.assertEqual(action["report_name"], "pmk_bridge.report_metal_spec_quotation")
        self.assertEqual(action["context"].get("active_ids"), [spec.id])

    def test_kp_skip_signal(self):
        spec = self._spec()
        self.assertEqual(spec.kp_skip_count, 1)
        self.assertEqual(plain(spec.kp_skip_text),
                         "В КП не попадут без цены: 1 изделие — «тест»")
        # Условие то же, что у печатной формы.
        printed = spec.product_ids.filtered(lambda p: p.price_customer_unit)
        self.assertEqual(printed.mapped("name"), ["Каркас"])
        spec.product_ids.filtered(lambda p: p.name == "тест").price_customer_unit = 100.0
        self.assertEqual(spec.kp_skip_count, 0)
        self.assertFalse(spec.kp_skip_text, "Всё с ценой — сигнала нет.")

    # ─── Вкладка «Цены» ─────────────────────────────────────────────────
    def test_prices_per_ton_and_summary(self):
        spec = self._spec()
        line = spec.price_line_ids
        self.assertEqual(line.price_state, "ok")
        self.assertAlmostEqual(line.price_unit, 110.0)
        self.assertAlmostEqual(line.price_ton, 220000.0, places=2)
        self.assertEqual(spec.compare_effective_date, D(2026, 6, 16))
        self.assertAlmostEqual(line.price_compare_unit, 100.0)
        self.assertAlmostEqual(line.price_compare_ton, 200000.0, places=2)
        self.assertAlmostEqual(line.price_now_ton, 220000.0, places=2,
                               msg="«Стало» — цена расчёта, когда прайс сравнения старше.")
        self.assertAlmostEqual(spec.compare_delta, 100.0, places=2)
        self.assertEqual(plain(spec.compare_summary), "С 16.06: +100 ₽ (+10 %)")

    def test_compare_with_later_price_reads_forward(self):
        """Доводка шага 32: расчёт на старых ценах сравнивают со свежим прайсом.

        Цены на 17.09 — прайс 16.06 (100 ₽), сравниваем с 21.09 (110 ₽).
        Было «С 21.09: −100 ₽ (−9,1 %)» — «с 21.09 подешевело», хотя свежий
        прайс дороже. Теперь по времени: было 100, стало 110, +10 %.
        """
        spec = self._spec(price_date=D(2026, 9, 17))
        spec.compare_price_date = D(2026, 9, 21)
        line = spec.price_line_ids
        self.assertAlmostEqual(line.price_unit, 100.0)
        self.assertAlmostEqual(line.price_compare_unit, 100.0)
        self.assertAlmostEqual(line.price_compare_ton, 200000.0, places=2)
        self.assertAlmostEqual(line.price_now_ton, 220000.0, places=2)
        self.assertAlmostEqual(line.price_compare_pct, 10.0, places=4)
        self.assertAlmostEqual(line.cost_compare_delta, 100.0, places=2)
        self.assertAlmostEqual(spec.compare_pct, 10.0, places=4)
        self.assertEqual(plain(spec.compare_summary),
                         "По прайсу от 21.09 стало бы: +100 ₽ (+10 %)")
        self.assertEqual(spec.compare_hint, "новее цен расчёта: «Стало» — по нему")
        # Цены расчёта сравнение не трогает.
        self.assertAlmostEqual(spec.total_cost_fact, 1000.0, places=2)

    def test_supplier_change_asks_to_reread(self):
        """Доводка шага 32: смена «Поставщика для цен» цены не меняет — их
        меняет только «Перечитать цены». До этого — сигнал словами."""
        other = self.env["res.partner"].create({
            "name": "ООО «Другой металл» (тест)", "is_company": True})
        self.env["product.supplierinfo"].create({
            "partner_id": other.id, "product_tmpl_id": self.tmpl.id,
            "price": 120.0, "date_start": D(2026, 6, 16)})
        spec = self._spec()
        line = spec.price_line_ids
        self.assertAlmostEqual(line.price_unit, 110.0, msg="Без выбора — дешевле.")
        self.assertFalse(spec.price_reread_needed)

        spec.supplier_id = other
        self.assertAlmostEqual(line.price_unit, 110.0,
                               msg="Сама цена не меняется: расчёт — на дату.")
        self.assertEqual(line.price_partner_id, other)
        self.assertTrue(spec.price_reread_needed)

        spec.action_refresh_prices()
        self.assertAlmostEqual(line.price_unit, 120.0)
        self.assertFalse(spec.price_reread_needed)

    def test_zero_mass_does_not_divide(self):
        """Мина листа: масса позиции обнулилась — «Было, ₽/т» ноль, не ошибка."""
        self.bolt.weight_kg = 0.0
        spec = self._spec()
        line = spec.price_line_ids
        self.assertEqual(line.price_state, "no_mass")
        self.assertAlmostEqual(line.price_compare_unit, 100.0)
        self.assertEqual(line.price_compare_ton, 0.0)

    def test_stale_price_in_words(self):
        spec = self._spec(price_date=D(2026, 9, 17))
        self.assertTrue(spec.price_stale)
        self.assertEqual(spec.price_stale_label, "есть прайс от 21.09")
        fresh = self._spec()
        self.assertFalse(fresh.price_stale)
        self.assertFalse(fresh.price_stale_label)

    # ─── Собранная разметка ─────────────────────────────────────────────
    def _form(self):
        views = self.env["pmk.metal.spec"].get_views([(False, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def test_our_view_is_active(self):
        """Вид с упавшим xpath Odoo выключает при загрузке — ловим это."""
        self.assertTrue(self.env.ref("pmk_bridge.view_metal_spec_form_cost").active)

    def test_one_filled_button_and_it_prints(self):
        arch = self._form()
        header = arch.find("header")
        buttons = [n for n in header if n.tag == "button"]
        self.assertEqual(buttons[0].get("name"), "action_print_quotation",
                         "Первой: на узком экране ядро оставляет одну первую кнопку.")
        self.assertEqual(buttons[0].get("string"), "КП (PDF)")
        self.assertEqual([b.get("name") for b in header.iter("button") if filled(b)],
                         ["action_print_quotation"], "Залитая на экране одна.")
        signal = header.find("span[@class='pmk-signal']")
        self.assertIsNotNone(signal)
        self.assertIsNotNone(signal.find("field[@name='kp_skip_text']"))
        self.assertEqual(signal.get("invisible"), "not kp_skip_text")
        self.assertIsNone(header.find("button[@name='action_send_quotation']"),
                          "«Отправить КП» — шаг 33.")

    def test_head_order_and_moved_fields(self):
        arch = self._form()
        head = arch.xpath("//div[contains(concat(' ', @class, ' '), ' pmk-doc-head__fields ')]")[0]
        fields_order = [f.get("name") for f in head.iter("field")
                        if f.get("name") in ("opportunity_id", "partner_id", "contact_id",
                                             "date", "price_date", "note", "company_id")]
        expected = ["partner_id", "contact_id", "date", "price_date", "note"]
        if "opportunity_id" in fields_order:
            expected.insert(0, "opportunity_id")
        if self.env.user.has_group("base.group_multi_company"):
            expected.append("company_id")
        self.assertEqual(fields_order, expected)
        self.assertIsNone(head.find(".//field[@name='supplier_id']"),
                          "«Поставщик для цен» — на вкладке «Цены».")
        self.assertFalse(head.xpath(".//span[contains(@class, 'text-bg-danger')]"),
                         "Красного «!» больше нет — словами.")
        self.assertIsNotNone(head.find(".//field[@name='price_stale_label']"))

    def test_prices_page(self):
        arch = self._form()
        page = arch.xpath("//page[@name='prices']")[0]
        self.assertIsNotNone(page.find(".//field[@name='supplier_id']"))
        columns = {f.get("name"): f.get("string")
                   for f in page.xpath("field[@name='price_line_ids']/list/field")}
        self.assertEqual(columns.get("price_compare_ton"), "Было, ₽/т")
        self.assertEqual(columns.get("price_now_ton"), "Стало, ₽/т")
        self.assertNotIn("price_ton", columns, "«Стало» — по времени, не всегда цена расчёта.")
        self.assertNotIn("price_compare_unit", columns)
        reread = page.xpath(".//div[@invisible='not price_reread_needed']")
        self.assertEqual(len(reread), 1, "Сигнал «цены не перечитаны» — на вкладке.")
        self.assertIsNotNone(reread[0].find("span[@class='pmk-signal']"))
        link = reread[0].find("button[@name='action_refresh_prices']")
        self.assertIsNotNone(link)
        self.assertNotIn("oe_highlight", link.get("class") or "",
                         "Залитая на экране одна — «КП (PDF)».")
        self.assertIsNotNone(page.find(".//field[@name='compare_summary']"))
        for name in ("compare_total_cost", "compare_delta", "compare_pct"):
            with self.subTest(gone=name):
                self.assertIsNone(page.find(".//field[@name='%s']" % name),
                                  "Итог — одной строкой.")

    def test_metal_next_to_price(self):
        arch = self._form()
        # Служебные колонки (column_invisible) на экране не видны и порядку
        # не мешают: сравниваем только видимые.
        columns = arch.xpath("//field[@name='product_ids']/list/field")
        names = [f.get("name") for f in columns]
        visible = [f.get("name") for f in columns
                   if f.get("column_invisible") not in ("1", "True")]
        self.assertEqual(visible.index("metal_one_label") + 1, visible.index("price_customer_unit"))
        self.assertNotIn("cost_fact_one", names, "Голое число без оговорки не показываем.")
        cost = columns[names.index("metal_one_label")]
        self.assertEqual(cost.get("string"), "Металл, ₽")
        self.assertEqual(cost.get("widget"), "badge")
        self.assertEqual(cost.get("decoration-warning"), "no_price_count > 0")
        count = columns[names.index("no_price_count")]
        self.assertEqual(count.get("column_invisible"), "1",
                         "Простое поле: column_invisible загрузку не режет.")

        form = arch.xpath("//field[@name='product_ids']/form")[0]
        form_names = [f.get("name") for f in form.iter("field")]
        self.assertLess(form_names.index("cost_fact_one"), form_names.index("price_customer_unit"))
        self.assertLess(form_names.index("metal_one_label"), form_names.index("price_customer_unit"))
        plain_cost = form.find(".//field[@name='cost_fact_one']")
        self.assertEqual(plain_cost.get("invisible"), "no_price_count")
        label = form.find(".//field[@name='metal_one_label']")
        self.assertEqual(label.get("invisible"), "not no_price_count")
        self.assertEqual(label.get("string"), plain_cost.get("string"), "Одна подпись.")

    def test_metal_label_marks_missing(self):
        """Доводка шага 32: у изделия с позициями без цены «Металл, ₽»
        занижен — пишем «≥ … · без N поз.», а ноль — «нет в прайсах»."""
        nut_tmpl = self.env["product.template"].create({"name": "Гайка М12 (тест)"})
        nut = self.env["pmk.metal.fastener"].create({
            "name": "Гайка М12 (тест)", "weight_kg": 0.1,
            "product_tmpl_id": nut_tmpl.id})
        bolt = Command.create({"calc_mode": "fastener", "fastener_id": self.bolt.id, "qty": 10})
        nuts = Command.create({"calc_mode": "fastener", "fastener_id": nut.id, "qty": 4})
        spec = self._spec(products=[
            {"name": "Каркас", "qty": 1, "line_ids": [bolt]},
            {"name": "Узел", "qty": 2, "line_ids": [
                Command.create({"calc_mode": "fastener", "fastener_id": self.bolt.id, "qty": 10}),
                nuts]},
            {"name": "Гайки", "qty": 1, "line_ids": [
                Command.create({"calc_mode": "fastener", "fastener_id": nut.id, "qty": 4})]},
            {"name": "тест", "qty": 1},
        ])
        labels = {p.name: plain(p.metal_one_label) for p in spec.product_ids}
        self.assertEqual(labels["Каркас"], "1 100,00")
        self.assertEqual(labels["Узел"], "≥ 1 100,00 · без 1 поз.",
                         "На ОДНО изделие, как и «Цена за шт».")
        self.assertEqual(labels["Гайки"], "нет в прайсах: 1 поз.")
        self.assertEqual(labels["тест"], "—")
        self.assertEqual(spec.no_price_count, 2, "Карточка KPI считает те же позиции.")
