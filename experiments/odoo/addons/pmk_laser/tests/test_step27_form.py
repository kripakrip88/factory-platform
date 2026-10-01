# -*- coding: utf-8 -*-
"""Задание лазеру — форма (разбор UX, шаг 27).

Гонять ТОЛЬКО на одноразовой базе (см. pmk_calc/tests/test_list_units.py).

Вид (плашки одной строкой, «Станок» той же ширины, рамки дробных полей)
смотрит основной агент глазами. Здесь — то, что ломается молча: вторая
залитая кнопка, вернувшиеся абзацы alert, длинные подписи, четыре знака
массы, файл стилей выпал из манифеста. И доводка: «файл разобран» — не
«есть листы» (заменённый после разбора файл возвращает залитую «Разобрать
файл»), плашка о длине реза не велит прикладывать уже приложенное.
"""
import ast
import base64
from types import SimpleNamespace
from unittest.mock import patch

from lxml import etree

from odoo.modules.module import get_manifest
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

SIGNALS = "not (technical_is_demo or parse_warning or balance_broken or plan_state == 'no_norm' or (plan_state == 'no_drawing' and parts_without_drawing) or (file and file_replaced))"
PARSE_FILLED = "not file or (sheet_ids and not file_replaced) or (file_replaced and measure_ids)"
PARSE_AGAIN = "not file or not sheet_ids or file_replaced"


@tagged("post_install", "-at_install")
class TestLaserJobFormStep27(TransactionCase):

    def _form(self):
        view = self.env.ref("pmk_laser.view_laser_job_form")
        views = self.env["pmk.laser.job"].get_views([(view.id, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def test_form_class(self):
        self.assertIn("pmk-doc-form", self._form().get("class", "").split())

    def test_one_filled_parse_button(self):
        """«Разобрать файл» залита, пока файл не разобран или заменён после
        разбора; разобран — контурная «Разобрать заново». Обе зовут тот же
        метод. Заменили файл у задания с замерами — кнопок разбора нет
        (сервер откажет), велит сигнал."""
        arch = self._form()
        header = arch.find("header")
        parse = header.findall("button[@name='action_parse_file']")
        self.assertEqual(len(parse), 2)
        by_string = {b.get("string"): b for b in parse}
        first, again = by_string["Разобрать файл"], by_string["Разобрать заново"]
        self.assertIn("btn-primary", first.get("class"))
        self.assertEqual(first.get("invisible"), PARSE_FILLED)
        self.assertIn("btn-secondary", again.get("class"))
        self.assertNotIn("btn-primary", again.get("class"))
        self.assertEqual(again.get("invisible"), PARSE_AGAIN)
        filled = [b for b in header.iter("button")
                  if {"btn-primary", "oe_highlight"} & set((b.get("class") or "").split())]
        self.assertEqual(filled, [first], "Залитая в шапке — одна.")
        # Поля из условий — в виде, иначе клиент их не знает.
        for name in ("file", "sheet_ids", "file_replaced", "measure_ids"):
            with self.subTest(field=name):
                self.assertTrue(arch.xpath("//field[@name='%s']" % name))

    def test_parse_buttons_by_state(self):
        """Условия видимости на всех состояниях задания: ровно одна кнопка
        разбора (или ни одной), залитая — только когда разбор и есть
        следующий шаг."""
        # (file, sheet_ids, file_replaced, measure_ids) → (залитая, контурная)
        cases = [
            ((False, [], False, []), (False, False)),       # файла нет
            ((True, [], False, []), (True, False)),         # приложен, не разобран
            ((True, [1], False, []), (False, True)),        # разобран
            ((True, [1], False, [7]), (False, True)),       # разобран, есть замеры
            ((True, [1], True, []), (True, False)),         # заменён после разбора
            ((True, [1], True, [7]), (False, False)),       # заменён после замеров
            ((False, [1], True, []), (False, False)),       # файл убрали
        ]
        for (file, sheets, replaced, measures), (filled, again) in cases:
            env = {"file": file, "sheet_ids": sheets, "file_replaced": replaced,
                   "measure_ids": measures}
            with self.subTest(state=env):
                self.assertEqual(not safe_eval(PARSE_FILLED, env), filled)
                self.assertEqual(not safe_eval(PARSE_AGAIN, env), again)

    def test_signals_one_row(self):
        arch = self._form()
        sheet = arch.find("sheet")
        self.assertFalse(sheet.xpath("./div[contains(concat(' ', @class, ' '), ' alert ')]"),
                         "Абзацы-плашки над группами заменены строкой сигналов.")
        rows = sheet.xpath("./div[@class='pmk-job-signals']")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("invisible"), SIGNALS)
        chips = rows[0].findall("span")
        self.assertEqual(len(chips), 7)
        bad = [c for c in chips if "pmk-job-signal--bad" in c.get("class")]
        self.assertEqual(len(bad), 1)
        self.assertIn("Баланс не сходится", "".join(bad[0].itertext()), "Цвет повторён словом.")
        no_drawing = [c for c in chips if c.find("field[@name='parts_without_drawing']") is not None][0]
        self.assertEqual(no_drawing.get("invisible"), "plan_state != 'no_drawing' or not parts_without_drawing",
                         "Без деталей «у 0 деталей нет чертежа» не пишем.")
        self.assertIn("pmk-job-signal--warn", no_drawing.get("class"))
        # Счётчик — детали без ДЛИНЫ РЕЗА, а не без файла: приложенный, но не
        # разобранный чертёж тоже в счёте. Плашка не велит только
        # «приложить» то, что уже приложено (доводка шага 27).
        text = "".join(no_drawing.itertext())
        self.assertTrue(text.startswith("Длина реза не разобрана у"), text)
        self.assertIn("приложите и разберите", text)
        self.assertNotIn("Деталей без чертежа", text)
        # Файл заменён после разбора — две плашки, по замерам взаимоисключающие.
        replaced = {c.get("invisible"): "".join(c.itertext()) for c in chips
                    if "file_replaced" in (c.get("invisible") or "")}
        self.assertEqual(set(replaced), {
            "not file or not file_replaced or measure_ids",
            "not file or not file_replaced or not measure_ids",
        })
        self.assertIn("разберите файл", replaced["not file or not file_replaced or measure_ids"])
        self.assertIn("к новому заданию", replaced["not file or not file_replaced or not measure_ids"])
        for chip in chips:
            with self.subTest(chip="".join(chip.itertext()).strip()[:30]):
                self.assertTrue(chip.get("title") or chip.find("field[@name='parse_warning']") is not None,
                                "Объяснение — в подсказке при наведении.")
                self.assertLess(len("".join(t for t in chip.itertext() if t.strip())), 120)
        thickness = rows[0].find(".//field[@name='thickness_mm']")
        self.assertTrue(ast.literal_eval(thickness.get("options") or "{}").get("hide_trailing_zeros"))

    def test_short_labels_and_digits(self):
        arch = self._form()
        labels = {"spec_id": "Расчёт", "sheet_id": "Лист", "file": "Файл",
                  "contour_gap_pct": "Расхождение, %"}
        for name, string in labels.items():
            with self.subTest(field=name):
                node = arch.xpath("//group//field[@name='%s']" % name)
                self.assertEqual(len(node), 1)
                self.assertEqual(node[0].get("string"), string)
        self.assertTrue(arch.xpath("//group//field[@name='file']")[0].get("help"))
        mass = arch.xpath("//group//field[@name='mass_per_sqm']")[0]
        self.assertEqual(mass.get("digits"), "[12,2]", "«23,55», а не «23,5500».")
        thickness = arch.xpath("//group//field[@name='thickness_mm']")[0]
        self.assertTrue(ast.literal_eval(thickness.get("options") or "{}").get("hide_trailing_zeros"))

    def test_styles_in_manifest(self):
        self.assertIn("pmk_laser/static/src/scss/laser_job.scss",
                      get_manifest("pmk_laser")["assets"]["web.assets_backend"])


FILE_A = base64.b64encode(b"PK lxds A")
FILE_B = base64.b64encode(b"PK lxds B")


@tagged("post_install", "-at_install")
class TestLaserJobFileReplaced(TransactionCase):
    """Файл заменён после разбора (доводка шага 27).

    Флаг file_replaced ставит write — новый файл у задания с листами; тот же
    файл заново (контрольная сумма та же) — не замена; у неразобранного
    задания — не замена; разбор снимает. Настоящий .lxds здесь не разбираем:
    листы кладём руками, а разбор подменяем готовой раскладкой — проверяется
    то, что action_parse_file пишет вместе с листами.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.machine = cls.env["pmk.laser.machine"].create({"name": "Станок-проба"})

    def _job(self, sheets=1):
        job = self.env["pmk.laser.job"].create({
            "machine_id": self.machine.id,
            "file": FILE_A,
            "file_name": "3мм проба Раскрой.lxds",
        })
        for number in range(1, sheets + 1):
            self.env["pmk.laser.job.sheet"].create({
                "job_id": job.id, "number": number,
                "width_mm": 1500, "length_mm": 6000, "utilization_pct": 80,
            })
        return job

    def _layout(self):
        nest = SimpleNamespace(index=1, plate_amount=2, width_mm=1500.0,
                               height_mm=3000.0, utilization_pct=75.0)
        return SimpleNamespace(
            thickness_mm=3.0, technical_declared={}, app_name="CypCut", app_version="",
            operator="", saved_at_raw="", saved_at=None, contours=0, demo_modes=False,
            warnings=[], parts=[], nests=[nest], sheet_count=2, parts_declared=0,
            thickness_source="")

    def test_new_file_on_parsed_job(self):
        job = self._job()
        self.assertFalse(job.file_replaced)
        job.write({"file": FILE_B})
        self.assertTrue(job.file_replaced, "Листы от прежнего файла — флаг стоит.")

    def test_same_file_is_not_replacement(self):
        job = self._job()
        job.write({"file": FILE_A})
        self.assertFalse(job.file_replaced)

    def test_unparsed_job_not_flagged(self):
        job = self._job(sheets=0)
        job.write({"file": FILE_B})
        self.assertFalse(job.file_replaced, "Листов нет — менять нечего, залитая и так видна.")

    def test_removed_then_new_file(self):
        job = self._job()
        job.write({"file": False})
        self.assertFalse(job.file_replaced, "Файл убрали — не замена.")
        job.write({"file": FILE_B})
        self.assertTrue(job.file_replaced)

    def test_other_fields_keep_flag(self):
        job = self._job()
        job.write({"file": FILE_B})
        job.write({"note": "Перевыгрузили раскладку"})
        self.assertTrue(job.file_replaced)

    def test_parse_clears_flag(self):
        job = self._job()
        job.write({"file": FILE_B})
        self.assertTrue(job.file_replaced)
        Job = type(job)
        layout = self._layout()
        with patch.object(Job, "_read_layout", lambda record: layout), \
                patch.object(Job, "_sheet_from_reference",
                             lambda record, thickness, sheet_type: record.env["pmk.metal.sheet"]):
            job.action_parse_file()
        self.assertFalse(job.file_replaced, "Разобрали новый файл — листы от него.")
        self.assertEqual(len(job.sheet_ids), 2)
        # Повторно тот же файл — снова не замена.
        job.write({"file": FILE_B})
        self.assertFalse(job.file_replaced)

    def test_explicit_flag_respected(self):
        job = self._job()
        job.write({"file": FILE_B, "file_replaced": False})
        self.assertFalse(job.file_replaced)
