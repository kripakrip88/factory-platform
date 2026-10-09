# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе (см. test_spec_form.py, test_kp_send.py).
# Без базы: python3 addons/pmk_bridge/tests/test_spec_text.py
from . import test_sku
from . import test_spec_text
from . import test_spec_form
from . import test_kp_send
from . import test_spec_list
from . import test_step25_prices
from . import test_spec_copy
from . import test_step28_supplier_sign
from . import test_step30_print_colors
# Шаг 53: «Product created» в ленте товара — по-русски.
from . import test_step53_product_created
# Шаг 58: реквизиты продавца и строка налога в КП (без базы — голым питоном).
from . import test_step58_seller
# Исправление 08.10.2026: новый расчёт с листом не сохранялся (зеркала деталей).
from . import test_hotfix_new_spec_save
# Шаг 56: «Цена за шт» в строке «Состава», КП при устаревшей раскладке.
from . import test_step56_inline_price
# Шаг З-10: позиция «на разнос» — без карточки, «Принять» заводит карточку.
from . import test_step_z10_card
