import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mailindex import quotes  # noqa: E402
from mailindex.threads import norm_subject  # noqa: E402


class Quotes(unittest.TestCase):
    def test_mailru_web(self):
        t = ("Добрый день! Счёт во вложении.\n\nС уважением,\nИван Петров\nменеджер\n+7 914 000-00-00\n\n"
             "Понедельник, 17 ноября 2026, 10:14 +10:00 от Клиент <c@x.ru>:\n> Пришлите счёт\n")
        r = quotes.split(t)
        self.assertEqual(r["kind"], "quote")
        self.assertIn("Счёт во вложении", r["new"])
        self.assertNotIn("Иван Петров", r["new"])
        self.assertIn("Иван Петров", r["signature"])
        self.assertNotIn("+7 914", r["new"])
        self.assertIn("+7 914", r["signature"])
        self.assertIn("Пришлите счёт", r["quote"])

    def test_gmail_ru_wrapped(self):
        t = "Ок, берём.\n\nпн, 17 нояб. 2026 г. в 10:14, Иван Петров <\nivan@pmkpark.ru>:\n\n> Цена 100 руб.\n"
        r = quotes.split(t)
        self.assertEqual(r["kind"], "quote")
        self.assertEqual(r["new"], "Ок, берём.")

    def test_outlook(self):
        t = ("Согласовано.\n\nОт: Иван <i@pmkpark.ru>\nОтправлено: 17 ноября 2026 г. 10:14\nКому: a@b.ru\n"
             "Тема: КП\n\nКП во вложении")
        r = quotes.split(t)
        self.assertEqual(r["kind"], "quote")
        self.assertEqual(r["new"], "Согласовано.")

    def test_dotted_date(self):
        t = 'Спасибо\n\n17.11.2026, 10:14, "Иван" <i@pmkpark.ru>:\n> текст'
        self.assertEqual(quotes.split(t)["new"], "Спасибо")

    def test_inline(self):
        t = ("Отвечаю по пунктам:\n\n> 1. Сроки?\n10 дней.\n> 2. Доставка?\nСамовывоз.\n")
        r = quotes.split(t)
        self.assertEqual(r["kind"], "inline")
        self.assertIn("10 дней", r["new"])
        self.assertIn("Сроки", r["new"])

    def test_forward(self):
        t = "Посмотрите заявку.\n\n-------- Пересылаемое сообщение --------\nОт: c@x.ru\nНужны закладные 40 шт"
        r = quotes.split(t)
        self.assertEqual(r["kind"], "forward")
        self.assertIn("закладные", r["new"])

    def test_mobile_footer(self):
        t = "Да, подойдёт\n\nОтправлено из мобильной Почты Mail.ru"
        self.assertEqual(quotes.split(t)["new"], "Да, подойдёт")

    def test_plain_no_quote(self):
        t = "Здравствуйте! Нужен расчёт навеса 6х12."
        r = quotes.split(t)
        self.assertEqual((r["kind"], r["new"]), ("", t))

    def test_long_signature_kept(self):
        # «С уважением» в середине длинного текста — не подпись
        body = "\n".join("строка %d" % i for i in range(40))
        t = "С уважением относимся к срокам.\n" + body
        self.assertIn("строка 39", quotes.split(t)["new"])

    def test_yandex_header(self):
        t = ("Посчитайте доставку.\n\n\\--\n\nКому: \"Валерий\" <v@ya.ru>;\nТема: зонты;\n"
             "02:55, 17 ноября 2026 г., \"Владимир\" <pmkpark@mail.ru>:\n> Здравствуйте")
        r = quotes.split(t)
        self.assertEqual(r["new"], "Посчитайте доставку.")

    def test_first_level(self):
        q = ("> От кого: Владимир <pmkpark@mail.ru>\n> Кому: Ольга <o@x.ru>\n> Дата: Вторник, 20 октября 2026, 09:05\n"
             "> Здравствуйте.\n> Хорошо\n>\n> С Уважением,\n> Голубенко\n>\n"
             ">> Вторник, 20 октября 2026, 16:00 +10:00 от Ольга <o@x.ru\n>> >:\n>> когда готов заказ?")
        body, deeper = quotes.first_level(q)
        self.assertEqual(body, "Здравствуйте.\nХорошо")
        self.assertTrue(deeper)

    def test_mailru_wrapped_header(self):
        q = ("Пятница, 13 ноября 2026, 16:39 +10:00 от Валерий <v@ya.ru\n> >:\n> Карточка во вложении.\n> --\n> Валерий")
        body, _ = quotes.first_level(q)
        self.assertEqual(body, "Карточка во вложении.")

    def test_subject(self):
        self.assertEqual(norm_subject("RE: Fwd: Re[2]: КП на закладные"), "кп на закладные")
        self.assertEqual(norm_subject("Ответ: Пересл: Заявка"), "заявка")


if __name__ == "__main__":
    unittest.main()
