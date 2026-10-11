# -*- coding: utf-8 -*-
"""Объединение клиентов: сравнить и не потерять (шаг З-17) — правила без базы.

Обычный unittest, как test_partner_keys_rules.py: tools/merge_rules.py —
чистые функции, гоняются голым питоном до всякой выкладки:

    python3 experiments/odoo/addons/pmk_partner/tests/test_merge_rules.py

Через модель — test_z17_merge.py. Значения группы «А ГРУПП» (карточки 9,
20, 44) — с боевой базы 11.10.2026 (SELECT по res_partner).
"""

import os
import sys
import unittest

try:
    from ..tools import merge_rules
except (ImportError, ValueError):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from tools import merge_rules


class TestInn(unittest.TestCase):

    def test_inn_key(self):
        self.assertEqual(merge_rules.inn_key("RU7717625418"), "7717625418")
        self.assertEqual(merge_rules.inn_key(" 7717 625 418 "), "7717625418")
        self.assertEqual(merge_rules.inn_key("de 123"), "DE123")
        self.assertEqual(merge_rules.inn_key(False), "")
        self.assertEqual(merge_rules.inn_key("  "), "")

    def test_conflict(self):
        rows = [{"id": 9, "name": "А ГРУПП МАРКЕТ", "vat": "7717625418"},
                {"id": 20, "name": "А ГРУПП", "vat": False},
                {"id": 44, "name": "А-ГРУПП", "vat": "2721073821"}]
        self.assertEqual(merge_rules.inn_conflict(rows),
                         [("7717625418", ["А ГРУПП МАРКЕТ"]), ("2721073821", ["А-ГРУПП"])])

    def test_no_conflict(self):
        self.assertEqual(merge_rules.inn_conflict([
            {"id": 9, "name": "А", "vat": "7717625418"},
            {"id": 20, "name": "Б", "vat": False}]), [], "ИНН только у одной.")
        self.assertEqual(merge_rules.inn_conflict([
            {"id": 9, "name": "А", "vat": "7717625418"},
            {"id": 20, "name": "Б", "vat": "RU 7717625418"}]), [], "Один ИНН, разная запись.")
        self.assertEqual(merge_rules.inn_conflict([]), [])


class TestDestination(unittest.TestCase):

    def test_inn_first(self):
        rows = [{"id": 9, "inn": "7717625418", "docs": 0, "active": True},
                {"id": 20, "inn": "", "docs": 3, "active": True}]
        self.assertEqual(merge_rules.pick_destination(rows),
                         {"dst": 9, "reason": "inn", "runner": 20})

    def test_docs_then_active_then_oldest(self):
        rows = [{"id": 18, "inn": "", "docs": 1, "active": False},
                {"id": 159, "inn": "", "docs": 0, "active": True}]
        self.assertEqual(merge_rules.pick_destination(rows)["dst"], 18, "Документы главнее архива.")
        self.assertEqual(merge_rules.pick_destination(rows)["reason"], "docs")
        rows = [{"id": 20, "inn": "", "docs": 0, "active": False},
                {"id": 44, "inn": "", "docs": 0, "active": True}]
        self.assertEqual(merge_rules.pick_destination(rows),
                         {"dst": 44, "reason": "active", "runner": 20})
        rows = [{"id": 44, "inn": "", "docs": 0, "active": True},
                {"id": 20, "inn": "", "docs": 0, "active": True}]
        self.assertEqual(merge_rules.pick_destination(rows),
                         {"dst": 20, "reason": "oldest", "runner": 44})

    def test_group_a(self):
        """«А ГРУПП»: ИНН только у 9, 20 и 44 в архиве, документов нет."""
        rows = [{"id": 44, "inn": "", "docs": 0, "active": False},
                {"id": 9, "inn": "7717625418", "docs": 0, "active": True},
                {"id": 20, "inn": "", "docs": 0, "active": False}]
        self.assertEqual(merge_rules.pick_destination(rows)["dst"], 9)

    def test_edge(self):
        self.assertEqual(merge_rules.pick_destination([])["dst"], False)
        one = merge_rules.pick_destination([{"id": 5, "inn": "", "docs": 0, "active": True}])
        self.assertEqual(one, {"dst": 5, "reason": "", "runner": False})


class TestCarry(unittest.TestCase):

    def test_final_values_like_core(self):
        dst = {"phone": "", "email": "dst@x.ru"}
        srcs = [{"phone": "1", "email": "a@x.ru"}, {"phone": "2", "email": ""}]
        self.assertEqual(merge_rules.final_values(dst, srcs, ["phone", "email"]),
                         {"phone": "2", "email": "dst@x.ru"},
                         "Назначение главнее, пустое — последнее непустое из исходных.")

    def test_value_keys(self):
        key = merge_rules.value_key
        self.assertEqual(key("phone", "8-800-302-07-07"), key("phone", "+7 (800) 302 07 07"))
        self.assertEqual(key("email", " Info@AG.market "), "info@ag.market")
        self.assertEqual(key("email", "b@y.ru; a@x.ru"), key("email", "a@x.ru, b@y.ru"))
        self.assertEqual(key("website", "https://www.agrupp.com/"), "agrupp.com")
        self.assertEqual(key("comment", "<p>Что&nbsp;возит:  лист</p>"), "что возит: лист")
        self.assertEqual(key("phone", False), "")

    def test_group_a_plan(self):
        """9 остаётся; у 20 и 44 одинаковый адрес для прайса info@ag.market —
        переносится один раз; примечания у всех разные — оба переносятся;
        телефон тот же — не переносится."""
        dst_final = {"phone": "8-800-302-07-07", "email": False, "website": "agrupp.com",
                     "pmk_price_email": "avlukina@agrupp.com",
                     "comment": "<p>Металлобаза, Москва</p>"}
        srcs = [
            {"id": 20, "name": "А ГРУПП", "phone": "8 (800) 302-07-07", "email": False,
             "website": "https://agrupp.com/", "pmk_price_email": "info@ag.market",
             "comment": "<p>Что возит: трубы</p>"},
            {"id": 44, "name": "А-ГРУПП", "phone": "88003020707", "email": False,
             "website": "ag.market", "pmk_price_email": "INFO@ag.market",
             "comment": "<p>Направление поиска: лист</p>"},
        ]
        plan = merge_rules.carry_plan(dst_final, srcs)
        self.assertEqual([item["id"] for item in plan], [20, 44])
        self.assertEqual(plan[0]["contact"], {}, "Телефон тот же — контакт не нужен.")
        self.assertEqual(plan[0]["note"], [("Адрес для запроса прайса", "info@ag.market")],
                         "Сайт тот же (без схемы и косой).")
        self.assertEqual(plan[0]["comment"], "<p>Что возит: трубы</p>")
        self.assertEqual(plan[1]["note"], [("Сайт", "ag.market")], "Адрес для прайса уже перенесён.")
        self.assertEqual(plan[1]["comment"], "<p>Направление поиска: лист</p>")

    def test_contact_or_note(self):
        dst_final = {"phone": "+7 4212 11-11-11", "email": "office@x.ru"}
        srcs = [{"id": 2, "name": "Икс", "phone": "+7 4212 22-22-22", "email": "sale@x.ru"}]
        plan = merge_rules.carry_plan(dst_final, srcs, fields=[])
        self.assertEqual(plan[0]["contact"], {"phone": "+7 4212 22-22-22", "email": "sale@x.ru"})
        self.assertEqual(plan[0]["note"], [])
        person = merge_rules.carry_plan(dst_final, srcs, fields=[], company=False)
        self.assertEqual(person[0]["contact"], {})
        self.assertEqual(person[0]["note"], [("Телефон", "+7 4212 22-22-22"),
                                             ("Эл. почта", "sale@x.ru")],
                         "У физлица контактных лиц нет — строкой примечания.")

    def test_children_known(self):
        dst_final = {"phone": "", "email": ""}
        srcs = [{"id": 2, "name": "Икс", "phone": "+7 4212 22-22-22", "email": "sale@x.ru"}]
        children = [{"phone": "84212222222", "email": "SALE@x.ru"}]
        self.assertEqual(merge_rules.carry_plan(dst_final, srcs, children, fields=[]), [],
                         "Телефон и почта уже у контактного лица — не дублируем.")

    def test_comment_already_inside(self):
        dst_final = {"comment": "<p>Старое</p><p>Из объединения: Что возит: трубы</p>"}
        srcs = [{"id": 2, "name": "Икс", "comment": "<p>Что возит: трубы</p>"}]
        self.assertEqual(merge_rules.carry_plan(dst_final, srcs, fields=[]), [],
                         "Повторное объединение не копит одно примечание дважды.")

    def test_nothing_left(self):
        self.assertEqual(merge_rules.carry_plan({"phone": "1"}, [{"id": 2, "name": "Икс"}]), [])


if __name__ == "__main__":
    unittest.main()
