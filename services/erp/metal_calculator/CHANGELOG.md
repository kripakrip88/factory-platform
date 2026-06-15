# Changelog — metal_calculator

## Раскрой металла (feature/metal-cutting)
- Модуль раскроя внутри metal_calculator (изолирован, не трогает калькулятор/справочники).
- DocTypes: Cutting Plan, Cutting Plan Item, Stock Length (не связаны с Item/Work Order/BOM ERP).
- Линейный раскрой (1D, First Fit Decreasing) с учётом kerf, группировка по сортаменту.
- Листовой гильотинный раскрой (2D, полочный shelf) с поворотом детали на 90°, SVG-карты.
- Кнопка «Добавить в раскрой» в калькуляторе веса → накопительный Cutting Plan.
- Размеры заготовки задаёт человек (без авто-дефолта); деловой остаток не выделяется.
- Юнит-тесты test_cutting_linear / test_cutting_sheet.
