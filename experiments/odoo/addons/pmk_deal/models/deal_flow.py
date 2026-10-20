# -*- coding: utf-8 -*-
"""Новая воронка: сделка → (расчёт) → счёт, меню «Создать» / «Печать», обзвон
лидов (этап 1 плана «сделка-счёт-расчёт», Антон 20.10.2026).

Стадии: Заявка → Расчёт → Счёт выставлен → Оплачено / в работе → Закрыта.
«КП отправлено» убрана («не нужна»): из расчёта сразу делают счёт.

Стадия идёт за ПОСЛЕДНИМ созданным документом — и назад тоже (Антон: «наверное
откатывает, потом если что изменим логику, менеджер должен потестировать»):
расчёт после счёта вернёт сделку в «Расчёт». Закрытую и проигранную не трогаем.

Меню документов — как в МойСкладе: «Создать ▾» и «Печать ▾» вместо кнопки на
каждый документ. Пункты отдаёт сервер (pmk_doc_menu), модули дописывают свои:
почта — «Письмо» (pmk_mail_ui), счёт — этапом 5.

Лиды — список для обзвона (Антон: «лидов копим для дальнейшего обзвона и
повторного контакта»): статус звонка и дата следующего, напоминание —
запланированная задача «Звонок» ответственному.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

STAGE_SPEC = "crm.stage_lead2"            # «Расчёт»
STAGE_INVOICED = "pmk_deal.stage_invoiced"  # «Счёт выставлен»
CALL_ACTIVITY = "mail.mail_activity_data_call"

CALL_STATES = [
    ("new", "Новый"),
    ("contacted", "Связались"),
    ("recall", "Повторный контакт"),
    ("refused", "Не интересно"),
]


class CrmLeadFlow(models.Model):
    _inherit = "crm.lead"

    pmk_call_state = fields.Selection(
        CALL_STATES, "Обзвон", default="new", tracking=True,
        help="Где мы с этим лидом: новый — ещё не звонили; связались; повторный "
             "контакт — позвонить снова в «Следующий звонок»; не интересно.")
    pmk_next_call = fields.Date(
        "Следующий звонок", tracking=True,
        help="Когда перезвонить. В этот день ответственному приходит задача «Звонок».")

    # ─── Стадия по документу ────────────────────────────────────────────
    def _pmk_doc_stage(self, xmlid):
        """Поставить стадию документа: расчёт → «Расчёт», счёт → «Счёт выставлен».

        Вперёд и назад — за последним документом. Закрытую (выигранную) и
        проигранную (в архиве / won_status lost) не трогаем.
        """
        stage = self.env.ref(xmlid, raise_if_not_found=False)
        if not stage:
            return
        for deal in self:
            if deal.type != "opportunity" or not deal.active or deal.stage_id.is_won:
                continue
            if "won_status" in deal._fields and deal.won_status == "lost":
                continue
            if deal.stage_id != stage:
                deal.stage_id = stage

    # ─── Меню «Создать» / «Печать» ──────────────────────────────────────
    def pmk_doc_menu(self):
        """Пункты меню документов сделки: {"create": [...], "print": [...]}.

        Пункт — {"key", "label", "icon", "method"}; method — метод сделки,
        который вернёт действие. Модули дописывают свои пункты (super()).
        """
        # Пустой набор — несохранённая сделка: «Создать» есть, печатать нечего.
        menu = {
            "create": [
                {"key": "spec", "label": _("Расчёт"), "icon": "fa-calculator",
                 "method": "action_pmk_new_spec"},
                {"key": "task", "label": _("Задача"), "icon": "fa-check-square-o",
                 "method": "action_pmk_new_task"},
            ],
            "print": [],
        }
        # «Письмо» (Антон 20.10: «в случае возникновения вопросов во время
        # расчёта») — когда стоит почта (mail_client): мягко, без зависимости.
        if "mail.client.compose" in self.env:
            menu["create"].insert(1, {"key": "letter", "label": _("Письмо"), "icon": "fa-envelope-o",
                                      "method": "action_pmk_new_letter"})
        if self[:1].spec_ids:
            menu["print"].append({"key": "kp", "label": _("КП (PDF)"), "icon": "fa-file-pdf-o",
                                  "method": "action_pmk_print_kp"})
        return menu

    def action_pmk_new_spec(self):
        """«Создать → Расчёт»: всегда новый расчёт, сделка и клиент подставлены."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Новый расчёт"),
            "res_model": "pmk.metal.spec",
            "views": [(False, "form")],
            "target": "current",
            "context": self._pmk_spec_defaults(),
        }

    def action_pmk_new_task(self):
        """«Создать → Задача»: штатное окно планирования задачи по сделке."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Задача"),
            "res_model": "mail.activity.schedule",
            "views": [(False, "form")],
            "target": "new",
            "context": {"active_model": self._name, "active_ids": self.ids, "active_id": self.id},
        }

    def action_pmk_new_letter(self):
        """«Создать → Письмо»: черновик письма контакту сделки с темой по
        сделке; почта открывается сразу на нём (pmk_mail_ui, step53_open.js,
        params.pmk_compose_id). Ящик — первый, к которому у человека есть
        доступ (вкладка «Доступ» ящика)."""
        self.ensure_one()
        if "mail.client.compose" not in self.env:
            raise UserError(_("Почта не установлена."))
        account = self.env["mail.client.account"].search([], order="id", limit=1)
        if not account:
            raise UserError(_("У вас нет почтового ящика в системе — попросите доступ к ящику."))
        draft = self.env["mail.client.compose"].start(account.id, mode="new")
        to = self.email_from or self.partner_id.email or ""
        self.env["mail.client.compose"].browse(draft["id"]).write({
            "email_to": to, "subject": self.name or ""})
        try:
            action = dict(self.env["ir.actions.actions"]._for_xml_id("pmk_mail_ui.action_mail_sale"))
        except ValueError:
            raise UserError(_("Раздел почты продаж не установлен.")) from None
        action["params"] = dict(action.get("params") or {}, pmk_compose_id=draft["id"])
        return action

    def action_pmk_print_kp(self):
        """«Печать → КП (PDF)» главного расчёта сделки."""
        self.ensure_one()
        from .deal_money import main_spec
        spec = main_spec(self.spec_ids)
        if not spec:
            raise UserError(_("У сделки нет расчёта — КП печатать не из чего."))
        return spec.action_print_quotation()

    # ─── Обзвон ─────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        leads.filtered("pmk_next_call")._pmk_plan_call()
        return leads

    def write(self, vals):
        res = super().write(vals)
        if "pmk_next_call" in vals or "user_id" in vals:
            self._pmk_plan_call()
        return res

    def _pmk_plan_call(self):
        """Задача «Звонок» на дату следующего звонка — одна на лид: дату
        переносим, а не плодим; дату сняли — задачу убираем."""
        call_type = self.env.ref(CALL_ACTIVITY, raise_if_not_found=False)
        if not call_type:
            return
        for lead in self:
            planned = lead.activity_ids.filtered(lambda a: a.activity_type_id == call_type)
            if not lead.pmk_next_call:
                planned.unlink()
                continue
            user = lead.user_id or self.env.user
            if planned:
                planned[:1].write({"date_deadline": lead.pmk_next_call, "user_id": user.id})
                (planned - planned[:1]).unlink()
            else:
                lead.activity_schedule(CALL_ACTIVITY, date_deadline=lead.pmk_next_call,
                                       user_id=user.id, summary=_("Перезвонить"))


class MetalSpecFlow(models.Model):
    _inherit = "pmk.metal.spec"

    def _pmk_moves_deal(self):
        # Контекст pmk_no_doc_stage — не двигать (тесты чужой логики стадий).
        if self.env.context.get("pmk_no_doc_stage"):
            return self.browse()
        """Расчёты, которые двигают стадию сделки. Технический расчёт инженера
        (pmk_tech) — нет: его делают после счёта под производство, и откат
        сделки в «Расчёт» был бы ложным."""
        return self.filtered(lambda s: s.opportunity_id and not (
            "pmk_kind" in s._fields and s.pmk_kind == "tech"))

    # ─── Меню «Создать» / «Печать» расчёта (Антон 20.10: «да делаем») ──
    def pmk_doc_menu(self):
        """Пункты меню документов расчёта — как у сделки и счёта. «Счёт»
        дописывает pmk_orders. Технический расчёт (pmk_tech) КП не печатает:
        у него своя кнопка «Заявка на металл»."""
        spec = self[:1]
        tech = "pmk_kind" in self._fields and spec.pmk_kind == "tech"
        menu = {
            "create": [{"key": "task", "label": _("Задача"), "icon": "fa-check-square-o",
                        "method": "action_pmk_doc_task"}],
            "print": [],
        }
        if "mail.client.compose" in self.env and (not spec or spec.opportunity_id):
            menu["create"].insert(0, {"key": "letter", "label": _("Письмо"), "icon": "fa-envelope-o",
                                      "method": "action_pmk_doc_letter"})
        if not tech:
            menu["print"] += [
                {"key": "kp", "label": _("КП (PDF)"), "icon": "fa-file-pdf-o",
                 "method": "action_print_quotation"},
                {"key": "kp_send", "label": _("Отправить КП письмом"), "icon": "fa-paper-plane-o",
                 "method": "action_send_quotation"},
            ]
        return menu

    def action_pmk_doc_task(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Задача"),
            "res_model": "mail.activity.schedule", "views": [(False, "form")], "target": "new",
            "context": {"active_model": self._name, "active_ids": self.ids, "active_id": self.id},
        }

    def action_pmk_doc_letter(self):
        """«Создать → Письмо» — то же письмо, что из сделки: контакту, тема по сделке."""
        self.ensure_one()
        if not self.opportunity_id:
            raise UserError(_("У расчёта нет сделки — письмо пишите из почты."))
        return self.opportunity_id.action_pmk_new_letter()

    @api.model_create_multi
    def create(self, vals_list):
        specs = super().create(vals_list)
        specs._pmk_moves_deal().opportunity_id._pmk_doc_stage(STAGE_SPEC)
        return specs

    def write(self, vals):
        res = super().write(vals)
        if vals.get("opportunity_id"):
            self._pmk_moves_deal().opportunity_id._pmk_doc_stage(STAGE_SPEC)
        return res
