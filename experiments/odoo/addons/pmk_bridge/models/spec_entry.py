# -*- coding: utf-8 -*-
"""Ввод строк во вкладке «Металлоизделия» (Антон 22.10.2026: «забиваем общий список, а потом
разносим по категориям»).

Строку набирают (или вставляют столбиком из Excel и письма) в сводке, и она сама уходит в свою
категорию — категория включается, если была выключена:
  • «дэ 2500мм 0,45мм рал8017 10шт» — доборный элемент: длина планки, лист (оцинковка нужной
    толщины), цвет, количество. Профиль потом рисуют в редакторе — развёртка посчитается, цену
    вписывает менеджер;
  • «зонт 500х1000 0,65 8017 2шт» — вентзонт: размер шахты, толщина, цвет, количество — всегда
    все четыре (Антон 22.10.2026);
  • «бф 2.1 м30 600 09г2с 16шт» — фундаментный болт (pmk_bolt дописывает свой разбор);
  • всё остальное — изделие «Конструкций» без состава («Ферма Ф-2 3шт»).
Правят — во вкладке своей категории, как и раньше. Ошиблась категория — «Перенести в»: строка
переносится, пока у неё нет своей работы (у изделия — деталей, у доборки — нарисованного профиля).

Расчёт → черновик счёта по-прежнему в одну сторону (pmk_orders): новая строка с ценой попадёт в
черновик, без цены — в «без цены клиенту».
"""
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

QTY_RE = re.compile(r"(\d+)\s*шт\b")
SIZE_RE = re.compile(r"(\d{2,5})\s*[хx×*]\s*(\d{2,5})")
THICK_RE = re.compile(r"(?<![\d.,])(\d[.,]\d{1,2})\s*(?:мм)?(?![\d.,])")
RAL_RE = re.compile(r"(?:рал|ral)\s*-?\s*(\d{4})\b")
MM_RE = re.compile(r"(?<![\d.,])(\d{2,5})\s*мм\b")
INT_RE = re.compile(r"(?<![\d.,хx×*])(\d{2,5})(?![\d.,хx×*])")
ZINC_RE = re.compile(r"\b(цинк|оц\w*)\b")

ROUTES = [("dobor", re.compile(r"^\s*дэ\b")), ("vent", re.compile(r"^\s*(зонт|вз)\b"))]
LABELS = {"metal": "Конструкции", "dobor": "Доборка", "vent": "Вентзонты"}


WORD_RE = re.compile(r"[а-яa-z]{3,}")
STOP_WORDS = {"ral", "рал", "мм", "шт", "зонт", "цинк", "лист", "планка", "доборный", "элемент"}


def _same_start(word, name):
    """«вино» ~ «винный», «белый» ~ «белая», «шоколад» ~ «шоколадный»: общее начало от 3 букв,
    расходятся не больше чем двумя последними буквами более короткого слова (окончание)."""
    n = 0
    for a, b in zip(word, name):
        if a != b:
            break
        n += 1
    return n >= max(3, min(len(word), len(name)) - 2)


def _low(text):
    return (text or "").lower().replace("ё", "е")


def _num(value):
    return ("%g" % value).replace(".", ",")


class EntryText(models.AbstractModel):
    """Как строку набрали в сводке — для «Перенести в»."""
    _name = "pmk.summary.entry.mixin"
    _description = "Строка из сводки «Металлоизделия»"

    pmk_entry_text = fields.Char("Набрано в сводке", copy=False)
    # №312 (Голубенко, Антон 23.10.2026): сквозной порядок строк сводки «Металлоизделия» —
    # он же порядок строк в КП и счёте. 0 — не перетаскивали: строка идёт блоком своей
    # категории после расставленных.
    pmk_kp_seq = fields.Integer("Порядок в КП", copy=False, default=0)


class MetalSpecProductEntry(models.Model):
    _name = "pmk.metal.spec.product"
    _inherit = ["pmk.metal.spec.product", "pmk.summary.entry.mixin"]


class DoborLineEntry(models.Model):
    _name = "pmk.dobor.order.line"
    _inherit = ["pmk.dobor.order.line", "pmk.summary.entry.mixin"]


class VentHoodEntry(models.Model):
    _name = "pmk.vent.hood"
    _inherit = ["pmk.vent.hood", "pmk.summary.entry.mixin"]


class MetalSpecEntry(models.Model):
    _inherit = "pmk.metal.spec"

    # ─── Куда идёт строка ───────────────────────────────────────────────
    def _pmk_entry_route(self, text):
        low = _low(text)
        for key, rx in ROUTES:
            if rx.match(low):
                return key
        return "metal"

    def _pmk_entry_labels(self):
        return dict(LABELS)

    def pmk_summary_add(self, texts):
        """Строки из сводки → категории. Ответ: {"added": {категория: N}, "errors": [...]}."""
        self.ensure_one()
        self.check_access("write")
        labels = self._pmk_entry_labels()
        added, errors = {}, []
        for text in texts or []:
            text = re.sub(r"\s+", " ", str(text or "")).strip()
            if not text:
                continue
            cat = self._pmk_entry_route(text)
            error = self._pmk_entry_add(cat, text)
            if error:
                errors.append("«%s»: %s" % (text, error))
            else:
                added[labels[cat]] = added.get(labels[cat], 0) + 1
        return {"added": added, "errors": errors}

    def _pmk_entry_add(self, cat, text):
        """Одна строка в категорию cat. Ошибка — текстом (строка не заведена), иначе None."""
        try:
            with self.env.cr.savepoint():
                getattr(self, "_pmk_entry_%s" % cat)(text)
        except (UserError, ValidationError) as exc:
            return exc.args[0] if exc.args else str(exc)
        return None

    # ─── Разбор общих частей ────────────────────────────────────────────
    def _pmk_entry_qty(self, low):
        m = QTY_RE.search(low)
        return (int(m.group(1)), low[:m.start()] + " " + low[m.end():]) if m else (1, low)

    def _pmk_entry_coating(self, low):
        """Цвет: «рал8017» / «ral 8017», голое «8017», если такой RAL есть в справочнике, название
        цвета из справочника («вино», «шоколад», «графит»), «цинк». Ответ: (покрытие, строка без цвета)."""
        Coating = self.env["pmk.dobor.coating"]
        m = RAL_RE.search(low)
        if m:
            coating = Coating.search([("ral_code", "=", m.group(1))], limit=1)
            if not coating:
                raise UserError(_("цвета RAL %s нет в справочнике «Цвета доборки (RAL)»") % m.group(1))
            return coating, low[:m.start()] + " " + low[m.end():]
        for m in INT_RE.finditer(low):
            if len(m.group(1)) == 4:
                coating = Coating.search([("ral_code", "=", m.group(1))], limit=1)
                if coating:
                    return coating, low[:m.start()] + " " + low[m.end():]
        coating, low2 = self._pmk_entry_coating_word(low)
        if coating:
            return coating, low2
        m = ZINC_RE.search(low)
        if m:
            zinc = self.env.ref("pmk_calc.coating_zinc", raise_if_not_found=False) \
                or Coating.search([("name", "=ilike", "Цинк")], limit=1)
            return zinc, low[:m.start()] + " " + low[m.end():]
        return Coating, low

    def _pmk_entry_coating_word(self, low):
        """Цвет словом (Антон 22.10.2026: «вино» → RAL 3005): слово строки совпадает началом
        (от 3 букв) со словом названия покрытия в справочнике — «вино», «винный» → «RAL 3005 Вино».
        Два разных покрытия — ошибка: уточнить RAL."""
        Coating = self.env["pmk.dobor.coating"]
        words = [(m, m.group(0)) for m in WORD_RE.finditer(low) if m.group(0) not in STOP_WORDS]
        found = {}
        for coating in Coating.search([("ral_code", "!=", False)]):
            names = [w for w in WORD_RE.findall(_low(coating.name)) if w not in STOP_WORDS]
            for m, word in words:
                if any(_same_start(word, name) for name in names):
                    found.setdefault(coating, m)
        if len(found) > 1:
            raise UserError(_("цвет неоднозначен (%s) — допишите RAL, например «рал%s»")
                            % (", ".join(c.name for c in found), next(iter(found)).ral_code))
        if found:
            coating, m = next(iter(found.items()))
            return coating, low[:m.start()] + " " + low[m.end():]
        return Coating, low

    def _pmk_entry_sheet(self, low):
        """Толщина «0,45» / «0.45мм» → оцинкованный лист справочника. (лист, строка без толщины)."""
        m = THICK_RE.search(low)
        if not m:
            return self.env["pmk.metal.sheet"], low
        thick = float(m.group(1).replace(",", "."))
        sheet = self.env["pmk.metal.sheet"].search(
            [("sheet_type", "=", "Оцинкованный"), ("thickness_mm", ">=", thick - 0.001),
             ("thickness_mm", "<=", thick + 0.001)], limit=1)
        if not sheet:
            raise UserError(_("оцинкованного листа %s мм нет в справочнике «Лист»") % _num(thick))
        return sheet, low[:m.start()] + " " + low[m.end():]

    @staticmethod
    def _pmk_coating_label(coating):
        """«RAL 8017 Шоколад» → «RAL 8017 (шоколад)», «Цинк» → «цинк»."""
        if not coating:
            return ""
        name = (coating.name or "").strip()
        if coating.ral_code:
            rest = re.sub(r"(?i)^\s*ral\s*%s\s*" % re.escape(coating.ral_code), "", name).strip()
            return "RAL %s (%s)" % (coating.ral_code, rest.lower()) if rest else "RAL %s" % coating.ral_code
        return name.lower()

    # ─── Конструкции ────────────────────────────────────────────────────
    def _pmk_entry_metal(self, text):
        m = QTY_RE.search(_low(text))
        qty = int(m.group(1)) if m else 1
        name = (text[:m.start()] + " " + text[m.end():]) if m else text
        name = re.sub(r"\s+", " ", name).strip(" ,;-")
        if not name:
            raise UserError(_("нет названия изделия"))
        if not self.cat_metal:
            self.cat_metal = True
        seq = max(self.product_ids.mapped("sequence") or [0]) + 10
        return self.env["pmk.metal.spec.product"].create({
            "spec_id": self.id, "name": name, "qty": qty, "sequence": seq, "pmk_entry_text": text})

    # ─── Доборка ────────────────────────────────────────────────────────
    def _pmk_entry_dobor(self, text):
        low = re.sub(r"^\s*дэ\b", " ", _low(text))
        qty, low = self._pmk_entry_qty(low)
        coating, low = self._pmk_entry_coating(low)
        sheet, low = self._pmk_entry_sheet(low)
        m = MM_RE.search(low) or INT_RE.search(low)
        length = float(m.group(1)) if m else 0.0
        if not length:
            raise UserError(_("нет длины планки — допишите, например, «2500мм»"))
        if not sheet:
            raise UserError(_("нет толщины листа — допишите, например, «0,45мм»"))
        parts = ["ДЭ %s мм" % _num(length), "%s мм" % _num(sheet.thickness_mm)]
        if coating:
            parts.append(self._pmk_coating_label(coating))
        if not self.cat_dobor:
            self.cat_dobor = True
        order = self.dobor_order_ids[:1] or self.env["pmk.dobor.order"].create(self._pmk_child_vals("pmk.dobor.order"))
        vals = {"order_id": order.id, "title": " · ".join(parts), "plank_length": length, "qty": qty,
                "sheet_id": sheet.id, "pmk_entry_text": text,
                "sequence": max(order.line_ids.mapped("sequence") or [0]) + 10}
        if coating:
            vals["coating_id"] = coating.id
        return self.env["pmk.dobor.order.line"].create(vals)

    # ─── Вентзонты ──────────────────────────────────────────────────────
    def _pmk_entry_vent(self, text):
        low = re.sub(r"^\s*(зонт|вз)\b", " ", _low(text))
        qty, low = self._pmk_entry_qty(low)
        m = SIZE_RE.search(low)
        if not m:
            raise UserError(_("нет размера шахты — допишите, например, «500х1000»"))
        a, b = int(m.group(1)), int(m.group(2))
        low = low[:m.start()] + " " + low[m.end():]
        coating, low = self._pmk_entry_coating(low)
        sheet, low = self._pmk_entry_sheet(low)
        if not coating:
            raise UserError(_("нет цвета — допишите, например, «8017» или «цинк»"))
        if not self.cat_vent:
            self.cat_vent = True
        order = self.vent_order_ids[:1] or self.env["pmk.vent.hood.order"].create(
            self._pmk_child_vals("pmk.vent.hood.order"))
        vals = {"order_id": order.id, "width": min(a, b), "length": max(a, b), "qty": qty,
                "coating_id": coating.id, "pmk_entry_text": text,
                "sequence": max(order.line_ids.mapped("sequence") or [0]) + 10}
        if sheet:
            vals["sheet_id"] = sheet.id
        return self.env["pmk.vent.hood"].create(vals)

    # ─── «Перенести в» ──────────────────────────────────────────────────
    def _pmk_entry_source(self, key):
        """Ключ строки сводки → (запись, текст для переноса) или ошибка, если переносить нельзя."""
        kind, _sep, rid = str(key or "").partition("-")
        if not rid.isdigit():
            raise UserError(_("Строка не найдена — обновите страницу."))
        rid = int(rid)
        if kind == "metal":
            record = self.product_ids.filtered(lambda p: p.id == rid)
            if record and record.line_ids:
                raise UserError(_("У изделия уже есть детали — переносить нельзя, только завести заново."))
            text = record.pmk_entry_text or "%s %sшт" % (record.name, record.qty)
        elif kind == "dobor":
            record = self.dobor_line_ids.filtered(lambda l: l.id == rid)
            if record and record.developed_width:
                raise UserError(_("У доборки уже нарисован профиль — переносить нельзя."))
            text = record.pmk_entry_text or "%s %sшт" % (record.title or "", record.qty)
        elif kind == "vent":
            record = self.vent_line_ids.filtered(lambda h: h.id == rid)
            text = record.pmk_entry_text or "%s×%s %sшт" % (record.width, record.length, record.qty)
        else:
            return self._pmk_entry_source_more(kind, rid)
        if not record:
            raise UserError(_("Строка не найдена — обновите страницу."))
        return record, text

    def _pmk_entry_source_more(self, kind, rid):
        raise UserError(_("Строка не найдена — обновите страницу."))

    def pmk_summary_move(self, key, target):
        """Перенести строку сводки в другую категорию: заводим там по набранному тексту, исходную
        удаляем. Не разобралось в новой категории — исходная остаётся, ответ с ошибкой."""
        self.ensure_one()
        self.check_access("write")
        labels = self._pmk_entry_labels()
        if target not in labels:
            raise UserError(_("Нет такой категории."))
        record, text = self._pmk_entry_source(key)
        body = re.sub(r"^\s*(дэ|зонт|вз|бф|болт)\b\s*", "", text, flags=re.I)
        prefix = {"dobor": "дэ ", "vent": "зонт ", "bolt": "бф "}.get(target, "")
        error = self._pmk_entry_add(target, text if target == "metal" else prefix + body)
        if error:
            return {"error": error}
        record.unlink()
        return {"moved": labels[target]}


class MetalSpecSummaryRows(models.Model):
    """№312: строки сводки — перетащить, копировать, удалить (Голубенко 20.10, Антон 23.10.2026:
    «кнопки удалить, копировать во всех разделах; drag-n-drop перетаскивания позиций»)."""
    _inherit = "pmk.metal.spec"

    def _pmk_summary_record(self, key):
        """Ключ строки сводки → запись (изделие, позиция доборки, зонт; болт — pmk_bolt)."""
        kind, _sep, rid = str(key or "").partition("-")
        rid = int(rid) if rid.isdigit() else 0
        record = {"metal": self.product_ids, "dobor": self.dobor_line_ids,
                  "vent": self.vent_line_ids}.get(kind)
        record = record.filtered(lambda r: r.id == rid) if record is not None else None
        if record is None:
            record = self._pmk_summary_record_more(kind, rid)
        if not record:
            raise UserError(_("Строка не найдена — обновите страницу."))
        return kind, record

    def _pmk_summary_record_more(self, kind, rid):
        return None

    @staticmethod
    def _pmk_summary_sorted(rows):
        """Сначала расставленные (порядок в КП), потом остальные — блоками категорий, как были."""
        return sorted(rows, key=lambda r: (0 if r.get("kp") else 1, r.get("kp") or 0))

    def _pmk_summary_keys(self):
        return [r["key"] for r in (self.pmk_summary or {}).get("rows", [])]

    def pmk_summary_order(self, keys):
        """Новый порядок строк сводки (перетаскивание) — номера 10, 20, 30…"""
        self.ensure_one()
        self.check_access("write")
        for number, key in enumerate(keys or [], 1):
            _kind, record = self._pmk_summary_record(key)
            if record.pmk_kp_seq != number * 10:
                record.pmk_kp_seq = number * 10
        self.invalidate_recordset(["pmk_summary"])
        if hasattr(self, "_pmk_sync_draft_invoices"):
            self._pmk_sync_draft_invoices()
        return True

    def _pmk_summary_copy_record(self, kind, record):
        """Копия строки своим калькулятором; ответ — новая запись."""
        if kind == "metal":
            before = self.product_ids
            record.action_pmk_copy()
            return self.product_ids - before
        if kind in ("dobor", "vent"):
            before = record.order_id.line_ids
            record.action_pmk_copy()
            return record.order_id.line_ids - before
        return self.env[record._name]

    def pmk_summary_copy(self, key):
        """«Копировать» в сводке: копия сразу под исходной (и в сводке, и в своей вкладке)."""
        self.ensure_one()
        self.check_access("write")
        kind, record = self._pmk_summary_record(key)
        keys = self._pmk_summary_keys()
        new = self._pmk_summary_copy_record(kind, record)
        self.invalidate_recordset(["pmk_summary"])
        if new and any(self._pmk_summary_record(k)[1].pmk_kp_seq for k in keys):
            new_key = "%s-%s" % ("metal" if kind == "metal" else kind, new[:1].id)
            order = [k for k in keys]
            order.insert(order.index(key) + 1, new_key)
            self.pmk_summary_order(order)
        self.message_post(body=_("Скопировано в сводке: %s") % (record.display_name or ""),
                          subtype_xmlid="mail.mt_note")
        return True

    def pmk_summary_delete(self, key):
        """«Удалить» в сводке (с подтверждением на экране); запись — в историю расчёта."""
        self.ensure_one()
        self.check_access("write")
        kind, record = self._pmk_summary_record(key)
        name = record.display_name or ""
        labels = {"metal": _("Конструкции"), "dobor": _("Доборка"), "vent": _("Вентзонты")}
        label = labels.get(kind) or self._pmk_entry_labels().get(kind, kind)
        if kind in ("dobor", "vent"):
            record.action_pmk_delete()
        else:
            record.unlink()
        self.invalidate_recordset(["pmk_summary"])
        self.message_post(body=_("Удалено в сводке: %(name)s (%(cat)s)", name=name, cat=label),
                          subtype_xmlid="mail.mt_note")
        return True
