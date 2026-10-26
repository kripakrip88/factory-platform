from . import metal_reference
# Шаг З-10: метка «на разнос» у справочников (до расчёта: metal_spec берёт
# отсюда пометку детали).
from . import metal_pending
from . import metal_spec
from . import dobor
from . import dobor_report
from . import dobor_cut
# 11.10.2026: вентзонты — генератор развёрток tools/vent_hood.py.
from . import vent_hood
# 26.10.2026: лист доборки и вентзонта по цвету (цинк / окрашенный).
from . import sheet_coating
from . import spec_layout
# Шаг З-13: «Лист раскладки» — группа деталей одного листа и габарита.
from . import spec_sheet_group
from . import res_partner
from . import metal_pending_bind
# После доборки и вентзонтов: цены (12.10.2026), категории и «Металл» расчёта.
from . import calc_price
from . import spec_categories
from . import spec_move
from . import spec_metal
# Вкладка «Металл» одной таблицей со схемой (15.10.2026).
from . import spec_metal_view
# Последним: представление базы по колонкам справочников (см. файл).
from . import metal_pending_report
