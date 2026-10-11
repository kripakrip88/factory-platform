# Эталоны генератора вентзонтов

Копия `tests/` и `tools/dxfread.py` из папки генератора Антона (`vent_hood_generator`,
11.10.2026) — без правок. 51 эталонный случай: DXF и спецификация.

Проверка переноса: `pmk_calc/tools/vent_hood.py` должен давать 51 из 51.

    python3 tests/vent_hood_golden/tests/check_golden.py --module tools/vent_hood.py

Тот же прогон делает тест Odoo `test_vent_hood.py` (во временной папке: проверка
пишет свои DXF рядом с эталонами). Эталоны пересобирать только в папке генератора
(`--regen` + сверка с шаблонами КОМПАС), затем копировать сюда вместе с vent_hood.py.
