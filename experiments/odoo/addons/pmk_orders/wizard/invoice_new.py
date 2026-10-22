# -*- coding: utf-8 -*-
"""«Создать» в списке «Счета покупателям» — окно «Новый счёт» (Антон 22.10.2026, этап 5 плана
«сделка → счёт»: «делаем»; счета без расчёта — услуги и перепродажа — «бывают хоть и редко»).

Счёт живёт в сделке (стадия, «Связи», один счёт на сделку), поэтому окно спрашивает сделку или
клиента и дальше идёт тем же путём, что «Создать ▾ → Счёт» в сделке (crm_lead.py,
action_pmk_new_invoice):
  • у сделки есть расчёт — черновик по расчёту;
  • расчёта нет — пустой черновик со строкой «Изделие» (типовое, услуга, перепродажа);
  • у сделки уже есть счёт — открываем его, второй не заводим;
  • только клиент — заводим ему сделку (менеджер — кто создаёт) и пустой черновик.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PmkInvoiceNewWizard(models.TransientModel):
    _name = "pmk.invoice.new.wizard"
    _description = "Новый счёт покупателю"

    lead_id = fields.Many2one(
        "crm.lead", "Сделка", domain="[('type', '=', 'opportunity')]",
        help="Счёт пойдёт в эту сделку: есть расчёт — по расчёту, нет — пустой черновик.")
    partner_id = fields.Many2one(
        "res.partner", "Клиент", domain="[('is_company', '=', True)]",
        help="Сделки нет — выберите клиента: заведём ему сделку и пустой счёт.")
    hint = fields.Char("Что будет", compute="_compute_hint")

    @api.onchange("lead_id")
    def _onchange_lead(self):
        if self.lead_id.partner_id:
            self.partner_id = self.lead_id.partner_id.commercial_partner_id

    @api.depends("lead_id", "partner_id")
    def _compute_hint(self):
        for wizard in self:
            lead = wizard.lead_id
            if lead:
                lead = lead.sudo()
                if lead._pmk_current_invoice():
                    wizard.hint = _("У сделки уже есть счёт — откроем его.")
                elif lead.spec_ids:
                    wizard.hint = _("Счёт по расчёту сделки: изделия — из расчёта.")
                else:
                    wizard.hint = _("Расчёта нет — пустой счёт: впишите изделия, услуги, количество и цену.")
            elif wizard.partner_id:
                wizard.hint = _("Заведём сделку на «%s» и пустой счёт.") % wizard.partner_id.display_name
            else:
                wizard.hint = _("Выберите сделку или клиента.")

    def action_create(self):
        self.ensure_one()
        lead = self.lead_id
        if not lead:
            if not self.partner_id:
                raise UserError(_("Выберите сделку или клиента."))
            partner = self.partner_id.commercial_partner_id
            lead = self.env["crm.lead"].create({
                "name": _("Счёт — %s") % partner.display_name,
                "type": "opportunity",
                "partner_id": partner.id,
                "user_id": self.env.user.id,
            })
        elif not lead.partner_id and self.partner_id:
            lead.partner_id = self.partner_id.commercial_partner_id
        return lead.action_pmk_new_invoice()
