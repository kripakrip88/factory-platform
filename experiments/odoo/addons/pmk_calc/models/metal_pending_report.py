# -*- coding: utf-8 -*-
"""Список «Справочники → Новые позиции на разнос» (шаг З-10).

Одним списком три справочника: прокат, лист, метизы — администратор видит
всё, что завели из расчётов, и разносит: «Привязать к существующей» или
«Принять в справочник». Представление базы, а не таблица: позиция живёт в
своём справочнике, список только показывает. В архиве (привязали) — уходит
из списка сам.

⚠️ Импорт в models/__init__.py — ПОСЛЕДНИМ: init() создаёт представление
по колонкам справочников (pmk_pending, active…), а они появляются при
_auto_init самих справочников — модели инициализируются по порядку.
"""
from odoo import _, fields, models, tools
from odoo.exceptions import UserError

from .metal_pending import NO_WEIGHT_LABEL, _plural

KINDS = [("linear", "Прокат"), ("sheet", "Лист"), ("fastener", "Метиз")]
KIND_MODEL = {
    "linear": "pmk.metal.profile",
    "sheet": "pmk.metal.sheet",
    "fastener": "pmk.metal.fastener",
}
# Форма справочника с «Принять в справочник» (views/pending_views.xml).
ACCEPT_FORM = {
    "pmk.metal.profile": "pmk_calc.view_metal_profile_form",
    "pmk.metal.sheet": "pmk_calc.view_metal_sheet_form",
    "pmk.metal.fastener": "pmk_calc.view_metal_fastener_form",
}
UNIT = {"linear": "кг/м", "sheet": "кг/м²", "fastener": "кг/шт"}


def _num(value):
    text = ("%.4f" % (value or 0.0)).rstrip("0").rstrip(".")
    return text.replace(".", ",")


class MetalPending(models.Model):
    _name = "pmk.metal.pending"
    _description = "Новая позиция на разнос"
    _auto = False
    _log_access = False
    _order = "date desc, id desc"
    _rec_name = "name"

    kind = fields.Selection(KINDS, "Вид", readonly=True)
    res_model = fields.Char("Справочник", readonly=True)
    res_id = fields.Integer("Позиция", readonly=True)
    name = fields.Char("Название", readonly=True)
    user_id = fields.Many2one("res.users", "Кто завёл", readonly=True)
    date = fields.Datetime("Когда", readonly=True)
    unit_mass = fields.Float("Масса единицы", readonly=True, digits=(12, 5))
    spec_id = fields.Many2one("pmk.metal.spec", "Где завели", readonly=True)

    weight_label = fields.Char("Вес", compute="_compute_usage")
    no_weight = fields.Boolean("Нет веса", compute="_compute_usage")
    spec_count = fields.Integer("В расчётах", compute="_compute_usage")
    line_count = fields.Integer("Деталей", compute="_compute_usage")
    spec_names = fields.Char("Расчёты", compute="_compute_usage")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT p.id * 10 + 1 AS id, 'linear'::varchar AS kind,
                       'pmk.metal.profile'::varchar AS res_model, p.id AS res_id,
                       COALESCE(NULLIF(p.pmk_pending_name, ''), p.display_name) AS name,
                       p.create_uid AS user_id, p.create_date AS date,
                       p.mass_per_meter::float AS unit_mass, p.pmk_pending_spec_id AS spec_id
                  FROM pmk_metal_profile p
                 WHERE p.pmk_pending AND p.active
                UNION ALL
                SELECT s.id * 10 + 2, 'sheet', 'pmk.metal.sheet', s.id,
                       COALESCE(NULLIF(s.pmk_pending_name, ''), s.display_name),
                       s.create_uid, s.create_date,
                       s.mass_per_sqm::float, s.pmk_pending_spec_id
                  FROM pmk_metal_sheet s
                 WHERE s.pmk_pending AND s.active
                UNION ALL
                SELECT f.id * 10 + 3, 'fastener', 'pmk.metal.fastener', f.id,
                       COALESCE(NULLIF(f.pmk_pending_name, ''), f.name),
                       f.create_uid, f.create_date,
                       f.weight_kg::float, f.pmk_pending_spec_id
                  FROM pmk_metal_fastener f
                 WHERE f.pmk_pending AND f.active
            )""" % self._table)

    def _pmk_source(self):
        """Сама позиция справочника за строкой списка."""
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id).exists()
        if not record:
            raise UserError(_("Позиции уже нет — обновите список."))
        return record

    def _compute_usage(self):
        for row in self:
            source = self.env[row.res_model].browse(row.res_id).exists() if row.res_model else False
            row.no_weight = not row.unit_mass
            row.weight_label = (
                NO_WEIGHT_LABEL if not row.unit_mass
                else "%s %s" % (_num(row.unit_mass), UNIT.get(row.kind, "")))
            if not source:
                row.spec_count = row.line_count = 0
                row.spec_names = False
                continue
            specs = source.pmk_pending_spec_ids
            row.spec_count = len(specs)
            row.line_count = source.pmk_pending_line_count
            names = specs[:5].mapped("name")
            if len(specs) > 5:
                names.append(_("ещё %s") % (len(specs) - 5))
            row.spec_names = ", ".join(names) or False

    # ─── Кнопки строки ──────────────────────────────────────────────────
    def _pmk_check_admin(self):
        self.env["pmk.metal.profile"]._pmk_check_admin()

    def action_pmk_bind(self):
        """«Привязать к существующей» — окно выбора настоящей позиции."""
        self.ensure_one()
        self._pmk_check_admin()
        source = self._pmk_source()
        lines = source.pmk_pending_line_count
        specs = source.pmk_pending_spec_ids
        if lines:
            usage = _("%(lines)s %(lword)s в %(specs)s %(sword)s: %(names)s",
                      lines=lines, lword=_plural(lines, "деталь", "детали", "деталей"),
                      specs=len(specs), sword=_plural(len(specs), "расчёте", "расчётах", "расчётах"),
                      names=", ".join(specs.mapped("name")))
        else:
            usage = _("Ни в одной детали не стоит.")
        wizard = self.env["pmk.metal.pending.bind"].create({
            "source_model": source._name,
            "source_id": source.id,
            "kind": self.kind,
            "source_name": source.display_name,
            "usage_text": usage,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Привязать к существующей"),
            "res_model": "pmk.metal.pending.bind",
            "res_id": wizard.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
        }

    def action_pmk_accept(self):
        """«Принять в справочник» — форма позиции: дозаполнить и принять."""
        self.ensure_one()
        self._pmk_check_admin()
        source = self._pmk_source()
        view = self.env.ref(ACCEPT_FORM[source._name])
        return {
            "type": "ir.actions.act_window",
            "name": _("Принять в справочник"),
            "res_model": source._name,
            "res_id": source.id,
            "view_mode": "form",
            "views": [(view.id, "form")],
            "target": "current",
        }

    def action_pmk_archive(self):
        """«В архив» — позиция нигде не стоит (завели и передумали)."""
        self._pmk_check_admin()
        for row in self:
            row._pmk_source().action_pmk_archive_unused()
        return True
