# -*- coding: utf-8 -*-
"""Трафик VPN по человеку и дню. Байты — во Float: Integer в Odoo — int4,
переполнился бы на 2 ГБ."""
from odoo import api, fields, models


class PmkVpnTraffic(models.Model):
    _name = "pmk.vpn.traffic"
    _description = "Трафик VPN за день"
    _order = "day desc"

    key_id = fields.Many2one("pmk.vpn.key", required=True, ondelete="cascade", index=True)
    day = fields.Date(required=True, index=True)
    bytes_up = fields.Float("Отправлено, байт", digits=(16, 0))
    bytes_down = fields.Float("Получено, байт", digits=(16, 0))

    _key_day_uniq = models.Constraint("UNIQUE(key_id, day)", "Одна строка на ключ и день.")

    @api.model
    def pmk_add(self, key, day, up, down):
        """Прибавить прирост. Одним запросом: синхронизация идёт раз в минуту,
        и строка дня обновляется, а не плодится."""
        self.env.cr.execute("""
            INSERT INTO pmk_vpn_traffic (key_id, day, bytes_up, bytes_down,
                                         create_uid, write_uid, create_date, write_date)
            VALUES (%s, %s, %s, %s, %s, %s, now() at time zone 'utc', now() at time zone 'utc')
            ON CONFLICT (key_id, day) DO UPDATE
               SET bytes_up = pmk_vpn_traffic.bytes_up + EXCLUDED.bytes_up,
                   bytes_down = pmk_vpn_traffic.bytes_down + EXCLUDED.bytes_down,
                   write_date = EXCLUDED.write_date
        """, [key.id, day, up, down, self.env.uid, self.env.uid])
        self.invalidate_model()
