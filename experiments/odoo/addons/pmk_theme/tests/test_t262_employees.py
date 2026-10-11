# -*- coding: utf-8 -*-
"""Задача 262 (12.10.2026): сотрудники — без пустых плашек, карточка только с
нужным, фото сотрудника — аватар его пользователя."""
import base64

from lxml import etree

from odoo.tests import TransactionCase, tagged

# 1×1 PNG — фото сотрудника.
PNG = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f80f000001010001a5d4f2b200"
    "00000049454e44ae426082"))


@tagged("post_install", "-at_install")
class TestT262Employees(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hr_user = cls.env["res.users"].create({
            "name": "Кадровик Т262", "login": "t262_hr",
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id,
                                  cls.env.ref("hr.group_hr_user").id])]})
        cls.removed = cls.env.ref("pmk_theme.group_pmk_removed")

    def _arch(self, user):
        views = self.env["hr.employee"].with_user(user).get_views([(False, "form")])
        return etree.fromstring(views["views"]["form"]["arch"])

    def test_form_only_needed(self):
        arch = self._arch(self.hr_user)
        pages = [p.get("name") for p in arch.iter("page")]
        for hidden in ("resume", "certification", "personal_information", "payroll_information", "hr_settings"):
            self.assertNotIn(hidden, pages)
        self.assertIn("work_information", pages)
        work = arch.xpath("//page[@name='work_information']")[0]
        names = [f.get("name") for f in work.iter("field")]
        for kept in ("department_id", "job_title", "parent_id", "user_id"):
            self.assertIn(kept, names)
        self.assertNotIn("job_id", names, "дубль должности спрятан")
        self.assertNotIn("company_id", names)
        self.assertEqual(work.xpath(".//field[@name='job_title']")[0].get("string"), "Должность")
        self.assertFalse(arch.xpath("//div[@id='o_employee_org_chart']"))
        self.assertFalse(arch.xpath("//header"), "пустая полоса шапки")
        for gone in ("address_id", "work_location_id", "monday_location_id"):
            self.assertNotIn(gone, names, "местоположение спрятано")
        self.assertFalse(arch.xpath("//div[@name='button_box']/button"))
        self.assertFalse(arch.xpath("//field[@name='category_ids']"))

    def test_removed_group_sees_everything(self):
        self.hr_user.group_ids = [(4, self.removed.id)]
        arch = self._arch(self.hr_user)
        pages = [p.get("name") for p in arch.iter("page")]
        self.assertIn("hr_settings", pages)
        self.assertIn("personal_information", pages)
        self.assertTrue(arch.xpath("//page[@name='work_information']//field[@name='job_id']"))
        self.assertTrue(arch.xpath("//page[@name='work_information']//field[@name='address_id']"))

    def test_photo_goes_to_user_avatar(self):
        user = self.env["res.users"].create({"name": "Голубь Т262", "login": "t262_pigeon"})
        employee = self.env["hr.employee"].create({"name": "Голубь Т262", "user_id": user.id,
                                                   "image_1920": PNG})
        self.assertEqual(user.partner_id.image_1920, employee.image_1920)
        other = base64.b64encode(base64.b64decode(PNG) + b"\0")
        employee.image_1920 = other
        self.assertEqual(user.partner_id.image_1920, employee.image_1920, "смена фото — тоже")

    def test_photo_on_user_link(self):
        employee = self.env["hr.employee"].create({"name": "Без пользователя Т262", "image_1920": PNG})
        user = self.env["res.users"].create({"name": "Позже Т262", "login": "t262_later"})
        employee.user_id = user
        self.assertEqual(user.partner_id.image_1920, employee.image_1920)

    def test_ghost_rule_everywhere(self):
        from odoo.tools.misc import file_open
        with file_open("pmk_theme/static/src/scss/hidden.scss") as fh:
            src = fh.read()
        self.assertIn(".o_kanban_renderer .o_kanban_record.o_kanban_ghost", src)

    def test_dark_search_panel_readable(self):
        from odoo.tools.misc import file_open
        with file_open("pmk_theme/static/src/scss/dark.scss") as fh:
            src = fh.read()
        self.assertIn("body.o_nexus_dark .o_search_panel .list-group-item", src)
