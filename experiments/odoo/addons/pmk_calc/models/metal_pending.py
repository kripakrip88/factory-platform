# -*- coding: utf-8 -*-
"""Позиция «на разнос»: нет в справочнике — завели из расчёта (шаг З-10).

Вопрос Антона 08.10.2026: «как быть инженеру, если он не нашёл нужную
номенклатуру в справочнике? создаёт новый материал, который мы потом
отдельно правильно разносим по справочнику?». Решения: заводят и менеджер
(в расчёте КП), и инженер (в техническом расчёте); разносит справочник пока
администратор.

КАК ЗАВОДЯТ. В выпадашке «Типоразмер» / «Лист» / «Метиз» детали — строка
«Нет в справочнике — завести новую…» (static/src/js/pending_create.js).
Короткое окно (views/pending_views.xml, формы *_pending_form): название как в
чертеже — обязательно; у проката — вид (из справочника видов, есть «Прочее»)
и вес погонного метра; у листа — толщина (обязательно) и масса м² (толщина ×
7,85); у метиза — вес штуки. Позиция встаёт с меткой pmk_pending, помнит,
кто завёл (create_uid) и в каком расчёте (pmk_pending_spec_id), и сразу
выбрана в детали.

НАБЛЮДАТЬ, А НЕ КОНТРОЛИРОВАТЬ. Позиция «на разнос» ничего не держит: КП,
счёт, заявка уходят как обычно. Вес не знают — деталь считается с весом 0 и
пометкой «нет веса» (как «нет цены»), без ошибки. Цены нет — карточки товара
у позиции нет, мост считает её «нет цены» (сигнал «в городе нет»).

РАЗНОС — администратор (base.group_system), список «Справочники → Новые
позиции на разнос» (metal_pending_report.py):
  • «Привязать к существующей» (_pmk_pending_bind): во ВСЕХ деталях всех
    расчётов (и в раскроях, заданиях лазеру, доборках — всюду, где поле
    ссылается на этот справочник) позиция заменяется настоящей, в ленту
    расчётов — заметка, временная — в архив;
  • «Принять в справочник» (action_pmk_accept): дозаполнить вид, стандарт,
    массу — метка снимается, позиция обычная; мост (pmk_bridge) заводит ей
    карточку товара (_pmk_after_accept).

ПРАВА. Создавать позиции справочника может каждый сотрудник
(security/ir.model.access.csv: perm_create), но только «на разнос»: create()
ставит метку всем, кроме администратора, и правило записи
(security/pending_rules.xml) не пропустит другую. Править и удалять —
по-прежнему только администратор. Снять метку может только он. «Новый» в
списках и формах справочников сотруднику не показан (create="0",
администратору возвращает get_view примеси ниже):
заводят из детали расчёта.

В ВЫПАДАШКЕ позиции «на разнос» — в конце и не больше PENDING_SLOTS мест,
настоящие позиции они не вытесняют (_pmk_merge_pending).
"""
import re

from lxml import etree

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain


def _plural(number, one, few, many):
    """«1 деталь», «3 детали», «7 деталей». Своя копия правила spec_layout:
    импорт оттуда завёл бы его модели раньше моделей расчёта (metal_spec
    импортирует этот файл)."""
    number = abs(int(number))
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


# Масса квадратного метра гладкого листа на миллиметр толщины, кг/м²
# (ГОСТ 19903-2015; так же считает весь справочник листа).
STEEL_KG_PER_SQM_MM = 7.85
# Стандарт позиции, у которой его ещё не знают: поле обязательное.
NO_GOST = "—"
# Вид листа и метиза, пока их не знают.
OTHER_KIND = "Прочее"
OTHER_PROFILE_TYPE = "pmk_calc.profile_type_other"

PENDING_LABEL = "на разнос"
NO_WEIGHT_LABEL = "нет веса"
# Сколько мест выпадашки могут занять позиции «на разнос», когда настоящих
# позиций под ввод больше, чем строк (_pmk_merge_pending).
PENDING_SLOTS = 2

# Слова названия из чертежа для поиска: «уг 75х6» → «уг», «75», «6».
_WORDS = re.compile(r"[\s×xх*]+")


def is_reference_admin(env):
    """Ведёт справочник: администратор (или код под суперпользователем)."""
    return env.su or env.user.has_group("base.group_system")


class MetalPendingMixin(models.AbstractModel):
    """Метка «на разнос» и разнос — одно на три справочника."""

    _name = "pmk.metal.pending.mixin"
    _description = "Позиция справочника «на разнос»"

    # Задаются у справочника: поле детали, вид позиции, поле массы единицы.
    _pmk_line_field = None
    _pmk_kind = None
    _pmk_mass_field = None

    # Временная позиция после «Привязать к существующей» уходит в архив, а
    # не удаляется: на неё могли ссылаться документы, которых разнос не
    # знает, и история («что было в чертеже») остаётся.
    active = fields.Boolean(
        "Действует", default=True,
        help="Снята — позиция в архиве: её привязали к существующей позиции "
             "справочника. В выпадашках её нет.")
    pmk_pending = fields.Boolean(
        "На разнос", index=True, copy=False,
        help="Позицию завели из расчёта: в справочнике её не было. Расчёт, КП "
             "и заявку она не держит; администратор привяжет её к "
             "существующей позиции или примет в справочник.")
    pmk_pending_name = fields.Char(
        "Название как в чертеже", copy=False,
        help="Как позицию записали в расчёте. Пока она «на разнос», это и "
             "есть её название.")
    pmk_pending_spec_id = fields.Many2one(
        "pmk.metal.spec", "Где завели", ondelete="set null", copy=False,
        readonly=True, help="Расчёт, в детали которого позицию завели.")
    pmk_pending_label = fields.Char(
        "Разнос", compute="_compute_pmk_pending_label",
        help="«на разнос» — позицию завели из расчёта, её проверит "
             "администратор справочника.")
    pmk_no_weight = fields.Boolean("Нет веса", compute="_compute_pmk_pending_label")
    pmk_pending_spec_ids = fields.Many2many(
        "pmk.metal.spec", string="В расчётах", compute="_compute_pmk_pending_usage")
    pmk_pending_spec_count = fields.Integer(
        "В расчётах", compute="_compute_pmk_pending_usage")
    pmk_pending_line_count = fields.Integer(
        "Деталей", compute="_compute_pmk_pending_usage")

    # ─── Метки ──────────────────────────────────────────────────────────
    def _pmk_unit_mass(self):
        """Масса единицы: кг/м проката, кг/м² листа, кг/шт метиза."""
        self.ensure_one()
        return self[self._pmk_mass_field] or 0.0

    @api.depends(lambda self: ("pmk_pending", self._pmk_mass_field or "pmk_pending"))
    def _compute_pmk_pending_label(self):
        for rec in self:
            rec.pmk_pending_label = PENDING_LABEL if rec.pmk_pending else False
            rec.pmk_no_weight = not rec._pmk_unit_mass()

    def _pmk_lines(self):
        """Детали расчётов, где стоят эти позиции (все расчёты, sudo)."""
        ids = [i for i in self._origin.ids if i]
        Line = self.env["pmk.metal.spec.line"].sudo()
        if not ids:
            return Line
        return Line.search([(self._pmk_line_field, "in", ids)])

    def _compute_pmk_pending_usage(self):
        by_item = {}
        for line in self._pmk_lines():
            by_item.setdefault(line[self._pmk_line_field].id, []).append(line)
        Spec = self.env["pmk.metal.spec"]
        for rec in self:
            lines = by_item.get(rec._origin.id, [])
            specs = Spec.browse(sorted({line.spec_id.id for line in lines if line.spec_id}))
            rec.pmk_pending_line_count = len(lines)
            rec.pmk_pending_spec_ids = specs
            rec.pmk_pending_spec_count = len(specs)

    # ─── «Новый» в справочниках — только администратору ──────────────
    @api.model
    def get_view(self, view_id=None, view_type="form", **options):
        """Списки и формы справочника: create="1" администратору, "0" прочим.

        Право создавать у сотрудника есть (ради «на разнос» из детали), и без
        этого «Новый» горел бы у всех. Наследование вида с group_ids Odoo 19
        не принимает, а _get_view_cache общий для всех групп — поэтому здесь,
        после кэша, на каждый запрос."""
        res = super().get_view(view_id, view_type, **options)
        if view_type in ("list", "form") and res.get("arch"):
            arch = etree.fromstring(res["arch"])
            arch.set("create", "1" if is_reference_admin(self.env) else "0")
            res["arch"] = etree.tostring(arch, encoding="unicode")
        return res

    # ─── Заведение ──────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        admin = is_reference_admin(self.env)
        default = bool(self.env.context.get("default_pmk_pending"))
        for vals in vals_list:
            if not admin:
                # Сотрудник заводит только «на разнос» — так и из выпадашки
                # детали, и из списка справочника.
                vals["pmk_pending"] = True
            if vals.get("pmk_pending", default):
                vals["pmk_pending"] = True
                self._pmk_pending_fill(vals)
        return super().create(vals_list)

    @api.model
    def _pmk_pending_fill(self, vals):
        """Дозаполнить обязательные поля позиции «на разнос»: окно спрашивает
        только название и вес. У каждого справочника — своё."""
        return vals

    def write(self, vals):
        if "pmk_pending" in vals and not is_reference_admin(self.env):
            if any(rec.pmk_pending != bool(vals["pmk_pending"]) for rec in self):
                raise AccessError(_(
                    "Метку «на разнос» снимает администратор справочника — "
                    "кнопкой «Принять в справочник»."))
            vals = dict(vals)
            vals.pop("pmk_pending")
        pending = self.filtered("pmk_pending")
        result = super().write(vals)
        # Вес у позиции «на разнос» дописали — детали пересчитываются. У
        # обычной позиции справочника правило прежнее: вес старых расчётов
        # сам не меняется (вес детали зависит от позиции, а не от её массы).
        if pending and self._pmk_mass_field in vals:
            lines = pending._pmk_lines()
            if lines:
                lines.modified([self._pmk_line_field])
        return result

    # ─── Разнос (администратор) ─────────────────────────────────────────
    def _pmk_check_admin(self):
        if not is_reference_admin(self.env):
            raise AccessError(_(
                "Разносит позиции справочника администратор (Настройки → "
                "права «Администратор»)."))

    def _pmk_bind_targets(self):
        """(модель, поле) всех хранимых ссылок на этот справочник: детали
        расчётов, раскрои, задания лазеру, доборки — и то, что появится."""
        targets = []
        for name in self.env.registry:
            Model = self.env[name]
            if Model._abstract or Model._transient or not Model._auto:
                continue
            for fname, field in Model._fields.items():
                if (field.type == "many2one" and field.comodel_name == self._name
                        and field.store and not field.related
                        and not (field.compute and field.readonly)):
                    targets.append((name, fname))
        return targets

    def _pmk_pending_bind(self, target):
        """«Привязать к существующей»: всюду, где стоит эта позиция «на
        разнос», ставим настоящую; временную — в архив. → число деталей."""
        self.ensure_one()
        self._pmk_check_admin()
        if not self.pmk_pending:
            raise UserError(_("«%s» уже в справочнике — привязывать нечего.") % self.display_name)
        target = target.exists() if target else target
        if not target or target._name != self._name:
            raise UserError(_("Выберите позицию справочника того же вида."))
        if target == self or target.pmk_pending:
            raise UserError(_(
                "Выберите настоящую позицию справочника, а не другую «на разнос»."))
        old_name = self.display_name
        by_spec = {}
        laid_by_spec = {}
        for model_name, fname in self._pmk_bind_targets():
            records = self.env[model_name].sudo().with_context(active_test=False).search(
                [(fname, "=", self.id)])
            if not records:
                continue
            if model_name == "pmk.metal.spec.line":
                for line in records:
                    by_spec[line.spec_id] = by_spec.get(line.spec_id, 0) + 1
                    # Лист входит в раскладку (spec_layout.py, LAYOUT_INPUTS):
                    # смена листа гасит разложенные детали — как при ручной
                    # смене листа в детали. Молча не гасим: говорим в ленте.
                    if fname == "sheet_id" and line.layout_state != "none":
                        laid_by_spec[line.spec_id] = laid_by_spec.get(line.spec_id, 0) + 1
            records.write({fname: target.id})
        self._pmk_pending_resolved(target)
        self.sudo().write({"active": False})
        for spec, count in by_spec.items():
            if not spec:
                continue
            body = Markup("<p>%s</p>") % _(
                "Позиция «%(old)s» (на разнос) заменена на «%(new)s» из справочника: "
                "%(count)s %(word)s. Вес и цены пересчитаны.",
                old=old_name, new=target.display_name, count=count,
                word=_plural(count, "деталь", "детали", "деталей"))
            laid = laid_by_spec.get(spec, 0)
            if laid:
                body += Markup("<p>%s</p>") % _(
                    "Раскладка листов сброшена у %(count)s %(word)s — нажмите "
                    "«Разложить листы (черновик)» заново.",
                    count=laid, word=_plural(laid, "детали", "деталей", "деталей"))
            tail = spec._pmk_pending_note_tail()
            if tail:
                body += Markup("<p>%s</p>") % tail
            spec.sudo()._message_log(body=body)
        return sum(by_spec.values())

    def _pmk_pending_resolved(self, target):
        """Позицию разнесли: target — настоящая позиция, которая теперь
        стоит вместо неё («Привязать» — выбранная, «Принять» — она сама).
        Для модулей, которые помнят позицию «на разнос» у себя: заявка на
        металл (pmk_tech) переписывает ключи своих строк."""
        return True

    def _pmk_accept_missing(self):
        """Чего не хватает, чтобы позиция стала обычной (подписи полей)."""
        return []

    def _pmk_accept_vals(self):
        return {}

    def _pmk_after_accept(self):
        """Позицию приняли в справочник. Мост (pmk_bridge) заводит карточку
        товара."""
        return True

    def action_pmk_accept(self):
        """«Принять в справочник»: метка снимается, позиция — обычная."""
        self._pmk_check_admin()
        for rec in self.filtered("pmk_pending"):
            missing = rec._pmk_accept_missing()
            if missing:
                raise UserError(_(
                    "Чтобы принять «%(name)s» в справочник, заполните: %(fields)s.",
                    name=rec.display_name, fields=", ".join(missing)))
            old_name = rec.display_name
            rec.write(dict(rec._pmk_accept_vals(), pmk_pending=False))
            rec._pmk_after_accept()
            rec._pmk_pending_resolved(rec)
            lines = rec._pmk_lines()
            if lines:
                # Вид, масса и карточка товара могли поменяться — детали
                # пересчитываются, как при выборе позиции заново.
                lines.modified([rec._pmk_line_field])
            new_name = rec.display_name
            for spec in lines.spec_id:
                spec.sudo()._message_log(body=Markup("<p>%s</p>") % _(
                    "Позиция «%(old)s» (на разнос) принята в справочник как «%(new)s».",
                    old=old_name, new=new_name))
        return True

    def action_pmk_archive_unused(self):
        """В архив — позицию «на разнос», которая нигде не стоит (завели и
        передумали)."""
        self._pmk_check_admin()
        for rec in self.filtered("pmk_pending"):
            if rec._pmk_lines():
                raise UserError(_(
                    "«%s» стоит в расчётах — привяжите её к существующей позиции "
                    "или примите в справочник.") % rec.display_name)
        self.filtered("pmk_pending").sudo().write({"active": False})
        return True

    # ─── Подсказка детали ───────────────────────────────────────────────
    @api.model
    def _pmk_pending_matches(self, name, domain=None):
        """Позиции «на разнос» под ввод: все слова ввода есть в названии."""
        words = [word for word in _WORDS.split((name or "").strip()) if word]
        if not words:
            return []
        dom = Domain.AND(
            [Domain(domain or Domain.TRUE), Domain("pmk_pending", "=", True)]
            + [Domain("display_name", "ilike", word) for word in words])
        return self.search(dom, limit=20).ids

    @api.model
    def _pmk_merge_pending(self, found, pending, limit):
        """Подсказка + позиции «на разнос» в конце. found — [(id, имя|None)].

        Без позиций «на разнос» — ровно прежняя выдача. Настоящие позиции
        справочника — первыми и почти целиком: «на разнос» занимают не
        больше PENDING_SLOTS мест (выпадашка просит 8 строк), остальное —
        только свободные места. Иначе слово «лист» или «уг», которое есть
        почти в любом названии из чертежа, вытесняло бы из выпадашки
        настоящие позиции, инженер решал бы, что позиции нет, и заводил бы
        ещё одну «на разнос» (доводка З-10)."""
        if not pending and all(row[1] is not None for row in found):
            return found
        pend = set(pending)
        base = [row[0] for row in found if row[0] not in pend]
        extra = list(pending)
        if limit:
            base = base[:max(limit - min(len(extra), PENDING_SLOTS), 0)]
            extra = extra[:max(limit - len(base), 0)]
        ids = base + extra
        return [(rec.id, rec.display_name) for rec in self.browse(ids).sudo()]


class MetalProfilePending(models.Model):
    _name = "pmk.metal.profile"
    _inherit = ["pmk.metal.profile", "pmk.metal.pending.mixin"]

    _pmk_line_field = "profile_id"
    _pmk_kind = "linear"
    _pmk_mass_field = "mass_per_meter"

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if (self.env.context.get("default_pmk_pending") and "type_id" in fields_list
                and not res.get("type_id")):
            other = self.env.ref(OTHER_PROFILE_TYPE, raise_if_not_found=False)
            if other:
                res["type_id"] = other.id
        return res

    @api.model
    def _pmk_pending_fill(self, vals):
        name = (vals.get("pmk_pending_name") or vals.get("size_label") or "").strip()
        if not name:
            raise ValidationError(_("Напишите название позиции, как в чертеже."))
        vals["pmk_pending_name"] = name
        if not vals.get("size_label"):
            vals["size_label"] = name
        type_id = vals.get("type_id") or self.env.context.get("default_type_id")
        ptype = self.env["pmk.metal.profile.type"].browse(type_id).exists() if type_id else False
        if not ptype:
            ptype = self.env.ref(OTHER_PROFILE_TYPE, raise_if_not_found=False)
        if not ptype:
            raise ValidationError(_("Выберите вид проката."))
        vals["type_id"] = ptype.id
        if not vals.get("profile_type"):
            vals["profile_type"] = ptype.sudo().name
        if not vals.get("gost"):
            vals["gost"] = NO_GOST
        vals.setdefault("mass_per_meter", 0.0)
        return vals

    # ─── Вид проката текстом = вид из справочника видов ──────────────────
    # profile_type («Вид проката (текст)», обязательное) держит имя позиции,
    # порядок справочника и фильтры «Уголок» / «Швеллер». До шага З-10 форму
    # строило ядро со всеми полями, и текст правили руками; в форме
    # view_metal_profile_form его нет — он следует за «Вид проката»
    # (type_id): при заведении, при смене вида и в окне до сохранения. Текст,
    # переданный явно (загрузка справочника), не трогаем. На 09.10.2026 у
    # всех 665 позиций боя текст и вид совпадают.
    @api.onchange("type_id")
    def _onchange_pmk_type_text(self):
        for rec in self:
            if rec.type_id:
                rec.profile_type = rec.type_id.name

    @api.model_create_multi
    def create(self, vals_list):
        Type = self.env["pmk.metal.profile.type"].sudo()
        for vals in vals_list:
            type_id = vals.get("type_id") or self.env.context.get("default_type_id")
            if type_id and not vals.get("profile_type"):
                ptype = Type.browse(type_id).exists()
                if ptype:
                    vals["profile_type"] = ptype.name
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("type_id") and "profile_type" not in vals:
            ptype = self.env["pmk.metal.profile.type"].sudo().browse(vals["type_id"]).exists()
            if ptype:
                vals = dict(vals, profile_type=ptype.name)
        return super().write(vals)

    def _pmk_accept_missing(self):
        self.ensure_one()
        other = self.env.ref(OTHER_PROFILE_TYPE, raise_if_not_found=False)
        missing = []
        if not self.type_id or self.type_id == other:
            missing.append(_("вид проката (не «Прочее»)"))
        if not (self.size_label or "").strip():
            missing.append(_("типоразмер"))
        if (self.gost or "").strip() in ("", NO_GOST):
            missing.append(_("стандарт (ГОСТ)"))
        if self.mass_per_meter <= 0:
            missing.append(_("масса, кг/м"))
        return missing

    def _pmk_accept_vals(self):
        self.ensure_one()
        return {"profile_type": self.type_id.name}


class MetalSheetPending(models.Model):
    _name = "pmk.metal.sheet"
    _inherit = ["pmk.metal.sheet", "pmk.metal.pending.mixin"]

    _pmk_line_field = "sheet_id"
    _pmk_kind = "sheet"
    _pmk_mass_field = "mass_per_sqm"

    @api.onchange("thickness_mm")
    def _onchange_pmk_pending_thickness(self):
        """Окно «на разнос»: масса м² — толщина × 7,85 (её можно поправить:
        у рифлёного и просечного листа она другая)."""
        for rec in self:
            if rec.pmk_pending and rec.thickness_mm:
                rec.mass_per_sqm = round(rec.thickness_mm * STEEL_KG_PER_SQM_MM, 4)

    @api.model
    def _pmk_pending_fill(self, vals):
        thickness = vals.get("thickness_mm") or 0.0
        if thickness <= 0:
            raise ValidationError(_("Укажите толщину листа, мм — без неё лист не завести."))
        name = (vals.get("pmk_pending_name") or "").strip() or (
            _("Лист %s мм") % ("%g" % thickness))
        vals["pmk_pending_name"] = name
        if not vals.get("sheet_type"):
            vals["sheet_type"] = OTHER_KIND
        if not vals.get("gost"):
            vals["gost"] = NO_GOST
        if not vals.get("mass_per_sqm"):
            vals["mass_per_sqm"] = round(thickness * STEEL_KG_PER_SQM_MM, 4)
        return vals

    def _pmk_accept_missing(self):
        self.ensure_one()
        missing = []
        if (self.sheet_type or "").strip() in ("", OTHER_KIND):
            missing.append(_("вид листа (не «Прочее»)"))
        if self.thickness_mm <= 0:
            missing.append(_("толщина, мм"))
        if (self.gost or "").strip() in ("", NO_GOST):
            missing.append(_("стандарт (ГОСТ)"))
        if self.mass_per_sqm <= 0:
            missing.append(_("масса, кг/м²"))
        return missing


class MetalFastenerPending(models.Model):
    _name = "pmk.metal.fastener"
    _inherit = ["pmk.metal.fastener", "pmk.metal.pending.mixin"]

    _pmk_line_field = "fastener_id"
    _pmk_kind = "fastener"
    _pmk_mass_field = "weight_kg"

    @api.depends("name", "pmk_pending", "pmk_pending_name")
    def _compute_display_name(self):
        """Имя метиза — наименование. В окне «Новая позиция на разнос»
        наименования ещё нет (его пишет create() из названия), а выбранной в
        детали позиции имя нужно сразу — берём название как в чертеже."""
        for rec in self:
            if rec.pmk_pending and rec.pmk_pending_name:
                rec.display_name = rec.pmk_pending_name
            else:
                rec.display_name = rec.name or ""

    @api.model
    def _pmk_pending_fill(self, vals):
        name = (vals.get("pmk_pending_name") or vals.get("name") or "").strip()
        if not name:
            raise ValidationError(_("Напишите название метиза, как в чертеже."))
        # Имя метиза — его название: пока он «на разнос», оно как в чертеже.
        vals["pmk_pending_name"] = name
        vals["name"] = name
        if not vals.get("fastener_type"):
            vals["fastener_type"] = "other"
        vals.setdefault("weight_kg", 0.0)
        return vals

    def write(self, vals):
        if "pmk_pending_name" in vals and vals["pmk_pending_name"] and "name" not in vals:
            if all(rec.pmk_pending for rec in self):
                vals = dict(vals, name=vals["pmk_pending_name"])
        return super().write(vals)

    def _pmk_accept_missing(self):
        self.ensure_one()
        missing = []
        if not (self.name or "").strip():
            missing.append(_("наименование"))
        if self.weight_kg <= 0:
            missing.append(_("масса, кг/шт"))
        return missing


def pending_note(item):
    """Пометка детали: «на разнос», «нет веса», «на разнос · нет веса»."""
    if not item:
        return False
    parts = []
    if item.pmk_pending:
        parts.append(PENDING_LABEL)
    if not item._pmk_unit_mass():
        parts.append(NO_WEIGHT_LABEL)
    return " · ".join(parts) or False

