# -*- coding: utf-8 -*-
"""Таблицы одного вида, разбор UX, шаг 24: что доезжает до браузера.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py).

Сам вид (высота строки, перенос шапки, пустые строки) смотрит основной агент
в браузере, правила знаков итога — node
(scratchpad/s24/list_table_rules.test.mjs). Здесь — то, что ломается
молча: файл выпал из бандла или встал раньше модуля, который импортирует;
стили положены в выключенный scss и на стенд не доехали.
"""
from odoo.tests import TransactionCase, tagged

JS = "pmk_theme/static/src/js/"


@tagged("post_install", "-at_install")
class TestListTableStep24(TransactionCase):

    def _paths(self, bundle="web.assets_backend"):
        return [entry[0].lstrip("/") for entry in self.env["ir.asset"]._get_asset_paths(bundle, {})]

    def test_js_in_bundle_in_order(self):
        paths = self._paths()
        for name in ("list_money.js", "list_table_rules.js", "list_table.js"):
            with self.subTest(file=name):
                self.assertIn(JS + name, paths)
        self.assertLess(paths.index(JS + "list_money.js"), paths.index(JS + "list_table_rules.js"))
        self.assertLess(paths.index(JS + "list_table_rules.js"), paths.index(JS + "list_table.js"),
                        "Правила — раньше патча, который их импортирует.")

    def test_styles_in_live_files(self):
        """Правила шага 24 — в живых scss (forms_nexus, dark): остальные файлы
        темы на стенде выключены (ir.asset active=False), правка туда не
        доехала бы."""
        paths = self._paths()
        for name in ("forms_nexus.scss", "dark.scss"):
            with self.subTest(file=name):
                self.assertIn("pmk_theme/static/src/scss/" + name, paths)
