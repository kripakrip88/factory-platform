# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pmk_cloud_login = fields.Char("Почта Mail.ru", config_parameter="pmk_cloud.login",
                                  default="pmkpark@mail.ru")
    pmk_cloud_password = fields.Char(
        "Пароль для внешнего приложения", config_parameter="pmk_cloud.password",
        help="Mail.ru → Безопасность → «Пароли для внешних приложений», доступ «Облако (WebDAV)». "
             "Обычный пароль от почты не подойдёт.")
    pmk_cloud_root = fields.Char("Папка", config_parameter="pmk_cloud.root",
                                 help="Путь в Облаке, например /ПРОИЗВОДСТВО. Пусто — «Проверить» покажет "
                                      "папки корня.")
    pmk_cloud_exts = fields.Char("Какие файлы", config_parameter="pmk_cloud.exts", default="dxf,lxds,zx",
                                 help="Расширения через запятую — остальные (.emf CypCut и т.п.) в группу не идут.")
    pmk_cloud_exclude = fields.Char("Только ночью", config_parameter="pmk_cloud.exclude", default="Архив",
                                    help="Папки первого уровня через запятую, которые раз в 5 минут не смотрим "
                                         "(большие). Их новые файлы придут после ночного обхода.")
    pmk_cloud_status = fields.Char("Последняя проверка", compute="_compute_pmk_cloud_status")

    def _compute_pmk_cloud_status(self):
        status = self.env["ir.config_parameter"].sudo().get_param("pmk_cloud.last_status") or "ещё не было"
        for rec in self:
            rec.pmk_cloud_status = status

    def action_pmk_cloud_check(self):
        self.execute()  # сначала сохранить введённое
        ok, text = self.env["pmk.cloud.file"].sudo()._check_connection()
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "success" if ok else "danger", "title": "Облако Mail.ru", "message": text, "sticky": True}}
