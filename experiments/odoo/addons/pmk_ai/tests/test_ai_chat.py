# -*- coding: utf-8 -*-
"""Панель ассистента (18.10.2026): цикл инструментов, лимит, расход, права — без сети."""
from unittest.mock import patch

from odoo.tests import TransactionCase, new_test_user, tagged

from ..models import ai_chat


def _text(text, usage=(100, 20)):
    return ({"content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
             "usage": {"input_tokens": usage[0], "output_tokens": usage[1]}}, 1.0)


@tagged("post_install", "-at_install")
class TestAiChat(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("pmk_ai.api_key", "sk-test")
        params.set_param("pmk_ai.budget", "100")
        params.set_param("pmk_ai.price_in", "3")
        params.set_param("pmk_ai.price_out", "15")
        cls.Chat = cls.env["pmk.ai.chat"]
        cls.partner = cls.env["res.partner"].create({"name": "ООО ДальТест (ассистент)", "is_company": True})

    def test_answer_and_usage(self):
        with patch.object(ai_chat.claude, "messages", return_value=_text("Привет")) as call:
            res = self.Chat.ask("тест", [], {})
        self.assertEqual(res["answer"], "Привет")
        payload = call.call_args[0][1]
        self.assertIn("ПМК Парк", payload["system"], "Ядро знаний — в системной подсказке.")
        self.assertEqual({t["name"] for t in payload["tools"]}, {"search_records", "read_record", "supplier_prices"})
        usage = self.env["pmk.ai.usage"].search([], limit=1)
        self.assertEqual((usage.input_tokens, usage.output_tokens, usage.calls), (100, 20, 1))
        self.assertAlmostEqual(usage.cost, (100 * 3 + 20 * 15) / 1e6, places=6)
        self.assertEqual(res["status"]["questions"], self.Chat.get_status()["questions"])

    def test_tool_loop_reads_as_user(self):
        tool = ({"content": [{"type": "tool_use", "id": "t1", "name": "search_records",
                              "input": {"kind": "partner", "text": "ДальТест"}}],
                 "stop_reason": "tool_use", "usage": {"input_tokens": 50, "output_tokens": 10}}, 1.0)
        with patch.object(ai_chat.claude, "messages", side_effect=[tool, _text("Нашёл")]) as call:
            res = self.Chat.ask("найди ДальТест", [], {})
        self.assertEqual(res["answer"], "Нашёл")
        second = call.call_args_list[1][0][1]["messages"][-1]["content"][0]
        self.assertEqual(second["type"], "tool_result")
        self.assertIn("ООО ДальТест (ассистент)", second["content"])
        self.assertIn('"id": %d' % self.partner.id, second["content"])

    def test_screen_context_in_system(self):
        with patch.object(ai_chat.claude, "messages", return_value=_text("ок")) as call:
            self.Chat.ask("что это?", [], {"model": "res.partner", "id": self.partner.id})
        self.assertIn("Открыт документ", call.call_args[0][1]["system"])
        self.assertIn("ООО ДальТест (ассистент)", call.call_args[0][1]["system"])

    def test_budget_guard(self):
        self.env["ir.config_parameter"].sudo().set_param("pmk_ai.budget", "0")
        with patch.object(ai_chat.claude, "messages") as call:
            res = self.Chat.ask("тест", [], {})
        call.assert_not_called()
        self.assertIn("Лимит месяца исчерпан", res["error"])

    def test_no_key(self):
        self.env["ir.config_parameter"].sudo().set_param("pmk_ai.api_key", "")
        res = self.Chat.ask("тест", [], {})
        self.assertIn("не подключён", res["error"])

    def test_api_error_is_logged_not_raised(self):
        with patch.object(ai_chat.claude, "messages", side_effect=ai_chat.claude.ClaudeError("нет связи")):
            res = self.Chat.ask("тест", [], {})
        self.assertEqual(res["error"], "нет связи")
        self.assertFalse(self.env["pmk.ai.usage"].search([], limit=1).ok)

    def test_tools_respect_access(self):
        user = new_test_user(self.env, login="pmk_ai_portal", groups="base.group_portal")
        chat = self.Chat.with_user(user)
        # Без pmk_calc в одноразовой базе раздела нет вовсе; с ним — портальному нет доступа.
        self.assertIn(chat._tool_search("spec", "", 5).get("ошибка"), ("нет доступа", "раздел не установлен"))
        self.assertEqual(chat._run_tool("read_record", {"model": "res.users", "id": 1})["ошибка"],
                         "этот раздел ассистенту не открыт")

    def test_unknown_tool(self):
        self.assertIn("ошибка", self.Chat._run_tool("delete_everything", {}))
