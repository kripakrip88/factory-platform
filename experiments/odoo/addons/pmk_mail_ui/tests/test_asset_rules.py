# -*- coding: utf-8 -*-
"""Правила «что грузить из письма» (разбор UX, Г13) — без базы.

Обычный unittest, без TransactionCase: tools/remote_paths.py — чистые
функции, и тесты гоняются голым питоном на ноутбуке, до всякого деплоя:

    python3 experiments/odoo/addons/pmk_mail_ui/tests/test_asset_rules.py

Внутри Odoo (--test-enable) обычный unittest-класс НЕ запускается: у него нет
test_tags, и отборщик тестов Odoo его пропускает (odoo/tests/tag_selector.py).
Поэтому ту же таблицу CASES через модель прогоняет test_remote_paths.py.

Строки — такие, какими письмо лежит в body_html после html_sanitize:
значения в кавычках, «<» и «>» внутри значений — &lt; &gt;, КРОМЕ
«<!--…-->»: его libxml2 оставляет в значении как есть (проверено на 2.9.14
сервера). Комментарии и <?…?> санитайзер тоже сохраняет. Каждая строка
проверяется дважды: до «Показать картинки» и после, и ещё раз прогоном по
уже заглушённому — повтор не должен ничего менять.
"""

import time
import unittest

try:
    # Внутри Odoo — как odoo.addons.pmk_mail_ui.tools.remote_paths.
    from ..tools import remote_paths
except (ImportError, ValueError):
    # Голым питоном — как соседний пакет.
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from tools import remote_paths

OWN = {"erppark.ru"}
B, K = "blocked", "kept"

# (текст письма, до кнопки, после кнопки)
CASES = [
    # --- чужой сервер без «http»: до кнопки глушим, после — показываем
    ('<img src="//tracker.example/p.gif">', B, K),
    ('<img src="HTTPS://t.example/p.gif">', B, K),
    ('<img src="https://erppark.ru.evil.example/p.gif">', B, K),
    ('<img src="https://erppark.ru/web/image/5?access_token=x">', B, K),
    ('<img src=//t.example/unq.gif>', B, K),
    ('<img srcset="//t.example/a.png 1x, https://t.example/b.png 2x">', B, K),
    ('<img srcset="data:image/png;base64,AA,BB 1x, //t.example/b.png 2x">', B, K),
    # Запятая внутри data: у кандидата БЕЗ описания («1x»): браузер срезает
    # её и читает «//t…» после пробела отдельным кандидатом.
    ('<img srcset="data:image/gif;base64,R0lGOD, //t.example/open.gif 2x">', B, K),
    ('<img srcset="cid:a,b,,  //t.example/open.gif 2x">', B, K),
    ('<picture><source srcset="data:,x, //t.example/p.gif 2x"><img src="cid:x"></picture>', B, K),
    ('<img srcset="\n//t.example/a.png 1x">', B, K),
    ('<table background="/\n/t.example/bg.gif"><tr><td>x</td></tr></table>', B, K),
    ('<table background="\\\\t.example\\bg.gif"><tr><td>x</td></tr></table>', B, K),
    ('<audio src="//t.example/a.mp3"></audio>', B, K),
    ('<div style="background-image:url(//t.example/b.jpg)">x</div>', B, K),
    ('<div style="background:url(&quot;//t.example/q.png&quot;); font-family:\'Arial\'">x</div>', B, K),
    ('<div style="background:u\\rl(//t.example/esc.png)">x</div>', B, K),
    ('<div style="cursor:url(//t.example/c.cur),auto">x</div>', B, K),
    # Презентационные атрибуты SVG берут url(), как CSS (повторная проверка
    # 29.09: Chrome грузит mask/clip-path/fill/stroke/marker/cursor из рамки).
    ('<svg mask="url(//t.example/x.svg#m)"></svg>', B, K),
    ('<svg cursor="url(//t.example/c.png), auto"></svg>', B, K),
    ('<svg clip-path="u&#114;l(//t.example/c.svg#c)"></svg>', B, K),
    ('<svg fill="url(#grad)"></svg>', K, K),
    ('<svg mask="url(/web/session/logout)"></svg>', B, B),
    ('<svg filter="image-set(\'//t.example/a.png\' 1x)"></svg>', B, B),
    ('<a href="https://example.org/?q=url(x)">ссылка</a>', K, K),
    ('<img alt="см. url(//t.example)" src="cid:logo">', K, K),
    # --- «к нам»: глушим всегда, кнопка не возвращает
    ('<img src="/web/session/logout">', B, B),
    ('<img src="../web/session/logout">', B, B),
    ('<img src="web/session/logout">', B, B),
    ('<img src="%5C%5Ctracker.example%5Cp.gif">', B, B),
    ('<img src="/%09/tracker.example/p.gif">', B, B),
    ('<img src="https:tracker.example/p.gif">', B, B),
    ('<img src="">', B, B),
    ('<img src="about:blank">', B, B),
    ('<img src="blob:https://erppark.ru/1">', B, B),
    ('<img src="https://erppark.ru/web/session/logout">', B, B),
    ('<img src="https://erppark.ru">', B, B),
    ('<img src="//www.erppark.ru/web/session/logout">', B, B),
    ('<img src="//n8n.erppark.ru/x.png">', B, B),
    ('<img src="////erppark.ru/x">', B, B),
    ('<img src="//erppark%2eru/x">', B, B),
    ('<img src="//erppark.ru./x">', B, B),
    ('<img src="//user@erppark.ru:443/x">', B, B),
    ('<img src="//ｅｒｐｐａｒｋ。ru/x">', B, B),
    ('<img src="https://erppark.ru/web/image/../session/logout">', B, B),
    ('<img src="https://erppark.ru/web/image/%2E%2E/session/logout">', B, B),
    ('<td background="/bg.gif">x</td>', B, B),
    ('<video poster="//t.example/p.jpg" src="/v.mp4"></video>', B, B),
    ('<video><source src="//t.example/v.mp4"><track src="/t.vtt"></video>', B, B),
    ("<div style='background:url(\"/web/session/logout\")'>x</div>", B, B),
    ('<div style="list-style-image:url(/l.png)">x</div>', B, B),
    ('<div style="background:url(//t.example/open.png">x</div>', B, K),
    ('<div style="background:url(/open.png">x</div>', B, B),
    ("<div style=\"background-image:image-set('//t.example/a.png' 1x)\">x</div>", B, B),
    ('<div style="background:-webkit-image-set(url(data:,x) 1x)">x</div>', B, B),
    ('<div style="background:\\75 rl(/esc2.png)">x</div>', B, B),
    ('<div style="background:url(\\2f\\2f t.example/e.png)">x</div>', B, B),
    ('<div style="background:&#117;rl(/ent.png)">x</div>', B, B),
    ('<img srcset="//t.example/a.png 1x, /b.png 2x">', B, B),
    ('<img SRC="/web/session/logout">', B, B),
    ('<img/src="/web/session/logout">', B, B),
    ('<img src = "/web/session/logout">', B, B),
    # Значение соседнего атрибута не должно прятать настоящий src: браузер
    # видит здесь title, живой src и alt (атрибуты разбираются по порядку).
    ('<img title="x src=\'" src="/web/session/logout" alt="\'">', B, B),
    ('<img title="x src=\'" src="//t.example/p.gif" alt="\'">', B, K),
    ('<img srcset="data:image/gif;base64,AA,, /web/session/logout 2x">', B, B),
    # «<!--…-->» в значении санитайзер не экранирует — тег всё равно тег.
    ('<img alt="<!--x-->" src="/web/session/logout">', B, B),
    ('<img title="<!--x-->" src="//t.example/p.gif">', B, K),
    ('<img alt=\'<!--a>"b-->\' src="/web/session/logout">', B, B),
    # Непарная кавычка в комментарии не прячет настоящий тег за ним.
    ('<p>x</p><!-- <a title="x --><img src="/web/session/logout?a="><!-- "> -->', B, B),
    ('<?x "?><img src="/web/session/logout"><p title="">y</p>', B, B),
    ('<!---><img src="/web/session/logout"> -->', B, B),
    ('<!-- a --!><img src="//t.example/p.gif"> b -->', B, K),
    ('</p title="><!--"><img src="/web/session/logout">-->', B, B),
    # Внутри комментария браузер ничего не грузит — глушим про запас.
    ('<!-- <img src="/web/session/logout"> -->', B, B),
    ('<a<img src="/web/session/logout">', B, B),
    # --- части самого письма и всё, что не грузит картинку: не трогаем
    ('<img src="cid:image001.png@01DD">', K, K),
    ('<img src="data:image/png;base64,AAAA">', K, K),
    ('<img src=" DATA:image/png;base64,AAAA">', K, K),
    ('<img srcset="data:image/png;base64,AA,BB 1x">', K, K),
    ('<div style="filter:url(#f)">x</div>', K, K),
    ('<div style="font-family:\'\\5B8B\\4F53\'; color:red">x</div>', K, K),
    ('<td nowrap style="color:red">x</td>', K, K),
    ('<a href="/web/session/logout">l</a> <a href="#top">t</a> '
     '<a href="mailto:a@b.ru">m</a> <a href="tel:+7">t</a>', K, K),
    ('<p>текст url(//t.example/text) и src="//t.example/text"</p>', K, K),
    ('<p>a &lt;img src="//t.example/x"&gt; b</p>', K, K),
    ('<!-- <p>комментарий</p> --><p>x</p>', K, K),
    ('<p>1 < 2 и 3 <4</p><!-- <a title="x --><img src="cid:y">', K, K),
    # выход вендора — повторный проход ничего не меняет
    ('<img data-blocked-src="https://t.example/a.png">'
     '<div style="background:url(about:blank)">x</div>', K, K),
]


class TestAssetRules(unittest.TestCase):

    def test_table(self):
        for body, when_blocked, when_allowed in CASES:
            for allow, expected in ((False, when_blocked), (True, when_allowed)):
                with self.subTest(body=body, allow=allow):
                    out = remote_paths.block_assets(body, OWN, allow)
                    self.assertEqual(K if out == body else B, expected, out)
                    self.assertEqual(
                        remote_paths.block_assets(out, OWN, allow), out,
                        "Повторный проход должен ничего не менять.")
                    self.assertNotIn("data-blocked-data-blocked", out)
                    self.assertNotIn("pmk-blocked-pmk-blocked", out)

    def test_blocked_attribute_is_renamed_whole(self):
        out = remote_paths.block_assets('<img src="/web/session/logout">', OWN, True)
        self.assertEqual(out, '<img data-blocked-src="/web/session/logout">')

    def test_css_url_is_replaced_by_blank(self):
        out = remote_paths.block_assets(
            '<div style="color:red;background:url(/x.png) no-repeat">x</div>', OWN, True)
        self.assertEqual(
            out, '<div style="color:red;background:url(about:blank) no-repeat">x</div>')

    def test_hidden_url_blocks_the_whole_style(self):
        out = remote_paths.block_assets(
            '<div style="background:\\75 rl(/esc2.png)">x</div>', OWN, True)
        self.assertTrue(out.startswith('<div data-blocked-style='), out)

    def test_quote_trick_does_not_hide_src(self):
        out = remote_paths.block_assets(
            '<img title="x src=\'" src="/web/session/logout" alt="\'">', OWN, True)
        self.assertIn(' data-blocked-src="/web/session/logout"', out)
        self.assertIn('title="x src=\'"', out, "Чужие атрибуты не трогаем.")

    def test_without_own_hosts_our_server_is_just_remote(self):
        # Шаг В можно выключить, отдав пустой набор имён.
        out = remote_paths.block_assets(
            '<img src="https://erppark.ru/web/session/logout">', set(), True)
        self.assertEqual(out, '<img src="https://erppark.ru/web/session/logout">')

    def test_kinds(self):
        kind = remote_paths.url_kind
        self.assertEqual(kind("cid:x", OWN), remote_paths.KEEP)
        self.assertEqual(kind("//t.example/p.gif", OWN), remote_paths.REMOTE)
        self.assertEqual(kind("/p.gif", OWN), remote_paths.LOCAL)
        self.assertEqual(kind("#f", OWN), remote_paths.LOCAL,
                         "Якорь в src — адрес нашей же страницы.")
        self.assertEqual(kind("#f", OWN, css=True), remote_paths.KEEP)

    def test_empty(self):
        self.assertEqual(remote_paths.block_assets("", OWN, False), "")
        self.assertIsNone(remote_paths.block_assets(None, OWN, False))

    def test_srcset_candidates_like_the_browser(self):
        urls = remote_paths._srcset_urls
        self.assertEqual(urls("data:a,b, //t/x 2x"), ["data:a,b", "//t/x"])
        self.assertEqual(urls("a.png 1x,b.png 2x"), ["a.png", "b.png"])
        self.assertEqual(urls(" , a.png,,, b.png"), ["a.png", "b.png"])
        # Запятая в скобках описания кандидата не заканчивает.
        self.assertEqual(urls("a.png (1,2) 1x, b.png"), ["a.png", "b.png"])
        self.assertEqual(urls(""), [])

    def test_long_unclosed_markup_is_linear(self):
        """Письмо в сотни КБ не должно вешать воркер: прежняя регулярка тега
        на «<aaaa…» без «>» работала за квадрат длины (8000 знаков — 0,24 с,
        100 КБ — полминуты на проход, а проходов при открытии три-четыре)."""
        bodies = [
            "<p>x</p><!-- <a" + "a" * 100000 + "< -->",
            "<a" + "a" * 100000,
            "<a " + "b " * 50000,
            '<img alt="' + "<" * 100000,
            "<!--" * 30000,
            "<" * 100000,
            '<img srcset="' + "a," * 50000 + '">',
            '<p title="' + '"' * 100000 + ">",
        ]
        for body in bodies:
            with self.subTest(body=body[:20]):
                started = time.monotonic()
                remote_paths.block_assets(body, OWN, False)
                self.assertLess(time.monotonic() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
