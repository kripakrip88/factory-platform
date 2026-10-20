# -*- coding: utf-8 -*-
"""Счёт МоегоСклада → сделка воронки (этап 3 плана «сделка → счёт», Антон 21.10.2026).

Менеджеры выставляют счета в МоёмСкладе, а воронка Odoo о них не знала: сделка
стояла в «Расчёте», когда клиент уже заплатил. Теперь синхронизация (крон раз в
10 минут) после каждого счёта:

- ищет открытую сделку того же контрагента, заведённую не позже чем через 3 дня
  после счёта (несколько — самая свежая); счёт — в «Счета» сделки;
- двигает сделку по статусу счёта: «Согласование» → «Счёт выставлен»;
  предоплата / оплачен / постоплата → «Оплачено / в работе»; отгружен на всю
  сумму → «Закрыта»; «Не актуальна» → проиграна (если других живых счетов нет);
- сделки нет, а счёт оплачен (или в постоплате) — заводит сделку сразу в
  «Оплачено / в работе», менеджер — владелец счёта. Счёт в «Согласовании» без
  сделки сделку не заводит: выставленные и забытые счета воронку не засоряют.

Только вперёд по воронке: новый счёт в «Согласовании» не откатывает оплаченную
сделку. Старые счета не трогаем — только созданные или изменённые в МоёмСкладе
после включения (pmk_moysklad.deals_since — метка updated МоегоСклада).

Счёт МоегоСклада — запись МоегоСклада: Odoo его не подтверждает и «Заказы в
работе» по нему не заводит. Поэтому стадию ставим с контекстом pmk_orders_skip
(реакции pmk_orders на «Оплачено» и «Закрыта» не срабатывают).
"""
import logging
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

SKIP = "pmk_orders_skip"
DEAL_DAYS = 3  # сделка, заведённая позже счёта не больше чем на столько, — тоже его

STAGE_INVOICED = "pmk_deal.stage_invoiced"
STAGE_IN_WORK = "pmk_deal.stage_in_work"
STAGE_CLOSED = "crm.stage_lead4"
STATE_STAGE = {
    "Согласование": STAGE_INVOICED,
    "Предоплата получена": STAGE_IN_WORK,
    "Оплачен": STAGE_IN_WORK,
    "Постоплата": STAGE_IN_WORK,
}
LOST_STATE = "Не актуальна"
# Без сделки сделку заводит только оплата (или постоплата — работа началась).
# Отгруженный счёт в «Согласовании» её не заводит: статус не ведут — прогон на
# копии 21.10.2026 завёл бы 16 «Закрытых» по неоплаченным счетам.
PAID_STATES = ("Предоплата получена", "Оплачен", "Постоплата")


class CrmLeadMs(models.Model):
    _inherit = "crm.lead"

    pmk_source = fields.Selection(selection_add=[("ms", "Счёт в МоёмСкладе")],
                                  ondelete={"ms": "set null"})


class SaleOrderDeal(models.Model):
    _inherit = "sale.order"

    def _pmk_ms_target_stage(self):
        """Стадия сделки по счёту МоегоСклада (xmlid) или None — «не трогать»."""
        self.ensure_one()
        if self.pmk_ms_state == LOST_STATE:
            return None
        total = self.pmk_ms_sum or self.amount_total
        if total > 0 and self.pmk_ms_shipped_sum >= total - 0.01:
            return STAGE_CLOSED
        return STATE_STAGE.get(self.pmk_ms_state or "")

    def _pmk_ms_find_deal(self):
        """Открытая сделка контрагента счёта: не выиграна, не проиграна, заведена
        не позже чем через DEAL_DAYS после счёта; несколько — самая свежая."""
        self.ensure_one()
        client = self.partner_id.commercial_partner_id
        if not client:
            return self.env["crm.lead"]
        domain = [("type", "=", "opportunity"), ("partner_id", "child_of", client.id),
                  ("stage_id.is_won", "=", False)]
        if "won_status" in self.env["crm.lead"]._fields:
            domain.append(("won_status", "=", "pending"))
        if self.date_order:
            domain.append(("create_date", "<=", self.date_order + timedelta(days=DEAL_DAYS)))
        return self.env["crm.lead"].search(domain, order="create_date desc, id desc", limit=1)

    def _pmk_ms_new_deal(self, stage):
        self.ensure_one()
        client = self.partner_id.commercial_partner_id
        # «Объект» МоегоСклада бывает номером («1»…«5») — тогда первая строка счёта.
        what = (self.pmk_ms_object or "").strip()
        if len(what) < 4 or what.isdigit():
            what = (self.order_line[:1].name or "").strip()
        # Контрагент — строкой под названием на карточке, в названии не повторяем.
        name = what[:90] or _("Счёт %s", self.name)
        vals = {
            "name": name, "type": "opportunity", "partner_id": client.id,
            "user_id": self.user_id.id or False, "stage_id": stage.id,
            "expected_revenue": self.pmk_ms_sum or self.amount_total, "pmk_source": "ms",
        }
        if "pmk_org_id" in self.env["crm.lead"]._fields and self.pmk_org_id:
            vals["pmk_org_id"] = self.pmk_org_id.id
        # Без письма «вам назначена сделка»: её завела синхронизация, а не человек.
        return self.env["crm.lead"].with_context(
            **{SKIP: True}, mail_create_nolog=True, mail_auto_subscribe_no_notify=True,
            tracking_disable=True).create(vals)

    def _pmk_ms_deal_sync(self):
        """Привязать счёт МоегоСклада к сделке и подвинуть её. Возвращает сделку."""
        self.ensure_one()
        Lead = self.env["crm.lead"].with_context(**{SKIP: True}, mail_auto_subscribe_no_notify=True)
        deal = self.opportunity_id
        target_xmlid = self._pmk_ms_target_stage()
        target = target_xmlid and self.env.ref(target_xmlid, raise_if_not_found=False)
        created = False
        if not deal and self.pmk_ms_state == LOST_STATE:
            # «Не актуальна» трогает только свою сделку: старый отменённый счёт не
            # должен привязаться к свежей сделке того же клиента и проиграть её.
            return Lead
        if not deal:
            deal = self._pmk_ms_find_deal()
            if not deal:
                if not target or self.pmk_ms_state not in PAID_STATES:
                    return Lead
                deal, created = self._pmk_ms_new_deal(target), True
            self.with_context(tracking_disable=True, mail_notrack=True).opportunity_id = deal.id
            if not created:
                deal.with_context(**{SKIP: True}).message_post(body=_(
                    "Счёт %(inv)s из МоегоСклада (%(state)s) привязан к сделке.",
                    inv=self.name, state=self.pmk_ms_state or _("без статуса")),
                    subtype_xmlid="mail.mt_note")
            else:
                deal.with_context(**{SKIP: True}).message_post(body=_(
                    "Сделка заведена по счёту %(inv)s из МоегоСклада (%(state)s): заявки в Odoo "
                    "по этому контрагенту не было.", inv=self.name, state=self.pmk_ms_state),
                    subtype_xmlid="mail.mt_note")
        deal = Lead.browse(deal.id)
        if self.pmk_ms_state == LOST_STATE:
            self._pmk_ms_deal_lost(deal)
        elif target and not created:
            self._pmk_ms_deal_forward(deal, target)
        return deal

    def _pmk_ms_deal_forward(self, deal, stage):
        """Только вперёд: закрытую, проигранную и ушедшую дальше сделку не трогаем."""
        if not deal.active or deal.stage_id.is_won or deal.stage_id == stage:
            return
        if "won_status" in deal._fields and deal.won_status == "lost":
            return
        if deal.stage_id.sequence > stage.sequence:
            return
        deal.with_context(**{SKIP: True}).stage_id = stage.id
        deal.with_context(**{SKIP: True}).message_post(body=_(
            "Стадия «%(stage)s» — по счёту %(inv)s из МоегоСклада (%(state)s).",
            stage=stage.name, inv=self.name,
            state=_("отгружен") if stage.is_won else (self.pmk_ms_state or "")),
            subtype_xmlid="mail.mt_note")

    def _pmk_ms_deal_lost(self, deal):
        """«Не актуальна» → сделка проиграна, если у неё не осталось живых счетов."""
        if not deal.active or deal.stage_id.is_won:
            return
        alive = self.search_count([("opportunity_id", "=", deal.id), ("id", "!=", self.id),
                                   ("state", "!=", "cancel")])
        if alive:
            return
        deal.with_context(**{SKIP: True}).action_set_lost()
        deal.with_context(**{SKIP: True}).message_post(body=_(
            "Сделка проиграна: счёт %s в МоёмСкладе «Не актуальна».", self.name),
            subtype_xmlid="mail.mt_note")


class PmkMoyskladDeal(models.AbstractModel):
    _inherit = "pmk.moysklad"

    @api.model
    def _ms_deals_since(self):
        return self.env["ir.config_parameter"].sudo().get_param("pmk_moysklad.deals_since") or ""

    @api.model
    def _ms_deal_after_upsert(self, order, inv):
        """Старое (updated не новее метки включения) не трогаем; сбой сделки не
        останавливает перенос счетов."""
        since = self._ms_deals_since()
        if not since or (inv.get("updated") or "") <= since:
            return
        try:
            with self.env.cr.savepoint():
                order._pmk_ms_deal_sync()
        except Exception as e:  # noqa: BLE001 — сделка вторична, счёт важнее
            _logger.warning("pmk_moysklad: счёт %s — сделка не обновлена: %s", order.name, e)

    @api.model
    def _upsert_invoice(self, inv, orgs, ctx, Order):
        order = super()._upsert_invoice(inv, orgs, ctx, Order)
        self._ms_deal_after_upsert(order, inv)
        return order

    @api.model
    def _ms_after_demand(self, order, dem):
        """Отгрузка меняет «Отгружено на сумму» счёта — перечитываем счёт (один запрос
        на отгрузку, их единицы в день) и двигаем сделку до «Закрыта»."""
        super()._ms_after_demand(order, dem)
        since = self._ms_deals_since()
        if not since or (dem.get("updated") or "") <= since or not order.pmk_ms_id:
            return
        try:
            inv = self._ms_get("entity/invoiceout/%s" % order.pmk_ms_id)
        except Exception as e:  # noqa: BLE001 — сделка вторична
            _logger.warning("pmk_moysklad: счёт %s не перечитан: %s", order.name, e)
            return
        order.pmk_ms_shipped_sum = (inv.get("shippedSum") or 0) / 100.0
        self._ms_deal_after_upsert(order, dict(inv, updated=dem.get("updated")))
