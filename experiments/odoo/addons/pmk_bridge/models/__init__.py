# -*- coding: utf-8 -*-
from . import sku
# №309: лист в м², габарит — единица «Лист WxL».
from . import sheet_uom
from . import reference_link
from . import spec_cost
# 20.10.2026: вкладка «Металлоизделия» — сводка изделий всех калькуляторов.
from . import spec_summary
# Ввод строк в сводке «Металлоизделия» — раскладка по категориям (22.10.2026).
from . import spec_entry
from . import reference_price
from . import kp_send
from . import mail_compose_message
# Разбор UX, шаг 28: признак «поставщик» для карточки контрагента.
from . import partner_supplier
# Шаг 58: кто выставляет КП — реквизиты и строка налога для печати.
from . import print_seller
# Шаг З-10: карточка товара позиции, принятой в справочник из «на разнос».
from . import pending_product
# 26.10.2026: каталог материалов — найти позицию глазами (окно catalog_dialog.js).
from . import catalog
