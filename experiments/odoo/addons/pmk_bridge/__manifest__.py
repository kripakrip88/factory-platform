# -*- coding: utf-8 -*-
{
    # Мост между справочником pmk_calc и номенклатурой Odoo. Нужен потому, что
    # цена поставщика (product.supplierinfo) требует товар, а сортамент лежит в
    # собственных таблицах pmk_calc и товаром не является.
    #
    # Модуль намеренно НЕ ставится автоматически. Он несёт СРЕДУ под
    # номенклатуру (коды ОКЕИ, дерево категорий, две характеристики), а сами
    # 752 карточки заводит скрипт scripts/load_products.py: карточки — данные
    # завода, а не данные модуля, и переустановка модуля не должна их трогать.
    "name": "ПМК: мост справочника в номенклатуру",
    "version": "19.0.0.3.0",
    "summary": "Артикулы (default_code) для переноса сортамента pmk_calc в товары",
    "category": "Inventory/Inventory",
    "author": "ПМК Парк",
    "license": "LGPL-3",
    # Каждая зависимость проверена по базе стенда, а не взята на память:
    #   product, uom      — товары, единицы, характеристики;
    #   stock             — склад, партии (кусок проката = партия);
    #   stock_account     — способ учёта затрат и оценка запасов на категориях
    #                       (property_cost_method / property_valuation);
    #   l10n_ru_doc       — поле uom.uom.kod (field_uom_uom__kod принадлежит ему);
    #   l10n_ru_upd_xml   — поле uom.uom.okei, без него УПД не выгрузится;
    #   pmk_calc          — сам справочник, из которого растут карточки;
    #   mrp               — подпись «Спецификации» у кнопки-счётчика товара:
    #                       кнопку добавляет mrp, и xpath на неё без этой
    #                       зависимости упал бы при загрузке (грабли 23.09.2026);
    #   mail              — окно письма «Отправить КП» и шаблон письма (шаг 33):
    #                       вид наследует mail.email_compose_message_wizard_form.
    #                       Стоит и так (через pmk_calc), здесь — явно, раз
    #                       xpath идёт по его узлам.
    "depends": [
        "product",
        "uom",
        "stock",
        "stock_account",
        "mrp",
        "l10n_ru_doc",
        "l10n_ru_upd_xml",
        "pmk_calc",
        "mail",
    ],
    # data/uom_by_category.csv сюда КЛАСТЬ НЕЛЬЗЯ: это не данные модели, а
    # таблица соответствий «категория — единица», её читают скрипты.
    #
    # ГРАБЛЯ ПРО ОКЕИ: коды лягут только при ПЕРВОЙ установке. Обновление
    # модуля (-u pmk_bridge) их не перепишет — orm/models.py::_load_records
    # пропускает запись, если у ЦЕЛЕВОЙ строки в ir_model_data стоит
    # noupdate, а модуль uom грузит свои единицы именно так. Если коды
    # поменяются — гонять scripts/prepare_environment.py, он грузит файл
    # в режиме init.
    "data": [
        "data/uom_okei.xml",
        "data/product_category.xml",
        "data/product_attribute.xml",
        # Деньги в расчёте металлопроката: поля цены, итоги, рейтинг
        # поставщика. Вид наследуется от pmk_calc — без моста форма
        # калькулятора остаётся прежней.
        "views/metal_spec_cost_views.xml",
        # Коммерческое предложение по образцу бланка, которым завод
        # пользуется в МойСкладе: стили отдельно, потому что печать
        # рендерится вне интерфейса и ассетов темы там нет.
        "report/quotation_styles.xml",
        "report/quotation_report.xml",
        # «Отправить КП» (разбор UX, шаг 33): шаблон письма ссылается на
        # отчёт КП — строго ПОСЛЕ него, иначе ref упадёт при установке.
        # noupdate: правки Антона в Настройках деплой не затрёт.
        "data/mail_template_kp.xml",
        "views/mail_compose_views.xml",
        # Подписи кнопок-счётчиков товара по-человечески: «Приход / Расход»
        # вместо «В: / Вон:», «Спецификации» вместо «Сводная ведомость
        # материалов» (разбор UX, 28.09.2026).
        "views/product_stat_buttons.xml",
    ],
    # Разовое заполнение связи «справочник → карточка» при установке: готовое
    # соответствие уже лежит в ir_model_data, хук переносит его в поле.
    # Работает ТОЛЬКО при install, при -u не вызывается — см. hooks.py.
    "post_init_hook": "link_reference_products",
    # Колонка «Закупка» в составе изделия. Файлы лежат здесь, а не в
    # pmk_calc: без моста поля cost_fact_total нет, и калькулятор,
    # обещающий работу без номенклатуры, упал бы при открытии расчёта.
    "assets": {
        "web.assets_backend": [
            "pmk_bridge/static/src/scss/spec_cost.scss",
            "pmk_bridge/static/src/js/product_lines_cost.js",
            "pmk_bridge/static/src/xml/product_lines_cost.xml",
            # Полоска маржи в списке «Расчётов» («оживить таблицы», 29.09.2026).
            "pmk_bridge/static/src/scss/margin_bar.scss",
            "pmk_bridge/static/src/js/margin_bar_field.js",
            "pmk_bridge/static/src/xml/margin_bar_field.xml",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
