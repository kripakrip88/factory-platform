# -*- coding: utf-8 -*-
"""Окно изделия расчёта — разбор UX, шаг 34 (02.10.2026).

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
    odoo -d pmk34_test -i pmk_deal --test-enable \\
         --test-tags /pmk_calc,/pmk_bridge --stop-after-init --http-port 8099

Правила поиска на всём справочнике — test_size_search.py (голым питоном).
Здесь — то, что идёт через ORM и разметку: name_search справочников (вид
строки контекстом, отбор поля, точное сравнение, запасной поиск), вид из
типоразмера, вид новой строки, собранная форма окна, ассеты. Глазами — окно
во весь экран, заголовок «Изделие», шапку в два ряда в обеих темах, редактор
состава под строкой изделия — смотрит основной агент.

Позиции справочника — из data/*.csv модуля (те же, что на стенде).
"""
import ast

from lxml import etree

from odoo import Command
from odoo.modules.module import get_manifest
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_path
from odoo.tools.safe_eval import safe_eval


def _read(path):
    with open(file_path(path), encoding="utf-8") as f:
        return f.read()


def _id(value):
    """Значение ссылки из ответа onchange: число или {id, display_name}."""
    if isinstance(value, dict):
        return value.get("id")
    return value


@tagged("post_install", "-at_install")
class TestProductWindowStep34(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ref = cls.env.ref
        cls.angle = ref("pmk_calc.profile_уголок_равнополочный_50x50x5")
        cls.tube = ref("pmk_calc.profile_труба_профильная_квадратная_50x50x5")
        cls.beam = ref("pmk_calc.profile_двутавр_20ш1")
        cls.Profile = cls.env["pmk.metal.profile"]
        cls.Sheet = cls.env["pmk.metal.sheet"]
        cls.Spec = cls.env["pmk.metal.spec"].with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True)

    # ─── Поиск типоразмера (name_search справочника) ─────────────────────
    def _first(self, text, **context):
        return self.Profile.with_context(**context).name_search(text, limit=8)[0][0]

    def test_search_abbreviations(self):
        """Примеры документа разбора и ловушка П-03."""
        self.assertEqual(self._first("уг 50х5"), self.angle.id)
        self.assertEqual(self._first("двут 20ш"), self.beam.id)
        self.assertEqual(self._first("тр 60х3"),
                         self.env.ref("pmk_calc.profile_труба_профильная_квадратная_60x60x3").id)
        found = self.Profile.name_search("50х50х5", limit=8)
        self.assertEqual([row[0] for row in found[:2]], [self.angle.id, self.tube.id],
                         "П-03: «50х50х5» — уголок, профтруба вторая.")
        self.assertEqual(found[0][1], "Уголок равнополочный 50x50x5")

    def test_search_dots_and_marks(self):
        """Доводка шага 34: точка сокращения, «э/с», ГОСТ и марка — через
        name_search; недописанное «уг.» — не пустой ответ (поле Odoo
        запомнило бы его и дальше на сервер не ходило)."""
        self.assertEqual(self._first("уг. 50х5"), self.angle.id)
        self.assertEqual(self._first("Уг.50х5"), self.angle.id)
        self.assertEqual(self._first("уг 50х5 ГОСТ 8509-93 ст3сп"), self.angle.id)
        self.assertEqual(self._first("двут. 20ш1"), self.beam.id)
        self.assertEqual(self._first("тр э/с 57х3,5"),
                         self.env.ref("pmk_calc.profile_труба_круглая_57x3_5").id)
        for partial in ("уг.", "уг 50 х", "уг 50х5 гос", "уг 50х5 ст"):
            with self.subTest(text=partial):
                self.assertTrue(self.Profile.web_name_search(partial, {"display_name": {}}, limit=8))
        self.assertEqual(self.Sheet.name_search("лист г.к. 10", limit=8)[0][0],
                         self.env.ref("pmk_calc.sheet_гладкий_10").id)
        self.assertEqual(self.Sheet.name_search("оц. 0,5", limit=8)[0][0],
                         self.env.ref("pmk_calc.sheet_оцинк_0_5").id)

    def test_search_row_type_first(self):
        """Вид строки — контекстом pmk_prefer_type_id: его позиции первыми,
        чужие не прячутся."""
        self.assertEqual(self._first("50х50х5", pmk_prefer_type_id=self.tube.type_id.id),
                         self.tube.id)
        self.assertEqual(self._first("уг 50х5", pmk_prefer_type_id=self.beam.type_id.id),
                         self.angle.id, "Сокращение главнее вида строки.")
        found = self.Profile.with_context(
            pmk_prefer_type_id=self.beam.type_id.id).name_search("", limit=5)
        self.assertEqual(len(found), 5)
        self.assertEqual(self.Profile.browse([row[0] for row in found]).type_id, self.beam.type_id,
                         "Пустое поле в строке двутавров — двутавры.")

    def test_search_contract(self):
        """Отбор поля, предел, точное сравнение, запасной поиск, web_name_search."""
        found = self.Profile.name_search(
            "50х50х5", domain=[("type_id", "=", self.tube.type_id.id)], limit=8)
        self.assertEqual([row[0] for row in found], [self.tube.id], "Отбор поля соблюдается.")
        self.assertEqual(len(self.Profile.name_search("уг", limit=8)), 8)
        exact = self.Profile.name_search("Уголок равнополочный 50x50x5", operator="=")
        self.assertEqual([row[0] for row in exact], [self.angle.id], "«=» — штатное сравнение.")
        # «x50x» правила не разбирают — справочник ищет подстроку, как раньше.
        fallback = [row[0] for row in self.Profile.name_search("x50x", limit=200)]
        self.assertIn(self.angle.id, fallback)
        # Выпадающий список поля зовёт web_name_search — порядок тот же.
        rows = self.Profile.web_name_search("уг 50х5", {"display_name": {}}, limit=8)
        self.assertEqual(rows[0]["id"], self.angle.id)
        self.assertEqual(rows[0]["display_name"], "Уголок равнополочный 50x50x5")

    def test_search_sheets(self):
        sheet = self.Sheet.name_search("оц 0,5", limit=8)[0]
        self.assertEqual(sheet[0], self.env.ref("pmk_calc.sheet_оцинк_0_5").id)
        self.assertEqual(self.Sheet.name_search("лист 4", limit=8)[0][0],
                         self.env.ref("pmk_calc.sheet_гладкий_4").id)
        # Доборка гнётся только из оцинковки: отбор поля работает и здесь.
        galv = self.Sheet.name_search("0,4", domain=[("sheet_type", "=", "Оцинкованный")], limit=20)
        self.assertTrue(galv)
        self.assertEqual(set(self.Sheet.browse([row[0] for row in galv]).mapped("sheet_type")),
                         {"Оцинкованный"})

    # ─── Вид из типоразмера ──────────────────────────────────────────────
    def test_type_from_profile(self):
        Line = self.env["pmk.metal.spec.line"]
        self.assertFalse(Line._fields["profile_id"].domain,
                         "Отбора по виду нет: «уг 50х5» после двутавров находится.")
        spec = self.Spec.create({"product_ids": [Command.create({
            "name": "Рама", "qty": 1,
            "line_ids": [
                Command.create({"calc_mode": "linear", "detail_name": "Стойка",
                                "profile_id": self.angle.id, "length_mm": 3000.0}),
                Command.create({"calc_mode": "linear", "detail_name": "Без размера",
                                "type_id": self.beam.type_id.id}),
            ],
        })]})
        stand, bare = spec.product_ids.line_ids.sorted("id")
        self.assertEqual(stand.type_id, self.angle.type_id, "Вид — из типоразмера.")
        self.assertEqual(bare.type_id, self.beam.type_id, "Без типоразмера вид остаётся.")
        stand.profile_id = self.beam
        self.assertEqual(stand.type_id, self.beam.type_id, "Сменили типоразмер — сменился вид.")
        bare.profile_id = self.tube
        self.assertEqual(bare.type_id, self.tube.type_id)
        copy = spec.copy()
        self.assertEqual([line.type_id for line in copy.product_ids.line_ids.sorted("id")],
                         [line.type_id for line in spec.product_ids.line_ids.sorted("id")],
                         "Копия расчёта — с теми же видами.")

    def test_type_in_window_onchange(self):
        """Как браузер: новая строка берёт вид предыдущей (default_type_id),
        выбранный типоразмер ставит свой вид, вид руками чистит чужой
        типоразмер."""
        Line = self.env["pmk.metal.spec.line"]
        fields_spec = {"calc_mode": {}, "type_id": {}, "profile_id": {},
                       "length_mm": {}, "qty": {}}
        beam_type = self.beam.type_id.id
        new = Line.with_context(default_calc_mode="linear",
                                default_type_id=beam_type).onchange({}, [], fields_spec)
        self.assertEqual(_id(new["value"]["type_id"]), beam_type)

        row = {"calc_mode": "linear", "type_id": beam_type, "profile_id": self.angle.id,
               "length_mm": 0.0, "qty": 1}
        picked = Line.onchange(dict(row), ["profile_id"], fields_spec)
        self.assertEqual(_id(picked["value"]["type_id"]), self.angle.type_id.id,
                         "«уг 50х5» в строке двутавров — вид «Уголок».")

        changed = Line.onchange(dict(row), ["type_id"], fields_spec)
        self.assertFalse(_id(changed["value"].get("profile_id")),
                         "Вид сменили руками — типоразмер другого вида очищен.")
        self.assertNotIn("type_id", changed["value"], "Вид — выбранный руками.")

    def test_next_type_for_new_line(self):
        spec = self.Spec.create({"product_ids": [Command.create({
            "name": "Рама",
            "line_ids": [
                Command.create({"calc_mode": "linear", "sequence": 1,
                                "profile_id": self.beam.id, "length_mm": 1000.0}),
                Command.create({"calc_mode": "linear", "sequence": 2,
                                "profile_id": self.angle.id, "length_mm": 1000.0}),
                Command.create({"calc_mode": "linear", "sequence": 3, "detail_name": "Пустая"}),
                Command.create({"calc_mode": "fastener", "sequence": 4, "detail_name": "Болты"}),
            ],
        })]})
        product = spec.product_ids
        self.assertEqual(product.next_type_id, self.angle.type_id,
                         "Вид последней строки проката, у которой он есть.")
        product.line_linear_ids.filtered(lambda line: line.profile_id == self.beam).sequence = 10
        self.assertEqual(product.next_type_id, self.beam.type_id, "Порядок — по номеру строки.")
        empty = self.Spec.create({"product_ids": [Command.create({"name": "Пусто"})]})
        self.assertFalse(empty.product_ids.next_type_id)

    # ─── Собранная форма окна ────────────────────────────────────────────
    def _window(self):
        views = self.env["pmk.metal.spec"].get_views([(False, "form")])
        arch = etree.fromstring(views["views"]["form"]["arch"])
        return arch.xpath("//field[@name='product_ids']/form")[0]

    def test_window_fullscreen_and_title(self):
        window = self._window()
        classes = window.get("class", "").split()
        for cls in ("pmk-product-form", "pmk-dialog-fullscreen", "pmk-dialog-own-title"):
            with self.subTest(cls=cls):
                self.assertIn(cls, classes)
        self.assertNotIn("pmk-doc-form", classes, "Окно — своя форма, не документ.")
        self.assertEqual(window.get("string"), "Изделие")
        js = _read("pmk_calc/static/src/js/dobor_dialog_fullscreen.js")
        self.assertIn('"pmk-dialog-own-title"', js)
        self.assertIn('props.size = "fullscreen"', js)
        self.assertIn("props.title = title", js)
        # Без «развернуть»: она открывала автоформу строки (своей формы у
        # модели изделия нет) и уводила из расчёта.
        self.assertIn("delete props.onExpand", js)
        self.assertFalse(self.env["ir.ui.view"].search_count(
            [("model", "=", "pmk.metal.spec.product"), ("type", "=", "form")]),
            "Если у изделия появится своя форма — вернуть «развернуть» можно.")

    def test_window_tabs_like_sections(self):
        pages = [page.get("name") for page in self._window().xpath("./notebook/page")]
        self.assertEqual(pages, ["linear", "sheet", "fastener", "paint"],
                         "Прокат · Лист · Метизы · Покрытие.")
        js = _read("pmk_calc/static/src/js/product_lines_field.js")
        order = [js.index('mode: "%s"' % mode) for mode in pages]
        self.assertEqual(order, sorted(order), "Разделы состава — в том же порядке.")

    def test_window_head_two_rows(self):
        window = self._window()
        self.assertIsNone(window.find("group"), "Шапка — не группы в две колонки.")
        head = window.find("div[@name='pmk_product_head']")
        # Комментарии разметки get_views отдаёт как есть — считаем только div.
        rows = [row for row in head if row.tag == "div"]
        self.assertEqual([row.get("name") for row in rows],
                         ["pmk_product_row_main", "pmk_product_row_numbers"])
        self.assertEqual([block.get("name") for block in rows[0] if block.tag == "div"],
                         ["pmk_pf_name", "pmk_pf_qty", "pmk_pf_note"])
        numbers = [block.get("name") for block in rows[1] if block.tag == "div"]
        self.assertEqual(numbers[:2], ["pmk_pf_weight_one", "pmk_pf_weight_total"])
        for block in head.iter("div"):
            if "pmk-product-head__field" not in (block.get("class") or "").split():
                continue
            with self.subTest(block=block.get("name")):
                self.assertEqual(block[0].tag, "label",
                                 "Подпись — первой: слева от поля (стили — spec_form.scss).")
        self.assertEqual(head.find(".//div[@name='pmk_pf_name']/label").get("string"), "Название",
                         "Окно называется «Изделие» — у поля названия своя подпись.")

        weight_total = head.find(".//div[@name='pmk_pf_weight_total']")
        self.assertIsNone(head.find(".//div[@name='pmk_pf_weight_one']").get("invisible"))
        for qty, hidden in ((1, True), (2, False), (19, False)):
            with self.subTest(qty=qty):
                self.assertEqual(bool(safe_eval(weight_total.get("invisible"), {"qty": qty})),
                                 hidden, "«Вес всего» — только при количестве больше 1.")

    def test_note_is_for_yourself(self):
        label = self._window().find(".//div[@name='pmk_pf_note']/label[@for='note']")
        self.assertEqual(label.get("string"), "Заметка для себя (в КП не идёт)")
        field = self.env["pmk.metal.spec.product"]._fields["note"]
        self.assertEqual(field.string, "Заметка для себя")
        self.assertIn("В КП не идёт", field.help)
        # Длинная заметка переносится, а не обрезается (у СМ-00024 — 101
        # знак): многострочное поле, ввод одной строкой.
        note = self._window().find(".//div[@name='pmk_pf_note']/field[@name='note']")
        self.assertEqual(note.get("widget"), "text")
        self.assertIs(ast.literal_eval(note.get("options")).get("line_breaks"), False)
        self.assertIn("pmk-product-head__field--note",
                      self._window().find(".//div[@name='pmk_pf_note']").get("class").split())

    def test_linear_tab_one_size_field(self):
        window = self._window()
        self.assertTrue(window.xpath("./field[@name='next_type_id'][@invisible='1']"),
                        "Поле в форме — контекст списка его читает.")
        linear = window.xpath("./notebook/page[@name='linear']/field[@name='line_linear_ids']")[0]
        context = linear.get("context")
        self.assertIn("'default_calc_mode': 'linear'", context)
        self.assertIn("'default_type_id': next_type_id", context)

        columns = linear.xpath("./list/field")
        names = [column.get("name") for column in columns]
        visible = [column.get("name") for column in columns
                   if column.get("optional") != "hide"
                   and column.get("column_invisible") not in ("1", "True")]
        self.assertNotIn("type_id", visible, "Вид проката не просят — он из типоразмера.")
        self.assertEqual(columns[names.index("type_id")].get("optional"), "hide",
                         "Скрыта обратимо — в меню колонок.")
        self.assertLess(names.index("profile_id"), names.index("type_id"))
        profile = columns[names.index("profile_id")]
        self.assertIsNone(profile.get("domain"), "Отбора по виду нет — только порядок.")
        self.assertIn("'pmk_prefer_type_id': type_id", profile.get("context") or "")
        self.assertTrue(profile.get("placeholder"))
        # Шаг З-10: позиции нет — «Нет в справочнике — завести новую…» (окно,
        # позиция «на разнос»); по набранному тексту без окна — нельзя.
        options = ast.literal_eval(profile.get("options"))
        self.assertFalse(options.get("no_create"))
        self.assertTrue(options.get("no_quick_create"))
        self.assertIn("'pmk_pending_create': True", profile.get("context") or "")

    def test_composition_editor_one_size_field(self):
        """Редактор под строкой изделия: поля «Вид проката» нет, вид строки
        уходит в подсказку, новая строка берёт вид предыдущей."""
        js = _read("pmk_calc/static/src/js/product_lines_field.js")
        linear = js[js.index('mode: "linear"'):js.index('mode: "sheet"')]
        self.assertNotIn('name: "type_id"', linear)
        self.assertIn('name: "profile_id"', linear)
        self.assertIn("pmk_prefer_type_id", js)
        self.assertIn("context.default_type_id", js)
        xml = _read("pmk_calc/static/src/xml/product_lines_field.xml")
        self.assertIn('context="refContext(line, input)"', xml)
        self.assertIn('placeholder="input.placeholder"', xml)

    # ─── Ассеты ──────────────────────────────────────────────────────────
    def test_assets(self):
        manifest = get_manifest("pmk_calc")["assets"]["web.assets_backend"]
        bundle = [entry[0].lstrip("/") for entry in
                  self.env["ir.asset"]._get_asset_paths("web.assets_backend", {})]
        for path in ("pmk_calc/static/src/js/dobor_dialog_fullscreen.js",
                     "pmk_calc/static/src/js/product_lines_field.js",
                     "pmk_calc/static/src/xml/product_lines_field.xml",
                     "pmk_calc/static/src/scss/spec_form.scss"):
            with self.subTest(path=path):
                self.assertIn(path, manifest)
                self.assertIn(path, bundle)

    def test_window_styles_compile(self):
        """Стили окна — в живом файле модуля (spec_form.scss), компилируются."""
        try:
            import sass
        except ImportError:
            self.skipTest("libsass не установлен")
        css = sass.compile(string=_read("pmk_calc/static/src/scss/spec_form.scss"))
        for selector in (
            ".modal-dialog.modal-fullscreen:has(> .modal-content.pmk-product-form)",
            ".modal-content.pmk-product-form .pmk-product-head__row",
            ".modal-content.pmk-product-form .pmk-product-head__field--wide",
            ".modal-content.pmk-product-form .pmk-product-head__field--note",
            ".pmk-edit__field.pmk-edit__field--xwide",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, css)
        # Подпись слева: блок — строка, а не столбик.
        block = css[css.index(".modal-content.pmk-product-form .pmk-product-head__field {"):]
        block = block[:block.index("}")]
        self.assertIn("flex-direction: row", block)
