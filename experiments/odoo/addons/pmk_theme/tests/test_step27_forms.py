# -*- coding: utf-8 -*-
"""Формы: один стиль подписей (разбор UX, шаг 27) — что доезжает до браузера.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py).

Сам вид (подпись слева, поля на одной вертикали, рамки дробных полей, бледные
нули раскроя) смотрит основной агент глазами на копии — в обеих темах.
Здесь — то, что ломается молча: правило положено в выключенный scss и на
стенд не доехало; тёмная тема снова красит подпись шапки серым; бледные
нули во вложенных таблицах включились всем, а не по согласию вида.
"""
import re

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_path

SCSS = "pmk_theme/static/src/scss/"


def read(path):
    with open(file_path(path), encoding="utf-8") as f:
        return f.read()


@tagged("post_install", "-at_install")
class TestFormsStep27(TransactionCase):

    def _paths(self, bundle="web.assets_backend"):
        return [entry[0].lstrip("/") for entry in self.env["ir.asset"]._get_asset_paths(bundle, {})]

    def test_rules_in_live_file(self):
        """Правила шага — в живом forms_nexus.scss (остальные scss темы на
        стенде выключены, ir.asset active=False)."""
        self.assertIn(SCSS + "forms_nexus.scss", self._paths())
        scss = read(SCSS + "forms_nexus.scss")
        self.assertIn("@supports (grid-template-columns: subgrid)", scss)
        self.assertIn("grid-template-columns: max-content minmax(0, 1fr) max-content minmax(0, 1fr)", scss)
        self.assertIn("grid-template-columns: subgrid", scss)
        self.assertIn(".o_form_view.pmk-doc-form:not(.o_xxs_form_view) .o_inner_group.grid", scss)
        self.assertIn(".o_field_float:not(.pmk-doc-form *) input.o_input", scss,
                      "Рамку дробного поля в наших документах возвращает тема.")
        self.assertIn("o_external_button", scss)

    def test_halves_only_when_they_fit(self):
        """Половины «подпись · поле · подпись · поле» — только с 1320 px;
        701–1319 px — каждый блок строкой во всю ширину, подпись слева
        (доводка шага 27: на 1101–1300 px половине не хватало места, и
        «Контактное лицо» и «Клиент» обрезались). Стиль подписи один —
        слева — в обеих раскладках."""
        scss = read(SCSS + "forms_nexus.scss")
        block = scss[scss.index("@supports (grid-template-columns: subgrid)"):]
        block = block[:block.index("\n}\n")]
        rows = block.index("@media (min-width: 701px)")
        two = block.index("grid-template-columns: max-content minmax(0, 1fr);")
        halves = block.index("@media (min-width: 1320px)")
        four = block.index("grid-template-columns: max-content minmax(0, 1fr) max-content minmax(0, 1fr)")
        self.assertLess(rows, two)
        self.assertLess(two, halves, "Строки — до порога половин.")
        self.assertLess(halves, four, "Четыре колонки — только с 1320 px.")
        self.assertIn("grid-column: 1 / -1", block[rows:halves], "Ниже порога — строка во всю ширину.")
        self.assertNotIn("span 2", block[rows:halves])
        self.assertIn("grid-column: span 2", block[halves:])
        self.assertIn("grid-template-columns: subgrid", block[rows:halves])
        self.assertIn("white-space: nowrap", block[rows:halves])

    def test_head_label_not_grey(self):
        """Подпись шапки — как у штатных групп: ни серого цвета, ни 12 px."""
        scss = read(SCSS + "forms_nexus.scss")
        block = scss[scss.index(".pmk-field {"):]
        block = block[:block.index("\n}\n")]
        label = block[block.index("> label {"):]
        label = label[:label.index("}")]
        self.assertNotIn("color", label)
        self.assertNotIn("font-size", label)
        dark = read(SCSS + "dark.scss")
        self.assertIsNone(re.search(r"^\s*body\.o_nexus_dark \.pmk-field > label", dark, re.M),
                          "В тёмной теме подпись шапки — цвет текста, не серый.")

    def test_x2many_zero_opt_in(self):
        js = read("pmk_theme/static/src/js/list_zero.js")
        self.assertIn('X2MANY_ZERO_OPT_IN = "o_pmk_zero_muted"', js)
        self.assertIn("this.isX2Many && !x2manyWantsMutedZeros(this.props.archInfo?.className)", js)
        self.assertIn("pmk_theme/static/src/js/list_zero.js", self._paths())
