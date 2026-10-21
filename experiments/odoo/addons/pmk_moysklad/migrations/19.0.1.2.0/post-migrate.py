# -*- coding: utf-8 -*-
"""Счета МоегоСклада → сделки (21.10.2026): старые счета не трогаем.

«Оплачено, а отгрузки нет» (ship_watch.py): у оплаченных счетов от 10.10.2026,
загруженных до выкладки, день оплаты неизвестен — берём дату счёта.

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
    cr.execute("""
        UPDATE sale_order SET pmk_ms_paid_on = (date_order + interval '10 hours')::date
        WHERE pmk_ms_id IS NOT NULL AND pmk_ms_paid_on IS NULL AND date_order >= '2026-10-09 14:00:00'
          AND pmk_ms_state IN ('Предоплата получена', 'Оплачен', 'Постоплата')
    """)
