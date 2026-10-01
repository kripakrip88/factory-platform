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
"""
import re

from odoo import api, models

REMOVED = "pmk_theme.group_pmk_removed"
STOCK = "pmk_theme.group_pmk_stock"
ADMIN = "base.group_system"

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
        for expr, group in HIDDEN_NODES.get((self._name, view_type), ()):
            # Группы ещё нет (pmk_theme ставится) — правило пропускаем: узел
            # с несуществующей группой ядро не вырезало бы ни у кого.
            if not self.env.ref(group, raise_if_not_found=False):
                continue
            for node in arch.xpath(expr):
                node.set("groups", group)

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
