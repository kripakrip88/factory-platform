# -*- coding: utf-8 -*-
"""Стоимость материала в спецификации: две цены, чистая и фактическая.

ЗАЧЕМ. Завод не торгует металлом, а производит металлоконструкции: цена
поставщика нужна не для перепродажи, а чтобы знать себестоимость изделия.
До этого файла в спецификации не было ни одного денежного поля — только веса.

ДВЕ СТОИМОСТИ, А НЕ ОДНА (решение владельца 23.09.2026). «Чистая» — металл,
который вошёл в деталь. «Фактическая» — металл, который придётся купить, с
отходом. Считать только чистую — занизить себестоимость: на живом замере
лазерного задания в детали ушло 52% купленного листа. Считать только
фактическую — не видеть, где именно теряем.

ВСЕ СУММЫ С НДС (решение владельца 23.09.2026). Поставщики называют цену с
НДС, и внутренний учёт ведётся так же: прайс → чистая → фактическая →
себестоимость → плюс маржа → цена клиенту. Обратного счёта на промежуточных
шагах нет. Это корректно, пока вход и выход по одной ставке: НДС работает
сквозным множителем и одинаково растягивает всю цепочку, поэтому процент
маржи от суммы с НДС равен проценту от суммы без НДС.
⚠️ Появится материал по 0% или 10% (импорт, льготные позиции) — схему
придётся пересматривать, потому что множители перестанут быть одинаковыми.

ПОЧЕМУ ЗДЕСЬ, А НЕ В pmk_calc. Манифест калькулятора обещает независимость от
склада: он должен считать вес и без номенклатуры. Деньги опираются на
product.template и product.supplierinfo, поэтому живут в мосте — как и поле
связи (см. reference_link.py). Не установлен мост — полей просто нет, и
калькулятор работает как раньше.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError

MM_IN_M = 1000.0
KG_IN_TON = 1000.0


class ResPartnerSupplierRank(models.Model):
    """Рейтинг поставщика: кого спрашиваем первым."""

    _inherit = "res.partner"

    # ЗАЧЕМ ОТДЕЛЬНОЕ ПОЛЕ, ЕСЛИ У ODOO ЕСТЬ ПОРЯДОК В ПРАЙСЕ. Ядро выбирает
    # поставщика по полю sequence в строке прайса (product.supplierinfo), но
    # наш загрузчик занял его номером уровня объёма — 1, 2, 3 по порогам
    # закупки. Пока поставщик один, это незаметно; появится второй — и
    # «назначенным» станет тот, у кого строка оказалась дешевле или раньше
    # заведена, то есть случайный.
    #
    # Рейтинг на контрагенте отвечает на другой вопрос: не «какая строка
    # прайса», а «с кем мы вообще работаем». Меньше — раньше в очереди.
    pmk_supplier_rank = fields.Integer(
        "Рейтинг поставщика", default=100,
        help="Кого спрашиваем первым при расчёте себестоимости. "
             "Меньше — выше приоритет. Одинаковый рейтинг — берётся тот, "
             "у кого цена на нужный объём ниже.")


class MetalSpecCost(models.Model):
    """Документ: настройки расчёта и итоги в деньгах."""

    _inherit = "pmk.metal.spec"

    currency_id = fields.Many2one(
        "res.currency", "Валюта", required=True, readonly=True,
        default=lambda self: self.env.company.currency_id,
        # Валюта нужна не для выбора — рубль единственный, — а потому что без
        # неё не работает тип Monetary и итог «сумма по колонке» в списке.
        help="Рубли. Поле техническое: без валюты денежные суммы не считаются.")

    # ⚠️ БЕЗ ДОМЕНА ПО ПРИЗНАКУ «ПОСТАВЩИК ПРАЙСОВ». Такой признак есть, но
    # объявлен в pmk_purchase, а тот зависит от модуля закупок Odoo и от нашей
    # темы оформления. Мост — низкоуровневый слой: тянуть в него тему ради
    # одного домена нельзя, иначе установка калькулятора начнёт требовать
    # половину системы. Отбор оставляем пользователю: список поставщиков он
    # знает лучше фильтра.
    supplier_id = fields.Many2one(
        "res.partner", "Поставщик для цен",
        help="Чьи цены берём в расчёт. Пусто — берётся поставщик с лучшим "
             "рейтингом из тех, у кого есть цена на нужную позицию.")

    price_date = fields.Date(
        "Цены на дату", default=fields.Date.context_today,
        help="На какую дату смотрим прайсы. Отдельно от даты документа: "
             "спецификацию заводят задним числом, а цены нужны свежие.")

    # ─── Использование металла ────────────────────────────────────────────
    #
    # Владелец: «коэффициент использования от 50% до 97% бывает». Одним числом
    # это не описать — доля зависит от того, как деталь ложится на лист, а не
    # от материала. Поэтому здесь стоит значение ПО УМОЛЧАНИЮ для документа, а
    # в строке его можно переопределить.
    #
    # ⚠️ ПО УМОЛЧАНИЮ 100%: СЕБЕСТОИМОСТЬ СЧИТАЕТСЯ ПО ЧИСТОМУ ВЕСУ.
    # Решение владельца 24.09.2026: «в расчете себестоимости будем
    # использовать вес заготовки пока что чистый по нашему справочнику,
    # перемножать на цену поставщика».
    #
    # Причина — не упрощение, а разделение задач. Сколько металла реально
    # купить, зависит от раскладки, а раскладку делает технолог: у одного
    # заказа листы разной толщины и разного габарита, и один коэффициент на
    # документ этого не описывает. Поэтому отход считается ОТДЕЛЬНО,
    # предварительным расчётом металла, и проходит через технолога перед
    # закупкой. В КП идёт чистый вес — предсказуемое число, за которое
    # менеджер отвечает сам.
    #
    # Поле оставлено: когда накопится статистика по переделам, сюда вернётся
    # осмысленная доля. Менять его можно и сейчас, но это ручное действие.
    utilization_sheet_pct = fields.Float(
        "Использование листа, %", default=100.0, digits=(5, 1),
        help="Сколько процентов купленного листа уходит в заготовки — по тем "
             "габаритам, которые введены в строках. Круг Ø100, записанный как "
             "квадрат 100×100, уже содержит запас на форму: замерные 52% "
             "относятся к чистым деталям, а не к габаритам, и здесь число "
             "должно быть выше. Меняйте по месту: в строке задаётся своё.")

    utilization_linear_pct = fields.Float(
        "Использование проката, %", default=100.0, digits=(5, 1),
        help="По умолчанию 100%: отход хлыста здесь не учтён. Точную долю "
             "даёт раскрой сортамента, когда он посчитан по заказу.")

    total_cost_clean = fields.Monetary(
        "Металл в деталях", compute="_compute_cost_totals", store=True,
        help="Стоимость металла, который вошёл в детали. С НДС.")
    total_cost_fact = fields.Monetary(
        "Металл к закупке", compute="_compute_cost_totals", store=True,
        help="Стоимость металла, который придётся купить, с отходом. С НДС.")
    total_cost_waste = fields.Monetary(
        "Цена раскроя", compute="_compute_cost_totals", store=True,
        help="Разница между закупкой и тем, что вошло в детали. "
             "Это не ошибка расчёта, а стоимость отхода.")
    total_weight_fact = fields.Float(
        "Купить металла, кг", compute="_compute_cost_totals", store=True, digits=(12, 3))
    total_weight_fact_t = fields.Float(
        "Купить металла, т", compute="_compute_cost_totals", store=True, digits=(12, 4))

    no_price_count = fields.Integer(
        "Позиций без цены", compute="_compute_cost_totals", store=True)
    price_incomplete = fields.Boolean(
        "Расчёт неполный", compute="_compute_cost_totals", store=True,
        help="Хотя бы у одной позиции нет цены — итог занижен.")

    @api.depends(
        "product_ids.cost_clean_total",
        "product_ids.cost_fact_total",
        "product_ids.weight_fact_total",
        "product_ids.no_price_count",
        "product_ids.qty",
    )
    def _compute_cost_totals(self):
        for spec in self:
            spec.total_cost_clean = sum(spec.product_ids.mapped("cost_clean_total"))
            spec.total_cost_fact = sum(spec.product_ids.mapped("cost_fact_total"))
            spec.total_cost_waste = spec.total_cost_fact - spec.total_cost_clean
            spec.total_weight_fact = sum(spec.product_ids.mapped("weight_fact_total"))
            spec.total_weight_fact_t = spec.total_weight_fact / KG_IN_TON
            spec.no_price_count = sum(spec.product_ids.mapped("no_price_count"))
            spec.price_incomplete = spec.no_price_count > 0

    def action_refresh_prices(self):
        """Перечитать цены из прайсов.

        Отдельная кнопка, а не автоматический пересчёт при каждом изменении
        прайса: спецификация — это расчёт НА ДАТУ. Если бы цены подтягивались
        сами, вчерашнее КП молча меняло бы сумму после заливки нового прайса,
        и разговор с клиентом расходился бы с документом.
        """
        lines = self.mapped("product_ids.line_ids")
        # Снимаем ручные правки цены: пользователь нажал «перечитать» —
        # значит хочет то, что в прайсе сейчас.
        lines.write({"price_unit": 0.0})
        lines._compute_price_from_supplier()
        return True


class MetalSpecProductCost(models.Model):
    """Изделие: итоги в деньгах. Количество изделий умножается ЗДЕСЬ."""

    _inherit = "pmk.metal.spec.product"

    currency_id = fields.Many2one(
        related="spec_id.currency_id", store=True, readonly=True, string="Валюта")

    cost_clean_one = fields.Monetary(
        "Металл в изделии", compute="_compute_product_cost", store=True)
    cost_clean_total = fields.Monetary(
        "Металл во всех", compute="_compute_product_cost", store=True)
    cost_fact_one = fields.Monetary(
        "Закупка на изделие", compute="_compute_product_cost", store=True)
    cost_fact_total = fields.Monetary(
        "Закупка на все", compute="_compute_product_cost", store=True)
    weight_fact_one = fields.Float(
        "Купить на изделие, кг", compute="_compute_product_cost", store=True, digits=(12, 3))
    weight_fact_total = fields.Float(
        "Купить на все, кг", compute="_compute_product_cost", store=True, digits=(12, 3))
    no_price_count = fields.Integer(
        "Позиций без цены", compute="_compute_product_cost", store=True)

    # Зависимости перечислены по ЧЕТЫРЁМ отфильтрованным наборам, а не по
    # line_ids: на этом уже обжигались при расчёте веса — правка во вкладке
    # не доходила до верхнего уровня, цепочка рвалась на первом звене.
    @api.depends(
        "qty",
        "line_linear_ids.cost_clean_total", "line_linear_ids.cost_fact_total",
        "line_linear_ids.weight_fact_total", "line_linear_ids.price_state",
        "line_sheet_ids.cost_clean_total", "line_sheet_ids.cost_fact_total",
        "line_sheet_ids.weight_fact_total", "line_sheet_ids.price_state",
        "line_fastener_ids.cost_clean_total", "line_fastener_ids.cost_fact_total",
        "line_fastener_ids.weight_fact_total", "line_fastener_ids.price_state",
        "line_paint_ids.cost_clean_total", "line_paint_ids.cost_fact_total",
        "line_paint_ids.weight_fact_total", "line_paint_ids.price_state",
    )
    def _compute_product_cost(self):
        for product in self:
            lines = (product.line_linear_ids | product.line_sheet_ids
                     | product.line_fastener_ids | product.line_paint_ids)
            qty = product.qty or 0
            product.cost_clean_one = sum(lines.mapped("cost_clean_total"))
            product.cost_fact_one = sum(lines.mapped("cost_fact_total"))
            product.weight_fact_one = sum(lines.mapped("weight_fact_total"))
            product.cost_clean_total = product.cost_clean_one * qty
            product.cost_fact_total = product.cost_fact_one * qty
            product.weight_fact_total = product.weight_fact_one * qty
            product.no_price_count = len(lines.filtered(
                lambda l: l.price_state not in ("ok", "empty")))


class MetalSpecLineCost(models.Model):
    """Деталь: цена за единицу, снимок прайса и две стоимости."""

    _inherit = "pmk.metal.spec.line"

    currency_id = fields.Many2one(
        related="spec_id.currency_id", store=True, readonly=True, string="Валюта")

    # ─── Откуда цена ──────────────────────────────────────────────────────
    price_state = fields.Selection(
        [("empty", "Позиция не выбрана"),
         ("ok", "Цена есть"),
         ("no_link", "Нет карточки товара"),
         ("no_price", "Нет цены в прайсах"),
         ("no_mass", "Неизвестна масса"),
         ("not_material", "Не материал")],
        "Состояние цены", compute="_compute_price_from_supplier", store=True,
        default="empty",
        help="Почему у строки нет стоимости. «Нет цены» — прайс не содержит "
             "эту позицию; такая строка считается нулём, и итог занижен.")

    price_partner_id = fields.Many2one(
        "res.partner", "Поставщик цены", compute="_compute_price_from_supplier",
        store=True, readonly=True)
    price_date_used = fields.Date(
        "Прайс от", compute="_compute_price_from_supplier", store=True, readonly=True,
        help="Дата начала действия строки прайса, из которой взята цена.")
    price_tier = fields.Integer(
        "Уровень объёма", compute="_compute_price_from_supplier", store=True, readonly=True,
        help="Какой порог закупки сработал: 1 — базовый, дальше оптовые.")

    # ⚠️ СНИМОК СКАЛЯРНЫЙ, А НЕ ССЫЛКОЙ НА СТРОКУ ПРАЙСА. Загрузчик при
    # повторной заливке ПЕРЕЗАПИСЫВАЕТ запись того же дня, поэтому ссылка
    # через месяц покажет другую цену. Ссылка ниже — только «посмотреть», ею
    # нельзя считать.
    price_source_id = fields.Many2one(
        "product.supplierinfo", "Строка прайса", readonly=True,
        help="Только для просмотра: содержимое строки меняется при заливке "
             "нового прайса.")

    price_unit = fields.Float(
        "Цена за единицу", compute="_compute_price_from_supplier", store=True,
        readonly=False, digits=(16, 4),
        help="С НДС, за единицу учёта позиции: прокат — за метр, лист и "
             "метиз — за штуку, краска — за килограмм. Можно задать вручную.")
    price_kg = fields.Float(
        "Цена за кг", compute="_compute_price_from_supplier", store=True,
        readonly=True, digits=(12, 4))
    price_ton = fields.Float(
        "Цена за тонну", compute="_compute_price_from_supplier", store=True,
        readonly=True, digits=(12, 2))

    # ─── Использование и вес к закупке ────────────────────────────────────
    utilization_pct = fields.Float(
        "Использование, %", compute="_compute_utilization", store=True,
        readonly=False, digits=(5, 1),
        help="Сколько процентов купленного металла уходит в деталь. "
             "Подставляется из документа, меняется по месту.")

    weight_fact_one = fields.Float(
        "Купить на шт, кг", compute="_compute_cost", store=True, digits=(12, 3))
    weight_fact_total = fields.Float(
        "Купить в изделии, кг", compute="_compute_cost", store=True, digits=(12, 3))

    cost_clean_one = fields.Monetary(
        "Металл в детали", compute="_compute_cost", store=True)
    cost_clean_total = fields.Monetary(
        "Металл в изделии", compute="_compute_cost", store=True)
    cost_fact_one = fields.Monetary(
        "Закупка на шт", compute="_compute_cost", store=True)
    cost_fact_total = fields.Monetary(
        "Закупка в изделии", compute="_compute_cost", store=True)

    # ─────────────────────────────────────────────────────────────────────
    def _cost_product(self):
        """Карточка товара, соответствующая позиции строки."""
        self.ensure_one()
        source = {
            "linear": self.profile_id,
            "sheet": self.sheet_id,
            "fastener": self.fastener_id,
            "paint": self.paint_id,
        }.get(self.calc_mode)
        return source.product_tmpl_id if source else self.env["product.template"]

    def _cost_mass_unit(self, tmpl):
        """Сколько килограммов в единице, за которую назначена цена.

        ⚠️ МАССУ БЕРЁМ ИЗ СПРАВОЧНИКА, А НЕ С КАРТОЧКИ. На карточке вес
        хранится с точностью «Вес товара» — два знака, и любое сохранение
        превращает 0,0985 кг болта в 0,10 (плюс полтора процента к цене
        килограмма). В справочнике лежит то самое число, которым посчитан
        вес детали, поэтому «по метрам» и «по весу» совпадают арифметически,
        а не случайно.

        Исключение — лист: он продаётся целым листом, и масса нужна именно
        листа, а не квадратного метра. Её берём с карточки: там сотни
        килограммов, и два знака безвредны.
        """
        self.ensure_one()
        if self.calc_mode == "linear":
            return self.profile_id.mass_per_meter
        if self.calc_mode == "sheet":
            return tmpl.weight
        if self.calc_mode == "fastener":
            return self.fastener_id.weight_kg
        if self.calc_mode == "paint":
            # Краска продаётся килограммами: цена килограмма и есть цена
            # единицы, переводить нечего.
            return 1.0
        return 0.0

    @api.depends("calc_mode", "profile_id", "sheet_id", "fastener_id", "paint_id",
                 "spec_id.price_date", "spec_id.supplier_id")
    def _compute_price_from_supplier(self):
        """Одна дверь к цене: прайс → цена за единицу → цена за килограмм.

        ⚠️ В depends НЕТ строк прайса. Иначе заливка нового прайса молча
        переписала бы суммы во всех старых спецификациях, включая уже
        отправленные клиенту. Обновление — только кнопкой «Перечитать цены».
        """
        for line in self:
            line._reset_price_fields()
            tmpl = line._cost_product()

            if not line._cost_position():
                line.price_state = "empty"
                continue
            if line.calc_mode == "paint" and line.paint_id.pmk_not_material:
                # Услуга, а не материал: цена килограмма ей не соответствует.
                line.price_state = "not_material"
                continue
            if not tmpl:
                line.price_state = "no_link"
                continue

            mass_unit = line._cost_mass_unit(tmpl)
            if not mass_unit:
                line.price_state = "no_mass"
                continue

            seller = line._cost_find_seller(tmpl)
            if not seller:
                line.price_state = "no_price"
                continue

            if seller.currency_id != line.spec_id.currency_id:
                # Громкий отказ вместо тихой конвертации: без курса пересчёт
                # прошёл бы один к одному и ошибку заметили бы в деньгах.
                raise UserError(
                    "Цена поставщика %s указана в валюте %s, а расчёт ведётся в %s. "
                    "Пересчёт валют не делаем — заведите цену в рублях."
                    % (seller.partner_id.display_name, seller.currency_id.name,
                       line.spec_id.currency_id.name))

            price = seller.price_discounted
            if not line.price_unit:
                line.price_unit = price
            line.price_state = "ok"
            line.price_partner_id = seller.partner_id
            line.price_date_used = seller.date_start
            line.price_tier = seller.sequence
            line.price_source_id = seller
            line.price_kg = line.price_unit / mass_unit
            line.price_ton = line.price_kg * KG_IN_TON

    def _cost_position(self):
        """Выбрана ли вообще позиция в строке."""
        self.ensure_one()
        return {
            "linear": self.profile_id,
            "sheet": self.sheet_id,
            "fastener": self.fastener_id,
            "paint": self.paint_id,
        }.get(self.calc_mode)

    def _cost_find_seller(self, tmpl):
        """Строка прайса: у заданного поставщика или у лучшего по рейтингу."""
        self.ensure_one()
        date = self.spec_id.price_date or fields.Date.context_today(self)
        sellers = tmpl.seller_ids.filtered(
            lambda s: (not s.date_start or s.date_start <= date)
            and (not s.date_end or s.date_end >= date))
        if not sellers:
            return False

        chosen = self.spec_id.supplier_id
        if chosen:
            sellers = sellers.filtered(lambda s: s.partner_id == chosen)
            if not sellers:
                return False
        else:
            # Рейтинг решает, чьи цены берём; при равном рейтинге — кто
            # дешевле. Сортировка по контрагенту, а не по строке прайса:
            # поле sequence в строке занято номером уровня объёма.
            best_rank = min(sellers.mapped("partner_id.pmk_supplier_rank") or [0])
            sellers = sellers.filtered(
                lambda s: s.partner_id.pmk_supplier_rank == best_rank)

        # Внутри поставщика берём базовый уровень: на этапе КП объём закупки
        # ещё не определён, и обещать оптовую цену рано.
        base = sellers.filtered(lambda s: not s.min_qty)
        return (base or sellers).sorted(lambda s: (s.price_discounted, s.id))[:1]

    def _reset_price_fields(self):
        self.ensure_one()
        self.price_state = "empty"
        self.price_partner_id = False
        self.price_date_used = False
        self.price_tier = 0
        self.price_source_id = False
        self.price_kg = 0.0
        self.price_ton = 0.0

    @api.depends("calc_mode", "spec_id.utilization_sheet_pct",
                 "spec_id.utilization_linear_pct")
    def _compute_utilization(self):
        for line in self:
            if line.utilization_pct:
                # Руками поставленное значение не перетираем: подставляем
                # только в пустую строку.
                continue
            spec = line.spec_id
            if line.calc_mode == "sheet":
                line.utilization_pct = spec.utilization_sheet_pct or 100.0
            elif line.calc_mode == "linear":
                line.utilization_pct = spec.utilization_linear_pct or 100.0
            else:
                # Метиз и краска покупаются ровно столько, сколько нужно:
                # отхода у них нет.
                line.utilization_pct = 100.0

    @api.depends("price_unit", "price_kg", "price_state", "utilization_pct",
                 "weight_one", "weight_total", "length_mm", "qty", "calc_mode")
    def _compute_cost(self):
        for line in self:
            clean_one = 0.0
            if line.price_state == "ok":
                if line.calc_mode == "linear":
                    clean_one = line.price_unit * (line.length_mm / MM_IN_M)
                elif line.calc_mode == "fastener":
                    clean_one = line.price_unit
                else:
                    # Лист и краска считаются через килограммы: у листа цена
                    # назначена за целый лист, у краски — сразу за килограмм.
                    clean_one = line.price_kg * line.weight_one

            share = (line.utilization_pct or 100.0) / 100.0
            qty = line.qty or 0
            fact_one = (clean_one / share) if share else 0.0
            weight_fact = (line.weight_one / share) if share else 0.0

            # ⚠️ ИТОГ СЧИТАЕТСЯ ОТ ЛОКАЛЬНОГО ЧИСЛА, А НЕ ОТ ПОЛЯ. Monetary
            # округляет значение до копеек при записи, и `line.cost_fact_one`
            # сразу после присваивания вернёт уже округлённое. Умножение
            # такого числа на количество разъезжается с чистой стоимостью:
            # замер на живой строке (850 мм × 10 шт) дал 2909,10 против
            # 2909,14 — четыре копейки из ниоткуда.
            line.cost_clean_one = clean_one
            line.cost_clean_total = clean_one * qty
            line.cost_fact_one = fact_one
            line.cost_fact_total = fact_one * qty
            line.weight_fact_one = weight_fact
            line.weight_fact_total = weight_fact * qty


class PaintCoatingNotMaterial(models.Model):
    """Покрытие, которое не наносят у себя, а заказывают на стороне."""

    _inherit = "pmk.paint.coating"

    # Горячее цинкование — ванна на стороне, а не краска из ведра. Считать
    # его по формуле «вес × цена килограмма» нельзя: цена килограмма цинка не
    # равна цене цинкования. Признак закрывает такую строку от расчёта, пока
    # услуга не заведена отдельно.
    pmk_not_material = fields.Boolean(
        "Не материал (услуга)", default=False,
        help="Работа подрядчика, а не покупаемый материал. Стоимость по "
             "весу для такой строки не считается.")
