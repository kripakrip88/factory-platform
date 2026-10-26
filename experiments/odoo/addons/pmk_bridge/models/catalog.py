# -*- coding: utf-8 -*-
"""Каталог материалов — найти позицию справочника глазами (Антон 26.10.2026).

«Если менеджер или инженер делает расчёт, но не может попасть в нужную номенклатуру —
может вызвать каталог справочника и там найти вручную?» Окно (static/src/js/catalog_dialog.js):
слева разделы (прокат по видам, лист по видам, метизы по видам), сверху поиск и фильтры
(класс и покрытие у метизов, «только с ценой»), в таблице — масса, цена из прайса и
поставщик. «Выбрать» ставит позицию туда, откуда открыли: Бутик, «Конструкции», заявка на
металл, состав фундаментного болта. «Нет в справочнике — завести» — та же короткая форма
«на разнос», что в расчёте (шаг З-10).

Ключ позиции — «profile:ID» / «sheet:ID» / «fastener:ID», как у подсказок Бутика.
"""
import re

from odoo import api, fields, models

LIMIT = 80
FASTENER_TYPES = [("bolt", "Болт"), ("nut", "Гайка"), ("washer", "Шайба"), ("screw", "Саморез"),
                  ("anchor", "Анкер"), ("other", "Прочее")]
UNIT = {"profile": "м", "sheet": "м²", "fastener": "шт"}
WORDS = [("fastener", "bolt", r"болт"), ("fastener", "nut", r"гайк"), ("fastener", "washer", r"шайб"),
         ("fastener", "screw", r"саморез"), ("fastener", "anchor", r"анкер"), ("sheet", None, r"\bлист|\bпвл\b")]


# Значок раздела (static/src/catalog/catalog_dialog.xml, t-name «pmk_bridge.CatalogIcon»).
ICONS = [("двутавр", "ibeam"), ("швеллер", "channel"), ("уголок", "angle"), ("арматур", "rebar"),
         ("квадрат", "squarebar"), ("шестигран", "hexbar"), ("круг", "roundbar"),
         ("профильн", "rtube"), ("труба", "pipe"), ("полос", "strip"),
         ("рифл", "sheet_ribbed"), ("просеч", "sheet_mesh"), ("лист", "sheet")]


def _icon(name):
    low = (name or "").lower()
    return next((icon for word, icon in ICONS if word in low), "other")


def _sizes(label):
    """«М20×60» → (20.0, 60.0); для сортировки и фильтра диаметра."""
    return tuple(float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", label or ""))


def _num(value):
    return ("%g" % round(value, 3)).replace(".", ",") if value else ""


class MetalCatalog(models.AbstractModel):
    _name = "pmk.metal.catalog"
    _description = "Каталог материалов"

    # ─── разделы ─────────────────────────────────────────────────────────
    @api.model
    def catalog_tree(self, sections=None):
        """[{key, label, kinds: [{key, label, count}]}] — только разделы из sections (None — все)."""
        out = []
        if not sections or "profile" in sections:
            Profile = self.env["pmk.metal.profile"]
            counts = dict((g[0].id, g[1]) for g in Profile._read_group([], ["type_id"], ["__count"]) if g[0])
            kinds = [{"key": t.id, "label": t.name, "count": counts.get(t.id, 0), "icon": _icon(t.name)}
                     for t in self.env["pmk.metal.profile.type"].search([]) if counts.get(t.id)]
            out.append({"key": "profile", "label": "Прокат", "kinds": kinds})
        if not sections or "sheet" in sections:
            groups = self.env["pmk.metal.sheet"]._read_group([], ["sheet_type"], ["__count"])
            out.append({"key": "sheet", "label": "Лист",
                        "kinds": [{"key": k, "label": k, "count": n, "icon": _icon("лист " + k)}
                                  for k, n in sorted(groups) if k]})
        if not sections or "fastener" in sections:
            Fastener = self.env["pmk.metal.fastener"]
            counts = dict(Fastener._read_group([], ["fastener_type"], ["__count"]))
            diam = {}
            for row in Fastener.search_read([], ["fastener_type", "size_label"]):
                nums = _sizes(row["size_label"])
                if nums:
                    diam.setdefault(row["fastener_type"], set()).add(nums[0])
            out.append({"key": "fastener", "label": "Метизы",
                        "kinds": [{"key": k, "label": label, "count": counts.get(k, 0), "icon": k,
                                   "diameters": ["%g" % d for d in sorted(diam.get(k, ()))]}
                                  for k, label in FASTENER_TYPES if counts.get(k)]})
        return out

    @api.model
    def catalog_guess(self, text, sections=None):
        """С чего открыть окно: раздел и вид по тексту строки («болт 20х60» → Метизы · Болт, поиск
        «20х60»)."""
        low = (text or "").lower()
        for section, kind, rx in WORDS:
            if (not sections or section in sections) and re.search(rx, low):
                query = re.sub(rx + r"\w*\.?", " ", low).strip()
                if section == "sheet":
                    found = self.env["pmk.metal.sheet"].name_search(text, limit=1)
                    kind = self.env["pmk.metal.sheet"].browse(found[0][0]).sheet_type if found else None
                return {"section": section, "kind": kind, "query": query}
        if text and (not sections or "profile" in sections):
            found = self.env["pmk.metal.profile"].name_search(text, limit=1)
            if found:
                return {"section": "profile", "kind": self.env["pmk.metal.profile"].browse(found[0][0]).type_id.id,
                        "query": text}
        first = (sections or ["profile"])[0]
        return {"section": first, "kind": None, "query": text or ""}

    # ─── выборка ─────────────────────────────────────────────────────────
    @api.model
    def catalog_search(self, section, kind=None, query="", strength_class="", coating="", priced=False,
                       diameter=""):
        """Позиции раздела: {rows: [...], more: bool}."""
        query = (query or "").strip()
        if section == "all":
            # «Везде»: поиск сразу по прокату, листу и метизам (без фильтров раздела).
            if not query:
                return {"rows": [], "more": False}
            rows = []
            for sec in ("profile", "sheet", "fastener"):
                rows += self.catalog_search(sec, None, query, "", "", priced)["rows"]
            return {"rows": rows[:LIMIT], "more": len(rows) > LIMIT}
        if section == "profile":
            Model = self.env["pmk.metal.profile"]
            domain = [("type_id", "=", int(kind))] if kind else []
            recs = (Model.browse([r for r, _n in Model.name_search(query, domain=domain, limit=LIMIT * 3)])
                    if query else Model.search(domain, limit=LIMIT * 3))
        elif section == "sheet":
            Model = self.env["pmk.metal.sheet"]
            domain = [("sheet_type", "=", kind)] if kind else []
            recs = (Model.browse([r for r, _n in Model.name_search(query, domain=domain, limit=LIMIT * 3)])
                    if query else Model.search(domain, order="sheet_type, thickness_mm", limit=LIMIT * 3))
        else:
            Model = self.env["pmk.metal.fastener"]
            domain = [("fastener_type", "=", kind)] if kind else []
            if strength_class:
                domain.append(("strength_class", "=", strength_class))
            if coating:
                domain.append(("coating", "=", coating))
            if diameter:
                # «М20» и «М20×60» — диаметр до знака «×» (саморез «5.5×19» — тоже).
                domain += ["|", ("size_label", "=", "М%s" % diameter), "|",
                           ("size_label", "=like", "М%s×%%" % diameter), ("size_label", "=like", "%s×%%" % diameter)]
            recs = Model.search(domain).sorted(lambda f: (f.fastener_type, _sizes(f.size_label), f.gost or "",
                                                          f.full_thread, float(f.strength_class or 0), f.coating or "", f.id))
            words = [w for w in re.split(r"\s+", re.sub(r"(\d)\s*[xх×*]\s*(\d)", r"\1×\2", query.lower())) if w]
            words = [re.sub(r"^[мm](?=\d)", "", w) for w in words]
            if words:
                recs = recs.filtered(lambda f: all(
                    w in ("%s %s" % (f.name or "", f.gost or "")).lower() for w in words))
        today = fields.Date.context_today(self)
        rows = []
        for rec in recs:
            row = self._catalog_row(section, rec, today)
            if priced and not row["price"]:
                continue
            rows.append(row)
            if len(rows) >= LIMIT:
                break
        return {"rows": rows, "more": len(rows) >= LIMIT}

    def _catalog_row(self, section, rec, today):
        tmpl = getattr(rec, "product_tmpl_id", False)
        seller = tmpl._pmk_find_seller(today) if tmpl else False
        if section == "profile":
            mass = "%s кг/м" % _num(rec.mass_per_meter)
        elif section == "sheet":
            mass = "%s кг/м²" % _num(rec.mass_per_sqm)
        else:
            mass = "%s кг" % _num(rec.weight_kg)
        price = seller.price_discounted if seller else 0.0
        return {
            "key": "%s:%d" % (section, rec.id),
            "name": rec.display_name,
            "gost": rec.gost or "",
            "mass": mass,
            "price": round(price, 2),
            "unit": UNIT[section],
            "supplier": seller.partner_id.name if seller else "",
            "date": fields.Date.to_string(seller.date_start) if seller and seller.date_start else "",
            "pending": bool(getattr(rec, "pmk_pending", False)),
            "strength_class": getattr(rec, "strength_class", "") or "",
            "coating": dict(rec._fields["coating"].selection).get(rec.coating, "") if section == "fastener" else "",
        }
