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
from markupsafe import Markup

from odoo.tools import format_amount
from odoo.exceptions import UserError

from ..tools import spec_text

MM_IN_M = 1000.0
KG_IN_TON = 1000.0


def _money(value):
    """Сумма с разрядами и запятой — как её пишут в документах завода."""
    return "{:,.2f}".format(value).replace(",", "\u00a0").replace(".", ",")


class SupplierInfoBarLength(models.Model):
    """Длина хлыста в строке прайса.

    ⚠️ ЭТО НЕ СВОЙСТВО СОРТАМЕНТА, А СВОЙСТВО ПОЗИЦИИ У ПОСТАВЩИКА. Уголок
    бывает и 6, и 9, и 12 метров — в сентябрьском прайсе Металлсервиса 28
    позиций уголка по 12 м, 10 по 6 м и 4 по 9 м. Поэтому «стандартную длину»
    нельзя ни зашить константой, ни спросить у справочника: правильный ответ
    знает только прайс той позиции, которую реально купят.

    Загрузчик читал эту длину и раньше — она нужна, чтобы посчитать массу
    метра, — но выбрасывал. Теперь сохраняем: по ней раскрой сортамента
    считает, сколько хлыстов взять.
    """

    _inherit = "product.supplierinfo"

    # aggregator=None (разбор UX, шаг 25): в списке «Цены поставщиков»,
    # сгруппированном по поставщику, длины хлыстов складывались бы в строке
    # группы — число, которое ничего не значит (как массы в справочниках,
    # шаг 24).
    pmk_bar_length_mm = fields.Float(
        "Длина хлыста, мм", digits=(10, 1), aggregator=None,
        help="Как поставщик продаёт эту позицию. Пусто — в прайсе длины не "
             "было (лист, метизы, мотки).")


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
    # ─── От кого выставляем ───────────────────────────────────────────────
    #
    # Решение владельца 27.09.2026: «в документах должен идти Чулков В.В.
    # однозначно, можно сделать вообще выпадашку для выбора… чтоб если заведём
    # потом ещё компанию, можно было менять, от кого выставляем предложение».
    #
    # Организация сейчас одна, но поле заводим сразу: когда появится вторая,
    # менять придётся печатные формы и заказы, а не спешно доделывать выбор.
    company_id = fields.Many2one(
        "res.company", "Организация", required=True,
        default=lambda self: self.env.company,
        help="От чьего имени пойдут предложение и счёт.")

    supplier_id = fields.Many2one(
        "res.partner", "Поставщик для цен",
        help="Чьи цены берём в расчёт. Пусто — берётся поставщик с лучшим "
             "рейтингом из тех, у кого есть цена на нужную позицию.")

    price_date = fields.Date(
        "Цены на дату", default=fields.Date.context_today,
        help="На какую дату смотрим прайсы. Отдельно от даты документа: "
             "расчёт заводят задним числом, а цены нужны свежие.")

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
    # Тоже зеркало деталей изделий: «создать деталь» через него без изделия
    # отбрасывается (pmk_calc, spec_layout.py — почему не сохранялся новый
    # расчёт, 08.10.2026). Вкладка «Цены» только для чтения и новые детали
    # до сохранения показывает — это безвредно, браузер их не присылает.
    _pmk_line_mirrors = ("sheet_line_ids", "price_line_ids")

    # ⚠️ ОБЫЧНОЕ ПОЛЕ, А НЕ ВЫЧИСЛЯЕМОЕ. Сначала дата подставлялась хранимым
    # compute — и это дважды вышло боком: значение посчиталось один раз по
    # неверному правилу и больше не пересчитывалось, а после миграции, которая
    # его обнулила, осталось пустым навсегда (обнулённое поле Odoo пересчитать
    # не просит). Теперь пусто значит «предыдущий прайс», и это состояние
    # честное: его видно в подсказке рядом с полем.
    compare_price_date = fields.Date(
        "Сравнить с ценами на", copy=False,
        help="С каким прайсом сравниваем. Пусто — с предыдущим по дате.")
    compare_effective_date = fields.Date(
        "Дата сравнения", compute="_compute_compare_date",
        help="Что реально взято за точку отсчёта.")
    compare_hint = fields.Char(
        "Сравниваем с", compute="_compute_compare_date")
    latest_price_date = fields.Date(
        "Последний прайс", compute="_compute_price_freshness",
        help="Самая свежая дата прайса по позициям этого расчёта.")
    price_stale = fields.Boolean(
        "Есть прайс свежее", compute="_compute_price_freshness",
        help="Цены взяты на дату старее последнего прайса: пересчёт по "
             "текущей дате ничего не изменит, потому что смотрит в архив.")
    # Разбор UX, шаг 32: красный «!» в шапке → словами «есть прайс от
    # 21.09». Значок без слова не говорил, что именно не так (правило
    # «цвет всегда повторён словом»).
    price_stale_label = fields.Char(
        "Свежий прайс", compute="_compute_price_freshness",
        help="Есть прайс новее даты цен этого расчёта. «Перечитать цены» "
             "перечитает старые — чтобы взять свежие, нажмите «Взять свежий "
             "прайс».")

    compare_total_cost = fields.Monetary(
        "Было по тому прайсу", compute="_compute_compare_totals")
    compare_delta = fields.Monetary(
        "Разница", compute="_compute_compare_totals")
    compare_pct = fields.Float(
        "Разница, %", compute="_compute_compare_totals", digits=(6, 1))
    # Разбор UX, шаг 32: итог вкладки «Цены» — одной строкой вместо блока
    # из четырёх полей («Было по тому прайсу», «Стало сейчас», «Разница»,
    # «Разница, %»): «С 16.06: +276 198 ₽ (+8,8 %)». Поля остались в модели.
    compare_summary = fields.Char(
        "Изменение цен", compute="_compute_compare_summary",
        help="Насколько изменилась стоимость металла этого расчёта с даты "
             "сравнения. Позиции, выпавшие из прайса, указаны отдельно: "
             "металл всё равно придётся купить.")

    # ─── Печать КП (разбор UX, шаг 32) ──────────────────────────────────
    #
    # Изделие без цены клиенту в КП не печатается (quotation_report.xml:
    # product_ids.filtered(lambda p: p.price_customer_unit)). Сигнал в шапке
    # говорит об этом ДО печати — и ничего не запрещает: КП печатается и
    # без них (правило «сигнал показывает, а не запрещает»; блокировка
    # отправки без цены закупки — решение 24.09, после обкатки).
    kp_skip_count = fields.Integer(
        "Изделий не попадёт в КП", compute="_compute_kp_skip")
    kp_skip_text = fields.Char(
        "Не попадут в КП", compute="_compute_kp_skip",
        help="Изделия без цены клиенту в КП не печатаются. Поставьте цену за "
             "штуку в составе.")

    # ─── Цена для клиента ─────────────────────────────────────────────────
    #
    # ⚠️ ВВОДИТСЯ РУКАМИ, И ЭТО НЕ ВРЕМЕННО ПО ЛЕНИ. Владелец 27.09.2026:
    # «выбор цены за изделие работа очень творческая, поэтому можно пока что
    # сделать ввод цены вручную, а после прогона станет понятно, как лучше
    # работать». Наценка процентом от металла тут неверна: в цену входят
    # переделы, сложность, срочность и отношения с заказчиком — формулы для
    # этого пока нет ни у кого на заводе.
    #
    # Себестоимость считается рядом и не спорит с ценой: она показывает, что
    # осталось, а не диктует, сколько просить.
    price_customer_total = fields.Monetary(
        "Цена клиенту", compute="_compute_customer_totals", store=True,
        help="Сумма по изделиям. Складывается из цен, которые менеджер "
             "поставил каждому изделию.")
    margin_amount = fields.Monetary(
        "Маржа", compute="_compute_customer_totals", store=True,
        help="Цена клиенту минус металл. Работа и переделы сюда ещё не "
             "входят — это не прибыль, а то, из чего её платят.")
    # aggregator=None: в сгруппированном списке Odoo по умолчанию СКЛАДЫВАЕТ
    # проценты в строке группы (две строки 0 % и 37,6 % давали «37,6 %»).
    # Сумма процентов бессмысленна — строку группы оставляем пустой.
    margin_pct = fields.Float(
        "Маржа, %", compute="_compute_customer_totals", store=True,
        digits=(6, 1), aggregator=None)

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

    # Разбор UX, шаг 11 (CA-02): неполный расчёт — плашкой с названиями
    # позиций и весом, а не мелкой строкой «Без цены позиций: 1». Какая
    # именно позиция без цены, на главной вкладке видно не было, а в СМ-00024
    # это был рифлёный лист — 30 % веса расчёта. Не хранится: считается при
    # открытии документа, по тем же строкам, что no_price_count.
    price_missing_text = fields.Char(
        "Позиции без цены", compute="_compute_price_missing_text")

    @api.depends("no_price_count")
    def _compute_price_missing_text(self):
        Line = self.env["pmk.metal.spec.line"]
        for spec in self:
            spec_id = spec._origin.id
            if not spec.no_price_count or not spec_id:
                spec.price_missing_text = False
                continue
            lines = Line.search([
                ("spec_id", "=", spec_id),
                ("price_state", "not in", ("ok", "empty")),
            ])
            # Одна позиция справочника в нескольких деталях — одной строкой.
            # Вес строки — на одно изделие, умножаем на их количество.
            weights = {}
            for line in lines:
                item = line.profile_id or line.sheet_id or line.fastener_id or line.paint_id
                name = item.display_name if item else (line.detail_name or "позиция")
                weights[name] = weights.get(name, 0.0) + (
                    (line.weight_fact_total or 0.0) * (line.product_id.qty or 1))
            ranked = sorted(weights.items(), key=lambda kv: -kv[1])
            shown = ["%s — %s" % (name, self._pmk_weight_label(kg)) for name, kg in ranked[:5]]
            rest = len(ranked) - len(shown)
            spec.price_missing_text = "; ".join(shown) + (
                " и ещё %s" % rest if rest > 0 else "")

    # «Купить, т» в шапке — только когда отличается от веса в деталях (есть
    # отход). Сравнение с допуском: дробные суммы расходятся в последнем
    # знаке, и точное «==» показывало бы строку почти всегда.
    buy_weight_differs = fields.Boolean(compute="_compute_buy_weight_differs")

    @api.depends("total_weight_fact", "total_weight")
    def _compute_buy_weight_differs(self):
        for spec in self:
            spec.buy_weight_differs = abs(
                (spec.total_weight_fact or 0.0) - (spec.total_weight or 0.0)) >= 0.5

    @staticmethod
    def _pmk_weight_label(kg):
        """15210 → «15,2 т», 445 → «445 кг», 0,4 → «0,4 кг»."""
        if kg >= 1000:
            return ("%.1f т" % (kg / 1000.0)).replace(".", ",")
        if kg >= 10:
            return "%d кг" % round(kg)
        return ("%.1f кг" % kg).replace(".", ",")

    @api.depends("product_ids.price_customer_total", "total_cost_fact")
    def _compute_customer_totals(self):
        for spec in self:
            total = sum(spec.product_ids.mapped("price_customer_total"))
            spec.price_customer_total = total
            spec.margin_amount = total - spec.total_cost_fact
            spec.margin_pct = (
                (total - spec.total_cost_fact) / total * 100.0) if total else 0.0

    # ─── Копия расчёта — новый расчёт на сегодня (приёмка 01.10.2026, R4) ──
    #
    # «Дублировать» в ⚙ делают, чтобы посчитать заявку заново: тот же состав,
    # другие объёмы или размеры. Значит копия — это НОВЫЙ расчёт: дата цен —
    # сегодня, цены закупки перечитываются из прайсов (price_unit не
    # копируется, см. поле), ручные правки цены не переносятся. Дату самого
    # документа ставит pmk_calc (MetalSpec.copy_data), сделку переносит
    # pmk_deal (opportunity_id, copy=True), раскладку листов не копирует
    # pmk_calc (spec_layout.py) — её пересчитывают кнопкой.
    def copy_data(self, default=None):
        default = dict(default or {})
        default.setdefault("price_date", fields.Date.context_today(self))
        return super().copy_data(default)

    def copy(self, default=None):
        new_specs = super().copy(default)
        # «Дублировать» из списка копирует сразу несколько: пара за парой.
        for origin, new in zip(self, new_specs):
            new._pmk_log_copy(origin)
        return new_specs

    def _pmk_log_copy(self, origin):
        """Запись в ленту копии: откуда она и что в ней посчитано заново.

        Без неё копия молча расходится с оригиналом в деньгах — другая дата
        цен, другие цены, — и через неделю не понять почему.
        """
        self.ensure_one()
        # Цена строки оригинала не совпадала с его строкой прайса — это ручная
        # правка (или цены не перечитаны после смены поставщика). В копию
        # такие цены не попадают: она считается по прайсу.
        manual = len(origin.price_line_ids.filtered(
            lambda l: l.price_state == "ok" and l.price_source_id
            and abs(l.price_unit - l.price_source_id.price_discounted) >= 0.005))
        laid_out = any(state != "none"
                       for state in origin.sheet_line_ids.mapped("layout_state"))
        on_date = self.price_date.strftime("%d.%m.%Y") if self.price_date else "сегодня"
        parts = ["Копия %s. Дата расчёта и цены — на %s: цены закупки перечитаны "
                 "из прайсов." % (origin.name, on_date)]
        if manual:
            parts.append("Цены, правленные вручную, не перенесены: %s поз." % manual)
        if laid_out:
            parts.append("Раскладку листов — заново кнопкой «Разложить листы "
                         "(черновик)» на вкладке «Раскладка».")
        if self.no_price_count:
            parts.append("Позиций без цены: %s." % self.no_price_count)
        self._message_log(body=" ".join(parts))

    def pmk_money(self, amount):
        """Сумма по-русски: «54 000,00 руб».

        ⚠️ ЗАЧЕМ СВОЙ МЕТОД, ЕСЛИ ЕСТЬ widget="monetary". Виджет в печати
        форматирует по-английски — «54,000.00 руб», — и язык, заданный
        контекстом шаблона, на него не влияет (проверено: то же число на
        ru_RU и en_US). В интерфейсе формат правильный, поэтому дефект видно
        только на бумаге у клиента. Здесь формат задаётся явно и работает
        одинаково во всех печатных формах.
        """
        self.ensure_one()
        env = self.env(context=dict(self.env.context, lang="ru_RU"))
        return format_amount(env, amount or 0.0, self.currency_id)

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

    @api.depends("price_date", "compare_price_date", "price_line_ids")
    def _compute_compare_date(self):
        """С каким прайсом сравниваем на самом деле."""
        for spec in self:
            base = spec.price_date or fields.Date.context_today(spec)
            dates = spec._price_dates()
            # ⚠️ СРАВНИВАТЬ НАДО С ПРЕДЫДУЩИМ ПРАЙСОМ, А НЕ С ПРЕДЫДУЩЕЙ ДАТОЙ.
            # Расчёт на 23 сентября берёт цены из прайса от 21-го, и «последняя
            # дата раньше 23-го» — это он же. Сравнение самого с собой давало
            # ровные нули во всей таблице: было равно стало.
            current = [d for d in dates if d <= base]
            current = current[-1] if current else None
            earlier = [d for d in dates if current and d < current]
            auto = earlier[-1] if earlier else False
            spec.compare_effective_date = spec.compare_price_date or auto
            if spec.compare_price_date and spec_text.compare_later(
                    spec.compare_price_date, spec.price_date):
                # Сравнение идёт по времени: «было» — цены расчёта, «стало» —
                # этот прайс (доводка шага 32). Говорим об этом рядом с датой.
                spec.compare_hint = "новее цен расчёта: «Стало» — по нему"
            elif spec.compare_price_date:
                spec.compare_hint = ""
            elif auto:
                spec.compare_hint = "предыдущий прайс от %s" % auto.strftime("%d.%m.%Y")
            else:
                spec.compare_hint = "сравнивать не с чем: прайс только один"

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
            spec.price_stale_label = spec_text.stale_label(
                spec.latest_price_date, spec.price_date) if spec.price_stale else False

    @api.depends("price_line_ids.cost_compare_delta", "total_cost_fact",
                 "compare_effective_date", "price_date")
    def _compute_compare_totals(self):
        for spec in self:
            delta = sum(spec.price_line_ids.mapped("cost_compare_delta"))
            spec.compare_delta = delta
            # «Было» — сумма на более ранних ценах. Обычно это прайс
            # сравнения: итог минус разница. Прайс сравнения новее цен
            # расчёта — тогда «было» и есть итог расчёта (доводка шага 32):
            # процент считается от него, «+10 %» — «свежий прайс дороже на 10 %».
            if spec_text.compare_later(spec.compare_effective_date, spec.price_date):
                was = spec.total_cost_fact
            else:
                was = spec.total_cost_fact - delta
            spec.compare_total_cost = was
            spec.compare_pct = (delta / was * 100.0) if was else 0.0

    @api.depends("compare_delta", "compare_pct", "compare_effective_date",
                 "price_date", "price_line_ids.price_compare_note")
    def _compute_compare_summary(self):
        for spec in self:
            base = spec.price_date or fields.Date.context_today(spec)
            lost = len(spec.price_line_ids.filtered(
                lambda l: l.price_compare_note == "выпала из прайса"))
            spec.compare_summary = spec_text.compare_summary(
                spec.compare_delta, spec.compare_pct,
                spec.compare_effective_date, lost=lost, base_year=base.year,
                later=spec_text.compare_later(
                    spec.compare_effective_date, spec.price_date))

    # Доводка шага 32: «Поставщик для цен» стоит теперь прямо над таблицей
    # «Было/Стало». Смена поставщика (или даты цен) цены в строках НЕ меняет
    # — их меняет только «Перечитать цены», расчёт считается на дату. Но
    # строка прайса уже от нового поставщика, и до перечитывания таблица
    # сравнивала бы цены разных поставщиков. Сигнал говорит об этом словами;
    # ничего не запрещает и сам ничего не перечитывает.
    #
    # Признак — цена строки не совпадает с той строкой прайса, которую по
    # нынешним настройкам выбрало бы правило (price_source_id). На боевой
    # базе 30.09 таких строк нет ни в одном расчёте — сигнал не загорится
    # на старых документах сам по себе.
    price_reread_needed = fields.Boolean(
        "Цены не перечитаны", compute="_compute_price_reread_needed",
        help="Цены в строках — по прежнему поставщику или прежней дате. "
             "Нажмите «Перечитать цены».")

    @api.depends("price_line_ids.price_unit", "price_line_ids.price_state",
                 "price_line_ids.price_source_id")
    def _compute_price_reread_needed(self):
        for spec in self:
            spec.price_reread_needed = any(
                line.price_state == "ok" and line.price_source_id
                and abs(line.price_unit - line.price_source_id.price_discounted) >= 0.005
                for line in spec.price_line_ids)

    # Условие то же, что у печатной формы: not price_customer_unit. В базе у
    # изделия без цены там NULL, а не 0 — ORM отдаёт 0.0, и оба случая одно.
    @api.depends("product_ids.price_customer_unit", "product_ids.name")
    def _compute_kp_skip(self):
        for spec in self:
            skipped = spec.product_ids.filtered(lambda p: not p.price_customer_unit)
            spec.kp_skip_count = len(skipped)
            spec.kp_skip_text = spec_text.kp_skip_text(skipped.mapped("name"))

    def action_print_quotation(self):
        """Кнопка «КП (PDF)» — печать коммерческого предложения.

        Раньше печать жила только в меню-шестерёнке, хотя ради неё расчёт и
        заводят (разбор UX, шаг 32). Привязка к шестерёнке осталась.

        ОБЪЕКТНОЙ КНОПКОЙ, А НЕ %(xmlid)d. Файл видов в манифесте грузится
        раньше отчёта, и ссылка на ещё не созданный отчёт уронила бы
        установку; менять порядок data ради кнопки незачем.

        config=False: иначе администратору базы без выбранного макета
        документов Odoo вместо PDF открыл бы мастер настройки макета — КП
        всё равно печатается нашим шаблоном, макет ему не нужен.
        """
        return self.env.ref(
            "pmk_bridge.action_report_metal_spec_quotation"
        ).report_action(self, config=False)

    @api.depends("cost_change_pct", "price_refreshed_on", "cost_new_total",
                 "total_cost_fact", "price_changed")
    def _compute_change_labels(self):
        for spec in self:
            spec.cost_change_abs_pct = abs(spec.cost_change_pct)
            # Разница в копейку — это округление Monetary, а не правка состава.
            # Снимка «стало» может не быть вовсе — у расчётов, пересчитанных
            # до того, как поле появилось. Это не «устарело», это «неизвестно»:
            # гореть предупреждением тут нечему.
            spec.price_signal_stale = bool(
                spec.price_refreshed_on and spec.cost_new_total
                and abs(spec.total_cost_fact - spec.cost_new_total) >= 0.01)
            if not spec.price_refreshed_on or not spec.cost_new_total:
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
            spec._log_price_refresh(was, now, lines)
        return True

    def _log_price_refresh(self, was, now, lines):
        """Запись в историю документа — человеческим языком.

        Odoo сам пишет, ЧТО поменялось в полях, но не пишет, ПОЧЕМУ: после
        пересчёта в истории остаются голые числа. Здесь один абзац, из
        которого через месяц понятно, на какой прайс переехали, насколько
        изменилась сумма и какие позиции её сдвинули.
        """
        self.ensure_one()
        changed = lines.filtered(lambda l: l.price_change_pct)
        top = changed.sorted(lambda l: -abs(l.price_change_pct))[:3]

        head = "Цены перечитаны на %s." % (
            self.price_date.strftime("%d.%m.%Y") if self.price_date else "сегодня")
        if not was:
            body = "%s Металл посчитан впервые: %s ₽." % (head, _money(now))
        elif abs(now - was) < 0.01:
            body = "%s Сумма не изменилась: %s ₽." % (head, _money(now))
        else:
            word = "подорожал" if now > was else "подешевел"
            body = "%s Металл %s на %.1f%%: %s → %s ₽." % (
                head, word, abs((now - was) / was * 100.0), _money(was), _money(now))

        if top:
            rows = "".join(
                "<li>%s: %+.1f%%</li>" % (line.position_label or line.detail_name or "позиция",
                                          line.price_change_pct)
                for line in top)
            body += "<ul>%s</ul>" % rows
        if self.price_lost_count:
            body += "<p>Выпало из прайса позиций: %s — металл всё равно придётся купить.</p>" % (
                self.price_lost_count)
        elif self.no_price_count:
            body += "<p>Позиций без цены: %s.</p>" % self.no_price_count

        self.message_post(body=Markup(body))


class MetalSpecProductCost(models.Model):
    """Изделие: итоги в деньгах. Количество изделий умножается ЗДЕСЬ."""

    _inherit = "pmk.metal.spec.product"

    currency_id = fields.Many2one(
        related="spec_id.currency_id", store=True, readonly=True, string="Валюта")

    price_customer_unit = fields.Monetary(
        "Цена клиенту за шт", help="Сколько просим за одно изделие. Ставит "
        "менеджер: цена зависит от переделов, сроков и заказчика, а не от "
        "веса металла.")
    price_customer_total = fields.Monetary(
        "Цена клиенту, всего", compute="_compute_customer_line", store=True)

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
    # Доводка шага 32: «Металл, ₽» рядом с ценой — с оговоркой, если у части
    # позиций нет цены закупки. Голое cost_fact_one у такого изделия занижено
    # (позиция без цены считается нулём), а в строке это никак не было видно:
    # на боевой базе 30.09 так было у 7 изделий из 10. Не хранится — подпись
    # к двум хранимым числам. Формат — tools/spec_text.metal_label.
    metal_one_label = fields.Char(
        "Металл, ₽", compute="_compute_metal_one_label",
        help="Стоимость металла на одно изделие. «≥ … · без N поз.» — у N "
             "позиций нет цены в прайсах (в городе их нет): металл не меньше "
             "этого числа, цену за штуку ставьте с запасом.")

    @api.depends("cost_fact_one", "no_price_count")
    def _compute_metal_one_label(self):
        for product in self:
            product.metal_one_label = spec_text.metal_label(
                product.cost_fact_one, product.no_price_count)

    @api.depends("price_customer_unit", "qty")
    def _compute_customer_line(self):
        for product in self:
            product.price_customer_total = (
                product.price_customer_unit or 0.0) * (product.qty or 0)

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
    # ⚠️ ВЫЧИСЛЯЕМОЕ ТЕМ ЖЕ МЕТОДОМ, ЧТО И ЦЕНА. Обычным полем оно читалось
    # пустым сразу после создания детали: вычисление цены отложено до сброса,
    # а чтение обычного поля его не запускает (тест шага 25 поймал это).
    price_source_id = fields.Many2one(
        "product.supplierinfo", "Строка прайса",
        compute="_compute_price_from_supplier", store=True, readonly=True,
        help="Только для просмотра: содержимое строки меняется при заливке "
             "нового прайса.")

    # ⚠️ copy=False — НЕ ПРО «НЕ ПЕРЕНОСИТЬ РУЧНУЮ ЦЕНУ», А ПРО ВСЮ ГРУППУ.
    # Хранимое правимое вычисляемое поле ядро копирует (orm/fields.py), и
    # create() защищает от пересчёта ВСЮ группу полей этого вычисления
    # (orm/models.py, protected): состояние, ₽/кг, ₽/т, строку прайса,
    # поставщика, дату прайса. Копия расчёта выходила с price_state по
    # умолчанию «empty», без строки прайса и с нулевым металлом — СМ-00025
    # (замечание владельца 01.10.2026: «продублировал расчёт, цены на металл
    # автоматически не проставились»). Без копирования цена считается при
    # создании копии, на её дату цен — как у нового расчёта.
    price_unit = fields.Float(
        "Цена за единицу", compute="_compute_price_from_supplier", store=True,
        readonly=False, digits=(16, 4), copy=False,
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
    #
    # ПО ВРЕМЕНИ, ОТ РАННЕГО К ПОЗДНЕМУ (доводка шага 32). Обычно прайс
    # сравнения старше цен расчёта: «было» — он, «стало» — цены расчёта. Но
    # расчёт на старых ценах сравнивают и со свежим прайсом — «насколько
    # подорожает, если его взять». Тогда «было» — цены расчёта, «стало» —
    # свежий прайс, и знак честный: дороже — плюс. Прежде в этом случае
    # таблица и итог читались наоборот: «с 21.09 подешевело».
    price_compare_unit = fields.Float(
        "Было", compute="_compute_price_compare", digits=(16, 4),
        help="Цена той же позиции на более раннюю из двух дат — обычно по "
             "прайсу, с которым сравниваем.")
    # Разбор UX, шаг 32: «Было, ₽/т» / «Стало, ₽/т» вместо «Было» / «Стало»
    # без единицы. Цена единицы у проката за метр, у листа за штуку, у
    # метиза за штуку, у краски за кг — в одной колонке это были числа в
    # разных единицах. За тонну сравнимо всё.
    price_compare_ton = fields.Float(
        "Было, ₽/т", compute="_compute_price_compare", digits=(12, 2),
        help="Цена позиции за тонну на более раннюю из двух дат.")
    # «Стало» — хранимое price_ton расчёта, а когда прайс сравнения новее
    # цен расчёта — цена по нему.
    price_now_ton = fields.Float(
        "Стало, ₽/т", compute="_compute_price_compare", digits=(12, 2),
        help="Цена позиции за тонну на более позднюю из двух дат — обычно "
             "цена этого расчёта.")
    price_compare_pct = fields.Float(
        "Изм., %", compute="_compute_price_compare", digits=(6, 1))
    cost_compare_delta = fields.Monetary(
        "В сумме, ₽", compute="_compute_price_compare",
        help="На сколько подорожала эта позиция в деньгах ЭТОГО расчёта. "
             "Процент говорит, что подорожало, рубли — насколько это важно: "
             "лист вырос слабее трубы, а в деньгах — в тридцать раз сильнее.")
    position_label = fields.Char(
        "Позиция", compute="_compute_position_label",
        help="Что за материал в строке. Без этого в таблице цен видны одни "
             "номера деталей, и понять, о чём речь, нельзя.")
    # Текстом, а не выбором: колонка должна МОЛЧАТЬ, когда всё в порядке.
    # «Есть обе цены» в каждой строке — шум, среди которого «выпала из
    # прайса» перестаёт бросаться в глаза.
    price_compare_note = fields.Char(
        "Замечание", compute="_compute_price_compare")
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

        Правило живёт у справочника (_pmk_mass_per_unit в reference_link.py,
        разбор UX, шаг 25): по нему же считает цену за тонну справочник и
        список «Цены поставщиков» — одна дверь, числа не расходятся.
        """
        self.ensure_one()
        position = self._cost_position()
        return position._pmk_mass_per_unit(tmpl) if position else 0.0

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

            # ⚠️ ВАЛЮТА НОВОГО РАСЧЁТА ДО СОХРАНЕНИЯ ПУСТАЯ. Поле с умолчанием
            # на документе, но деталь заводится в диалоге изделия, и там
            # документ ещё не записан — валюта приходит False. Проверка
            # валют роняла форму на ПЕРВОЙ же детали с ценой: «расчёт
            # ведётся в False». Найдено прогоном реальной заявки 27.09.2026;
            # на сохранённых расчётах, где шли все проверки, не проявлялось.
            spec_currency = (line.spec_id.currency_id
                             or line.spec_id.company_id.currency_id
                             or self.env.company.currency_id)
            if seller.currency_id != spec_currency:
                # Громкий отказ вместо тихой конвертации: без курса пересчёт
                # прошёл бы один к одному и ошибку заметили бы в деньгах.
                raise UserError(
                    "Цена поставщика %s указана в валюте %s, а расчёт ведётся в %s. "
                    "Пересчёт валют не делаем — заведите цену в рублях."
                    % (seller.partner_id.display_name, seller.currency_id.name,
                       spec_currency.name))

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

    @api.depends("profile_id", "sheet_id", "fastener_id", "paint_id")
    def _compute_position_label(self):
        for line in self:
            item = (line.profile_id or line.sheet_id
                    or line.fastener_id or line.paint_id)
            line.position_label = item.display_name if item else ""

    @api.depends("price_unit", "price_state", "price_ton", "cost_fact_total",
                 "spec_id.compare_effective_date", "spec_id.price_date",
                 "spec_id.supplier_id",
                 "profile_id", "sheet_id", "fastener_id", "paint_id")
    def _compute_price_compare(self):
        """Цена этой позиции по прайсу, с которым сравниваем.

        Стоимость линейна по цене единицы, поэтому вклад в сумму считается
        долей, а не пересчётом всей цепочки: cost × (стало − было) / цена
        расчёта. Так число совпадает с итогом документа до копейки, и не
        приходится второй раз воспроизводить правила расчёта массы и
        количества.

        Было и стало — по времени (доводка шага 32): прайс сравнения старше
        цен расчёта — он «было»; новее — он «стало», а «было» — цены расчёта.
        """
        for line in self:
            spec = line.spec_id
            date = spec.compare_effective_date
            tmpl = line._cost_product()
            seller = line._cost_find_seller(tmpl, date=date) if (date and tmpl) else False
            other = seller.price_discounted if seller else 0.0
            ours = line.price_unit if line.price_state == "ok" else 0.0
            # Масса единицы — тем же правилом, что у price_ton. Нулевая масса
            # (мина листа 1500×6000) — ноль, без деления.
            other_ton = spec_text.per_ton(
                other, line._cost_mass_unit(tmpl) if (other and tmpl) else 0.0)
            ours_ton = line.price_ton if ours else 0.0

            later = spec_text.compare_later(date, spec.price_date)
            if later:
                old, new, old_ton, new_ton = ours, other, ours_ton, other_ton
            else:
                old, new, old_ton, new_ton = other, ours, other_ton, ours_ton

            line.price_compare_unit = old
            line.price_compare_ton = old_ton
            line.price_now_ton = new_ton
            if old and new:
                line.price_compare_note = False
                line.price_compare_pct = (new - old) / old * 100.0
                # Сумма строки посчитана по цене расчёта (ours) — от неё и доля.
                line.cost_compare_delta = line.cost_fact_total * (new - old) / ours
            elif old and not new:
                # Позиция была в прайсе и пропала. Деньги «сэкономлены» только
                # на бумаге: металл всё равно придётся купить, просто цена
                # теперь неизвестна.
                line.price_compare_note = "выпала из прайса"
                line.price_compare_pct = 0.0
                line.cost_compare_delta = 0.0
            elif new and not old:
                # Цена есть только на позднюю дату. Прайс сравнения старше —
                # позиции в нём не было; новее — цена есть только в нём.
                line.price_compare_note = (
                    "есть только в том прайсе" if later else "не было в том прайсе")
                line.price_compare_pct = 0.0
                line.cost_compare_delta = 0.0
            else:
                line.price_compare_note = "цены нет"
                line.price_compare_pct = 0.0
                line.cost_compare_delta = 0.0

    def _cost_find_seller(self, tmpl, date=None):
        """Строка прайса: у заданного поставщика или у лучшего по рейтингу.

        Дата приходит параметром, чтобы тем же кодом отвечать на вопрос «а
        сколько это стоило в июне»: вкладка «Цены» сравнивает два прайса, и
        расхождение в правилах выбора поставщика сделало бы сравнение
        бессмысленным — разница показывала бы не цену, а другой алгоритм.

        Само правило выбора — у карточки товара (product.template.
        _pmk_find_seller, reference_price.py, разбор UX, шаг 25): по нему же
        справочник показывает цену колонкой. Здесь — только дата и поставщик
        этого расчёта.
        """
        self.ensure_one()
        date = date or self.spec_id.price_date or fields.Date.context_today(self)
        return tmpl._pmk_find_seller(date, supplier=self.spec_id.supplier_id) or False

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
