# -*- coding: utf-8 -*-
SINCE = "2026-09-30 14:00:00"   # 01.10.2026 00:00 по Хабаровску (UTC+10), даты писем — в UTC


def post_init_hook(env):
    """Счета берём с 01.10.2026 по Хабаровску (Антон 25.10: «с 01.10»; ≈15 счетов Металлсервиса,
    Голубенко проверит пачкой); проверяющий — тот же, что у разбора почты (Голубенко).
    Сигнал в Телеграм о новом счёте не нужен (Антон 25.10) — хватает списка «Ждут проверки».
    Отбор почты включён сразу (Антон 25.10: «для постоянного обновления цен»); на копии
    почта не качается — включение ничего не делает."""
    params = env["ir.config_parameter"].sudo()
    if not params.get_param("pmk_supplier_invoice.enabled"):
        params.set_param("pmk_supplier_invoice.enabled", "1")
    if not params.get_param("pmk_supplier_invoice.since"):
        params.set_param("pmk_supplier_invoice.since", SINCE)
