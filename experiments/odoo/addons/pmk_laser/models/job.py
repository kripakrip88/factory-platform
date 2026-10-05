# -*- coding: utf-8 -*-
"""Задание на лазерную резку: файл раскроя, листы, детали, деньги.

Задание — главный документ участка. Из него берут знаменатель замеры, из него
же считается премия и баланс металла.

ЧТО БЕРЁТСЯ ИЗ ФАЙЛА И ЧЕМУ В НЁМ МОЖНО ВЕРИТЬ. Управляющий файл CypCut
(.lxds) разбирает tools/lxds.py; ему можно верить в составе заказа, числе
листов, габарите и использовании — это считает сама программа раскроя. Верить
НЕЛЬЗЯ разделу Technical: у технолога только демонстрационные режимы, и во всех
трёх присланных файлах (2, 3 и 10 мм) он побайтово одинаков, с Thickness="1.5"
и «чёрной сталью». Поэтому толщина берётся из ИМЕНИ файла — туда её пишут для
оператора станка, — а вид листа файл не знает вовсе: «3мм» не говорит, гладкий
он или рифлёный. По умолчанию гладкий, в задании — выбор.

ПОЧЕМУ ДЕТАЛИ И ЛИСТЫ — РАЗНЫЕ ТАБЛИЦЫ. Лист физически кладут на стол и
физически снимают, поэтому замер живёт на листе. Деталь физически режут, и
только у неё есть чертёж, из которого берётся длина реза и число проколов —
знаменатель, без которого замер непереносим на другой заказ. Какая деталь на
каком листе, файл открытым текстом не говорит (раскладка лежит в двоичном
Shapes2D/data.bin), поэтому знаменатель мы честно знаем по ЗАДАНИЮ целиком, а
не по отдельному листу. Отсюда правило норматива: в статистику идут только
задания, у которых замерены ВСЕ листы (см. norm.py).

ЧЕГО ЗДЕСЬ НЕТ. Складских движений. Баланс металла считается и показывается,
но списание листов и оприходование обрезков станет проводками тогда, когда
сортамент доедет до номенклатуры Odoo (этим занят pmk_bridge). Считать баланс
уже сейчас — не забегание вперёд: именно он показывает, что обрезки не
оприходуют, а этого сегодня не видит никто.

ДЕНЬГИ МЕТАЛЛА (разбор UX, шаг 36). «Металл, ₽» и «Лом, ₽» — списанный металл
и лом по цене поставщика за тонну, той же, что берёт расчёт: задание привязано
к расчёту и лист в нём есть с ценой — цена строки расчёта (её снимок); иначе
строка прайса выбирается тем же правилом (дверь моста
product.template._pmk_find_seller). Связь с мостом МЯГКАЯ, как у раскроя
(pmk_cut, доводка шага 35): pmk_bridge держит stock_account и модули RuOdoo
(l10n_ru_doc, l10n_ru_upd_xml), которых у лазера в зависимостях нет, и при
жёсткой зависимости удаление любого из них в «Приложениях» каскадом снесло
бы pmk_laser — со всеми заданиями, замерами и нормативами.
Поэтому деньги не хранятся и считаются при открытии: моста нет — «цены
поставщиков не подключены», цены нет — «нет в прайсах» (сигнал «в городе
нет», а не ноль).
"""

import base64
import os
import tempfile

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from . import labels, money, timing
from .machine import table_size_label

# Вид листа по умолчанию. Из имени файла вид не виден, а режут обычно чёрную
# сталь гладким листом — решение владельца.
DEFAULT_SHEET_TYPE = "Гладкий"

# Допуск при поиске толщины в справочнике. Толщина приходит из имени файла
# строкой («3мм»), в справочнике лежит числом с плавающей точкой — сравнивать
# их на точное равенство нельзя.
THICKNESS_TOLERANCE_MM = 0.001


class LaserJob(models.Model):
    _name = "pmk.laser.job"
    _description = "Задание на лазерную резку"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    machine_id = fields.Many2one(
        "pmk.laser.machine", "Станок", required=True, tracking=True,
        help="На каком из двух станков режем. От него берутся минуты на "
             "загрузку и разгрузку стола и по нему же ищется норматив.")
    partner_id = fields.Many2one("res.partner", "Заказчик", tracking=True)
    sale_order_id = fields.Many2one(
        "sale.order", "Заказ", tracking=True,
        help="Необязательно. Нужен, чтобы полезный вес и время резки можно "
             "было отнести на конкретный заказ, а не на участок вообще.")
    # ⚠️ ЗАЧЕМ ВТОРАЯ ССЫЛКА, ЕСЛИ ЕСТЬ «ЗАКАЗ». Заказов клиента в базе нет ни
    # одного: цена клиенту и КП живут в расчёте, заказ из него пока не
    # рождается. Ссылка на sale.order пуста у всех заданий, и на схеме связей
    # (pmk_flow) лазер висел отдельно от заявки, по которой режут. Расчёт —
    # документ, по которому режут на самом деле.
    #
    # Зависимость от pmk_calc у модуля уже есть (справочник листа), новой
    # связи между модулями поле не добавляет.
    spec_id = fields.Many2one(
        "pmk.metal.spec", "Расчёт металлопроката", index=True, ondelete="set null",
        tracking=True,
        help="По какому расчёту режем. Задание появится на схеме связей "
             "расчёта и сделки.")
    note = fields.Char("Примечание")

    # ------------------------------------------------------------------
    # Файл раскроя
    # ------------------------------------------------------------------
    file = fields.Binary("Файл раскроя (.lxds)", attachment=True, copy=False)
    file_name = fields.Char(
        "Имя файла", copy=False,
        help="Имя важно: толщина листа берётся именно из него. Переименованный "
             "файл разобрать не получится, и это правильно — гадать нельзя.")

    file_app = fields.Char("Программа раскроя", readonly=True, copy=False)
    file_operator = fields.Char("Сохранил", readonly=True, copy=False)
    file_saved_text = fields.Char(
        "Сохранён", readonly=True, copy=False,
        help="Время, как его записал CypCut. Это местное время станка, "
             "поэтому оно показано текстом и никуда не пересчитывается: "
             "перевод «из UTC» увёл бы вечерние раскрои на следующие сутки.")
    contour_count = fields.Integer(
        "Контуров в файле", readonly=True, copy=False,
        help="Число замкнутых контуров в раскладке. Почти равно числу проколов "
             "и служит перекрёстной проверкой того, что дали чертежи.")
    technical_is_demo = fields.Boolean("Режимы демонстрационные", readonly=True, copy=False)
    technical_note = fields.Char("Что объявлено в файле", readonly=True, copy=False)
    parse_warning = fields.Text("Замечания разбора", readonly=True, copy=False)
    # Разбор UX, шаг 27 (доводка): признаком «файл разобран» в форме служили
    # листы (sheet_ids). Технолог перевыгрузил раскладку и приложил новый
    # .lxds — листы и детали на экране от прежнего файла, а в шапке только
    # контурная «Разобрать заново»: залитой кнопки следующего шага нет, и то,
    # что листы старые, легко не заметить. Флаг ставит write() при смене
    # файла у разобранного задания (сверка контрольной суммы вложения: тот же
    # файл заново — не замена), снимает action_parse_file. Хранимый, без
    # миграции: у заданий до этой версии он пуст (False) — как и было.
    file_replaced = fields.Boolean(
        "Файл заменён после разбора", readonly=True, copy=False,
        help="Файл раскроя приложили заново, а листы и детали — от прежнего "
             "файла. Снимается разбором файла.")
    # Разбор UX, шаг 36: блок «Файл раскроя» — четыре строки служебных
    # сведений (программа, кто сохранил, когда, контуров) над вкладками —
    # стал одной серой строкой под полем «Файл»: «CypCut 6.3 · сохранил XE ·
    # 08.09.2026 14:34 · 65 контуров». Четыре поля на месте, их пишет разбор
    # файла; строка их только складывает (labels.file_info_line). Не хранится.
    file_info = fields.Char(
        "Сведения о файле", compute="_compute_file_info",
        help="Программа раскроя, кто и когда сохранил файл, сколько в нём "
             "контуров. Время — как его записал CypCut: местное время станка, "
             "без пересчёта поясов. Контуров почти столько же, сколько "
             "проколов, — перекрёстная проверка того, что дали чертежи.")

    # ------------------------------------------------------------------
    # Материал
    # ------------------------------------------------------------------
    sheet_id = fields.Many2one(
        "pmk.metal.sheet", "Лист по справочнику", tracking=True,
        help="Отсюда берётся масса квадратного метра — и только отсюда. "
             "Плотность не используется: у рифлёного листа квадрат на 5–7% "
             "тяжелее гладкого, у просечно-вытяжного металла 37–63% габарита, "
             "и справочник это уже знает, а формула по плотности — нет.")
    sheet_type = fields.Char(related="sheet_id.sheet_type", string="Вид листа", store=True, readonly=True)
    # Толщина и масса м² берут aggregator=None у справочника листа
    # (pmk_calc, шаг 24): связанное поле копирует его, если своего нет.
    thickness_mm = fields.Float(related="sheet_id.thickness_mm", string="Толщина, мм", store=True, readonly=True)
    mass_per_sqm = fields.Float(related="sheet_id.mass_per_sqm", string="Масса, кг/м²", readonly=True)
    grade_id = fields.Many2one("pmk.metal.grade", "Марка стали")

    kerf_mm = fields.Float(
        "Ширина реза, мм", digits=(4, 2), default=money.DEFAULT_KERF_MM, required=True, aggregator=None,
        help="Полоска металла, которую рез уносит в пыль на всю толщину. "
             "Значение своё, а не из файла: раздел с режимами у технолога "
             "демонстрационный. Без этой строки лом в балансе всегда "
             "«больше расчётного», и непонятно почему.")
    min_offcut_mm = fields.Float(
        "Обрезок от, мм", digits=(8, 0), default=money.DEFAULT_MIN_OFFCUT_MM, required=True, aggregator=None,
        help="Короче этого остаток в реестр не заводится — место на стеллаже "
             "дороже металла.")

    part_ids = fields.One2many("pmk.laser.job.part", "job_id", "Детали", copy=True)
    sheet_ids = fields.One2many("pmk.laser.job.sheet", "job_id", "Листы", copy=False)
    operator_ids = fields.One2many("pmk.laser.job.operator", "job_id", "Операторы", copy=True)
    offcut_ids = fields.One2many("pmk.laser.offcut", "job_id", "Обрезки", copy=False)
    measure_ids = fields.One2many("pmk.laser.measure", "job_id", "Замеры", copy=False)

    # ------------------------------------------------------------------
    # Металл и деньги
    # ------------------------------------------------------------------
    sheet_count = fields.Integer("Листов", compute="_compute_metal", store=True)
    gross_area_m2 = fields.Float("Куплено, м²", compute="_compute_metal", store=True, digits=(12, 2))
    useful_area_m2 = fields.Float("Полезно, м²", compute="_compute_metal", store=True, digits=(12, 2))
    # Теория бывшей вкладки «Баланс металла» (разбор UX, шаг 36) — в
    # подсказках «?» полей баланса: сама вкладка ушла строкой карточек над
    # вкладками.
    mass_kg = fields.Float(
        "Списано металла, кг", compute="_compute_metal", store=True, digits=(12, 1),
        help="Вес списанных листов = детали + обрезки + пропил + лом. Лом не "
             "вводят, он получается вычитанием — и именно поэтому по нему "
             "видно, что обрезки не оприходуют или что раскладка плохая.")
    useful_mass_kg = fields.Float(
        "Полезный вес, кг", compute="_compute_metal", store=True, digits=(12, 1),
        help="Вес разложенных деталей. За него платит заказчик и от него "
             "считается премия — не от веса купленного листа.")
    sheets_note = fields.Char("Сколько листов", compute="_compute_sheets_note")
    # «Оживить таблицы» (29.09.2026): в строке группы пусто. Сумма процентов
    # (по умолчанию у Odoo) бессмысленна, а простое среднее обманывает:
    # задание без раскладки хранит 0 % и тянет группу вниз, и оно не
    # взвешено по металлу.
    utilization_pct = fields.Float("Использование, %", compute="_compute_metal", store=True, digits=(5, 1), aggregator=None)

    # Шаг 24: ставку и процент расхождения в строке группы не складываем —
    # сумма ставок ₽/т и процентов ничего не значит. Премия, вес, листы и
    # минуты складываются как раньше (и в сводной «Загрузки участка»).
    premium_rate_rub = fields.Float(
        "Ставка премии, ₽/т", compute="_compute_premium", store=True, digits=(8, 0), aggregator=None)
    premium_rub = fields.Float(
        "Премия, ₽", compute="_compute_premium", store=True, digits=(10, 2), tracking=True,
        help="От полезного веса, а не от веса листа: 500 ₽/т на листе от 3 мм "
             "включительно, 3000 ₽/т тоньше — на тонком листе деталей в разы "
             "больше при том же весе. Делится между операторами смены поровну "
             "(вкладка «Операторы и премия»).")

    cut_length_m = fields.Float("Длина реза, м", compute="_compute_denominator", store=True, digits=(12, 2))
    pierce_count = fields.Integer("Проколов", compute="_compute_denominator", store=True)
    parts_without_drawing = fields.Integer("Деталей без чертежа", compute="_compute_denominator", store=True)
    contour_gap_pct = fields.Float(
        "Расхождение с контурами, %", compute="_compute_denominator", store=True, digits=(6, 1), aggregator=None,
        help="Насколько число проколов по чертежам расходится с числом "
             "контуров в файле раскроя. Большое расхождение значит, что "
             "к деталям приложены не те чертежи.")

    kerf_mass_kg = fields.Float(
        "Пропил, кг", compute="_compute_balance", store=True, digits=(12, 2),
        help="Металл, который рез уносит в пыль: длина реза × ширина реза "
             "(вкладка «Обрезки», «Параметры») на всю толщину. На десятке метр "
             "реза уносит 15,7 г. Без этой строки лом в балансе всегда "
             "«больше расчётного», и непонятно почему.")
    offcut_mass_kg = fields.Float(
        "Обрезки, кг", compute="_compute_balance", store=True, digits=(12, 1),
        help="Только подтверждённые обрезки: предложение системы — ещё не "
             "кусок на стеллаже.")
    scrap_mass_kg = fields.Float(
        "Лом, кг", compute="_compute_balance", store=True, digits=(12, 1),
        help="Не вводится, а получается вычитанием: списано минус детали, "
             "обрезки и пропил. Систематический перекос в лом означает либо "
             "что обрезки не оприходуют, либо что раскладка плохая.")
    balance_broken = fields.Boolean("Баланс не сходится", compute="_compute_balance", store=True)
    # Разбор UX, шаг 36: лом — главная цифра экономии металла (премия от
    # маржи). Доля хранится: по ней сортирует список и ищет фильтр «Много
    # лома». Подпись — «Лом, % (число)»: в меню колонок (⚙) рядом стоит
    # «Лом, %» словом, и это одно и то же число (доводка шага 36).
    scrap_pct = fields.Float(
        "Лом, % (число)", compute="_compute_balance", store=True, digits=(5, 1), aggregator=None,
        help="Лом от веса списанных листов — то же число, что «Лом, %» словом, "
             "но им можно сортировать и фильтровать.")
    # ⚠️ «МНОГО» НЕ ХРАНИТСЯ (доводка шага 36). Порог — решение по умолчанию
    # (money.SCRAP_HIGH_PCT), владелец может его сменить. Хранимый признак
    # после смены константы не пересчитался бы (зависимости те же, -u
    # досчитывает только новые колонки): задание с 17 % при пороге 15 %
    # писало бы «· много» без жёлтой плашки, и фильтр бы его не находил.
    # Теперь подпись и признак считаются при открытии от хранимой доли одним
    # решением (labels.scrap_signal), а фильтр ищет по той же доле
    # (_search_scrap_high) — порог действует сразу и везде. Число в
    # подсказках — из той же константы.
    scrap_high = fields.Boolean(
        "Много лома", compute="_compute_scrap_signal", search="_search_scrap_high",
        help="Лом больше %s списанного металла. Сигнал, а не запрет: обычно "
             "это неоприходованный цельный обрезок или плохая раскладка. "
             "Подтвердили обрезок — лом уменьшится, сигнал погаснет сам."
             % labels.pct(money.SCRAP_HIGH_PCT))
    scrap_label = fields.Char(
        "Лом, %", compute="_compute_scrap_signal",
        help="Доля лома от списанного металла. Больше %s — жёлтым и словом "
             "«много»; баланс не сходится — «не сходится»."
             % labels.pct(money.SCRAP_HIGH_PCT))

    # ------------------------------------------------------------------
    # Деньги металла (разбор UX, шаг 36)
    # ------------------------------------------------------------------
    # Не хранятся: связь с ценами мягкая (шапка файла), а цену заводят и
    # правят заливкой прайса — хранимое значение устаревало бы молча.
    # ⚠️ ДВА ЗНАКА, А НЕ ЦЕЛЫЕ (доводка шага 36). Присвоение в вычислении
    # проходит через кеш, а кеш Float округляет до знаков поля
    # (orm/fields_numeric.py, convert_to_cache): с digits=(12, 0) поле
    # хранило бы 72 914 вместо 72 913,52. Как у строки расчёта (price_ton,
    # pmk_bridge) — до копеек; на экран цена идёт строкой «Цена металла»,
    # округлённой до рубля.
    metal_price_ton = fields.Float(
        "Цена металла, ₽/т", compute="_compute_metal_money", digits=(12, 2))
    metal_price_note = fields.Char("Цена металла", compute="_compute_metal_money")
    metal_price_missing = fields.Boolean("Нет цены металла", compute="_compute_metal_money")
    metal_rub = fields.Float(
        "Металл, ₽", compute="_compute_metal_money", digits=(12, 2),
        help="Списанный металл (вес списанных листов) по цене поставщика за "
             "тонну — той же, что в расчёте: задание привязано к расчёту и "
             "лист в нём с ценой — цена строки расчёта, как она стоит в нём "
             "(«из расчёта»); иначе по правилу расчёта — его поставщик и дата "
             "цен, без расчёта — поставщик с лучшим рейтингом на дату "
             "задания, базовый уровень объёма. Цены нет — позиции нет в "
             "прайсах («в городе нет»): это сигнал, а не ноль.")
    scrap_rub = fields.Float(
        "Лом, ₽", compute="_compute_metal_money", digits=(12, 2),
        help="Столько стоил металл, ушедший в лом, — по той же цене за тонну. "
             "Цены сдачи лома в базе нет; появится — лом можно будет считать "
             "по ней. Баланс не сходится — вместо суммы «не сходится»: "
             "стоимость отрицательного лома ничего не значит.")

    # ------------------------------------------------------------------
    # «Очередь листов» (доводка шага 36)
    # ------------------------------------------------------------------
    # Убрать листы из очереди было нечем: «Готов» у листа значит только «есть
    # закрытый замер». Брошенное и пробное задание, раскрой, отрезанный без
    # кнопок, старое задание, чей файл заменили после замеров, — их листы
    # «Ждут» навсегда и стоят над текущей работой (старые задания первыми).
    # Снять — фиктивным замером (ложь в факт и норматив) или удалив задание
    # вместе с премией. Теперь задание снимают с очереди — ⚙ «Действие» →
    # «Снять с очереди» (и «Вернуть в очередь»). Ничего не удаляется, замеры,
    # премия и норматив не меняются; лист, который режется, из очереди не
    # уходит, пока его не закончат.
    queue_closed = fields.Boolean(
        "Снято с очереди", copy=False, tracking=True,
        help="Неотрезанные листы задания не показываются в «Очереди листов»: "
             "задание брошено или пробное, раскрой отрезали без кнопок, файл "
             "заменили после замеров и новый приложили к новому заданию. "
             "Замеры, премия и норматив не меняются; лист, который режется, "
             "остаётся в очереди, пока его не закончат. Снять и вернуть — "
             "⚙ «Действие» в задании или в списке заданий.")
    queue_closed_note = fields.Char(
        "Очередь", compute="_compute_queue_closed_note",
        help="Задание снято с «Очереди листов», а неотрезанные листы у него "
             "есть. Вернуть — ⚙ «Действие» → «Вернуть в очередь».")

    # Строка действия вкладки «Обрезки» — только пока есть что подтверждать.
    offcut_proposed_count = fields.Integer(
        "Ждут подтверждения", compute="_compute_offcut_proposed_count", aggregator=None,
        help="Обрезки, предложенные системой и ещё не подтверждённые "
             "технологом: в баланс металла они не идут.")

    # ------------------------------------------------------------------
    # План и факт
    # ------------------------------------------------------------------
    # Разбор UX, шаг 36: подписи короткие — значки в списке заданий
    # («Грубо: рез и проколы не разделены», «Все листы замерены») обрезались
    # на полуслове. Те же слова — у норматива (norm.py, mode) и в узле схемы
    # связей (pmk_flow, _LASER_PLAN): одно понятие — одно слово. Полный смысл
    # каждого значения — в подсказке «?».
    plan_state = fields.Selection(
        [("ok", "Норматив есть"),
         ("rough", "Норматив грубый"),
         ("no_norm", "Нет норматива"),
         ("no_drawing", "Рез не разобран")],
        "План", compute="_compute_plan", store=True, default="no_drawing",
        help="Норматив есть — план считается по замерам этой толщины на этом "
             "станке. Норматив грубый — рез и проколы не разделены: минуты на "
             "метр реза есть, время прокола отдельно не выведено. Нет "
             "норматива — на этой толщине ещё нет ни одного замера; среднее по "
             "соседним толщинам не подставляется. Рез не разобран — у деталей "
             "нет длины реза: приложите и разберите чертежи.")
    planned_minutes = fields.Float(
        "План, мин", compute="_compute_plan", store=True, digits=(10, 1),
        help="Загрузка и разгрузка стола на каждый лист плюс резка по "
             "нормативу. Пока по толщине нет ни одного замера, план остаётся "
             "пустым — среднее по соседним толщинам не подставляется.")
    # Счётчик для сводной таблицы «Загрузки участка»: рядом с «План, мин» видно,
    # сколько заданий в этом дне ещё без плана. Без него ноль минут читается
    # как «станок свободен» (разбор UX, решение Антона 28.09.2026).
    plan_missing = fields.Integer(
        "Заданий без плана", compute="_compute_plan", store=True,
        help="1, если у задания нет норматива или не разобрана длина реза.")
    actual_minutes = fields.Float("Факт, мин", compute="_compute_fact", store=True, digits=(10, 1))
    measure_state = fields.Selection(
        [("none", "Не мерили"), ("partial", "Мерили часть"), ("done", "Замерено")],
        "Замеры", compute="_compute_fact", store=True, default="none",
        help="Не мерили — ни у одного листа нет замера. Мерили часть — "
             "замерены не все листы. Замерено — замер есть у каждого листа; "
             "только такое задание идёт в норматив: знаменатель (метры реза и "
             "проколы) известен по заданию целиком, а не по листу.")

    # ==================================================================
    # Вычисления
    # ==================================================================

    @api.depends("sheet_ids.area_m2", "sheet_ids.useful_area_m2",
                 "sheet_ids.mass_kg", "sheet_ids.useful_mass_kg")
    def _compute_metal(self):
        for job in self:
            sheets = job.sheet_ids
            job.sheet_count = len(sheets)
            job.gross_area_m2 = sum(sheets.mapped("area_m2"))
            job.useful_area_m2 = sum(sheets.mapped("useful_area_m2"))
            job.mass_kg = sum(sheets.mapped("mass_kg"))
            job.useful_mass_kg = sum(sheets.mapped("useful_mass_kg"))
            job.utilization_pct = (
                100.0 * job.useful_area_m2 / job.gross_area_m2 if job.gross_area_m2 else 0.0)

    @api.depends("useful_mass_kg", "thickness_mm")
    def _compute_premium(self):
        for job in self:
            job.premium_rate_rub = money.premium_rate(job.thickness_mm) if job.thickness_mm else 0.0
            job.premium_rub = money.premium_rub(job.useful_mass_kg, job.thickness_mm)

    @api.depends("part_ids.cut_length_total_m", "part_ids.pierces_total",
                 "part_ids.cut_length_mm", "contour_count")
    def _compute_denominator(self):
        for job in self:
            parts = job.part_ids
            job.parts_without_drawing = len(parts.filtered(lambda p: p.cut_length_mm <= 0.0))
            # Знаменатель считаем ТОЛЬКО когда разобраны все детали. Половина
            # деталей дала бы половину метров — и норматив, посчитанный по
            # такому знаменателю, был бы вдвое быстрее настоящего.
            if parts and not job.parts_without_drawing:
                job.cut_length_m = sum(parts.mapped("cut_length_total_m"))
                job.pierce_count = sum(parts.mapped("pierces_total"))
            else:
                job.cut_length_m = 0.0
                job.pierce_count = 0
            job.contour_gap_pct = (
                100.0 * abs(job.pierce_count - job.contour_count) / job.contour_count
                if job.contour_count and job.pierce_count else 0.0)

    @api.depends("mass_kg", "useful_mass_kg", "cut_length_m", "kerf_mm", "mass_per_sqm",
                 "offcut_ids.mass_kg", "offcut_ids.state")
    def _compute_balance(self):
        for job in self:
            job.kerf_mass_kg = money.mass_kg(
                money.kerf_area_m2(job.cut_length_m, job.kerf_mm), job.mass_per_sqm)
            # В баланс идут только подтверждённые обрезки: предложение системы —
            # ещё не металл на стеллаже.
            confirmed = job.offcut_ids.filtered(lambda o: o.state == "confirmed")
            job.offcut_mass_kg = sum(confirmed.mapped("mass_kg"))
            job.scrap_mass_kg = money.scrap_mass_kg(
                job.mass_kg, job.useful_mass_kg, job.offcut_mass_kg, job.kerf_mass_kg)
            job.balance_broken = job.mass_kg > 0.0 and job.scrap_mass_kg < 0.0
            # Доля — от уже округлённых весов, как их видит человек (кеш
            # хранимого поля округляет до знаков поля), и хранится с одним
            # знаком: по ней же решают подпись, плашка и фильтр «Много лома».
            job.scrap_pct = money.scrap_pct(job.scrap_mass_kg, job.mass_kg)

    @api.depends("scrap_pct", "mass_kg", "balance_broken")
    def _compute_scrap_signal(self):
        """«Лом, %» словом и признак «много» — одним решением по хранимой доле
        (labels.scrap_signal): «27 % · много» всегда с жёлтой плашкой, и
        фильтр находит ровно эти задания (_search_scrap_high)."""
        for job in self:
            label, high = labels.scrap_signal(job.scrap_pct, job.mass_kg, job.balance_broken)
            job.scrap_label = label or False
            job.scrap_high = high

    def _search_scrap_high(self, operator, value):
        """Фильтр «Много лома» — по хранимой доле с тем же порогом, что у
        признака: доля с одним знаком строго больше порога, баланс сходится,
        металл списан. Порог читается при каждом поиске.

        Odoo 19 приводит условие на логическое поле к «in [True]» (orm/
        domains.py, _optimize_boolean_in); «не много» ядро получает само —
        отрицанием этого же условия.
        """
        if operator != "in":
            return NotImplemented
        return [
            ("balance_broken", "=", False),
            ("mass_kg", ">", 0.0),
            ("scrap_pct", ">", money.SCRAP_HIGH_PCT),
        ]

    @api.depends("file_app", "file_operator", "file_saved_text", "contour_count")
    def _compute_file_info(self):
        for job in self:
            job.file_info = labels.file_info_line(
                job.file_app, job.file_operator, job.file_saved_text, job.contour_count) or False

    @api.depends("sheet_count")
    def _compute_sheets_note(self):
        for job in self:
            job.sheets_note = labels.sheets_note(job.sheet_count) or False

    @api.depends("queue_closed", "sheet_ids.cut_state")
    def _compute_queue_closed_note(self):
        for job in self:
            waiting = len(job.sheet_ids.filtered(lambda s: s.cut_state == "waiting"))
            job.queue_closed_note = (
                labels.queue_closed_note(waiting) if job.queue_closed else "") or False

    @api.depends("offcut_ids.state")
    def _compute_offcut_proposed_count(self):
        for job in self:
            job.offcut_proposed_count = len(job.offcut_ids.filtered(lambda o: o.state == "proposal"))

    # ------------------------------------------------------------------
    # Деньги металла (разбор UX, шаг 36)
    # ------------------------------------------------------------------

    @api.depends("sheet_id", "date", "spec_id", "mass_kg", "scrap_mass_kg", "balance_broken")
    def _compute_metal_money(self):
        for job in self:
            price_ton, note, missing = job._metal_price()
            job.metal_price_ton = price_ton
            job.metal_price_note = note
            job.metal_price_missing = missing
            # От локальной цены, а не от поля: кеш округлил бы её до знаков.
            job.metal_rub = money.rub_from_ton(job.mass_kg, price_ton)
            # Баланс не сходится — лом отрицательный, и его «стоимость» ничего
            # не значит (доводка шага 36): в карточке вместо суммы слово «не
            # сходится», отрицательных денег в задании нет.
            job.scrap_rub = 0.0 if job.balance_broken else money.rub_from_ton(
                job.scrap_mass_kg, price_ton)

    @api.model
    def _pmk_price_ready(self):
        """Стоит ли мост номенклатуры (pmk_bridge) — источник цены листа.

        Связь МЯГКАЯ, как у раскроя (pmk_cut, _pmk_price_bars_ready): в
        зависимостях pmk_laser моста нет — удаление stock_account или
        модулей RuOdoo, на которых он держится, каскадом снесло бы участок
        со всеми заданиями и замерами. От моста нужны связь листа с карточкой
        товара (pmk.metal.sheet.product_tmpl_id), выбор строки прайса
        (product.template._pmk_find_seller) и масса единицы
        (pmk.metal.sheet._pmk_mass_per_unit).
        """
        env = self.env
        return (
            "product_tmpl_id" in env["pmk.metal.sheet"]._fields
            and hasattr(env["product.template"], "_pmk_find_seller")
            and hasattr(env["pmk.metal.sheet"], "_pmk_mass_per_unit"))

    def _spec_sheet_line(self, sheet):
        """Строка расчёта с этим листом и ценой — или пустой набор.

        Задание привязано к расчёту — металл в задании стоит столько же,
        сколько в расчёте (доводка шага 36). Строка расчёта держит цену
        снимком (pmk_bridge, spec_cost.py: price_ton, «Поставщик цены»,
        «Прайс от») и сама не перечитывается: новая заливка прайса доходит до
        неё только кнопкой «Перечитать цены». Выбирать строку прайса заново
        значило бы разойтись с расчётом — когда цены в нём не перечитаны,
        когда прайс залили заново, когда «Цены на дату» пусты (расчёт
        посчитан «сегодня» того дня, а не нынешнего).

        Строк с этим листом несколько — первая по порядку расчёта. Поля
        цены строки ставит мост; без них (моста нет) — пустой набор.
        """
        Line = self.env["pmk.metal.spec.line"]
        needed = ("calc_mode", "sheet_id", "price_state", "price_ton",
                  "price_partner_id", "price_date_used")
        if not self.spec_id or not sheet or any(name not in Line._fields for name in needed):
            return Line
        return Line.search([
            ("spec_id", "=", self.spec_id.id),
            ("calc_mode", "=", "sheet"),
            ("sheet_id", "=", sheet.id),
            ("price_state", "=", "ok"),
            ("price_ton", ">", 0.0),
        ], limit=1)

    def _metal_price(self):
        """Цена металла задания: (₽ за тонну, пояснение, цены нет).

        ОДНА ДВЕРЬ С РАСЧЁТОМ. Задание привязано к расчёту, и лист в нём
        есть с ценой — цена этой строки расчёта, как она в нём стоит
        (_spec_sheet_line, пояснение «из расчёта»). Иначе строку прайса
        выбирает тот же метод, что и расчёт (product.template.
        _pmk_find_seller: действует на дату, поставщик расчёта или лучший по
        рейтингу, базовый уровень объёма), и масса листа — то же правило
        (_pmk_mass_per_unit: вес листа с карточки): при расчёте — его дата
        цен (пусто — сегодня, как у расчёта) и поставщик, без расчёта — дата
        задания (день резки) и лучший поставщик.

        Цены нет — не ноль, а слово: «нет в прайсах» — позиции нет у
        поставщиков города (сигнал, не ошибка данных; на 02.10.2026 цены
        есть у 14 листов справочника из 57). Валюту не пересчитываем: без
        курса пересчёт прошёл бы один к одному.
        """
        self.ensure_one()
        sheet = self.sheet_id
        if not sheet:
            return 0.0, "лист не выбран", True
        if not self._pmk_price_ready():
            return 0.0, "цены поставщиков не подключены", True
        try:
            line = self._spec_sheet_line(sheet)
            if line:
                currency = line.currency_id if "currency_id" in line._fields else False
                if currency and currency != self.env.company.currency_id:
                    return 0.0, "цена в расчёте не в рублях (%s)" % currency.name, True
                return line.price_ton, labels.price_note(
                    line.price_ton, line.price_partner_id.display_name,
                    line.price_date_used, source="из расчёта"), False
            tmpl = sheet.product_tmpl_id
            if not tmpl:
                return 0.0, "у листа нет карточки товара", True
            spec = self.spec_id
            if spec:
                # Правило расчёта целиком (pmk_bridge, _cost_find_seller):
                # «Цены на дату» пусты — сегодня, а не дата задания.
                on_date = ((spec.price_date if "price_date" in spec._fields else False)
                           or fields.Date.context_today(self))
            else:
                on_date = self.date or fields.Date.context_today(self)
            supplier = spec.supplier_id if spec and "supplier_id" in spec._fields else False
            seller = tmpl._pmk_find_seller(on_date, supplier=supplier or None)
            if not seller:
                if supplier:
                    return 0.0, "нет в прайсе поставщика расчёта (%s)" % supplier.display_name, True
                return 0.0, "нет в прайсах — позиции нет у поставщиков города", True
            if seller.currency_id and seller.currency_id != self.env.company.currency_id:
                return 0.0, "цена поставщика не в рублях (%s)" % seller.currency_id.name, True
            mass_unit = sheet._pmk_mass_per_unit(tmpl)
            if not mass_unit:
                # Мина листа (pmk_bridge, reference_link.py): второй габарит
                # обнулит вес карточки — цены за тонну не будет.
                return 0.0, "неизвестен вес листа на карточке товара", True
            if not seller.price_discounted:
                return 0.0, "в прайсе цена 0", True
            price_ton = money.per_ton(seller.price_discounted, mass_unit)
            return price_ton, labels.price_note(
                price_ton, seller.partner_id.display_name, seller.date_start), False
        except AccessError:
            # Прайсы и карточки товаров закрыты правами — деньги не покажем,
            # но форма откроется.
            return 0.0, "нет доступа к ценам поставщиков", True

    @api.depends("cut_length_m", "pierce_count", "sheet_count", "machine_id",
                 "machine_id.load_min", "machine_id.unload_min",
                 "sheet_type", "thickness_mm")
    def _compute_plan(self):
        norms = self.env["pmk.laser.norm"]
        for job in self:
            handling = job.sheet_count * (job.machine_id.load_min + job.machine_id.unload_min)
            if job.cut_length_m <= 0.0:
                job.plan_state = "no_drawing"
                job.planned_minutes = 0.0
                job.plan_missing = 1
                continue
            norm = norms._lookup(job.machine_id, job.sheet_type, job.thickness_mm)
            cutting = timing.estimate_minutes(
                norm.mode, norm.min_per_m, norm.speed_mm_min, norm.pierce_time_s,
                job.cut_length_m, job.pierce_count) if norm else None
            if cutting is None:
                # Ни одного замера на этой толщине. Показываем пусто, а не
                # среднее по соседним толщинам: выдуманный план хуже
                # отсутствующего — по нему поставят срок заказчику.
                job.plan_state = "no_norm"
                job.planned_minutes = 0.0
                job.plan_missing = 1
                continue
            job.plan_state = "ok" if norm.mode == timing.MODE_FULL else "rough"
            job.planned_minutes = handling + cutting
            job.plan_missing = 0

    @api.depends("sheet_ids.actual_minutes", "sheet_ids.measure_ids.state",
                 "sheet_ids.measure_ids.excluded")
    def _compute_fact(self):
        for job in self:
            sheets = job.sheet_ids
            job.actual_minutes = sum(sheets.mapped("actual_minutes"))
            measured = len(sheets.filtered(lambda s: s.actual_minutes > 0.0))
            if not sheets or not measured:
                job.measure_state = "none"
            elif measured < len(sheets):
                job.measure_state = "partial"
            else:
                job.measure_state = "done"

    # ==================================================================
    # Создание
    # ==================================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.laser.job") or "Черновик"
        return super().create(vals_list)

    def _file_checksums(self):
        """Контрольные суммы приложенных файлов раскроя: {id задания: sha1}.

        Файл хранится вложением (attachment=True), сумму ведёт ядро
        (ir.attachment.checksum). sudo — как у самого поля в ядре
        (fields_binary.py): читаем только суммы вложений этих заданий."""
        if not self.ids:
            return {}
        attachments = self.env["ir.attachment"].sudo().search([
            ("res_model", "=", self._name),
            ("res_field", "=", "file"),
            ("res_id", "in", self.ids),
        ])
        return {attachment.res_id: attachment.checksum for attachment in attachments}

    def write(self, vals):
        """Новый файл у разобранного задания — флаг «Файл заменён после
        разбора» (file_replaced, доводка шага 27): листы и детали остаются от
        прежнего файла, пока технолог не разберёт новый, и форма снова
        показывает залитую «Разобрать файл». Тот же файл заново (сумма та
        же) — не замена. Файл убрали — флаг не трогаем: без файла кнопки
        разбора и сигнал скрыты, а новый файл сверится с пустотой. Флаг,
        переданный явно, не перебиваем."""
        if "file" not in vals or "file_replaced" in vals:
            return super().write(vals)
        parsed = self.filtered("sheet_ids")
        before = parsed._file_checksums()
        result = super().write(vals)
        after = parsed._file_checksums()
        replaced = parsed.filtered(
            lambda job: after.get(job.id) and after[job.id] != before.get(job.id))
        if replaced:
            replaced.write({"file_replaced": True})
        return result

    @api.onchange("spec_id")
    def _onchange_spec_id(self):
        """Заказчик берётся из расчёта, если в задании его ещё нет.

        Заполненного не перетираем — тот же приём, что у сделки в расчёте
        (pmk_deal): выбор технолога важнее автоподстановки.
        """
        for job in self:
            if job.spec_id and not job.partner_id:
                job.partner_id = job.spec_id.partner_id

    # ==================================================================
    # Разбор файла раскроя
    # ==================================================================

    def _read_layout(self):
        """Отдать разобранный .lxds.

        Файл кладём во временную папку ПОД ЕГО СОБСТВЕННЫМ ИМЕНЕМ: толщина
        берётся из имени, и под случайным именем tmp7xk разбор честно вернёт
        «толщины в имени нет».
        """
        self.ensure_one()
        from ..tools import lxds  # разбор живёт в tools/, Odoo ему не нужен

        if not self.file:
            raise UserError(_("Сначала приложите файл раскроя .lxds"))
        file_name = self.file_name or "raskroy.lxds"
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, file_name)
            with open(path, "wb") as handle:
                handle.write(base64.b64decode(self.file))
            return lxds.read_layout(path)

    def _sheet_from_reference(self, thickness_mm, sheet_type):
        """Найти лист в справочнике pmk_calc по толщине и виду."""
        self.ensure_one()
        if not thickness_mm:
            raise UserError(_(
                "В имени файла «%s» нет толщины листа. Толщину пишут в имя для "
                "оператора станка — верить разделу с режимами нельзя, он у "
                "технолога демонстрационный.") % (self.file_name or ""))
        domain = [
            ("sheet_type", "=", sheet_type),
            ("thickness_mm", ">=", thickness_mm - THICKNESS_TOLERANCE_MM),
            ("thickness_mm", "<=", thickness_mm + THICKNESS_TOLERANCE_MM),
        ]
        sheets = self.env["pmk.metal.sheet"].search(domain)
        if not sheets:
            raise UserError(_(
                "Листа «%(type)s» %(thick)g мм нет в справочнике. Без массы "
                "квадратного метра полезный вес не посчитать, а брать её через "
                "плотность нельзя: у рифлёного и просечно-вытяжного листа она "
                "другая.") % {"type": sheet_type, "thick": thickness_mm})
        if len(sheets) > 1:
            labels = ", ".join(sheets.mapped(lambda s: s.size_label or "без типоразмера"))
            raise UserError(_(
                "Лист «%(type)s» %(thick)g мм есть в нескольких исполнениях "
                "(%(labels)s) — выберите нужный вручную, масса квадрата у них "
                "разная.") % {"type": sheet_type, "thick": thickness_mm, "labels": labels})
        return sheets

    def action_parse_file(self):
        """Разобрать приложенный .lxds и разложить его по документу."""
        for job in self:
            if job.measure_ids:
                raise UserError(_(
                    "По заданию уже есть замеры — перечитывать файл нельзя: "
                    "листы пересоздадутся, и замеры операторов пропадут. "
                    "Если раскрой переделали, заведите новое задание."))
            layout = job._read_layout()
            if job.sheet_id:
                # Лист выбрали руками (например, рифлёный — из имени файла вид
                # не виден). Толщину всё равно сверяем: имя файла — пометка для
                # оператора станка, и расхождение с ней означает, что к заданию
                # приложили чужой раскрой.
                if layout.thickness_mm and abs(
                        job.thickness_mm - layout.thickness_mm) > THICKNESS_TOLERANCE_MM:
                    raise UserError(_(
                        "В задании выбран лист %(chosen)g мм, а в имени файла "
                        "«%(file)s» стоит %(file_thick)g мм. Толщину в имя пишут "
                        "для оператора станка — либо файл не тот, либо лист."
                    ) % {"chosen": job.thickness_mm, "file": job.file_name or "",
                         "file_thick": layout.thickness_mm})
                sheet = job.sheet_id
            else:
                sheet = job._sheet_from_reference(layout.thickness_mm, DEFAULT_SHEET_TYPE)

            declared = layout.technical_declared or {}
            values = {
                "sheet_id": sheet.id,
                "file_app": ("%s %s" % (layout.app_name, layout.app_version)).strip(),
                "file_operator": layout.operator,
                "file_saved_text": layout.saved_at_raw,
                "contour_count": layout.contours,
                "technical_is_demo": layout.demo_modes,
                "technical_note": _("в файле объявлено: толщина %(thick)s, материал %(mat)s") % {
                    "thick": declared.get("thickness") or "—",
                    "mat": declared.get("material") or "—",
                },
                "parse_warning": "\n".join(layout.warnings),
                "part_ids": job._part_commands(layout),
                "sheet_ids": job._sheet_commands(layout),
                # Листы теперь от этого файла (доводка шага 27, см. write).
                "file_replaced": False,
            }
            if layout.saved_at:
                # Берём только ДАТУ: время в файле местное, и переводить его в
                # UTC значит сдвинуть вечерние раскрои на сутки вперёд.
                values["date"] = layout.saved_at.date()
            job.write(values)

            message = _(
                "Файл разобран: %(sheets)s листов, %(parts)s деталей, "
                "%(contours)s контуров.") % {
                    "sheets": layout.sheet_count,
                    "parts": layout.parts_declared,
                    "contours": layout.contours,
            }
            if layout.demo_modes:
                message += _(
                    "<br/>Параметры резки в файле демонстрационные — толщина взята "
                    "из имени файла (%s).") % layout.thickness_source
            if layout.warnings:
                message += "<br/>" + "<br/>".join(layout.warnings)
            job.message_post(body=message)
        return True

    def _part_commands(self, layout):
        """Команды на пересоздание деталей с сохранением уже разобранных чертежей.

        Чертёж прикладывает технолог руками, и терять его при повторном разборе
        файла нельзя. Сопоставляем по имени детали — это то же имя, которым она
        названа в раскрое («Крайняя часть отвода - 12шт»).
        """
        self.ensure_one()
        kept = {
            part.name: {
                "drawing": part.drawing,
                "drawing_name": part.drawing_name,
                "cut_length_mm": part.cut_length_mm,
                "pierce_count": part.pierce_count,
                "preview_svg": part.preview_svg,
            }
            for part in self.part_ids
        }
        commands = [fields.Command.clear()]
        for part in layout.parts:
            values = {"name": part.name, "qty": part.amount, "qty_used": part.amount_used}
            values.update(kept.get(part.name, {}))
            commands.append(fields.Command.create(values))
        return commands

    def _sheet_commands(self, layout):
        """Развернуть раскладки в физические листы.

        В файле кронштейнов одна раскладка на 89,2% повторена семь раз — это
        семь листов, а не один. Считать раскладки вместо листов значит занизить
        полезный вес в семь раз, а вместе с ним и премию.
        """
        self.ensure_one()
        commands = [fields.Command.clear()]
        number = 0
        for nest in layout.nests:
            for _copy in range(nest.plate_amount):
                number += 1
                commands.append(fields.Command.create({
                    "number": number,
                    "nest_index": nest.index,
                    "width_mm": nest.width_mm,
                    "length_mm": nest.height_mm,
                    "utilization_pct": nest.utilization_pct,
                }))
        return commands

    def action_parse_drawings(self):
        """Разобрать чертежи деталей: длина реза, проколы, эскиз."""
        for job in self:
            without = job.part_ids.filtered(lambda p: not p.drawing)
            if without:
                raise UserError(_(
                    "Нет чертежей у деталей: %s. Без них у замера не будет "
                    "знаменателя — «лист резался 47 минут» не переносится на "
                    "другой заказ.") % ", ".join(without.mapped("name")))
            job.part_ids.action_parse_drawing()
        return True

    # ==================================================================
    # Обрезки
    # ==================================================================

    def action_propose_offcuts(self):
        """Предложить обрезки по листам, где остался цельный кусок.

        Кнопка обязана всегда делать что-то осмысленное. Раньше повторное
        нажатие выдавало «всё в лом», хотя обрезок уже был предложен первым
        нажатием: лист с готовым обрезком пропускался, счётчик оставался
        нулём, и человек видел отказ вместо своего же результата. Теперь
        «уже предложено» и «нечего предлагать» — разные исходы, и в обоих
        случаях открывается список: в первом с тем, что есть, во втором
        пустой, чтобы завести обрезок руками.
        """
        offcuts = self.env["pmk.laser.offcut"]
        created = 0
        already = 0
        small_sheets = []
        smallest = min(self.mapped("min_offcut_mm") or [money.DEFAULT_MIN_OFFCUT_MM])
        for job in self:
            for sheet in job.sheet_ids:
                if sheet.offcut_ids:
                    already += len(sheet.offcut_ids)
                    continue
                proposal = money.propose_offcut(
                    sheet.width_mm, sheet.length_mm, sheet.utilization_pct,
                    min_length_mm=job.min_offcut_mm)
                if not proposal:
                    small_sheets.append(sheet.number)
                    continue
                width, length = proposal
                offcuts.create({
                    "job_id": job.id,
                    "sheet_line_id": sheet.id,
                    "width_mm": width,
                    "length_mm": length,
                })
                created += 1

        # Что сказать человеку. Предложение ГРУБОЕ — точный свободный
        # прямоугольник считается по геометрии раскладки, а она в двоичной
        # части файла. Поэтому про правку размера говорим всегда, а не только
        # когда предложить не вышло.
        if created:
            msg = _("Предложено обрезков: %(n)s. Размер прикидочный — "
                    "посмотрите на лист и поправьте.") % {"n": created}
        elif already:
            msg = _("Обрезки по этому заданию уже предложены (%(n)s). "
                    "Ниже — то, что есть; размер можно поправить.") % {"n": already}
        else:
            msg = _("Свободного куска длиннее %(mm)g мм не нашлось — по расчёту "
                    "всё уходит в лом. Если на листе цельный остаток есть, "
                    "заведите обрезок кнопкой «Новое»: точный прямоугольник "
                    "по файлу пока не считается.") % {"mm": smallest}

        action = self.env["ir.actions.actions"]._for_xml_id("pmk_laser.action_laser_offcut")
        action["domain"] = [("job_id", "in", self.ids)]
        action["context"] = dict(self.env.context, default_job_id=self[:1].id)
        action["help"] = "<p class='o_view_nocontent_smiling_face'>%s</p>" % msg
        return action

    # ==================================================================
    # Нормативы
    # ==================================================================

    def action_update_norms(self):
        """Пересчитать нормативы по замерам — после того, как задание закрыто."""
        self.env["pmk.laser.norm"]._sync_from_measures()
        return True

    # ==================================================================
    # «Очередь листов» (доводка шага 36)
    # ==================================================================

    def action_queue_close(self):
        """⚙ «Действие» → «Снять с очереди»: неотрезанные листы задания уходят
        из «Очереди листов». Ничего не удаляет, замеры, премия и норматив не
        меняются; лист, который режется, остаётся, пока его не закончат.
        Обратимо — «Вернуть в очередь». Пункт меню, а не кнопка в шапке:
        нужен редко, а шапку шаг 36 и сжимал."""
        self.write({"queue_closed": True})
        return True

    def action_queue_open(self):
        """⚙ «Действие» → «Вернуть в очередь»."""
        self.write({"queue_closed": False})
        return True


class LaserJobPart(models.Model):
    """Деталь задания: сколько штук и что говорит её чертёж.

    Чертёж нужен не для красоты. Он даёт знаменатель: метры реза и проколы.
    Без него замер оператора остаётся числом «47 минут», которое нельзя
    перенести ни на один другой заказ.
    """

    _name = "pmk.laser.job.part"
    _description = "Деталь задания на резку"
    _order = "job_id, id"

    job_id = fields.Many2one("pmk.laser.job", "Задание", required=True, ondelete="cascade", index=True)
    name = fields.Char("Деталь", required=True)
    qty = fields.Integer("Заявлено", required=True, default=1)
    qty_used = fields.Integer(
        "Разложено", help="Отличается от заявленного, когда в раскладку влезли "
                          "не все детали — часть заказа уедет на следующий лист.")

    # Теория вкладки «Детали и чертежи» — в подсказке «?» (разбор UX, шаг 36).
    drawing = fields.Binary(
        "Чертёж (.dxf)", attachment=True,
        help="Чертёж даёт знаменатель замера: метры реза и проколы. Без него "
             "«лист резался 47 минут» остаётся числом, которое нельзя "
             "перенести на другой заказ. Эскиз и метрики — в одной строке с "
             "деталью: видно, что разобран чертёж именно этой детали.")
    drawing_name = fields.Char("Имя чертежа")

    cut_length_mm = fields.Float(
        "Рез на деталь, мм", digits=(12, 1), readonly=True,
        help="Длина реза одной детали по чертежу — контур и все отверстия. "
             "Появляется кнопкой «Разобрать» в строке детали.")
    pierce_count = fields.Integer("Проколов на деталь", readonly=True)
    preview_svg = fields.Text("Эскиз", readonly=True)

    cut_length_total_m = fields.Float("Рез всего, м", compute="_compute_totals", store=True, digits=(12, 2))
    pierces_total = fields.Integer("Проколов всего", compute="_compute_totals", store=True)

    @api.depends("qty", "cut_length_mm", "pierce_count")
    def _compute_totals(self):
        for part in self:
            part.cut_length_total_m = part.qty * part.cut_length_mm / 1000.0
            part.pierces_total = part.qty * part.pierce_count

    def action_parse_drawing(self):
        """Прочитать чертёж: длина реза, число замкнутых контуров, эскиз.

        Разбор живёт в tools/drawing.py и Odoo не требует — здесь только
        единственная точка вызова. Ожидаемый ответ: объект с полями
        cut_length_mm, pierces, preview_svg.
        """
        from ..tools import drawing  # разбор DXF, Odoo ему не нужен

        for part in self:
            if not part.drawing:
                raise UserError(_("У детали «%s» не приложен чертёж") % part.name)
            with tempfile.TemporaryDirectory() as folder:
                path = os.path.join(folder, part.drawing_name or "part.dxf")
                with open(path, "wb") as handle:
                    handle.write(base64.b64decode(part.drawing))
                parsed = drawing.read_drawing(path)
            part.write({
                "cut_length_mm": parsed.cut_length_mm,
                "pierce_count": parsed.pierces,
                "preview_svg": parsed.preview_svg,
            })
        return True


class LaserJobSheet(models.Model):
    """Физический лист на столе станка.

    Отдельная строка на каждый лист, даже когда раскладка одна и та же: лист
    кладут, режут и снимают поштучно, и замер оператора привязан именно к
    листу. Семь одинаковых листов — семь строк и семь замеров.
    """

    _name = "pmk.laser.job.sheet"
    _description = "Лист задания на резку"
    _order = "job_id, number"
    _rec_name = "number"

    job_id = fields.Many2one("pmk.laser.job", "Задание", required=True, ondelete="cascade", index=True)
    # Теория вкладки «Листы» — в подсказке «?» (разбор UX, шаг 36).
    # ⚠️ aggregator=None у номера, раскладки, габарита и использования
    # (доводка шага 36). «Очередь листов» сгруппирована по станку, а Odoo
    # складывает в строке группы каждое число, у которого есть агрегатор
    # (у Integer и Float по умолчанию сумма): «Лист № 36», «Использование,
    # % 620,4» — та же бессмыслица, что шаг 24 убирал у задания. Хуже того,
    # web_read_group строит порядок групп из default_order списка
    # (_get_read_group_order): «number» с агрегатором превращался в
    # «number:sum», и станки вставали по сумме номеров листов — менялись
    # местами по ходу резки. Без агрегатора номер в порядок групп не идёт, и
    # группы стоят по станку (его _order). Масса и минуты складываются, как
    # и раньше.
    number = fields.Integer(
        "Лист №", required=True, aggregator=None,
        help="Строка на каждый физический лист, даже если раскладка одна и та "
             "же: лист кладут, режут и снимают поштучно, и замер привязан к "
             "листу. Оператору два касания — «Начал» и «Закончил», всё "
             "остальное подставится из задания.")
    nest_index = fields.Integer(
        "Раскладка", aggregator=None,
        help="Номер раскладки в файле. У листов одной раскладки картинка одна "
             "и та же — их время должно совпадать, и расхождение сразу видно "
             "в замерах.")
    width_mm = fields.Float("Ширина, мм", digits=(8, 0), required=True, aggregator=None)
    length_mm = fields.Float("Длина, мм", digits=(8, 0), required=True, aggregator=None)
    utilization_pct = fields.Float("Использование, %", digits=(5, 1), required=True, aggregator=None)

    area_m2 = fields.Float("Габарит, м²", compute="_compute_metal", store=True, digits=(10, 3))
    useful_area_m2 = fields.Float("Полезно, м²", compute="_compute_metal", store=True, digits=(10, 3))
    mass_kg = fields.Float("Масса листа, кг", compute="_compute_metal", store=True, digits=(12, 1))
    useful_mass_kg = fields.Float("Полезный вес, кг", compute="_compute_metal", store=True, digits=(12, 1))

    measure_ids = fields.One2many("pmk.laser.measure", "sheet_line_id", "Замеры")
    offcut_ids = fields.One2many("pmk.laser.offcut", "sheet_line_id", "Обрезки")
    actual_minutes = fields.Float("Факт, мин", compute="_compute_actual", store=True, digits=(8, 1))

    # ------------------------------------------------------------------
    # Резка листа: состояние и «Очередь листов» (разбор UX, шаг 36)
    # ------------------------------------------------------------------
    # У каждого листа горели обе кнопки — «Начал» и «Закончил», даже у
    # отрезанного: на задании из 8 листов 16 кнопок. Теперь у листа
    # состояние и одна нужная кнопка: ждёт — «Начал», режется — «Закончил»,
    # готов — ничего. Хранится: по нему отбирает и группирует очередь.
    cut_state = fields.Selection(
        [("waiting", "Ждёт"), ("running", "Режется"), ("done", "Готов")],
        "Состояние", compute="_compute_cut_state", store=True, index=True,
        default="waiting",
        help="Ждёт — «Начал» ещё не нажимали. Режется — «Начал» нажат, "
             "«Закончил» ещё нет. Готов — лист снят. Замер, который мастер "
             "исключил из норматива (обед, поломка), лист готовым оставляет: "
             "лист отрезан, исключение касается только норматива.")
    # Станок — копией из задания, хранимой: очередь группирует листы по
    # станку, а группировать по полю другой таблицы список не умеет.
    machine_id = fields.Many2one(
        related="job_id.machine_id", string="Станок", store=True, index=True)
    thickness_mm = fields.Float(
        related="job_id.thickness_mm", string="Толщина, мм", aggregator=None)
    # Имя файла — по нему оператор находит программу на станке.
    job_file_name = fields.Char(related="job_id.file_name", string="Файл")
    size_label = fields.Char(
        "Габарит, мм", compute="_compute_size_label",
        help="Ширина × длина листа, как пишут габарит в прайсе: «1500×3000».")
    # Доводка шага 36: в задании приложили новый файл раскроя, а листы — от
    # прежнего (file_replaced). В форме задания на это жёлтый сигнал, а в
    # очереди колонка «Файл» показывала уже имя НОВОГО файла: оператор грузил
    # новую программу и жал «Начал» на листе, которого в ней может не быть.
    # Сигнал, а не запрет: «Начал» на месте. Колонка молчит, когда всё в
    # порядке. Не хранится — читается при показе.
    queue_note = fields.Char(
        "Замечание", compute="_compute_queue_note",
        help="«Файл заменён» — в задании приложили новый файл раскроя, а листы "
             "от прежнего: программа на станке и лист в очереди могут не "
             "совпасть. Без замеров технолог разбирает новый файл; после "
             "замеров новый файл кладут в новое задание, а это снимают с "
             "очереди (⚙ «Действие» в задании).")

    @api.depends("measure_ids.state")
    def _compute_cut_state(self):
        for sheet in self:
            states = set(sheet.measure_ids.mapped("state"))
            if "running" in states:
                sheet.cut_state = "running"
            elif "done" in states:
                # Исключённый мастером замер — тоже «Готов» (решение по
                # умолчанию, утверждает владелец): иначе отрезанный лист
                # вернулся бы в очередь, и оператор резал бы его второй раз.
                sheet.cut_state = "done"
            else:
                sheet.cut_state = "waiting"

    @api.depends("width_mm", "length_mm")
    def _compute_size_label(self):
        for sheet in self:
            sheet.size_label = table_size_label(sheet.width_mm, sheet.length_mm)

    @api.depends("job_id.file_replaced")
    def _compute_queue_note(self):
        for sheet in self:
            sheet.queue_note = "файл заменён" if sheet.job_id.file_replaced else False

    def action_open_job(self):
        """Строка «Очереди листов» открывает задание: чертежи, детали, замеры."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "pmk.laser.job",
            "res_id": self.job_id.id,
            "views": [[False, "form"]],
            "target": "current",
        }

    @api.depends("width_mm", "length_mm", "utilization_pct", "job_id.mass_per_sqm")
    def _compute_metal(self):
        for sheet in self:
            mass_per_sqm = sheet.job_id.mass_per_sqm
            sheet.area_m2 = money.sheet_area_m2(sheet.width_mm, sheet.length_mm)
            sheet.useful_area_m2 = money.useful_area_m2(sheet.area_m2, sheet.utilization_pct)
            sheet.mass_kg = money.mass_kg(sheet.area_m2, mass_per_sqm)
            sheet.useful_mass_kg = money.mass_kg(sheet.useful_area_m2, mass_per_sqm)

    @api.depends("measure_ids.duration_minutes", "measure_ids.state", "measure_ids.excluded")
    def _compute_actual(self):
        for sheet in self:
            # По листу считаем ПОЛНОЕ время: оператор нажал «начал», когда взялся
            # за лист, и «закончил», когда снял детали. Чистую резку из этого
            # вычитает сам замер — она нужна нормативу, а не сменному заданию.
            usable = sheet.measure_ids.filtered(lambda m: m.state == "done" and not m.excluded)
            sheet.actual_minutes = sum(usable.mapped("duration_minutes"))

    def action_start_cut(self):
        """Первое касание оператора: «начал». Всё остальное берётся из задания.

        Отрезанный лист заново не начинается (доводка шага 36). У готового
        листа вид кнопку прячет, но страница могла устареть: у станка двое
        или очередь открыта на двух устройствах. Второй замер лёг бы на
        отрезанный лист — он снова «Режется», а реально режущийся остаётся
        «Ждёт»; «Факт, мин» и норматив сложили бы оба замера. Это защита от
        устаревшей страницы, а не запрет: лист правда режут заново — прежний
        замер удаляют в «Замерах», и лист снова «Ждёт».
        """
        measures = self.env["pmk.laser.measure"]
        for sheet in self:
            if sheet.cut_state == "done":
                raise UserError(_(
                    "Лист %s уже отрезан — обновите страницу: очередь могла "
                    "устареть.") % sheet.number)
            running = sheet.measure_ids.filtered(lambda m: m.state == "running")
            if running:
                raise UserError(_("По листу %s замер уже идёт") % sheet.number)
            measures |= measures.create({
                "job_id": sheet.job_id.id,
                "sheet_line_id": sheet.id,
                "operator_id": self.env.user.employee_id.id,
                "started_at": fields.Datetime.now(),
            })
        return True

    def action_finish_cut(self):
        """Второе касание оператора: «закончил»."""
        for sheet in self:
            running = sheet.measure_ids.filtered(lambda m: m.state == "running")
            if not running:
                raise UserError(_("По листу %s никто не начинал резку") % sheet.number)
            running.action_finish()
        return True


class LaserJobOperator(models.Model):
    """Оператор смены и его доля премии.

    Список, а не одно поле: операторы делят премию пополам, но смена бывает и
    из одного, и из троих. Списком состав меняется в задании, а не в коде —
    это требование владельца.
    """

    _name = "pmk.laser.job.operator"
    _description = "Оператор в задании на резку"
    _order = "job_id, sequence, id"
    _rec_name = "employee_id"

    job_id = fields.Many2one("pmk.laser.job", "Задание", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer("Порядок", default=10)
    employee_id = fields.Many2one("hr.employee", "Оператор", required=True)
    # Теория вкладки «Операторы и премия» — в подсказке «?» (разбор UX, шаг 36).
    amount_rub = fields.Float(
        "Премия, ₽", compute="_compute_amount", store=True, digits=(10, 2),
        help="Доля оператора: премия задания поровну на всех в списке. Делёж "
             "идёт в копейках, поэтому сумма долей всегда равна премии: "
             "738,20 ₽ на троих — 246,07 + 246,07 + 246,06.")

    _employee_once = models.UniqueIndex(
        "(job_id, employee_id)",
        "Оператор уже есть в этом задании — вторая строка удвоила бы его долю.",
    )

    @api.depends("job_id.premium_rub", "job_id.operator_ids", "sequence")
    def _compute_amount(self):
        self.amount_rub = 0.0
        for job in self.mapped("job_id"):
            lines = job.operator_ids
            shares = money.split_rub(job.premium_rub, len(lines))
            for line, share in zip(lines, shares):
                if line in self:
                    line.amount_rub = share
