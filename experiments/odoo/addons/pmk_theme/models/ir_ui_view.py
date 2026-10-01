# -*- coding: utf-8 -*-
"""Значки переключателя видов — тонкие линейные (разбор UX, шаг 47, 02.10.2026).

Вариант А, утверждён Антоном 01.10.2026: значки в стиле Tabler Icons вместо
штатных глифов шрифтов oi/fa («полный отстой»): канбан — layout-kanban,
список — list-details, активность — calendar-time, календарь — calendar,
сводная — table, график — chart-bar, форма — file-text, иерархия — sitemap,
карта — map-pin (вида «Карта» в бесплатной версии нет, класс про запас).

ОТКУДА ЗНАЧОК. Не из шаблона: ядро берёт класс значка из словаря видов,
который сервер отдаёт браузеру при загрузке страницы —
ir.ui.view._get_view_info() → get_view_info() → session_info['view_info'] →
action_service (viewSwitcherEntries[].icon) → ControlPanel:
<i class="oi-fw" t-att-class="view.icon"/>. Тот же класс рисуется и в ряду
кнопок широкого экрана, и в выпадашке узкого (там он у активного вида на
кнопке и у каждого пункта). Поэтому одна правка здесь вместо наследования
шаблона web.ControlPanel в трёх местах.

КАК. К классам ядра дописываются наши: pmk_vi (гасит глиф шрифта, рисует
значок маской) и pmk_vi--<вид> (какой значок). Стили и сами значки —
static/src/scss/navbar_nexus.scss, раздел «Переключатель видов». Классы ядра
остаются впереди: не доедут стили — кнопка покажет штатный значок, а не
пустоту. fa-rotate-90 (иерархия) снимается: повернул бы и наш значок.

Порядок наследования: mail (activity) и web_hierarchy (hierarchy) грузятся
раньше pmk_theme (граф модулей сортирует по глубине зависимостей,
odoo/modules/module_graph.py), поэтому super() уже содержит их виды. Модуль
с новым видом, поставленный позже pmk_theme, до перезапуска сервера может
показать штатный значок своего вида; после перезапуска порядок снова по
глубине. Вид без пары в PMK_VIEW_ICONS остаётся со штатным значком.

Вернуть штатные значки: удалить этот файл и строку импорта в
models/__init__.py, выложить pmk_theme (deploy.sh перезапускает Odoo).
Таблица — docs/disabled-features.md, раздел шага 47.
"""
from odoo import models

# Вид → наш класс значка. Пара к карте $pmk-view-icons в navbar_nexus.scss:
# тест сверяет, что у каждого класса здесь есть правило там.
PMK_VIEW_ICONS = {
    "list": "pmk_vi--list",
    "kanban": "pmk_vi--kanban",
    "form": "pmk_vi--form",
    "calendar": "pmk_vi--calendar",
    "pivot": "pmk_vi--pivot",
    "graph": "pmk_vi--graph",
    "activity": "pmk_vi--activity",
    "hierarchy": "pmk_vi--hierarchy",
    "map": "pmk_vi--map",
}

# Классы ядра, которые испортили бы наш значок.
_DROP_CLASSES = {"fa-rotate-90"}


class IrUiView(models.Model):
    _inherit = "ir.ui.view"

    def _get_view_info(self):
        info = super()._get_view_info()
        for view_type, icon_class in PMK_VIEW_ICONS.items():
            if view_type not in info:
                continue
            core = [cls for cls in (info[view_type].get("icon") or "").split()
                    if cls not in _DROP_CLASSES]
            info[view_type] = dict(info[view_type], icon=" ".join(core + ["pmk_vi", icon_class]))
        return info
