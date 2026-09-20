# -*- coding: utf-8 -*-
"""Загрузка рабочего центра на текущую неделю — свой расчёт.

ПОЧЕМУ НЕ ШТАТНЫЙ ПОКАЗАТЕЛЬ. У mrp.workcenter есть готовое поле
kanban_dashboard_graph, и соблазн взять его велик. Смотрим, откуда оно берёт
числа (Odoo 19, mrp/models/mrp_workcenter.py, _get_workcenter_load_per_week):

    has_workorder = self.env['mrp.workorder'].search_count(...)
    if not has_workorder:
        load_limit = 40
        load_data[wc] = {week_start: randint(0, int(load_limit * 2)) ...}

При пустой таблице рабочих заданий ядро подставляет СЛУЧАЙНЫЕ часы — это
демо-данные для пустой базы. На стенде заданий ноль, то есть экран приёмки
нарисовал бы правдоподобные проценты, которых никто не планировал. Полоса,
показывающая случайное число, хуже отсутствующей полосы: ей верят.

ЧТО СЧИТАЕМ МЫ.

    загрузка = плановые часы рабочих заданий недели / рабочие часы календаря
               этого рабочего центра за ту же неделю

Числитель — сумма duration_expected (минуты) по рабочим заданиям, знаменатель —
resource_calendar_id.get_work_hours_count() за границы недели. Оба источника
настоящие: первый заполняет планировщик, второй — график работы участка.

ЧЕГО ЭТОТ РАСЧЁТ НЕ УМЕЕТ (осознанные упрощения, а не недосмотр):

  * задание считается целиком в ту неделю, в которой НАЧИНАЕТСЯ. Задание на
    три смены через воскресенье целиком ляжет в первую неделю. Так же делает
    и ядро в своём графике, поэтому цифры двух экранов не разойдутся;
  * берутся плановые минуты, а не фактические, даже у завершённых заданий.
    Полоса отвечает на вопрос «чем неделя занята», а не «сколько отработано»;
  * параллельность и КПД участка отдельно не учитываются, и делить на них
    второй раз НЕЛЬЗЯ — ядро уже заложило оба множителя в duration_expected
    (mrp/models/mrp_workorder.py, _get_duration_expected, строки 815-836:
    _get_capacity(...) и time_efficiency).

    Про имя поля: поля `capacity` у mrp.workcenter в Odoo 19 НЕТ — проверено
    запросом к ir_model_fields на стенде, там из этой пары есть только
    time_efficiency. Сколько изделий участок делает за цикл, лежит в строках
    ОТДЕЛЬНОЙ модели mrp.workcenter.capacity (связь capacity_ids, поле
    capacity в самой строке). Раньше в этом абзаце стояло
    «mrp.workcenter.capacity» как имя поля центра, и следующий человек искал
    бы его на форме рабочего центра.
"""

from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models

# Пороги цвета — из прототипа владельца (loadColor: >=95 красный, >=75 жёлтый).
# Живут в Python, а не в CSS, сознательно: «с какого процента тревога» — вопрос
# производства, а не оформления, и менять его будут здесь.
LOAD_WARN_PCT = 75
LOAD_DANGER_PCT = 95

# Имена токенов темы (pmk_theme/static/src/scss/indicators.scss). В вид уезжает
# ИМЯ переменной, а сам цвет остаётся в теме: так у полосы и у бейджа один
# красный, и перекрасить всю систему можно одной правкой в теме.
TOKEN_OK = "--pmk-ok-ink"
TOKEN_WARN = "--pmk-warn-ink"
TOKEN_DANGER = "--pmk-danger-ink"
TOKEN_MUTED = "--pmk-muted-ink"

# Что показываем в узкой колонке процентов, когда считать не из чего. Слова
# «нет данных» туда не влезают (колонка 42px под «100%»), поэтому в колонке
# прочерк, а полными словами причина написана строкой ниже — см. pmk_load_note.
NO_DATA_MARK = "—"


def _hours(value):
    """Часы по-русски: 40.0 → «40,0». Отдельной функцией, чтобы оба числа
    подписи («18,5 из 40,0 ч») были набраны одинаково: разнобой «40.0 / 40,00»
    в одной строке читается как два разных числа."""
    return ("%.1f" % value).replace(".", ",")


class MrpWorkcenter(models.Model):
    _inherit = "mrp.workcenter"

    # Все поля нехранимые и считаются одним методом: они описывают ОДНО
    # состояние (загрузка недели), и частично пересчитанный набор — это
    # полоса одного цвета с процентом другого.
    #
    # Хранить их нельзя по той же причине, что и просрочку заказа: «эта
    # неделя» сдвигается сама, без единой записи в базу.
    pmk_load_hours = fields.Float(
        "Запланировано, ч", compute="_compute_pmk_load", digits=(10, 1))
    pmk_load_capacity = fields.Float(
        "Ёмкость недели, ч", compute="_compute_pmk_load", digits=(10, 1))

    # Ширина заливки отдельным полем, а не тем же процентом: при перегрузе
    # 128% полоса должна упереться в конец дорожки, а число рядом обязано
    # остаться настоящим. Одно поле на две роли здесь либо врёт, либо
    # вылезает за карточку.
    #
    # Самого процента отдельным полем НЕТ. Он был (pmk_load_pct), но его не
    # выводил ни один вид: на экран процент попадает строкой из
    # pmk_load_label, а ширину полосы несёт pmk_load_bar. Поле, которое
    # считается при каждом чтении и никому не показывается, — это работа без
    # адресата; процент живёт локальной переменной в расчёте ниже.
    pmk_load_bar = fields.Integer(
        "Ширина полосы, %", compute="_compute_pmk_load")
    pmk_load_label = fields.Char(
        "Подпись загрузки", compute="_compute_pmk_load")
    pmk_load_token = fields.Char(
        "Токен цвета", compute="_compute_pmk_load",
        help="Имя CSS-переменной темы, например --pmk-warn-ink.")
    pmk_load_note = fields.Char(
        "Пояснение к загрузке", compute="_compute_pmk_load",
        help="«18,5 из 40,0 ч» либо причина, по которой данных нет.")

    def _pmk_week_bounds(self):
        """Границы текущей недели (понедельник 00:00 — следующий понедельник).

        Часовой пояс берём пользовательский: «эта неделя» — это неделя того,
        кто смотрит на экран. На стенде пояс ЗАДАН: у admin он
        Asia/Vladivostok (проверено запросом к res_partner.tz, а не по
        памяти), то есть неделя здесь считается по Владивостоку, а не по UTC.

        Ветка `or "UTC"` — не описание нашего стенда, а запасной выход для
        пользователя с незаполненным поясом: у него граница недели уедет на
        несколько часов. Мириться с этим можно, врать числами — нет.

        tz.localize, а не replace(tzinfo=...): при переходе на летнее время
        второй способ даёт смещение соседнего времени года, и понедельник
        начинается в 23:00 воскресенья.
        """
        tz = pytz.timezone(self.env.user.tz or "UTC")
        today = datetime.now(tz).date()
        monday = today - timedelta(days=today.weekday())
        start = tz.localize(datetime.combine(monday, time.min))
        end = tz.localize(datetime.combine(monday + timedelta(days=7), time.min))
        return start, end

    # company_id.resource_calendar_id в зависимостях обязателен: у рабочего
    # центра без своего календаря ёмкость недели берётся из заводского
    # (см. ниже, ветка `or workcenter.company_id.resource_calendar_id`).
    # Без этой строки смена графика компании не сбрасывала бы кэш полей, и в
    # одном запросе полоса осталась бы посчитанной по старому графику.
    @api.depends(
        "order_ids.duration_expected",
        "order_ids.production_date",
        "order_ids.state",
        "resource_calendar_id",
        "company_id.resource_calendar_id",
    )
    def _compute_pmk_load(self):
        start_local, end_local = self._pmk_week_bounds()
        # В базе даты лежат наивными в UTC, поэтому в домен уходит UTC без
        # tzinfo, а в календарь — те же границы с поясом: get_work_hours_count
        # наивную дату молча считает за UTC, и рабочий день уехал бы на
        # разницу поясов.
        start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(pytz.utc).replace(tzinfo=None)

        # Один запрос на все карточки, а не по запросу на строку: иначе экран
        # из десяти участков — это десять группировок по таблице заданий.
        planned = {}
        if self.ids:
            groups = self.env["mrp.workorder"]._read_group(
                [
                    ("workcenter_id", "in", self.ids),
                    # Отменённые не занимают неделю. Завершённые — занимают:
                    # они эту неделю уже съели, и убрать их значит показать
                    # пустую пятницу на полностью отработанном участке.
                    ("state", "!=", "cancel"),
                    # production_date = date_start задания, а если оно не
                    # запланировано — дата начала производственного заказа
                    # (mrp/models/mrp_workorder.py, _compute_production_date).
                    # Поле хранимое, поэтому годится для домена.
                    ("production_date", ">=", start_utc),
                    ("production_date", "<", end_utc),
                ],
                ["workcenter_id"],
                ["duration_expected:sum"],
            )
            planned = {workcenter.id: total for workcenter, total in groups}

        for workcenter in self:
            # Календарь участка, а если его нет — календарь компании: рабочий
            # центр без своего графика работает по заводскому.
            calendar = (
                workcenter.resource_calendar_id
                or workcenter.company_id.resource_calendar_id
            )
            capacity = (
                calendar.get_work_hours_count(start_local, end_local)
                if calendar else 0.0
            )
            minutes = planned.get(workcenter.id)
            hours = (minutes or 0.0) / 60.0

            workcenter.pmk_load_hours = hours
            workcenter.pmk_load_capacity = capacity

            # Три разные причины «нет данных» разведены намеренно: «заданий
            # нет» чинит планировщик, «нет календаря» — мастер участка, «у
            # заданий нет времени» — технолог. Одна общая надпись отправила бы
            # всех троих искать вслепую.
            if not capacity:
                reason = (
                    "нет данных: у рабочего центра нет календаря с рабочими часами"
                )
            elif minutes is None:
                reason = "нет данных: на этой неделе рабочих заданий нет"
            elif not minutes:
                reason = "нет данных: у заданий недели не задано плановое время"
            else:
                reason = None

            if reason:
                workcenter.pmk_load_bar = 0
                workcenter.pmk_load_label = NO_DATA_MARK
                workcenter.pmk_load_token = TOKEN_MUTED
                workcenter.pmk_load_note = reason
                continue

            pct = int(round(hours / capacity * 100))
            # Заливка упирается в конец дорожки, подпись остаётся настоящей.
            workcenter.pmk_load_bar = min(pct, 100)
            workcenter.pmk_load_label = "%s%%" % pct
            if pct >= LOAD_DANGER_PCT:
                workcenter.pmk_load_token = TOKEN_DANGER
            elif pct >= LOAD_WARN_PCT:
                workcenter.pmk_load_token = TOKEN_WARN
            else:
                workcenter.pmk_load_token = TOKEN_OK
            workcenter.pmk_load_note = "%s из %s ч" % (
                _hours(hours), _hours(capacity))
