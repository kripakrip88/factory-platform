# -*- coding: utf-8 -*-
"""Номенклатура: цена поставщика колонками и кнопка «Цены N» — разбор UX, шаг 37.

ЗАЧЕМ. В «Номенклатуре» стояли «Стоимость», «На руках», «Прогноз» и цена-
заглушка 1,00 (шаг 29 их спрятал), а цены поставщика не было вовсе: чтобы её
узнать, открывали карточку и вкладку «Покупка». Теперь — колонками: цена за
единицу, за тонну, прайс от, поставщик. Нет цены — серым «нет в прайсах»:
позиции нет у поставщиков города, это сигнал, а не ошибка, ничего не
запрещается.

ОДНА ДВЕРЬ К ЦЕНЕ. Строку прайса выбирает тот же метод, что и расчёт, и
справочники проката и листа (шаг 25): product.template._pmk_find_seller
(pmk_bridge/models/reference_price.py) — действует сегодня, поставщик с
лучшим рейтингом, при равном — дешевле, базовый уровень объёма. Цена за
тонну — поле самой строки прайса (pmk_price_ton, та же масса единицы, что у
расчёта и у списка «Цены поставщиков»). Своего правила выбора здесь нет.

НЕ ХРАНИТСЯ: цена меняется с каждой заливкой прайса, «сегодня» сдвигается
само — хранимое значение устаревало бы молча (как у справочников). Сортировки
по этим колонкам нет — она и не нужна: «что без цены» отбирает фильтр «Нет в
прайсах», «что устарело» — «Закупки → Цены поставщиков», «Старше 30 дней».
Итога в строке группы у них тоже нет: ядро не складывает нехранимые поля.

ОДНА ДВЕРЬ К МАССЕ (проверка шага 37). «Вес единицы, кг» в списке и «Вес
метра» в карточке — масса, по которой расчёт и «Цена, ₽/т» переводят цену в
тонны (pmk_bridge, reference_link.py, _pmk_mass_per_unit): у проката, метизов
и красок — из справочника, только чтение; у листа и остального — вес
карточки, правится в карточке. Раньше там стоял вес карточки у всех: его один
раз залил загрузчик номенклатуры, и правка «Веса метра» в карточке не меняла
ни расчёт, ни цену за тонну рядом.

«Цены N» над карточкой — поставщики, у которых на сегодня есть цена на эту
позицию (проверка шага 37: строки с оптовыми порогами давали «3» у всех 261
позиций с ценой — базовая и два порога одного Металлсервиса). Кнопка
открывает «Цены поставщиков» с фасетами «Действуют сегодня», «Базовая цена
(без опта)» и «Позиция» — по строке на поставщика, столько же, сколько на
кнопке; опт — снять фасет. Условие «действует сегодня» — то же, что у
фильтра current (views/supplier_price_views.xml) и у _pmk_find_seller.

Вернуть как было — убрать импорт этого файла в models/__init__.py и файл
views/step37_product.xml из __manifest__.py (docs/disabled-features.md,
раздел «шаг 37»).
"""
from collections.abc import Collection

from odoo import api, fields, models

from odoo.addons.pmk_theme.models.ir_actions_act_window import hint

# Одно понятие — одно слово: тот же сигнал, что в справочниках проката и
# листа (pmk_bridge, reference_link.py) и в строке расчёта
# (pmk_bridge/static/src/js/product_lines_cost.js).
NO_PRICE = "нет в прайсах"

# Справочники, у которых масса единицы своя, а не вес карточки: прокат —
# масса метра, метизы — масса штуки, краски — 1 кг (продаются килограммами).
# Лист сюда не входит: его масса — вес карточки (вес листа), её берёт и
# расчёт (pmk_bridge, reference_link.py, MetalSheetLink._pmk_mass_per_unit).
MASS_REFERENCES = ("pmk.metal.profile", "pmk.metal.fastener", "pmk.paint.coating")
MASS_HELP = ("Масса единицы, по которой расчёт и «Цена, ₽/т» переводят цену в "
             "тонны. Прокат — масса метра, метизы — масса штуки, краска — 1 кг: "
             "берутся из справочника и правятся там, в карточке только "
             "чтение. Лист и остальное — вес карточки товара.")


def current_domain(today):
    """Строка прайса действует на дату — как фильтр «Действуют сегодня»."""
    return ["|", ("date_start", "=", False), ("date_start", "<=", today),
            "|", ("date_end", "=", False), ("date_end", ">=", today)]


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # «Номенклатура» открывается сгруппированной по категории, и ядро
    # складывало бы веса в строке группы: сумма весов метра разных профилей
    # ничего не значит (тот же приём, что у цен строк прайса, шаг 25).
    # Меняется только итог строки группы, само поле ядра не тронуто.
    weight = fields.Float(aggregator=None)

    pmk_price_unit = fields.Float(
        "Цена, ₽", compute="_compute_pmk_price", digits=(12, 2),
        help="Цена поставщика за единицу товара на сегодня — та, которую взял "
             "бы новый расчёт. Пусто — позиции нет в прайсах.")
    pmk_price_ton = fields.Float(
        "Цена, ₽/т", compute="_compute_pmk_price", digits=(12, 0),
        help="Та же цена за тонну — по массе единицы, которую берёт расчёт. "
             "Пусто — позиции нет в прайсах или масса неизвестна.")
    pmk_price_date = fields.Date(
        "Прайс от", compute="_compute_pmk_price",
        help="С какой даты действует строка прайса, из которой взята цена.")
    pmk_price_supplier_label = fields.Char(
        "Поставщик", compute="_compute_pmk_price",
        help="Чья цена. «нет в прайсах» — позиции нет у поставщиков города: "
             "это сигнал, а не ошибка данных.")
    pmk_price_missing = fields.Boolean(
        "Нет в прайсах", compute="_compute_pmk_price",
        search="_search_pmk_price_missing",
        help="На сегодня ни одной действующей строки прайса по этой позиции.")
    pmk_price_count = fields.Integer(
        "Цены", compute="_compute_pmk_price_count",
        help="Сколько поставщиков дают цену на эту позицию сегодня. Щелчок — "
             "их базовые цены списком «Цены поставщиков»; оптовые пороги — "
             "снять фильтр «Базовая цена (без опта)».")

    # Масса — одной дверью с расчётом (см. шапку файла).
    pmk_mass_ref = fields.Boolean(
        "Масса из справочника", compute="_compute_pmk_mass",
        help="Позиция связана со справочником проката, метизов или красок: "
             "масса единицы берётся оттуда и правится там.")
    # Пять знаков, а не «Stock Weight» базы: масса метра и штуки в
    # справочниках — с граммами (0,0985 кг/м; 0,0054 кг/шт), и округление до
    # точности базы (на свежей базе — два знака) показало бы не ту массу,
    # что берёт расчёт.
    pmk_mass_unit = fields.Float(
        "Вес единицы, кг", compute="_compute_pmk_mass", digits=(12, 5),
        help=MASS_HELP)

    # Вкладка «Склад» в карточке (проверка шага 37). Без «Убранного» на ней
    # остаётся одна «Прослеживаемость» — блок партий, который ядро показывает
    # только у позиции с учётом партиями. Включат «Партии и серийные номера»
    # — у метизов и красок (учёт количеством, 31 из 753) вкладка открылась бы
    # пустой. Признак «на вкладке есть что показать»: «Убранное» у того, кто
    # смотрит, или учёт партиями у позиции. Зависит от пользователя — не
    # хранится.
    pmk_inventory_tab = fields.Boolean(
        "Вкладка «Склад»", compute="_compute_pmk_inventory_tab")

    # Рейтинг поставщика — в зависимостях: от него _pmk_find_seller выбирает
    # строку, и сменённый рейтинг должен сразу менять цену в открытой форме.
    @api.depends("seller_ids", "seller_ids.price", "seller_ids.discount",
                 "seller_ids.date_start", "seller_ids.date_end",
                 "seller_ids.min_qty", "seller_ids.partner_id",
                 "seller_ids.partner_id.pmk_supplier_rank")
    @api.depends_context("company")
    def _compute_pmk_price(self):
        today = fields.Date.context_today(self)
        for tmpl in self:
            seller = tmpl._pmk_find_seller(today)
            if not seller:
                tmpl.pmk_price_unit = 0.0
                tmpl.pmk_price_ton = 0.0
                tmpl.pmk_price_date = False
                tmpl.pmk_price_supplier_label = NO_PRICE
                tmpl.pmk_price_missing = True
                continue
            tmpl.pmk_price_unit = seller.price_discounted
            tmpl.pmk_price_ton = seller.pmk_price_ton
            tmpl.pmk_price_date = seller.date_start
            tmpl.pmk_price_supplier_label = seller.partner_id.display_name
            tmpl.pmk_price_missing = False

    def _search_pmk_price_missing(self, operator, value):
        """Фильтр «Нет в прайсах» — условие то же, что у _pmk_find_seller.

        Odoo 19 приводит «= True», «!= False» и списки к in / not in с
        OrderedSet (не set: проверка на list/tuple/set его пропускала,
        справочники на этом уже падали — pmk_bridge, reference_link.py),
        поэтому — любая коллекция, кроме строки.
        """
        if operator not in ("in", "not in"):
            return NotImplemented
        if isinstance(value, Collection) and not isinstance(value, str):
            flags = {bool(v) for v in value}
        else:
            flags = {bool(value)}
        if operator == "not in":
            flags = {True, False} - flags
        if flags == {True, False}:
            return []
        if not flags:
            return [("id", "in", [])]
        today = fields.Date.context_today(self)
        priced = self.env["product.supplierinfo"].sudo().search(
            current_domain(today)).product_tmpl_id.ids
        if True in flags:
            return [("id", "not in", priced)]
        return [("id", "in", priced)]

    @api.depends_context("company")
    def _compute_pmk_price_count(self):
        # Поставщики, а не строки: у Металлсервиса на каждую позицию три
        # строки — базовая и два оптовых порога, и «Цены 3» читалось как три
        # предложения. Одним запросом на всю страницу; _origin — у нового
        # товара в форме записи ещё нет (NewId), и строк прайса у него нет.
        ids = self._origin.ids
        counts = {}
        if ids:
            today = fields.Date.context_today(self)
            counts = dict(self.env["product.supplierinfo"]._read_group(
                [("product_tmpl_id", "in", ids)] + current_domain(today),
                ["product_tmpl_id"], ["partner_id:count_distinct"]))
        for tmpl in self:
            tmpl.pmk_price_count = counts.get(tmpl._origin, 0)

    def _pmk_mass_references(self):
        """{id карточки: строка справочника с массой} — одним поиском на
        справочник на всю страницу, а не по одному на карточку."""
        ids = [tmpl._origin.id for tmpl in self if tmpl._origin.id]
        refs = {}
        if ids:
            for model in MASS_REFERENCES:
                for ref in self.env[model].sudo().search([("product_tmpl_id", "in", ids)]):
                    refs[ref.product_tmpl_id.id] = ref
        return refs

    @api.depends("weight")
    def _compute_pmk_mass(self):
        # Справочник — тот же метод, что у расчёта и «Цены, ₽/т»
        # (_pmk_mass_per_unit): своей формулы массы здесь нет.
        refs = self._pmk_mass_references()
        for tmpl in self:
            ref = refs.get(tmpl._origin.id)
            tmpl.pmk_mass_ref = bool(ref)
            tmpl.pmk_mass_unit = ref._pmk_mass_per_unit(tmpl) if ref else tmpl.weight

    @api.depends("tracking")
    @api.depends_context("uid")
    def _compute_pmk_inventory_tab(self):
        removed = self.env.user.has_group("pmk_theme.group_pmk_removed")
        for tmpl in self:
            tmpl.pmk_inventory_tab = removed or tmpl.tracking != "none"

    def action_pmk_open_prices(self):
        """«Цены N»: «Закупки → Цены поставщиков» по этой позиции.

        Отбор — фасетами поиска («Действуют сегодня», «Базовая цена (без
        опта)», «Позиция: …»), а не жёстким доменом: сняв фасет, видно опт,
        историю прайсов или все цены. Базовая цена — по строке на
        поставщика, столько же строк, сколько на кнопке. Если у позиции на
        сегодня одни оптовые строки, фасета «Базовая» нет: расчёт тогда
        берёт оптовую (_pmk_find_seller), и список не должен быть пустым.
        """
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "pmk_purchase.action_supplier_prices")
        context = {
            "visible_product_tmpl_id": False,
            "search_default_current": 1,
            "search_default_product_tmpl_id": self.id,
        }
        today = fields.Date.context_today(self)
        if self.env["product.supplierinfo"].search_count(
                [("product_tmpl_id", "=", self.id), ("min_qty", "=", 0)]
                + current_domain(today), limit=1):
            context["search_default_base_qty"] = 1
        action["context"] = context
        # Подсказка пустого экрана (тема рисует её по help действия):
        # «Цены 0» — позиции нет в прайсах, это сигнал, а не ошибка.
        action["help"] = hint(
            "По выбранным фильтрам цен на эту позицию нет.",
            "Нет действующих — позиции нет в прайсах поставщиков: это сигнал "
            "«в городе нет», а не ошибка. Старые прайсы — снимите фильтр "
            "«Действуют сегодня».",
        )
        return action


class ProductProduct(models.Model):
    _inherit = "product.product"

    # У варианта вес — своё поле (product.product.weight): итог группы в
    # списке вариантов не нужен по той же причине, что у шаблона.
    weight = fields.Float(aggregator=None)

    # Своё, а не от шаблона: у листа масса — вес варианта (марка × габарит),
    # как в расчёте (MetalSheetLink._pmk_mass_per_unit берёт variant.weight).
    # Шаблон с двумя вариантами веса не знает (ядро: ноль), и колонка списка
    # вариантов показала бы ноль там, где расчёт берёт вес варианта.
    pmk_mass_unit = fields.Float(
        "Вес единицы, кг", compute="_compute_pmk_mass_unit", digits=(12, 5),
        help=MASS_HELP)

    @api.depends("weight", "product_tmpl_id")
    def _compute_pmk_mass_unit(self):
        for variant in self:
            tmpl = variant.product_tmpl_id
            variant.pmk_mass_unit = tmpl.pmk_mass_unit if tmpl.pmk_mass_ref else variant.weight

    def action_pmk_open_prices(self):
        """Кнопка «Цены N» в карточке варианта (из строки запроса КП).

        Цены-колонки и счётчик варианту достаются от шаблона делегированием
        (_inherits), как «Прокат (хлыстами)» pmk_bridge.
        """
        self.ensure_one()
        return self.product_tmpl_id.action_pmk_open_prices()
