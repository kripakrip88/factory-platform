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
# Лента справа от листа от 2200 px (шаг 49Б): раздел в конце живого
# forms_nexus.scss, порог един с js/chatter_aside_rules.js, шаг 49 до порога
# без изменений. Вместе с шагами 49, 48, 40 и 30 (лента, кнопка «История»):
#   odoo -d pmk49b_test -i pmk_theme,pmk_deal,theme_nexus --test-enable \
#        --test-tags /pmk_theme:TestStep49bAside,/pmk_theme:TestStep49Width,/pmk_theme:TestHeaderStep48,/pmk_theme:TestDarkPairsStep40,/pmk_theme:TestHighlightsStep30 \
#        --stop-after-init --http-port 8099
# Правила без Odoo — node static/tests/chatter_aside_step49b.test.mjs.
from . import test_step49b_aside
# Мелочи после приёмки 22–34 (шаг 53): теги сделки, «Снабженец», поля рулона
# в доборке — до востребования; «Возможность» → «Сделка» (слова sale_crm,
# форма стадии, Настройки CRM, тур). С pmk_calc (доборка) и pmk_purchase:
#   odoo -d pmk53_test -i pmk_theme,pmk_purchase,pmk_deal,pmk_calc --test-enable \
#        --test-tags /pmk_theme:TestHiddenStep53,/pmk_theme:TestStep53Words,/pmk_theme:TestStep39Words \
#        --stop-after-init --http-port 8099
from . import test_step53_hidden
from . import test_step53_words
from . import test_step59_tasks
# Плоско на бежевом (шаг 52): шапка документа одной рамкой со строкой кнопок,
# лист без белой подложки, вкладка карточкой, таблица своей рамкой; раздел в
# конце живых forms_nexus.scss и dark.scss, обёртка шапки — разметкой вида
# (views/step52_doc_top.xml и виды pmk_calc, pmk_cut, pmk_laser, pmk_orders,
# pmk_tech). Вместе с соседями, чьи тесты смотрят на верх листа:
#   odoo -d pmk52_test -i pmk_theme,pmk_deal,pmk_org,pmk_tech,pmk_cut,pmk_laser,theme_nexus --test-enable \
#        --test-tags /pmk_theme:TestStep52Flat,/pmk_theme:TestStep49bAside,/pmk_theme:TestStep49Width,/pmk_theme:TestHeaderStep48,/pmk_theme:TestDarkPairsStep40,/pmk_theme:TestStep39Words,/pmk_deal,/pmk_org,/pmk_laser,/pmk_tech \
#        --stop-after-init --http-port 8099
from . import test_step52_flat
# «История» кнопкой в строке пути, лента из формы убрана (шаг 65): вкладка
# «Файлы» основным документам с вкладками, выключатель «Убранное (показать)»,
# расширения шаблонов (строка пути, копия ленты, ярлык вкладки), раздел в
# конце живых forms_nexus.scss и dark.scss. Вместе с соседями (52 — порядок
# разделов, pmk_flow — «Связи» последней из своих вкладок):
#   odoo -d pmk65_test -i pmk_theme,pmk_deal,pmk_calc,pmk_flow,pmk_orders,pmk_tech,pmk_cut,pmk_laser,theme_nexus --test-enable \
#        --test-tags /pmk_theme:TestStep65History,/pmk_theme:TestStep65Session,/pmk_theme:TestStep52Flat,/pmk_theme:TestStep49bAside,/pmk_theme:TestStep49Width,/pmk_theme:TestHeaderStep48,/pmk_theme:TestDarkPairsStep40,/pmk_theme:TestStep39Words,/pmk_flow \
#        --stop-after-init --http-port 8099
# Правила без Odoo — node static/tests/doc_tools_step65.test.mjs.
from . import test_step65_history
# Окно «История» как в МоёмСкладе (шаг 66): событие — заголовок «Карнеев А.,
# изменено 08.10.2026 22:48» и таблица «Поле | Было | Стало»; свой шаблон
# события (не расширение mail.Message), договор с ядром mail и Owl, разметка
# tracking_manager, раздел в конце живых forms_nexus.scss и dark.scss.
# С tracking_manager (разбор изменений строк) и соседями шага 65:
#   odoo -d pmk66_test -i pmk_theme,pmk_deal,pmk_calc,pmk_flow,tracking_manager,theme_nexus --test-enable \
#        --test-tags /pmk_theme:TestStep66HistoryView,/pmk_theme:TestStep65History,/pmk_theme:TestStep52Flat,/pmk_theme:TestHeaderStep48,/pmk_theme:TestDarkPairsStep40,/pmk_theme:TestStep39Words \
#        --stop-after-init --http-port 8099
# Правила без Odoo — node static/tests/history_step66.test.mjs.
from . import test_step66_history_view
from . import test_tracking_lang
from . import test_t262_employees
from . import test_t265_chrome_tabs
from . import test_t266_wide
from . import test_login_page
from . import test_step75_navbar_tabs
