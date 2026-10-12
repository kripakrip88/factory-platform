# -*- coding: utf-8 -*-
"""Генератор развёрток вентзонта — ОДИН на ERP и пакет раскроя: pmk_calc/tools/vent_hood.py (калькулятор).

До 12.10.2026 здесь лежала копия генератора со свесом-параметром; ERP-сессия перенесла свес в сам генератор
(f65710b), код совпал файл в файл — копия убрана, чтобы правки генератора (например, правило шага лапок)
не приходилось делать в двух местах и сверка DXF заказа с генератором (api.Order) не разъехалась.

Пакет запускается и вне Odoo (тесты, командная строка, процесс-воркер), поэтому генератор грузится как файл
по пути, а не как пакет odoo.addons. Путь по умолчанию — соседний модуль в том же каталоге аддонов:
    <аддоны>/pmk_vent_nest/lib/vent_nesting/hood_sves.py → <аддоны>/pmk_calc/tools/vent_hood.py
Переопределить — переменной окружения VENT_HOOD_GENERATOR (полный путь к vent_hood.py).
Нет файла — ImportError с понятным текстом (без тихого отката на старую копию).
"""
import os
import importlib.util

GENERATOR_PATH = os.environ.get("VENT_HOOD_GENERATOR") or os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "pmk_calc", "tools", "vent_hood.py"))

if not os.path.isfile(GENERATOR_PATH):
    raise ImportError("генератор вентзонтов не найден: %s — нужен модуль pmk_calc рядом с pmk_vent_nest "
                      "(или путь в переменной окружения VENT_HOOD_GENERATOR)" % GENERATOR_PATH)

_spec = importlib.util.spec_from_file_location("vent_nesting._vent_hood_generator", GENERATOR_PATH)
_gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gen)
for _k, _v in vars(_gen).items():
    if not _k.startswith("__"):
        globals()[_k] = _v
if not hasattr(_gen, "SVES_MIN") or "sves" not in _gen.hood.__code__.co_varnames:
    raise ImportError("генератор %s без параметра свеса (нужен pmk_calc с f65710b и новее)" % GENERATOR_PATH)
