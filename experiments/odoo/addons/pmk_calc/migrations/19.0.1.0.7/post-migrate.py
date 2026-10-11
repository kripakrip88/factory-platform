# -*- coding: utf-8 -*-
"""Вентзонт → заказ из нескольких размеров (11.10.2026).

В v1.56.0 документ «Вентзонт» был один на размер: номер, клиент, объект,
дата и статус лежали в самой записи pmk.vent.hood. Теперь документ — заказ
pmk.vent.hood.order, а pmk.vent.hood — его строка (размер × количество).

Каждый прежний зонт становится заказом С ТЕМ ЖЕ НОМЕРОМ (ВЗ-00001 остаётся
ВЗ-00001) и одной строкой — им самим. Вложения (скачанные DXF), история и
подписчики переезжают на заказ. На бою на 11.10 такой зонт один (ВЗ-00001,
1000×1000, цинк, 0,65), заведён Антоном при пробе.

Старые колонки (name, partner_id, customer, order_date, state) читаем SQL-ом:
полей в модели уже нет, ядро снесёт колонки в конце обновления. Повторный
запуск ничего не делает — берутся только строки без заказа.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

OLD = ("name", "partner_id", "customer", "order_date", "state")


def migrate(cr, version):
    cr.execute("SELECT column_name FROM information_schema.columns "
               "WHERE table_name = 'pmk_vent_hood'")
    cols = {row[0] for row in cr.fetchall()}
    if not set(OLD) <= cols:
        return
    cr.execute("SELECT id, name, partner_id, customer, order_date, state, "
               "create_uid, create_date FROM pmk_vent_hood WHERE order_id IS NULL ORDER BY id")
    rows = cr.dictfetchall()
    env = api.Environment(cr, SUPERUSER_ID, {"tracking_disable": True, "mail_create_nolog": True})
    Order = env["pmk.vent.hood.order"]
    for row in rows:
        order = Order.create({
            "name": row["name"] or "Черновик",
            "partner_id": row["partner_id"],
            "customer": row["customer"],
            "order_date": row["order_date"],
            "state": row["state"] or "draft",
        })
        cr.execute("UPDATE pmk_vent_hood_order SET create_uid = %s, create_date = %s WHERE id = %s",
                   (row["create_uid"], row["create_date"], order.id))
        cr.execute("UPDATE pmk_vent_hood SET order_id = %s WHERE id = %s", (order.id, row["id"]))
        cr.execute("UPDATE ir_attachment SET res_model = 'pmk.vent.hood.order', res_id = %s "
                   "WHERE res_model = 'pmk.vent.hood' AND res_id = %s", (order.id, row["id"]))
        cr.execute("UPDATE mail_message SET model = 'pmk.vent.hood.order', res_id = %s "
                   "WHERE model = 'pmk.vent.hood' AND res_id = %s", (order.id, row["id"]))
        cr.execute("DELETE FROM mail_followers WHERE res_model = 'pmk.vent.hood' AND res_id = %s",
                   (row["id"],))
        _logger.info("Вентзонт %s (строка %s) → заказ %s", row["name"], row["id"], order.id)
    if rows:
        env.invalidate_all()
        lines = env["pmk.vent.hood"].browse([row["id"] for row in rows])
        lines.modified(["qty", "total_sheet_1250_m", "total_mass_net_kg", "spec_error"])
        env.flush_all()
    cr.execute("SELECT count(*) FROM pmk_vent_hood WHERE order_id IS NULL")
    if not cr.fetchone()[0]:
        cr.execute("ALTER TABLE pmk_vent_hood ALTER COLUMN order_id SET NOT NULL")
