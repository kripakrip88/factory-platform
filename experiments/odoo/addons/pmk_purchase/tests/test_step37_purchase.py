# -*- coding: utf-8 -*-
"""Закупки, прайсы, номенклатура — разбор UX, шаг 37 (02.10.2026).

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo (см. __init__.py).
Разметка — собранная, как её получает браузер (get_views: все наследники
применены, узлы чужих групп вырезаны сервером). Глазами это не заменяет:
ширины колонок, строку кнопок над отмеченными, вес в карточке, серый ноль
на «Цены 0» смотрит основной агент на копии.

Цены — свои, числа проверяются в уме:
  • уголок (тест): масса метра 10 кг, 1 000 ₽/м → 100 000 ₽/т; дешевле
    у поставщика с худшим рейтингом (900) и оптом (950) — не берутся,
    закрытый прайс (500) — не действует; поставщиков с ценой — два;
  • уголок без прайса — «нет в прайсах»;
  • болт (тест): строка прайса без даты — «Без даты», действует всегда;
  • болт М12×40 из справочника метизов: 0,0542 кг/шт, в карточке 0,05.

Что ловим:
  • виды шага живы (упавший xpath Odoo выключает при загрузке молча);
  • «Цены поставщиков»: «Старше 30 дней» и «Без даты» (сделано шагом 25) —
    по доменам из самого вида поиска;
  • «Номенклатура» и список вариантов: колонки по порядку, цена — одной
    дверью с расчётом (_pmk_find_seller), «нет в прайсах» — тем же словом,
    что в справочнике, серым; итога веса в строке группы нет;
  • масса — одной дверью с расчётом (проверка шага): у проката, метизов,
    красок — из справочника, только чтение; у листа и остального — вес
    карточки;
  • карточка: «Артикул», вес в «Основной информации» с подписью по виду
    позиции, «Цены N» первой и всегда, «Закуплено» — только при числе;
    вкладка «Склад» — только тем, кому на ней есть что видеть, в том числе
    у позиции без учёта партиями;
  • «Цены N» — поставщики с ценой; открытый ею список (базовые цены)
    показывает столько же строк;
  • «Адрес проверен» / «Адрес не работает» меняют только состояние адреса
    у отмеченных, пачка не меняется наполовину, отказ — по месту (реестр
    прайсов или нет); сменили адрес — состояние «Не проверен»;
  • одно слово: «Проверен» на кнопке, плашке и в фильтрах; «Адрес», «Раз в,
    дн», «Прайс от» — в списке и в карточке; плашки без адреса нет нигде;
  • строка кнопок над отмеченными — короткие подписи; «Рейтинг»; ширины
    шагов 25/26.
"""
import datetime

from dateutil.relativedelta import relativedelta
from lxml import etree

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.pmk_purchase.models.product_template import NO_PRICE

REMOVED = "pmk_theme.group_pmk_removed"
STOCK = "pmk_theme.group_pmk_stock"
LOTS = "stock.group_production_lot"
HIDDEN = ("1", "True", "true")

VIEWS = (
    "pmk_purchase.view_product_template_list_step37",
    "pmk_purchase.view_product_product_list_step37",
    "pmk_purchase.view_product_template_search_step37",
    "pmk_purchase.view_product_template_form_step37",
    "pmk_purchase.view_product_product_form_step37",
    "pmk_purchase.view_price_supplier_list_step37",
    "pmk_purchase.view_price_supplier_search_step37",
    "pmk_purchase.view_partner_form_price_step37",
    "pmk_purchase.view_price_mailing_form_step37",
)
LISTS = (
    ("product.template", "product.product_template_tree_view"),
    ("product.product", "product.product_product_tree_view"),
)
FORMS = (
    ("product.template", "product.product_template_only_form_view"),
    ("product.product", "product.product_normal_form_view"),
)
COLUMNS = ["default_code", "name", "uom_id", "pmk_mass_unit", "pmk_price_unit",
           "pmk_price_ton", "pmk_price_date", "pmk_price_supplier_label"]
# Строка кнопок над отмеченными поставщиками — короткие подписи, чтобы при
# 1440 px строка не ломалась на две (проверка шага 37).
HEADER = [("action_pmk_confirm_price_email", "Адрес проверен"),
          ("action_pmk_invalidate_price_email", "Адрес не работает"),
          ("action_pmk_mailing_on", "В рассылку"),
          ("action_pmk_mailing_off", "Из рассылки"),
          ("action_pmk_period_weekly", "Раз в неделю"),
          ("action_pmk_period_biweekly", "Раз в 2 недели")]
# Одно слово в списке и в карточке поставщика.
PARTNER_LABELS = {"pmk_price_email": "Адрес", "pmk_price_period_days": "Раз в, дн",
                  "pmk_price_last_date": "Прайс от"}


def shown(arch, expr):
    """Узлы, которые человек увидит: поля, досозданные ядром невидимыми
    (_add_missing_fields), не считаем."""
    return [node for node in arch.xpath(expr)
            if (node.get("invisible") or "").strip() not in HIDDEN
            and (node.get("column_invisible") or "").strip() not in HIDDEN]


@tagged("post_install", "-at_install")
class TestStep37Purchase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.write({"group_ids": [Command.link(cls.env.ref(x).id) for x in (
            "purchase.group_purchase_manager", "stock.group_stock_manager")]})
        today = fields.Date.context_today(cls.env["res.partner"])
        cls.today = today
        cls.old = today - datetime.timedelta(days=45)
        Partner = cls.env["res.partner"]
        cls.metal = Partner.create({"name": "Металлсервис (тест 37)", "is_company": True,
                                    "pmk_supplier_rank": 10})
        cls.far = Partner.create({"name": "Дальний (тест 37)", "is_company": True,
                                  "pmk_supplier_rank": 50})
        Info = cls.env["product.supplierinfo"]

        # Прокат: цена за метр, масса метра из справочника.
        ptype = cls.env["pmk.metal.profile.type"].create({"name": "Уголок (тест 37)"})
        cls.angle_tmpl = cls.env["product.template"].create({
            "name": "Уголок 100×8 (тест 37)", "default_code": "UGR-T37", "weight": 10.0})
        cls.angle = cls.env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Уголок (тест 37)", "gost": "ГОСТ тест",
            "size_label": "100×8", "mass_per_meter": 10.0, "product_tmpl_id": cls.angle_tmpl.id})
        cls.base_line = Info.create({"partner_id": cls.metal.id, "product_tmpl_id": cls.angle_tmpl.id,
                                     "price": 1000.0, "date_start": cls.old})
        # Оптовый порог дешевле базового — на этапе КП не берётся.
        Info.create({"partner_id": cls.metal.id, "product_tmpl_id": cls.angle_tmpl.id,
                     "price": 950.0, "min_qty": 3.0, "date_start": cls.old})
        # Дешевле, но у поставщика с худшим рейтингом — не берётся.
        Info.create({"partner_id": cls.far.id, "product_tmpl_id": cls.angle_tmpl.id,
                     "price": 900.0, "date_start": cls.old})
        # Закрытый прайс — на сегодня не действует и в «Цены N» не входит.
        cls.closed = Info.create({"partner_id": cls.metal.id, "product_tmpl_id": cls.angle_tmpl.id,
                                  "price": 500.0, "date_start": today - datetime.timedelta(days=90),
                                  "date_end": cls.old - datetime.timedelta(days=1)})

        # Позиция без прайса — «нет в прайсах».
        cls.bare_tmpl = cls.env["product.template"].create({"name": "Уголок 200×20 (тест 37)"})
        cls.bare = cls.env["pmk.metal.profile"].create({
            "type_id": ptype.id, "profile_type": "Уголок (тест 37)", "gost": "ГОСТ тест",
            "size_label": "200×20", "mass_per_meter": 60.0, "product_tmpl_id": cls.bare_tmpl.id})

        # Строка прайса без даты — действует всегда.
        cls.bolt_tmpl = cls.env["product.template"].create({"name": "Болт М12 (тест 37)", "weight": 0.5})
        cls.undated = Info.create({"partner_id": cls.metal.id, "product_tmpl_id": cls.bolt_tmpl.id,
                                   "price": 110.0})

        # Метиз из справочника: масса штуки с граммами, в карточке — грубее.
        cls.screw_tmpl = cls.env["product.template"].create({
            "name": "Болт М12×40 (тест 37)", "weight": 0.05})
        cls.screw = cls.env["pmk.metal.fastener"].create({
            "name": "Болт М12×40 (тест 37)", "weight_kg": 0.0542,
            "product_tmpl_id": cls.screw_tmpl.id})
        # Лист: масса — вес карточки, его и берёт расчёт.
        cls.sheet_tmpl = cls.env["product.template"].create({
            "name": "Лист 5 мм (тест 37)", "weight": 500.0})
        cls.env["pmk.metal.sheet"].create({
            "sheet_type": "Гладкий (тест 37)", "thickness_mm": 5.0, "gost": "ГОСТ тест",
            "mass_per_sqm": 39.25, "product_tmpl_id": cls.sheet_tmpl.id})
        # Учёт партиями — у неё на вкладке «Склад» есть блок партий.
        cls.lot_tmpl = cls.env["product.template"].create({
            "name": "Уголок партиями (тест 37)", "is_storable": True, "tracking": "lot"})

    def _arch(self, model, xmlid=None, view_type="list"):
        view_id = self.env.ref(xmlid).id if xmlid else False
        views = self.env[model].with_user(self.admin).get_views([(view_id, view_type)])
        return etree.fromstring(views["views"][view_type]["arch"])

    def _join(self, *xmlids):
        self.admin.write({"group_ids": [Command.link(self.env.ref(x).id) for x in xmlids]})

    def _switches(self, *xmlids):
        """У admin ровно эти группы-выключатели (и «Партии»), остальные сняты.
        «Партии» могли прийти и через «Внутреннего пользователя» (демо-данные
        одноразовой базы) — такую не снять, тест это учитывает."""
        self.admin.write({"group_ids": [Command.unlink(self.env.ref(x).id) for x in (REMOVED, STOCK, LOTS)]
                                       + [Command.link(self.env.ref(x).id) for x in xmlids]})

    def _filter_domain(self, search_arch, name):
        node = search_arch.xpath("//filter[@name='%s']" % name)
        self.assertEqual(len(node), 1, name)
        return safe_eval(node[0].get("domain"),
                         {"context_today": lambda: self.today, "relativedelta": relativedelta})

    def test_views_active(self):
        for xmlid in VIEWS:
            with self.subTest(view=xmlid):
                self.assertTrue(self.env.ref(xmlid).active)

    # ─── (1) «Цены поставщиков»: старые и без даты (сделано шагом 25) ──
    def test_price_filters_stale_and_undated(self):
        """«Действуют сегодня» + «Старше 30 дней» — цены, которые расчёт ещё
        берёт, а прайс пора обновить (на боевой базе 02.10 — 9 строк от
        16.06). «Без даты» — строка, которая действует всегда."""
        search = self._arch("product.supplierinfo", "pmk_purchase.view_supplier_price_search", "search")
        Info = self.env["product.supplierinfo"]
        ours = [("product_tmpl_id", "in", (self.angle_tmpl | self.bolt_tmpl).ids)]
        current = self._filter_domain(search, "current")
        stale = Info.search(ours + current + self._filter_domain(search, "older_30"))
        self.assertIn(self.base_line, stale)
        self.assertNotIn(self.closed, stale, "Закрытый прайс — не «действует сегодня».")
        self.assertNotIn(self.undated, stale, "Строка без даты — не «старше 30 дней».")
        undated = Info.search(ours + self._filter_domain(search, "no_date"))
        self.assertEqual(undated, self.undated)
        self.assertIn(self.undated, Info.search(ours + current), "Без даты — действует всегда.")

    # ─── (2) Номенклатура: цена одной дверью с расчётом ────────────────
    def test_price_columns_one_door(self):
        seller = self.angle_tmpl._pmk_find_seller(self.today)
        self.assertEqual(seller, self.base_line)
        self.assertAlmostEqual(self.angle_tmpl.pmk_price_unit, 1000.0, places=2)
        self.assertAlmostEqual(self.angle_tmpl.pmk_price_ton, 100000.0, places=0)
        self.assertAlmostEqual(self.angle_tmpl.pmk_price_ton, self.angle.pmk_price_ton, places=0,
                               msg="Номенклатура и справочник показывают одну цену.")
        self.assertEqual(self.angle_tmpl.pmk_price_date, self.old)
        self.assertEqual(self.angle_tmpl.pmk_price_supplier_label, self.metal.display_name)
        self.assertFalse(self.angle_tmpl.pmk_price_missing)
        variant = self.angle_tmpl.product_variant_id
        self.assertEqual(variant.pmk_price_supplier_label, self.metal.display_name)
        self.assertAlmostEqual(variant.pmk_price_unit, 1000.0, places=2)
        # Рейтинг сменился — цена в колонке меняется сразу, как и у расчёта.
        self.far.pmk_supplier_rank = 5
        self.assertEqual(self.angle_tmpl.pmk_price_supplier_label, self.far.display_name)
        self.assertAlmostEqual(self.angle_tmpl.pmk_price_unit, 900.0, places=2)

    def test_no_price_is_a_signal(self):
        self.assertEqual(self.bare_tmpl.pmk_price_supplier_label, NO_PRICE)
        self.assertEqual(NO_PRICE, self.bare.pmk_price_supplier_label,
                         "Одно понятие — одно слово: как в справочнике.")
        self.assertTrue(self.bare_tmpl.pmk_price_missing)
        self.assertFalse(self.bare_tmpl.pmk_price_unit)
        self.assertFalse(self.bare_tmpl.pmk_price_date)
        self.assertEqual(self.bare_tmpl.pmk_price_count, 0)
        Tmpl = self.env["product.template"]
        ours = [("id", "in", (self.angle_tmpl | self.bare_tmpl).ids)]
        for domain, missing in (([("pmk_price_missing", "=", True)], True),
                                ([("pmk_price_missing", "!=", False)], True),
                                ([("pmk_price_missing", "=", False)], False),
                                ([("pmk_price_missing", "in", [True, False])], None)):
            with self.subTest(domain=domain):
                found = Tmpl.search(domain + ours)
                expected = {True: self.bare_tmpl, False: self.angle_tmpl,
                            None: self.angle_tmpl | self.bare_tmpl}[missing]
                self.assertEqual(found, expected)
        self.assertEqual(self.env["product.product"].search(
            [("pmk_price_missing", "=", True), ("product_tmpl_id", "=", self.bare_tmpl.id)]),
            self.bare_tmpl.product_variant_id)

    def test_nomenclature_is_this_list(self):
        """Предпосылка: «Номенклатура» (действие склада без своего вида) и
        «Искать ещё…» открывают именно эти списки — список по умолчанию."""
        for model, xmlid in LISTS:
            with self.subTest(model=model):
                default = self.env[model].get_views([(False, "list")])
                self.assertEqual(default["views"]["list"]["id"], self.env.ref(xmlid).id)

    def test_nomenclature_columns(self):
        for model, xmlid in LISTS:
            arch = self._arch(model, xmlid)
            names = [f.get("name") for f in shown(arch, "/list/field") if f.get("optional") != "hide"]
            with self.subTest(view=xmlid):
                self.assertEqual([n for n in names if n in COLUMNS], COLUMNS)
                code = arch.xpath("/list/field[@name='default_code']")[0]
                self.assertEqual(code.get("string"), "Артикул")
                self.assertEqual(code.get("width"), "140px", "Артикул не обрезается.")
                self.assertEqual(arch.xpath("/list/field[@name='name']")[0].get("string"), "Название")
                uom = arch.xpath("/list/field[@name='uom_id']")
                self.assertEqual(len(uom), 1, "Ед. — всем, без «Единиц измерения».")
                self.assertEqual(uom[0].get("string"), "Ед.")
                mass = arch.xpath("/list/field[@name='pmk_mass_unit']")
                self.assertEqual(len(mass), 1, "Масса — та, что у расчёта, а не вес карточки.")
                self.assertEqual(self.env[model]._fields["pmk_mass_unit"].string, "Вес единицы, кг")
                self.assertTrue(self.env[model]._fields["pmk_mass_unit"].readonly,
                                "Масса пачкой в списке не правится.")
                self.assertFalse(shown(arch, "/list/field[@name='weight']"),
                                 "Вес карточки рядом с массой расчёта — две разные массы.")
                label = arch.xpath("/list/field[@name='pmk_price_supplier_label']")[0]
                self.assertEqual(label.get("decoration-muted"), "pmk_price_missing",
                                 "«нет в прайсах» — серым, не красным.")
                self.assertEqual(arch.xpath("/list/field[@name='pmk_price_unit']")[0].get("invisible"),
                                 "pmk_price_missing")
                self.assertTrue(arch.xpath("/list/field[@name='pmk_price_missing']"),
                                "Признак для серого цвета — в разметке (скрытой колонкой).")

    def test_mass_one_door(self):
        """Масса в «Номенклатуре» и в карточке — та, по которой расчёт и
        «Цена, ₽/т» переводят цену в тонны (находка проверки: правка «Веса
        метра» в карточке не меняла ни расчёт, ни цену за тонну рядом)."""
        # Вес карточки разошёлся со справочником — масса всё равно справочная.
        self.angle_tmpl.weight = 12.0
        cases = (
            # карточка, масса из справочника?, масса
            (self.angle_tmpl, True, 10.0),     # прокат — масса метра
            (self.bare_tmpl, True, 60.0),      # прокат без прайса — тоже
            (self.screw_tmpl, True, 0.0542),   # метиз — масса штуки, с граммами
            (self.sheet_tmpl, False, 500.0),   # лист — вес карточки, как в расчёте
            (self.bolt_tmpl, False, 0.5),      # не в справочнике — вес карточки
        )
        for tmpl, from_reference, mass in cases:
            with self.subTest(product=tmpl.name):
                self.assertEqual(tmpl.pmk_mass_ref, from_reference)
                self.assertAlmostEqual(tmpl.pmk_mass_unit, mass, places=5)
                variant = tmpl.product_variant_id
                self.assertEqual(variant.pmk_mass_ref, from_reference)
                self.assertAlmostEqual(variant.pmk_mass_unit, mass, places=5)
        # Цена за тонну в той же строке посчитана по этой же массе.
        self.assertAlmostEqual(
            self.angle_tmpl.pmk_price_unit / self.angle_tmpl.pmk_mass_unit * 1000.0,
            self.angle_tmpl.pmk_price_ton, places=0)
        self.assertAlmostEqual(self.angle_tmpl.pmk_price_ton, 100000.0, places=0)
        self.assertIn("правятся там", self.env["product.template"]._fields["pmk_mass_unit"].help,
                      "Подсказка «?» у подписи говорит, где масса правится.")

    def test_weight_not_summed_in_groups(self):
        """«Номенклатура» сгруппирована по категории: сумма весов метра разных
        профилей ничего не значит."""
        for model in ("product.template", "product.product"):
            with self.subTest(model=model):
                self.assertIsNone(self.env[model]._fields["weight"].aggregator)
        self.assertIsNone(self.env["res.partner"]._fields["pmk_supplier_rank"].aggregator,
                          "Рейтинги в строке группы «Поставщиков прайсов» не складываются.")

    def test_no_price_filter(self):
        arch = self._arch("product.template", "product.product_template_search_view", "search")
        domain = self._filter_domain(arch, "pmk_no_price")
        self.assertEqual(arch.xpath("//filter[@name='pmk_no_price']")[0].get("string"), "Нет в прайсах")
        found = self.env["product.template"].search(
            domain + [("id", "in", (self.angle_tmpl | self.bare_tmpl).ids)])
        self.assertEqual(found, self.bare_tmpl)

    # ─── (3) Карточка товара ─────────────────────────────────────────────
    def test_card_reference_weight_and_prices_button(self):
        self._switches()
        for model, xmlid in FORMS:
            arch = self._arch(model, xmlid, "form")
            with self.subTest(view=xmlid):
                code = shown(arch, "//group[@name='group_standard_price']/field[@name='default_code']")
                self.assertEqual(len(code), 1)
                self.assertEqual(code[0].get("string"), "Артикул")
                general = "//page[@name='general_information']"
                self.assertTrue(arch.xpath(general + "//div[@name='weight']/field[@name='weight']"),
                                "Вес — в «Основной информации».")
                self.assertTrue(arch.xpath(general + "//div[@name='weight']/field[@name='pmk_mass_unit']"),
                                "Масса из справочника — в той же строке.")
                for name in ("pmk_is_linear", "pmk_mass_ref"):
                    self.assertTrue(arch.xpath("//field[@name='%s']" % name),
                                    "Признак — в разметке: по нему выбирается подпись и поле.")
                # Видимое по виду позиции: (подпись, к какому полю), поле в строке.
                kinds = {
                    "прокат": ({"pmk_is_linear": True, "pmk_mass_ref": True},
                               ("Вес метра", "pmk_mass_unit"), "pmk_mass_unit"),
                    "метиз, краска": ({"pmk_is_linear": False, "pmk_mass_ref": True},
                                      ("Вес единицы", "pmk_mass_unit"), "pmk_mass_unit"),
                    "лист, остальное": ({"pmk_is_linear": False, "pmk_mass_ref": False},
                                        ("Вес единицы", "weight"), "weight"),
                }
                labels = arch.xpath(general + "//label[@for='weight' or @for='pmk_mass_unit']")
                fields_ = arch.xpath(general + "//div[@name='weight']/field[@name!='weight_uom_name']")
                for kind, (flags, label, field) in kinds.items():
                    values = dict(flags, type="consu", product_variant_count=1,
                                  is_product_variant=model == "product.product")
                    with self.subTest(view=xmlid, kind=kind):
                        visible = [(n.get("string"), n.get("for")) for n in labels
                                   if not safe_eval(n.get("invisible") or "False", values)]
                        self.assertEqual(visible, [label])
                        visible = [n.get("name") for n in fields_
                                   if not safe_eval(n.get("invisible") or "False", values)]
                        self.assertEqual(visible, [field])
                first = arch.xpath("//div[@name='button_box']/button")[0]
                self.assertEqual(first.get("name"), "action_pmk_open_prices")
                self.assertIsNone(first.get("invisible"), "Наш шаг — видна всегда, ноль серым.")
                self.assertEqual(first.xpath("./field[@name='pmk_price_count']")[0].get("string"), "Цены")
                po = arch.xpath("//button[@name='action_view_po']")
                self.assertEqual(len(po), 1)
                self.assertIn("not purchased_product_qty", po[0].get("invisible"),
                              "«Закуплено» — штатный процесс: только при числе больше нуля.")

    def test_inventory_tab(self):
        """«Склад»: вес уехал, остальное шаг 29 убрал — вкладка только тем, у
        кого на ней что-то есть: «Убранное» или «Партии» (прослеживаемость).
        «Склад (показать)» на этой вкладке ничего не возвращает. С
        «Партиями» без «Убранного» — только у позиции с учётом партиями:
        блок партий ядро у остальных прячет (находка проверки шага 37)."""
        for model, xmlid in FORMS:
            self._switches()
            lots = self.admin.has_group(LOTS)
            arch = self._arch(model, xmlid, "form")
            with self.subTest(view=xmlid, switches="нет"):
                self.assertEqual(bool(arch.xpath("//page[@name='inventory']")), lots)
                self.assertFalse(arch.xpath("//group[@name='group_lots_and_weight']"),
                                 "Пустого заголовка «Логистика» нет.")
            self._switches(STOCK)
            arch = self._arch(model, xmlid, "form")
            with self.subTest(view=xmlid, switches="Склад"):
                self.assertEqual(bool(arch.xpath("//page[@name='inventory']")), lots)
            self._switches(REMOVED)
            arch = self._arch(model, xmlid, "form")
            with self.subTest(view=xmlid, switches="Убранное"):
                self.assertTrue(arch.xpath("//page[@name='inventory']"))
                self.assertTrue(arch.xpath("//group[@name='group_lots_and_weight']"))
                self.assertTrue(arch.xpath("//page[@name='inventory']//field[@name='volume']"))
                self.assertFalse(arch.xpath("//page[@name='inventory']//field[@name='weight']"),
                                 "Вес не вернулся на «Склад».")
            self._switches(LOTS)
            arch = self._arch(model, xmlid, "form")
            with self.subTest(view=xmlid, switches="Партии"):
                page = arch.xpath("//page[@name='inventory']")
                self.assertTrue(page)
                self.assertTrue(arch.xpath("//page[@name='inventory']//group[@name='traceability']"))
                self.assertFalse(arch.xpath("//group[@name='group_lots_and_weight']"))
                # Блок партий ядро показывает только при учёте партиями — по
                # тому же признаку и вкладка.
                self.assertEqual(
                    arch.xpath("//page[@name='inventory']//group[@name='traceability']")[0].get("invisible"),
                    "tracking == 'none'")
                self.assertIn("not pmk_inventory_tab", page[0].get("invisible"))
                self.assertTrue(arch.xpath("//field[@name='pmk_inventory_tab']"),
                                "Признак — в разметке (ядро добавляет его невидимым).")

    def test_inventory_tab_flag(self):
        """Признак вкладки «Склад»: «Убранное» у того, кто смотрит, или учёт
        партиями у позиции. Метизы и краски на боевой базе — учёт
        количеством (31 из 753)."""
        cases = (
            # группы, позиция, вкладка видна?
            ((LOTS,), self.bolt_tmpl, False),
            ((LOTS,), self.lot_tmpl, True),
            ((REMOVED,), self.bolt_tmpl, True),
            ((REMOVED, LOTS), self.bolt_tmpl, True),
        )
        self.assertEqual(self.bolt_tmpl.tracking, "none")
        self.assertEqual(self.lot_tmpl.tracking, "lot")
        for groups, tmpl, visible in cases:
            self._switches(*groups)
            self.env.invalidate_all()
            with self.subTest(groups=groups, product=tmpl.name):
                record = tmpl.with_user(self.admin)
                self.assertEqual(record.pmk_inventory_tab, visible)
                self.assertEqual(record.product_variant_id.pmk_inventory_tab, visible)

    def test_weight_still_editable_from_form(self):
        """Вес переехал — правится там же, через тот же вид и onchange, что у
        браузера. У нового товара «Цены 0»."""
        form = Form(self.env["product.template"].with_user(self.admin))
        form.name = "Уголок 63×5 (тест 37)"
        form.weight = 4.81
        record = form.save()
        self.assertAlmostEqual(record.weight, 4.81, places=2)
        self.assertEqual(record.pmk_price_count, 0)
        self.assertEqual(record.pmk_price_supplier_label, NO_PRICE)

    def test_prices_button_opens_same_rows(self):
        """«Цены N» — поставщики с ценой на сегодня, а не строки с оптовыми
        порогами (находка проверки: «3» у всех 261 позиции — базовая и два
        порога одного Металлсервиса). Список, который кнопка открывает, —
        базовые цены: строк столько же, сколько на кнопке."""
        self.assertEqual(self.angle_tmpl.pmk_price_count, 2,
                         "Металлсервис (базовая и опт) и второй поставщик; закрытый прайс не в счёт.")
        self.assertEqual(self.angle_tmpl.product_variant_id.pmk_price_count, 2)
        self.assertEqual(self.bolt_tmpl.pmk_price_count, 1, "Строка без даты действует всегда.")
        search = self._arch("product.supplierinfo", "pmk_purchase.view_supplier_price_search", "search")
        self.assertTrue(search.xpath("//field[@name='product_tmpl_id']"),
                        "Фасет «Позиция» — поле поиска списка цен.")
        current = self._filter_domain(search, "current")
        base = self._filter_domain(search, "base_qty")
        rows = self.env["product.supplierinfo"].search_count(
            [("product_tmpl_id", "=", self.angle_tmpl.id)] + current + base)
        self.assertEqual(rows, self.angle_tmpl.pmk_price_count)
        for record in (self.angle_tmpl, self.angle_tmpl.product_variant_id):
            action = record.with_user(self.admin).action_pmk_open_prices()
            with self.subTest(model=record._name):
                self.assertEqual(action["res_model"], "product.supplierinfo")
                self.assertEqual(action["views"][0][0],
                                 self.env.ref("pmk_purchase.view_supplier_price_list").id)
                ctx = action["context"]
                self.assertEqual(ctx["search_default_product_tmpl_id"], self.angle_tmpl.id)
                self.assertEqual(ctx["search_default_current"], 1)
                self.assertEqual(ctx["search_default_base_qty"], 1,
                                 "Базовые цены — по строке на поставщика, опт — снять фасет.")
                self.assertFalse(ctx["visible_product_tmpl_id"],
                                 "Форма строки прайса показывает товар, как в «Ценах поставщиков».")
                self.assertFalse(action.get("domain"), "Отбор — фасетами, их можно снять.")
                self.assertIn("в городе нет", action["help"])

    def test_prices_button_wholesale_only(self):
        """Позиция, у которой на сегодня одни оптовые строки: расчёт берёт
        оптовую (_pmk_find_seller), поэтому и кнопка её считает, и список
        открывается без фасета «Базовая цена» — не пустым."""
        tmpl = self.env["product.template"].create({"name": "Швеллер опт (тест 37)"})
        self.env["product.supplierinfo"].create({
            "partner_id": self.metal.id, "product_tmpl_id": tmpl.id,
            "price": 800.0, "min_qty": 5.0, "date_start": self.old})
        self.assertEqual(tmpl.pmk_price_count, 1)
        self.assertFalse(tmpl.pmk_price_missing)
        ctx = tmpl.with_user(self.admin).action_pmk_open_prices()["context"]
        self.assertNotIn("search_default_base_qty", ctx)
        search = self._arch("product.supplierinfo", "pmk_purchase.view_supplier_price_search", "search")
        rows = self.env["product.supplierinfo"].search_count(
            [("product_tmpl_id", "=", tmpl.id)] + self._filter_domain(search, "current"))
        self.assertEqual(rows, tmpl.pmk_price_count)

    def test_sale_flag_untouched(self):
        """Шаг 37 галочку «Продажи» в базе не меняет: у нового товара она по
        умолчанию стоит, а в карточке её спрятал шаг 29 («Убранное»)."""
        self.assertTrue(self.angle_tmpl.sale_ok)
        self._switches()
        arch = self._arch("product.template", "product.product_template_only_form_view", "form")
        self.assertFalse(shown(arch, "//span[@name='sale_option']"))

    # ─── (4) «Адрес проверен» / «Адрес не работает» ─────────────────────
    def test_address_buttons_in_header(self):
        """Строка кнопок над отмеченными: сначала адрес, потом рассылка;
        подписи короткие — при 1440 px строка не ломается на две (находка
        проверки: шесть кнопок с прежними подписями ≈1010 px при ≈810
        свободных)."""
        arch = self._arch("res.partner", "pmk_purchase.view_price_supplier_list")
        buttons = arch.xpath("/list/header/button")
        self.assertEqual([(b.get("name"), b.get("string")) for b in buttons], HEADER)
        filled = [b.get("name") for b in buttons if "btn-primary" in (b.get("class") or "")]
        self.assertEqual(filled, ["action_pmk_mailing_on"], "Залитая — одна.")
        # Подсказка «Рассылки прайсов» называет кнопку тем же словом.
        mailing = etree.fromstring(self.env["pmk.price.mailing"].get_views(
            [(self.env.ref("pmk_purchase.view_price_mailing_form").id, "form")]
        )["views"]["form"]["arch"])
        text = " ".join(" ".join(mailing.itertext()).split())
        self.assertIn("нажмите сверху «В рассылку»", text)
        self.assertNotIn("Включить в рассылку", text)

    def test_address_state_on_selected(self):
        Partner = self.env["res.partner"]
        a = Partner.create({"name": "А (тест 37)", "is_company": True, "pmk_price_supplier": True,
                            "pmk_price_email": "a@supplier.example", "pmk_price_mailing": True})
        b = Partner.create({"name": "Б (тест 37)", "is_company": True, "pmk_price_supplier": True,
                            "pmk_price_email": "b@supplier.example", "email": "b@supplier.example",
                            "pmk_price_mailing": True})
        bare = Partner.create({"name": "Без адреса (тест 37)", "is_company": True,
                               "pmk_price_supplier": True})
        (a | b).action_pmk_confirm_price_email()
        self.assertEqual(set((a | b).mapped("pmk_price_email_state")), {"confirmed"})
        self.assertFalse(a.email, "Адрес в «Эл. почту» контрагента кнопка не переносит.")
        self.assertTrue(a.pmk_price_mailing, "Рассылку кнопка не трогает.")
        b.action_pmk_invalidate_price_email()
        self.assertEqual(b.pmk_price_email_state, "invalid")
        self.assertEqual(b.email, "b@supplier.example", "«Эл. почту» кнопка не стирает.")
        self.assertTrue(b.pmk_price_mailing, "Сигнал, а не запрет: из рассылки не снимает.")
        with self.assertRaises(UserError) as caught:
            (a | bare).action_pmk_invalidate_price_email()
        self.assertIn(bare.display_name, str(caught.exception), "Отказ называет, у кого нет адреса.")
        self.assertEqual(a.pmk_price_email_state, "confirmed", "Пачка не меняется наполовину.")
        with self.assertRaises(UserError):
            bare.action_pmk_confirm_price_email()
        self.assertEqual(bare.pmk_price_email_state, "draft")

    def test_refusal_names_the_way(self):
        """Отказ ведёт туда, где адрес можно вписать (находка проверки):
        блок «Прайсы» есть только у реестра прайсов, а кнопки видны и в
        «Закупки → Поставщики». Поставщику не из реестра — сначала флажок
        «Поставщик прайсов», как в отказе «В рассылку»."""
        Partner = self.env["res.partner"]
        inside = Partner.create({"name": "Реестр без адреса (тест 37)", "is_company": True,
                                 "pmk_price_supplier": True})
        outside = Partner.create({"name": "Новый поставщик (тест 37)", "is_company": True,
                                  "supplier_rank": 1})
        with self.assertRaises(UserError) as caught:
            inside.action_pmk_confirm_price_email()
        text = str(caught.exception)
        self.assertIn("блок «Прайсы»", text)
        self.assertNotIn("не в реестре", text)
        with self.assertRaises(UserError) as caught:
            outside.action_pmk_invalidate_price_email()
        text = str(caught.exception)
        self.assertIn("не в реестре прайсов", text)
        self.assertIn("«Поставщик прайсов»", text)
        self.assertIn(outside.display_name, text)
        with self.assertRaises(UserError) as caught:
            (inside | outside).action_pmk_confirm_price_email()
        text = str(caught.exception)
        self.assertLess(text.index(inside.display_name), text.index("не в реестре прайсов"))
        self.assertGreater(text.index(outside.display_name), text.index("не в реестре прайсов"))
        # Поставщик не из реестра, но с адресом (на боевой базе таких 9, все в
        # архиве) — адрес есть, проверить его можно.
        outside.pmk_price_email = "price@outside.example"
        outside.action_pmk_confirm_price_email()
        self.assertEqual(outside.pmk_price_email_state, "confirmed")

    def test_new_address_is_not_checked(self):
        """Сменили адрес — состояние снова «Не проверен» (находка проверки:
        «Не работает» и «Проверен» оставались у нового адреса)."""
        Partner = self.env["res.partner"]

        def supplier(name, email, state):
            return Partner.create({"name": name, "is_company": True, "pmk_price_supplier": True,
                                   "pmk_price_email": email, "pmk_price_email_state": state})

        broken = supplier("Не работал (тест 37)", "old@supplier.example", "invalid")
        broken.pmk_price_email = "new@supplier.example"
        self.assertEqual(broken.pmk_price_email_state, "draft")
        checked = supplier("Проверен (тест 37)", "ok@supplier.example", "confirmed")
        checked.pmk_price_email = " OK@Supplier.example "
        self.assertEqual(checked.pmk_price_email_state, "confirmed",
                         "Тот же ящик (пробелы, регистр) — проверка в силе.")
        checked.write({"pmk_price_email": "other@supplier.example",
                       "pmk_price_email_state": "confirmed"})
        self.assertEqual(checked.pmk_price_email_state, "confirmed",
                         "Передали состояние вместе с адресом — берём переданное.")
        checked.pmk_price_email = False
        self.assertEqual(checked.pmk_price_email_state, "draft", "Нет адреса — нечего и проверять.")
        # Пачкой: у каждого — по своему адресу.
        same = supplier("Тот же адрес (тест 37)", "same@supplier.example", "confirmed")
        other = supplier("Другой адрес (тест 37)", "other2@supplier.example", "confirmed")
        (same | other).write({"pmk_price_email": "same@supplier.example"})
        self.assertEqual(same.pmk_price_email_state, "confirmed")
        self.assertEqual(other.pmk_price_email_state, "draft")
        # В открытой карточке — сразу, до сохранения; вернули адрес — вернулось
        # и состояние.
        spec = {"pmk_price_email": {}, "pmk_price_email_state": {}}
        card = supplier("Карточка (тест 37)", "card@supplier.example", "invalid")
        value = card.onchange({"pmk_price_email": "fresh@supplier.example"},
                              ["pmk_price_email"], spec)["value"]
        self.assertEqual(value["pmk_price_email_state"], "draft")
        value = card.onchange({"pmk_price_email": "card@supplier.example"},
                              ["pmk_price_email"], spec)["value"]
        self.assertEqual(value.get("pmk_price_email_state", card.pmk_price_email_state), "invalid")
        self.assertEqual(card.pmk_price_email_state, "invalid", "В базе — до сохранения ничего.")

    def test_address_state_words(self):
        """Одно понятие — одно слово: кнопка «Адрес проверен» → плашка
        «Проверен» → фильтр «Адрес проверен»."""
        selection = dict(self.env["res.partner"].fields_get(
            ["pmk_price_email_state"])["pmk_price_email_state"]["selection"])
        self.assertEqual(selection, {"draft": "Не проверен", "confirmed": "Проверен",
                                     "invalid": "Не работает"})
        search = self._arch("res.partner", "pmk_purchase.view_price_supplier_search", "search")
        strings = {name: search.xpath("//filter[@name='%s']" % name)[0].get("string")
                   for name in ("confirmed", "draft", "invalid")}
        self.assertEqual(strings, {"confirmed": "Адрес проверен", "draft": "Адрес не проверен",
                                   "invalid": "Адрес не работает"})
        self.assertEqual(self._filter_domain(search, "invalid"),
                         [("pmk_price_email_state", "=", "invalid")])

    def test_unchecked_filter_skips_no_address(self):
        """«Адрес не проверен» — только у кого адрес есть: отметить всё и
        нажать «Адрес проверен» не упрётся в поставщика без адреса (на боевой
        базе — «Метиз Центр»)."""
        Partner = self.env["res.partner"]
        with_mail = Partner.create({"name": "С адресом (тест 37)", "is_company": True,
                                    "pmk_price_supplier": True,
                                    "pmk_price_email": "x@supplier.example"})
        without = Partner.create({"name": "Без адреса 2 (тест 37)", "is_company": True,
                                  "pmk_price_supplier": True})
        search = self._arch("res.partner", "pmk_purchase.view_price_supplier_search", "search")
        found = Partner.search(self._filter_domain(search, "draft")
                               + [("id", "in", (with_mail | without).ids)])
        self.assertEqual(found, with_mail)
        found.action_pmk_confirm_price_email()
        self.assertEqual(with_mail.pmk_price_email_state, "confirmed")

    # ─── (5) Подписи и «Рейтинг» ─────────────────────────────────────────
    def test_price_supplier_list_labels(self):
        arch = self._arch("res.partner", "pmk_purchase.view_price_supplier_list")

        def col(name):
            nodes = arch.xpath("/list/field[@name='%s']" % name)
            self.assertEqual(len(nodes), 1, name)
            return nodes[0]

        for name, label in PARTNER_LABELS.items():
            with self.subTest(label=name):
                self.assertEqual(col(name).get("string"), label)
        rank = col("pmk_supplier_rank")
        self.assertEqual(rank.get("string"), "Рейтинг")
        self.assertEqual(rank.get("optional"), "show")
        names = [f.get("name") for f in arch.xpath("/list/field")]
        self.assertEqual(names.index("pmk_supplier_rank"), names.index("pmk_has_stock") + 1)
        self.assertEqual(col("pmk_price_email_state").get("invisible"), "not pmk_price_email",
                         "Нет адреса — нечего и проверять: плашки нет.")
        # Ширины шагов 25/26 — на месте.
        for name, width in (("pmk_price_mailing", "70px"), ("pmk_supply_ids", "170px"),
                            ("pmk_has_stock", "44px"), ("pmk_price_request_date", "112px"),
                            ("pmk_price_last_date", "80px")):
            with self.subTest(width=name):
                self.assertEqual(col(name).get("width"), width)

    def test_partner_card_same_words(self):
        """Карточка поставщика (блок «Прайсы», шаг 28): те же слова, что в
        списке, и плашки без адреса нет и здесь (находки проверки)."""
        view_id = self.env.ref("base.view_partner_form").id
        arch = etree.fromstring(self.env["res.partner"].with_user(self.admin).get_views(
            [(view_id, "form")])["views"]["form"]["arch"])

        def card(name):
            nodes = arch.xpath("//group[@name='pmk_price']//field[@name='%s']" % name)
            self.assertEqual(len(nodes), 1, name)
            return nodes[0]

        for name, label in PARTNER_LABELS.items():
            with self.subTest(label=name):
                self.assertEqual(card(name).get("string"), label)
        self.assertEqual(card("pmk_price_email_state").get("invisible"), "not pmk_price_email")
