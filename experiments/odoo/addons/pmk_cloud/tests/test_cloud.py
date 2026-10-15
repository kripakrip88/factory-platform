# -*- coding: utf-8 -*-
"""Облако Mail.ru → группа: точка отсчёта, новые, перенесённые, обновлённые, фильтр расширений.

Облако — подделка с тем же list(), что у tools.webdav.WebDav (сеть в тестах не нужна).
"""
from datetime import date, datetime
from unittest import mock

from odoo.tests import TransactionCase, tagged

from ..tools.webdav import WebDav, WebDavError, is_recent, parse_multistatus

T = datetime(2026, 10, 9, 3, 10)


class FakeDav(WebDav):
    def __init__(self, tree):
        self.tree = tree  # {путь папки: [(имя, размер | None для папки)]}
        self.listed = []

    def list(self, path):
        self.listed.append(path)
        if path not in self.tree:
            raise WebDavError("В Облаке нет папки «%s»." % path)
        return [{"path": path + "/" + n, "name": n, "dir": s is None, "size": s or 0, "mtime": T}
                for n, s in self.tree[path]]


@tagged("post_install", "-at_install")
class TestCloud(TransactionCase):

    def setUp(self):
        super().setUp()
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("pmk_cloud.password", "test")
        icp.set_param("pmk_cloud.root", "/ПРОИЗВОДСТВО")
        icp.set_param("pmk_cloud.baseline_root", False)
        self.Cloud = self.env["pmk.cloud.file"]
        self.tree = {
            "/ПРОИЗВОДСТВО": [("09.10.26", None), ("01.06.26", None), ("план.dxf", 10), ("тест", None),
                              ("Архив", None)],
            "/ПРОИЗВОДСТВО/тест": [],
            "/ПРОИЗВОДСТВО/Архив": [("2025", None)],
            "/ПРОИЗВОДСТВО/Архив/2025": [("давнее.lxds", 500)],
            "/ПРОИЗВОДСТВО/09.10.26": [("СИБЭМУ", None), ("опора.lxds", 148497), ("опора.lxds.fs.emf", 10)],
            "/ПРОИЗВОДСТВО/09.10.26/СИБЭМУ": [("лист.dxf", 670528)],
            "/ПРОИЗВОДСТВО/01.06.26": [("старое.zx", 2000)],
        }
        self.dav = FakeDav(self.tree)
        self.sent = []
        patches = [
            mock.patch.object(type(self.Cloud), "_dav", lambda s, cfg: self.dav),
            mock.patch.object(type(self.Cloud), "_notify",
                              lambda s, root, fresh: self.sent.append(s._message(root, fresh)) or True),
            mock.patch("odoo.fields.Date.context_today", return_value=date(2026, 10, 15)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_baseline_is_silent(self):
        self.Cloud._cron_scan()
        self.assertEqual(self.sent, [], "что уже лежит — не новость")
        self.assertEqual(sorted(self.Cloud.search([]).mapped("name")),
                         ["давнее.lxds", "лист.dxf", "опора.lxds", "план.dxf", "старое.zx"], ".emf не берём")
        self.assertIn("/ПРОИЗВОДСТВО/01.06.26", self.dav.listed, "точка отсчёта — вся папка")

    def test_new_files_one_message(self):
        self.Cloud._cron_scan()
        self.tree["/ПРОИЗВОДСТВО/09.10.26/СИБЭМУ"].append(("косынка.DXF", 2048))
        self.tree["/ПРОИЗВОДСТВО/09.10.26"].append(("гнутьё.zx", 3 * 1048576))
        self.tree["/ПРОИЗВОДСТВО/09.10.26"].append(("фото.jpg", 5))
        self.dav.listed = []
        self.Cloud._cron_scan()
        self.assertNotIn("/ПРОИЗВОДСТВО/01.06.26", self.dav.listed, "старые даты — только ночью")
        self.assertEqual(len(self.sent), 1)
        msg = self.sent[0]
        self.assertIn("новых файлов: 2", msg)
        self.assertIn("ПРОИЗВОДСТВО / 09.10.26 / СИБЭМУ", msg)
        self.assertIn("косынка.DXF (2 КБ)", msg)
        self.assertIn("гнутьё.zx (3,0 МБ)", msg)
        self.assertNotIn("фото.jpg", msg)

    def test_folder_without_date_checked_often_archive_at_night(self):
        """Папки без даты («тест», «Типовые детали») — раз в 5 минут; «Архив» — только ночью."""
        self.Cloud._cron_scan()
        self.tree["/ПРОИЗВОДСТВО/тест"].append(("проба.lxds", 4096))
        self.tree["/ПРОИЗВОДСТВО/Архив/2025"].append(("в архив.dxf", 1024))
        self.dav.listed = []
        self.Cloud._cron_scan()
        self.assertIn("/ПРОИЗВОДСТВО/тест", self.dav.listed)
        self.assertNotIn("/ПРОИЗВОДСТВО/Архив", self.dav.listed)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("проба.lxds", self.sent[0])
        self.assertNotIn("в архив.dxf", self.sent[0])
        self.Cloud._cron_scan(full=True)
        self.assertEqual(len(self.sent), 2)
        self.assertIn("в архив.dxf", self.sent[1])

    def test_old_date_folder_caught_by_night_scan(self):
        self.Cloud._cron_scan()
        self.tree["/ПРОИЗВОДСТВО/01.06.26"].append(("дозалили.lxds", 1024))
        self.Cloud._cron_scan()
        self.assertEqual(self.sent, [])
        self.Cloud._cron_scan(full=True)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("дозалили.lxds", self.sent[0])

    def test_moved_is_not_new_and_update_is_reported(self):
        self.Cloud._cron_scan()
        self.tree["/ПРОИЗВОДСТВО/09.10.26/СИБЭМУ"] = []
        self.tree["/ПРОИЗВОДСТВО/09.10.26"].append(("лист.dxf", 670528))
        self.Cloud._cron_scan()
        self.assertEqual(self.sent, [], "перенос в другую папку — не новый файл")
        self.tree["/ПРОИЗВОДСТВО/09.10.26"] = [("опора.lxds", 150000)]
        self.Cloud._cron_scan()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("опора.lxds", self.sent[0])
        self.assertIn("обновлён", self.sent[0])

    def test_baseline_in_parts(self):
        """Обход частями: за запуск — сколько успеется; сбой папки — она в очередь, найденное не теряется."""
        clock = {"t": 0.0}

        def tick():
            clock["t"] += 50.0  # каждая сверка срока — +50 с: за запуск (90 с) одна папка
            return clock["t"]

        fail = {"path": "/ПРОИЗВОДСТВО/09.10.26/СИБЭМУ", "left": 1}
        list_ = self.dav.list

        def flaky(path):
            if path == fail["path"] and fail["left"]:
                fail["left"] -= 1
                raise WebDavError("Облако недоступно: ReadTimeout")
            return list_(path)

        self.dav.list = flaky
        icp = self.env["ir.config_parameter"].sudo()
        with mock.patch("odoo.addons.pmk_cloud.models.cloud_file.time.monotonic", side_effect=tick):
            runs = 0
            while icp.get_param("pmk_cloud.baseline_root") != "/ПРОИЗВОДСТВО" and runs < 10:
                self.Cloud._cron_scan()
                runs += 1
        self.assertGreater(runs, 3, "обход растянулся на несколько запусков")
        self.assertEqual(self.sent, [], "точка отсчёта — без сообщений")
        self.assertFalse(icp.get_param("pmk_cloud.walk"), "очередь обхода закрыта")
        self.assertEqual(sorted(self.Cloud.search([]).mapped("name")),
                         ["давнее.lxds", "лист.dxf", "опора.lxds", "план.dxf", "старое.zx"],
                         "сбой папки не выбросил её файлы из точки отсчёта")

    def test_telegram_refused_is_resent(self):
        """Телеграм отказал (тема закрыта) — файл не считается отправленным, уйдёт следующей проверкой."""
        self.Cloud._cron_scan()
        self.tree["/ПРОИЗВОДСТВО/09.10.26"].append(("заказ.dxf", 2048))
        with mock.patch.object(type(self.Cloud), "_notify", lambda s, root, fresh: False):
            self.Cloud._cron_scan()
        rec = self.Cloud.search([("name", "=", "заказ.dxf")])
        self.assertTrue(rec.pending)
        self.assertIn("не принял", self.env["ir.config_parameter"].sudo().get_param("pmk_cloud.last_status"))
        self.Cloud._cron_scan()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("заказ.dxf", self.sent[0])
        self.assertFalse(rec.pending)
        self.assertTrue(rec.notified)

    def test_copy_from_archive_is_new(self):
        """Копия файла из «Архива» в папку даты — новый файл, запись оригинала не трогаем."""
        self.Cloud._cron_scan()
        self.tree["/ПРОИЗВОДСТВО/09.10.26"].append(("давнее.lxds", 500))
        self.Cloud._cron_scan()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("давнее.lxds", self.sent[0])
        self.assertEqual(sorted(self.Cloud.search([("name", "=", "давнее.lxds")]).mapped("path")),
                         ["/ПРОИЗВОДСТВО/09.10.26/давнее.lxds", "/ПРОИЗВОДСТВО/Архив/2025/давнее.lxds"])

    def test_error_goes_to_status_not_crash(self):
        self.env["ir.config_parameter"].sudo().set_param("pmk_cloud.root", "/НЕТ")
        self.Cloud._cron_scan()
        self.assertIn("нет папки", self.env["ir.config_parameter"].sudo().get_param("pmk_cloud.last_status"))

    def test_paused_is_quiet(self):
        self.Cloud._cron_scan()
        self.env["ir.config_parameter"].sudo().set_param("pmk_cloud.paused", "1")
        self.tree["/ПРОИЗВОДСТВО/09.10.26"].append(("новое.dxf", 10))
        self.dav.listed = []
        self.Cloud._cron_scan()
        self.assertEqual(self.dav.listed, [], "уведомления выключены — Облако не трогаем")
        self.assertEqual(self.sent, [])

    def test_not_configured_is_quiet(self):
        self.env["ir.config_parameter"].sudo().set_param("pmk_cloud.password", False)
        self.Cloud._cron_scan()
        self.assertEqual(self.dav.listed, [])

    def test_check_lists_root(self):
        self.env["ir.config_parameter"].sudo().set_param("pmk_cloud.root", False)
        self.tree["/"] = [("ПРОИЗВОДСТВО", None), ("Фото", None)]
        ok, text = self.Cloud._check_connection()
        self.assertTrue(ok)
        self.assertIn("ПРОИЗВОДСТВО, Фото", text)

    def test_pure_helpers(self):
        self.assertTrue(is_recent("09.10.26", date(2026, 10, 15), 7))
        self.assertFalse(is_recent("01.06.26", date(2026, 10, 15), 7))
        self.assertFalse(is_recent("СИБЭМУ", date(2026, 10, 15), 7))
        items = parse_multistatus(
            b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>/%D0%90/</d:href><d:propstat><d:prop>'
            b'<d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>'
            b'<d:response><d:href>/%D0%90/x%201.dxf</d:href><d:propstat><d:prop><d:resourcetype/>'
            b'<d:getcontentlength>12</d:getcontentlength>'
            b'<d:getlastmodified>Thu, 09 Oct 2026 03:10:22 GMT</d:getlastmodified></d:prop></d:propstat>'
            b'</d:response></d:multistatus>')
        self.assertEqual([(i["path"], i["dir"], i["size"]) for i in items],
                         [("/А", True, 0), ("/А/x 1.dxf", False, 12)])

    def test_retry_on_timeout(self):
        """Медленное Облако: два сбоя сети подряд — не ошибка, третий — ошибка с именем папки."""
        import requests

        class Resp:
            status_code = 207
            content = (b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>/X/</d:href><d:propstat><d:prop>'
                       b'<d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>'
                       b'</d:multistatus>')

        class Http:
            def __init__(self, fails):
                self.fails, self.calls, self.auth = fails, 0, None

            def request(self, *a, **kw):
                self.calls += 1
                if self.calls <= self.fails:
                    raise requests.exceptions.ReadTimeout()
                return Resp()

        http = Http(2)
        self.assertEqual(WebDav("u", "p", session=http, sleep=lambda s: None).list("/X"), [])
        self.assertEqual(http.calls, 3)
        with self.assertRaisesRegex(WebDavError, "ReadTimeout.*«/X».*3"):
            WebDav("u", "p", session=Http(3), sleep=lambda s: None).list("/X")
