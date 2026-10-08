# -*- coding: utf-8 -*-
"""Расчёт металлопроката — разбор UX, шаг 56 (08.10.2026).

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
    odoo -d pmk56_test -i pmk_deal --test-enable \\
         --test-tags /pmk_calc,/pmk_bridge --stop-after-init --http-port 8099

Три доработки по приёмке Антона 07.10:
  1. «Количество, шт» правится в строке «Состава» (цена — мост, его тесты
     test_step56_inline_price.py). Сама правка в строке — JS
     (product_lines_field.js), её смотрит основной агент глазами. Здесь —
     что запись строки пересчитывает всё так же, как окно изделия: через
     onchange документа (Form) и командой, как присылает браузер (write);
  2. поиск «уг 50 5» через ORM (name_search / web_name_search); правила на
     всём справочнике — test_size_search.py (голым питоном);
  3. сигнал «Раскладка устарела»: отпечаток, плашка, список, миграция.
"""
import importlib.util

from lxml import etree

from odoo import Command
from odoo.tests import Form, TransactionCase, tagged
from odoo.tools.misc import file_path


def _read(path):
    with open(file_path(path), encoding="utf-8") as f:
        return f.read()


def _migration():
    """migrations/19.0.1.0.6/post-migrate.py — точки в имени папки не дают
    импортировать его обычным образом."""
    path = file_path("pmk_calc/migrations/19.0.1.0.6/post-migrate.py")
    spec = importlib.util.spec_from_file_location("pmk_calc_step56_migrate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("post_install", "-at_install")
class TestStep56Spec(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ref = cls.env.ref
        cls.angle = ref("pmk_calc.profile_уголок_равнополочный_50x50x5")
        cls.angle4 = ref("pmk_calc.profile_уголок_равнополочный_50x50x4")
        cls.sheet4 = ref("pmk_calc.sheet_гладкий_4")
        cls.sheet6 = ref("pmk_calc.sheet_гладкий_6")
        cls.Profile = cls.env["pmk.metal.profile"]
        cls.Sheet = cls.env["pmk.metal.sheet"]
        cls.Spec = cls.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)

    def _spec(self, products):
        return self.Spec.create({"product_ids": [
            Command.create({
                "name": name, "qty": qty,
                "line_ids": [Command.create(vals) for vals in lines],
            }) for name, qty, lines in products
        ]})

    def _sheet_line(self, **vals):
        line = {"calc_mode": "sheet", "detail_name": "Пластина", "sheet_id": self.sheet4.id,
                "a_mm": 1000.0, "b_mm": 500.0, "qty": 2}
        line.update(vals)
        return line

    # ─── 2. Поиск «уг 50 5» ──────────────────────────────────────────────
    def test_search_numbers_by_space(self):
        """Антон 07.10: «уголок 50х50х5 можно было найти запросом „уг 50 5“»."""
        found = [row[0] for row in self.Profile.name_search("уг 50 5", limit=100)]
        self.assertEqual(found[:1], [self.angle.id])
        self.assertNotIn(self.angle4.id, found, "«5» не находит «50»: 50x50x4 не в выдаче.")
        rows = self.Profile.web_name_search("уг 50 5", {"display_name": {}}, limit=8)
        self.assertEqual(rows[0]["id"], self.angle.id)
        self.assertEqual(rows[0]["display_name"], "Уголок равнополочный 50x50x5")
        cases = {
            "уг 50 50 5": "Уголок равнополочный 50x50x5",
            "УГ 50Х50Х5": "Уголок равнополочный 50x50x5",
            "уг 50*5": "Уголок равнополочный 50x50x5",
            "Уголок 50×50×5": "Уголок равнополочный 50x50x5",
            "уг 50 4": "Уголок равнополочный 50x50x4",
            "тр 40 20 2": "Труба профильная прямоугольная 40x20x2",
            "швел 10": "Швеллер 10П",
            "шв 10": "Швеллер 10П",
            "арм 12": "Арматура d12",
            # Толщина первой (находка проверки 08.10: был пустой ответ).
            "уг 5 50": "Уголок равнополочный 50x50x5",
            "уг 5 50 50": "Уголок равнополочный 50x50x5",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.Profile.name_search(text, limit=8)[0][1], want)

    def test_search_sheet_and_fallback(self):
        sheets = self.Sheet.browse([row[0] for row in self.Sheet.name_search("лист 4", limit=100)])
        self.assertTrue(sheets)
        self.assertEqual(set(sheets.mapped("thickness_mm")), {4.0},
                         "«лист 4» — только 4 мм, без 4,5 и 40.")
        # Правила не разобрали — штатный поиск подстроки, как раньше.
        fallback = [row[0] for row in self.Profile.name_search("x50x", limit=200)]
        self.assertIn(self.angle.id, fallback)
        # На полпути ответ не пустой: поле Odoo запомнило бы пустой.
        for partial in ("тр 40 20 1", "уг 50 50", "уг 50 5 ст"):
            with self.subTest(text=partial):
                self.assertTrue(self.Profile.web_name_search(partial, {"display_name": {}}, limit=8))

    # ─── 1. Количество изделия в строке «Состава» ────────────────────────
    def test_qty_in_row_by_command(self):
        """Как присылает браузер правку строки: Command.update изделия."""
        spec = self._spec([("Рама", 1, [self._sheet_line()]), ("Без состава", 1, [])])
        frame, empty = spec.product_ids.sorted("id")
        self.assertAlmostEqual(frame.weight_one, 31.4, places=3)  # 4 мм · 0,5 м² · 2
        spec.write({"product_ids": [Command.update(frame.id, {"qty": 3}),
                                    Command.update(empty.id, {"qty": 5})]})
        self.assertEqual(frame.qty, 3)
        self.assertAlmostEqual(frame.weight_total, 94.2, places=3)
        self.assertAlmostEqual(spec.total_weight, 94.2, places=3)
        self.assertAlmostEqual(spec.total_weight_t, 0.0942, places=4)
        self.assertEqual(empty.qty, 5, "Изделие без состава — количество сохранено.")
        self.assertEqual(empty.weight_total, 0.0)

    def test_qty_in_row_by_onchange(self):
        """Тот же путь, что правка в строке до сохранения: onchange расчёта."""
        spec = self._spec([("Рама", 1, [self._sheet_line()])])
        form = Form(spec)
        with form.product_ids.edit(0) as row:
            row.qty = 4
        self.assertAlmostEqual(form.total_weight, 125.6, places=3)
        form.save()
        self.assertEqual(spec.product_ids.qty, 4)
        self.assertAlmostEqual(spec.total_weight, 125.6, places=3)

    def test_product_list_stays_window_based(self):
        """Список изделий целиком не editable: «Добавить изделие» — окно,
        название — окно. Правка в строке — только у цены и количества (JS)."""
        arch = etree.fromstring(self.env["pmk.metal.spec"].get_views(
            [(False, "form")])["views"]["form"]["arch"])
        product_list = arch.xpath("//field[@name='product_ids']/list")[0]
        self.assertIsNone(product_list.get("editable"))
        qty = product_list.find("field[@name='qty']")
        self.assertNotIn(qty.get("readonly"), ("1", "True"))
        js = _read("pmk_calc/static/src/js/product_lines_field.js")
        self.assertIn('return ["qty"];', js)
        self.assertIn("pmkIsInline(column)", js)
        # Esc — своя отмена: ядро у существующей строки x2many не откатывает
        # (находка проверки 08.10). Поведение смотрит основной агент глазами.
        self.assertIn('hotkey === "escape"', js)
        self.assertIn("pmkCancelInline(record)", js)
        self.assertIn("pmkRememberBefore()", js)
        css = _read("pmk_calc/static/src/scss/spec_form.scss")
        self.assertIn("cursor: text !important", css, "Утилита ядра cursor-pointer — с !important.")
        dark = _read("pmk_theme/static/src/scss/dark.scss")
        self.assertIn(".o_selected_row > td:focus-within", dark,
                      "Тёмная тема: ячейка с полем ввода не белая.")

    # ─── 3. Сигнал «Раскладка устарела» ──────────────────────────────────
    def test_stale_signal_lifecycle(self):
        spec = self._spec([("Рама", 1, [self._sheet_line()])])
        product = spec.product_ids
        line = product.line_sheet_ids
        self.assertFalse(spec.layout_stale, "Не раскладывали — без плашки.")

        spec.action_draft_layout()
        self.assertTrue(spec.layout_fingerprint)
        self.assertFalse(spec.layout_stale, "Разложили — плашки нет.")
        self.assertFalse(spec.layout_stale_label)

        line.write({"detail_name": "Пластина, ред."})
        self.assertFalse(spec.layout_stale, "Название детали раскладку не меняет.")

        checks = [
            ("размер", lambda: line.write({"a_mm": 1200.0})),
            ("количество деталей", lambda: line.write({"qty": 3})),
            ("лист", lambda: line.write({"sheet_id": self.sheet6.id})),
            ("габарит", lambda: spec.write({"sheet_line_ids": [
                Command.update(line.id, {"layout_sheet_size": "1500x3000"})]})),
            ("количество изделий", lambda: spec.write({"product_ids": [
                Command.update(product.id, {"qty": product.qty + 2})]})),
            ("новая листовая деталь", lambda: product.write({"line_ids": [
                Command.create(self._sheet_line(detail_name="Косынка", a_mm=200.0))]})),
        ]
        for what, change in checks:
            with self.subTest(change=what):
                spec.action_draft_layout()
                self.assertFalse(spec.layout_stale)
                change()
                self.assertTrue(spec.layout_stale, "Сменили %s — раскладка устарела." % what)
                self.assertEqual(spec.layout_stale_label, "устарела")
                self.assertIn("Разложить листы", spec.layout_stale_text)
        spec.action_draft_layout()
        self.assertFalse(spec.layout_stale, "Разложили заново — плашка исчезла.")

        # Поменяли и вернули обратно: в базе раскладка уже погашена.
        line.write({"a_mm": 999.0})
        line.write({"a_mm": 1200.0})
        self.assertTrue(spec.layout_stale)
        spec.action_draft_layout()

        # Удалили деталь — числа оставшихся верны, сигнала нет.
        product.line_sheet_ids.filtered(lambda l: l.detail_name == "Косынка").unlink()
        self.assertFalse(spec.layout_stale)

    def test_stale_on_screen_before_save(self):
        """Onchange: плашка загорается до «Сохранить» — новая деталь, размер,
        количество изделий."""
        spec = self._spec([("Рама", 1, [self._sheet_line()])])
        spec.action_draft_layout()
        form = Form(spec)
        self.assertFalse(form.layout_stale)
        with form.product_ids.edit(0) as row:
            row.qty = 2
        self.assertTrue(form.layout_stale, "Количество изделий в строке «Состава».")

        form = Form(spec)
        with form.product_ids.edit(0) as row:
            with row.line_sheet_ids.edit(0) as line:
                line.a_mm = 700.0
        self.assertTrue(form.layout_stale, "Размер детали в окне изделия.")

        form = Form(spec)
        with form.product_ids.edit(0) as row:
            with row.line_sheet_ids.new() as line:
                line.detail_name = "Косынка"
                line.sheet_id = self.sheet4
                line.a_mm = 200.0
                line.b_mm = 200.0
        self.assertTrue(form.layout_stale, "Новая листовая деталь.")

    def test_stale_when_key_matches_other_detail(self):
        """Находка проверки 08.10: деталь «Опоры-2» после правки количества
        совпала ключом с деталью «Опоры» из отпечатка. Сравнение — с
        повторами (Counter), плашка горит и до «Сохранить»."""
        spec = self._spec([
            ("Опора", 1, [self._sheet_line(a_mm=200.0, b_mm=200.0, qty=8)]),
            ("Опора-2", 1, [self._sheet_line(a_mm=200.0, b_mm=200.0, qty=4)]),
        ])
        spec.action_draft_layout()
        self.assertEqual(len(spec.layout_fingerprint.split()), 2)
        self.assertFalse(spec.layout_stale)
        form = Form(spec)
        with form.product_ids.edit(1) as row:
            self.assertEqual(row.name, "Опора-2")
            row.qty = 2
        self.assertTrue(form.layout_stale, "Ключ «Опоры-2» = ключ «Опоры», но деталей стало две такие.")
        form.save()
        self.assertTrue(spec.layout_stale)
        spec.action_draft_layout()
        keys = spec.layout_fingerprint.split()
        self.assertEqual(len(keys), 2)
        self.assertEqual(len(set(keys)), 1, "Отпечаток хранит повторы.")
        self.assertFalse(spec.layout_stale)

    def test_no_sheet_no_signal(self):
        spec = self._spec([("Стойки", 1, [{"calc_mode": "linear", "detail_name": "Стойка",
                                          "profile_id": self.angle.id, "length_mm": 3000.0}])])
        spec.action_draft_layout()
        self.assertFalse(spec.layout_fingerprint)
        self.assertFalse(spec.layout_stale, "Без листовых деталей — без плашки.")
        spec.write({"product_ids": [Command.update(spec.product_ids.id, {"qty": 7})]})
        self.assertFalse(spec.layout_stale)

    def test_copy_has_no_signal(self):
        """Копия — новый расчёт: раскладка в неё не переносится (R4), плашки нет."""
        spec = self._spec([("Рама", 1, [self._sheet_line()])])
        spec.action_draft_layout()
        copy = spec.copy()
        self.assertFalse(copy.layout_fingerprint)
        self.assertFalse(copy.layout_stale)

    def test_legacy_fingerprint(self):
        from odoo.addons.pmk_calc.models.spec_layout import LEGACY_FINGERPRINT
        spec = self._spec([("Рама", 1, [self._sheet_line()])])
        spec.action_draft_layout()
        spec.layout_fingerprint = LEGACY_FINGERPRINT
        self.assertTrue(spec.layout_stale)
        self.assertIn("до исправления 30.09", spec.layout_stale_text)
        self.assertIn("могла устареть", spec.layout_stale_text)
        self.assertEqual(spec.layout_stale_label, "могла устареть",
                         "Старый расчёт: детали могли не меняться — не «устарела».")
        spec.action_draft_layout()
        self.assertFalse(spec.layout_stale)
        self.assertNotEqual(spec.layout_fingerprint, LEGACY_FINGERPRINT)

    def test_migration_by_layout_date(self):
        """Разложен после 30.09 — актуален; до исправления или без записи —
        «могла устареть»; не раскладывался — без отпечатка."""
        from odoo.addons.pmk_calc.models.spec_layout import LEGACY_FINGERPRINT
        fresh = self._spec([("Рама", 1, [self._sheet_line()])])
        old = self._spec([("Рама", 1, [self._sheet_line()])])
        silent = self._spec([("Рама", 1, [self._sheet_line()])])
        never = self._spec([("Рама", 1, [self._sheet_line()])])
        for spec in (fresh, old, silent):
            spec.action_draft_layout()
        self.env.flush_all()
        cr = self.env.cr
        # Даты — явно: часы машины, на которой гоняют тесты, не опора.
        cr.execute("UPDATE mail_message SET date = '2026-10-05 13:23:50' "
                   "WHERE model = 'pmk.metal.spec' AND res_id = %s", [fresh.id])
        cr.execute("UPDATE mail_message SET date = '2026-09-25 03:00:00' "
                   "WHERE model = 'pmk.metal.spec' AND res_id = %s", [old.id])
        # Раскладка старше записей о ней (до 27.09) — записи в истории нет.
        cr.execute("UPDATE mail_message SET body = '<p>Запись не о раскладке</p>' "
                   "WHERE model = 'pmk.metal.spec' AND res_id = %s", [silent.id])
        specs = fresh | old | silent | never
        cr.execute("UPDATE pmk_metal_spec SET layout_fingerprint = NULL WHERE id IN %s",
                   [tuple(specs.ids)])
        self.env.invalidate_all()

        _migration().migrate(cr, "19.0.1.0.5")
        self.env.invalidate_all()
        self.assertTrue(fresh.layout_fingerprint)
        self.assertNotEqual(fresh.layout_fingerprint, LEGACY_FINGERPRINT)
        self.assertFalse(fresh.layout_stale)
        self.assertEqual(old.layout_fingerprint, LEGACY_FINGERPRINT)
        self.assertTrue(old.layout_stale)
        self.assertEqual(silent.layout_fingerprint, LEGACY_FINGERPRINT)
        self.assertFalse(never.layout_fingerprint)
        self.assertFalse(never.layout_stale)

        before = {spec.id: spec.layout_fingerprint for spec in specs}
        _migration().migrate(cr, "19.0.1.0.5")
        self.env.invalidate_all()
        self.assertEqual({spec.id: spec.layout_fingerprint for spec in specs}, before,
                         "Повторный запуск ничего не меняет.")

    def test_stale_markup(self):
        arch = etree.fromstring(self.env["pmk.metal.spec"].get_views(
            [(False, "form")])["views"]["form"]["arch"])
        alert = arch.xpath("//div[@name='pmk_layout_stale']")[0]
        self.assertIn("pmk-price-alert", alert.get("class"), "Бледно-жёлтая, как «Нет цены».")
        self.assertEqual(alert.get("invisible"), "not layout_stale")
        self.assertIsNotNone(alert.find("field[@name='layout_stale_text']"))
        button = alert.find("button[@name='action_draft_layout']")
        self.assertIn("btn-secondary", button.get("class"), "Залитая на экране одна — «КП (PDF)».")
        following = alert.getnext()
        while following is not None and "pmk-doc-head" not in (following.get("class") or ""):
            following = following.getnext()
        self.assertIsNotNone(following, "Плашка — над шапкой документа.")
        page = arch.xpath("//page[@name='layout']")[0]
        self.assertEqual(len(page.xpath(".//button[@name='action_draft_layout']")), 1)
        tab_alert = page.xpath(".//span[@invisible='not layout_stale']")
        self.assertTrue(tab_alert)
        self.assertIsNotNone(tab_alert[0].find("field[@name='layout_stale_text']"),
                             "Текст на вкладке — то же поле, что в плашке (одно понятие — одно слово).")

        lst = etree.fromstring(self.env["pmk.metal.spec"].get_views(
            [(False, "list")])["views"]["list"]["arch"])
        label = lst.xpath("//field[@name='layout_stale_label']")[0]
        self.assertEqual(label.get("optional"), "hide", "Колонка в меню колонок, скрыта.")
        self.assertEqual(label.get("widget"), "badge")
        self.assertEqual(label.get("decoration-warning"), "layout_stale")
