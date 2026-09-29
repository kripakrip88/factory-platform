# -*- coding: utf-8 -*-
"""Синхронизация почты закреплена на 10 минутах (data/ir_cron.xml).

При «раз в 2 минуты» заходы налезали друг на друга и клали ящик в error
(27.09.2026). Тест ловит возврат к значению автора модуля почты.
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCronInterval(TransactionCase):

    def test_sync_cron_runs_every_ten_minutes(self):
        cron = self.env.ref("mail_client.ir_cron_mail_client_sync")
        self.assertEqual((cron.interval_number, cron.interval_type), (10, "minutes"))
