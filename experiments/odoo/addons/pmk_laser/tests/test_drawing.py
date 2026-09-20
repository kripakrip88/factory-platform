# -*- coding: utf-8 -*-
"""Тесты метрик чертежа.

Две части. Синтетические чертежи проверяют арифметику: там геометрия
задана руками и правильный ответ известен из формулы, а не из прогона
кода. Живые чертежи закрепляют числа, посчитанные на 29 файлах развёрток
вентзонтов, — чтобы правка правил очистки не сдвинула их молча.

Живые тесты пропускаются, если файлов рядом нет: на чужой машине набор
чертежей может отсутствовать, и это не повод валить всю пачку.

Запуск:
    PYTHONPATH=<pylibs>:<addons>/pmk_laser python3 -m unittest discover -s tests
"""

from __future__ import annotations

import math
import os
import unittest

import ezdxf

from tools.drawing import (
    CleanupRules,
    analyze,
    entity_length_mm,
    render_svg,
)

DOWNLOADS = os.path.expanduser("~/Downloads")


def _new_doc(insunits: int = 4):
    """Пустой чертёж в заданных единицах."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = insunits
    return doc, doc.modelspace()


def _live(*parts: str) -> str:
    return os.path.join(DOWNLOADS, *parts)


def _require(path: str) -> None:
    if not os.path.exists(path):
        raise unittest.SkipTest("нет живого чертежа: %s" % path)


# ── АРИФМЕТИКА ДЛИН ────────────────────────────────────────────────────────


class TestEntityLength(unittest.TestCase):
    """Длина примитива должна совпадать с формулой, а не «примерно»."""

    def test_line(self):
        _doc, msp = _new_doc()
        line = msp.add_line((0, 0), (3, 4))
        self.assertAlmostEqual(entity_length_mm(line), 5.0, places=9)

    def test_circle(self):
        _doc, msp = _new_doc()
        circle = msp.add_circle((10, 10), radius=7.5)
        self.assertAlmostEqual(entity_length_mm(circle), 2 * math.pi * 7.5, places=9)

    def test_arc_quarter(self):
        _doc, msp = _new_doc()
        arc = msp.add_arc((0, 0), radius=10.0, start_angle=0, end_angle=90)
        self.assertAlmostEqual(entity_length_mm(arc), math.pi * 10.0 / 2.0, places=9)

    def test_arc_wrapping_zero(self):
        """Дуга через ноль градусов: 350°..10° — это 20°, а не -340°."""
        _doc, msp = _new_doc()
        arc = msp.add_arc((0, 0), radius=10.0, start_angle=350, end_angle=10)
        self.assertAlmostEqual(entity_length_mm(arc), math.radians(20) * 10.0, places=9)

    def test_polyline_bulge_is_not_ignored(self):
        """Главная ловушка: по вершинам паз даёт 18.0 вместо 23.14.

        Полилиния из живого чертежа: четыре вершины, на двух сегментах
        bulge=-1, то есть полуокружности. Хорда каждой 4.5, значит радиус
        2.25, и каждая полуокружность добавляет pi*2.25 поверх прямых.
        """
        _doc, msp = _new_doc()
        polyline = msp.add_lwpolyline(
            [
                (-722.473893165748, 19.25401072947837, 0, 0, -1.0),
                (-718.3448058302312, 21.04304336631708, 0, 0, 0.0),
                (-716.5557731933943, 16.91395603080075, 0, 0, -1.0),
                (-720.6848605289063, 15.12492339396113, 0, 0, 0.0),
            ],
            format="xyseb",
            close=True,
        )
        expected = 2 * 4.5 + 2 * math.pi * 2.25
        self.assertAlmostEqual(entity_length_mm(polyline), expected, places=3)
        # И заодно фиксируем, что наивная сумма по вершинам сильно меньше:
        # если кто-то «упростит» расчёт, тест это поймает.
        self.assertGreater(entity_length_mm(polyline), 23.0)

    def test_polyline_open_vs_closed(self):
        """У замкнутой полилинии есть замыкающий сегмент, у открытой нет."""
        _doc, msp = _new_doc()
        square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        open_pl = msp.add_lwpolyline(square, close=False)
        closed_pl = msp.add_lwpolyline(square, close=True)
        self.assertAlmostEqual(entity_length_mm(open_pl), 30.0, places=9)
        self.assertAlmostEqual(entity_length_mm(closed_pl), 40.0, places=9)


# ── ПРАВИЛА ОЧИСТКИ ────────────────────────────────────────────────────────


class TestCleanupRules(unittest.TestCase):

    def test_duplicate_line_counted_once(self):
        """Дважды начерченный отрезок режется один раз."""
        _doc, msp = _new_doc()
        msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
        msp.add_line((0, 0), (10, 0))
        msp.add_line((10, 0), (0, 0))  # тот же отрезок, записан наоборот
        metrics = analyze_doc(msp.doc)
        self.assertIn("дубликат объекта", metrics.dropped)
        self.assertEqual(metrics.dropped["дубликат объекта"][0], 1)

    def test_duplicates_can_be_kept(self):
        """Правило выключается настройкой, а не правкой кода."""
        _doc, msp = _new_doc()
        msp.add_line((0, 0), (10, 0))
        msp.add_line((0, 0), (10, 0))
        kept = analyze_doc(msp.doc, CleanupRules(drop_duplicates=False))
        self.assertNotIn("дубликат объекта", kept.dropped)

    def test_open_chain_is_bend_not_cut(self):
        """Открытая цепочка — линия гиба: в рез не идёт, в проколы тоже."""
        _doc, msp = _new_doc()
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
        msp.add_line((10, 50), (90, 50))  # линия гиба поперёк детали
        metrics = analyze_doc(msp.doc)
        self.assertAlmostEqual(metrics.cut_length_mm, 400.0, places=6)
        self.assertAlmostEqual(metrics.bend_length_mm, 80.0, places=6)
        self.assertEqual(metrics.pierce_count, 1)

    def test_bend_layer_by_pattern(self):
        """Слой с «гиб» в имени уходит в гибы даже замкнутым контуром."""
        _doc, msp = _new_doc()
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
        msp.add_line((10, 50), (90, 50), dxfattribs={"layer": "Линии гиба"})
        metrics = analyze_doc(msp.doc)
        self.assertAlmostEqual(metrics.cut_length_mm, 400.0, places=6)
        self.assertAlmostEqual(metrics.bend_length_mm, 80.0, places=6)

    def test_skip_layer_from_settings(self):
        """Слой выкидывается настройкой, имя слоя в коде не зашито."""
        _doc, msp = _new_doc()
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
        msp.add_circle((50, 50), radius=10, dxfattribs={"layer": "Размеры"})
        default = analyze_doc(msp.doc)
        self.assertEqual(default.pierce_count, 2)
        filtered = analyze_doc(msp.doc, CleanupRules(skip_layers=("Размеры",)))
        self.assertEqual(filtered.pierce_count, 1)
        self.assertAlmostEqual(filtered.cut_length_mm, 400.0, places=6)

    def test_defpoints_skipped_by_default(self):
        """Служебный слой AutoCAD не печатается и не режется."""
        _doc, msp = _new_doc()
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
        msp.add_circle((50, 50), radius=10, dxfattribs={"layer": "Defpoints"})
        metrics = analyze_doc(msp.doc)
        self.assertEqual(metrics.pierce_count, 1)

    def test_frozen_layer_skipped(self):
        doc, msp = _new_doc()
        doc.layers.add("Черновик")
        doc.layers.get("Черновик").freeze()
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
        msp.add_circle((50, 50), radius=10, dxfattribs={"layer": "Черновик"})
        metrics = analyze_doc(doc)
        self.assertEqual(metrics.pierce_count, 1)

    def test_degenerate_entity_dropped(self):
        _doc, msp = _new_doc()
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
        msp.add_line((5, 5), (5, 5))  # отрезок нулевой длины
        metrics = analyze_doc(msp.doc)
        self.assertIn("вырожденный объект", metrics.dropped)
        self.assertAlmostEqual(metrics.cut_length_mm, 400.0, places=6)

    def test_text_is_not_cut(self):
        """Надписи и размеры — оформление, а не рез."""
        _doc, msp = _new_doc()
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
        msp.add_text("деталь 1").set_placement((10, 10))
        metrics = analyze_doc(msp.doc)
        self.assertAlmostEqual(metrics.cut_length_mm, 400.0, places=6)
        self.assertTrue(any("не режущийся" in reason for reason in metrics.dropped))


class TestSheetFrame(unittest.TestCase):
    """Рамка листа опознаётся по геометрии, а не по имени слоя."""

    def test_frame_around_two_parts_is_dropped(self):
        _doc, msp = _new_doc()
        # Рамка стандартного листа 1500x3000.
        msp.add_lwpolyline(
            [(0, 0), (3000, 0), (3000, 1500), (0, 1500)], close=True)
        msp.add_lwpolyline(
            [(100, 100), (500, 100), (500, 500), (100, 500)], close=True)
        msp.add_lwpolyline(
            [(1000, 100), (1400, 100), (1400, 500), (1000, 500)], close=True)
        metrics = analyze_doc(msp.doc)
        self.assertEqual(metrics.part_count, 2)
        self.assertEqual(metrics.pierce_count, 2)
        self.assertAlmostEqual(metrics.cut_length_mm, 3200.0, places=6)
        self.assertTrue(any("рамка листа" in reason for reason in metrics.dropped))

    def test_single_part_with_holes_is_not_a_frame(self):
        """Опасный случай: наружный контур детали тоже «содержит всё».

        Если правило рамки написать как «контур, внутри которого лежит
        остальное», единственная деталь с отверстиями потеряет свой наружный
        контур, и рез уедет вниз. Спасает проверка габарита по листу.
        """
        _doc, msp = _new_doc()
        msp.add_lwpolyline(
            [(0, 0), (800, 0), (800, 600), (0, 600)], close=True)
        msp.add_circle((200, 300), radius=25)
        msp.add_circle((600, 300), radius=25)
        metrics = analyze_doc(msp.doc)
        self.assertEqual(metrics.part_count, 1)
        self.assertEqual(metrics.hole_count, 2)
        self.assertEqual(metrics.pierce_count, 3)
        self.assertAlmostEqual(
            metrics.cut_length_mm, 2800.0 + 2 * 2 * math.pi * 25, places=6)

    def test_part_sized_like_a_sheet_but_not_rectangular_is_kept(self):
        """Деталь в габарите листа рамкой не считается: периметр выдаёт."""
        _doc, msp = _new_doc()
        # Гребёнка 3000x1500: габарит листа, но периметр много больше 9000.
        points = [(0, 0), (3000, 0), (3000, 1500)]
        x = 3000.0
        while x > 0:
            points.append((x, 1200))
            points.append((x - 100, 1200))
            points.append((x - 100, 1500))
            points.append((x - 200, 1500))
            x -= 200
        msp.add_lwpolyline(points, close=True)
        msp.add_circle((500, 500), radius=20)
        metrics = analyze_doc(msp.doc)
        self.assertEqual(metrics.part_count, 1)
        self.assertFalse(any("рамка листа" in r for r in metrics.dropped))


class TestUnits(unittest.TestCase):

    def test_inches_converted_to_mm(self):
        """Дюймовый чертёж без пересчёта занизил бы рез в 25.4 раза."""
        _doc, msp = _new_doc(insunits=1)
        msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
        metrics = analyze_doc(msp.doc)
        self.assertAlmostEqual(metrics.cut_length_mm, 40.0 * 25.4, places=6)
        self.assertTrue(metrics.warnings)

    def test_missing_units_warns_but_counts(self):
        _doc, msp = _new_doc(insunits=0)
        msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
        metrics = analyze_doc(msp.doc)
        self.assertAlmostEqual(metrics.cut_length_mm, 40.0, places=6)
        self.assertTrue(any("INSUNITS" in w for w in metrics.warnings))


class TestRulesSerialization(unittest.TestCase):

    def test_round_trip_through_dict(self):
        rules = CleanupRules(skip_layers=("Рамка",), min_contour_length_mm=2.0)
        restored = CleanupRules.from_dict(rules.to_dict())
        self.assertEqual(restored, rules)

    def test_json_lists_become_tuples(self):
        """Из JSON кортежи приезжают списками — правила должны остаться
        хешируемыми, иначе frozen dataclass развалится при сравнении."""
        restored = CleanupRules.from_dict({
            "skip_layers": ["Размеры", "Рамка"],
            "sheet_frame_sizes_mm": [[1500.0, 3000.0]],
        })
        self.assertEqual(restored.skip_layers, ("Размеры", "Рамка"))
        self.assertEqual(restored.sheet_frame_sizes_mm, ((1500.0, 3000.0),))
        hash(restored)

    def test_unknown_keys_ignored(self):
        restored = CleanupRules.from_dict({"нет_такого_правила": 1})
        self.assertEqual(restored, CleanupRules())


# ── ЖИВЫЕ ЧЕРТЕЖИ ──────────────────────────────────────────────────────────


class TestLiveDrawings(unittest.TestCase):
    """Числа, посчитанные на присланных файлах. Сдвинулись — значит правила
    очистки поменяли смысл, и это надо объяснить, а не принять молча."""

    def test_vsh_1000x1200(self):
        path = _live("вш 1000х1200.dxf")
        _require(path)
        metrics = analyze(path)
        self.assertAlmostEqual(metrics.cut_length_mm, 17423.2, delta=0.1)
        self.assertEqual(metrics.pierce_count, 88)
        self.assertEqual(metrics.part_count, 4)
        self.assertAlmostEqual(metrics.width_mm, 2196.3, delta=0.1)
        self.assertAlmostEqual(metrics.height_mm, 1581.1, delta=0.1)

    def test_duplicate_lines_found_in_live_file(self):
        """В четырёх файлах «вш 1000х*» по два отрезка начерчено дважды."""
        path = _live("вш 1000х1200.dxf")
        _require(path)
        metrics = analyze(path)
        count, length = metrics.dropped["дубликат объекта"]
        self.assertEqual(count, 2)
        self.assertAlmostEqual(length, 42.43, delta=0.01)

    def test_system_layer_is_a_real_part_not_a_frame(self):
        """Ключевая проверка.

        На трёх файлах «24л» есть слой «Системный слой» длиной 5373-5507 мм,
        и его легко принять за рамку раскройной программы. Это не рамка:
        контур замкнут, габарит 961x1581 — ровно как у двух соседних панелей
        корпуса, в нём 12 отверстий Ø7 под лапки с тем же шагом 275 мм, и
        лежит он не ВОКРУГ остальной геометрии, а между двумя панелями
        третьей секцией. У файла без «24л» таких панелей две, у этого три.

        Выкинуть его по имени слоя значило бы потерять реальную деталь и
        занизить рез. Тест закрепляет: по умолчанию слой остаётся.
        """
        path = _live("вш 1000х2500 24л.dxf")
        _require(path)
        metrics = analyze(path)
        self.assertEqual(metrics.part_count, 5)

        system = [c for c in metrics.contours if c.layer == "Системный слой"]
        self.assertEqual(len(system), 13)  # 1 контур панели + 12 отверстий
        panel = max(system, key=lambda c: c.length_mm)
        self.assertTrue(panel.closed)
        self.assertEqual(panel.depth, 0)
        self.assertAlmostEqual(panel.width_mm, 961.0, delta=0.1)
        self.assertAlmostEqual(panel.height_mm, 1581.1, delta=0.1)

        # Соседний файл без «24л» — тот же чертёж, но панелей две.
        sibling = _live("вш 1000х1200.dxf")
        _require(sibling)
        self.assertEqual(analyze(sibling).part_count, 4)

    def test_system_layer_can_be_excluded_by_settings(self):
        """Если на другом заводе этот слой всё-таки мусорный — он убирается
        настройкой, и видно, сколько именно ушло."""
        path = _live("вш 1000х2500 24л.dxf")
        _require(path)
        full = analyze(path)
        trimmed = analyze(path, CleanupRules(
            skip_layers=("Defpoints", "Системный слой")))
        self.assertEqual(trimmed.part_count, 4)
        self.assertAlmostEqual(
            full.cut_length_mm - trimmed.cut_length_mm, 5373.0, delta=0.1)

    def test_no_open_chains_in_live_set(self):
        """На этих 29 чертежах линий гиба нет ни одной: все цепочки замкнуты.

        Правило про открытые цепочки всё равно нужно — оно ловит разметку в
        чертежах из другой CAD, — но врать, что оно здесь что-то чистит,
        нельзя. Тест фиксирует факт.
        """
        path = _live("вш 600х3800.dxf")
        _require(path)
        metrics = analyze(path)
        self.assertEqual(metrics.bend_length_mm, 0.0)
        self.assertTrue(all(c.closed for c in metrics.contours))

    def test_hood_layer_with_arcs(self):
        """Файлы vent_dxf собраны из LINE+ARC, а не из полилиний: контур
        обязан собраться из россыпи примитивов."""
        path = _live("vent_dxf", "вш400х550.dxf")
        _require(path)
        metrics = analyze(path)
        self.assertEqual(metrics.part_count, 3)
        self.assertEqual(metrics.pierce_count, 47)
        self.assertAlmostEqual(metrics.cut_length_mm, 7860.8, delta=0.1)

    def test_same_hood_two_formats_agree(self):
        """Один и тот же зонт вш400х650, начерченный дугами (vent_dxf) и
        полилиниями (корень) — рез должен сойтись, иначе одна из веток
        разбора считает неправильно."""
        arcs = _live("vent_dxf", "вш400х650.dxf")
        polys = _live("вш400х650.dxf")
        _require(arcs)
        _require(polys)
        left = analyze(arcs)
        right = analyze(polys)
        self.assertEqual(left.part_count, right.part_count)
        self.assertEqual(left.pierce_count, right.pierce_count)
        self.assertAlmostEqual(left.cut_length_mm, right.cut_length_mm, delta=0.5)


class TestPreview(unittest.TestCase):

    def test_svg_has_geometry(self):
        path = _live("вш 1000х2500 24л.dxf")
        _require(path)
        content = render_svg(path)
        self.assertTrue(content.startswith("<?xml"))
        self.assertIn("<svg", content)
        # 176 путей — это вся геометрия чертежа, а не пустая страница.
        self.assertGreater(content.count("<path"), 100)

    def test_svg_respects_cleanup_rules(self):
        """Картинка рисуется тем же ситом, что и цифры: убрали слой из
        расчёта — он должен пропасть и с превью."""
        path = _live("вш 1000х2500 24л.dxf")
        _require(path)
        full = render_svg(path)
        trimmed = render_svg(path, CleanupRules(
            skip_layers=("Defpoints", "Системный слой")))
        self.assertLess(trimmed.count("<path"), full.count("<path"))


# ── вспомогательное ────────────────────────────────────────────────────────


def analyze_doc(doc, rules=None):
    """Посчитать метрики для чертежа, собранного в памяти.

    analyze() принимает путь, потому что в бою файл приходит с диска.
    Синтетические чертежи сохраняем во временный файл — так тесты идут по
    тому же пути, что и боевой вызов, включая чтение заголовка.
    """
    import tempfile

    handle = tempfile.NamedTemporaryFile(suffix=".dxf", delete=False)
    handle.close()
    try:
        doc.saveas(handle.name)
        return analyze(handle.name, rules)
    finally:
        os.unlink(handle.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
