# -*- coding: utf-8 -*-
"""«Печать ▾ → Расчёт (Excel)» (Антон 21.10.2026: «срочно нужен такой формат»).

Три листа:
- «Изделия» — все изделия расчёта (конструкции, зонты, доборка): количество,
  вес, цена, сумма, итог и НДС; без цены клиенту — жёлтым;
- «Состав» — формат спецификаций Бутова: № по заявке, № по спецификации,
  наименование сортаментом, длина, кол-во на 1 шт, кол-во изделий, всего
  (формулой), марка, изделие, вес и цена металла за тонну — та, что подставила
  система (не обратный счёт: стоимость закупки целым листом/хлыстом даёт
  «625 000 ₽/т» на мелком заказе); ниже — зонты, доборка, болты блоками;
- «Металл и деньги» — внутренний: материалы (метры, м², вес деталей, купить,
  стоимость закупки) и по изделиям металл, цена клиенту, маржа.

«Расчёт для клиента (Excel)» — только «Изделия», без сделки, себестоимости и
маржи. Источник — сводка «Металлоизделия» (pmk_summary, все калькуляторы) и
строки деталей; файл собирается в памяти за доли секунды, база не нагружается.
"""
import io
import re
from collections import OrderedDict

from odoo import _, models

SRC = {"metal": "Конструкции", "manual": "Конструкции", "vent": "Зонты", "dobor": "Доборка"}
VAT_RATE = 22


def _num(value):
    return value or 0.0


class MetalSpecXlsx(models.Model):
    _inherit = "pmk.metal.spec"

    # ─── Меню «Печать» ──────────────────────────────────────────────────
    def pmk_doc_menu(self):
        menu = super().pmk_doc_menu()
        spec = self[:1]
        tech = "pmk_kind" in self._fields and spec.pmk_kind == "tech"
        menu["print"].append({"key": "xlsx", "label": _("Расчёт (Excel)"), "icon": "fa-file-excel-o",
                              "method": "action_pmk_xlsx"})
        if not tech:
            menu["print"].append({"key": "xlsx_client", "label": _("Расчёт для клиента (Excel)"),
                                  "icon": "fa-file-excel-o", "method": "action_pmk_xlsx_client"})
        return menu

    def action_pmk_xlsx(self):
        return self._pmk_xlsx_action(client=False)

    def action_pmk_xlsx_client(self):
        return self._pmk_xlsx_action(client=True)

    def _pmk_xlsx_action(self, client):
        self.ensure_one()
        self.check_access("read")
        return {"type": "ir.actions.act_url", "target": "self",
                "url": "/pmk_orders/spec/%s/xlsx%s" % (self.id, "?client=1" if client else "")}

    def _pmk_xlsx_filename(self, client=False):
        self.ensure_one()
        name = re.sub(r'[\\/:*?"<>|]+', " ", self.name or "Расчёт").strip()
        return "Расчёт %s%s.xlsx" % (name, " для клиента" if client else "")

    # ─── Файл ───────────────────────────────────────────────────────────
    def _pmk_xlsx(self, client=False):
        """Файл .xlsx (байты): см. шапку модуля."""
        self.ensure_one()
        import xlsxwriter
        out = io.BytesIO()
        wb = xlsxwriter.Workbook(out, {"in_memory": True})
        fmt = _Formats(wb)
        rows = list((self.pmk_summary or {}).get("rows", []))
        self._pmk_xlsx_products(wb, fmt, rows, client)
        if not client:
            self._pmk_xlsx_composition(wb, fmt, rows)
            self._pmk_xlsx_money(wb, fmt, rows)
        wb.close()
        return out.getvalue()

    def _pmk_xlsx_head(self, ws, fmt, title, cols, client=False):
        ws.write(0, 0, title, fmt.h1)
        info = [(_("Расчёт"), "%s от %s" % (self.name, self.date.strftime("%d.%m.%Y") if self.date else ""))]
        if not client:
            info.append((_("Сделка"), self.opportunity_id.display_name or "—"))
        info.append((_("Контрагент"), self.partner_id.display_name or "—"))
        if "pmk_org_id" in self._fields:
            info.append((_("Наша организация"), self.pmk_org_id.display_name or "—"))
        for i, (key, value) in enumerate(info, 1):
            ws.write(i, 0, key, fmt.muted)
            ws.merge_range(i, 1, i, cols, value, fmt.plain)
        return len(info) + 2

    # Лист 1 ─────────────────────────────────────────────────────────────
    def _pmk_xlsx_products(self, wb, fmt, rows, client):
        ws = wb.add_worksheet(_("Изделия"))
        r = self._pmk_xlsx_head(ws, fmt, _("Расчёт стоимости"), 6, client)
        ws.write_row(r, 0, [_("№"), _("Изделие"), _("Раздел"), _("Кол-во"), _("Вес, кг"),
                            _("Цена за шт"), _("Сумма")], fmt.th)
        ws.set_row(r, 22)
        first = r = r + 1
        for i, row in enumerate(rows, 1):
            price = _num(row.get("price_unit"))
            ws.write(r, 0, i, fmt.center)
            ws.write(r, 1, (row.get("name") or "").strip(), fmt.wrap)
            ws.write(r, 2, SRC.get(row.get("source"), ""), fmt.center)
            ws.write(r, 3, row.get("qty") or 0, fmt.int)
            ws.write(r, 4, _num(row.get("weight")), fmt.kg)
            ws.write(r, 5, price, fmt.rub if price or client else fmt.rub_warn)
            ws.write_formula(r, 6, "=D%d*F%d" % (r + 1, r + 1), fmt.rub, _num(row.get("total")))
            r += 1
        ws.merge_range(r, 0, r, 3, _("Итого"), fmt.total)
        ws.write_formula(r, 4, "=SUM(E%d:E%d)" % (first + 1, r), fmt.total_kg)
        ws.write(r, 5, "", fmt.total)
        ws.write_formula(r, 6, "=SUM(G%d:G%d)" % (first + 1, r), fmt.total_rub)
        r += 1
        ws.merge_range(r, 0, r, 5, _("в т.ч. НДС %s%%") % VAT_RATE, fmt.vat_label)
        ws.write_formula(r, 6, "=G%d*%d/%d" % (r, VAT_RATE, 100 + VAT_RATE), fmt.vat)
        if not client and any(not row.get("price_unit") for row in rows):
            ws.write(r + 2, 1, _("Жёлтым — нет цены клиенту: проставить в расчёте."), fmt.muted)
        ws.set_column(0, 0, 5)
        ws.set_column(1, 1, 58)
        ws.set_column(2, 2, 13)
        ws.set_column(3, 4, 10)
        ws.set_column(5, 6, 16)
        ws.freeze_panes(first, 0)

    # Лист 2 ─────────────────────────────────────────────────────────────
    def _pmk_xlsx_composition(self, wb, fmt, rows):
        ws = wb.add_worksheet(_("Состав"))
        r = self._pmk_xlsx_head(ws, fmt, _("Состав изделий"), 10)
        ws.write_row(r, 0, [_("№ по заяв"), _("№ по спец"), _("Наименование"), _("Длина, мм"),
                            _("Кол-во на 1 шт"), _("Кол-во изделий"), _("Всего"), _("Марка"),
                            _("Изделие"), _("Вес, кг"), _("Металл, ₽/т")], fmt.th)
        ws.set_row(r, 30)
        start = r = r + 1
        state = {"r": r, "n": 0}

        def section(title):
            ws.merge_range(state["r"], 0, state["r"], 10, title, fmt.section)
            state["r"] += 1

        def block(qty, title, lines):
            """lines: (поз, наименование, длина, кол-во на 1, марка, вес, ₽/т | None | 0)."""
            state["n"] += 1
            top = state["r"]
            for pos, name, length, per_one, grade, kg, price_t in lines or [("", "", "", 0, "", 0, None)]:
                i = state["r"]
                ws.write(i, 1, pos, fmt.center)
                ws.write(i, 2, name, fmt.wrap)
                ws.write(i, 3, length or "", fmt.int)
                ws.write(i, 4, per_one or "", fmt.int)
                ws.write_formula(i, 6, "=E%d*$F$%d" % (i + 1, top + 1), fmt.int)
                ws.write(i, 7, grade, fmt.center)
                ws.write(i, 9, kg or "", fmt.kg)
                if price_t is None:
                    ws.write(i, 10, "", fmt.cell)
                elif price_t:
                    ws.write(i, 10, price_t, fmt.int)
                else:
                    ws.write(i, 10, _("нет цены"), fmt.warn_text)
                state["r"] += 1
            last = state["r"] - 1
            for col, value, style in ((0, state["n"], fmt.merged), (5, qty, fmt.merged), (8, title, fmt.merged_wrap)):
                if last > top:
                    ws.merge_range(top, col, last, col, value, style)
                else:
                    ws.write(top, col, value, style)

        products = self.product_ids.sorted(lambda p: (p.sequence, p.id)) if self.cat_metal else self.product_ids.browse()
        if products:
            section(_("Конструкции"))
            for product in products:
                block(product.qty, (product.name or "").strip(), [
                    self._pmk_xlsx_line(line, product) for line in product.line_ids.sorted(lambda l: (l.sequence, l.id))])
        vents = [row for row in rows if row.get("source") == "vent"]
        if vents:
            section(_("Зонты"))
            for row in vents:
                info = row.get("vent") or {}
                parts = info.get("parts") or []
                lines = [("", ("%s %s" % (p.get("name") or "", p.get("size") or "")).strip(), "", p.get("qty"), "", "", None)
                         for p in parts]
                if lines:
                    weight = _num(info.get("weight_one")) * (row.get("qty") or 0)
                    lines[0] = lines[0][:5] + (weight, None)
                block(row.get("qty"), "%s\n%s" % (row.get("name") or "", info.get("head") or ""), lines)
        dobors = [row for row in rows if row.get("source") == "dobor"]
        if dobors:
            section(_("Доборка"))
            for row in dobors:
                info = row.get("dobor") or {}
                desc = _("развёртка %(dev)s мм, %(bends)s, %(area)s м² на шт",
                         dev=("%g" % _num(info.get("developed"))).replace(".", ","),
                         bends=info.get("bends") or _("без гибов"),
                         area=("%.2f" % _num(info.get("area_one"))).replace(".", ","))
                material = " · ".join(p for p in (info.get("sheet"), info.get("coating")) if p)
                block(row.get("qty"), "%s\n%s" % (row.get("name") or "", material), [
                    ("", desc, info.get("length") or "", 1, "", _num(info.get("weight_one")) * (row.get("qty") or 0), None)])
        self._pmk_xlsx_composition_more(rows, section, block)
        r = state["r"]
        ws.merge_range(r, 0, r, 8, _("Итого вес"), fmt.total)
        ws.write_formula(r, 9, "=SUM(J%d:J%d)" % (start + 1, r), fmt.total_kg)
        ws.write(r, 10, "", fmt.total)
        ws.write(r + 2, 2, _("Металл, ₽/т — цена поставщика, которую подставила система (самая низкая из "
                             "прайсов). «нет цены» — позиции нет в прайсах."), fmt.muted)
        ws.set_column(0, 1, 9)
        ws.set_column(2, 2, 40)
        ws.set_column(3, 7, 10)
        ws.set_column(8, 8, 46)
        ws.set_column(9, 9, 10)
        ws.set_column(10, 10, 12)
        ws.freeze_panes(start, 0)

    def _pmk_xlsx_composition_more(self, rows, section, block):
        """Разделы других калькуляторов на листе «Состав» (pmk_bolt — болты): section(заголовок),
        block(кол-во, изделие, строки) — как у зонтов и доборки."""

    def _pmk_xlsx_line(self, line, product):
        """Строка детали в записи Бутова: «Труба круглая 57x3» + длина, «Лист гладкий 4х100»
        + длина (ширина × длина листа), «по КМ N кг» — масса из КМ без длины."""
        item = line.profile_id or line.sheet_id or line.fastener_id or line.paint_id
        name = item.display_name if item else ""
        length = 0.0
        if line.pmk_mass_kg and line.calc_mode in ("linear", "sheet"):
            name = _("%(name)s (по КМ %(kg)s кг)", name=name, kg=("%g" % line.pmk_mass_kg).replace(".", ","))
        elif line.calc_mode == "sheet":
            if line.a_mm:
                name = "%sх%g" % (name.replace(" мм", ""), line.a_mm)
            length = line.b_mm
        elif line.calc_mode == "linear":
            length = line.length_mm
        price_t = None
        if line.calc_mode in ("linear", "sheet") and "price_ton" in line._fields:
            price_t = round(line.price_ton) if line.price_state in ("ok", "manual") else 0
        return (line.detail_name or "", name, length, line.qty, line.grade_id.display_name or "",
                line.weight_total * (product.qty or 0), price_t)

    def _pmk_xlsx_money_more(self, rows, add):
        """Материалы других калькуляторов на листе «Металл и деньги»: add(материал, kg=, rub=, …)."""

    # Лист 3 ─────────────────────────────────────────────────────────────
    def _pmk_xlsx_money(self, wb, fmt, rows):
        ws = wb.add_worksheet(_("Металл и деньги"))
        r = self._pmk_xlsx_head(ws, fmt, _("Материалы и себестоимость (внутренний, клиенту не отправлять)"), 5)
        ws.write(r, 0, _("Материалы"), fmt.bold)
        r += 1
        ws.write_row(r, 0, [_("Материал"), _("Длина всего, м"), _("Площадь, м²"), _("Вес деталей, кг"),
                            _("Купить, кг"), _("Стоимость закупки, ₽")], fmt.th)
        ws.set_row(r, 30)
        first = r = r + 1
        agg = OrderedDict()

        def add(key, **vals):
            a = agg.setdefault(key, {"m": 0.0, "m2": 0.0, "kg": 0.0, "buy": 0.0, "rub": 0.0})
            for k, v in vals.items():
                a[k] += v or 0.0

        if self.cat_metal:
            for product in self.product_ids:
                pq = product.qty or 0
                for line in product.line_ids:
                    item = line.profile_id or line.sheet_id or line.fastener_id or line.paint_id
                    if not item:
                        continue
                    add(item.display_name,
                        m=line.length_mm * line.qty * pq / 1000.0 if line.calc_mode == "linear" and not line.pmk_mass_kg else 0,
                        m2=line.a_mm * line.b_mm * line.qty * pq / 1e6 if line.calc_mode == "sheet" else 0,
                        kg=line.weight_total * pq,
                        buy=(line.weight_fact_total * pq) if "weight_fact_total" in line._fields else 0,
                        rub=(line.cost_fact_total * pq) if "cost_fact_total" in line._fields else 0)
        for row in rows:
            if row.get("source") == "vent":
                info = row.get("vent") or {}
                add((info.get("head") or _("Лист (зонты)")).split(" · ")[0],
                    m2=_num(info.get("metal_m2")) * (row.get("qty") or 0),
                    kg=_num(info.get("weight_one")) * (row.get("qty") or 0))
            elif row.get("source") == "dobor":
                info = row.get("dobor") or {}
                add(info.get("sheet") or _("Лист (доборка)"), m2=info.get("area_total"),
                    kg=_num(info.get("weight_one")) * (row.get("qty") or 0))
        self._pmk_xlsx_money_more(rows, add)
        for key, a in agg.items():
            ws.write(r, 0, key, fmt.wrap)
            ws.write(r, 1, a["m"] or "", fmt.kg)
            ws.write(r, 2, a["m2"] or "", fmt.dec2)
            ws.write(r, 3, a["kg"], fmt.kg)
            ws.write(r, 4, a["buy"] or "", fmt.kg)
            ws.write(r, 5, a["rub"] or "", fmt.rub)
            r += 1
        ws.write(r, 0, _("Итого"), fmt.total)
        ws.write(r, 1, "", fmt.total)
        ws.write(r, 2, "", fmt.total)
        for col, letter in ((3, "D"), (4, "E")):
            ws.write_formula(r, col, "=SUM(%s%d:%s%d)" % (letter, first + 1, letter, r), fmt.total_kg)
        ws.write_formula(r, 5, "=SUM(F%d:F%d)" % (first + 1, r), fmt.total_rub)
        r += 2
        ws.write(r, 0, _("Деньги по изделиям"), fmt.bold)
        r += 1
        ws.write_row(r, 0, [_("Изделие"), _("Кол-во"), _("Металл, ₽"), _("Цена клиенту, ₽"),
                            _("Маржа, ₽"), _("Маржа, %")], fmt.th)
        first = r = r + 1
        for row in rows:
            cost = _num((row.get("foot") or {}).get("cost_one")) * (row.get("qty") or 0)
            total = _num(row.get("total"))
            ws.write(r, 0, (row.get("name") or "").strip(), fmt.wrap)
            ws.write(r, 1, row.get("qty") or 0, fmt.int)
            ws.write(r, 2, cost or "", fmt.rub)
            ws.write(r, 3, total, fmt.rub if total else fmt.rub_warn)
            ws.write_formula(r, 4, "=D%d-C%d" % (r + 1, r + 1), fmt.rub)
            ws.write_formula(r, 5, "=IF(D%d=0,0,E%d/D%d*100)" % (r + 1, r + 1, r + 1), fmt.pct)
            r += 1
        ws.write(r, 0, _("Итого по расчёту"), fmt.total)
        ws.write(r, 1, "", fmt.total)
        for col, letter in ((2, "C"), (3, "D"), (4, "E")):
            ws.write_formula(r, col, "=SUM(%s%d:%s%d)" % (letter, first + 1, letter, r), fmt.total_rub)
        ws.write_formula(r, 5, "=IF(D%d=0,0,E%d/D%d*100)" % (r + 1, r + 1, r + 1), fmt.total_pct)
        ws.write(r + 2, 0, _("Металл — закупка по прайсам поставщиков (самая низкая цена), целыми листами "
                             "и хлыстами, без переделов и покраски. Зонты и доборка — площадь и вес листа."),
                 fmt.muted)
        ws.set_column(0, 0, 60)
        ws.set_column(1, 5, 15)


class _Formats:
    """Стили книги: Arial 10, рамки, бежевая шапка, жёлтым — «нет цены»."""

    def __init__(self, wb):
        def f(**kw):
            return wb.add_format(dict({"font_name": "Arial", "font_size": 10, "valign": "vcenter"}, **kw))
        rub = '# ##0.00" ₽"'
        self.h1 = f(bold=True, font_size=14)
        self.muted = f(font_color="#6b6b6b")
        self.plain = f()
        self.bold = f(bold=True, font_size=11)
        self.th = f(bold=True, bg_color="#EEEAE0", border=1, text_wrap=True, align="center")
        self.cell = f(border=1)
        self.wrap = f(border=1, text_wrap=True)
        self.center = f(border=1, align="center")
        self.int = f(border=1, num_format="# ##0")
        self.kg = f(border=1, num_format="# ##0.0")
        self.dec2 = f(border=1, num_format="# ##0.00")
        self.rub = f(border=1, num_format=rub)
        self.rub_warn = f(border=1, num_format=rub, bg_color="#FFF4CC")
        self.warn_text = f(border=1, align="center", bg_color="#FFF4CC")
        self.pct = f(border=1, num_format='0.0"%"')
        self.total = f(bold=True, border=1, bg_color="#F6F4EE")
        self.total_kg = f(bold=True, border=1, bg_color="#F6F4EE", num_format="# ##0.0")
        self.total_rub = f(bold=True, border=1, bg_color="#F6F4EE", num_format=rub)
        self.total_pct = f(bold=True, border=1, bg_color="#F6F4EE", num_format='0.0"%"')
        self.section = f(bold=True, border=1, bg_color="#F6F4EE")
        self.merged = f(border=1, align="center", bold=True)
        self.merged_wrap = f(border=1, text_wrap=True)
        self.vat_label = f(align="right", italic=True)
        self.vat = f(italic=True, num_format=rub)
