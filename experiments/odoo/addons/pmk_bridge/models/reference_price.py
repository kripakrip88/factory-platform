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

    def _pmk_find_seller(self, date, supplier=None):
        """Строка прайса, по которой считаем себестоимость на дату.

        • строка действует на дату (дата начала не позже, окончания не раньше);
        • задан поставщик — только его строки; не задан — поставщик с лучшим
          рейтингом (меньше — раньше), при равном рейтинге — дешевле.
          Сортировка по контрагенту, а не по строке прайса: поле sequence в
          строке занято номером уровня объёма;
        • уровень объёма — базовый (без минимального количества): на этапе КП
          объём закупки ещё не определён, и обещать оптовую цену рано.

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
        else:
            best_rank = min(sellers.mapped("partner_id.pmk_supplier_rank") or [0])
            sellers = sellers.filtered(
                lambda s: s.partner_id.pmk_supplier_rank == best_rank)

        base = sellers.filtered(lambda s: not s.min_qty)
        return (base or sellers).sorted(lambda s: (s.price_discounted, s.id))[:1]


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

    @api.depends("product_id.product_template_attribute_value_ids")
    def _compute_pmk_variant_label(self):
        # ⚠️ НЕ _get_combination_name(). Штатное имя варианта выбрасывает
        # характеристики, у которых на карточке одно значение, — а у каждого
        # нашего листа ровно один вариант, и имя вышло бы пустым. Здесь нужны
        # сами значения: марка и габарит, по порядку характеристик.
        for info in self:
            values = info.product_id.product_template_attribute_value_ids.sorted(
                lambda v: (v.attribute_id.sequence, v.attribute_id.id))
            info.pmk_variant_label = ", ".join(values.mapped("name")) or False
