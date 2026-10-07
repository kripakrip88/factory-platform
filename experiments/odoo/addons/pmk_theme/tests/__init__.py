# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk23_test -i pmk_theme,pmk_purchase,theme_nexus --test-enable \
#        --test-tags /pmk_theme,/pmk_purchase --stop-after-init --http-port 8099
# theme_nexus — как на стенде: переключатель темы опирается на её механизм
# (шаг 47); без неё часть проверок сборки пропускается.
# Подсветку строки разделов (JS) здесь не проверить — в контейнере нет
# Chrome, туры пропускаются. Ключи подсветки — чистые функции
# static/src/js/active_section_keys.js, их гоняет node вне Odoo.
from . import test_dangerous_actions
from . import test_settings_paid_hidden
from . import test_step30_highlights
from . import test_list_table
from . import test_empty_screens
from . import test_step27_forms
from . import test_step47_trifles
from . import test_step29_hidden
# Меню внутри разделов (шаг 38): состав и порядок пунктов, разделы «Ещё» по
# группе, заголовки окон. Вместе с pmk_purchase и pmk_mail_ui:
#   odoo -d pmk38_test -i pmk_theme,pmk_purchase,pmk_mail_ui,theme_nexus \
#        --test-enable --test-tags /pmk_theme,/pmk_purchase,/pmk_mail_ui \
#        --stop-after-init --http-port 8099
from . import test_step38_menus
from . import test_step40_dark
# Одно понятие — одно слово (шаг 39): файлы слов, строки кода, DATA_WORDS,
# крючок загрузки переводов, заголовки окон; экраны — со штатным русским
# переводом модулей (TestStep39Screens грузит его сам, это дольше):
#   odoo -d pmk39_test -i pmk_theme,pmk_purchase,pmk_deal --test-enable \
#        --test-tags /pmk_theme:TestStep39Words,/pmk_theme:TestStep39Screens \
#        --stop-after-init --http-port 8099
from . import test_step39_words
# Шапка документа (шаг 48): кнопки и этап в строке пути, «Сохранить» /
# «Отменить» и «⚙ Действия ▾» кнопками, листалка без счётчика, «Отметить
# проигрыш» не в ⚙ формы. Вместе с pmk_deal (номер сделки, форма без «Новое»):
#   odoo -d pmk48_test -i pmk_theme,pmk_deal,theme_nexus --test-enable \
#        --test-tags /pmk_theme:TestHeaderStep48,/pmk_deal --stop-after-init \
#        --http-port 8099
# Правила без Odoo — node static/tests/form_head_step48.test.mjs.
from . import test_step48_header
# Ширина экрана (шаг 49): лист и лента до 1800 px, короткие поля 25rem,
# подсветка по контуру поля; раздел в живом forms_nexus.scss, forms.scss
# выключен. Вместе с шагами 48 и 40 (раздел 48 теперь не последний в файле):
#   odoo -d pmk49_test -i pmk_theme,pmk_deal,theme_nexus --test-enable \
#        --test-tags /pmk_theme:TestStep49Width,/pmk_theme:TestHeaderStep48,/pmk_theme:TestDarkPairsStep40,/pmk_theme \
#        --stop-after-init --http-port 8099
from . import test_step49_width
# Мелочи после приёмки 22–34 (шаг 53): теги сделки, «Снабженец», поля рулона
# в доборке — до востребования; «Возможность» → «Сделка» (слова sale_crm,
# форма стадии, Настройки CRM, тур). С pmk_calc (доборка) и pmk_purchase:
#   odoo -d pmk53_test -i pmk_theme,pmk_purchase,pmk_deal,pmk_calc --test-enable \
#        --test-tags /pmk_theme:TestHiddenStep53,/pmk_theme:TestStep53Words,/pmk_theme:TestStep39Words \
#        --stop-after-init --http-port 8099
from . import test_step53_hidden
from . import test_step53_words
