# Гонять ТОЛЬКО на одноразовой базе (см. test_spec_form.py).
# Без базы: python3 addons/pmk_calc/tests/test_sheet_use.py
#           python3 addons/pmk_calc/tests/test_size_search.py
from . import test_sheeting
from . import test_sheet_use
from . import test_spec_form
from . import test_size_search
from . import test_step34_product_window
from . import test_list_units
from . import test_dobor_fit
from . import test_dobor_copy
from . import test_step27_forms
from . import test_step30_tracking
from . import test_step35_dobor
# Слово «расчёт» вместо «спецификации» (шаг 39): имена, подписи, история.
from . import test_step39_words
# Шаг 56: правка в строке «Состава», поиск «уг 50 5», «Раскладка устарела».
from . import test_step56_spec
# Шаг З-10: позиция «на разнос» — заведение из детали, разнос, права.
from . import test_step_z10_pending
# Шаг З-13: совместная раскладка листа. Чистые функции — test_sheet_group
# (голым питоном: python3 addons/pmk_calc/tests/test_sheet_group.py).
from . import test_sheet_group
from . import test_step_z13
from . import test_vent_hood
