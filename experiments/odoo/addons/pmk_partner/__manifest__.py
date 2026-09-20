{
    "name": "ПМК — карточка контрагента",
    "version": "19.0.1.0.0",
    "summary": "Убраны поля, которых нет в работе завода; поля в едином виде темы",
    "description": """
Форма контрагента в Odoo собрана из двадцати наследованных представлений и
содержит 105 полей: каждый установленный модуль дописывает своё. Заводу из них
нужна примерно треть, остальное — европейское электронное выставление счетов,
проверка НДС по базе ЕС, сохранённые банковские карты, встречи, задачи и кадры.

Здесь эти поля скрыты, а не удалены: возврат — снятие одного атрибута.
Поля индивидуального предпринимателя оставлены, но показываются только когда
выбран тип «физическое лицо».

Что именно скрыто и почему — `experiments/odoo/docs/disabled-features.md`.
""",
    "category": "Productivity",
    "author": "ПМК Парк",
    "depends": [
        # владельцы полей, которые скрываем: без них xpath не найдёт узел и
        # модуль не поставится. Список получен запросом к ir.model.fields,
        # а не на глаз — при снятии любого из них править этот модуль.
        "base",
        "account",
        "stock",
        "purchase",
        "payment",
        "project",
        "hr",
        "calendar",
        "base_vat",
        "account_edi_ubl_cii",
        "account_add_gln",
        "l10n_ru_doc",
        "l10n_ru_upd_xml",
        "l10n_ru_contract",
        "purchase_stock",
        "product",
        "website",
        # ради стилей полей
        "pmk_theme",
    ],
    "data": [
        "views/res_partner_views.xml",
        "views/purchase_views.xml",
        "views/res_partner_flat_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
