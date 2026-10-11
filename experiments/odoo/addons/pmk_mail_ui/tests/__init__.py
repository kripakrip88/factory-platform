# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk_mail_test -i pmk_mail_ui --test-enable \
#        --test-tags /pmk_mail_ui,/mail_client --stop-after-init --http-port 8099
# Правила Г13 без базы: python3 addons/pmk_mail_ui/tests/test_asset_rules.py
# Свёрнутые цитаты без базы: python3 addons/pmk_mail_ui/tests/test_quote_rules.py
# Лид из письма без базы: python3 addons/pmk_mail_ui/tests/test_lead_text_rules.py
from . import test_asset_rules
from . import test_cron_interval
from . import test_frame_head
from . import test_lead_from_letter
from . import test_lead_source
from . import test_lead_text_rules
from . import test_mail_list
from . import test_quote_fold
from . import test_quote_rules
from . import test_remote_paths
from . import test_sent_copy_guard
from . import test_shared_flags
from . import test_step30_token_button
# Почта в меню (шаг 38): одна — в Продажах; «Почтовые ящики» — администратору.
from . import test_step38_mail_menus
from . import test_thread_seen
# Почта, остальное (шаг 41): имена вложений, лид у строки, «С лидом», звезда
# переписки, счётчик новых, ассеты.
from . import test_step41_mail
# Мелочи после приёмки (шаг 53): «Закупки → Почта» со своим ящиком, папка
# письма для «Связей», адрес info@ → лиды выключен.
# Правила выбора ящика без базы: node addons/pmk_mail_ui/static/tests/step53_open_rules.test.mjs
from . import test_step53_open
# Клиент из письма (шаг З-14): клиент по домену и ИНН, телефон из подписи.
# Поиск клиента — pmk_partner: ставить вместе (-i pmk_mail_ui,pmk_partner).
# Подпись без базы: python3 addons/pmk_mail_ui/tests/test_signature_rules.py
from . import test_signature_rules
from . import test_z14_lead_client
