# -*- coding: utf-8 -*-
"""Лид и мастер «Преобразовать в сделку»: найденный клиент по умолчанию
(шаг З-14, 10.10.2026).

1. КЛИЕНТ ЛИДА. Правило ядра «найти клиента лида»
   (crm.lead._find_matching_partner) ищет только по адресу целиком. Сверху
   — общий поиск по ИНН и домену (models/partner_match.py), но лишь когда
   находка одна: из нескольких не угадываем. Этим правилом пользуются
   мастер «В сделку», мастер массового перевода и мастер КП (sale_crm).

2. МАСТЕР «В СДЕЛКУ». Ядро ставит «Связать с существующим клиентом», только
   если правило выше что-то нашло; иначе «Создать нового клиента» — так у
   Кытмановой (09.10) завёлся бы третий «Трубное решение». Здесь «Создать
   нового» по умолчанию — только когда не нашли никого. Нашли несколько —
   «Связать с существующим» с пустым полем и подсказкой со списком: выбор
   за менеджером. Ничего не запрещено: «Создать нового» выбирается щелчком.

3. ПОЧТА И ТЕЛЕФОН ЛИДА НЕ УХОДЯТ В КАРТОЧКУ ОРГАНИЗАЦИИ. У ядра поля
   лида «Эл. почта» и «Телефон» связаны с клиентом в обе стороны
   (crm_lead.py: _compute_email_from / _inverse_email_from, то же для
   телефона; правило — _get_partner_email_update / _phone_update). Лид от
   Кытмановой с клиентом-филиалом 18 записал бы её личный адрес и мобильный
   из подписи в карточку филиала, а при переводе в сделку ядро, наоборот,
   затёрло бы их общим телефоном филиала; в форме лида горели бы значки
   «адрес клиента отличается». Здесь: клиент — организация, у лида своё
   непустое значение → не синхронизировать. Пустое поле лида организация
   заполняет, как у ядра. С клиентом-человеком всё как у ядра.
   «Своё» — значит не подтянутое из другой карточки: если адрес или телефон
   лида — это адрес или телефон прежнего клиента (до правки в форме) или
   другой компании верхнего уровня, его когда-то поставило ядро, и при смене
   клиента A → B лид берёт почту и телефон B, а значок «отличается» горит,
   как у ядра. Иначе лид с клиентом B хранил бы почту A, и ответ из ленты
   ушёл бы в A (находка проверки 11.10).

4. КОМАНДА «ПРОДАЖИ». Мастер показал команду «Sales»: у записи ядра
   sales_team.team_sales_department русское имя есть, но исходное —
   английское, и его видят все, у кого язык не русский (OdooBot, письма
   робота, новые пользователи до выбора языка). Исходное имя меняем на
   «Продажи», если его никто не переименовывал (_pmk_russian_sales_team,
   вызывается из data/crm_team.xml при каждой установке и обновлении
   модуля; запись ядра — noupdate, обновление crm имя не вернёт).
"""

from odoo import api, fields, models, tools


class CrmLead(models.Model):
    _inherit = "crm.lead"

    def _pmk_client_match(self):
        """Общий поиск клиента по адресу лида (ИНН в лиде не ищем — его
        ищет лид из письма по тексту письма)."""
        self.ensure_one()
        return self.env["res.partner"]._pmk_find_company(
            email=self.email_normalized or self.email_from)

    def _find_matching_partner(self):
        partner = super()._find_matching_partner()
        if partner or not (self.email_normalized or self.email_from):
            return partner
        match = self._pmk_client_match()
        if len(match["partners"]) == 1:
            return match["partners"]
        return partner

    def _pmk_value_from_other_card(self, fname):
        """Почта (fname="email") или телефон ("phone") лида взяты из другой
        карточки: прежнего клиента лида (до правки в форме) или компании
        (человека) верхнего уровня вне компании нынешнего клиента. Контакт
        внутри чужой компании не в счёт: это может быть тот же человек,
        заведённый в дубле (Кытманова в «ТРУБНОЕ РЕШЕНИЕ»)."""
        self.ensure_one()
        value = self.email_from if fname == "email" else self.phone
        if not value:
            return False
        if fname == "email":
            key = tools.email_normalize(value) or value

            def same(partner):
                return bool(partner.email) and (
                    (tools.email_normalize(partner.email) or partner.email) == key)
        else:
            key = self._phone_format(fname="phone") or value

            def same(partner):
                return bool(partner.phone) and (
                    partner.phone == value
                    or partner._phone_format(fname="phone") == key)
        previous = self._origin.partner_id
        if previous and previous != self.partner_id and same(previous):
            return True
        Partner = self.env["res.partner"].sudo().with_context(active_test=False)
        commercial = self.partner_id.commercial_partner_id
        if fname == "email":
            search = [("email_normalized", "=", key)] if "@" in key else [("email", "=", value)]
        else:
            search = ["|", ("phone", "=", value)]
            search += [("phone_sanitized", "=", key)] if "phone_sanitized" in Partner._fields \
                else [("phone", "=", key)]
        return bool(Partner.search_count(
            [("parent_id", "=", False), ("id", "not in", commercial.ids)] + search, limit=1))

    def _pmk_keep_own_value(self, fname):
        """У клиента-организации лид хранит своё значение (см. п. 3)."""
        return bool(self.partner_id.is_company
                    and not self._pmk_value_from_other_card(fname))

    def _get_partner_email_update(self, force_void=True):
        update = super()._get_partner_email_update(force_void=force_void)
        if update and self.email_from and self._pmk_keep_own_value("email"):
            return False
        return update

    def _get_partner_phone_update(self, force_void=True):
        update = super()._get_partner_phone_update(force_void=force_void)
        if update and self.phone and self._pmk_keep_own_value("phone"):
            return False
        return update

    def _handle_partner_assignment(self, force_partner_id=False, create_missing=True, with_parent=None):
        """Лиды, у которых клиент уже тот самый, повторно не присваиваем:
        запись того же клиента заново запускает пересчёт почты и телефона
        лида от карточки. У такого лида клиент есть — создавать некого."""
        leads = self
        if force_partner_id:
            leads = self.filtered(lambda lead: lead.partner_id.id != force_partner_id)
        if leads:
            super(CrmLead, leads)._handle_partner_assignment(
                force_partner_id=force_partner_id, create_missing=create_missing,
                with_parent=with_parent)


# Письма архивной карточке ядро не отправляет и не говорит об этом
# (mail_thread._notify_get_recipients пропускает неактивных).
ARCHIVE_TAIL = "верните карточку из архива, иначе письма с КП клиенту не уйдут"


class CrmLeadToOpportunity(models.TransientModel):
    _inherit = "crm.lead2opportunity.partner"

    pmk_client_hint = fields.Char("Подсказка", compute="_compute_pmk_client_hint")

    @api.depends("lead_id")
    def _compute_action(self):
        super()._compute_action()
        for convert in self:
            if convert.action == "create" and convert.lead_id \
                    and convert.lead_id._pmk_client_match()["partners"]:
                convert.action = "exist"

    @api.depends("lead_id", "partner_id", "action")
    def _compute_pmk_client_hint(self):
        """Подсказка над выбором клиента. Лид без клиента — что нашли по
        домену или ИНН. Лид с клиентом (лид из письма ставит его сам) —
        только если карточка в архиве: письма архивной карточке Odoo молча
        не отправляет (mail_thread._notify_get_recipients), а пометка в ленте
        лида легко теряется."""
        archive_tail = ARCHIVE_TAIL
        for convert in self:
            lead = convert.lead_id
            hint = ""
            chosen = convert.partner_id
            if convert.action != "exist":
                convert.pmk_client_hint = hint
                continue
            if lead and not lead.partner_id:
                match = lead._pmk_client_match()
                partners = match["partners"]
                if len(partners) > 1 or (partners and chosen in partners):
                    hint = self.env["res.partner"]._pmk_match_text(match)
            if chosen and not chosen.active:
                if hint:
                    hint += " — " + archive_tail
                else:
                    hint = "Клиент «%s» в архиве — %s" % (chosen.display_name, archive_tail)
            convert.pmk_client_hint = hint


class CrmTeam(models.Model):
    _inherit = "crm.team"

    @api.model
    def _pmk_russian_sales_team(self):
        team = self.env.ref("sales_team.team_sales_department", raise_if_not_found=False)
        if not team:
            return
        source = team.with_context(lang="en_US")
        if source.name == "Sales":
            source.name = "Продажи"
