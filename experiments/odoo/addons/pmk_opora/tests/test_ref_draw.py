# -*- coding: utf-8 -*-
"""Чертежи марки справочника (27.10.2026): задание в очередь чертёжного процесса и сбор готового —
без самого процесса (его работу изображает тест)."""
import json
import os
import tempfile
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models import ref_draw


@tagged("post_install", "-at_install")
class TestRefDraw(TransactionCase):

    def setUp(self):
        super().setUp()
        self.root = tempfile.mkdtemp()
        open(os.path.join(self.root, ref_draw.WORKER_ALIVE), "w").close()
        patcher = patch.object(ref_draw.OporaRefDraw, "_draw_root", staticmethod(lambda: self.root))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.Ref = self.env["pmk.opora.ref"]
        self.kx = self.Ref.search([("opora_type", "=", "kx"), ("execution", "=", "А12"), ("dn", "=", 219)], limit=1)

    def test_queue_and_collect(self):
        info = self.kx.opora_draw()
        self.assertEqual(info["state"], "queued")
        wd = self.kx.draw_workdir
        self.assertTrue(os.path.exists(os.path.join(wd, "queued")))
        with open(os.path.join(wd, "runner")) as f:
            self.assertEqual(f.read(), "pmk_opora/worker/runner.py")
        with open(os.path.join(wd, "input.json"), encoding="utf-8") as f:
            item = json.load(f)["items"][0]
        self.assertEqual((item["kind"], item["exe"], item["dn"]), ("kx", "А12", 219))
        self.assertEqual(self.kx.opora_draw_state()["state"], "queued", "Процесс ещё рисует.")
        # «процесс» нарисовал
        out = os.path.join(wd, "out", item["key"])
        os.makedirs(out)
        for name, data in (("a.pdf", b"%PDF-1.4"), ("a.png", b"\x89PNG"), ("поз1.dxf", b"0\nEOF\n")):
            with open(os.path.join(out, name), "wb") as f:
                f.write(data)
        with open(os.path.join(wd, "result.json"), "w", encoding="utf-8") as f:
            json.dump({"items": [{"key": item["key"], "pdf": "out/%s/a.pdf" % item["key"],
                                  "png": ["out/%s/a.png" % item["key"]], "rules": "v2",
                                  "dxf": [{"file": "out/%s/поз1.dxf" % item["key"], "qty": 1}]}]}, f)
        info = self.kx.opora_draw_state()
        self.assertEqual(info["state"], "done")
        self.assertTrue(info["pdf"] and info["png"] and info["zip"])
        self.assertEqual(self.kx.draw_pdf_id.raw, b"%PDF-1.4")
        self.assertFalse(os.path.exists(wd), "Папка задания убрана.")

    def test_worker_down(self):
        os.utime(os.path.join(self.root, ref_draw.WORKER_ALIVE), (0, 0))
        info = self.kx.opora_draw()
        self.assertEqual(info["state"], "error")
        self.assertIn("не отвечает", info["error"])

    def test_unsupported(self):
        other = self.Ref.search([("opora_type", "=", "kx"), ("execution", "=", "А11")], limit=1)
        self.assertFalse(other._draw_info()["supported"])
        with self.assertRaises(UserError):
            other.opora_draw()

    def test_worker_error(self):
        self.kx.opora_draw()
        with open(os.path.join(self.kx.draw_workdir, "result.json"), "w", encoding="utf-8") as f:
            json.dump({"items": [{"key": str(self.kx.id), "error": "чертёж не построен: тест"}]}, f)
        info = self.kx.opora_draw_state()
        self.assertEqual((info["state"], info["error"]), ("error", "чертёж не построен: тест"))
