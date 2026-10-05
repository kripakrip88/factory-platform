# -*- coding: utf-8 -*-
"""Слово «расчёт» вместо «спецификации» (разбор UX, шаг 39), pmk_calc.

Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
    odoo -d pmk39_test -i pmk_calc --test-enable \\
         --test-tags /pmk_calc:TestStep39Words --stop-after-init --http-port 8099

Что проверяем:
  • имя модели, изделия, подписи полей «Расчёт», заголовки формы и списка,
    подсказка пустого экрана — без «спецификации» (на заводе это чертёж
    клиента);
  • запись истории о создании (tools/tracking_ru.py, renamed_created):
    «Создано: Спецификация металлопроката» → «Создано: Расчёт
    металлопроката», английская «… created» — тоже, чужое и текст клиента
    не трогаются, повтор ничего не меняет;
  • миграция 19.0.1.0.5 на настоящих телах: правит только записи о создании
    расчётов, имя нумератора СМ- — только если стоит прежнее.
"""
import importlib.util
import re

from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_path

from odoo.addons.pmk_calc.tools.tracking_ru import RENAMED_MODELS, renamed_created

SPEC = re.compile(r"спецификац", re.I)
OLD = "<p>Создано: Спецификация металлопроката</p>"
NEW = "<p>Создано: Расчёт металлопроката</p>"


@tagged("post_install", "-at_install")
class TestStep39Words(TransactionCase):

    def _migration(self):
        path = file_path("pmk_calc/migrations/19.0.1.0.5/post-migrate.py")
        spec = importlib.util.spec_from_file_location("pmk_calc_migration_19_0_1_0_5", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.migrate

    # ─── Имена и подписи ────────────────────────────────────────────────
    def test_model_and_field_names(self):
        Model = self.env["ir.model"]
        self.assertEqual(Model._get("pmk.metal.spec").name, "Расчёт металлопроката")
        self.assertEqual(Model._get("pmk.metal.spec.product").name, "Изделие расчёта")
        for model in ("pmk.metal.spec.product", "pmk.metal.spec.line"):
            with self.subTest(model=model):
                self.assertEqual(self.env[model].fields_get(["spec_id"], ["string"])["spec_id"]["string"],
                                 "Расчёт")
        for model in ("pmk.metal.spec", "pmk.metal.spec.product", "pmk.metal.spec.line"):
            for fname, desc in self.env[model].fields_get([], ["string", "help"]).items():
                for attr in ("string", "help"):
                    text = desc.get(attr) or ""
                    with self.subTest(model=model, field=fname, attr=attr):
                        self.assertFalse(SPEC.search(text), text)

    def test_views_and_help(self):
        Spec = self.env["pmk.metal.spec"]
        views = Spec.get_views([(self.env.ref("pmk_calc.view_metal_spec_form").id, "form"),
                                (self.env.ref("pmk_calc.view_metal_spec_list").id, "list")])["views"]
        self.assertEqual(etree.fromstring(views["form"]["arch"]).get("string"), "Расчёт")
        self.assertEqual(etree.fromstring(views["list"]["arch"]).get("string"), "Расчёты")
        action = self.env["ir.actions.act_window"]._for_xml_id("pmk_calc.action_metal_spec")
        self.assertIn("Расчёт состоит из изделий", action["help"])
        self.assertFalse(SPEC.search(action["help"] or ""))

    def test_new_record_creation_message(self):
        """Новая запись о создании — уже с новым именем модели."""
        spec = self.env["pmk.metal.spec"].with_context(lang="en_US").create({})
        self.env.flush_all()
        bodies = [str(m.body) for m in spec.message_ids]
        self.assertTrue(any("Расчёт металлопроката" in body for body in bodies), bodies)
        self.assertFalse(any(SPEC.search(body) for body in bodies), bodies)

    # ─── История: запись о создании ─────────────────────────────────────
    def test_renamed_created_samples(self):
        self.assertEqual(renamed_created(OLD), NEW)
        self.assertEqual(renamed_created(NEW), NEW, "Повтор ничего не меняет.")
        self.assertEqual(renamed_created("<p>Спецификация металлопроката created</p>"), NEW,
                         "Английская запись — сначала по-русски (шаг 30), потом новое имя.")
        self.assertEqual(renamed_created("<p>Создано: Изделие спецификации</p>"),
                         "<p>Создано: Изделие расчёта</p>")
        for body in ("<p>Создано: Заказ доборных элементов</p>",
                     "<p>Создано: Спецификация металлопроката КМ1</p>",
                     "<div><b>Добавлено:</b> МК по КМ1 — весь объём спецификации</div>",
                     "<p>Создано: Спецификация металлопроката</p> и текст",
                     ""):
            with self.subTest(body=body):
                self.assertEqual(renamed_created(body), body, "Не запись о создании целиком.")
        self.assertIsNone(renamed_created(None))
        self.assertEqual(set(RENAMED_MODELS.values()),
                         {self.env["ir.model"]._get(m).name for m in ("pmk.metal.spec", "pmk.metal.spec.product")},
                         "Новые имена — те, что у моделей сейчас.")

    def test_migration(self):
        spec = self.env["pmk.metal.spec"].create({})
        other = self.env["pmk.metal.spec"].create({})
        Message = self.env["mail.message"]

        def note(record, body):
            return Message.create({"model": record._name, "res_id": record.id,
                                   "message_type": "notification", "body": body})

        created = note(spec, OLD)
        customer = note(other, "<div><b>Добавлено:</b> МК по КМ1 — весь объём спецификации</div>")
        partner = self.env["res.partner"].create({"name": "Не расчёт"})
        foreign = note(partner, OLD)
        sequence = self.env.ref("pmk_calc.seq_metal_spec")
        sequence.name = "Спецификация металлопроката"
        self.env.flush_all()

        migrate = self._migration()
        migrate(self.env.cr, "19.0.1.0.4")
        self.env.invalidate_all()
        # История на боевой не переписывается (по слову Антона — отдельно).
        self.assertEqual(str(created.body), OLD, "История расчёта — как была.")
        self.assertIn("спецификации", str(customer.body), "Чертёж клиента — как был.")
        self.assertEqual(str(foreign.body), OLD)
        self.assertEqual(sequence.name, "Расчёт металлопроката")
        self.assertEqual(sequence.prefix, "СМ-", "Номер документа не тронут.")

        sequence.name = "Своё имя"
        self.env.flush_all()
        migrate(self.env.cr, "19.0.1.0.4")
        self.env.invalidate_all()
        self.assertEqual(sequence.name, "Своё имя", "Ручная правка цела.")
        self.assertEqual(str(created.body), OLD, "Повтор ничего не меняет.")
