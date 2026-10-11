# -*- coding: utf-8 -*-
"""Штатный мастер «Объединить контакты»: сравнить и не потерять
(шаги З-14, 10.10.2026, и З-17, 11.10.2026).

МАСТЕР ЯДРА (base/wizard/base_partner_merge.py) переводит на оставшуюся
карточку всё, что ссылается на остальные (лиды, сделки, расчёты, заказы,
письма в ленте, контактные лица), а поля берёт так: заполненное у
оставшейся не трогает, пустое берёт у объединяемых (_update_values). Всё
прочее — второй телефон, другая почта, примечание — теряется молча, а
объединяемые карточки удаляются: отменить нельзя.

ЧТО ЗДЕСЬ (шаг З-17, Антон 11.10: «нужно сопоставлять живые данные — ИНН,
телефон… либо объединять телефоны, либо принимать какой-то ИНН как истинно
верный»):

  • Разные непустые ИНН среди выбранных — красная плашка «Разные ИНН: … это
    разные юрлица, объединять нельзя», кнопка «Объединить контакты» спрятана,
    пока лишнюю карточку не уберут крестиком; на сервере та же проверка
    (_merge) для всех, админа тоже. ИСКЛЮЧЕНИЕ из правила «сигнал показывает,
    а не запрещает»: объединение необратимо, а склеенные два юрлица портят
    счета, УПД и сверку — это не «наблюдать», а ошибка данных без отката.
    Одинаковый ИНН или ИНН только у одной — как обычно.
  • Какая карточка останется по умолчанию: с ИНН → больше документов (лиды
    и сделки, заказы, расчёты, закупки — с архивом и контактами) → активная
    → заведена раньше (меньший номер). Ядро оставляло «активную самую
    свежую» — для 18/159 это была бы 159 с голым названием из таблицы. В
    окне подсказка «Останется: … — почему», выбрать другую можно.
  • Не терять: телефон и почта исходной карточки, которых у оставшейся и её
    контактов нет, — контактным лицом «Контакт из «…»» внутри компании (у
    физлица и ИП — строкой примечания); сайт, адрес для прайса, КПП, адреса
    и примечание — строкой «Из объединения ДД.ММ.ГГГГ — «…» (№ n)» в
    примечание. Всё это и список объединённых — одной заметкой в ленту:
    вкладка «Заметки» карточки спрятана шагом 28, и лента — место, где это
    видно. В конце заметки — «Сверьте по ИНН».
  • Английская заметка mail «Объединено со следующими партнерами: ['X <n/a>
    (ID 20)']» (список питона) заменена нашей.
  • После ручного объединения — карточка, которая осталась, а не экран ядра
    «Больше нет контактов…» с залитой «Удалить дубликаты других контактов».
    Пакетный режим ядра (state option/finished) не трогаем.
  • Доводка 11.10:
      – контактное лицо «Контакт из «…»» заводится в контексте без default_*
        и с is_company=False: из «Клиенты → Действия → Объединить» приходит
        контекст списка (default_is_company, res_partner_search_mode), и оно
        стало бы организацией и отдельным клиентом;
      – «Объединить автоматически» ядра (пакетный проход с cr.commit после
        группы) группу с разными ИНН пропускает с записью в журнал, а не
        обрывается на ней;
      – предпросмотр «Не потеряется» считает «организацию», как ядро (у кого-то
        из выбранных is_company — оставшаяся станет организацией);
      – карточек меньше двух — кнопки «Объединить контакты» нет, на сервере
        отказ (ядро молча ничего не делало, а мы открыли бы карточку);
      – примечание исходной в ленте целиком (вкладка «Заметки» скрыта);
      – один ИНН и разные КПП — жёлтый сигнал «возможно, головная и филиал»,
        НЕ запрет; колонка КПП в окне;
      – подсказка «больше документов» называет, из чего число.

Права — как у ядра: мастер только у «Управления контактами»
(base.group_partner_manager); почта у объединяемых разная — только
администратор (ядро; здесь та же проверка, но русским текстом).
"""

import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools import merge_rules

_logger = logging.getLogger(__name__)

# Подписи полей, которые ядро заполняет из объединяемых, когда у оставшейся
# пусто: так в заметке видно, откуда взялся ИНН или телефон.
FILLED_LABELS = (
    ("vat", "ИНН"), ("phone", "Телефон"), ("email", "Эл. почта"),
    ("website", "Сайт"), ("pmk_price_email", "Адрес для запроса прайса"),
    ("kpp", "КПП"), ("ogrn", "ОГРН"), ("pmk_legal_name", "Полное наименование"),
    ("pmk_legal_address", "Юридический адрес"), ("city", "Город"),
)


class ResPartnerMergeLabel(models.Model):
    _inherit = "res.partner"

    # Колонка «В архиве» окна объединения: словом, а не галочкой «Активно»
    # (цвет — серая строка — повторён словом). Не хранится.
    pmk_archived_label = fields.Char("В архиве", compute="_compute_pmk_archived_label")

    @api.depends("active")
    def _compute_pmk_archived_label(self):
        for partner in self:
            partner.pmk_archived_label = "" if partner.active else "Да"


class PartnerMergeWizard(models.TransientModel):
    _inherit = "base.partner.merge.automatic.wizard"

    pmk_inn_conflict = fields.Char(
        "Разные ИНН", compute="_compute_pmk_inn_conflict",
        help="Среди выбранных карточек разные ИНН — это разные юрлица.")
    pmk_dst_hint = fields.Char("Какая останется", compute="_compute_pmk_hints")
    pmk_carry_hint = fields.Char("Что перенесётся", compute="_compute_pmk_hints")
    pmk_kpp_hint = fields.Char(
        "Один ИНН, разные КПП", compute="_compute_pmk_inn_conflict",
        help="Сигнал, не запрет: возможно, головная организация и филиал.")
    pmk_partner_count = fields.Integer("Карточек", compute="_compute_pmk_partner_count")

    # ------------------------------------------------------------------
    # правила
    # ------------------------------------------------------------------
    @api.model
    def _pmk_conflict_text(self, partners):
        """Текст плашки «Разные ИНН» или пусто."""
        conflict = merge_rules.inn_conflict(
            [{"id": p.id, "name": p.name, "vat": p.vat} for p in partners])
        if not conflict:
            return ""
        parts = ", ".join(
            "%s (%s)" % (inn, ", ".join("«%s»" % name for name in names))
            for inn, names in conflict)
        return _("Разные ИНН: %s. Это разные юрлица — объединять нельзя. Уберите "
                 "лишнюю карточку крестиком или исправьте ИНН в карточке.", parts)

    @api.model
    def _pmk_kpp_text(self, partners):
        """Жёлтый сигнал «Один ИНН, разные КПП» или пусто. Не запрет: у
        головной и филиала один ИНН, а КПП у филиала свой; после объединения
        КПП филиала уйдёт строкой в примечание, а его документы — на
        оставшуюся. Пусть человек это увидит до необратимой склейки."""
        if "kpp" not in partners._fields:
            return ""
        by_inn = {}
        for partner in partners:
            key = merge_rules.inn_key(partner.vat)
            kpp = (partner.kpp or "").strip()
            if key and kpp:
                by_inn.setdefault(key, {}).setdefault(kpp, []).append(partner.name or "")
        parts = []
        for kpps in by_inn.values():
            if len(kpps) > 1:
                parts.append(", ".join(
                    "%s у %s" % (kpp, ", ".join("«%s»" % name for name in names))
                    for kpp, names in kpps.items()))
        if not parts:
            return ""
        return _("Один ИНН, разные КПП: %s. Возможно, это головная организация и "
                 "филиал — у филиала свой КПП, и в его документах он нужен. "
                 "Проверьте, прежде чем объединять.", "; ".join(parts))

    @api.model
    def _pmk_rank(self, partners):
        """Какая карточка останется по умолчанию: {"dst", "reason", "runner",
        "docs"} — см. merge_rules.pick_destination."""
        partners = partners.with_context(active_test=False).exists()
        docs = self.env["pmk.partner.duplicate"]._pmk_documents(partners)
        rows = [{"id": p.id, "inn": merge_rules.inn_key(p.vat),
                 "docs": docs.get(p.id, 0), "active": p.active} for p in partners]
        result = merge_rules.pick_destination(rows)
        result["docs"] = docs
        return result

    @api.model
    def _pmk_reason_text(self, rank, partners):
        Partner = partners.with_context(active_test=False)
        dst, runner = Partner.browse(rank["dst"]), Partner.browse(rank["runner"])
        reason = rank["reason"]
        if reason == "inn":
            return _("у неё есть ИНН %s", dst.vat)
        if reason == "docs":
            return _("к ней привязано больше документов (лиды и сделки, в том числе "
                     "архивные, заказы, расчёты, закупки — вместе с контактными лицами): "
                     "%(dst)s против %(other)s у «%(name)s»",
                     dst=rank["docs"].get(dst.id, 0), other=rank["docs"].get(runner.id, 0),
                     name=runner.name)
        if reason == "active":
            return _("она активная, а «%s» в архиве", runner.name)
        if reason == "oldest":
            return _("она заведена раньше «%s»", runner.name)
        return ""

    def _pmk_snapshot(self, partner, names):
        values = {}
        for name in names:
            if name in partner._fields:
                value = partner[name]
                values[name] = value.id if isinstance(value, models.BaseModel) else value
        return values

    def _pmk_note_fields(self, partner):
        return [(name, label) for name, label in merge_rules.NOTE_FIELDS
                if name in partner._fields]

    def _pmk_plan_fields(self, partner):
        return ([name for name, _label in merge_rules.CONTACT_FIELDS]
                + [name for name, _label in self._pmk_note_fields(partner)]
                + [merge_rules.COMMENT_FIELD])

    def _pmk_carry_plan(self, srcs, dst_final, children, partner, company):
        names = self._pmk_plan_fields(partner)
        rows = []
        for src in srcs:
            row = self._pmk_snapshot(src, names)
            row.update(id=src.id, name=src.name)
            rows.append(row)
        return merge_rules.carry_plan(
            dst_final, rows,
            children=[{"phone": c.phone, "email": c.email} for c in children],
            fields=self._pmk_note_fields(partner),
            company=bool(company))

    # ------------------------------------------------------------------
    # окно
    # ------------------------------------------------------------------
    @api.depends("partner_ids", "partner_ids.vat", "partner_ids.kpp")
    def _compute_pmk_inn_conflict(self):
        for wizard in self:
            partners = wizard.partner_ids._origin.with_context(active_test=False)
            several = len(partners) > 1
            wizard.pmk_inn_conflict = self._pmk_conflict_text(partners) if several else ""
            wizard.pmk_kpp_hint = (self._pmk_kpp_text(partners)
                                   if several and not wizard.pmk_inn_conflict else "")

    @api.depends("partner_ids")
    def _compute_pmk_partner_count(self):
        """Сколько карточек в окне: меньше двух — объединять нечего, кнопки нет."""
        for wizard in self:
            wizard.pmk_partner_count = len(wizard.partner_ids)

    @api.depends("partner_ids", "dst_partner_id")
    def _compute_pmk_hints(self):
        for wizard in self:
            wizard.pmk_dst_hint = wizard.pmk_carry_hint = ""
            partners = wizard.partner_ids._origin.with_context(active_test=False)
            dst = wizard.dst_partner_id._origin.with_context(active_test=False)
            if len(partners) < 2 or dst not in partners:
                continue
            rank = self._pmk_rank(partners)
            if rank["dst"] == dst.id:
                reason = self._pmk_reason_text(rank, partners)
                wizard.pmk_dst_hint = (_("Останется: «%(name)s» — %(why)s.", name=dst.name, why=reason)
                                       if reason else _("Останется: «%s».", dst.name))
            else:
                best = partners.browse(rank["dst"])
                wizard.pmk_dst_hint = _(
                    "Останется: «%(name)s» — выбрана вручную. По правилу осталась бы "
                    "«%(best)s»: %(why)s.", name=dst.name, best=best.name,
                    why=self._pmk_reason_text(rank, partners))
            wizard.pmk_carry_hint = self._pmk_carry_text(partners, dst)

    def _pmk_carry_text(self, partners, dst):
        """Предпросмотр: что из убираемых карточек перенесётся, а не пропадёт."""
        srcs = partners - dst
        names = self._pmk_plan_fields(dst)
        dst_final = merge_rules.final_values(
            self._pmk_snapshot(dst, names), [self._pmk_snapshot(s, names) for s in srcs], names)
        children = partners.with_context(active_test=False).child_ids
        # Ядро пишет в оставшуюся is_company последнее непустое значение
        # (поле с copy): физлицо, объединённое с организацией, станет
        # организацией — тогда телефон и почта уйдут контактным лицом.
        company = any(partners.mapped("is_company"))
        plan = self._pmk_carry_plan(srcs, dst_final, children, dst, company)
        if not plan:
            return ""
        contacts = [item["name"] for item in plan if item["contact"]]
        contact_labels = [label.lower() for name, label in merge_rules.CONTACT_FIELDS
                          if any(name in item["contact"] for item in plan)]
        note_labels = []
        for item in plan:
            for label, _value in item["note"]:
                if label.lower() not in note_labels:
                    note_labels.append(label.lower())
            if item["comment"] and "примечание" not in note_labels:
                note_labels.append("примечание")
        parts = []
        if contacts:
            parts.append(_("%(what)s из %(names)s → контактное лицо",
                           what=" и ".join(contact_labels),
                           names=", ".join("«%s»" % name for name in contacts)))
        if note_labels:
            parts.append(_("%s → в примечание карточки и в ленту", ", ".join(note_labels)))
        return _("Не потеряется: %s.", "; ".join(parts))

    @api.model
    def default_get(self, fields):
        result = super().default_get(fields)
        context = self.env.context
        active_ids = context.get("active_ids") or []
        if ("dst_partner_id" not in fields or context.get("active_model") != "res.partner"
                or not active_ids):
            return result
        dst = context.get("pmk_merge_dst_id")
        if dst and dst in active_ids:
            result["dst_partner_id"] = dst
        else:
            # И из «Возможных дублей», и из штатного «Действия → Объединить».
            partners = self.env["res.partner"].with_context(active_test=False).browse(active_ids)
            best = self._pmk_rank(partners)["dst"]
            if best:
                result["dst_partner_id"] = best
        return result

    @api.onchange("partner_ids")
    def _onchange_pmk_partner_ids(self):
        """Оставшуюся убрали крестиком — выбрать заново по тому же правилу."""
        partners = self.partner_ids._origin.with_context(active_test=False)
        if self.dst_partner_id._origin in partners:
            return
        self.dst_partner_id = self._pmk_rank(partners)["dst"] if partners else False

    # ------------------------------------------------------------------
    # объединение
    # ------------------------------------------------------------------
    def _merge(self, partner_ids, dst_partner=None, extra_checks=True):
        """Разные ИНН — нельзя (для всех); почта разная — только админ (как у
        ядра, но русским текстом). Строки «Возможных дублей» объединяемых
        карточек — убрать.

        Мастер переводит на оставшуюся карточку ВСЕ ссылки на объединяемые,
        в том числе строки нашего экрана (_update_foreign_keys идёт по всем
        внешним ключам на res_partner), и в списке стояли бы две строки
        одной карточки. Группа разобрана — её строки не нужны; остальное
        покажет повторное «Возможные дубли». Ошибка мастера откатит и это."""
        ids = [getattr(item, "id", item) for item in partner_ids or ()]
        partners = self.env["res.partner"].with_context(active_test=False).browse(ids).exists()
        if 2 <= len(partners) <= 3:
            conflict = self._pmk_conflict_text(partners)
            if conflict and self.env.context.get("pmk_merge_auto"):
                # «Объединить автоматически» ядра: отказ оборвал бы весь проход
                # (после каждой группы cr.commit) и на повторе упёрся бы в ту
                # же группу. Группу с разными ИНН пропускаем, остальные идут.
                _logger.warning("Пропущена группа %s при автоматическом объединении: %s",
                                partners.ids, conflict)
                return None
            if conflict:
                raise UserError(conflict)
            if (extra_checks and not self.env.is_admin()
                    and len(set(partner.email for partner in partners)) > 1):
                raise UserError(_(
                    "У карточек разная эл. почта — объединяет их только администратор. "
                    "Покажите ему эту группу."))
        if len(ids) > 1:
            self.env["pmk.partner.duplicate"].sudo().search(
                [("partner_id", "in", ids)]).unlink()
        return super()._merge(partner_ids, dst_partner=dst_partner, extra_checks=extra_checks)

    @api.model
    def _update_values(self, src_partners, dst_partner):
        """После ядра — перенести то, что оно потеряло бы, и написать заметку.

        К этому моменту контактные лица исходных уже у оставшейся
        (_update_foreign_keys), а сами исходные ещё не удалены."""
        names = (self._pmk_plan_fields(dst_partner)
                 + [name for name, _label in FILLED_LABELS]
                 + ["pmk_price_email_state"])
        before = self._pmk_snapshot(dst_partner, list(dict.fromkeys(names)))
        result = super()._update_values(src_partners, dst_partner)
        self._pmk_carry_over(src_partners, dst_partner, before)
        return result

    def _pmk_carry_over(self, srcs, dst, before):
        dst = dst.with_context(active_test=False)
        # Контакты исходных ядро перевело на оставшуюся SQL-запросом
        # (_update_foreign_keys_generic) — кэш списка контактов мог устареть.
        dst.invalidate_recordset(["child_ids"])
        names = self._pmk_plan_fields(dst)
        dst_final = self._pmk_snapshot(dst, names)
        plan = self._pmk_carry_plan(srcs, dst_final, dst.child_ids, dst, dst.is_company)
        # Контекст без default_* и режима поиска: из «Действия → Объединить»
        # в списке «Клиенты» приходят default_is_company=True и
        # res_partner_search_mode='customer' (контекст списка), и контактное
        # лицо стало бы организацией и отдельным клиентом.
        clean = {key: value for key, value in self.env.context.items()
                 if not key.startswith("default_") and key != "res_partner_search_mode"}
        Partner = self.env["res.partner"].with_context(clean, no_vat_validation=True)
        today = fields.Date.context_today(self).strftime("%d.%m.%Y")

        # Состояние адреса для прайса: ядро взяло адрес у исходной, а
        # состояние (selection, всегда непустое) — у оставшейся, то есть
        # «Не проверен» вместо «Проверен». Пишем оба поля одним write:
        # иначе pmk_purchase.write снова сбросит состояние в «Не проверен».
        if ("pmk_price_email_state" in dst._fields and not before.get("pmk_price_email")
                and dst.pmk_price_email):
            key = merge_rules.value_key("pmk_price_email", dst.pmk_price_email)
            for src in srcs[::-1]:  # у ядра побеждает последнее непустое
                if merge_rules.value_key("pmk_price_email", src.pmk_price_email) == key:
                    if src.pmk_price_email_state != dst.pmk_price_email_state:
                        dst.write({"pmk_price_email": dst.pmk_price_email,
                                   "pmk_price_email_state": src.pmk_price_email_state})
                    break

        contacts = {}
        blocks = []
        for item in plan:
            if item["contact"]:
                contacts[item["id"]] = Partner.create({
                    "name": _("Контакт из «%s»", item["name"]),
                    "parent_id": dst.id,
                    "type": "contact",
                    "is_company": False,
                    **item["contact"],
                })
            if item["note"] or item["comment"]:
                block = Markup("<p><b>%s</b></p>") % _(
                    "Из объединения %(date)s — «%(name)s» (№ %(id)s):",
                    date=today, name=item["name"], id=item["id"])
                if item["note"]:
                    block += Markup("<ul>%s</ul>") % Markup("").join(
                        Markup("<li>%s: %s</li>") % (label, value) for label, value in item["note"])
                if item["comment"]:
                    block += Markup("<div>%s</div>") % Markup(item["comment"])
                blocks.append(block)
        if blocks:
            dst.write({"comment": Markup(dst.comment or "") + Markup("").join(blocks)})

        # Примечание оставшейся было пустым — ядро молча взяло его у
        # объединённой (_update_values), и carry_plan его уже не видит.
        # Вкладка «Заметки» спрятана шагом 28: показать в ленте.
        inherited = ""
        if (not merge_rules.plain_text(before.get(merge_rules.COMMENT_FIELD) or "")
                and merge_rules.plain_text(dst_final.get(merge_rules.COMMENT_FIELD) or "")):
            inherited = dst_final[merge_rules.COMMENT_FIELD]
        dst.message_post(
            body=self._pmk_merge_note(srcs, dst, plan, contacts, before, inherited),
            subtype_xmlid="mail.mt_note")

    def _pmk_merge_note(self, srcs, dst, plan, contacts, before, inherited=""):
        """Заметка в ленту оставшейся карточки — всё, что видно человеку:
        кого объединили, что куда перенесено, что сделать дальше."""
        merged = []
        for src in srcs:
            inside = [_("№ %s", src.id)]
            if src.vat:
                inside.append(_("ИНН %s", src.vat))
            if not src.active:
                inside.append(_("в архиве"))
            merged.append("«%s» (%s)" % (src.name, ", ".join(inside)))
        body = Markup("<p>%s</p>") % _("Объединены с этой карточкой: %s.", "; ".join(merged))

        filled = [label for name, label in FILLED_LABELS
                  if name in dst._fields and not before.get(name) and dst[name]]
        if filled:
            body += Markup("<p>%s</p>") % _(
                "Пустые поля заполнены из объединённых: %s.", ", ".join(filled))

        if inherited:
            body += Markup("<p>%s</p>") % _(
                "Примечание было пустым — взято из объединённой: «%s».",
                merge_rules.plain_text(inherited))

        lines = []
        for item in plan:
            parts = []
            contact = contacts.get(item["id"])
            if contact:
                values = ", ".join(str(value) for value in item["contact"].values())
                parts.append(_("%(values)s → контактное лицо «%(contact)s»",
                               values=values, contact=contact.name))
            notes = ["%s %s" % (label.lower(), value) for label, value in item["note"]]
            if item["comment"]:
                # Целиком: вкладка «Заметки» спрятана шагом 28, лента —
                # единственное место, где примечание видно.
                notes.append(_("примечание «%s»", merge_rules.plain_text(item["comment"])))
            if notes:
                parts.append(_("%s → в примечание карточки", "; ".join(notes)))
            lines.append(Markup("<li>%s</li>") % _(
                "из «%(name)s»: %(what)s", name=item["name"], what="; ".join(parts)))
        if lines:
            body += Markup("<p>%s</p><ul>%s</ul>") % (_("Перенесено, чтобы не потерять:"),
                                                       Markup("").join(lines))
        elif not inherited:
            body += Markup("<p>%s</p>") % _(
                "Всё, что было в объединённых карточках, у этой уже есть.")

        if "pmk_legal_name" in dst._fields:  # pmk_dadata стоит — кнопки есть
            if not dst.vat:
                hint = _("ИНН не указан — впишите его на вкладке «Реквизиты» и "
                         "нажмите «Заполнить по ИНН».")
            elif dst.pmk_legal_name or dst.kpp or dst.ogrn:
                hint = _("Сверьте реквизиты: вкладка «Реквизиты» → «Сверить по ИНН».")
            else:
                hint = _("Заполните реквизиты: вкладка «Реквизиты» → «Заполнить по ИНН».")
            body += Markup("<p>%s</p>") % hint
        return body

    def _log_merge_operation(self, src_partners, dst_partner):
        """Без super: mail пишет в ленту английскую строку со списком питона
        («Объединено со следующими партнерами: ['X <n/a> (ID 20)']»). Наша
        заметка уже в ленте (_update_values → _pmk_merge_note)."""
        _logger.info("(uid = %s) merged the partners %r with %s",
                     self.env.uid, src_partners.ids, dst_partner.id)

    def action_start_automatic_process(self):
        """«Объединить автоматически» ядра: группы с разными ИНН пропускаются
        (см. _merge), а не обрывают весь проход."""
        return super(PartnerMergeWizard, self.with_context(pmk_merge_auto=True)) \
            .action_start_automatic_process()

    def parent_migration_process_cb(self):
        return super(PartnerMergeWizard, self.with_context(pmk_merge_auto=True)) \
            .parent_migration_process_cb()

    def action_merge(self):
        """Ручное объединение — открыть оставшуюся карточку вместо экрана ядра
        «Больше нет контактов…». Пакетный режим (строки line_ids) — как у ядра."""
        manual = not self.current_line_id and not self.line_ids
        if manual and self.state == "selection" and len(self.partner_ids) < 2:
            # Ядро при одной карточке молча ничего не делает, а мы открыли бы
            # её — будто объединение прошло.
            raise UserError(_("Отметьте минимум две карточки: объединять пока нечего."))
        manual = manual and bool(self.partner_ids)
        result = super().action_merge()
        dst = self.dst_partner_id.with_context(active_test=False)
        if manual and dst.exists():
            return {
                "type": "ir.actions.act_window",
                "name": dst.display_name,
                "res_model": "res.partner",
                "res_id": dst.id,
                "views": [[False, "form"]],
                "target": "current",
            }
        return result
