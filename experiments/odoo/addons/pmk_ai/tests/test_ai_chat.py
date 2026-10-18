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
        params.set_param("pmk_ai.worker_alive", "%.0f" % __import__("time").time())
        params.set_param("pmk_ai.api_key", "sk-test")
        params.set_param("pmk_ai.budget", "100")
        params.set_param("pmk_ai.price_in", "3")
        params.set_param("pmk_ai.price_out", "15")
        cls.Chat = cls.env["pmk.ai.chat"]
        cls.partner = cls.env["res.partner"].create({"name": "ООО ДальТест (ассистент)", "is_company": True})

    def test_answer_and_usage(self):
        with patch.object(ai_chat.claude, "messages", return_value=_text("Привет")) as call:
            res = self.Chat._answer("тест", [], {})
        self.assertEqual(res["answer"], "Привет")
        payload = call.call_args[0][1]
        self.assertIn("ПМК Парк", payload["system"], "Ядро знаний — в системной подсказке.")
        self.assertEqual({t["name"] for t in payload["tools"]}, {"search_records", "summary", "read_record", "partner_overview", "supplier_prices"})
        usage = self.env["pmk.ai.usage"].search([], limit=1)
        self.assertEqual((usage.input_tokens, usage.output_tokens, usage.calls), (100, 20, 1))
        self.assertAlmostEqual(usage.cost, (100 * 3 + 20 * 15) / 1e6, places=6)

    def test_tool_loop_reads_as_user(self):
        tool = ({"content": [{"type": "tool_use", "id": "t1", "name": "search_records",
                              "input": {"kind": "partner", "text": "ДальТест"}}],
                 "stop_reason": "tool_use", "usage": {"input_tokens": 50, "output_tokens": 10}}, 1.0)
        with patch.object(ai_chat.claude, "messages", side_effect=[tool, _text("Нашёл")]) as call:
            res = self.Chat._answer("найди ДальТест", [], {})
        self.assertEqual(res["answer"], "Нашёл")
        second = call.call_args_list[1][0][1]["messages"][-1]["content"][0]
        self.assertEqual(second["type"], "tool_result")
        self.assertIn("ООО ДальТест (ассистент)", second["content"])
        self.assertIn('"id": %d' % self.partner.id, second["content"])

    def test_screen_context_in_system(self):
        with patch.object(ai_chat.claude, "messages", return_value=_text("ок")) as call:
            self.Chat._answer("что это?", [], {"model": "res.partner", "id": self.partner.id})
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
            res = self.Chat._answer("тест", [], {})
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

    def test_last_call_forces_answer(self):
        tool = ({"content": [{"type": "tool_use", "id": "t", "name": "search_records",
                              "input": {"kind": "partner", "text": "ДальТест"}}],
                 "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5}}, 1.0)
        calls = []

        def fake(key, payload, base=None):
            calls.append(dict(payload))
            if payload.get("tool_choice"):
                return _text("Итог")
            return tool
        with patch.object(ai_chat.claude, "messages", side_effect=fake):
            res = self.Chat._answer("тест", [], {})
        self.assertEqual(res["answer"], "Итог", "Последний заход — ответ, а не обрывок сбора данных.")
        self.assertEqual(len(calls), ai_chat.MAX_CALLS)
        self.assertEqual(self.env["pmk.ai.usage"].search([], limit=1).answer, "Итог")

    def test_partner_overview_and_clean_card(self):
        res = self.Chat._run_tool("partner_overview", {"id": self.partner.id})
        self.assertEqual(res["контрагент"], "ООО ДальТест (ассистент)")
        card = self.Chat._brief("res.partner", self.partner.id)
        self.assertFalse({"Черный список", "Есть сообщение", "Has Message"} & set(card),
                         "Служебных полей Odoo в карточке нет.")

    # ─── очередь и фоновый процесс (правило «не тормозить систему», 18.10) ──
    def test_queue_roundtrip(self):
        queued = self.Chat.ask("вопрос в очередь", [{"role": "user", "text": "раньше"}], {"title": "СМ-1"})
        self.assertIn("request_id", queued, "Страница только ставит вопрос в очередь.")
        self.assertEqual(self.Chat.poll(queued["request_id"])["state"], "queued")
        again = self.Chat.ask("второй", [], {})
        self.assertIn("ещё отвечает", again["error"], "У одного человека — один вопрос за раз.")
        ids = self.Chat._worker_tick(4)
        self.assertIn(queued["request_id"], ids)
        self.assertEqual(self.Chat.poll(queued["request_id"])["state"], "running")
        with patch.object(ai_chat.claude, "messages", return_value=_text("Готово")) as call:
            self.Chat._process_request(queued["request_id"])
        self.assertEqual(call.call_args[0][1]["messages"][0]["content"], "раньше", "История доехала.")
        done = self.Chat.poll(queued["request_id"])
        self.assertEqual((done["state"], done["answer"]), ("done", "Готово"))
        self.assertEqual(self.env["pmk.ai.usage"].search([], limit=1).screen, "СМ-1")

    def test_poll_only_own(self):
        queued = self.Chat.ask("мой вопрос", [], {})
        other = new_test_user(self.env, login="pmk_ai_other", groups="base.group_user")
        self.assertEqual(self.Chat.with_user(other).poll(queued["request_id"])["state"], "error")

    def test_worker_not_running(self):
        self.env["ir.config_parameter"].sudo().set_param("pmk_ai.worker_alive", "0")
        self.assertIn("не запущен", self.Chat.ask("тест", [], {})["error"])


    def test_summary_and_stage_filter(self):
        for i in range(3):
            self.env["res.partner"].create({"name": "Сводка %d (ассистент)" % i, "is_company": True, "city": "Хабаровск"})
        res = self.Chat._run_tool("search_records", {"kind": "partner", "text": "Сводка", "limit": 2})
        self.assertEqual((res["всего в базе по отбору"], res["показано"]), (3, 2))
        self.assertIn("подсказка", res, "Показаны не все — ассистент узнаёт об этом.")
        summary = self.Chat._run_tool("summary", {"kind": "partner", "group_by": "user"})
        self.assertGreaterEqual(summary["всего"], 4)
        self.assertIn("ошибка", self.Chat._run_tool("summary", {"kind": "product", "group_by": "stage"}))

    def test_rate_own_answer(self):
        with patch.object(ai_chat.claude, "messages", return_value=_text("ок")):
            res = self.Chat._answer("тест", [], {})
        self.assertTrue(self.Chat.rate(res["usage_id"], "bad", "неполно"))
        usage = self.env["pmk.ai.usage"].browse(res["usage_id"])
        self.assertEqual((usage.rating, usage.feedback), ("bad", "неполно"))
        other = new_test_user(self.env, login="pmk_ai_rater", groups="base.group_user")
        self.assertFalse(self.Chat.with_user(other).rate(res["usage_id"], "good"), "Только свой ответ.")
