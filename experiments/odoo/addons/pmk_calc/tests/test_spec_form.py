# -*- coding: utf-8 -*-
"""Форма расчёта, разбор UX, шаг 32: раскладка и собранная разметка.

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
    odoo -d pmk_calc_test -i pmk_deal --test-enable \\
         --test-tags /pmk_calc,/pmk_bridge,/pmk_deal --stop-after-init --http-port 8099

Разметка — собранная, как её получает браузер (get_views: все наследники
применены). Глазами это не заменяет — вид смотрит основной агент в браузере.
Здесь ловится то, что ломается молча: xpath, переставшее находить узел,
вторая залитая кнопка, вернувшиеся колонки.
"""
import html
from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, tagged

NB = " "


def plain(text):
    return (text or "").replace(NB, " ").replace("&nbsp;", " ")


@tagged("post_install", "-at_install")
class TestSpecLayoutStep32(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Свой лист, а не строка справочника по xmlid: тест не должен
        # зависеть от того, как названы записи CSV.
        cls.sheet6 = cls.env["pmk.metal.sheet"].create({
            "sheet_type": "Тестовый", "thickness_mm": 6.0,
            "gost": "ГОСТ 19903-2015", "mass_per_sqm": 47.1})
        cls.Spec = cls.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)

    def _spec(self, lines):
        return self.Spec.create({
            "product_ids": [Command.create({
                "name": "МК по КМ1", "qty": 1,
                "line_ids": [Command.create(vals) for vals in lines],
            })],
        })

    def test_size_one_column(self):
        spec = self._spec([
            {"calc_mode": "sheet", "detail_name": "Лестницы −6",
             "sheet_id": self.sheet6.id, "a_mm": 100.0, "b_mm": 100.0, "qty": 42},
            {"calc_mode": "sheet", "detail_name": "Косынка",
             "sheet_id": self.sheet6.id, "a_mm": 120.5, "b_mm": 210.0, "qty": 1},
            {"calc_mode": "linear", "detail_name": "Стойка", "length_mm": 3500.0},
        ])
        labels = {l.detail_name: l.detail_size_label for l in spec.product_ids.line_ids}
        self.assertEqual(labels["Лестницы −6"], "100×100")
        self.assertEqual(labels["Косынка"], "120,5×210")
        self.assertFalse(labels["Стойка"], "У проката размера «A×B» нет.")

    def test_use_signal_and_history(self):
        """Лист 6 мм ради 42 деталей 100×100 — 4,7 %: красным и словом."""
        spec = self._spec([
            {"calc_mode": "sheet", "detail_name": "Лестницы −6",
             "sheet_id": self.sheet6.id, "a_mm": 100.0, "b_mm": 100.0, "qty": 42},
        ])
        line = spec.sheet_line_ids
        self.assertEqual(line.layout_use_level, "none")
        self.assertFalse(line.layout_use_label, "До раскладки — без подписи.")

        spec.action_draft_layout()
        self.assertEqual(line.layout_state, "ok")
        self.assertEqual(line.layout_sheets, 1)
        self.assertEqual(plain(line.layout_use_label), "4,7 % · очень мало")
        self.assertEqual(line.layout_use_level, "bad")

        body = plain(spec.message_ids[:1].body)
        self.assertIn("Раскладка листов (черновик): купить 1 лист", body)
        # В ленте пробел перед «%» неразрывный и приходит сущностью &nbsp;.
        text = html.unescape(str(body)).replace("\xa0", " ")
        self.assertIn("использование 4,7 % · очень мало", text)
        self.assertNotIn("Предварительный расчёт металла", body)

    def test_layout_goes_stale_in_db(self):
        """Доводка шага 32: сменили размер, габарит или количество —
        раскладка гаснет В БАЗЕ, а не только на экране до сохранения.

        Поля раскладки readonly, и браузер их сброс на сервер не отправляет:
        после «Сохранить» рядом с новым размером стояли старые «В листе /
        Листов» и красное «очень мало».
        """
        spec = self._spec([
            {"calc_mode": "sheet", "detail_name": "Лестницы −6",
             "sheet_id": self.sheet6.id, "a_mm": 100.0, "b_mm": 100.0, "qty": 42},
        ])
        product = spec.product_ids
        line = spec.sheet_line_ids

        def assert_fresh(msg):
            self.assertEqual(line.layout_state, "ok", msg)
            self.assertEqual(line.layout_use_level, "bad", msg)

        def assert_stale(msg):
            self.assertEqual(line.layout_state, "none", msg)
            self.assertEqual(line.layout_sheets, 0, msg)
            self.assertEqual(line.layout_per_sheet, 0, msg)
            self.assertEqual(line.layout_use_level, "none", msg)
            self.assertFalse(line.layout_use_label, msg)

        spec.action_draft_layout()
        assert_fresh("Раскладка сама себя не гасит.")

        line.write({"a_mm": 100.0, "detail_name": "Лестницы −6, ред."})
        assert_fresh("Тот же размер и новое название — раскладка та же.")

        # Вкладка «Раскладка»: габарит листа.
        spec.write({"sheet_line_ids": [
            Command.update(line.id, {"layout_sheet_size": "1000x4000"})]})
        assert_stale("Сменили габарит листа.")

        # Окно изделия: размер детали — командой через документ, как браузер.
        spec.action_draft_layout()
        assert_fresh("Разложили заново.")
        spec.write({"product_ids": [Command.update(product.id, {
            "line_sheet_ids": [Command.update(line.id, {"a_mm": 1400.0, "b_mm": 900.0})]})]})
        assert_stale("Сменили размер детали.")

        spec.action_draft_layout()
        self.assertEqual(line.layout_state, "ok")
        line.qty = 43
        assert_stale("Сменили количество деталей.")

        spec.action_draft_layout()
        self.assertEqual(line.layout_state, "ok")
        product.write({"qty": 1})
        self.assertEqual(line.layout_state, "ok", "Количество изделий то же.")
        product.write({"qty": 3})
        assert_stale("Сменили количество изделий: заготовок стало втрое больше.")

    def test_layout_onchange_resets_on_screen(self):
        """Onchange остаётся — гасит раскладку на экране до сохранения."""
        draft = self.env["pmk.metal.spec.line"].new({
            "calc_mode": "sheet", "sheet_id": self.sheet6.id,
            "a_mm": 100.0, "b_mm": 100.0, "qty": 42,
            "layout_sheet_size": "1000x4000", "layout_state": "ok",
            "layout_per_sheet": 885, "layout_sheets": 1,
            "layout_scheme": "59 × 15", "layout_utilization_pct": 4.7,
        })
        draft._onchange_layout_stale()
        self.assertEqual(draft.layout_state, "none")
        self.assertEqual(draft.layout_sheets, 0)
        self.assertEqual(draft.layout_per_sheet, 0)
        self.assertFalse(draft.layout_scheme)
        self.assertEqual(draft.layout_use_level, "none")

    def test_nothing_to_lay_out(self):
        spec = self._spec([{"calc_mode": "linear", "detail_name": "Стойка",
                            "length_mm": 3500.0}])
        spec.action_draft_layout()
        self.assertIn("Раскладка листов (черновик): считать нечего",
                      plain(spec.message_ids[:1].body))

    # ─── Собранная разметка ─────────────────────────────────────────────
    def _form(self):
        views = self.env["pmk.metal.spec"].get_views([(False, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def test_form_class_and_header(self):
        arch = self._form()
        self.assertIn("pmk-spec-form", arch.get("class", "").split())
        header = arch.find("header")
        self.assertIsNotNone(header, "Шапку не сносим: на неё идёт xpath моста.")
        self.assertIsNone(header.find(".//button[@name='action_draft_layout']"),
                          "Раскладка переехала на свою вкладку.")

    def test_layout_page(self):
        arch = self._form()
        page = arch.xpath("//page[@name='layout']")[0]
        button = page.xpath(".//button[@name='action_draft_layout']")
        self.assertEqual(len(button), 1)
        self.assertEqual(button[0].get("string"), "Разложить листы (черновик)")
        self.assertIn("btn-secondary", button[0].get("class"),
                      "Контурная: залитая на экране одна — «КП (PDF)».")
        self.assertIn("sheet_line_ids", button[0].get("invisible"))

        columns = page.xpath("field[@name='sheet_line_ids']/list/field")
        visible = [c.get("name") for c in columns
                   if c.get("optional") != "hide" and c.get("column_invisible") not in ("1", "True")]
        self.assertEqual(visible, [
            "detail_name", "sheet_id", "detail_size_label", "qty",
            "layout_sheet_size", "layout_per_sheet", "layout_sheets", "layout_use_label"])
        by_name = {c.get("name"): c for c in columns}
        for name in ("product_id", "layout_scheme", "layout_state"):
            with self.subTest(hidden=name):
                self.assertEqual(by_name[name].get("optional"), "hide",
                                 "Скрыта обратимо — в меню колонок.")
        self.assertNotIn("a_mm", by_name)
        self.assertNotIn("b_mm", by_name)
        use = by_name["layout_use_label"]
        self.assertEqual(use.get("widget"), "badge")
        self.assertEqual(use.get("decoration-warning"), "layout_use_level == 'low'")
        self.assertEqual(use.get("decoration-danger"), "layout_use_level == 'bad'")
        self.assertIn("layout_use_level", by_name, "Уровень для цвета — служебной колонкой.")

    def test_head_blocks(self):
        arch = self._form()
        head = arch.xpath("//div[contains(concat(' ', @class, ' '), ' pmk-doc-head__fields ')]")[0]
        names = [d.get("name") for d in head if d.get("name")]
        ours = [n for n in names if n in ("pmk_f_partner", "pmk_f_contact", "pmk_f_date", "pmk_f_note")]
        self.assertEqual(ours, ["pmk_f_partner", "pmk_f_contact", "pmk_f_date", "pmk_f_note"])
        for name in ("pmk_f_partner", "pmk_f_contact", "pmk_f_note"):
            with self.subTest(block=name):
                block = head.find("div[@name='%s']" % name)
                self.assertIn("pmk-field--wide", block.get("class"))
        self.assertNotIn("pmk-field--wide", head.find("div[@name='pmk_f_date']").get("class"))
