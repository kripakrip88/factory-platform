# -*- coding: utf-8 -*-
"""Страница входа ПМК (15.10.2026): внутренняя система планирования заказов,
завод металлоконструкций по всему ДВ, ссылка на pmkpark.ru; без шапки и подвала
сайта, без Passkey и «Powered by Odoo»."""
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestLoginPage(HttpCase):

    def test_login_page(self):
        response = self.url_open("/web/login")
        self.assertEqual(response.status_code, 200)
        html = response.text
        for text in ("Вход для сотрудников", "Планирование заказов", "Дальнему Востоку",
                     "https://pmkpark.ru", "Эл. почта", "Пароль", "Войти", "pmk-login"):
            with self.subTest(text=text):
                self.assertIn(text, html)
        self.assertNotIn("Powered by", html)
        self.assertNotIn("About us", html)
