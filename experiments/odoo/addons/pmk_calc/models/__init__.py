from . import metal_reference
# Шаг З-10: метка «на разнос» у справочников (до расчёта: metal_spec берёт
# отсюда пометку детали).
from . import metal_pending
from . import metal_spec
from . import dobor
from . import dobor_report
# 11.10.2026: вентзонты — генератор развёрток tools/vent_hood.py.
from . import vent_hood
from . import spec_layout
# Шаг З-13: «Лист раскладки» — группа деталей одного листа и габарита.
from . import spec_sheet_group
from . import res_partner
from . import metal_pending_bind
# Последним: представление базы по колонкам справочников (см. файл).
from . import metal_pending_report
