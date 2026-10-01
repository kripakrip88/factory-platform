# -*- coding: utf-8 -*-
"""Поле связи «строка справочника → карточка товара».

ЗАЧЕМ ЭТОТ ФАЙЛ. До него связь существовала, но не полем, а соглашением об
именах служебных записей: строка `pmk_calc.<имя>` соответствует карточке
`pmk_bridge.product_<имя>`. Загрузчик цен так и ищет цель — `env.ref("pmk_bridge.
product_%s" % ref_id)`. Соглашение работает (сходится 752 позиции из 753), но у
него три беды:

  1. За `ir_model_data.res_id` не следит никто: это обычное число без внешнего
     ключа. Удалили карточку — служебная запись осталась висеть на пустоту.
  2. Каждый потребитель обязан знать правило имён и лазить в служебную таблицу
     строками. Любая опечатка в префиксе даёт «товар не найден» вместо связи.
  3. Из карточки товара нельзя дойти до справочника вообще никак.

Поле снимает все три: связь становится обычным Many2one, за которым следит
внешний ключ базы, и читается из кода как `line.profile_id.product_tmpl_id`.

ПОЧЕМУ ОБЪЯВЛЕНО ЗДЕСЬ, А НЕ В pmk_calc. Манифест pmk_calc обещает текстом:
«Модуль намеренно НЕ зависит от склада: справочник свой, чтобы калькулятор
работал до того, как будет решён вопрос платформы и загружена номенклатура».
Калькуляторы должны считать и без номенклатуры. `pmk_bridge` уже зависит и от
`product`, и от `pmk_calc` — он и есть место для такой связи. Через `_inherit`
колонка физически ляжет в таблицу справочника, но зависимость останется здесь:
не установлен мост — поля просто нет, и всё работает как раньше.

ПОЧЕМУ product.template, А НЕ product.product. Строка справочника описывает
типоразмер («Двутавр 20Б1»), а марка стали и габарит листа заведены как
характеристики с вариантами. Цена проката лежит на шаблоне (738 записей из 780),
цена листа — на варианте, и нужный вариант выбирается в рантайме по паре
(марка, габарит). Хранить вариант в справочнике нечем: марки в строке нет.
"""

from collections.abc import Collection

from odoo import api, fields, models

from ..tools import spec_text

# Справочники, у которых есть карточка товара, и правило имён служебных записей.
# Правило одно на все четыре: карточка называется product_<имя строки>.
LINKED_MODELS = (
    "pmk.metal.profile",
    "pmk.metal.sheet",
    "pmk.metal.fastener",
    "pmk.paint.coating",
)


class ProductLinkMixin(models.AbstractModel):
    """Одно поле связи на четыре справочника.

    Через примесь, а не копированием поля в каждый класс: определение живёт в
    одном месте, и правку (скажем, смену ondelete) нельзя случайно внести в три
    справочника из четырёх.
    """

    _name = "pmk.product.link.mixin"
    _description = "Связь строки справочника с карточкой товара"

    product_tmpl_id = fields.Many2one(
        "product.template",
        string="Карточка товара",
        index=True,
        copy=False,
        # set null, а не cascade и не restrict. cascade увёл бы строку
        # справочника вслед за карточкой — а на неё смотрят спецификации,
        # раскрои и лазерные задания, это девять внешних ключей. restrict
        # запретил бы удалять карточку вовсе, что слишком строго для
        # номенклатуры. set null оставляет справочник целым, связь просто
        # обнуляется и заполняется заново.
        ondelete="set null",
        help="Позиция номенклатуры, соответствующая этой строке справочника. "
             "Через неё берутся цены поставщиков и себестоимость материала.",
    )

    # Одна карточка — одна строка справочника. Иначе два типоразмера начнут
    # брать цену из одной позиции номенклатуры, и расхождение вылезет уже в
    # деньгах, где его трудно заметить. NULL ограничению не мешает: в SQL
    # несколько NULL уникальности не нарушают, незаполненных связей может быть
    # сколько угодно.
    _product_tmpl_uniq = models.Constraint(
        "unique(product_tmpl_id)",
        "На одну карточку товара может ссылаться только одна позиция справочника.",
    )

    # ─── Цена в справочнике (разбор UX, шаг 25) ──────────────────────────
    #
    # Раньше из справочника проката и листа не было видно, есть ли у позиции
    # цена: чтобы узнать, приходилось открывать карточку товара. Теперь —
    # колонками «Цена, ₽/т», «Поставщик», «Прайс от».
    #
    # ОДНА ДВЕРЬ К ЦЕНЕ. Строку прайса выбирает тот же метод, что и расчёт
    # (product.template._pmk_find_seller: действует на дату, поставщик с
    # лучшим рейтингом, при равном — дешевле, базовый уровень объёма), и
    # масса единицы — то же правило (_pmk_mass_per_unit ниже). Справочник
    # показывает ровно ту цену, которую сегодня взял бы новый расчёт.
    #
    # «НЕТ В ПРАЙСАХ» — СИГНАЛ, А НЕ ОШИБКА: позиции нет у поставщиков города.
    # Поэтому серым, а не красным, и ничего не запрещается.
    #
    # Не хранится: цена меняется с каждой заливкой прайса, а дата «сегодня»
    # сдвигается сама — хранимое значение устаревало бы молча.
    pmk_price_ton = fields.Float(
        "Цена, ₽/т", compute="_compute_pmk_price", digits=(12, 0),
        help="Цена поставщика за тонну на сегодня — та, которую взял бы новый "
             "расчёт. Пусто — позиции нет в прайсах или неизвестна масса.")
    pmk_price_supplier_label = fields.Char(
        "Поставщик", compute="_compute_pmk_price",
        help="Чья цена. «нет в прайсах» — позиции нет у поставщиков города: "
             "это сигнал, а не ошибка данных.")
    pmk_price_date = fields.Date(
        "Прайс от", compute="_compute_pmk_price",
        help="С какой даты действует строка прайса, из которой взята цена.")
    pmk_price_missing = fields.Boolean(
        "Нет в прайсах", compute="_compute_pmk_price",
        search="_search_pmk_price_missing",
        help="На сегодня ни одной действующей строки прайса по этой позиции.")

    def _pmk_mass_per_unit(self, tmpl, variant=None):
        """Сколько килограммов в единице, за которую назначена цена.

        У каждого справочника своё правило (см. классы ниже); у примеси —
        ноль, то есть «масса неизвестна», и цена за тонну не считается.
        """
        return 0.0

    @api.depends("product_tmpl_id")
    @api.depends_context("company")
    def _compute_pmk_price(self):
        today = fields.Date.context_today(self)
        for rec in self:
            tmpl = rec.product_tmpl_id
            seller = tmpl._pmk_find_seller(today) if tmpl else False
            if not seller:
                rec.pmk_price_ton = 0.0
                rec.pmk_price_supplier_label = "нет в прайсах"
                rec.pmk_price_date = False
                rec.pmk_price_missing = True
                continue
            rec.pmk_price_ton = spec_text.per_ton(
                seller.price_discounted, rec._pmk_mass_per_unit(tmpl))
            rec.pmk_price_supplier_label = seller.partner_id.display_name
            rec.pmk_price_date = seller.date_start
            rec.pmk_price_missing = False

    def _search_pmk_price_missing(self, operator, value):
        """Фильтр «Нет в прайсах»: без карточки или без действующей строки.

        Условие то же, что у _pmk_find_seller: строка прайса действует на
        сегодня (дата начала не позже, дата окончания не раньше).
        """
        if operator not in ("in", "not in"):
            return NotImplemented
        # Odoo 19 приводит «= True» к ('in', OrderedSet([True])). OrderedSet —
        # не наследник set, а MutableSet: проверка на list/tuple/set его
        # пропускала, и {OrderedSet} падал «unhashable type» окном ошибки
        # при нажатии фильтра. Поэтому — любая коллекция, кроме строки.
        if isinstance(value, Collection) and not isinstance(value, str):
            values = set(value)
        else:
            values = {value}
        want_missing = (True in values) if operator == "in" else (True not in values)
        today = fields.Date.context_today(self)
        priced = self.env["product.supplierinfo"].sudo().search([
            "|", ("date_start", "=", False), ("date_start", "<=", today),
            "|", ("date_end", "=", False), ("date_end", ">=", today),
        ]).product_tmpl_id.ids
        if want_missing:
            return ["|", ("product_tmpl_id", "=", False),
                    ("product_tmpl_id", "not in", priced)]
        return [("product_tmpl_id", "in", priced)]


class MetalProfileLink(models.Model):
    _name = "pmk.metal.profile"
    _inherit = ["pmk.metal.profile", "pmk.product.link.mixin"]

    def _pmk_mass_per_unit(self, tmpl, variant=None):
        # Прокат продаётся метрами: масса погонного метра из справочника, а не
        # вес карточки — там два знака, и 0,0985 превратилось бы в 0,10.
        self.ensure_one()
        return self.mass_per_meter


class MetalSheetLink(models.Model):
    _name = "pmk.metal.sheet"
    _inherit = ["pmk.metal.sheet", "pmk.product.link.mixin"]

    def _pmk_mass_per_unit(self, tmpl, variant=None):
        # Лист продаётся целым листом: нужна масса листа, а не квадратного
        # метра, — она на карточке (сотни килограммов, два знака безвредны).
        # Строка прайса на конкретный вариант (марка × габарит) — его вес:
        # пока вариант один, он равен весу карточки.
        # ⚠️ Мина: второй габарит обнулит вес карточки → масса 0, цены за
        # тонну нет (project_sheet_size_trap).
        self.ensure_one()
        return (variant or tmpl).weight


class MetalFastenerLink(models.Model):
    _name = "pmk.metal.fastener"
    _inherit = ["pmk.metal.fastener", "pmk.product.link.mixin"]

    def _pmk_mass_per_unit(self, tmpl, variant=None):
        # Метиз продаётся штукой: масса штуки из справочника (с граммами).
        self.ensure_one()
        return self.weight_kg


class PaintCoatingLink(models.Model):
    _name = "pmk.paint.coating"
    _inherit = ["pmk.paint.coating", "pmk.product.link.mixin"]

    def _pmk_mass_per_unit(self, tmpl, variant=None):
        # Краска продаётся килограммами: цена единицы и есть цена килограмма.
        self.ensure_one()
        return 1.0
