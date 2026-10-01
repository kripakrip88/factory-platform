# -*- coding: utf-8 -*-
"""Сделка показывает деньги из расчёта, а не «доход 0» и выдуманную вероятность.

Разбор UX, шаг 31 (30.09.2026). Под названием сделки крупно стояли
«Ожидаемый доход 0,00» и «Вероятность 91,67 %»: доход никто не вписывал,
вероятность считал автомат без истории. Цена, маржа и вес жили только в
расчёте, и чтобы наблюдать за КП, приходилось открывать каждую сделку.

ГЛАВНЫЙ РАСЧЁТ СДЕЛКИ — ПОСЛЕДНИЙ. Расчётов у сделки бывает несколько
(пересчитали объём, поменяли сортамент), и новый расчёт заменяет старый.
Последний — по дате, при равной дате — по номеру, как и порядок списка
расчётов (_order в pmk_calc).

ДОХОД СДЕЛКИ = ЦЕНА КЛИЕНТУ ИЗ ГЛАВНОГО РАСЧЁТА. Штатное поле
expected_revenue не заменяем, а вычисляем: на нём держатся сумма в шапке
колонки воронки, итог в списке, прогноз и отчёты ядра — всё это заработает
само. Поле остаётся записываемым (readonly=False): быстрое создание в
канбане и sale_crm при подтверждении штатного заказа пишут в него, и такая
запись не должна падать. Пересчёт идёт только при смене главного расчёта
или его цены. Изменение попадает в историю сделки (tracking ядра).

«ОТКУДА ПРИШЁЛ» — СВОЁ ПОЛЕ, А НЕ UTM ЯДРА. Справочники «Источник» и
«Канал» — 10 английских записей маркетинга, ни одна не используется, а
маркетинг скрыт шагом 8. Many2one позволил бы плодить значения; здесь пять
заводских, и через месяц группировкой видно, какой канал приносит маржу.
Кнопка «Лид» в почте ставит «Почта» сама (pmk_mail_ui).

ОБЪЕДИНЕНИЕ С ПРЕЖНЕЙ СДЕЛКОЙ. Мастер «Преобразовать в сделку» по умолчанию
вливает новую заявку в прежнюю сделку клиента (дубль по почте или клиенту,
даже проигранный). Главной остаётся прежняя, а переносятся только поля из
_merge_get_fields — наших там не было: «Почта» у письма пропадала вместе с
удалённым лидом, расчёты удалённой сделки оставались без сделки, доход
брался из старой суммы. Правила — в _merge_get_fields_specific ниже.

«КЛИЕНТ» НА КАРТОЧКЕ ВОРОНКИ — pmk_client_id, а не commercial_partner_id.
Штатное commercial_partner_id заполнено, только когда в сделке выбран
человек из компании; у сделки на саму компанию или на частное лицо оно
пустое, и клиент с карточки пропадал. partner_id.commercial_partner_id —
всегда тот, с кем договор: у человека в компании — компания, у компании —
она сама, у частного лица — он сам.

«ОТВЕТИТЬ КЛИЕНТУ ДО» — подпись поля date_deadline в самом поле, а не только
в трёх видах: иначе в «Добавить свой фильтр», своей группировке и выгрузке
оставалось «Ожидаемое закрытие», а подсказка «?» у метки говорила про
«дату, когда возможность будет выиграна». Русский текст — исходный
(en_US): Odoo при смене исходного текста сбрасывает старый перевод, и
русский интерфейс показывает наш. ⚠️ -u crm снова дольёт штатный перевод
«Ожидаемое закрытие» — в форме, списке и поиске подпись останется нашей
(атрибуты string/help в видах), а в конструкторе фильтра и выгрузке
вернётся штатная.
"""

from datetime import date

from odoo import Command, api, fields, models

from ..tools import money_text

SOURCES = [
    ("mail", "Почта"),
    ("site", "Сайт"),
    ("call", "Звонок"),
    ("b2b", "B2B-Center"),
    ("repeat", "Повторный"),
]

DEADLINE_HELP = ("Срок ответа клиенту. Просрочен — красным в списке сделок; "
                 "ничего не запрещает.")


def main_spec(specs):
    """Главный расчёт из набора — последний по дате, при равной дате — по
    номеру (как порядок списка расчётов, _order в pmk_calc).

    Сортируем явно, а не верим порядку набора: только что привязанный
    расчёт кэш дописывает в конец, а не по _order.
    """
    return specs.sorted(
        key=lambda spec: (spec.date or date.min, spec._origin.id or 0),
        reverse=True,
    )[:1]


class CrmLeadMoney(models.Model):
    _inherit = "crm.lead"

    pmk_spec_id = fields.Many2one(
        "pmk.metal.spec", "Расчёт", compute="_compute_pmk_spec_id",
        store=True, index=True,
        help="Главный расчёт сделки — последний по дате. Из него берутся "
             "цена клиенту, металл, маржа и вес.")
    expected_revenue = fields.Monetary(
        compute="_compute_pmk_expected_revenue", store=True, readonly=False,
        help="Цена клиенту из главного расчёта сделки.")
    pmk_no_price_label = fields.Char(
        "Без цены", compute="_compute_pmk_money_text",
        help="Позиция без цены закупки — сигнал «в городе нет», не ошибка. "
             "Итог по металлу занижен на эти позиции.")
    pmk_spec_summary = fields.Char(
        "Расчёт одной строкой", compute="_compute_pmk_money_text")
    pmk_spec_card = fields.Char(
        "Расчёт на карточке", compute="_compute_pmk_money_text")
    pmk_source = fields.Selection(
        SOURCES, "Откуда пришёл", tracking=True, index=True,
        help="Кнопка «Лид» в почте ставит «Почта» сама. Остальное — руками.")
    pmk_client_id = fields.Many2one(
        "res.partner", "Клиент", related="partner_id.commercial_partner_id",
        help="С кем договор: у человека в компании — компания, у компании — "
             "она сама, у частного лица — он сам.")
    date_deadline = fields.Date(string="Ответить клиенту до", help=DEADLINE_HELP)

    # Разбор UX, шаг 25: маржа и вес главного расчёта — колонками списка
    # сделок, рядом с «Ценой клиенту». Не хранятся: это окно в расчёт, а не
    # копия — второй источник правды разошёлся бы с расчётом после первой
    # же правки. Признак неполного расчёта и число позиций без цены нужны
    # полоске маржи (pmk_margin_bar): неполный — красная полоска и «≤».
    pmk_margin_pct = fields.Float(
        related="pmk_spec_id.margin_pct", string="Маржа, %",
        help="Маржа над металлом главного расчёта: работа и переделы ещё не "
             "вычтены. «≤» — у части позиций нет цены закупки, маржа завышена.")
    pmk_weight_t = fields.Float(
        related="pmk_spec_id.total_weight_t", string="Вес, т",
        help="Вес металла главного расчёта сделки.")
    pmk_no_price_count = fields.Integer(
        related="pmk_spec_id.no_price_count", string="Позиций без цены")
    pmk_price_incomplete = fields.Boolean(
        related="pmk_spec_id.price_incomplete", string="Расчёт неполный")
    # База полоски маржи в списке сделок — цена клиенту ИЗ РАСЧЁТА, а не
    # expected_revenue: тот правится в строке списка (multi_edit), и у
    # сделки без расчёта со вписанной суммой полоска показывала «0,0 %» как
    # плохую маржу. Нет расчёта или в нём нет цены — прочерк.
    pmk_spec_price = fields.Monetary(
        related="pmk_spec_id.price_customer_total", string="Цена клиенту по расчёту",
        currency_field="company_currency")

    # «Получен» в списке лидов — когда клиент написал, а не когда нажали
    # «Лид» (разбор UX, шаг 25). Лиды заводятся кнопкой в почте, и между
    # письмом и нажатием проходят часы и дни: у лида 4 письмо от 16.09, лид
    # создан 20.09 — create_date занижал бы задержку ответа. Кнопка «Лид»
    # пишет дату письма сама (pmk_mail_ui). Вычисление — только для тех, кому
    # её не передали: самое раннее входящее письмо в чате лида, иначе дата
    # заведения. Зависимостей нет — считается один раз: при создании лида и
    # при установке поля (так заполняются лиды, созданные до шага 25).
    pmk_received = fields.Datetime(
        "Получен", compute="_compute_pmk_received", store=True, readonly=False,
        help="Когда клиент написал: у лида из почты — дата письма, у "
             "заведённого руками — дата заведения.")

    @api.model_create_multi
    def create(self, vals_list):
        # «Получен» у заведённого руками лида — момент заведения. Вычисление
        # без зависимостей на создании не срабатывало (тест шага 25): колонка
        # «Получен» у ручного лида оставалась пустой. Время транзакции — то же,
        # что пишется в create_date. Дату письма передаёт pmk_mail_ui.
        now = self.env.cr.now()
        for vals in vals_list:
            if not vals.get("pmk_received"):
                vals["pmk_received"] = now
        return super().create(vals_list)

    @api.depends()
    def _compute_pmk_received(self):
        ids = [lead.id for lead in self if isinstance(lead.id, int)]
        first = {}
        if ids:
            first = dict(self.env["mail.message"].sudo()._read_group(
                [("model", "=", "crm.lead"), ("res_id", "in", ids),
                 ("message_type", "=", "email")],
                ["res_id"], ["date:min"]))
        for lead in self:
            lead.pmk_received = (first.get(lead.id) or lead.create_date
                                 or fields.Datetime.now())

    @api.depends("spec_ids", "spec_ids.date")
    def _compute_pmk_spec_id(self):
        for lead in self:
            lead.pmk_spec_id = main_spec(lead.spec_ids)

    @api.depends("pmk_spec_id.price_customer_total")
    def _compute_pmk_expected_revenue(self):
        for lead in self:
            lead.expected_revenue = lead.pmk_spec_id.price_customer_total or 0.0

    @api.depends(
        "pmk_spec_id.name",
        "pmk_spec_id.total_weight",
        "pmk_spec_id.price_customer_total",
        "pmk_spec_id.total_cost_fact",
        "pmk_spec_id.margin_pct",
        "pmk_spec_id.no_price_count",
    )
    def _compute_pmk_money_text(self):
        for lead in self:
            spec = lead.pmk_spec_id
            if not spec:
                lead.pmk_spec_summary = False
                lead.pmk_spec_card = False
                lead.pmk_no_price_label = False
                continue
            lead.pmk_spec_summary = money_text.spec_line(
                spec.name, spec.total_weight, spec.price_customer_total,
                spec.total_cost_fact, spec.margin_pct)
            lead.pmk_spec_card = money_text.card_line(
                spec.total_weight, spec.price_customer_total, spec.margin_pct)
            lead.pmk_no_price_label = money_text.no_price_label(spec.no_price_count) or False

    def _merge_get_fields_specific(self):
        """Объединение сделок (мастер «Преобразовать в сделку» → «Объединить»,
        действие «Объединить» в списке).

        • «Откуда пришёл» — первое непустое по уверенности (как у ядра
          телефон или клиент): у прежней сделки было своё — остаётся, было
          пусто — берётся «Почта» у письма, из которого пришла заявка;
        • расчёты всех сделок — к итоговой (как sale_crm делает с заказами):
          удалённая сделка не оставляет расчёт без сделки;
        • доход — цена клиенту главного расчёта объединённой сделки, а не
          первая попавшаяся сумма: иначе строка денег и доход разошлись бы;
        • «Получен» — самое раннее: клиент ждёт с первого письма.
        """
        fields_info = super()._merge_get_fields_specific()
        fields_info["pmk_source"] = lambda fname, leads: next(
            (lead.pmk_source for lead in leads if lead.pmk_source), False)
        fields_info["pmk_received"] = lambda fname, leads: min(
            (lead.pmk_received for lead in leads if lead.pmk_received), default=False)
        fields_info["spec_ids"] = lambda fname, leads: [
            Command.link(spec.id) for spec in leads.spec_ids]

        def revenue(fname, leads):
            if leads.spec_ids:
                return main_spec(leads.spec_ids).price_customer_total or 0.0
            return next((lead.expected_revenue for lead in leads if lead.expected_revenue), 0.0)

        fields_info["expected_revenue"] = revenue
        return fields_info
