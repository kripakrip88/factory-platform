# -*- coding: utf-8 -*-
"""Объединение клиентов: сравнить и не потерять (шаг З-17, 11.10.2026).

Ловим:
  • окно мастера: колонки по-русски (Название, ИНН, Телефон, Эл. почта,
    Город, Сделок, Счетов, В архиве), без «Является компанией», «Страна» и
    «ID» в нашем виде — они под «вернуть убранное»; «Пропустить» — только в
    пакетном режиме; одна залитая кнопка;
  • разные непустые ИНН — плашка, кнопка «Объединить контакты» спрятана, на
    сервере отказ (и для админа); один ИНН или ИНН у одной — объединяется;
  • какая карточка останется: с ИНН → больше документов → активная →
    меньший номер; подсказка «Останется: … — почему»; убрали крестиком —
    выбрана заново; и из «Возможных дублей», и из штатного «Объединить»;
  • не терять: телефон и почта исходной — контактным лицом (у физлица —
    строкой примечания), сайт, адрес для прайса и примечание — в
    примечание; состояние адреса для прайса переезжает с адресом; одна
    заметка в ленте по-русски вместо английской строки mail; лиды и письма
    переезжают (ядро);
  • после ручного объединения — карточка, которая осталась;
  • права: мастер — только «Управление контактами»; почта разная — только
    администратор, отказ по-русски;
  • доводка 11.10: «Действия → Объединить» из списка «Клиенты» (контекст
    default_is_company, res_partner_search_mode) не делает контактное лицо
    организацией и клиентом; «Объединить автоматически» ядра пропускает
    группу с разными ИНН, а не падает; предпросмотр считает «организацию»,
    как ядро; карточек меньше двух — кнопки нет, на сервере отказ;
    примечание в ленте целиком; один ИНН и разные КПП — жёлтый сигнал (не
    запрет), колонка КПП; подсказка называет, из чего число документов;
    архивную карточку можно выбрать обратно (active_test=False у поля).
Правила без базы — test_merge_rules.py. Глазами (плашки в обеих темах,
окно «Возможные дубли» → «Объединить…») — основной агент на копии.
"""

from unittest.mock import patch

from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.base.wizard.base_partner_merge import BasePartnerMergeAutomaticWizard

WIZARD = "base.partner.merge.automatic.wizard"
REMOVED = "pmk_theme.group_pmk_removed"


@tagged("post_install", "-at_install")
class TestZ17Merge(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"].with_context(no_vat_validation=True)
        cls.manager = new_test_user(
            cls.env, login="z17_partner_manager",
            groups="base.group_user,base.group_partner_manager,sales_team.group_sale_salesman")

    # ------------------------------------------------------------------
    def _company(self, name, **values):
        values.setdefault("is_company", True)
        return self.Partner.create(dict(values, name=name))

    def _wizard(self, partners, env=None, **context):
        env = env or self.env
        return env[WIZARD].with_context(
            active_model="res.partner", active_ids=partners.ids, active_id=partners.ids[0],
            active_test=False, **context).create({})

    def _arch(self, user):
        view = self.env.ref("base.base_partner_merge_automatic_wizard_form")
        arch = self.env[WIZARD].with_user(user).get_views([(view.id, "form")])["views"]["form"]["arch"]
        return etree.fromstring(arch)

    def _columns(self, root):
        return [(node.get("name"), node.get("string"))
                for node in root.xpath("//field[@name='partner_ids']/list/field")]

    # ------------------------------------------------------------------
    # окно
    # ------------------------------------------------------------------
    def test_columns_in_russian(self):
        root = self._arch(self.manager)
        columns = self._columns(root)
        self.assertEqual(columns, [
            ("display_name", "Название"), ("vat", "ИНН"), ("kpp", "КПП"), ("phone", "Телефон"),
            ("email", "Эл. почта"), ("city", "Город"), ("pmk_deal_count", "Сделок"),
            ("sale_order_count", "Счетов"), ("pmk_archived_label", "В архиве"),
        ])
        texts = " ".join(filter(None, (node.get("string") for node in root.iter()
                                      if isinstance(node.tag, str))))
        for word in ("Display Name", "Tax ID", "Merge the following contacts"):
            self.assertNotIn(word, texts)
        dst = root.xpath("//field[@name='dst_partner_id']")[0]
        self.assertEqual(dst.get("string"), "Останется карточка")
        self.assertNotIn("partner_show_db_id", dst.get("context") or "", "Без «(ID 9)».")
        self.assertFalse(safe_eval(dst.get("context"))["active_test"],
                         "Архивную карточку можно выбрать обратно.")

    def test_removed_columns_come_back(self):
        self.manager.write({"group_ids": [Command.link(self.env.ref(REMOVED).id)]})
        names = [name for name, _label in self._columns(self._arch(self.manager))]
        for name in ("id", "is_company", "country_id"):
            self.assertIn(name, names, "Вернуть убранное возвращает колонки ядра.")

    def test_buttons(self):
        root = self._arch(self.manager)
        merge = root.xpath("//footer/button[@name='action_merge']")[0]
        skip = root.xpath("//footer/button[@name='action_skip']")[0]
        self.assertEqual(merge.get("string"), "Объединить контакты")
        expression = merge.get("invisible")
        values = {"state": "selection", "pmk_inn_conflict": False, "pmk_partner_count": 2}
        self.assertTrue(safe_eval(expression, dict(values, pmk_inn_conflict="Разные ИНН")))
        self.assertFalse(safe_eval(expression, values))
        self.assertTrue(safe_eval(expression, dict(values, pmk_partner_count=1)),
                        "Одна карточка — объединять нечего, кнопки нет.")
        self.assertTrue(safe_eval(skip.get("invisible"),
                                  {"state": "selection", "current_line_id": False}),
                        "Ручной режим — без «Пропустить».")
        self.assertFalse(safe_eval(skip.get("invisible"),
                                   {"state": "selection", "current_line_id": 7}))
        primary = [node for node in root.xpath("//footer/button")
                   if "oe_highlight" in (node.get("class") or "")
                   or "btn-primary" in (node.get("class") or "")]
        selection = [node for node in primary if not safe_eval(
            node.get("invisible") or "False",
            {"state": "selection", "pmk_inn_conflict": False, "current_line_id": False,
             "pmk_partner_count": 2})]
        self.assertEqual(len(selection), 1, "Одна залитая кнопка в окне.")
        alert = root.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' alert-danger ')]")[0]
        self.assertEqual(alert.get("invisible"), "not pmk_inn_conflict")

    # ------------------------------------------------------------------
    # разные ИНН
    # ------------------------------------------------------------------
    def test_different_inn_blocked(self):
        a = self._company("А ГРУПП МАРКЕТ З17", vat="7717625418")
        b = self._company("А ГРУПП З17", vat="2721073821")
        wizard = self._wizard(a | b)
        self.assertIn("Разные ИНН", wizard.pmk_inn_conflict)
        self.assertIn("7717625418", wizard.pmk_inn_conflict)
        self.assertIn("разные юрлица", wizard.pmk_inn_conflict)
        with self.assertRaises(UserError) as caught:
            wizard.action_merge()
        self.assertIn("Разные ИНН", str(caught.exception))
        self.assertTrue(a.exists() and b.exists(), "Ничего не объединено.")
        # Убрали лишнюю крестиком — можно.
        wizard.partner_ids = [Command.unlink(b.id)]
        self.assertFalse(wizard.pmk_inn_conflict)

    def test_same_inn_or_one_inn_merges(self):
        a = self._company("Альфа З17", vat="7717625418")
        b = self._company("Альфа-2 З17", vat="RU 7717625418")
        c = self._company("Альфа-3 З17")
        wizard = self._wizard(a | b | c)
        self.assertFalse(wizard.pmk_inn_conflict)
        wizard.action_merge()
        self.assertEqual((a | b | c).exists(), wizard.dst_partner_id)

    # ------------------------------------------------------------------
    # какая останется
    # ------------------------------------------------------------------
    def test_destination_inn_first(self):
        no_inn = self._company("Бета З17")
        self.env["crm.lead"].create({"name": "Сделка З17", "partner_id": no_inn.id})
        with_inn = self._company("ООО «Бета» З17", vat="7717625418", active=False)
        wizard = self._wizard(no_inn | with_inn)
        self.assertEqual(wizard.dst_partner_id, with_inn, "ИНН главнее документов и архива.")
        self.assertIn("ИНН 7717625418", wizard.pmk_dst_hint)
        self.assertTrue(wizard.pmk_dst_hint.startswith("Останется: «ООО «Бета» З17»"))

    def test_destination_docs_active_oldest(self):
        old = self._company("Гамма З17", active=False)
        new = self._company("ГАММА З17")
        self.env["crm.lead"].create({"name": "Лид З17", "partner_id": old.id})
        self.assertEqual(self._wizard(old | new).dst_partner_id, old, "Больше документов.")
        first = self._company("Дельта З17", active=False)
        second = self._company("ДЕЛЬТА З17")
        wizard = self._wizard(first | second)
        self.assertEqual(wizard.dst_partner_id, second, "Активная.")
        self.assertIn("в архиве", wizard.pmk_dst_hint)
        one = self._company("Эпсилон З17")
        two = self._company("ЭПСИЛОН З17")
        wizard = self._wizard(two | one)
        self.assertEqual(wizard.dst_partner_id, one, "Заведена раньше.")
        self.assertIn("заведена раньше", wizard.pmk_dst_hint)

    def test_manual_choice_hint_and_reselect(self):
        a = self._company("Зета З17", vat="7717625418")
        b = self._company("ЗЕТА З17")
        c = self._company("Зета-3 З17")
        wizard = self._wizard(a | b | c)
        wizard.dst_partner_id = b
        self.assertIn("выбрана вручную", wizard.pmk_dst_hint)
        self.assertIn("«Зета З17»", wizard.pmk_dst_hint)
        wizard.dst_partner_id = a
        wizard.partner_ids = [Command.unlink(a.id)]
        wizard._onchange_pmk_partner_ids()
        self.assertEqual(wizard.dst_partner_id, b, "Оставшуюся убрали — выбрана заново.")

    def test_duplicates_screen_same_rule(self):
        a = self._company("ООО «Эта-З17»", vat="7717625418", active=False)
        b = self._company("ЭТА-З17")
        self.env["crm.lead"].create({"name": "Лид З17", "partner_id": b.id})
        self.env["res.partner"].action_pmk_duplicates()
        rows = self.env["pmk.partner.duplicate"].search(
            [("create_uid", "=", self.env.uid), ("partner_id", "in", (a | b).ids)])
        self.assertEqual(len(rows), 2)
        action = rows.action_pmk_merge()
        self.assertEqual(action["context"]["pmk_merge_dst_id"], a.id,
                         "«Возможные дубли» — то же правило: ИНН главнее сделки.")

    # ------------------------------------------------------------------
    # не терять
    # ------------------------------------------------------------------
    def test_nothing_lost(self):
        dst = self._company("ООО «Тета З17»", vat="7717625418", phone="8-800-302-07-07",
                            email="office@teta-z17.ru", website="https://teta-z17.ru",
                            comment="<p>Металлобаза</p>")
        src = self._company("ТЕТА З17", phone="+7 (4212) 22-22-22", email="sale@teta-z17.ru",
                            website="https://teta-z17.com", comment="<p>Что возит: трубы</p>",
                            active=False)
        lead = self.env["crm.lead"].create({"name": "Лид З17", "partner_id": src.id})
        message = src.message_post(body="Письмо клиента З17")
        wizard = self._wizard(dst | src)
        self.assertEqual(wizard.dst_partner_id, dst)
        self.assertIn("Не потеряется", wizard.pmk_carry_hint)
        self.assertIn("телефон и эл. почта из «ТЕТА З17» → контактное лицо", wizard.pmk_carry_hint)
        self.assertIn("сайт", wizard.pmk_carry_hint)
        self.assertIn("примечание", wizard.pmk_carry_hint)
        action = wizard.action_merge()
        self.assertFalse(src.exists())
        self.assertEqual((action["res_model"], action["res_id"], action["target"]),
                         ("res.partner", dst.id, "current"), "Открыта оставшаяся карточка.")
        self.assertEqual(lead.partner_id, dst, "Лид переехал (ядро).")
        self.assertEqual(message.res_id, dst.id, "Письмо в ленте переехало (ядро).")
        self.assertEqual(dst.phone, "8-800-302-07-07", "Своё значение у оставшейся.")
        contact = dst.child_ids.filtered(lambda c: c.name == "Контакт из «ТЕТА З17»")
        self.assertEqual(len(contact), 1)
        self.assertEqual((contact.phone, contact.email, contact.type),
                         ("+7 (4212) 22-22-22", "sale@teta-z17.ru", "contact"))
        comment = str(dst.comment)
        self.assertIn("Металлобаза", comment)
        self.assertIn("Из объединения", comment)
        self.assertIn("Что возит: трубы", comment)
        self.assertIn("teta-z17.com", comment)
        note = dst.message_ids.filtered(lambda m: "Объединены с этой карточкой" in (m.body or ""))
        self.assertEqual(len(note), 1, "Одна заметка в ленте.")
        body = str(note.body)
        self.assertIn("ТЕТА З17", body)
        self.assertIn("контактное лицо", body)
        self.assertEqual(dst.email, "office@teta-z17.ru")
        if "pmk_legal_name" in dst._fields:  # стоит pmk_dadata
            self.assertIn("По ИНН", body.replace("по ИНН", "По ИНН"))
        for english in ("Merged with", "Объединено со следующими"):
            self.assertFalse(dst.message_ids.filtered(lambda m: english in (m.body or "")),
                             "Английской строки mail нет.")

    def test_person_gets_note_not_contact(self):
        dst = self._company("Иванов Иван З17", is_company=False, phone="+7 900 111-11-11")
        src = self._company("Иванов И. З17", is_company=False, phone="+7 900 222-22-22")
        self._wizard(dst | src).action_merge()
        self.assertFalse(dst.child_ids, "У физлица контактных лиц не заводим.")
        self.assertIn("+7 900 222-22-22", str(dst.comment))

    def test_nothing_to_carry(self):
        dst = self._company("Йота З17", phone="1-11")
        src = self._company("ЙОТА З17", phone="1-11")
        self._wizard(dst | src).action_merge()
        self.assertFalse(dst.child_ids)
        self.assertNotIn("Из объединения", str(dst.comment or ""))
        note = dst.message_ids.filtered(lambda m: "Объединены с этой карточкой" in (m.body or ""))
        self.assertIn("у этой уже есть", str(note.body))

    def test_price_email_state_moves(self):
        if "pmk_price_email_state" not in self.Partner._fields:
            self.skipTest("pmk_purchase не стоит")
        dst = self._company("Каппа З17", vat="7717625418")
        src = self._company("КАППА З17")
        src.write({"pmk_price_email": "price@kappa-z17.ru", "pmk_price_email_state": "confirmed"})
        self._wizard(dst | src).action_merge()
        self.assertEqual(dst.pmk_price_email, "price@kappa-z17.ru")
        self.assertEqual(dst.pmk_price_email_state, "confirmed",
                         "«Проверен» переехал вместе с адресом.")

    def test_price_email_kept_and_other_noted(self):
        if "pmk_price_email" not in self.Partner._fields:
            self.skipTest("pmk_purchase не стоит")
        dst = self._company("Лямбда З17", vat="7717625418")
        dst.write({"pmk_price_email": "avlukina@lambda-z17.ru", "pmk_price_email_state": "confirmed"})
        src1 = self._company("ЛЯМБДА З17", active=False)
        src1.write({"pmk_price_email": "info@lambda-z17.ru"})
        src2 = self._company("Лямбда-2 З17", active=False)
        src2.write({"pmk_price_email": "INFO@lambda-z17.ru"})
        self._wizard(dst | src1 | src2).action_merge()
        self.assertEqual(dst.pmk_price_email, "avlukina@lambda-z17.ru")
        self.assertEqual(dst.pmk_price_email_state, "confirmed")
        comment = str(dst.comment)
        self.assertEqual(comment.lower().count("info@lambda-z17.ru"), 1,
                         "Одинаковый адрес двух карточек — одной строкой.")

    # ------------------------------------------------------------------
    # права
    # ------------------------------------------------------------------
    def test_rights(self):
        salesman = new_test_user(self.env, login="z17_salesman",
                                 groups="base.group_user,sales_team.group_sale_salesman")
        a, b = self._company("Мю З17"), self._company("МЮ З17")
        with self.assertRaises(AccessError):
            self._wizard(a | b, env=self.env(user=salesman))
        merge = self.env.ref("base.action_partner_merge")
        bindings = self.env["ir.actions.actions"].with_user(salesman).get_bindings("res.partner")
        self.assertNotIn(merge.id, [item["id"] for item in bindings.get("action", [])],
                         "Пункта «Объединить» у менеджера нет.")

    def test_different_email_admin_only(self):
        a = self._company("Ню З17", email="a@nu-z17.ru")
        b = self._company("НЮ З17", email="b@nu-z17.ru")
        self.assertFalse(self.manager._is_admin())
        wizard = self._wizard(a | b, env=self.env(user=self.manager))
        with self.assertRaises(UserError) as caught:
            wizard.action_merge()
        self.assertIn("администратор", str(caught.exception))
        self.assertTrue(a.exists() and b.exists())

    # ------------------------------------------------------------------
    # доводка 11.10
    # ------------------------------------------------------------------
    def test_contact_from_customers_list_context(self):
        """«Клиенты → Действия → Объединить»: контекст списка с default_*."""
        dst = self._company("Омикрон З17", vat="7717625418", phone="1-11")
        src = self._company("ОМИКРОН З17", phone="2-22")
        self._wizard(dst | src, default_is_company=True, default_customer_rank=1,
                     res_partner_search_mode="customer").action_merge()
        contact = dst.child_ids.filtered(lambda c: c.name == "Контакт из «ОМИКРОН З17»")
        self.assertEqual(len(contact), 1)
        self.assertFalse(contact.is_company, "Контактное лицо — не организация.")
        if "customer_rank" in contact._fields:
            self.assertEqual(contact.customer_rank, 0, "И не отдельный клиент.")
        self.assertEqual(contact.commercial_partner_id, dst, "ИНН — с компании.")

    def test_automatic_process_skips_inn_conflict(self):
        a = self._company("Пи З17", vat="7717625418")
        b = self._company("ПИ З17", vat="2721073821")
        wizard = self._wizard(a | b)
        with self.assertLogs("odoo.addons.pmk_partner.models.partner_merge", "WARNING"):
            self.assertIsNone(wizard.with_context(pmk_merge_auto=True)._merge((a | b).ids),
                              "Автоматический проход — группа пропущена, без отказа.")
        self.assertTrue(a.exists() and b.exists(), "Ничего не объединено.")
        with self.assertRaises(UserError):
            wizard._merge((a | b).ids)  # ручной — отказ, как был
        seen = {}

        def fake(self_):
            seen["auto"] = self_.env.context.get("pmk_merge_auto")
            return True
        with patch.object(BasePartnerMergeAutomaticWizard, "action_start_automatic_process", fake):
            wizard.action_start_automatic_process()
        self.assertTrue(seen.get("auto"), "«Объединить автоматически» ставит флаг пропуска.")

    def test_preview_person_becomes_company(self):
        dst = self._company("Ро З17", is_company=False, vat="7717625418", phone="1-11")
        src = self._company("РО З17", phone="2-22")
        wizard = self._wizard(dst | src)
        self.assertEqual(wizard.dst_partner_id, dst)
        self.assertIn("контактное лицо", wizard.pmk_carry_hint,
                      "Ядро сделает оставшуюся организацией — телефон в контактное лицо.")
        wizard.action_merge()
        self.assertTrue(dst.is_company)
        self.assertTrue(dst.child_ids.filtered(lambda c: c.phone == "2-22"))

    def test_one_card_left_refused(self):
        a, b = self._company("Сигма З17"), self._company("СИГМА З17")
        wizard = self._wizard(a | b)
        self.assertEqual(wizard.pmk_partner_count, 2)
        wizard.partner_ids = [Command.unlink(b.id)]
        wizard._onchange_pmk_partner_ids()
        self.assertEqual(wizard.pmk_partner_count, 1)
        with self.assertRaises(UserError) as caught:
            wizard.action_merge()
        self.assertIn("минимум две", str(caught.exception))
        self.assertTrue(a.exists() and b.exists())

    def test_long_comment_whole_in_feed(self):
        dst = self._company("Тау З17", vat="7717625418")
        tail = "конец-примечания-З17"
        src = self._company("ТАУ З17", comment="<p>%s %s</p>" % ("площадка " * 60, tail))
        self._wizard(dst | src).action_merge()
        note = dst.message_ids.filtered(lambda m: "Объединены с этой карточкой" in (m.body or ""))
        self.assertIn(tail, str(note.body), "Вкладка «Заметки» скрыта — в ленте целиком.")

    def test_same_inn_different_kpp_signal(self):
        head = self._company("Ипсилон З17", vat="7717625418", kpp="771701001")
        branch = self._company("Ипсилон, филиал Хабаровск З17", vat="7717625418",
                               kpp="272101001")
        wizard = self._wizard(head | branch)
        self.assertFalse(wizard.pmk_inn_conflict)
        self.assertIn("Один ИНН, разные КПП", wizard.pmk_kpp_hint)
        self.assertIn("272101001", wizard.pmk_kpp_hint)
        root = self._arch(self.manager)
        alert = root.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), "
                           "' alert-warning ')]")[0]
        self.assertEqual(alert.get("invisible"), "not pmk_kpp_hint")
        wizard.action_merge()  # сигнал, не запрет
        self.assertEqual(len((head | branch).exists()), 1)
        same = self._company("Фи З17", vat="2721073821", kpp="272101001")
        other = self._company("ФИ З17", vat="2721073821", kpp="272101001")
        self.assertFalse(self._wizard(same | other).pmk_kpp_hint)

    def test_docs_reason_names_what_counted(self):
        old = self._company("Хи З17", active=False)
        new = self._company("ХИ З17")
        self.env["crm.lead"].create({"name": "Лид З17", "partner_id": old.id})
        wizard = self._wizard(old | new)
        self.assertIn("лиды и сделки", wizard.pmk_dst_hint)
        self.assertIn("1 против 0", wizard.pmk_dst_hint)
