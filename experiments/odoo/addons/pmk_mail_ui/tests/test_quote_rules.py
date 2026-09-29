# -*- coding: utf-8 -*-
"""Свёрнутые цитаты «···» (шаг 20, В2) — правила без базы.

Обычный unittest, как test_asset_rules.py: tools/quote_fold.py — чистая
функция, тесты гоняются голым питоном до всякого деплоя:

    python3 experiments/odoo/addons/pmk_mail_ui/tests/test_quote_rules.py

Внутри Odoo обычный unittest-класс не запускается (нет test_tags), поэтому
ту же таблицу через модель прогоняет test_quote_fold.py.

Разметка — такой, какой её сохраняет html_sanitize (с data-o-mail-quote*,
кавычки в атрибутах, «<» и «>» в тексте — &lt; &gt;), обезличенная. Живые
письма базы (29.09.2026): mail.ru веб — 117, 15343, 57481, 57542; Outlook —
106, 57260 (шапка в лишнем <div>), 57479; Thunderbird — 125; Яндекс — 57501;
пересылки из приложения mail.ru — 89 и 95 (не сворачиваются).
"""

import html
import re
import time
import unittest

try:
    # Внутри Odoo — как odoo.addons.pmk_mail_ui.tools.quote_fold.
    from ..tools import quote_fold
except (ImportError, ValueError):
    # Голым питоном — как соседний пакет.
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from tools import quote_fold

fold_quotes = quote_fold.fold_quotes

MAILRU_QUOTE = (
    '<div class="mail-quote-collapse"><blockquote data-o-mail-quote-node="1" '
    'style="border-left:1px solid #0857A6;margin:10px;padding:0 0 0 10px">'
    '<span data-o-mail-quote="1">Понедельник, 21 сентября 2026, 09:54 +10:00 от '
    'zakaz@example.org:</span><br data-o-mail-quote="1">'
    '<div data-o-mail-quote="1">Просим прислать прайс на лист 4 мм.</div>'
    '<div data-o-mail-quote="1"><img src="cid:logo@x" alt=""></div>'
    '</blockquote></div>'
)

# (имя, письмо, тема, ожидаемое правило или None)
CASES = [
    # ---------------------------------------------------------------- mail.ru
    ("mail.ru веб",
     '<div class="cl-9in"><div>Добрый день, счёт во вложении.</div><br>'
     + MAILRU_QUOTE + '<br><div>С уважением, Иван<br>тел. +7 900 000-00-00</div></div>',
     "Re: Прайс", "mailru"),
    ("mail.ru веб, подпись после цитаты, своего текста нет (117)",
     '<div class="cl-9in"><br><br>' + MAILRU_QUOTE
     + '<br><div><strong>С уважением, ООО «Металл»</strong><br>тел. (4212) 00-00-00</div></div>',
     "Re: Прайс", "mailru"),
    ("mail.ru веб при пересылке — класс с _mr_css_attr",
     '<div>Ответ ниже.</div>' + MAILRU_QUOTE.replace(
         "mail-quote-collapse", "mail-quote-collapse_mr_css_attr"),
     "Re: Прайс", "mailru"),
    ("mail.ru приложение: ответ, шапка голым текстом остаётся",
     '<div id="composeWebView_editable_content"><div>Спасибо, получили.</div>'
     '<div id="mail-app-auto-signature">Отправлено из мобильной Почты Mail.ru</div>'
     '<br><br>Среда, 23 сентября 2026, 10:00 +10:00 от Иван &lt;ivan@example.org&gt;:<br>'
     '<div id="composeWebView_previouse_content"><blockquote id="mail-app-auto-quote" '
     'style="border-left: 1px solid #0077ff;">'
     '<div>Когда отгрузка?</div></blockquote></div></div>',
     "Re: Отгрузка", "mailru_app"),
    # ---------------------------------------------------------------- Outlook
    ("Outlook настольный, EN",
     '<div class="WordSection1"><p class="MsoNormal">Добрый день! Цены в магазине.</p>'
     '<p class="MsoNormal">&nbsp;</p>'
     '<div><div style="border:none;border-top:solid #E1E1E1 1.0pt;padding:3.0pt 0cm 0cm 0cm">'
     '<p class="MsoNormal"><b>From:</b> zakaz@example.org &lt;zakaz@example.org&gt;<br>'
     '<b>Sent:</b> Monday, September 21, 2026 9:55 AM<br><b>To:</b> Иван &lt;ivan@example.org&gt;<br>'
     '<b>Subject:</b> Запрос прайс-листа</p></div></div>'
     '<p class="MsoNormal">&nbsp;</p><p class="MsoNormal">Просим прислать прайс.</p></div>',
     "RE: Запрос прайс-листа", "outlook"),
    ("Outlook настольный, RU, шапка без обёртки",
     '<div class="WordSection1"><p class="MsoNormal">Спасибо, ждём расчёт.</p>'
     '<div style="border:none;border-top:solid #B5C4DF 1.0pt;padding:3.0pt 0cm 0cm 0cm">'
     '<p class="MsoNormal"><b>От:</b> Иван &lt;ivan@example.org&gt;<br>'
     '<b>Отправлено:</b> 25 сентября 2026 г. 11:21<br><b>Кому:</b> zakaz@example.org<br>'
     '<b>Тема:</b> Запрос</p></div>'
     '<p class="MsoNormal">Исходный текст запроса.</p></div>',
     "RE: Запрос", "outlook"),
    ("Outlook: шапка в лишнем <div> (57260)",
     '<div class="WordSection1"><p class="MsoNormal">Владимир, добрый день!</p>'
     '<div><div><div style="border:none;border-top:solid #E1E1E1 1.0pt;padding:3.0pt 0cm 0cm 0cm">'
     '<p class="MsoNormal"><b>From:</b> Иван &lt;ivan@example.org&gt;<br>'
     '<b>Sent:</b> Friday, September 25, 2026 11:21 AM</p></div></div></div>'
     '<p class="MsoNormal">Текст прошлого письма.</p></div>',
     "RE: запрос", "outlook"),
    ("Outlook в браузере (OWA)",
     '<div dir="ltr">Счёт во вложении.</div>'
     '<hr style="display:inline-block;width:98%" tabindex="-1">'
     '<div id="divRplyFwdMsg" dir="ltr"><font face="Calibri"><b>From:</b> Иван &lt;ivan@example.org&gt;'
     '<br><b>Sent:</b> Monday, September 21, 2026 10:00<br><b>Subject:</b> Счёт</font></div>'
     '<div>Пришлите счёт.</div>',
     "RE: Счёт", "owa"),
    # ---------------------------------------------------------------- Gmail
    ("Gmail",
     '<div dir="ltr">Спасибо, всё получили!</div><br>'
     '<div class="gmail_quote gmail_quote_container"><div dir="ltr" class="gmail_attr">'
     'пн, 21 сент. 2026 г. в 10:00, Иван &lt;<a href="mailto:ivan@example.org">ivan@example.org</a>&gt;:<br></div>'
     '<blockquote class="gmail_quote" style="margin:0px 0px 0px 0.8ex;border-left:1px solid rgb(204,204,204)">'
     'Высылаю документы.</blockquote></div>',
     "Re: Документы", "gmail"),
    # ---------------------------------------------------------------- Thunderbird, Apple
    ("Thunderbird: шапка moz-cite-prefix, подпись после цитаты (125)",
     '<p><br></p><p>Прайс во вложении.</p>'
     '<div class="moz-cite-prefix">21.09.2026 20:11, <a class="moz-txt-link-abbreviated" '
     'href="mailto:zakaz@example.org">zakaz@example.org</a> пишет:<br></div>'
     '<blockquote type="cite" cite="mid:x@example.org"><p>Просим прислать прайс.</p></blockquote>'
     '<pre class="moz-signature" cols="72">-- \nИван, менеджер, +7 900 000-00-00</pre>',
     "Re: Прайс", "cite"),
    ("Apple Mail: blockquote type=cite",
     '<div dir="ltr">Хорошо, договорились.</div><div dir="ltr"><br>'
     '<blockquote type="cite">21 сент. 2026 г., в 10:00, Иван &lt;ivan@example.org&gt; написал(а):<br>'
     '<br><div dir="ltr">Подтвердите заказ.</div></blockquote></div>',
     "Re: Заказ", "cite"),
    # ---------------------------------------------------------------- Яндекс
    ("Яндекс: строки-шапки и голый blockquote (57501)",
     '<div>Владимир, здравствуйте.</div><div>Пришлите сертификаты.</div><div> </div>'
     '<div>----------------</div><div>Кому: Ирина (irina@example.org);</div>'
     '<div>Тема: забор груза;</div>'
     '<div>23.07.2026, 03:56, "Владимир" &lt;zakaz@example.org&gt;:</div>'
     '<blockquote><div>Груз готов к отгрузке.</div></blockquote>',
     "Re: забор груза", "header"),
    ("шапка голым текстом перед голым blockquote",
     '<div>Принято.<br><br>Пн, 21.09.2026, 10:00, Иван &lt;ivan@example.org&gt;:<br>'
     '<blockquote>Отправили вчера.</blockquote></div>',
     "Re: Отгрузка", "header"),
    ("«пишет:» без даты и адреса перед голым blockquote",
     '<div>Согласовано.</div><div>Иван Петров пишет:</div>'
     '<blockquote><div>Можно ли отгрузить в пятницу?</div></blockquote>',
     "Re: Отгрузка", "header"),
    # ---------------------------------------------------------------- «Original Message»
    ("-----Original Message----- в своём div",
     '<div>Ответ на ваш вопрос: да.</div>'
     '<div>-----Original Message-----<br>From: Иван &lt;ivan@example.org&gt;<br>'
     'Sent: Monday, September 21, 2026<br>Subject: Вопрос<br><br>Будет ли скидка?</div>',
     "RE: Вопрос", "separator"),
    ("«Исходное сообщение» в span внутри абзаца — поднимаемся до абзаца",
     '<div class="WordSection1"><p>Ответ: да.</p>'
     '<p class="MsoNormal"><span>-----Исходное сообщение-----</span></p>'
     '<p class="MsoNormal">От: Иван</p><p class="MsoNormal">Будет ли скидка?</p></div>',
     "RE: Вопрос", "separator"),
    ("«Исходное сообщение» хвостом после <br>",
     '<div>Ответ: да.<br>-----Исходное сообщение-----<br>От: Иван<br>Будет ли скидка?</div>',
     "RE: Вопрос", "separator"),

    # ================================================================ не сворачиваем
    ("пересылка из приложения mail.ru (95)",
     '<div id="composeWebView_editable_content"><div><br></div>'
     '<div id="mail-app-auto-signature">Отправлено из мобильной Почты Mail.ru</div>'
     '<br><br>-------- Пересылаемое сообщение --------<br>От: Иван &lt;ivan@example.org&gt;'
     '<br>Кому: zakaz@example.org<br>Тема: RE: ммк<br><br>'
     '<div id="composeWebView_previouse_content"><blockquote id="mail-app-auto-quote">'
     '<div>Счёт во вложении.</div></blockquote></div></div>',
     "RE: ммк", None),
    ("пересылка по теме письма",
     '<div>Посмотри, пожалуйста.</div>' + MAILRU_QUOTE, "Fwd: Счёт", None),
    ("пересылка по теме письма, FW:",
     '<div>Посмотри.</div>' + MAILRU_QUOTE, "FW: запрос на лестницы", None),
    ("Gmail: пересылка внутри gmail_quote",
     '<div dir="ltr">Для информации.</div><div class="gmail_quote">'
     '---------- Forwarded message ---------<br>От: Иван &lt;ivan@example.org&gt;<br>'
     'Date: пн, 21 сент. 2026 г.<br><br><div>Текст заявки.</div></div>',
     "Документы", None),
    ("сплошная цитата — своего текста нет",
     MAILRU_QUOTE, "Re: Прайс", None),
    ("ответы между цитатами",
     '<div class="moz-cite-prefix">21.09.2026 20:11, Иван пишет:<br></div>'
     '<blockquote type="cite">Сколько стоит?</blockquote><p>100 рублей.</p>'
     '<blockquote type="cite">Когда отгрузка?</blockquote><p>Завтра.</p>',
     "Re: Вопросы", None),
    ("голый blockquote — отступ, не цитата",
     '<p>Прошу изготовить:</p><blockquote>ограждение 12 м;<br>калитка 1 шт.</blockquote>'
     '<p>Спасибо.</p>',
     "Заявка", None),
    ("голый blockquote с отступом Gmail без шапки",
     '<div dir="ltr">Текст<blockquote style="margin:0 0 0 40px;border:none;padding:0px">'
     '<div>с отступом</div></blockquote></div>',
     "Заявка", None),
    # Разбор шага 20 (30.09.2026): строка самой заявки с датой, временем или
    # адресом и «:» в конце, под ней — отступ. Это содержание письма, а не
    # цитата: одной даты, одного времени или одного адреса для шапки мало.
    ("отступ после строки с датой — заявка, не цитата",
     '<div>Добрый день!</div><div>Прошу рассчитать по КМД от 12.09.2026:</div>'
     '<blockquote>ограждение 12 м;<br>калитка 1 шт.</blockquote><div>Спасибо, Иван</div>',
     "Заявка на ограждение", None),
    ("отступ после строки со временем",
     '<div>Совещание завтра в 10:00, повестка:</div>'
     '<blockquote>1. Сроки<br>2. Цена</blockquote><div>Иван</div>',
     "Совещание", None),
    ("отступ после строки с адресом",
     '<div>Документы присылайте на docs@example.org:</div>'
     '<blockquote>счёт, УПД, сертификаты</blockquote><div>Спасибо</div>',
     "Документы", None),
    ("отступ после строки с датой голым текстом",
     '<div>Нужны позиции к 01.10.2026:<blockquote>лист 4 мм — 2 т</blockquote>С уважением</div>',
     "Заявка", None),
    ("подпись «-- » — не цитата",
     '<div>Добрый день, заявка во вложении.</div><div>-- </div>'
     '<div data-o-mail-quote="1">Иван, +7 900 000-00-00</div>',
     "Заявка", None),
    ("подпись gmail_signature — не цитата",
     '<div dir="ltr">Заявка во вложении.</div><div dir="ltr" class="gmail_signature" '
     'data-o-mail-quote="1">Иван<br>+7 900 000-00-00</div>',
     "Заявка", None),
    ("метки Odoo data-o-mail-quote сами по себе — не признак",
     '<div>Текст</div><div data-o-mail-quote-container="1"><div data-o-mail-quote="1">'
     'Отправлено из мобильной Почты Mail.ru</div></div>',
     "Заявка", None),
    ("кандидат внутри <p>",
     '<p>Текст <span class="mail-quote-collapse">цитата пишет:</span> и ещё текст</p>',
     "Re: x", None),
    ("кандидат внутри <tr>",
     '<div>Текст</div><table><tr><div class="mail-quote-collapse"><blockquote>'
     'цитата</blockquote></div></tr></table>',
     "Re: x", None),
    ("без признаков цитаты",
     '<div>Добрый день!</div><div>Прошу КП на навес 6×12 м.</div>',
     "Запрос КП", None),
    ("пустое письмо", "", "Re: x", None),
]


def _visible(markup):
    """Видимый текст без «···»: что увидит читатель, раскрыв всё."""
    text = re.sub(r"<[^>]*>", " ", markup).replace(quote_fold.SUMMARY_TEXT, " ")
    return re.findall(r"\w+", html.unescape(text))


def _urls(markup):
    return sorted(re.findall(r'(?:src|data-blocked-src|href)="([^"]*)"', markup))


class TestQuoteRules(unittest.TestCase):

    def test_table(self):
        for name, body, subject, expected in CASES:
            with self.subTest(name):
                out, rule = fold_quotes(body, subject)
                self.assertEqual(rule, expected)
                if expected is None:
                    self.assertIs(out, body, "Без свёртки — исходная строка как есть.")
                    continue
                self.assertEqual(out.count("<details"), 1)
                self.assertIn('<details class="pmk-quote" data-pmk-rule="%s">' % expected, out)
                self.assertIn('<summary title="%s">%s</summary>' % (
                    quote_fold.SUMMARY_TITLE, quote_fold.SUMMARY_TEXT), out)
                self.assertEqual(_visible(out), _visible(body), "Текст письма цел.")
                self.assertEqual(_urls(out), _urls(body), "Адреса картинок и ссылок на месте.")
                again, second = fold_quotes(out, subject)
                self.assertIsNone(second, "Повторный проход ничего не меняет.")
                self.assertIs(again, out)

    def test_quote_is_what_gets_hidden(self):
        body = CASES[0][1]
        out, _rule = fold_quotes(body)
        inside = out[out.index("<details"):out.index("</details>")]
        self.assertIn("Просим прислать прайс", inside)
        self.assertIn("cid:logo@x", inside, "Картинка цитаты свёрнута вместе с ней.")
        self.assertNotIn("Добрый день, счёт во вложении", inside)
        self.assertNotIn("С уважением, Иван", inside, "Подпись после цитаты видна.")

    def test_header_lines_fold_with_the_quote(self):
        body = next(case[1] for case in CASES if case[0].startswith("Яндекс"))
        out, _rule = fold_quotes(body)
        inside = out[out.index("<details"):]
        for line in ("----------------", "Кому: Ирина", "Тема: забор груза", "23.07.2026"):
            self.assertIn(line, inside)
        self.assertNotIn("Пришлите сертификаты", inside)

    def test_outlook_folds_to_the_end_of_the_section(self):
        body = next(case[1] for case in CASES if case[0] == "Outlook настольный, EN")
        out, _rule = fold_quotes(body)
        inside = out[out.index("<details"):out.index("</details>")]
        self.assertIn("From:", inside)
        self.assertIn("Просим прислать прайс", inside)
        self.assertNotIn("Добрый день! Цены в магазине", inside)

    def test_mailru_app_keeps_the_bare_header_visible(self):
        body = next(case[1] for case in CASES if case[0].startswith("mail.ru приложение"))
        out, _rule = fold_quotes(body)
        self.assertLess(out.index("Среда, 23 сентября"), out.index("<details"))
        self.assertIn('<details class="pmk-quote" data-pmk-rule="mailru_app">'
                      '<summary title="%s">%s</summary><div id="composeWebView_previouse_content">'
                      % (quote_fold.SUMMARY_TITLE, quote_fold.SUMMARY_TEXT), out)

    def test_text_after_the_quote_stays_outside(self):
        body = '<div>Ответ.</div><blockquote type="cite">Вопрос?</blockquote>Хвост после цитаты'
        out, rule = fold_quotes(body)
        self.assertEqual(rule, "cite")
        self.assertTrue(out.endswith("</details>Хвост после цитаты"), out)

    def test_markup_object_is_accepted(self):
        class Markup(str):
            pass
        body = Markup(CASES[0][1])
        out, rule = fold_quotes(body)
        self.assertEqual(rule, "mailru")
        plain = Markup("<div>Без цитаты</div>")
        self.assertIs(fold_quotes(plain)[0], plain)

    def test_big_letter_is_left_alone_quickly(self):
        big = "<div>Ответ</div>" + "<p>строка текста письма</p>" * 60000 + MAILRU_QUOTE
        self.assertGreater(len(big), quote_fold.MAX_CHARS)
        started = time.monotonic()
        out, rule = fold_quotes(big)
        self.assertIsNone(rule)
        self.assertIs(out, big)
        self.assertLess(time.monotonic() - started, 1.0)

    def test_heavy_letter_under_the_limit_is_fast(self):
        body = "<div>Ответ</div>" + "<p>строка текста письма</p>" * 35000 + MAILRU_QUOTE
        self.assertLess(len(body), quote_fold.MAX_CHARS)
        started = time.monotonic()
        _out, rule = fold_quotes(body)
        self.assertEqual(rule, "mailru")
        self.assertLess(time.monotonic() - started, 1.0)

    def test_deep_nesting_is_fast_and_loses_nothing(self):
        for depth in (50, 300, 3000):
            body = "<div>Ответ клиента</div>" + "<div>" * depth + MAILRU_QUOTE + "</div>" * depth
            started = time.monotonic()
            out, rule = fold_quotes(body)
            self.assertLess(time.monotonic() - started, 1.0, depth)
            if rule is None:
                self.assertIs(out, body)
            else:
                self.assertEqual(_visible(out), _visible(body), depth)

    def test_broken_markup_is_left_alone(self):
        for body in ("<div", "<<<>>>", "<blockquote", "\x00<blockquote type=cite>x"):
            out, _rule = fold_quotes(body)
            self.assertIsInstance(out, str)


if __name__ == "__main__":
    unittest.main()
