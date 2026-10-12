# -*- coding: utf-8 -*-
"""Вкладка «Раскрой» заказа вентзонтов: запуск, состояние, экономика свеса, программы."""
import base64
import hashlib
import json
import os
from html import escape

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

from .nest_material import fmt_kg, fmt_mm

GAP_RANGE, EDGE_RANGE = (0.5, 50.0), (0.0, 100.0)


def _pct(part, whole):
    return ("%.1f" % (100.0 * part / whole)).replace(".", ",") if whole else "0"


class VentHoodOrder(models.Model):
    _inherit = "pmk.vent.hood.order"

    nest_gap = fields.Float("Зазор между деталями, мм", default=2.0, digits=(6, 1),
                            help="0,5…50. По умолчанию 2 — так режут 0,65. Задаётся до раскроя.")
    nest_edge = fields.Float("Отступ от края листа, мм", default=2.0, digits=(6, 1),
                             help="0…100. По умолчанию 2.")
    nest_job_ids = fields.One2many("pmk.vent.nest.job", "order_id", "Задания раскроя")
    nest_material_ids = fields.One2many("pmk.vent.nest.material", "order_id", "Материалы раскроя")
    nest_busy = fields.Boolean("Раскрой считается", compute="_compute_nest")
    nest_status = fields.Char("Состояние раскроя", compute="_compute_nest")
    nest_status_kind = fields.Selection([("none", ""), ("busy", ""), ("done", ""), ("stale", ""),
                                         ("error", "")], compute="_compute_nest")
    nest_png = fields.Binary("Картинка раскроя", compute="_compute_nest")
    nest_html = fields.Html("Экономия по свесу", compute="_compute_nest", sanitize=False)

    # ------------------------------------------------------------ состояние
    def _nest_fingerprint(self):
        self.ensure_one()
        rows = sorted((l._vh_dxf_name(), l.qty) for l in self.line_ids if l.spec_json)
        raw = json.dumps([rows, self.nest_gap, self.nest_edge], ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()

    @api.depends("nest_job_ids.state", "nest_job_ids.progress", "nest_material_ids",
                 "line_ids", "line_ids.qty", "nest_gap", "nest_edge")
    def _compute_nest(self):
        for order in self:
            jobs = order.nest_job_ids.sorted("id", reverse=True)
            busy = jobs.filtered(lambda j: j.state in ("queued", "running"))[:1]
            plan = jobs.filtered(lambda j: j.kind == "plan" and j.state in ("done", "error"))[:1]
            last = jobs.filtered(lambda j: j.state in ("done", "error"))[:1]
            order.nest_busy = bool(busy)
            order.nest_png = plan.png if plan.state == "done" else False
            order.nest_html = order._nest_economy_html()
            if busy:
                what = "раскрой и перебор свеса" if busy.kind == "plan" else "программы CypCut"
                if busy.state == "queued":
                    text = "В очереди: %s — ждёт, пока досчитается другой заказ." % what
                else:
                    text = "Считается %s%s. Можно уйти с экрана — по готовности придёт уведомление." % (
                        what, " · %s" % busy.progress if busy.progress else "")
                order.nest_status, order.nest_status_kind = text, "busy"
            elif last.state == "error":
                order.nest_status = "Ошибка: %s" % (last.error or "")
                order.nest_status_kind = "error"
            elif plan.state == "done":
                stale = plan.fingerprint != order._nest_fingerprint()
                when = fields.Datetime.context_timestamp(order, plan.finished_at).strftime("%d.%m %H:%M")
                order.nest_status = ("Заказ менялся после раскроя %s — пересчитайте." % when if stale else
                                     "Раскрой посчитан %s за %s · зазор %s, отступ %s мм." % (
                                         when, plan._duration_text(), fmt_kg(plan.gap), fmt_kg(plan.edge)))
                order.nest_status_kind = "stale" if stale else "done"
            else:
                order.nest_status = "Раскрой ещё не считали."
                order.nest_status_kind = "none"

    def _nest_price_kg(self, thickness):
        """Цена кг листа этой толщины из прайса или None. Не подставляем соседнюю позицию:
        нет цены — рублей нет (сигнал «в городе нет», а не дыра)."""
        sheets = self.line_ids.filtered(lambda l: abs((l.thickness or 0) - thickness) < 1e-6).mapped("sheet_id")
        for s in sheets:
            if "pmk_price_ton" in s._fields and not s.pmk_price_missing and s.pmk_price_ton:
                return s.pmk_price_ton / 1000.0, s.display_name
        return None, sheets[:1].display_name if sheets else None

    def _nest_economy_html(self):
        """Таблица «свес × склад/бухта» по каждому материалу и итог «лучше всего»."""
        self.ensure_one()
        if not self.nest_material_ids:
            return False
        out = []
        for mat in self.nest_material_ids:
            base = mat._row(150, "stock")
            base_kg = base.get("kg") if not base.get("error") else None
            base_coil = mat._row(150, "coil").get("kg")
            ref_kg, ref_name = (base_kg, "150 + склад") if base_kg else (base_coil, "150 + бухта")
            price, sheet_name = self._nest_price_kg(mat.thickness)
            best = mat._best()
            head = '<div class="pmk-nest-mat"><div class="pmk-nest-mat__title">%s · %s мм</div>' % (
                escape(mat.color), fmt_mm(mat.thickness))
            rows = []
            for sv, _l in mat._fields["sves"].selection:
                cells = []
                for src in ("stock", "coil"):
                    r = mat._row(int(sv), src)
                    if r.get("error"):
                        cells.append('<td class="pmk-nest-na" title="%s">нельзя</td>' % escape(r["error"]))
                    elif r.get("kg"):
                        is_best = best and int(float(best["sves"])) == int(sv) and best["source"] == src
                        cells.append('<td class="%s">%s<span class="pmk-nest-len">%s</span></td>' % (
                            "pmk-nest-best" if is_best else "", fmt_kg(r["kg"]), escape(r.get("lengths") or "")))
                    else:
                        cells.append("<td>—</td>")
                rows.append('<tr><th>%s</th>%s</tr>' % (sv, "".join(cells)))
            table = ('<table class="pmk-nest-table"><thead><tr><th>Свес, мм</th><th>Склад 2500, кг</th>'
                     '<th>Бухта, кг</th></tr></thead><tbody>%s</tbody></table>' % "".join(rows))
            note = ""
            if best and ref_kg:
                d = ref_kg - best["kg"]
                src = "склад" if best["source"] == "stock" else "бухта"
                note = "Лучше всего: свес %s + %s — %s кг" % (fmt_kg(float(best["sves"])), src, fmt_kg(best["kg"]))
                if d > 0.05:
                    note += ", экономия %s кг (%s %%) против %s" % (fmt_kg(d), _pct(d, ref_kg), ref_name)
                    d2 = (base_coil or 0) - best["kg"]
                    if ref_name != "150 + бухта" and base_coil and d2 > 0.05:
                        note += ", %s кг против 150 + бухта" % fmt_kg(d2)
                    if price:
                        note += " ≈ %s ₽" % ("{:,.0f}".format(d * price).replace(",", " "))
                note += "."
                if float(best["sves"]) < 150:
                    note += " Свес меньше 150 — только по решению инженера."
            if not price:
                note += ' <span class="pmk-nest-muted">Рублей нет: у «%s» нет цены в прайсах.</span>' % escape(
                    sheet_name or "листа")
            out.append(head + table + '<div class="pmk-nest-note">%s</div></div>' % note)
        return Markup('<div class="pmk-nest">%s</div>' % "".join(out))

    # ------------------------------------------------------------ кнопки
    def _nest_check_params(self):
        self.ensure_one()
        if not (GAP_RANGE[0] <= self.nest_gap <= GAP_RANGE[1]):
            raise UserError("Зазор между деталями — от 0,5 до 50 мм.")
        if not (EDGE_RANGE[0] <= self.nest_edge <= EDGE_RANGE[1]):
            raise UserError("Отступ от края — от 0 до 100 мм.")
        if self.nest_busy:
            raise UserError("Раскрой этого заказа уже считается — дождитесь уведомления.")
        self._vh_good_lines()

    def _nest_start(self, kind, builds=None):
        Job = self.env["pmk.vent.nest.job"]
        job = Job.create({"order_id": self.id, "kind": kind, "gap": self.nest_gap, "edge": self.nest_edge,
                          "fingerprint": self._nest_fingerprint(),
                          "builds_json": json.dumps(builds or [], ensure_ascii=False)})
        if not Job.search_count([("state", "=", "running")]):
            job._launch()
        cron = self.env.ref("pmk_vent_nest.cron_vent_nest", raise_if_not_found=False)
        if cron:
            cron._trigger()
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "info", "title": "Раскрой считается в фоне",
            "message": "Можно работать дальше — по готовности придёт уведомление.",
            "next": {"type": "ir.actions.client", "tag": "soft_reload"}}}

    def action_nest_plan(self):
        self._nest_check_params()
        return self._nest_start("plan")

    def action_nest_build(self):
        self._nest_check_params()
        if not self.nest_material_ids:
            raise UserError("Сначала посчитайте раскрой.")
        plan = self.nest_job_ids.filtered(lambda j: j.kind == "plan" and j.state == "done").sorted("id")[-1:]
        if plan.fingerprint != self._nest_fingerprint():
            raise UserError("Заказ менялся после раскроя — пересчитайте раскрой, потом собирайте программы.")
        builds = []
        for m in self.nest_material_ids:
            row = m._row(int(m.sves), m.choice)
            if row.get("error"):
                raise UserError("%s: %s при свесе %s невозможна — %s" % (
                    m.color, dict(m._fields["choice"].selection)[m.choice], m.sves, row["error"]))
            builds.append({"key": m.key, "source": m.choice, "sves": int(m.sves),
                           "label": "%s %s, %s, свес %s" % (m.color, fmt_mm(m.thickness),
                                                             "склад" if m.choice == "stock" else "бухта", m.sves)})
        return self._nest_start("build", builds)

    # ------------------------------------------------------------ результат
    def _nest_apply_plan(self, job, result):
        self.ensure_one()
        self.nest_material_ids.unlink()
        rows = result.get("sves") or []
        vals = []
        for i, m in enumerate(result.get("materials") or []):
            st, co = m.get("stock") or {}, m.get("coil") or {}
            vals.append({
                "order_id": self.id, "sequence": i, "key": m["key"], "color": m["color"],
                "thickness": m["thickness"],
                "stock_kg": st.get("kg") or 0.0, "stock_lengths": st.get("lengths"), "stock_error": st.get("error"),
                "coil_kg": co.get("kg") or 0.0, "coil_lengths": co.get("lengths"), "coil_error": co.get("error"),
                "recommend": m.get("recommend") if m.get("recommend") in ("stock", "coil") else False,
                "choice": m.get("recommend") if m.get("recommend") in ("stock", "coil") else "coil",
                "sves": "150",
                "sves_json": json.dumps([r for r in rows if r.get("key") == m["key"]], ensure_ascii=False),
            })
        self.env["pmk.vent.nest.material"].create(vals)

    def _nest_apply_build(self, job, result):
        self.ensure_one()
        Att = self.env["ir.attachment"]
        good, bad = [], []
        for f in result.get("files") or []:
            if not f.get("ok"):
                bad.append(f)
                continue
            with open(os.path.join(job.workdir, f["path"]), "rb") as fh:
                data = fh.read()
            Att.create({"name": f["filename"], "datas": base64.b64encode(data),
                        "res_model": self._name, "res_id": self.id,
                        "mimetype": "application/octet-stream"})
            good.append(f)
        job.result_json = json.dumps(dict(result, attached=[f["filename"] for f in good],
                                          rejected=[f["filename"] for f in bad]), ensure_ascii=False)

    def _nest_notify(self, job):
        """Запись в историю заказа (заметка — без писем) и всплывашка тому, кто запускал."""
        self.ensure_one()
        title = "%s: %s" % (self.name, "раскрой" if job.kind == "plan" else "программы CypCut")
        if job.state == "error":
            body = "Раскрой не получился: %s" % (job.error or "")
            kind = "danger"
        elif job.kind == "plan":
            parts = []
            for m in self.nest_material_ids:
                best = m._best()
                txt = "%s %s мм — склад %s кг, бухта %s кг" % (m.color, fmt_mm(m.thickness),
                                                              fmt_kg(m.stock_kg) if not m.stock_error else "нельзя",
                                                              fmt_kg(m.coil_kg) if not m.coil_error else "нельзя")
                if best and float(best["sves"]) < 150:
                    txt += "; при свесе %s — %s кг" % (fmt_kg(float(best["sves"])), fmt_kg(best["kg"]))
                parts.append(txt)
            body = "Раскрой готов (%s): %s." % (job._duration_text(), "; ".join(parts))
            kind = "success"
        else:
            res = json.loads(job.result_json or "{}")
            body = "Программы CypCut готовы, во вкладке «Файлы»: %s." % (", ".join(res.get("attached") or []) or "нет")
            coil = ["%s %s мм — %s" % (m.color, fmt_mm(m.thickness), m.choice_lengths)
                    for m in self.nest_material_ids if m.choice == "coil" and m.choice_lengths]
            if coil:
                body += " Бухта — заказать листы: %s." % "; ".join(coil)
            if res.get("rejected"):
                body += " Не выданы (не прошли самопроверку, передано разработчику): %s." % ", ".join(res["rejected"])
                kind = "warning"
            else:
                kind = "success"
        self.message_post(body=body, subtype_xmlid="mail.mt_note")
        if job.user_id:
            job.user_id._bus_send("simple_notification", {
                "title": title, "message": body, "sticky": True, "type": kind})
