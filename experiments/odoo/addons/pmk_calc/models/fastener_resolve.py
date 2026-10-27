# -*- coding: utf-8 -*-
"""Метиз по записи инженера — с классом и покрытием (26.10.2026).

С 26.10 у метиза отдельные позиции на класс прочности и покрытие (5.8 / 8.8 / 10.9 —
цены отличаются до двух раз). Подбор по одному имени («Болт М20×60») брал бы первую
попавшуюся — поэтому разбираем запись:

    вид        болт / гайка / шайба / анкер / саморез;
    размер     «М20×60», «м20х60», «20х60»; гайка и шайба — «М20»; саморез «5,5х19»;
    класс      «кл. 8.8», «8.8», «кл.пр.10» (у гайки 8 / 10 / 12);
    покрытие   «цинк», «оц», «Zn» — цинк; «гц», «гор. цинк» — горячий; «RAL», «рал», «8017» —
               окрашенный; не указано — без покрытия (Антон 26.10), у самореза — цинк;
    подвид     «высокопрочный», «52644» — ГОСТ Р 5264x; «пружинная», «гровер» — ГОСТ 6402;
               «полная резьба», «933» — полная резьба (иначе — обычный).

Класс у болта не указан, а позиций разных классов несколько — НЕ подставляем (пусто,
строка «не найдено»): цена 5.8 и 10.9 разная, угадывать нельзя. У гайки без класса —
обычная ГОСТ 5915 без класса, если такая есть.
"""
import re

from odoo import api, models

NUM = r"\d+(?:[.,]\d+)?"
TYPE_RE = [("bolt", r"болт"), ("nut", r"гайк"), ("washer", r"шайб"), ("anchor", r"анкер"),
           ("screw", r"саморез")]
SIZE_RE = re.compile(r"(?<![\d.,])[мm]?\s*(%s)(?:\s*[xх×*]\s*(%s))?" % (NUM, NUM), re.I)
CLASS_RE = re.compile(r"кл\.?\s*(?:пр\.?)?\s*(\d{1,2}(?:[.,]\d)?)|(?<![\d.,])(5[.,]8|8[.,]8|10[.,]9|12[.,]9)(?![\d])",
                      re.I)
HOT_RE = re.compile(r"гор\w*\.?\s*цинк|\bгц\b|горяч", re.I)
ZINC_RE = re.compile(r"цинк|\bоц\w*|\bzn\b", re.I)
PAINT_RE = re.compile(r"\bral\b|\bрал\b|окраш|(?<![\d.,])(?:10|20|30|50|60|70|80|90)\d\d(?![\d.,])", re.I)
HS_RE = re.compile(r"высокопр|5264[456]|\bвп\b", re.I)
SPRING_RE = re.compile(r"пружин|гровер|6402", re.I)
BIG_RE = re.compile(r"увелич|6958|9021", re.I)
OBLIQUE_RE = re.compile(r"\bкос\w*|10906", re.I)
LOCK_RE = re.compile(r"стопор|самоконтр|\b985\b", re.I)
FULL_RE = re.compile(r"полн\w*\s*резьб|\b933\b|7805", re.I)
SCREW_KIND = [("кровельный", r"кровел|ш/г"), ("с прессшайбой", r"пресс|п/ш"), ("для сэндвич", r"сэндвич")]
COAT_ORDER = {"black": 0, "zinc": 1, "hot_zinc": 2, "painted": 3, False: 4}


def _f(text):
    return float(text.replace(",", "."))


def parse(text):
    """Запись → признаки (то, чего в записи нет, — None)."""
    low = (text or "").lower().replace("ё", "е")
    out = {"type": next((t for t, rx in TYPE_RE if re.search(rx, low)), None)}
    # Размер — первое «число[×число]» после слова вида; класс «8.8» размером не считаем.
    body = CLASS_RE.sub(" ", low)
    body = re.sub(r"гост\s*р?\s*[\d.\-]+|din\s*\d+|iso\s*\d+", " ", body)
    m = SIZE_RE.search(body)
    out["d"], out["l"] = (_f(m.group(1)), _f(m.group(2)) if m.group(2) else None) if m else (None, None)
    c = CLASS_RE.search(low)
    out["class"] = (c.group(1) or c.group(2)).replace(",", ".") if c else None
    if out["class"] and "." not in out["class"] and out["type"] == "bolt":
        out["class"] = None
    out["coating"] = ("hot_zinc" if HOT_RE.search(low) else "zinc" if ZINC_RE.search(low)
                      else "painted" if PAINT_RE.search(body) else None)
    out["hs"] = bool(HS_RE.search(low))
    out["spring"] = bool(SPRING_RE.search(low))
    out["big"] = bool(BIG_RE.search(low))
    out["oblique"] = bool(OBLIQUE_RE.search(low))
    out["lock"] = bool(LOCK_RE.search(low))
    out["full"] = bool(FULL_RE.search(low))
    out["screw_kind"] = next((k for k, rx in SCREW_KIND if re.search(rx, low)), None)
    return out


def _size(label):
    nums = re.findall(NUM, (label or "").replace("×", "x"))
    return tuple(_f(n) for n in nums)


class MetalFastenerResolve(models.Model):
    _inherit = "pmk.metal.fastener"

    @api.model
    def _pmk_same_size(self, info):
        """Позиции того же вида, размера и подвида — без учёта класса, покрытия и резьбы."""
        if not info["type"] or not info["d"]:
            return self.browse()
        want = (info["d"], info["l"]) if info["l"] else (info["d"],)
        cands = self.search([("fastener_type", "=", info["type"])]).filtered(
            lambda f: _size(f.size_label) == want)
        if info["type"] in ("bolt", "nut", "washer"):
            cands = cands.filtered(lambda f: ("5264" in (f.gost or "")) == info["hs"])
        if info["type"] == "washer" and not info["hs"]:
            cands = cands.filtered(lambda f: ("6402" in (f.gost or "")) == info["spring"]
                                   and ("6958" in (f.gost or "")) == info["big"]
                                   and ("10906" in (f.gost or "")) == info["oblique"])
        if info["type"] == "nut" and not info["hs"]:
            cands = cands.filtered(lambda f: ("985" in (f.gost or "")) == info["lock"])
        if info["type"] == "screw" and info["screw_kind"]:
            cands = cands.filtered(lambda f: info["screw_kind"] in (f.name or ""))
        return cands

    @api.model
    def _pmk_variants(self, text):
        """Выбор для ячейки «Марка» (27.10.2026, Антон: «выпадашка в марке, как у листа»): все
        классы / покрытия / резьбы этого размера — по классу, потом покрытию."""
        return self._pmk_same_size(parse(text)).sorted(
            lambda f: (f.strength_class or "", COAT_ORDER.get(f.coating, 4), f.full_thread, f.id))

    def _pmk_variant_label(self):
        """«кл. 8.8 · цинк · полная резьба» — то, чем позиция отличается от соседей по размеру."""
        self.ensure_one()
        coat = dict(self._fields["coating"]._description_selection(self.env)).get(self.coating) or ""
        parts = ["кл. %s" % self.strength_class if self.strength_class else "",
                 "" if self.coating in (False, "black") else coat.lower(),
                 "полная резьба" if self.full_thread else ""]
        return " · ".join(p for p in parts if p) or "без класса"

    @api.model
    def _pmk_resolve(self, text):
        """Позиция справочника по записи или пустой набор (не найдено / неоднозначно)."""
        info = parse(text)
        cands = self._pmk_same_size(info)
        if not cands:
            return self.browse()
        if info["type"] == "bolt":
            cands = cands.filtered(lambda f: f.full_thread == info["full"])
        if info["class"]:
            cands = cands.filtered(lambda f: (f.strength_class or "") == info["class"])
        elif len(set(cands.mapped(lambda f: f.strength_class or ""))) > 1:
            plain = cands.filtered(lambda f: not f.strength_class)
            if info["type"] == "bolt" or not plain:
                return self.browse()        # класс не указан — цену 5.8 за 10.9 не выдаём
            cands = plain
        if info["coating"]:
            cands = cands.filtered(lambda f: f.coating == info["coating"])
        else:
            default = "zinc" if info["type"] == "screw" else "black"
            if cands.filtered(lambda f: f.coating == default):
                cands = cands.filtered(lambda f: f.coating == default)
        return cands.sorted(lambda f: (COAT_ORDER.get(f.coating, 4), f.strength_class or "", f.id))[:1]
