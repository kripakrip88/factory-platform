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

    # ─── Что изменилось после пересчёта ───────────────────────────────────
    #
    # ЗАЧЕМ. Пересчёт по новому прайсу меняет сумму молча: менеджер нажал
    # кнопку, число поменялось, и на глаз не видно ни что оно поменялось, ни
    # насколько. А разница бывает большой: сентябрьский прайс поднял уголок на
    # 38%, арматуру на 27%, и при этом трубы подешевели.
    #
    # Поэтому запоминаем сумму ДО пересчёта и показываем разницу. Цифра живёт
    # до следующего пересчёта — это не история цен, а ответ на вопрос «что
    # изменилось сейчас».
    cost_prev_total = fields.Monetary(
        "Закупка до пересчёта", readonly=True, copy=False,
        help="Сколько стоил металл по прежним ценам. Заполняется кнопкой "
             "«Перечитать цены».")
    cost_change_pct = fields.Float(
        "Изменение, %", readonly=True, digits=(6, 1), copy=False,
        help="На сколько изменилась стоимость металла после пересчёта. "
             "Плюс — подорожало.")
    price_changed = fields.Boolean(
        "Цены изменились", readonly=True, copy=False,
        help="После последнего пересчёта сумма стала другой.")
    # Дата пересчёта нужна, чтобы плашка не врала по смыслу. Она живёт в
    # документе до следующего пересчёта, и через неделю «металл подорожал»
    # читается как новость сегодняшнего дня. С датой это уже факт, а не тревога.
    price_refreshed_on = fields.Datetime(
        "Цены перечитаны", readonly=True, copy=False,
        help="Когда последний раз нажимали «Перечитать цены».")

    # Снимок «стало» нужен, чтобы плашка не врала после правки состава.
    # Без него на экране соседствуют замороженное «было» и живой итог: добавил
    # деталь — и текст «подорожал на 6%» стоит над числами, которые показывают
    # совсем другое. Сравнивая снимок с текущим итогом, видно, что расчёт
    # трогали после пересчёта, и сигнал гасится.
    cost_new_total = fields.Monetary(
        "Закупка после пересчёта", readonly=True, copy=False)
    cost_change_abs_pct = fields.Float(
        "Изменение по модулю, %", compute="_compute_change_labels",
        digits=(6, 1),
        help="Знак несёт текст «подорожал/подешевел»: «подешевел на −5,7%» "
             "читается как двойное отрицание.")
    cost_change_label = fields.Char(
        "Изм., %", compute="_compute_change_labels",
        help="Для списка: прочерк, пока расчёт не пересчитывали. Ноль в этой "
             "колонке читается как «проверено, изменений нет».")
    price_signal_stale = fields.Boolean(
        "Сигнал устарел", compute="_compute_change_labels",
        help="Состав или количества правили после пересчёта — цифры «было» и "
             "«стало» больше не про этот расчёт.")

    # Позиции, потерявшие цену при пересчёте, — это НЕ удешевление.
    # Без отдельного счётчика выпавшая из прайса позиция попадает в общий
    # итог нулём, и документ радостно сообщает «металл подешевел на 100%».
    price_lost_count = fields.Integer(
        "Позиций выпало из прайса", readonly=True, copy=False,
        help="Сколько позиций потеряли цену при последнем пересчёте.")

    # ─── Вкладка «Цены»: что изменилось и за какой период ─────────────────
    #
    # Замысел владельца 25.09.2026: «мониторить что из цен изменилось и за
    # какой период». Кнопка отвечает только на вопрос «изменилось ли сейчас»,
    # а прайсы лежат рядами по датам — значит можно сравнить с любым из них,
    # а не только с предыдущим нажатием.
    #
    # Всё считается на лету, ничего не хранится: история уже есть в прайсах,
    # дублировать её в документе значило бы заводить второй источник правды.
    price_line_ids = fields.One2many(
        "pmk.metal.spec.line", "spec_id", string="Позиции с ценами")

    compare_price_date = fields.Date(
        "Сравнить с ценами на", compute="_compute_compare_date",
        store=True, readonly=False,
        help="С каким прайсом сравниваем текущие цены. По умолчанию — "
             "предыдущий по дате.")
    latest_price_date = fields.Date(
        "Последний прайс", compute="_compute_price_freshness",
        help="Самая свежая дата прайса по позициям этого расчёта.")
    price_stale = fields.Boolean(
        "Есть прайс свежее", compute="_compute_price_freshness",
        help="Цены взяты на дату старее последнего прайса: пересчёт по "
             "текущей дате ничего не изменит, потому что смотрит в архив.")

    compare_total_cost = fields.Monetary(
        "Было по тому прайсу", compute="_compute_compare_totals")
    compare_delta = fields.Monetary(
        "Разница", compute="_compute_compare_totals")
    compare_pct = fields.Float(
        "Разница, %", compute="_compute_compare_totals", digits=(6, 1))

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

    def _price_dates(self):
        """Даты прайсов, которые вообще касаются позиций этого расчёта.

        Смотрим только по своим позициям, а не по всей базе: расчёт из одного
        листа не должен реагировать на заливку прайса по метизам.
        """
        self.ensure_one()
        tmpls = self.env["product.template"]
        for line in self.price_line_ids:
            tmpls |= line._cost_product()
        dates = tmpls.mapped("seller_ids.date_start")
        return sorted({d for d in dates if d})

    @api.depends("price_date", "price_refreshed_on")
    def _compute_compare_date(self):
        """По умолчанию сравниваем с прайсом, который действовал до нынешнего."""
        for spec in self:
            if spec.compare_price_date:
                continue
            base = spec.price_date or fields.Date.context_today(spec)
            earlier = [d for d in spec._price_dates() if d < base]
            spec.compare_price_date = earlier[-1] if earlier else False

    @api.depends("price_date", "price_line_ids")
    def _compute_price_freshness(self):
        """Есть ли прайс свежее того, на который смотрит расчёт.

        ⚠️ ЭТО НЕ ПРИДИРКА, А ТИХИЙ ОТКАЗ. Дата цен ставится при создании и
        сама не двигается, а выбор строки прайса идёт по ней. Значит после
        заливки нового прайса кнопка «Перечитать цены» на старом расчёте
        честно перечитает СТАРЫЕ цены и промолчит — а молчание читается как
        «нас не задело». Поэтому о свежем прайсе говорим явно.
        """
        for spec in self:
            dates = spec._price_dates()
            spec.latest_price_date = dates[-1] if dates else False
            spec.price_stale = bool(
                spec.latest_price_date and spec.price_date
                and spec.latest_price_date > spec.price_date)

    @api.depends("price_line_ids.cost_compare_delta", "total_cost_fact")
    def _compute_compare_totals(self):
        for spec in self:
            delta = sum(spec.price_line_ids.mapped("cost_compare_delta"))
            spec.compare_delta = delta
            was = spec.total_cost_fact - delta
            spec.compare_total_cost = was
            spec.compare_pct = (delta / was * 100.0) if was else 0.0

    @api.depends("cost_change_pct", "price_refreshed_on", "cost_new_total",
                 "total_cost_fact", "price_changed")
    def _compute_change_labels(self):
        for spec in self:
            spec.cost_change_abs_pct = abs(spec.cost_change_pct)
            # Разница в копейку — это округление Monetary, а не правка состава.
            spec.price_signal_stale = bool(
                spec.price_refreshed_on
                and abs(spec.total_cost_fact - spec.cost_new_total) >= 0.01)
            if not spec.price_refreshed_on:
                spec.cost_change_label = "—"
            elif spec.price_signal_stale:
                spec.cost_change_label = "устарело"
            elif not spec.price_changed:
                spec.cost_change_label = "без изменений"
            else:
                sign = "+" if spec.cost_change_pct > 0 else "−"
                spec.cost_change_label = "%s%.1f%%" % (
                    sign, abs(spec.cost_change_pct))

    def action_use_latest_prices(self):
        """Перейти на самый свежий прайс и пересчитать.

        Отдельной кнопкой, а не внутри «Перечитать цены»: расчёт НА ДАТУ —
        осмысленная вещь (по нему разговаривали с клиентом), и молча двигать
        дату нельзя. Здесь пользователь говорит это явно.
        """
        for spec in self:
            if spec.latest_price_date:
                spec.price_date = spec.latest_price_date
        return self.action_refresh_prices()

    def action_refresh_prices(self):
        """Перечитать цены из прайсов.

        Отдельная кнопка, а не автоматический пересчёт при каждом изменении
        прайса: спецификация — это расчёт НА ДАТУ. Если бы цены подтягивались
        сами, вчерашнее КП молча меняло бы сумму после заливки нового прайса,
        и разговор с клиентом расходился бы с документом.
        """
        for spec in self:
            was = spec.total_cost_fact
            was_no_price = spec.no_price_count
            lines = spec.mapped("product_ids.line_ids")
            # Снимок цен ДО обнуления: после него прежнего значения уже не
            # узнать, а именно оно отвечает на вопрос «из-за чего подорожало».
            for line in lines:
                line.price_prev_unit = line.price_unit
            # Снимаем ручные правки цены: пользователь нажал «перечитать» —
            # значит хочет то, что в прайсе сейчас.
            lines.write({"price_unit": 0.0})
            lines._compute_price_from_supplier()
            for line in lines:
                was_unit = line.price_prev_unit
                line.price_change_pct = (
                    (line.price_unit - was_unit) / was_unit * 100.0
                    if was_unit else 0.0)
            # Пересчёт полей идёт отложенно, а сумму надо сравнить сразу —
            # поэтому читаем её заново, сбросив кэш.
            spec.invalidate_recordset(["total_cost_fact", "no_price_count"])
            now = spec.total_cost_fact

            spec.cost_prev_total = was
            spec.cost_new_total = now
            spec.price_refreshed_on = fields.Datetime.now()
            # Позиции, потерявшие цену, — отдельная новость. Без этого счётчика
            # исчезновение позиции из прайса выглядит как удешевление: сумма
            # упала, значит «подешевело».
            spec.price_lost_count = max(0, spec.no_price_count - was_no_price)
            # ПЕРВЫЙ ПЕРЕСЧЁТ — НЕ ИЗМЕНЕНИЕ. Когда прежней суммы не было
            # (расчёт только завели, цены не подтягивались), сравнивать не с
            # чем: «подорожало с нуля» — неправда, металл просто впервые
            # посчитан. Сигналим только когда было с чем сравнить.
            spec.price_changed = bool(was) and abs(now - was) >= 0.01
            spec.cost_change_pct = ((now - was) / was * 100.0) if was else 0.0
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

    # Изменение по строке: сумма документа говорит «стало дороже», а строка —
    # из-за чего именно. Без этого менеджер видит рост и не знает, спорить с
    # поставщиком по уголку или по листу.
    price_prev_unit = fields.Float(
        "Цена до пересчёта", readonly=True, digits=(16, 4), copy=False)

    # ─── Сравнение с другим прайсом (вкладка «Цены») ──────────────────────
    #
    # Считается на лету и не хранится: это не свойство строки, а ответ на
    # вопрос «что было на выбранную дату». Смени дату сравнения — ответ
    # другой, и хранить его негде.
    price_compare_unit = fields.Float(
        "Было", compute="_compute_price_compare", digits=(16, 4),
        help="Цена той же позиции по прайсу, с которым сравниваем.")
    price_compare_pct = fields.Float(
        "Изм., %", compute="_compute_price_compare", digits=(6, 1))
    cost_compare_delta = fields.Monetary(
        "В сумме, ₽", compute="_compute_price_compare",
        help="На сколько подорожала эта позиция в деньгах ЭТОГО расчёта. "
             "Процент говорит, что подорожало, рубли — насколько это важно: "
             "лист вырос слабее трубы, а в деньгах — в тридцать раз сильнее.")
    price_compare_state = fields.Selection(
        [("ok", "Есть обе цены"),
         ("no_old", "Не было в том прайсе"),
         ("no_new", "Выпала из прайса"),
         ("none", "Цены нет")],
        "Состояние сравнения", compute="_compute_price_compare")
    price_change_pct = fields.Float(
        "Изменение цены, %", readonly=True, digits=(6, 1), copy=False)

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
                # Прежняя цена запоминается ровно в тот момент, когда её
                # заменяют: кнопка обнуляет price_unit, и здесь ещё доступно
                # то, что стояло до обнуления — через снимок в price_prev_unit
                # его пишет сама кнопка (см. action_refresh_prices).
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

    @api.depends("price_unit", "price_state", "cost_fact_total",
                 "spec_id.compare_price_date", "spec_id.supplier_id",
                 "profile_id", "sheet_id", "fastener_id", "paint_id")
    def _compute_price_compare(self):
        """Цена этой позиции по прайсу, с которым сравниваем.

        Стоимость линейна по цене единицы, поэтому вклад в сумму считается
        долей, а не пересчётом всей цепочки: cost × (новая − старая) / новая.
        Так число совпадает с итогом документа до копейки, и не приходится
        второй раз воспроизводить правила расчёта массы и количества.
        """
        for line in self:
            date = line.spec_id.compare_price_date
            tmpl = line._cost_product()
            seller = line._cost_find_seller(tmpl, date=date) if (date and tmpl) else False
            old = seller.price_discounted if seller else 0.0
            new = line.price_unit if line.price_state == "ok" else 0.0

            line.price_compare_unit = old
            if old and new:
                line.price_compare_state = "ok"
                line.price_compare_pct = (new - old) / old * 100.0
                line.cost_compare_delta = line.cost_fact_total * (new - old) / new
            elif old and not new:
                # Позиция была в прайсе и пропала. Деньги «сэкономлены» только
                # на бумаге: металл всё равно придётся купить, просто цена
                # теперь неизвестна.
                line.price_compare_state = "no_new"
                line.price_compare_pct = 0.0
                line.cost_compare_delta = 0.0
            elif new and not old:
                line.price_compare_state = "no_old"
                line.price_compare_pct = 0.0
                line.cost_compare_delta = 0.0
            else:
                line.price_compare_state = "none"
                line.price_compare_pct = 0.0
                line.cost_compare_delta = 0.0

    def _cost_find_seller(self, tmpl, date=None):
        """Строка прайса: у заданного поставщика или у лучшего по рейтингу.

        Дата приходит параметром, чтобы тем же кодом отвечать на вопрос «а
        сколько это стоило в июне»: вкладка «Цены» сравнивает два прайса, и
        расхождение в правилах выбора поставщика сделало бы сравнение
        бессмысленным — разница показывала бы не цену, а другой алгоритм.
        """
        self.ensure_one()
        date = date or self.spec_id.price_date or fields.Date.context_today(self)
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
