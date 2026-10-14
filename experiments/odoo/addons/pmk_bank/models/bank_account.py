# -*- coding: utf-8 -*-
"""Счёт в банке, за поступлениями на который следим.

Заводится руками в «Настройки → Банк: счета» — только те счета, о деньгах на
которые нужно знать (Антон 14.10.2026: у ИП Чулкова — только основной
…8163; карточный, «налог», копилка, юаневый — нет). Опрос банка — cron раз в
5 минут.

Что считать новым. Модульбанк отдаёт у операции только ДАТУ (executed
«2026-10-13T00:00:00»), времени нет — правило «присылать пришедшее после
момента подключения» потеряло бы платежи дня подключения. Поэтому: первый
опрос счёта запоминает всё, что банк уже показывает, как «было до
подключения» (state=baseline, в группу не идёт), а дальше в группу идёт
каждая операция, которой банк раньше не показывал.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

from ..tools.modulbank import Modulbank, ModulbankError
from ..tools.tochka import Tochka

_logger = logging.getLogger(__name__)

PARAM_TOKEN = "pmk_bank.%s.token"
BANKS = [("modulbank", "Модульбанк"), ("tochka", "Точка")]
# Сколько дней назад перечитывать при каждом опросе: банк может провести
# платёж задним числом, а дубли отсекаются по id операции.
LOOKBACK_DAYS = 3


class PmkBankAccount(models.Model):
    _name = "pmk.bank.account"
    _description = "Счёт в банке (поступления)"
    _order = "org_id, number"

    name = fields.Char("Счёт", compute="_compute_name", store=True)
    active = fields.Boolean("Следить", default=True)
    org_id = fields.Many2one("pmk.org", "Организация", required=True, ondelete="restrict")
    bank = fields.Selection(BANKS, "Банк", required=True, default="modulbank")
    number = fields.Char("Номер счёта", required=True)
    token_param = fields.Char(
        "Ключ (системный параметр)",
        help="Имя системного параметра с ключом банка. Пусто — pmk_bank.<банк>.token. "
             "Свой ключ нужен, когда у организаций разные ключи (Точка: Бутов и "
             "Астахов — каждый выпускает свой).")
    bank_ref = fields.Char("ID счёта в банке", readonly=True, copy=False,
                           help="Находится по номеру при первом опросе.")
    last_sync = fields.Datetime("Последний опрос", readonly=True)
    last_error = fields.Char("Ошибка опроса", readonly=True)
    payment_ids = fields.One2many("pmk.bank.payment", "account_id", "Поступления")

    _number_uniq = models.Constraint("UNIQUE(bank, number)", "Этот счёт уже заведён.")

    @api.depends("bank", "number", "org_id")
    def _compute_name(self):
        labels = dict(BANKS)
        for acc in self:
            acc.name = "%s …%s · %s" % (labels.get(acc.bank, ""), (acc.number or "")[-4:],
                                        acc.org_id.name or "")

    # ── опрос ────────────────────────────────────────────────────────────

    def _pmk_client(self):
        key = self.token_param or PARAM_TOKEN % self.bank
        token = self.env["ir.config_parameter"].sudo().get_param(key)
        if not token:
            raise ModulbankError("не задан ключ (системный параметр %s)" % key)
        return Tochka(token) if self.bank == "tochka" else Modulbank(token)

    @api.model
    def _cron_sync(self):
        for acc in self.search([("active", "=", True)]):
            acc.pmk_sync()

    def action_sync(self):
        for acc in self:
            acc.pmk_sync()

    def pmk_sync(self, notify=True):
        """Забрать новые поступления и прислать их в группу (кроме первого опроса)."""
        self.ensure_one()
        try:
            client = self._pmk_client()
            if not self.bank_ref:
                found = [a for a in client.accounts() if a["number"] == self.number]
                if not found:
                    raise ModulbankError("банк не знает счёт %s" % self.number)
                self.bank_ref = found[0]["id"]
            since = fields.Date.context_today(self) - timedelta(days=LOOKBACK_DAYS)
            ops = client.incoming(self.bank_ref, since.strftime("%Y-%m-%d"))
        except ModulbankError as exc:
            self.write({"last_error": str(exc)[:250], "last_sync": fields.Datetime.now()})
            _logger.warning("Банк %s: %s", self.name, exc)
            return self.env["pmk.bank.payment"]
        Payment = self.env["pmk.bank.payment"]
        known = set(Payment.search([("account_id", "=", self.id)]).mapped("ext_id"))
        baseline = not self.last_sync          # первый опрос счёта
        new = Payment
        for op in ops:
            if op.get("id") in known:
                continue
            known.add(op.get("id"))
            new |= Payment._pmk_create_from_op(self, op, baseline=baseline)
        self.write({"last_error": False, "last_sync": fields.Datetime.now()})
        if notify and not baseline:
            for pay in new.filtered(lambda p: p.state == "new").sorted("executed"):
                pay.pmk_notify()
        return new
