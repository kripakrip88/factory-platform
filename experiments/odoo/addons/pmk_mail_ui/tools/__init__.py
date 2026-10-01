# -*- coding: utf-8 -*-
# Чистые функции без Odoo — их проверяют голым питоном (tests/test_asset_rules.py,
# tests/test_quote_rules.py, tests/test_lead_text_rules.py). Модели импортируют
# их сами: remote_paths (Г13), quote_fold (свёрнутые цитаты «···», шаг 20) и
# lead_text (лид из письма: название и адрес, шаг 27) — см.
# models/mail_client_message.py.
