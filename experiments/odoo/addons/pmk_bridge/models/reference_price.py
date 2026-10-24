# -*- coding: utf-8 -*-
"""Одна дверь к цене поставщика и список «Цены поставщиков» (разбор UX, шаг 25).

ЗАЧЕМ. Цену из прайса выбирали только внутри строки расчёта
(spec_cost.py, _cost_find_seller). Справочнику проката и листа нужна та же
цена колонкой, а новому списку «Цены поставщиков» — цена за тонну каждой
строки прайса. Если бы каждый экран выбирал строку и считал массу по-своему,
справочник однажды показал бы одну цену, а расчёт взял бы другую, и спорить
пришлось бы уже в деньгах КП.

Поэтому правило выбора строки прайса живёт у карточки товара
(_pmk_find_seller), а масса единицы — у строки справочника
(_pmk_mass_per_unit, reference_link.py). Расчёт, справочник и список цен
зовут одно и то же.
"""

from odoo import api, fields, models

from ..tools import spec_text
from ..tools import grades
from ..tools.grades import BASE_GRADE
from .reference_link import LINKED_MODELS


class ProductTemplatePmkSeller(models.Model):
    _inherit = "product.template"

    # ─── Прокат хлыстами (приёмка 01.10.2026, R11) ───────────────────────
    #
    # Владелец: «Зачем длина хлыста для листа, метизов и т. д.?» Длина хлыста
    # нужна только прокату: его продают хлыстами 6 / 11,7 / 12 м, и по ней
    # раскрой считает, сколько хлыстов купить. Признак — у карточки есть
    # строка справочника сортамента (pmk.metal.profile: арматура, уголок,
    # трубы…). По нему колонка «Длина хлыста» в поставщиках карточки товара
    # видна только у проката, а в «Ценах поставщиков» у не-проката ячейка
    # пустая. Не хранится: связь со справочником правят, а хранимый признак
    # устарел бы молча (так же сделаны цены справочника, reference_link.py).
    pmk_is_linear = fields.Boolean(
        "Прокат (хлыстами)", compute="_compute_pmk_is_linear",
        help="Позиция — прокат из справочника сортамента: продаётся хлыстами, "
             "длина хлыста нужна раскрою. У листа, метизов и краски её нет.")

    def _compute_pmk_is_linear(self):
        # Одним поиском на всю страницу, а не по одному на карточку.
        # _origin: у карточки в форме нового товара записи ещё нет (NewId).
        ids = [tmpl._origin.id for tmpl in self if tmpl._origin.id]
        linear = set()
        if ids:
            linear = set(self.env["pmk.metal.profile"].sudo().search(
                [("product_tmpl_id", "in", ids)]).product_tmpl_id.ids)
        for tmpl in self:
            tmpl.pmk_is_linear = tmpl._origin.id in linear

    def _pmk_find_seller(self, date, supplier=None, uom=None, grade=None):
        """Строка прайса, по которой считаем себестоимость на дату.

        • строка действует на дату (дата начала не позже, окончания не раньше);
        • задан поставщик — только его строки; не задан — поставщик с лучшим
          рейтингом (меньше — раньше), при равном рейтинге — дешевле.
          Сортировка по контрагенту, а не по строке прайса: поле sequence в
          строке занято номером уровня объёма;
        • уровень объёма — САМЫЙ ДЕШЁВЫЙ (оптовый). Антон 19.10.2026: «нам
          всегда считают по самой низкой цене, тк мы оптовики, и это скорее
          общий прайс». Было (до 19.10): базовый, без минимального количества.

        • лист в м², МАРКА (№309, этап 2): только цены варианта марки grade
          (строка без варианта — на всю карточку — годится любой марке). Нет
          цены марки — цены нет: подставлять Ст3сп вместо 09Г2С нельзя (Антон
          18.10: такой марки в прайсах «не может не быть»). Марка не задана —
          самая дешёвая из всех марок (Антон 19.10: «в 90% случаев нужен самый
          дешёвый материал… если требуется, марку меняют в расчёте вручную»);
        • прокат, МАРКА (№313, Владимир 24.10.2026: 09Г2С на 15–20% дороже Ст3):
          марка задана — только цены варианта этой марки. Цены без варианта
          (марка в прайсе не опознана — «Ст2кп», «Углерод.») — только базовой
          марке Ст3сп: обычная сталь, как и было до №313. 09Г2С вместо Ст3сп
          и наоборот не подставляем — «цены нет». Марка не задана — самая
          дешёвая из всех, как у листа;
        • лист в м² (№309): строка ГАБАРИТА uom («Лист 1500×3000»); у
          поставщиков такого нет — любого габарита (вариант «а», Антон 18.10:
          цена тонны та же, единица приведена к м²). Габарит не задан — как
          было до №309: 1500×6000, иначе любой.

        Пустой набор — цены нет: позиции нет в прайсах (сигнал «в городе
        нет», не ошибка).
        """
        self.ensure_one()
        empty = self.env["product.supplierinfo"]
        sellers = self.seller_ids.filtered(
            lambda s: (not s.date_start or s.date_start <= date)
            and (not s.date_end or s.date_end >= date))
        if not sellers:
            return empty

        if supplier:
            sellers = sellers.filtered(lambda s: s.partner_id == supplier)
            if not sellers:
                return empty
        if self._pmk_is_sqm():
            sellers = self._pmk_sellers_of_grade(sellers, grade)
            if not sellers:
                return empty
        elif grade:
            sellers = self._pmk_linear_sellers_of_grade(sellers, grade)
            if not sellers:
                return empty
        if not supplier:
            best_rank = min(sellers.mapped("partner_id.pmk_supplier_rank") or [0])
            sellers = sellers.filtered(
                lambda s: s.partner_id.pmk_supplier_rank == best_rank)

        if self._pmk_is_sqm():
            want = uom or self.env["uom.uom"]._pmk_sheet_uom("1500x6000")
            same = sellers.filtered(lambda s: s.product_uom_id == want)
            sellers = same or sellers

        return sellers.sorted(lambda s: (s.price_discounted, s.id))[:1]

    def _pmk_sellers_of_grade(self, sellers, grade):
        """Строки прайса марки grade (имя, «09Г2С»). Без марки — все: дальше
        выберется самая дешёвая (Антон 19.10)."""
        attr = self.env.ref("pmk_bridge.attr_grade", raise_if_not_found=False)

        def grade_of(info):
            names = info.product_id.product_template_attribute_value_ids.filtered(
                lambda v: v.attribute_id == attr).mapped("name")
            return names[0] if names else None
        if grade:
            return sellers.filtered(lambda s: grade_of(s) in (grade, None))
        return sellers

    def _pmk_linear_sellers_of_grade(self, sellers, grade):
        """Прокат (№313): строки прайса марки grade; строки без варианта — только
        базовой марке (Ст3сп). Правило — в _pmk_find_seller."""
        attr = self.env.ref("pmk_bridge.attr_grade", raise_if_not_found=False)

        def grade_of(info):
            names = info.product_id.product_template_attribute_value_ids.filtered(
                lambda v: v.attribute_id == attr).mapped("name")
            return names[0] if names else None
        # Вариант карточки без строки прайса со своей маркой (product_id пуст у
        # старых цен) — «без марки»; марка базового варианта у проката — Ст3сп.
        return sellers.filtered(
            lambda s: grade_of(s) == grade or (grade_of(s) is None and grade == BASE_GRADE))


    def _pmk_linear_prices_to_grade_variants(self):
        """№313 (24.10.2026): старые цены проката — с шаблона на вариант марки.

        До №313 цена проката лежала на шаблоне, а марка осталась только в
        названии строки прайса («Труба эл/св 114 х 4 Ст 09Г2С»). Загрузчик теперь
        пишет цену на вариант марки, а ряд цен он ведёт по варианту: оставь старые
        строки на шаблоне — новая цена не закрыла бы прошлый период, и старая
        всплывала бы рядом. Поэтому переносим ряд целиком, с историей.

        Карточкам проката без характеристики марки (147 позиций сортамента от
        18.10.2026 завели без неё) — характеристика с базовой маркой Ст3сп, как
        у остальных: единственный вариант её впитывает, нового не заводится.
        Без этого цену Ст3пс или 09Г2С такой карточки загрузчику положить некуда.

        Марка не опознана — строка остаётся на шаблоне («марка не различается»,
        годится базовой марке).
        Возвращает (перенесено по маркам, осталось на шаблоне, не перенесено).
        """
        attr = self.env.ref("pmk_bridge.attr_grade", raise_if_not_found=False)
        moved, kept, refused = {}, 0, {}
        if not attr:
            return moved, kept, refused
        tmpls = self.env["pmk.metal.profile"].sudo().with_context(
            active_test=False).search([]).product_tmpl_id
        base = attr.value_ids.filtered(lambda v: v.name == BASE_GRADE)[:1]
        bare = tmpls.filtered(lambda t: not t.attribute_line_ids and len(t.product_variant_ids) == 1)
        if base:
            for tmpl in bare:
                tmpl.attribute_line_ids = [(0, 0, {"attribute_id": attr.id, "value_ids": [(6, 0, base.ids)]})]
            moved["карточкам добавлена марка Ст3сп"] = len(bare)
        tmpl_ids = tmpls.ids
        infos = self.env["product.supplierinfo"].sudo().search(
            [("product_tmpl_id", "in", tmpl_ids), ("product_id", "=", False)])
        for info in infos:
            grade = grades.grade_from_vendor_name(info.product_name)
            tmpl = info.product_tmpl_id
            if not grade or not tmpl.attribute_line_ids.filtered(lambda l: l.attribute_id == attr):
                kept += 1
                continue
            variant = tmpl._pmk_grade_variant(grade, create=True)
            if not variant:
                refused[grade] = refused.get(grade, 0) + 1
                continue
            info.product_id = variant.id
            moved[grade] = moved.get(grade, 0) + 1
        return moved, kept, refused


class SupplierInfoPmkPrice(models.Model):
    """Строка прайса в списке «Цены поставщиков»: цена за тонну и габарит."""

    _inherit = "product.supplierinfo"

    # aggregator=None: в списке, сгруппированном по поставщику или позиции,
    # цены за метр и за лист и пороги объёма складывались бы в строке группы
    # — суммы, которые ничего не значат (как массы в справочниках, шаг 24).
    # Меняется только итог строки группы; само поле ядра не тронуто.
    price = fields.Float(aggregator=None)
    min_qty = fields.Float(aggregator=None)

    pmk_price_ton = fields.Float(
        "Цена, ₽/т", compute="_compute_pmk_price_ton", digits=(12, 0),
        help="Цена строки за тонну — по той же массе единицы, что берёт "
             "расчёт: прокат — масса метра из справочника, лист — вес листа, "
             "метиз — масса штуки. Пусто — позиция не связана со справочником "
             "или масса неизвестна.")
    # Длина хлыста — только у проката (приёмка 01.10.2026, R11): по этому
    # признаку «Цены поставщиков» оставляют ячейку пустой у листа, метизов и
    # краски. Сама длина объявлена в spec_cost.py (pmk_bar_length_mm).
    pmk_is_linear = fields.Boolean(
        related="product_tmpl_id.pmk_is_linear", string="Прокат (хлыстами)")
    pmk_variant_label = fields.Char(
        "Марка, габарит", compute="_compute_pmk_variant_label",
        help="Характеристики варианта, на который назначена цена: у листа — "
             "марка стали и габарит («Ст3сп, 1500x6000»). У проката цена на "
             "всю позицию, и здесь пусто.")

    @api.depends("price", "discount", "product_tmpl_id", "product_id",
                 "product_tmpl_id.weight", "product_id.weight")
    def _compute_pmk_price_ton(self):
        # Строка справочника по карточке — одним поиском на справочник на всю
        # страницу списка, а не по одному на строку прайса.
        # _origin: у строки, которую заводят в форме нового товара, карточка
        # ещё не записана (NewId), и искать её в справочнике нечем.
        tmpl_ids = self.product_tmpl_id._origin.ids
        reference = {}
        if tmpl_ids:
            for model in LINKED_MODELS:
                for ref in self.env[model].sudo().search([("product_tmpl_id", "in", tmpl_ids)]):
                    reference[ref.product_tmpl_id.id] = ref
        for info in self:
            ref = reference.get(info.product_tmpl_id._origin.id)
            mass = ref._pmk_mass_per_unit(info.product_tmpl_id, variant=info.product_id) if ref else 0.0
            info.pmk_price_ton = spec_text.per_ton(info.price_discounted, mass)

    # №309, этап 2: марка строки прайса отдельной колонкой — у листа цены
    # Ст3сп и 09Г2С одного поставщика стоят рядом, без марки их не отличить.
    pmk_grade_label = fields.Char("Марка", compute="_compute_pmk_grade_label")

    @api.depends("product_id.product_template_attribute_value_ids")
    def _compute_pmk_grade_label(self):
        attr = self.env.ref("pmk_bridge.attr_grade", raise_if_not_found=False)
        for info in self:
            names = info.product_id.product_template_attribute_value_ids.filtered(
                lambda v: v.attribute_id == attr).mapped("name") if attr else []
            info.pmk_grade_label = names[0] if names else False

    @api.depends("product_id.product_template_attribute_value_ids", "product_uom_id")
    def _compute_pmk_variant_label(self):
        # ⚠️ НЕ _get_combination_name(). Штатное имя варианта выбрасывает
        # характеристики, у которых на карточке одно значение, — а у каждого
        # нашего листа ровно один вариант, и имя вышло бы пустым. Здесь нужны
        # сами значения: марка и габарит, по порядку характеристик.
        for info in self:
            values = info.product_id.product_template_attribute_value_ids.sorted(
                lambda v: (v.attribute_id.sequence, v.attribute_id.id))
            names = values.mapped("name")
            # №309: габарит листа — единица цены «Лист WxL», а не вариант.
            size = info.product_uom_id._pmk_sheet_size() if info.product_uom_id else ""
            if size:
                names.append(size)
            info.pmk_variant_label = ", ".join(names) or False
