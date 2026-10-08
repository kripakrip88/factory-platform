# -*- coding: utf-8 -*-
"""Колонки у каждого, разбор UX, шаг 55: хранение и права.

Гонять ТОЛЬКО на одноразовой базе (см. __init__.py).

Поведение списка (ширина после растягивания, порядок, галочки, окно
«Колонки») смотрит основной агент в браузере; правила порядка и слияния с
колонками вида — node (static/tests/list_prefs_step55.test.mjs). Здесь —
то, что ломается молча: настройка не у того человека, общая без прав,
файлы не в бандле, стили в выключенном scss.
"""
import re
from unittest.mock import patch

from psycopg2 import errors as pg_errors

from odoo.exceptions import AccessError, ConcurrencyError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools.misc import file_open

KEY = "list|res.partner|12|7"
KEY_X2M = "x2m|pmk.metal.spec|product_ids|55"
JS = "pmk_list_prefs/static/src/js/"
PREFS = {
    "order": ["phone", "name", "email"],
    "widths": {"name": 240, "email": 180},
    "visible": {"email": False, "vat": True},
}


def _read(path):
    with file_open(path) as handle:
        return handle.read()


@tagged("post_install", "-at_install")
class TestListPrefsStep55(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Prefs = cls.env["pmk.list.prefs"]
        cls.user = new_test_user(cls.env, login="pmk55_user", groups="base.group_user")
        cls.other = new_test_user(cls.env, login="pmk55_other", groups="base.group_user")
        cls.admin = new_test_user(cls.env, login="pmk55_admin",
                                  groups="base.group_user,base.group_system")

    def _as(self, user):
        return self.Prefs.with_user(user)

    def _session(self, user):
        return self._as(user)._pmk_session_prefs()

    # ─── Своя настройка ─────────────────────────────────────────────────
    def test_save_and_read_own(self):
        clean = self._as(self.user).pmk_save(KEY, "res.partner", PREFS)
        self.assertEqual(clean, {"v": 1, **PREFS})
        session = self._session(self.user)
        self.assertEqual(session["own"][KEY], clean, "порядок, ширины и видимость — как сохранили")
        self.assertNotIn(KEY, session["common"])
        record = self.Prefs.search([("view_key", "=", KEY), ("user_id", "=", self.user.id)])
        self.assertEqual(len(record), 1)
        self.assertEqual(record.res_model, "res.partner")

    def test_save_twice_keeps_one_record(self):
        prefs = self._as(self.user)
        prefs.pmk_save(KEY, "res.partner", PREFS)
        prefs.pmk_save(KEY, "res.partner", {"order": ["name"]})
        records = self.Prefs.search([("view_key", "=", KEY), ("user_id", "=", self.user.id)])
        self.assertEqual(len(records), 1)
        self.assertEqual(records.prefs["order"], ["name"])
        self.assertEqual(records.prefs["widths"], {}, "сохранение заменяет настройку целиком")

    # ─── Две вкладки: правка сливается с хранимой ───────────────────────
    def test_change_merges_with_stored(self):
        """Вкладка А сохранила ширину и порядок; вкладка Б со старым кэшем
        (без своей настройки) снимает галочку — ширина и порядок А целы."""
        prefs = self._as(self.user)
        prefs.pmk_save(KEY, "res.partner", {"order": ["email", "name"], "widths": {"name": 300}},
                       {"order": ["email", "name"], "widths": {"name": 300}})
        stale_tab = {"order": [], "widths": {}, "visible": {"vat": False}}
        saved = prefs.pmk_save(KEY, "res.partner", stale_tab, {"visible": {"vat": False}})
        self.assertEqual(saved, {"v": 1, "order": ["email", "name"], "widths": {"name": 300},
                                 "visible": {"vat": False}})
        self.assertEqual(self._session(self.user)["own"][KEY], saved, "в базе — слитая")

    def test_change_ops(self):
        prefs = self._as(self.user)
        prefs.pmk_save(KEY, "res.partner", PREFS)
        # Снять одну ширину, поставить другую; порядок заменить.
        saved = prefs.pmk_save(KEY, "res.partner", {}, {
            "widths": {"name": None, "phone": 10, "junk": "x"},
            "order": ["email", "phone"],
            "visible": {"email": True, "bad": "yes"},
        })
        self.assertEqual(saved["widths"], {"email": 180, "phone": 40})
        self.assertEqual(saved["order"], ["email", "phone"])
        self.assertEqual(saved["visible"], {"email": True, "vat": True})
        # Двойной щелчок по краю — все ширины сняты, остальное цело.
        saved = prefs.pmk_save(KEY, "res.partner", {}, {"resetWidths": True})
        self.assertEqual(saved["widths"], {})
        self.assertEqual(saved["order"], ["email", "phone"])

    def test_change_without_record_saves_prefs(self):
        """Своей записи нет — сохраняется настройка целиком (копия общей или
        того, что было на экране, плюс правка)."""
        saved = self._as(self.user).pmk_save(KEY, "res.partner", PREFS, {"widths": {"name": 240}})
        self.assertEqual(saved, {"v": 1, **PREFS})

    def test_change_must_be_dict(self):
        with self.assertRaises(ValidationError):
            self._as(self.user).pmk_save(KEY, "res.partner", PREFS, ["x"])

    def test_concurrent_first_save_retried(self):
        """Две вкладки одновременно заводят первую настройку: вторая получает
        UniqueViolation. Повторный поиск в той же транзакции (REPEATABLE READ)
        соседа не видит — правка пропала бы молча. Поэтому ConcurrencyError:
        ядро повторит весь запрос в новой транзакции."""
        Model = type(self.Prefs)

        def clash(self_, vals_list):
            raise pg_errors.UniqueViolation("duplicate key value violates unique constraint")

        with patch.object(Model, "create", clash), self.assertRaises(ConcurrencyError):
            self._as(self.user).pmk_save(KEY, "res.partner", PREFS, {"visible": {"email": False}})

    def test_views_are_separate(self):
        prefs = self._as(self.user)
        prefs.pmk_save(KEY, "res.partner", PREFS)
        prefs.pmk_save(KEY_X2M, "pmk.metal.product", {"order": ["qty"]})
        own = self._session(self.user)["own"]
        self.assertEqual(own[KEY]["order"], PREFS["order"])
        self.assertEqual(own[KEY_X2M]["order"], ["qty"])
        # Другое действие того же вида — другой список («Клиенты» и «Поставщики»).
        self.assertNotIn("list|res.partner|12|8", own)

    def test_second_user_has_own(self):
        self._as(self.user).pmk_save(KEY, "res.partner", PREFS)
        self.assertNotIn(KEY, self._session(self.other)["own"], "чужая настройка не видна")
        self._as(self.other).pmk_save(KEY, "res.partner", {"order": ["email"]})
        self.assertEqual(self._session(self.user)["own"][KEY]["order"], PREFS["order"])
        self.assertEqual(self._session(self.other)["own"][KEY]["order"], ["email"])

    def test_reset_own(self):
        prefs = self._as(self.user)
        prefs.pmk_save(KEY, "res.partner", PREFS)
        self.assertTrue(prefs.pmk_reset(KEY))
        self.assertNotIn(KEY, self._session(self.user)["own"])
        self.assertTrue(prefs.pmk_reset(KEY), "сброс пустого — не ошибка")

    # ─── Чистка ─────────────────────────────────────────────────────────
    def test_clean(self):
        clean = self._as(self.user).pmk_save(KEY, "res.partner", {
            "order": ["a", "a", "", 5, "b"],
            "widths": {"a": 5, "b": 99999, "c": "250.6", "d": True, "e": "x", "f": -3},
            "visible": {"a": False, "b": "no", "c": 1},
            "junk": {"x": 1},
        })
        self.assertEqual(clean, {
            "v": 1,
            "order": ["a", "b"],
            "widths": {"a": 40, "b": 2000, "c": 251},
            "visible": {"a": False},
        })
        self.assertEqual(self._as(self.user).pmk_save(KEY, False, None),
                         {"v": 1, "order": [], "widths": {}, "visible": {}})

    def test_bad_input(self):
        prefs = self._as(self.user)
        for key in ("", "form|x", "list|res.partner|1|1; drop", "x" * 300, None, 12):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                prefs.pmk_save(key, "res.partner", {})
        with self.assertRaises(ValidationError):
            prefs.pmk_save(KEY, "res.partner", ["not", "a", "dict"])
        with self.assertRaises(ValidationError):
            prefs.pmk_save(KEY, "res.partner", {"order": ["k" * 100] * 300})
        # Модель — только имя модели, иначе пусто.
        prefs.pmk_save(KEY, "res.partner'); --", {})
        record = self.Prefs.search([("view_key", "=", KEY), ("user_id", "=", self.user.id)])
        self.assertFalse(record.res_model)

    # ─── Общая («у всех по умолчанию») ──────────────────────────────────
    def test_common_seen_by_users_without_own(self):
        result = self._as(self.admin).pmk_save_common(KEY, "res.partner", PREFS)
        self.assertEqual(result["prefs"], {"v": 1, **PREFS})
        # Человек без своей настройки и новый пользователь видят общую.
        self.assertEqual(self._session(self.other)["common"][KEY], result["prefs"])
        newcomer = new_test_user(self.env, login="pmk55_newcomer", groups="base.group_user")
        session = self._session(newcomer)
        self.assertEqual(session["common"][KEY], result["prefs"])
        self.assertNotIn(KEY, session["own"])

    def test_own_wins_over_common(self):
        self._as(self.user).pmk_save(KEY, "res.partner", {"order": ["email"]})
        self._as(self.admin).pmk_save_common(KEY, "res.partner", PREFS)
        session = self._session(self.user)
        # Браузер берёт свою, если она есть (list_prefs_rules.js, effectivePrefs).
        self.assertEqual(session["own"][KEY]["order"], ["email"])
        self.assertEqual(session["common"][KEY]["order"], PREFS["order"])
        # «Вернуть общую»: своя снимается — остаётся общая.
        self._as(self.user).pmk_reset(KEY)
        session = self._session(self.user)
        self.assertNotIn(KEY, session["own"])
        self.assertIn(KEY, session["common"])

    def test_common_count_and_admin_own_dropped(self):
        self._as(self.admin).pmk_save(KEY, "res.partner", {"order": ["a"]})
        self._as(self.user).pmk_save(KEY, "res.partner", {"order": ["b"]})
        result = self._as(self.admin).pmk_save_common(KEY, "res.partner", PREFS)
        self.assertNotIn(KEY, self._session(self.admin)["own"],
                         "администратор сразу видит то, что увидят все")
        internal = self.env["res.users"].search_count([("share", "=", False)])
        self.assertEqual(result["users_on_common"], internal - 1, "все внутренние, кроме pmk55_user")
        # Общая одна: повторное «у всех» её заменяет.
        self._as(self.admin).pmk_save_common(KEY, "res.partner", {"order": ["z"]})
        common = self.Prefs.search([("view_key", "=", KEY), ("user_id", "=", False)])
        self.assertEqual(len(common), 1)
        self.assertEqual(common.prefs["order"], ["z"])

    def test_reset_common(self):
        self._as(self.admin).pmk_save_common(KEY, "res.partner", PREFS)
        with self.assertRaises(AccessError):
            self._as(self.user).pmk_reset_common(KEY)
        self.assertTrue(self._as(self.admin).pmk_reset_common(KEY))
        self.assertNotIn(KEY, self._session(self.user)["common"])

    # ─── Права ──────────────────────────────────────────────────────────
    def test_only_admin_saves_common(self):
        with self.assertRaises(AccessError):
            self._as(self.user).pmk_save_common(KEY, "res.partner", PREFS)
        self.assertFalse(self.Prefs.search([("view_key", "=", KEY), ("user_id", "=", False)]))
        # В обход метода — тоже нельзя.
        with self.assertRaises(AccessError):
            self._as(self.user).create({"view_key": KEY, "user_id": False, "prefs": {}})
        with self.assertRaises(AccessError):
            self._as(self.user).create({"view_key": KEY, "user_id": self.other.id, "prefs": {}})

    def test_records_closed_to_others(self):
        self._as(self.admin).pmk_save_common(KEY, "res.partner", PREFS)
        self._as(self.other).pmk_save(KEY, "res.partner", {"order": ["x"]})
        common = self.Prefs.search([("view_key", "=", KEY), ("user_id", "=", False)])
        others = self.Prefs.search([("view_key", "=", KEY), ("user_id", "=", self.other.id)])
        as_user = self._as(self.user)
        # Общую читать можно, писать и удалять — нет.
        self.assertEqual(as_user.browse(common.id).prefs["order"], PREFS["order"])
        with self.assertRaises(AccessError):
            as_user.browse(common.id).write({"prefs": {}})
        with self.assertRaises(AccessError):
            as_user.browse(common.id).unlink()
        # Чужую свою — ни видеть, ни трогать.
        self.assertFalse(as_user.search([("id", "=", others.id)]))
        with self.assertRaises(AccessError):
            as_user.browse(others.id).prefs  # noqa: B018 — чтение поля
        with self.assertRaises(AccessError):
            as_user.browse(others.id).write({"prefs": {}})
        # Свою запись не переписать на другого.
        self._as(self.user).pmk_save(KEY, "res.partner", {})
        mine = self.Prefs.search([("view_key", "=", KEY), ("user_id", "=", self.user.id)])
        with self.assertRaises(AccessError):
            as_user.browse(mine.id).write({"user_id": self.other.id})
        with self.assertRaises(AccessError):
            as_user.browse(mine.id).write({"user_id": False})

    def test_user_removed_prefs_removed(self):
        user = new_test_user(self.env, login="pmk55_gone", groups="base.group_user")
        self._as(user).pmk_save(KEY, "res.partner", PREFS)
        user.unlink()
        self.assertFalse(self.Prefs.search([("view_key", "=", KEY), ("user_id", "=", user.id)]))

    # ─── Сборка ─────────────────────────────────────────────────────────
    def _paths(self, bundle="web.assets_backend"):
        return [entry[0].lstrip("/") for entry in self.env["ir.asset"]._get_asset_paths(bundle, {})]

    def test_js_in_bundle_in_order(self):
        paths = self._paths()
        files = [JS + "list_prefs_rules.js", JS + "list_prefs_store.js", JS + "columns_dialog.js",
                 "pmk_list_prefs/static/src/xml/columns_dialog.xml", JS + "list_prefs.js"]
        for name in files:
            with self.subTest(file=name):
                self.assertIn(name, paths)
        self.assertEqual([paths.index(name) for name in files],
                         sorted(paths.index(name) for name in files),
                         "правила — раньше файлов, которые их импортируют")
        # Наш getActiveColumns — поверх патчей шага 24 (знаки, деньги).
        self.assertLess(paths.index("pmk_theme/static/src/js/list_table.js"),
                        paths.index(JS + "list_prefs.js"))
        self.assertNotIn("pmk_list_prefs/static/tests/list_prefs_step55.test.mjs", paths)

    def test_requests_through_env_services(self):
        """Грабля шага 31: промис useService после уничтожения компонента."""
        for name in ("list_prefs_store.js", "list_prefs.js", "columns_dialog.js"):
            code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", _read(JS + name), flags=re.S))
            with self.subTest(file=name):
                self.assertNotIn("useService", code)
        store = _read(JS + "list_prefs_store.js")
        for method in ('"pmk_save"', '"pmk_reset"', '"pmk_save_common"', '"pmk_reset_common"'):
            self.assertIn(method, store)
        self.assertIn("session.pmk_list_prefs", store)

    def test_no_column_invisible_trick(self):
        """Прячем убиранием из колонок, а не column_invisible: у вложенной
        таблицы column_invisible режет загрузку её наборов."""
        code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", _read(JS + "list_prefs.js"), flags=re.S))
        self.assertNotIn("column_invisible =", code)
        self.assertNotIn("column_invisible:", code)

    def test_styles_in_live_files(self):
        """Стили — в живых scss темы (forms_nexus seq 41, dark seq 42):
        остальные файлы темы на стенде выключены."""
        paths = self._paths()
        forms = "pmk_theme/static/src/scss/forms_nexus.scss"
        dark = "pmk_theme/static/src/scss/dark.scss"
        for path in (forms, dark):
            self.assertIn(path, paths)
        light = _read(forms)
        start = light.index("// ═══ Шаг 55")
        section = light[start:]
        for selector in (".o_pmk_cols_dialog", ".o_pmk_cols_row", ".o_pmk_col_drop",
                         "th.o_pmk_col_dragged", "body.o_pmk_col_dragging"):
            with self.subTest(selector=selector):
                self.assertIn(selector, section)
        dark_src = _read(dark)
        dark_section = dark_src[dark_src.index("// ═══ Шаг 55"):]
        self.assertIn("body.o_nexus_dark .o_pmk_cols_dialog", dark_section)
        self.assertIn("body.o_nexus_dark .o_pmk_col_drop", dark_section)
        self.assertIn("@media screen", dark_section, "печать из тёмной остаётся светлой")


@tagged("post_install", "-at_install")
class TestListPrefsSession(HttpCase):
    """Настройки приходят со страницей и пишутся вызовом из браузера."""

    def setUp(self):
        super().setUp()
        self.password = "pmk55-page-pass"
        self.user = new_test_user(self.env, login="pmk55_page", password=self.password,
                                  groups="base.group_user")

    def _call(self, method, *args):
        return self.make_jsonrpc_request(f"/web/dataset/call_kw/pmk.list.prefs/{method}", {
            "model": "pmk.list.prefs", "method": method, "args": list(args), "kwargs": {},
        })

    def test_session_info_round_trip(self):
        self.authenticate(self.user.login, self.password)
        info = self.make_jsonrpc_request("/web/session/get_session_info")
        self.assertEqual(info["pmk_list_prefs"], {"own": {}, "common": {}})
        self._call("pmk_save", KEY, "res.partner", PREFS)
        info = self.make_jsonrpc_request("/web/session/get_session_info")
        self.assertEqual(info["pmk_list_prefs"]["own"][KEY], {"v": 1, **PREFS})
        # Страница веб-клиента несёт то же (session_info в разметке).
        response = self.url_open("/odoo", timeout=60)
        self.assertEqual(response.status_code, 200)
        # Кавычки в разметке страницы могут прийти экранированными — ищем без них.
        self.assertIn("pmk_list_prefs", response.text)
        self.assertIn(KEY, response.text)

    def test_not_for_portal(self):
        portal = new_test_user(self.env, login="pmk55_portal", password=self.password,
                               groups="base.group_portal")
        self.authenticate(portal.login, self.password)
        info = self.make_jsonrpc_request("/web/session/get_session_info")
        self.assertNotIn("pmk_list_prefs", info)
