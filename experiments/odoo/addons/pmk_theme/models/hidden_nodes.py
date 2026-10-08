# -*- coding: utf-8 -*-
"""Скрытое без новых зависимостей — разбор UX, шаг 29 (02.10.2026).

ЗАЧЕМ ЗДЕСЬ, А НЕ НАСЛЕДНИКОМ ВИДА. Часть узлов, которые разбор просит
убрать, дописывают модули, от которых наши НЕ зависят и не должны зависеть:
  • Настройки — разделы «Сайт» (website), «Проект» (project), «Обслуживание»
    (maintenance), иностранные коннекторы продаж и доставки, Ringover (CRM),
    SEPA / чеки и OCR (Счета), barcodelookup (Склад);
  • запрос КП / заказ поставщику — «Доставить в», «Инкотерм» ×2,
    «% своевременной поставки», прогнозный отчёт в строке (purchase_stock),
    «Проект» (project_purchase).
Наследник вида с xpath на такой узел — грабли «xpath на узлы зависимого
модуля»: без зависимости модуль может загрузиться раньше владельца узла, вид
падает и выключается при загрузке, причём молча. Добавить зависимость —
значит снова привязать тему к website / project / maintenance, от которых
шаг 43 её отвязывает (ловушка удаления модулей).

КАК. Тем же приёмом, что models/base.py (шаг 26, атрибут sample): правим
собранную разметку в _get_view — после всех наследников, до кэша видов.
Узлу ставится groups= группы-выключателя (security/pmk_step29_groups.xml),
дальше работает ядро: _postprocess_view переводит groups в __groups_key__,
кэш хранит вид для всех групп, а get_view вырезает узел у того, кого в
группе нет (_postprocess_access_rights). Поля, на которые ссылаются
модификаторы соседей, ядро досоздаёт невидимыми (_add_missing_fields).
Разметка в базе не меняется; узла нет (модуль снят) — правило молча ничего
не делает, поэтому каждое правило проверяет тест (tests/test_step29_hidden.py).

⚠️ Атрибут groups у узла один: если у узла была штатная группа («Проект» —
пользователям проектов, разделы Настроек — их администраторам), наша встаёт
вместо неё. Поэтому «Убранное (показать)» — только администратору
(подробно — в security/pmk_step29_groups.xml).

«СВОЙСТВА» — ТОЛЬКО АДМИНИСТРАТОРУ. Поле типа properties в форме даёт пункт
шестерёнки «Изменить свойства» (ядро ставит его, когда в разметке есть такое
поле: web/views/form/form_arch_parser.js, addPropertyFieldValue) — любой мог
завести своё поле в сделке, контрагенте, товаре. В поиске — поле поиска по
свойствам и группировка «Свойства». Правило общее для всех моделей: узлу
поля типа properties (вне вложенных таблиц) и группировке по нему ставится
base.group_system, если своей группы у узла нет. Определений свойств на
стенде нет ни одного (02.10.2026), прятать от остальных нечего.

Вернуть: строку — убрать из HIDDEN_NODES и выложить pmk_theme; всё разом —
удалить этот файл и его импорт в models/__init__.py. Таблица —
docs/disabled-features.md, раздел «шаг 29».

ШАГ З-6 (09.10.2026, карточка 6 «Заказ от заявки до цеха»): «ПОСТУПЛЕНИЯ»
ДО УЧЁТА. Подтверждённый заказ поставщику сам заводит «Поступление»
(purchase_stock), а кнопка «Подтвердить» в нём ПРОВОДИТ приход на склад —
ловушка: два одинаковых слова для разных действий. Склад не ведём, поэтому
из заказа поставщику убраны все дороги к «Поступлению» и складские итоги
строк (STEP_Z6_NODES): кнопка-счётчик «Поступления» (грузовик) и штатная
«Получить» (обе — action_view_picking), «Статус получения», колонки строк
«Получено» и «Выставленный счёт», в окне строки — те же количества и
вкладка «Счета и поступающие товары», «Статус выставления счетов» во
«Другой информации».
  • Скрываем не группой склада: у снабженца (Владимир) есть «Склад:
    пользователь» — штатно он видел бы всё. Узел получает groups= наших
    выключателей; у «Поступлений» их два (ИЛИ): «Убранное (показать)» и
    «Склад (показать)» — когда начнут вести склад, хватит второй (она сама
    даёт права склада); у счетов строки — «Убранное» и «Деньги (показать)».
  • Ничего не удаляется и не отменяется: уже созданные «Поступления» лежат в
    базе, подтверждение заказа по-прежнему заводит новое (не проводит).
    «Материал пришёл» (pmk_tech, шаг З-5) с «Поступлением» не связан.
  • Отдельным словарём, а не в HIDDEN_NODES: тесты шагов 29 и 53 перебирают
    правила HIDDEN_NODES по ключу и ждут там только своё.
Вернуть одну строку — убрать её из STEP_Z6_NODES; всё разом — добавить
человека в группу. Таблица — docs/disabled-features.md, раздел «шаг З-6».
"""
import re

from odoo import api, models

REMOVED = "pmk_theme.group_pmk_removed"
STOCK = "pmk_theme.group_pmk_stock"
MONEY = "pmk_theme.group_pmk_money"
ADMIN = "base.group_system"
# Шаг З-6: группа правила может быть набором — узел видит любой из них.
RECEIPTS = (REMOVED, STOCK)
BILLS = (REMOVED, MONEY)

# (модель, тип вида) → ((xpath, группа), ...). Xpath ищется в собранной
# разметке ЛЮБОГО вида этого типа у модели; правило ставит группу на все
# найденные узлы.
HIDDEN_NODES = {
    ("res.config.settings", "form"): (
        # Разделы модулей, которые на заводе не ведутся (сайт завода —
        # pmkpark.ru на Bitrix): в левой колонке Настроек их больше нет.
        ("//app[@name='website']", REMOVED),
        ("//app[@name='project']", REMOVED),
        ("//app[@name='maintenance']", REMOVED),
        # Продажи → «Коннекторы»: Amazon, Gelato, Shopee.
        ("//block[@id='connectors_setting_container']", REMOVED),
        # Склад → «Разъемы для транспортировки»: UPS, DHL, FedEx, USPS,
        # bpost, Easypost, Sendcloud, Shiprocket, Starshipit, Envia.
        ("//block[@name='shipping_connectors_setting_container']", REMOVED),
        # Продажи → «Доставка»: те же перевозчики. Сама «Доставка» (расчёт
        # стоимости доставки, module_delivery) остаётся — это не коннектор.
        ("//block[@name='sale_shipping_setting_container']/setting[not(@id='delivery')]", REMOVED),
        # Иностранные сервисы в других разделах (доводка шага 29):
        #   CRM — «Ringover VOIP Phone»: расширение браузера для звонков
        #   через французский сервис (ссылка в Chrome Web Store);
        ("//setting[@id='ringover-voip']", REMOVED),
        #   Счета — «Оплаты поставщикам» (SEPA / ISO20022 — платежи в евро;
        #   «Чеки» — печать американских чеков, видна только с полным
        #   учётом) и «Оцифровка» (OCR счетов, платный сервис Odoo):
        #   блоками целиком — без строк остался бы голый заголовок;
        ("//block[@id='print_vendor_checks_setting_container']", REMOVED),
        ("//block[@id='account_digitalization']", REMOVED),
        #   Счета — Intrastat (статистика торговли внутри ЕС): у российской
        #   компании ядро и так прячет условием, правило — на смену страны;
        ("//setting[@id='intrastat_statistics']", REMOVED),
        #   Склад → «Штрихкод» — «Stock Barcode Database» (barcodelookup.com,
        #   заграничная база штрихкодов по ключу API). Сам «Штрихкод» в
        #   блоке остаётся.
        ("//setting[@id='process_stock_barcodelookup']", REMOVED),
        # Общие → «Электронные письма» → «Сводка» (digest): сама рассылка
        # выключена data/digest_off.xml, здесь — её галочка.
        ("//setting[@id='digest']", REMOVED),
    ),
    ("purchase.order", "form"): (
        # purchase_stock: «Доставить в» (тип приёмки — один склад, ставится
        # сам), «Инкотерм» и его место.
        ("//field[@name='picking_type_id']", REMOVED),
        ("//field[@name='incoterm_id']", REMOVED),
        ("//field[@name='incoterm_location']", REMOVED),
        # project_purchase: «Проект».
        ("//field[@name='project_id']", REMOVED),
        # purchase_stock: «% своевременной поставки» у даты поставки и
        # «Прогнозный отчёт» (значок графика) в строке заказа.
        ("//div[@name='date_planned_div']//button[.//field[@name='on_time_rate']]", STOCK),
        ("//field[@name='order_line']//button[@name='action_product_forecast_report']", STOCK),
    ),
    # ─── Шаг 53 (приёмка 07.10.2026): спрятать до востребования ─────────
    # Данные не трогаем, поля в моделях на месте; вернуть — группа
    # «Убранное (показать)» или строку убрать отсюда. В печать и в КП эти
    # поля не идут (grep по report/ и pmk_pdf, 07.10.2026).
    #
    # Теги сделки и лида: на стенде 0 тегов и 0 связей (SELECT 07.10.2026).
    # Форма (у лида и у сделки — два узла: pmk_deal переносит узел лида
    # в левую колонку, правило работает после всех наследников), список
    # (там тег и так column_invisible — правило на случай, если колонку
    # вернут), канбан воронки и поиск («Тег» в строке поиска).
    # [not(ancestor::field)] — только поля самой сделки, не вложенных таблиц.
    ("crm.lead", "form"): (
        ("//field[@name='tag_ids'][not(ancestor::field)]", REMOVED),
    ),
    ("crm.lead", "list"): (
        ("//field[@name='tag_ids'][not(ancestor::field)]", REMOVED),
    ),
    ("crm.lead", "kanban"): (
        ("//field[@name='tag_ids'][not(ancestor::field)]", REMOVED),
    ),
    ("crm.lead", "search"): (
        ("//field[@name='tag_ids']", REMOVED),
    ),
    # «Снабженец» в карточке контрагента (purchase, buyer_id): заполнен у 0
    # из 88 контрагентов. Подпись «Снабженец» — pmk_purchase, она остаётся
    # на узле и вернётся вместе с ним.
    ("res.partner", "form"): (
        ("//field[@name='buyer_id'][not(ancestor::field)]", REMOVED),
    ),
    # Поля рулона в доборке: заполнены у 1 позиции из 16 (ДОБ-00001: 1250 мм,
    # 4 полосы, отход 170) — значения хранятся и пересчитываются как раньше.
    # Окно позиции: ширина рулона, полос, отход; список позиций: полос и
    # отход (в ⚙ колонок). ⚠️ Служебную колонку coil_width в списке позиций
    # (column_invisible) НЕ трогать: из неё «Копировать» берёт значение
    # (pmk_calc/static/src/js/dobor_copy_line.js, COPY_FIELDS).
    ("pmk.dobor.order", "form"): (
        ("//field[@name='line_ids']/form//field[@name='coil_width']", REMOVED),
        ("//field[@name='line_ids']/form//field[@name='strips']", REMOVED),
        ("//field[@name='line_ids']/form//field[@name='strip_waste']", REMOVED),
        ("//field[@name='line_ids']/list/field[@name='strips']", REMOVED),
        ("//field[@name='line_ids']/list/field[@name='strip_waste']", REMOVED),
    ),
}

# ─── Шаг З-6 (09.10.2026): «Поступления» до учёта ──────────────────────
# Узлы дописывает purchase_stock (кроме qty_invoiced и вкладки строки —
# purchase), pmk_theme от него не зависит — поэтому здесь, а не xpath в виде.
# Поля простые (число, выбор), не вложенные наборы: ловушки column_invisible
# с загрузкой вложенного набора здесь нет. На qty_invoiced ссылаются
# readonly цены и скидки строки, на receipt_status и invoice_status —
# соседние модификаторы: ядро досоздаст их невидимыми (_add_missing_fields).
# В печать не идут (бланк заказа и запроса их не печатает, КП — документ
# расчёта). [not(ancestor::field)] — поле заказа, не вложенной таблицы.
STEP_Z6_NODES = {
    ("purchase.order", "form"): (
        # Кнопка-счётчик «Поступления» (грузовик, button_box) и штатная
        # «Получить» в шапке — одно действие, оба узла.
        ("//button[@name='action_view_picking']", RECEIPTS),
        # «Статус получения» — «Другая информация».
        ("//field[@name='receipt_status'][not(ancestor::field)]", RECEIPTS),
        # Строки заказа: колонка «Получено» и в окне строки «Полученное
        # количество».
        ("//field[@name='order_line']/list/field[@name='qty_received']", RECEIPTS),
        ("//field[@name='order_line']/form//field[@name='qty_received']", RECEIPTS),
        # Колонка «Выставленный счёт» и «Выставленное количество» — счета
        # поставщиков ведутся в МоёмСкладе (как «Загрузить счёт», шаг 29).
        ("//field[@name='order_line']/list/field[@name='qty_invoiced']", BILLS),
        ("//field[@name='order_line']/form//field[@name='qty_invoiced']", BILLS),
        # Окно строки: вкладка «Счета и поступающие товары» (счета строки и
        # движения склада) — целиком.
        ("//field[@name='order_line']/form//page[@name='invoices_incoming_shiptments']", REMOVED),
        # «Статус выставления счетов» — «Другая информация».
        ("//field[@name='invoice_status'][not(ancestor::field)]", BILLS),
    ),
    # Списки закупок: «Статус получения» в ⚙ колонок «Подтверждённых
    # заказов» (purchase_order_view_tree, у остальных его нет) и «Статус
    # выставления счетов» в ⚙ обоих списков (с шага 25 там optional=hide) —
    # то же, что спрятано в форме.
    ("purchase.order", "list"): (
        ("//field[@name='receipt_status'][not(ancestor::field)]", RECEIPTS),
        ("//field[@name='invoice_status'][not(ancestor::field)]", BILLS),
    ),
}

# ─── Шаг З-9 (09.10.2026): «Счёт покупателю» по-нашему ─────────────────
# Свои узлы счёта (шапка, строки, итог, «Другая информация») pmk_orders
# прячет своим видом — sale и его соседи у него в зависимостях. Здесь — узлы
# модулей, от которых ни тема, ни pmk_orders не зависят (грабли «xpath на узлы
# зависимого модуля»):
#   • l10n_ru_advance_payments (RuOdoo): кнопка «Авансовый счет» в шапке
#     счёта в работе — авансовые счета-фактуры ведёт бухгалтерия снаружи
#     (как «Создать счёт» ядра — «Деньги», шаг З-2). Кнопка-счётчик
#     «Авансовые счета» видна только при числе больше нуля — не трогаем;
#   • sale_pdf_quote_builder: вкладка «Конструктор КП» (вкладыши PDF к
#     штатному бланку) — КП уходит из расчёта своим бланком; у ядра вкладка
#     и так скрыта, пока нет вкладышей, правило — на случай, если их заведут.
# В печать не идут. Вернуть строку — убрать её отсюда; всё — группа
# «Убранное (показать)». Таблица — docs/disabled-features.md, шаг З-9.
STEP_Z9_NODES = {
    ("sale.order", "form"): (
        ("//header/button[@name='button_advance']", BILLS),
        ("//page[@name='pdf_quote_builder']", REMOVED),
    ),
}

# 'group_by': 'lead_properties' (и 'properties.<ключ>') в контексте фильтра.
GROUP_BY = re.compile(r"""['"]group_by['"]\s*:\s*['"]([\w.]+)""")


class Base(models.AbstractModel):
    _inherit = "base"

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if arch is None:
            return arch, view
        self._pmk_hide_nodes(arch, view_type)
        self._pmk_properties_admin_only(arch)
        return arch, view

    @api.model
    def _pmk_hide_nodes(self, arch, view_type):
        key = (self._name, view_type)
        rules = HIDDEN_NODES.get(key, ()) + STEP_Z6_NODES.get(key, ()) + STEP_Z9_NODES.get(key, ())
        for expr, group in rules:
            # Группа — одна или набор (ИЛИ, шаг З-6).
            groups = (group,) if isinstance(group, str) else tuple(group)
            # Группы ещё нет (pmk_theme ставится) — правило пропускаем: узел
            # с несуществующей группой ядро не вырезало бы ни у кого.
            if not all(self.env.ref(xmlid, raise_if_not_found=False) for xmlid in groups):
                continue
            for node in arch.xpath(expr):
                node.set("groups", ",".join(groups))

    @api.model
    def _pmk_properties_admin_only(self, arch):
        props = {name for name, field in self._fields.items() if field.type == "properties"}
        if not props:
            return
        for node in arch.iter("field"):
            # Вне вложенных таблиц: у них своя модель, и одноимённое поле
            # там — чужое.
            if (node.get("name") in props and not node.get("groups")
                    and not node.xpath("ancestor::field")):
                node.set("groups", ADMIN)
        for node in arch.iter("filter"):
            match = GROUP_BY.search(node.get("context") or "")
            if match and match.group(1).split(".")[0] in props and not node.get("groups"):
                node.set("groups", ADMIN)
