# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).
# test_drawing.py — обычный unittest без базы, запускается голым питоном
# (см. его шапку), сюда не подключается.
from . import test_list_units
from . import test_list_columns
from . import test_offcut_empty
from . import test_step27_form
from . import test_step29_hide
# Разбор UX, шаг 36: компактный верх, одна кнопка на лист, «Очередь листов»,
# лом в кг и ₽, с доводкой (деньги с ценой — только с мостом:
# -i pmk_laser,pmk_bridge,pmk_flow --test-tags /pmk_laser).
from . import test_step36_laser
# Разбор UX, шаг 46: «Посмотреть» чертёж детали окном DXF (pmk_drawing —
# мягко; с ним: -i pmk_laser,pmk_drawing).
from . import test_step46_drawing
