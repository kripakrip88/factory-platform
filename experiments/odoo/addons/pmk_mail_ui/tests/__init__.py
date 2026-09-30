# -*- coding: utf-8 -*-
# Гонять ТОЛЬКО на одноразовой базе, не на боевой odoo:
#   odoo -d pmk_mail_test -i pmk_mail_ui --test-enable \
#        --test-tags /pmk_mail_ui,/mail_client --stop-after-init --http-port 8099
# Правила Г13 без базы: python3 addons/pmk_mail_ui/tests/test_asset_rules.py
# Свёрнутые цитаты без базы: python3 addons/pmk_mail_ui/tests/test_quote_rules.py
from . import test_asset_rules
from . import test_cron_interval
from . import test_frame_head
from . import test_lead_source
from . import test_mail_list
from . import test_quote_fold
from . import test_quote_rules
from . import test_remote_paths
from . import test_sent_copy_guard
from . import test_shared_flags
from . import test_thread_seen
