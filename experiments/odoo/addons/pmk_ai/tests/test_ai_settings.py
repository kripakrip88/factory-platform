# -*- coding: utf-8 -*-
"""Настройки ассистента (17.10.2026): проверка связи без сети — ответ API подменён."""
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

from ..tools import claude


def _resp(status, body):
    r = MagicMock(status_code=status)
    r.json.return_value = body
    return r


@tagged("post_install", "-at_install")
class TestAiSettings(TransactionCase):

    def _check(self, response):
        settings = self.env["res.config.settings"].create({"pmk_ai_api_key": "sk-ant-test"})
        with patch.object(claude, "_http") as http:
            http.return_value.post.return_value = response
            return settings.action_pmk_ai_check()

    def test_ok(self):
        action = self._check(_resp(200, {"model": "claude-sonnet-5-5", "content": [{"type": "text", "text": "Да"}],
                                         "usage": {"input_tokens": 20, "output_tokens": 2}}))
        self.assertEqual(action["params"]["type"], "success")
        self.assertIn("Связь есть: «Да»", action["params"]["message"])
        self.assertEqual(self.env["ir.config_parameter"].get_param("pmk_ai.api_key"), "sk-ant-test")
        self.assertIn("Связь есть", self.env["ir.config_parameter"].get_param("pmk_ai.last_status"))

    def test_bad_key_is_human(self):
        action = self._check(_resp(401, {"type": "error", "error": {"type": "authentication_error",
                                                                     "message": "invalid x-api-key"}}))
        self.assertEqual(action["params"]["type"], "danger")
        self.assertIn("Ключ не принят", action["params"]["message"])

    def test_no_key(self):
        with self.assertRaises(claude.ClaudeError):
            claude.messages("", {})
