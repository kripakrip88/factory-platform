# -*- coding: utf-8 -*-
"""Тесты генератора артикулов.

Обычный unittest, без TransactionCase: генератор — чистые функции, база ему
не нужна. Поэтому тесты гоняются и внутри Odoo (--test-enable), и голым
питоном на ноутбуке, до всякого деплоя:

    python3 -m unittest discover -s experiments/odoo/addons/pmk_bridge -v

Набор собран не «для галочки»: сюда сложены ровно те случаи, на которых
самодельная транслитерация обычно и ломается.
"""

import unittest

try:
    # Внутри Odoo модуль импортируется как odoo.addons.pmk_bridge.models.sku.
    from ..models import sku
except (ImportError, ValueError):
    # Голым питоном — как соседний файл.
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from models import sku


class TestTranslit(unittest.TestCase):
    """Транслитерация сама по себе."""

    def test_token_romb(self):
        # «ромб» по буквам дал бы «romb». Утверждено RHM, значит это токен, а
        # не набор символов.
        self.assertEqual(sku.translit("ромб"), "RHM")

    def test_sh_gives_two_letters(self):
        # Ш — одна буква, но две латинских. Любой посимвольный расчёт длины
        # артикула «по числу символов исходника» на ней врёт.
        self.assertEqual(sku.translit("Ш"), "SH")
        self.assertEqual(sku.translit("ш"), "sh")

    def test_case_is_preserved(self):
        # На сохранении регистра держится утверждённый VGP-Du15x2.5.
        self.assertEqual(sku.translit("Ду"), "Du")
        self.assertEqual(sku.translit("а"), "a")
        self.assertEqual(sku.translit("А"), "A")

    def test_ascii_passes_through(self):
        self.assertEqual(sku.translit("63x63x5"), "63x63x5")
        self.assertEqual(sku.translit("d12"), "d12")

    def test_unknown_non_ascii_raises(self):
        # Тихая подмена на «?» склеила бы разные позиции в один артикул.
        with self.assertRaises(sku.SkuError):
            sku.translit("20°")


class TestProfileSku(unittest.TestCase):
    """Прокат: 665 строк, разделитель — латинская «x»."""

    def test_approved_examples(self):
        # Артикулы из решения владельца. Если тест упал — поменяли схему,
        # а не «поправили мелочь».
        self.assertEqual(sku.profile_sku("Арматура", "d12"), "ARM-d12")
        self.assertEqual(sku.profile_sku("Двутавр", "20Б1"), "DVT-20B1")
        self.assertEqual(sku.profile_sku("Круг", "d12"), "KRG-d12")
        self.assertEqual(sku.profile_sku("Уголок равнополочный", "63x63x5"), "UGR-63x63x5")
        self.assertEqual(sku.profile_sku("Уголок неравнополочный", "125x80x8"), "UGN-125x80x8")
        self.assertEqual(sku.profile_sku("Шестигранник", "S24"), "SHG-S24")
        self.assertEqual(sku.profile_sku("Труба круглая", "89x4"), "TRK-89x4")
        self.assertEqual(sku.profile_sku("Труба профильная квадратная", "100x100x3"),
                         "TPK-100x100x3")
        self.assertEqual(sku.profile_sku("Труба профильная прямоугольная", "180x100x6"),
                         "TPP-180x100x6")

    def test_fraction_in_number(self):
        # 6,5У — точка внутри номера. Парсер, режущий строку «по первой
        # нецифре», отрезал бы «5У».
        self.assertEqual(sku.profile_sku("Швеллер", "6.5У"), "SHV-6.5U")
        self.assertEqual(sku.profile_sku("Швеллер", "6.5Э"), "SHV-6.5E")

    def test_lowercase_a_modifier(self):
        # 16аП: строчная «а» — это увеличенный вариант профиля, отдельная
        # позиция. Подъём в верхний регистр слил бы 16аП и 16АП, а потеря
        # буквы — 16аП и 16П.
        self.assertEqual(sku.profile_sku("Швеллер", "16аП"), "SHV-16aP")
        self.assertEqual(sku.profile_sku("Швеллер", "18аУ"), "SHV-18aU")
        self.assertNotEqual(sku.profile_sku("Швеллер", "16аП"),
                            sku.profile_sku("Швеллер", "16П"))

    def test_sh_in_beam(self):
        # 20Ш1 — Ш даёт две буквы, артикул длиннее исходника.
        self.assertEqual(sku.profile_sku("Двутавр", "20Ш1"), "DVT-20SH1")
        # И не сливается с широкополочным 20Б1 и колонным 20К1.
        self.assertEqual(len({sku.profile_sku("Двутавр", s)
                              for s in ("20Б1", "20Ш1", "20К1")}), 3)

    def test_seamless_suffix(self):
        # Бесшовная и электросварная — две разные карточки: разные ГОСТы и
        # разные цены. Суффикс их разводит, но оставляет рядом в сортировке.
        self.assertEqual(sku.profile_sku("Труба круглая", "89x4 бесш"), "TRK-89x4-BS")
        self.assertNotEqual(sku.profile_sku("Труба круглая", "89x4"),
                            sku.profile_sku("Труба круглая", "89x4 бесш"))

    def test_vgp_du(self):
        # Ду — условный проход, не наружный диаметр. ВГП Ду15 имеет наружный
        # 21.3 мм, так что выбросить «Ду» нельзя: получится другая труба.
        self.assertEqual(sku.profile_sku("Труба ВГП", "Ду15x2.5"), "VGP-Du15x2.5")
        self.assertEqual(sku.profile_sku("Труба ВГП", "Ду100x4.5"), "VGP-Du100x4.5")

    def test_bare_number_square(self):
        # Квадрат «10» — чистое число без единой буквы. Парсер, ждущий букву
        # как якорь, на этой строке падает.
        self.assertEqual(sku.profile_sku("Квадрат", "10"), "KVD-10")
        self.assertEqual(sku.profile_sku("Квадрат", "200"), "KVD-200")

    def test_fastener_separator_rejected(self):
        # Строка метизов в парсере проката — не «почти то же самое».
        with self.assertRaises(sku.SkuError):
            sku.profile_sku("Круг", "М8×20")

    def test_cyrillic_x_rejected(self):
        # Кириллическая «х» в «63х63х5» неотличима глазом от латинской.
        # Пропустив её, получим второй артикул на тот же уголок.
        with self.assertRaises(sku.SkuError):
            sku.profile_sku("Уголок равнополочный", "63х63х5")

    def test_unknown_type_and_empty_size(self):
        with self.assertRaises(sku.SkuError):
            sku.profile_sku("Балка двутавровая", "20Б1")
        with self.assertRaises(sku.SkuError):
            sku.profile_sku("Двутавр", "")
        with self.assertRaises(sku.SkuError):
            sku.profile_sku("Труба круглая", "89xx4")


class TestSheetSku(unittest.TestCase):
    """Лист: считаем штуками, габарит — характеристика, в артикул не входит."""

    def test_approved_examples(self):
        self.assertEqual(sku.sheet_sku("Гладкий", 3), "LST-GL-3")
        self.assertEqual(sku.sheet_sku("Рифлёный", 4, "ромб"), "LST-RF-4")
        self.assertEqual(sku.sheet_sku("Просечно-вытяжной", 4, "406"), "LST-PV-406")
        self.assertEqual(sku.sheet_sku("Оцинкованный тонколистовой", 0.5), "LST-ZN-0.5")

    def test_thickness_normalised(self):
        # «1», «1.0» и 1.00 из Float-поля — один и тот же лист. Иначе две
        # загрузки заведут две карточки.
        self.assertEqual(sku.sheet_sku("Гладкий", 1), sku.sheet_sku("Гладкий", "1.0"))
        self.assertEqual(sku.sheet_sku("Оцинкованный тонколистовой", 1.00), "LST-ZN-1")
        self.assertEqual(sku.sheet_sku("Оцинкованный тонколистовой", 0.35), "LST-ZN-0.35")

    def test_pvl_uses_label_not_thickness(self):
        # 506, 508 и 510 — три разных ПВЛ толщиной 5 мм. По толщине они
        # схлопнулись бы в один артикул.
        codes = {sku.sheet_sku("Просечно-вытяжной", 5, lbl) for lbl in ("506", "508", "510")}
        self.assertEqual(codes, {"LST-PV-506", "LST-PV-508", "LST-PV-510"})

    def test_pvl_without_label_raises(self):
        with self.assertRaises(sku.SkuError):
            sku.sheet_sku("Просечно-вытяжной", 5, "")

    def test_non_default_pattern_goes_into_sku(self):
        # Ромб — базовое рифление и в артикуле не пишется. Любое другое —
        # пишется, иначе два рифления одной толщины дадут один артикул.
        self.assertEqual(sku.sheet_sku("Рифлёный", 4, "чечевица"), "LST-RF-4-chechevitsa")
        self.assertNotEqual(sku.sheet_sku("Рифлёный", 4, "ромб"),
                            sku.sheet_sku("Рифлёный", 4, "чечевица"))

    def test_unknown_type(self):
        with self.assertRaises(sku.SkuError):
            sku.sheet_sku("Нержавеющий", 3)


class TestFastenerSku(unittest.TestCase):
    """Метизы: разделитель «×» (U+00D7), «М» кириллическая (U+041C)."""

    def test_approved_example(self):
        self.assertEqual(sku.fastener_sku("bolt", "М8×20"), "MTZ-BLT-M8x20")

    def test_all_kinds(self):
        self.assertEqual(sku.fastener_sku("nut", "М8"), "MTZ-NUT-M8")
        self.assertEqual(sku.fastener_sku("washer", "М8"), "MTZ-WSH-M8")
        self.assertEqual(sku.fastener_sku("anchor", "М10×100"), "MTZ-ANC-M10x100")
        # Саморез — без резьбовой «М» вообще, только два числа.
        self.assertEqual(sku.fastener_sku("screw", "4.8×35"), "MTZ-SCR-4.8x35")

    def test_kind_separates_same_size(self):
        # Гайка М8, шайба М8 и болт М8×20 — три разные позиции с похожим
        # размером. Вид метиза в артикуле их и разводит.
        codes = {sku.fastener_sku("nut", "М8"), sku.fastener_sku("washer", "М8"),
                 sku.fastener_sku("bolt", "М8×20")}
        self.assertEqual(len(codes), 3)

    def test_profile_separator_rejected(self):
        # Латинской «x» в справочнике метизов нет ни в одной из 25 строк.
        with self.assertRaises(sku.SkuError):
            sku.fastener_sku("bolt", "М8x20")

    def test_latin_m_rejected(self):
        with self.assertRaises(sku.SkuError):
            sku.fastener_sku("bolt", "M8×20")

    def test_unknown_kind_and_empty_parts(self):
        with self.assertRaises(sku.SkuError):
            sku.fastener_sku("rivet", "М8")
        with self.assertRaises(sku.SkuError):
            sku.fastener_sku("bolt", "М8×")


class TestPaintSku(unittest.TestCase):
    """ЛКП: товары в кг, артикул из латинского XML-id."""

    def test_all_six(self):
        self.assertEqual(sku.paint_sku("paint_gf021"), "LKP-GF021")
        self.assertEqual(sku.paint_sku("paint_pf115"), "LKP-PF115")
        self.assertEqual(sku.paint_sku("paint_3in1"), "LKP-3IN1")
        self.assertEqual(sku.paint_sku("paint_powder_pe"), "LKP-POWDER-PE")
        self.assertEqual(sku.paint_sku("paint_zinc_hot"), "LKP-ZINC-HOT")
        self.assertEqual(sku.paint_sku("paint_zinc_cold"), "LKP-ZINC-COLD")

    def test_full_xmlid_accepted(self):
        # ir_model_data отдаёт «module.name» — загрузчику не должно быть
        # разницы, откуда он взял id.
        self.assertEqual(sku.paint_sku("pmk_calc.paint_gf021"), "LKP-GF021")

    def test_foreign_xmlid_rejected(self):
        with self.assertRaises(sku.SkuError):
            sku.paint_sku("coating_zinc")


class TestVariantSku(unittest.TestCase):
    """Варианты: марка стали — характеристика, а не отдельная карточка."""

    def test_approved_example(self):
        self.assertEqual(
            sku.variant_sku(sku.profile_sku("Двутавр", "20Б1"), sku.grade_code("09Г2С")),
            "DVT-20B1-09G2S")

    def test_all_eight_grades_distinct(self):
        grades = ["Ст3сп", "Ст3пс", "09Г2С", "10ХСНД", "17Г1С", "15ХСНД", "Ст20", "40Х"]
        codes = [sku.grade_code(g) for g in grades]
        self.assertEqual(codes, ["St3sp", "St3ps", "09G2S", "10HSND",
                                 "17G1S", "15HSND", "St20", "40H"])
        # Ст3сп и Ст3пс отличаются перестановкой двух букв — проверяем, что
        # различие переживает транслитерацию и в верхнем регистре тоже.
        self.assertEqual(len({c.upper() for c in codes}), 8)

    def test_sheet_variant_carries_size(self):
        # У листа две характеристики: марка и габарит. Порядок фиксирован,
        # иначе один вариант получит два артикула.
        self.assertEqual(
            sku.variant_sku(sku.sheet_sku("Гладкий", 3), sku.grade_code("Ст3сп"), "1500x6000"),
            "LST-GL-3-St3sp-1500x6000")

    def test_empty_suffix_rejected(self):
        with self.assertRaises(sku.SkuError):
            sku.variant_sku("DVT-20B1", "")
        with self.assertRaises(sku.SkuError):
            sku.grade_code("")


class TestDispatcher(unittest.TestCase):
    """Одна точка входа для загрузчика: он идёт по четырём справочникам."""

    def test_four_models(self):
        self.assertEqual(
            sku.sku_for_row("pmk.metal.profile",
                            {"profile_type": "Швеллер", "size_label": "6.5У"}),
            "SHV-6.5U")
        self.assertEqual(
            sku.sku_for_row("pmk.metal.sheet",
                            {"sheet_type": "Гладкий", "thickness_mm": 3, "size_label": ""}),
            "LST-GL-3")
        self.assertEqual(
            sku.sku_for_row("pmk.metal.fastener",
                            {"fastener_type": "bolt", "size_label": "М8×20"}),
            "MTZ-BLT-M8x20")
        self.assertEqual(
            sku.sku_for_row("pmk.paint.coating", {"id": "paint_gf021"}), "LKP-GF021")

    def test_unknown_model(self):
        with self.assertRaises(sku.SkuError):
            sku.sku_for_row("pmk.metal.grade", {"name": "Ст3сп"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
