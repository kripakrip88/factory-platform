# -*- coding: utf-8 -*-
"""Цена в справочниках и в списке «Цены поставщиков» — разбор UX, шаг 25.

Гонять ТОЛЬКО на одноразовой базе (см. test_spec_form.py). Цены — свои, числа
проверяются в уме:
  • уголок (тест): масса метра 10 кг — 1 000 ₽/м → 100 000 ₽/т;
  • лист (тест): карточка весит 500 кг — 40 000 ₽/лист → 80 000 ₽/т;
  • болт (тест): 0,5 кг — 110 ₽ → 220 000 ₽/т.

Главное, что ловим: справочник показывает ту же строку прайса и ту же
массу единицы, что взял бы расчёт (одна дверь к цене), а «нет в прайсах» —
сигнал, не ошибка.
"""
import datetime

from lxml import etree

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

D = datetime.date


@tagged("post_install", "-at_install")
class TestStep25Prices(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        today = fields.Date.context_today(cls.env["res.partner"])
        cls.today = today
        cls.old = today - datetime.timedelta(days=100)
        cls.metal = cls.env["res.partner"].create({
            "name": "Металлсервис (тест 25)", "is_company": True, "pmk_supplier_rank": 10})
        cls.far = cls.env["res.partner"].create({
            "name": "Дальний поставщик (тест 25)", "is_company": True, "pmk_supplier_rank": 50})
        Info = cls.env["product.supplierinfo"]

        # Прокат: цена за метр, масса метра из справочника.
        ptype = cls.env["pmk.metal.profile.type"].create({"name": "Уголок (тест 25)"})
        cls.angle_tmpl = cls.env["product.template"].create({"name": "Уголок 100×8 (тест 25)"})
        cls.angle = cls.env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Уголок (тест 25)", "gost": "ГОСТ тест",
            "size_label": "100×8", "mass_per_meter": 10.0,
            "product_tmpl_id": cls.angle_tmpl.id})
        cls.angle_line = Info.create({
            "partner_id": cls.metal.id, "product_tmpl_id": cls.angle_tmpl.id,
            "price": 1000.0, "date_start": cls.old, "pmk_bar_length_mm": 12000.0})
        # Дешевле, но у поставщика с худшим рейтингом — не берётся.
        Info.create({"partner_id": cls.far.id, "product_tmpl_id": cls.angle_tmpl.id,
                     "price": 900.0, "date_start": cls.old})
        # Оптовый порог дешевле базового — на этапе КП не берётся.
        Info.create({"partner_id": cls.metal.id, "product_tmpl_id": cls.angle_tmpl.id,
                     "price": 950.0, "min_qty": 3.0, "date_start": cls.old})
        # Закрытый прайс — на сегодня не действует.
        Info.create({"partner_id": cls.metal.id, "product_tmpl_id": cls.angle_tmpl.id,
                     "price": 500.0, "date_start": cls.old,
                     "date_end": cls.today - datetime.timedelta(days=1)})

        # Лист: цена за лист, масса листа — с карточки.
        cls.sheet_tmpl = cls.env["product.template"].create({
            "name": "Лист 5 мм (тест 25)", "weight": 500.0})
        cls.sheet = cls.env["pmk.metal.sheet"].create({
            "sheet_type": "Гладкий (тест 25)", "thickness_mm": 5.0, "gost": "ГОСТ тест",
            "mass_per_sqm": 39.25, "product_tmpl_id": cls.sheet_tmpl.id})
        cls.sheet_line = Info.create({
            "partner_id": cls.metal.id, "product_tmpl_id": cls.sheet_tmpl.id,
            "price": 40000.0, "date_start": cls.old})

        # Позиция без прайса — «нет в прайсах».
        cls.bare_tmpl = cls.env["product.template"].create({"name": "Уголок 200×20 (тест 25)"})
        cls.bare = cls.env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Уголок (тест 25)", "gost": "ГОСТ тест",
            "size_label": "200×20", "mass_per_meter": 60.0,
            "product_tmpl_id": cls.bare_tmpl.id})

    # ─── Одна дверь к цене ──────────────────────────────────────────────
    def test_find_seller_rules(self):
        seller = self.angle_tmpl._pmk_find_seller(self.today)
        self.assertEqual(seller, self.angle_line,
                         "Лучший рейтинг, базовый уровень, действует сегодня.")
        self.assertEqual(self.angle_tmpl._pmk_find_seller(self.today, supplier=self.far).price, 900.0,
                         "Заданный поставщик — только его строки.")
        self.assertFalse(self.bare_tmpl._pmk_find_seller(self.today))
        # Равный рейтинг — дешевле.
        self.far.pmk_supplier_rank = 10
        self.assertEqual(self.angle_tmpl._pmk_find_seller(self.today).price, 900.0)

    def test_spec_line_uses_the_same_door(self):
        """Строка расчёта берёт ту же строку прайса и ту же массу, что справочник."""
        spec = self.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True).create({
                "price_date": self.today,
                "product_ids": [Command.create({
                    "name": "Рама", "qty": 1,
                    "line_ids": [Command.create({
                        "calc_mode": "linear", "profile_id": self.angle.id,
                        "length_mm": 1000.0, "qty": 1})]})],
            })
        line = spec.product_ids.line_ids
        self.assertEqual(line.price_source_id, self.angle_line,
                         "state=%s supplier=%s currency=%s/%s" % (
                             line.price_state, spec.supplier_id.display_name,
                             spec.currency_id.name, self.angle_line.currency_id.name))
        self.assertAlmostEqual(line.price_ton, self.angle.pmk_price_ton, places=2)
        self.assertEqual(line.price_date_used, self.angle.pmk_price_date)

    # ─── Справочник ─────────────────────────────────────────────────────
    def test_reference_price_columns(self):
        self.assertAlmostEqual(self.angle.pmk_price_ton, 100000.0, places=2)
        self.assertEqual(self.angle.pmk_price_supplier_label, self.metal.display_name)
        self.assertEqual(self.angle.pmk_price_date, self.old)
        self.assertFalse(self.angle.pmk_price_missing)
        self.assertAlmostEqual(self.sheet.pmk_price_ton, 80000.0, places=2,
                               msg="Лист продаётся целым листом — масса листа, не м².")

    def test_reference_without_price_is_a_signal(self):
        self.assertEqual(self.bare.pmk_price_ton, 0.0)
        self.assertEqual(self.bare.pmk_price_supplier_label, "нет в прайсах")
        self.assertFalse(self.bare.pmk_price_date)
        self.assertTrue(self.bare.pmk_price_missing)
        Profile = self.env["pmk.metal.profile"]
        missing = Profile.search([("pmk_price_missing", "=", True)])
        self.assertIn(self.bare, missing)
        self.assertNotIn(self.angle, missing)
        priced = Profile.search([("pmk_price_missing", "=", False)])
        self.assertIn(self.angle, priced)
        self.assertNotIn(self.bare, priced)

    def test_missing_filter_all_operators(self):
        """Odoo 19 приводит «=», «!=» и списки к in/not in с OrderedSet —
        не set: раньше это падало «unhashable type: 'OrderedSet'»."""
        for model, bare, priced in (("pmk.metal.profile", self.bare, self.angle),
                                    ("pmk.metal.sheet", None, self.sheet)):
            Ref = self.env[model]
            for domain, missing in (
                ([("pmk_price_missing", "=", True)], True),
                ([("pmk_price_missing", "!=", False)], True),
                ([("pmk_price_missing", "in", [True])], True),
                ([("pmk_price_missing", "=", False)], False),
                ([("pmk_price_missing", "!=", True)], False),
                ([("pmk_price_missing", "not in", [True])], False),
            ):
                with self.subTest(model=model, domain=domain):
                    found = Ref.search(domain)
                    self.assertEqual(priced in found, not missing)
                    if bare:
                        self.assertEqual(bare in found, missing)
            # Фильтр «Нет в прайсах» — домен из самого вида поиска.
            with self.subTest(model=model, filter="pmk_no_price"):
                views = Ref.get_views([(False, "search")])
                search = etree.fromstring(views["views"]["search"]["arch"])
                domain = safe_eval(search.xpath("//filter[@name='pmk_no_price']")[0].get("domain"))
                found = Ref.search(domain)
                self.assertNotIn(priced, found)
                if bare:
                    self.assertIn(bare, found)

    def test_reference_views(self):
        for model, xmlid in (("pmk.metal.profile", "pmk_calc.view_metal_profile_list"),
                             ("pmk.metal.sheet", "pmk_calc.view_metal_sheet_list")):
            with self.subTest(view=xmlid):
                views = self.env[model].get_views([(self.env.ref(xmlid).id, "list"),
                                                   (False, "search")])
                arch = etree.fromstring(views["views"]["list"]["arch"])
                names = [f.get("name") for f in arch.xpath("/list/field")]
                for name in ("pmk_price_ton", "pmk_price_supplier_label", "pmk_price_date"):
                    self.assertIn(name, names)
                    node = arch.xpath("/list/field[@name='%s']" % name)[0]
                    self.assertEqual(node.get("optional"), "show")
                supplier = arch.xpath("/list/field[@name='pmk_price_supplier_label']")[0]
                self.assertEqual(supplier.get("decoration-muted"), "pmk_price_missing",
                                 "«нет в прайсах» — серым, не красным.")
                self.assertIsNone(supplier.get("decoration-danger"))
                search = etree.fromstring(views["views"]["search"]["arch"])
                self.assertTrue(search.xpath("//filter[@name='pmk_no_price']"))
        for xmlid in ("pmk_bridge.view_metal_profile_list_price",
                      "pmk_bridge.view_metal_sheet_list_price",
                      "pmk_bridge.view_metal_profile_search_price",
                      "pmk_bridge.view_metal_sheet_search_price"):
            with self.subTest(active=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    def test_reference_price_not_summed(self):
        for model in ("pmk.metal.profile", "pmk.metal.sheet"):
            info = self.env[model].fields_get(["pmk_price_ton"], ["aggregator"])
            self.assertFalse(info["pmk_price_ton"].get("aggregator"))

    # ─── Строка прайса: цена за тонну, марка и габарит ──────────────────
    def test_supplierinfo_price_per_ton(self):
        self.assertAlmostEqual(self.angle_line.pmk_price_ton, 100000.0, places=2)
        self.assertAlmostEqual(self.sheet_line.pmk_price_ton, 80000.0, places=2)
        self.assertFalse(self.angle_line.pmk_variant_label, "У проката цена на всю позицию.")
        orphan = self.env["product.supplierinfo"].create({
            "partner_id": self.metal.id,
            "product_tmpl_id": self.env["product.template"].create({"name": "Без справочника"}).id,
            "price": 10.0})
        self.assertEqual(orphan.pmk_price_ton, 0.0, "Нет строки справочника — массы нет.")

    def test_supplierinfo_variant_label(self):
        """Марка и габарит листа — даже когда у характеристики одно значение
        (штатное имя варианта такие выбрасывает)."""
        Attr = self.env["product.attribute"]
        grade = Attr.create({"name": "Марка (тест 25)", "create_variant": "always", "sequence": 1})
        size = Attr.create({"name": "Габарит (тест 25)", "create_variant": "always", "sequence": 2})
        st3 = self.env["product.attribute.value"].create({"name": "Ст3сп", "attribute_id": grade.id})
        big = self.env["product.attribute.value"].create({"name": "1500x6000", "attribute_id": size.id})
        tmpl = self.env["product.template"].create({
            "name": "Лист 8 мм (тест 25)",
            "attribute_line_ids": [
                Command.create({"attribute_id": size.id, "value_ids": [Command.set(big.ids)]}),
                Command.create({"attribute_id": grade.id, "value_ids": [Command.set(st3.ids)]}),
            ]})
        variant = tmpl.product_variant_ids
        self.assertEqual(len(variant), 1)
        info = self.env["product.supplierinfo"].create({
            "partner_id": self.metal.id, "product_tmpl_id": tmpl.id,
            "product_id": variant.id, "price": 50000.0})
        self.assertEqual(info.pmk_variant_label, "Ст3сп, 1500x6000",
                         "По порядку характеристик: марка, потом габарит.")

    def test_supplierinfo_group_sums_off(self):
        info = self.env["product.supplierinfo"].fields_get(
            ["price", "min_qty", "pmk_bar_length_mm", "pmk_price_ton"], ["aggregator"])
        for name, desc in info.items():
            with self.subTest(field=name):
                self.assertFalse(desc.get("aggregator"))


@tagged("post_install", "-at_install")
class TestStep25SpecLists(TransactionCase):
    """Список расчётов, изделия и вкладка «Цены» — собранная разметка."""

    def _arch(self, view_type, xmlid=None):
        view_id = self.env.ref(xmlid).id if xmlid else False
        views = self.env["pmk.metal.spec"].get_views([(view_id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def test_spec_list(self):
        arch = self._arch("list", "pmk_calc.view_metal_spec_list")
        fields_ = {f.get("name"): f for f in arch.xpath("/list/field")}
        names = [f.get("name") for f in arch.xpath("/list/field")]
        subject = fields_["note"]
        self.assertEqual(subject.get("string"), "Предмет КП")
        self.assertEqual(subject.get("optional"), "show")
        self.assertEqual(fields_["contact_id"].get("optional"), "hide")
        self.assertEqual(fields_["total_products"].get("optional"), "hide")
        # Номер · Дата · Клиент · Сделка · Предмет КП.
        order = [n for n in names if n in ("name", "date", "partner_id", "opportunity_id", "note")]
        expected = ["name", "date", "partner_id", "note"]
        if "opportunity_id" in names:
            expected.insert(3, "opportunity_id")
        self.assertEqual(order, expected)
        count = fields_["no_price_count"]
        self.assertEqual(count.get("string"), "Без цены")
        self.assertEqual(count.get("optional"), "show")
        self.assertEqual(count.get("decoration-danger"), "no_price_count > 0")
        self.assertEqual(len(arch.xpath("/list/field[@name='no_price_count']")), 1,
                         "Одна колонка: служебная копия для полоски не нужна.")
        self.assertEqual(fields_["price_incomplete"].get("column_invisible"), "1",
                         "Колонка «Р…» убрана из меню колонок; поле читает полоска.")
        self.assertEqual(names[names.index("total_weight_t") + 1], "total_cost_fact")

    def test_product_list(self):
        arch = self._arch("form")
        columns = {f.get("name"): f for f in arch.xpath("//field[@name='product_ids']/list/field")}
        self.assertEqual(columns["weight_fact_total"].get("optional"), "hide")
        self.assertEqual(columns["weight_fact_total"].get("string"), "Купить, кг")
        self.assertEqual(columns["cost_fact_total"].get("optional"), "hide")
        self.assertEqual(columns["cost_fact_total"].get("string"), "Закупка")
        count = columns["no_price_count"]
        self.assertEqual(count.get("optional"), "show")
        self.assertEqual(count.get("decoration-muted"), "no_price_count == 0",
                         "Ноль серым явно: бледные нули темы во вложенных таблицах не работают.")

    def test_prices_page_date(self):
        arch = self._arch("form")
        date = arch.xpath("//page[@name='prices']//field[@name='price_line_ids']/list"
                          "/field[@name='price_date_used']")
        self.assertEqual(len(date), 1)
        self.assertEqual(date[0].get("string"), "Прайс от")
        self.assertEqual(date[0].get("optional"), "show")
