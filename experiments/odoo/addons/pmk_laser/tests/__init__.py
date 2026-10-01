# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).
# test_drawing.py — обычный unittest без базы, запускается голым питоном
# (см. его шапку), сюда не подключается.
from . import test_list_units
from . import test_list_columns
from . import test_offcut_empty
from . import test_step27_form
from . import test_step29_hide
