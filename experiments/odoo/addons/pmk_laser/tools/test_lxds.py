# -*- coding: utf-8 -*-
"""Тесты разбора .lxds.

Две половины. Первая гоняет разбор на живых управляющих файлах с лазера и
сверяет с цифрами, посчитанными владельцем вручную — расхождение означает
ошибку в коде, а не повод подправить ожидание. Вторая собирает .lxds из XML
прямо в тесте: так проверяется арифметика и поведение на битом файле, и эта
половина работает всегда, даже когда живых файлов под рукой нет.

Запуск:
    python3 -m unittest discover -s experiments/odoo/addons/pmk_laser/tools -v

Каталог с живыми файлами берётся из PMK_LXDS_SAMPLES, если задан.
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lxds  # noqa: E402


def _find_samples():
    """Где лежат живые файлы CypCut. В репозиторий они не кладутся: это
    производственные файлы заказчиков, им место рядом с рабочим столом."""
    candidates = []
    env = os.environ.get("PMK_LXDS_SAMPLES")
    if env:
        candidates.append(Path(env))
    candidates.append(Path(__file__).resolve().parent / "samples")
    candidates.append(Path.home() / "Downloads" / "nc")
    candidates.append(Path(
        "/private/tmp/claude-501/-Users-antonkarneev-Projects-factory-platform"
        "/1538398d-b6b6-4975-8322-dc4c80b8cac1/scratchpad/nc"))
    for folder in candidates:
        if folder.is_dir() and any(folder.glob("*.lxds")):
            return folder
    return None


SAMPLES = _find_samples()

# Цифры владельца, посчитанные вручную по этим же трём файлам.
# Ключ — начало имени файла, остальное подставляется поиском по каталогу.
CONTROL = {
    "10мм": dict(
        thickness=10.0, sheets=4, plate=(1500.0, 6000.0),
        utilizations=[66.7010838, 65.035262, 51.6898346, 25.5509243],
        parts=3, pieces=30, contours=660,
        useful_mass_kg=1476.42, premium_rub=738.21, rate=500.0,
    ),
    "2мм": dict(
        thickness=2.0, sheets=8, plate=(1000.0, 4000.0),
        utilizations=[89.2188472, 40.2359507],
        parts=1, pieces=380, contours=528,
        useful_mass_kg=417.47, premium_rub=1252.42, rate=3000.0,
    ),
    "3мм": dict(
        thickness=3.0, sheets=1, plate=(1500.0, 3000.0),
        utilizations=[72.9777778],
        parts=2, pieces=12, contours=65,
        useful_mass_kg=77.34, premium_rub=38.67, rate=500.0,
    ),
}


def _sample(prefix):
    for path in sorted(SAMPLES.glob("*.lxds")):
        if path.name.startswith(prefix):
            return path
    raise AssertionError(f"в {SAMPLES} нет файла на «{prefix}»")


@unittest.skipIf(SAMPLES is None,
                 "живых файлов .lxds нет — положите их в tools/samples "
                 "или укажите каталог в PMK_LXDS_SAMPLES")
class LiveFilesTest(unittest.TestCase):
    """Разбор на настоящих файлах с лазера, 08.09.2026."""

    @classmethod
    def setUpClass(cls):
        cls.reference = lxds.load_sheet_reference()

    def _analyze(self, prefix):
        return lxds.analyze(_sample(prefix), reference=self.reference)

    def test_состав_и_листы(self):
        for prefix, want in CONTROL.items():
            with self.subTest(prefix):
                layout = self._analyze(prefix)
                self.assertEqual(layout.thickness_mm, want["thickness"])
                self.assertEqual(layout.sheet_count, want["sheets"])
                self.assertEqual(len(layout.parts), want["parts"])
                self.assertEqual(layout.parts_declared, want["pieces"])
                self.assertEqual(layout.contours, want["contours"])
                for nest in layout.nests:
                    self.assertEqual((nest.width_mm, nest.height_mm), want["plate"])
                self.assertEqual(
                    [round(n.utilization_pct, 6) for n in layout.nests],
                    [round(u, 6) for u in want["utilizations"]])

    def test_вес_и_премия(self):
        """Главная сверка: полезный вес и премия против ручного счёта."""
        for prefix, want in CONTROL.items():
            with self.subTest(prefix):
                money = self._analyze(prefix).economics
                self.assertIsNotNone(money, "деньги обязаны посчитаться")
                self.assertEqual(money.premium_rate, want["rate"])
                self.assertAlmostEqual(money.useful_mass_kg, want["useful_mass_kg"], delta=0.01)
                self.assertAlmostEqual(money.premium_total_rub, want["premium_rub"], delta=0.01)

    def test_все_детали_разложены(self):
        """Заявлено = разложено на всех трёх файлах, предупреждений нет."""
        for prefix in CONTROL:
            with self.subTest(prefix):
                layout = self._analyze(prefix)
                self.assertEqual(layout.parts_nested, layout.parts_declared)
                self.assertEqual(layout.warnings, [])

    def test_режимы_демонстрационные(self):
        """Technical/content.xml побайтово один и тот же во всех файлах —
        на этом и держится решение брать толщину из имени."""
        digests = set()
        for prefix in CONTROL:
            layout = self._analyze(prefix)
            digests.add(layout.technical_md5)
            self.assertTrue(layout.demo_modes)
            # А заявленная в файле толщина — везде одна и та же неправда.
            self.assertEqual(layout.technical_declared["thickness"], "1.5")
        self.assertEqual(digests, {lxds.DEMO_TECHNICAL_MD5})

    def test_время_не_сдвигается(self):
        """SaveTime помечен «Z», но это местное время: 15:47 на десятке."""
        layout = self._analyze("10мм")
        self.assertEqual(layout.saved_at.strftime("%Y-%m-%d %H:%M:%S"), "2026-09-08 15:47:26")
        self.assertEqual(layout.app_version, "6.3.907.8")

    def test_имена_деталей(self):
        layout = self._analyze("10мм")
        self.assertEqual(
            sorted((p.name, p.amount) for p in layout.parts),
            [("Вторая деталь от края - 12шт", 12),
             ("Крайняя часть отвода - 12шт", 12),
             ("Центральная часть отвода - 6шт", 6)])

    def test_отчёт_печатается(self):
        text = lxds.format_report(self._analyze("2мм"))
        self.assertIn("380 шт", text)
        self.assertIn("8 листов", text)
        self.assertIn("1252", text)

    def test_cli_на_трёх_файлах(self):
        argv = [str(_sample(p)) for p in CONTROL] + ["--operator", "Иванов",
                                                     "--operator", "Петров"]
        buffer, stdout = io.StringIO(), sys.stdout
        sys.stdout = buffer
        try:
            code = lxds.main(argv)
        finally:
            sys.stdout = stdout
        self.assertEqual(code, 0)
        out = buffer.getvalue()
        self.assertIn(lxds.DEMO_TECHNICAL_MD5, out)
        # Премия делится пополам: 738.21 / 2 на десятке.
        self.assertIn("369.11", out)


class ThicknessFromNameTest(unittest.TestCase):
    """Толщина из имени — единственный живой источник, разбор проверяем зло."""

    def test_живые_имена(self):
        cases = {
            "10мм Виталий Отводы на 630 трубу Раскрой.lxds": 10.0,
            "2мм СМП810 Кронштейны для егозы - 380шт.lxds": 2.0,
            "3мм Сталкер Площадка ГРПШ шириной 1500мм Раскрой.lxds": 3.0,
        }
        for name, want in cases.items():
            with self.subTest(name):
                value, note = lxds.parse_thickness_from_name(name)
                self.assertEqual(value, want)
                self.assertTrue(note)

    def test_ширина_изделия_не_толщина(self):
        """Ловушка «шириной 1500мм»: 1500 мм лазер не режет."""
        value, _ = lxds.parse_thickness_from_name("Площадка шириной 1500мм 3мм.lxds")
        self.assertEqual(value, 3.0)

    def test_дробная_и_пробел(self):
        self.assertEqual(lxds.parse_thickness_from_name("1,5 мм Кожух.lxds")[0], 1.5)
        self.assertEqual(lxds.parse_thickness_from_name("0.8mm cover.lxds")[0], 0.8)

    def test_нет_толщины(self):
        value, note = lxds.parse_thickness_from_name("Раскрой без толщины.lxds")
        self.assertIsNone(value)
        self.assertIn("нет миллиметров", note)

    def test_только_негодные_миллиметры(self):
        value, note = lxds.parse_thickness_from_name("Балка длиной 12000мм.lxds")
        self.assertIsNone(value)
        self.assertIn("не похожи на толщину", note)


class PremiumRuleTest(unittest.TestCase):
    """Правило премии владельца, включая саму границу."""

    def test_граница_три_миллиметра(self):
        self.assertEqual(lxds.premium_rate(2.9), 3000.0)
        self.assertEqual(lxds.premium_rate(3.0), 500.0)   # «от 3 мм ВКЛЮЧИТЕЛЬНО»
        self.assertEqual(lxds.premium_rate(10.0), 500.0)

    def test_справочник_вместо_плотности(self):
        """Рифлёный квадрат тяжелее гладкого — ради этого и справочник."""
        reference = lxds.load_sheet_reference()
        flat = lxds.find_sheet_grade(3.0, "Гладкий", reference=reference)
        checker = lxds.find_sheet_grade(3.0, "Рифлёный", "ромб", reference=reference)
        self.assertEqual(flat.mass_per_sqm, 23.55)
        self.assertEqual(checker.mass_per_sqm, 25.1)
        self.assertGreater(checker.mass_per_sqm, flat.mass_per_sqm)

    def test_неоднозначный_типоразмер(self):
        """ПВЛ 5 мм бывает 506/508/510 — молча брать первый нельзя."""
        reference = lxds.load_sheet_reference()
        with self.assertRaises(lxds.LxdsError) as ctx:
            lxds.find_sheet_grade(5.0, "Просечно-вытяжной", reference=reference)
        self.assertIn("укажите типоразмер", str(ctx.exception))

    def test_нет_такой_толщины(self):
        reference = lxds.load_sheet_reference()
        with self.assertRaises(lxds.LxdsError) as ctx:
            lxds.find_sheet_grade(7.3, reference=reference)
        self.assertIn("нет листа", str(ctx.exception))


def _build_lxds(path, nests, parts=(("Деталь", 10),), thickness_note="4мм",
                technical=b"<Technical/>", shapes=12):
    """Собрать минимальный .lxds той же структуры, что пишет CypCut."""
    results = "".join(
        f'<NestResult Index="{i}" PartCount="{pc}" Utilization="{u}" '
        f'PlanCount="{n}" SizeX="{w}" SizeY="{h}"/>'
        for i, (w, h, u, n, pc) in enumerate(nests, start=1))
    parts_xml = "".join(
        f'<NestPart Name="{name}" Amount="{amount}" AmountUsed="{amount}"/>'
        for name, amount in parts)
    name = f"{thickness_note} Проба.lxds" if thickness_note else "Проба.lxds"
    target = Path(path) / name
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("info.xml",
                         '<PackData><Application AppName="CypCut" AppVer="6.3.907.8"/>'
                         '<SavedBy User="XE" Computer="XE6642" '
                         'SaveTime="2026-09-08T15:47:26Z"/></PackData>')
        archive.writestr("Nest2D/content.xml", f'<NestInfo><Results Count="{len(nests)}"/></NestInfo>')
        archive.writestr("Nest2D/Results/content.xml", f"<NestResults>{results}</NestResults>")
        for i, (w, h, u, n, _pc) in enumerate(nests, start=1):
            archive.writestr(
                f"Nest2D/Results/{i}/content.xml",
                f'<NestResult PlateAmount="{n}" Utilization="{u}">'
                f'<ExtMax X="{w}" Y="{h}"/></NestResult>')
        archive.writestr("Nest2D/Parts/content.xml", f"<Parts>{parts_xml}</Parts>")
        archive.writestr("Technical/content.xml", technical)
        archive.writestr("Shapes2D/content.xml",
                         "<Shapes2D>" + '<LwPolyline Handle="1"/>' * shapes + "</Shapes2D>")
    return target


class ArithmeticTest(unittest.TestCase):
    """Арифметика на собранном вручную файле — без живых файлов."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reference = lxds.load_sheet_reference()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_повтор_раскладки_это_листы(self):
        """Раскладка x5 = пять листов. Если считать раскладки, вес упадёт впятеро."""
        path = _build_lxds(self.tmp, [(1000.0, 2000.0, 50.0, 5, 2)],
                           parts=(("Деталь", 10),), thickness_note="4мм")
        layout = lxds.analyze(path, reference=self.reference)
        self.assertEqual(layout.sheet_count, 5)
        # 2 м² x 50% x 5 листов = 5 м²; 4 мм → 31.4 кг/м² → 157 кг.
        self.assertAlmostEqual(layout.useful_area_m2, 5.0, places=6)
        self.assertAlmostEqual(layout.economics.useful_mass_kg, 157.0, places=6)
        # 0.157 т x 500 ₽/т = 78.5 ₽.
        self.assertAlmostEqual(layout.economics.premium_total_rub, 78.5, places=6)

    def test_премия_делится_на_смену(self):
        path = _build_lxds(self.tmp, [(1000.0, 2000.0, 50.0, 5, 2)], thickness_note="4мм")
        for crew, share in ((("Иванов",), 78.5), (("Иванов", "Петров"), 39.25),
                            (("Иванов", "Петров", "Сидоров"), 78.5 / 3)):
            with self.subTest(len(crew)):
                money = lxds.analyze(path, operators=crew, reference=self.reference).economics
                self.assertEqual(len(money.operators), len(crew))
                self.assertAlmostEqual(money.premium_per_operator_rub, share, places=6)

    def test_неполный_раскрой_отмечается(self):
        """20 деталей заявлено, 10 разложено — замер нельзя относить к заказу."""
        path = _build_lxds(self.tmp, [(1000.0, 2000.0, 50.0, 1, 10)],
                           parts=(("Деталь", 20),), thickness_note="4мм")
        layout = lxds.analyze(path, reference=self.reference)
        self.assertEqual((layout.parts_declared, layout.parts_nested), (20, 10))
        self.assertTrue(any("не полностью" in w for w in layout.warnings))

    def test_без_толщины_разбор_живёт(self):
        """Имя без миллиметров: состав и листы читаются, деньги — нет."""
        path = _build_lxds(self.tmp, [(1000.0, 2000.0, 50.0, 2, 3)], thickness_note="")
        layout = lxds.analyze(path, reference=self.reference)
        self.assertEqual(layout.sheet_count, 2)
        self.assertIsNone(layout.economics)
        self.assertTrue(any("толщин" in w.lower() for w in layout.warnings))

    def test_расхождение_сводки_и_раскладки(self):
        """Сводка говорит 1 лист, сама раскладка — 3. Берём раскладку и говорим."""
        path = self.tmp / "5мм Расхождение.lxds"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("info.xml", "<PackData/>")
            archive.writestr("Nest2D/content.xml", "<NestInfo/>")
            archive.writestr("Nest2D/Results/content.xml",
                             '<NestResults><NestResult Index="1" PartCount="4" '
                             'Utilization="50" PlanCount="1" SizeX="1000" SizeY="2000"/>'
                             "</NestResults>")
            archive.writestr("Nest2D/Results/1/content.xml",
                             '<NestResult PlateAmount="3" Utilization="50">'
                             '<ExtMax X="1000" Y="2000"/></NestResult>')
        layout = lxds.read_layout(path)
        self.assertEqual(layout.sheet_count, 3)
        self.assertTrue(any("листов в сводке" in w for w in layout.warnings))

    def test_демо_режимы_по_эталону(self):
        """Чужой Technical → не демо; эталонный → демо."""
        own = _build_lxds(self.tmp, [(1000.0, 2000.0, 50.0, 1, 1)],
                          technical=b"<Technical>own</Technical>", thickness_note="4мм")
        self.assertFalse(lxds.read_layout(own).demo_modes)
        if SAMPLES is not None:
            sample = lxds.read_layout(_sample("3мм"))
            self.assertTrue(sample.demo_modes)


class BrokenInputTest(unittest.TestCase):
    """Битый или чужой файл обязан давать фразу, а не трейсбек."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _message(self, path):
        with self.assertRaises(lxds.LxdsError) as ctx:
            lxds.read_layout(path)
        message = str(ctx.exception)
        self.assertNotIn("Traceback", message)
        return message

    def test_файла_нет(self):
        self.assertIn("Файла нет", self._message(self.tmp / "нет.lxds"))

    def test_пустой_файл(self):
        path = self.tmp / "пустой.lxds"
        path.write_bytes(b"")
        self.assertIn("пустой", self._message(path))

    def test_не_zip(self):
        path = self.tmp / "чертёж.lxds"
        path.write_text("0\nSECTION\n2\nHEADER\n", encoding="utf-8")   # это DXF
        self.assertIn("не ZIP-контейнер", self._message(path))

    def test_zip_но_не_раскрой(self):
        path = self.tmp / "архив.lxds"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("readme.txt", "просто архив")
        message = self._message(path)
        self.assertIn("не раскрой CypCut", message)
        self.assertIn("info.xml", message)

    def test_испорченный_xml(self):
        path = self.tmp / "битый.lxds"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("info.xml", "<PackData>")          # тег не закрыт
            archive.writestr("Nest2D/content.xml", "<NestInfo/>")
            archive.writestr("Nest2D/Results/content.xml", "<NestResults/>")
        self.assertIn("Испорченный XML", self._message(path))

    def test_раскладок_нет(self):
        path = self.tmp / "3мм Пустой.lxds"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("info.xml", "<PackData/>")
            archive.writestr("Nest2D/content.xml", "<NestInfo/>")
            archive.writestr("Nest2D/Results/content.xml", "<NestResults/>")
        self.assertIn("на лист не разложены", self._message(path))

    def test_раскладка_без_габарита(self):
        path = self.tmp / "3мм Безразмерный.lxds"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("info.xml", "<PackData/>")
            archive.writestr("Nest2D/content.xml", "<NestInfo/>")
            archive.writestr("Nest2D/Results/content.xml",
                             '<NestResults><NestResult Index="1" Utilization="50"/>'
                             "</NestResults>")
        self.assertIn("нет габарита", self._message(path))

    def test_cli_не_падает_на_чужом_файле(self):
        path = self.tmp / "чужой.lxds"
        path.write_text("не архив", encoding="utf-8")
        err, stderr = io.StringIO(), sys.stderr
        sys.stderr = err
        try:
            code = lxds.main([str(path)])
        finally:
            sys.stderr = stderr
        self.assertEqual(code, 1)
        self.assertIn("Ошибка:", err.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
