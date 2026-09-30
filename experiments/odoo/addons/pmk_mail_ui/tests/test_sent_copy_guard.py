# -*- coding: utf-8 -*-
"""Предохранитель копии в «Отправленные» (разбор UX, шаг 33).

Копия исходящего письма ложится в IMAP-папку «Отправленные» ящика
(models/ir_mail_server.py). В тестах и при загрузке реестра ядро письмо не
отправляет, но подшивка шла дальше — в настоящий ящик. На копии боевой базы
оба ящика подключены, и тестовое письмо легло бы в «Отправленные»
pmkpark@mail.ru.

Самое коварное место — штатная заглушка почты в тестах
(mock_smtplib_connection): чтобы прогнать поддельный SMTP, она подменяет
_disable_send на False. Здесь ровно этот случай: SMTP поддельный, а
IMAP-подключение ящика подменено счётчиком — он не должен сработать.

Гонять ТОЛЬКО на одноразовой базе (см. tests/__init__.py).
"""
from unittest.mock import MagicMock, patch

from odoo.addons.base.tests.common import MockSmtplibCase
from odoo.tests import TransactionCase, tagged

BOX = "kp.box@example.org"


@tagged("post_install", "-at_install")
class TestSentCopyGuard(TransactionCase, MockSmtplibCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = cls.env["mail.client.server"].create({
            "name": "mailcow", "imap_host": "mail.example.org",
            "auth_mode": "master", "master_user": "master",
        })
        cls.account = cls.env["mail.client.account"].create({
            "name": "Ящик завода (тест)", "email": BOX, "server_id": cls.server.id,
        })
        cls.sent_folder = cls.env["mail.client.folder"].create({
            "name": "Отправленные", "account_id": cls.account.id,
            "imap_path": "Отправленные", "role": "sent",
        })
        cls.env["ir.mail_server"].create({
            "name": "Ящик завода (тест)", "smtp_host": "localhost", "from_filter": BOX,
        })

    def _message(self):
        return self.env["ir.mail_server"]._build_email__(
            '"Антон Карнеев" <%s>' % BOX, ["client@example.com"],
            "Коммерческое предложение СМ-00001", "<p>Здравствуйте!</p>",
            subtype="html")

    def test_no_imap_during_tests_even_with_fake_smtp(self):
        connection = MagicMock()
        account_cls = type(self.env["mail.client.account"])
        with self.mock_smtplib_connection(), \
             patch.object(account_cls, "_open_connection", autospec=True,
                          return_value=connection) as opened:
            self.env["ir.mail_server"].send_email(self._message())
        self.assertEqual(len(self.emails), 1, "Поддельный SMTP письмо получил.")
        opened.assert_not_called()
        connection.append.assert_not_called()

    def test_filing_itself_still_works(self):
        """Сама подшивка не сломана: вызванная напрямую, кладёт письмо в
        папку «Отправленные» ящика отправителя (IMAP — заглушка)."""
        connection = MagicMock()
        account_cls = type(self.env["mail.client.account"])
        with patch.object(account_cls, "_open_connection", autospec=True,
                          return_value=connection):
            filed = self.env["ir.mail_server"]._pmk_file_to_sent(self._message())
        self.assertTrue(filed)
        connection.append.assert_called_once()
        self.assertEqual(connection.append.call_args[0][0], "Отправленные")

    def test_guard_says_disabled_in_tests(self):
        self.assertTrue(self.env["ir.mail_server"]._pmk_sent_copy_disabled())
