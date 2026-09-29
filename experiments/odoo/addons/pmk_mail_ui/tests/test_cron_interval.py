# -*- coding: utf-8 -*-
"""Синхронизация почты закреплена на 2 минутах (data/ir_cron.xml, шаг 22).

До 30.09.2026 стояло 10: без защиты от наложения заходы крона и кнопки
«Синхронизировать» налезали друг на друга и клали ящик в error (27.09).
Защита — блокировка ящика на проход (mail_client/tests/test_sync_lock.py).
Чаще 2 минут не ставим: как часто mail.ru пускает по IMAP, неизвестно. Тест
ловит и возврат к 10, и «ускорение» до минуты без решения.
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCronInterval(TransactionCase):

    def test_sync_cron_runs_every_two_minutes(self):
        cron = self.env.ref("mail_client.ir_cron_mail_client_sync")
        self.assertEqual((cron.interval_number, cron.interval_type), (2, "minutes"))
