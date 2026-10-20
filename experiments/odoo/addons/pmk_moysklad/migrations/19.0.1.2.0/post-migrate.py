# -*- coding: utf-8 -*-
"""Счета МоегоСклада → сделки (21.10.2026): старые счета не трогаем.

Метка включения — последнее «updated» уже перенесённых счетов (время МоегоСклада):
сделки двигают только счета, созданные или изменённые в МоёмСкладе позже неё.
"""
from datetime import datetime, timedelta


def migrate(cr, version):
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'pmk_moysklad.last_invoices'")
    row = cr.fetchone()
    # Нет переносов (новая база) — московское «сейчас», как пишет МойСклад.
    since = (row and row[0]) or (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S.000")
    cr.execute("""
        INSERT INTO ir_config_parameter (key, value, create_date, write_date)
        VALUES ('pmk_moysklad.deals_since', %s, now(), now())
        ON CONFLICT (key) DO NOTHING
    """, (since,))
