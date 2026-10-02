# -*- coding: utf-8 -*-
"""Документ раскроя: заготовки, отрезки, результат.

Расчёт живёт отдельно, в cutting.py, и базы не касается — здесь только
подготовка данных и раскладка результата по полям. Так арифметику можно
проверять тестами, не поднимая окружение.

ПОЧЕМУ РАСЧЁТ ИДЁТ ПО ТИПОРАЗМЕРАМ ОТДЕЛЬНО. Из хлыста уголка 50x50
швеллер не выкроить. Поэтому и у заготовки, и у отрезка есть позиция
сортамента, а расчёт группирует по ней и считает каждую группу сама по
себе. Один документ при этом может закрывать всю спецификацию.

РАСЧЁТ В ШАПКЕ, ХЛЫСТЫ ИЗ ПРАЙСА (разбор UX, шаг 35, 02.10.2026). Связь с
расчётом пряталась во второй вкладке, клиента вводили заново, хлысты
набирали руками по две строки на профиль («6 м» и «12 м»). Теперь:
  • «Расчёт» — первым полем шапки, кнопка «Заполнить из расчёта» — в шапке;
  • клиент подставляется сам из расчёта (поле можно поправить руками);
  • хлыст по длине из прайса поставщика добавляется сам типоразмерам, у
    которых нет ни одной заготовки, — одним правилом у обеих кнопок
    («Заполнить из расчёта» и «Рассчитать»): свой набор заготовок —
    решение человека, его не расширяем. Строку прайса выбирает та же
    дверь, что у расчёта и справочника (product.template._pmk_find_seller,
    pmk_bridge): поставщик расчёта или лучший по рейтингу, базовый уровень
    объёма, прайс на сегодня. Длины нет — позиции нет в прайсах («в городе
    нет»: 418 типоразмеров из 665 на 02.10.2026) или в строке прайса не
    было длины (3) — заготовку вводят руками, и форма говорит об этом
    серой строкой: сигнал, а не запрет;
  • хлыст из прайса — ДОКУПКА, и в дело он идёт последним: очерёдность
    PRICE_BAR_PRIORITY (100) против 10 у своих заготовок и 1 у обрезков.
    При общей очерёдности расчёт выбирал длину по наименьшему лому и брал
    3 хлыста 12 м к закупке, а 5 своих по 6 м оставлял лежать (доводка).
Мост (pmk_bridge) — МЯГКАЯ связь, в зависимостях модуля его нет: мост
зависит от mrp, stock_account и модулей RuOdoo, и удаление любого из них
каскадом снесло бы pmk_cut со всеми раскроями. Без моста длины нет —
ручной ввод, как до шага 35 (_pmk_price_bars_ready).
Существующие раскрои не пересчитываются: клиент у РК-00001 остаётся, как
был (Odoo досчитывает вычисляемые поля только у НОВЫХ колонок).
"""

import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .cutting import WASTE_WARN_PCT, bar_name, cut_plan
from .cutting import waste_label as waste_label_of

_logger = logging.getLogger(__name__)

MM_IN_M = 1000.0

# Очерёдность хлыста из прайса (доводка шага 35, 02.10.2026). Хлыст из
# прайса — докупка, а не то, что лежит на складе, и в дело он идёт ПОСЛЕДНИМ:
# свои заготовки по умолчанию 10, обрезкам советуем 1. Внутри одной
# очерёдности расчёт сам выбирает длину по наименьшему лому
# (cutting._orderings), и при общих 10 хлыст из прайса «выигрывал» у
# складских: склад 6 м × 5 и прайс 12 м, отрезки 5000 × 6 → 3 хлыста 12 м к
# закупке, а свои 6 м не тронуты. Человек может поставить хлысту из прайса
# очерёдность меньше — это его решение.
PRICE_BAR_PRIORITY = 100


class PmkCutPlan(models.Model):
    _name = "pmk.cut.plan"
    _description = "Раскрой сортамента"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="Черновик")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    # Шаг 35: клиент подставляется сам из расчёта. Вычисляемое и хранимое с
    # правкой (readonly=False), а не onchange: подставится и при создании
    # из кода; выбор человека важнее — сменили расчёт без клиента, прежний
    # клиент остаётся. Существующая колонка при -u не пересчитывается
    # (Odoo досчитывает только новые колонки) — РК-00001 не тронут.
    # copy=True — как было до шага: вычисляемое поле Odoo по умолчанию не
    # копирует, и копия раскроя с клиентом, поправленным руками, получила
    # бы клиента расчёта.
    partner_id = fields.Many2one(
        "res.partner", "Клиент", tracking=True, copy=True,
        compute="_compute_partner_id", store=True, readonly=False,
        help="Подставляется из расчёта; можно поправить руками.")
    note = fields.Char("Примечание")

    spec_id = fields.Many2one(
        "pmk.metal.spec", "Расчёт", index=True,
        help="Из какого расчёта раскрой. «Заполнить из расчёта» перенесёт "
             "линейные детали (количество — на все изделия), клиента и хлысты "
             "по длине из прайса — типоразмерам, у которых заготовок ещё нет.")

    # Пропил — свойство станка, а не металла: ленточная пила съедает больше,
    # дисковая меньше. Поэтому поле документа, а не справочника.
    kerf_mm = fields.Float("Ширина пропила, мм", default=3.0, digits=(6, 1), required=True)
    min_useful_mm = fields.Float(
        "Годный остаток от, мм", default=500.0, digits=(8, 1), required=True,
        help="Остаток не короче этого возвращается на склад как заготовка. "
             "Всё короче считается ломом.")

    stock_ids = fields.One2many("pmk.cut.stock", "plan_id", "Заготовки", copy=True)
    part_ids = fields.One2many("pmk.cut.part", "plan_id", "Отрезки", copy=True)
    result_ids = fields.One2many("pmk.cut.result", "plan_id", "Результат", readonly=True, copy=False)

    total_bars = fields.Integer("Заготовок", compute="_compute_totals", store=True)
    total_weight = fields.Float("Взято металла, кг", compute="_compute_totals", store=True, digits=(12, 2))
    scrap_weight = fields.Float("В лом, кг", compute="_compute_totals", store=True, digits=(12, 2))
    # «Оживить таблицы» (29.09.2026): в строке группы пусто — сумма процентов
    # бессмысленна, а простое среднее не взвешено по металлу.
    waste_ratio = fields.Float("Отход, %", compute="_compute_totals", store=True, digits=(5, 2), aggregator=None)
    has_unplaced = fields.Boolean("Есть неразмещённые", compute="_compute_totals", store=True)

    # Шаг 35: отход больше 10 % — карточка «Отход, %» в шапке жёлтая и с
    # пометкой «много». Не хранится: следует за хранимым waste_ratio.
    waste_high = fields.Boolean(
        "Отход больше 10 %", compute="_compute_waste_high",
        help="Сигнал, а не запрет: раскрой стоит пересмотреть — нет ли "
             "заготовки выгоднее.")
    # Доводка шага 35: отход словом и в СПИСКЕ раскроев — правило 7: сигнал
    # виден там, где принимают решение (список, шапка), а не только внутри
    # документа. Больше 10 % — жёлтой плашкой и «· много» (cutting.waste_label,
    # тот же текст, что во вкладке «Результат»). Не хранится: следует за
    # хранимыми waste_ratio и total_weight. Металла не взято (не посчитан,
    # заготовок нет) — пусто: «0 %» читался бы как идеальный раскрой.
    waste_label = fields.Char("Отход", compute="_compute_waste_label")
    # Шаг 35: типоразмеры отрезков без единой заготовки, у которых в прайсе
    # нет длины хлыста, — им заготовку вводят руками. Остальным хлыст из
    # прайса добавится сам при расчёте. Правило «без единой заготовки» —
    # то же, что у обеих кнопок (_pmk_bare_profiles).
    stock_missing_text = fields.Char(
        "Нет длины хлыста в прайсе", compute="_compute_stock_missing_text",
        help="Типоразмеры отрезков без заготовок, для которых в прайсе нет "
             "длины хлыста: заготовку для них введите вручную.")

    @api.depends("spec_id")
    def _compute_partner_id(self):
        for plan in self:
            plan.partner_id = plan.spec_id.partner_id or plan.partner_id

    @api.depends("waste_ratio")
    def _compute_waste_high(self):
        for plan in self:
            plan.waste_high = (plan.waste_ratio or 0.0) > WASTE_WARN_PCT

    @api.depends("waste_ratio", "total_weight")
    def _compute_waste_label(self):
        for plan in self:
            plan.waste_label = (
                waste_label_of(plan.waste_ratio)[0] if plan.total_weight else False)

    # Зависимость от поставщика расчёта — только если стоит мост: поле
    # supplier_id объявлено в pmk_bridge, а связь с ним мягкая. Строкой в
    # @api.depends без моста реестр не собрался бы («Dependency field not
    # found»), поэтому функцией: Odoo зовёт её при сборке реестра.
    @api.depends(lambda self: ("part_ids.profile_id", "stock_ids.profile_id") + (
        ("spec_id.supplier_id",)
        if "supplier_id" in self.env["pmk.metal.spec"]._fields else ()))
    def _compute_stock_missing_text(self):
        for plan in self:
            bare = plan._pmk_bare_profiles()
            lengths = plan._pmk_price_bar_lengths(bare)
            missing = bare.filtered(lambda p: not lengths.get(p.id))
            plan.stock_missing_text = ", ".join(missing.mapped("display_name")) or False

    @api.depends("result_ids.bars_used", "result_ids.weight_total",
                 "result_ids.scrap_weight", "result_ids.unplaced_text")
    def _compute_totals(self):
        for plan in self:
            results = plan.result_ids
            plan.total_bars = sum(results.mapped("bars_used"))
            plan.total_weight = sum(results.mapped("weight_total"))
            plan.scrap_weight = sum(results.mapped("scrap_weight"))
            # Отход считаем по металлу, а не по числу заготовок: две заготовки
            # разной длины — это разный металл.
            plan.waste_ratio = (
                100.0 * plan.scrap_weight / plan.total_weight if plan.total_weight else 0.0)
            plan.has_unplaced = any(results.mapped("unplaced_text"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Черновик") == "Черновик":
                vals["name"] = self.env["ir.sequence"].next_by_code("pmk.cut.plan") or "Черновик"
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Хлысты из прайса (разбор UX, шаг 35)
    # ------------------------------------------------------------------

    def _pmk_price_bars_ready(self):
        """Стоит ли мост номенклатуры (pmk_bridge) — источник длины хлыста.

        Связь МЯГКАЯ (доводка шага 35): в зависимостях pmk_cut моста нет.
        Мост держит mrp, stock_account и модули RuOdoo, и при жёсткой
        зависимости удаление любого из них в «Приложениях» каскадом снесло бы
        pmk_bridge, а за ним pmk_cut — с таблицами всех раскроев РК-….
        Раскрою от моста нужны: связь типоразмера с карточкой
        (pmk.metal.profile.product_tmpl_id), выбор строки прайса
        (product.template._pmk_find_seller), длина в ней
        (product.supplierinfo.pmk_bar_length_mm) и поставщик расчёта
        (pmk.metal.spec.supplier_id). Нет моста — нет длины: заготовку
        вводят руками, как до шага 35.
        """
        env = self.env
        return (
            "product.supplierinfo" in env
            and "pmk_bar_length_mm" in env["product.supplierinfo"]._fields
            and "product_tmpl_id" in env["pmk.metal.profile"]._fields
            and hasattr(env["product.template"], "_pmk_find_seller"))

    def _pmk_bare_profiles(self):
        """Типоразмеры отрезков, у которых нет ни одной заготовки.

        ОДНО ПРАВИЛО для обеих кнопок и серой строки «Нет длины хлыста в
        прайсе»: хлыст из прайса получают только они. Типоразмер, у которого
        заготовки уже есть, не трогаем — их набор решение человека («только
        эти 5 хлыстов», «режем только 6 м»). Раньше «Заполнить из расчёта»
        добавляло хлыст всем типоразмерам без заготовки той же длины и
        возвращало хлыст, который человек удалил (доводка шага 35).
        """
        self.ensure_one()
        return self.part_ids.profile_id - self.stock_ids.profile_id

    def _pmk_price_bar_lengths(self, profiles):
        """{id типоразмера: длина хлыста, мм} по строке прайса; 0 — длины нет.

        Строку выбирает product.template._pmk_find_seller (pmk_bridge) — та
        же дверь, через которую расчёт берёт цену: поставщик расчёта, а если
        он не задан — лучший по рейтингу; базовый уровень объёма. Прайс — на
        СЕГОДНЯ, а не на дату документа: хлысты покупают сейчас, а у прайсов
        до 21.09.2026 длины не записаны вовсе. Моста нет — у всех 0.
        """
        self.ensure_one()
        lengths = dict.fromkeys(profiles.ids, 0.0)
        if not profiles or not self._pmk_price_bars_ready():
            return lengths
        today = fields.Date.context_today(self)
        spec = self.spec_id
        supplier = spec.supplier_id if "supplier_id" in spec._fields else None
        for profile in profiles:
            tmpl = profile.product_tmpl_id
            seller = tmpl._pmk_find_seller(today, supplier=supplier) if tmpl else False
            lengths[profile.id] = (seller.pmk_bar_length_mm if seller else 0.0) or 0.0
        return lengths

    def _pmk_add_price_bars(self):
        """Добавить «хлыст из прайса» типоразмерам без единой заготовки.

        Кто их получает — _pmk_bare_profiles (одно правило у обеих кнопок).
        Количество 0 — «сколько нужно» (докупим), очерёдность
        PRICE_BAR_PRIORITY — в дело последним, после своих заготовок и
        обрезков. Длины в прайсе нет — строку не добавляем (её вводят руками,
        stock_missing_text). Возвращает число добавленных строк.
        """
        self.ensure_one()
        bare = self._pmk_bare_profiles()
        lengths = self._pmk_price_bar_lengths(bare)
        values = [{
            "plan_id": self.id,
            "profile_id": profile.id,
            "length_mm": lengths[profile.id],
            "qty": 0,
            "priority": PRICE_BAR_PRIORITY,
            # Пометка видна в колонке «Название» (её вернул шаг 35): без неё
            # докупку не отличить от своего хлыста той же длины.
            "name": "%s (из прайса)" % bar_name(lengths[profile.id]),
        } for profile in bare if lengths.get(profile.id, 0.0) > 0]
        if values:
            self.env["pmk.cut.stock"].create(values)
            # Набор заготовок документа перечитываем: расчёт ниже смотрит на
            # него сразу после добавления.
            self.invalidate_recordset(["stock_ids"])
        return len(values)

    # ------------------------------------------------------------------
    # Заполнение из расчёта
    # ------------------------------------------------------------------

    def action_fill_from_spec(self):
        """Перенести линейные детали расчёта в отрезки.

        Количество перемножаем: в расчёте количество указано НА ОДНО
        изделие, а изделий в документе может быть сто. Не перемножить —
        значит посчитать раскрой на одну ферму вместо партии.

        Шаг 35: заодно клиент (если пуст) и хлысты по длине из прайса —
        типоразмерам без заготовок; прежний результат сбрасывается — он
        посчитан по прежним отрезкам.
        """
        self.ensure_one()
        if not self.spec_id:
            raise UserError(_("Не выбран расчёт."))

        rows = {}
        for product in self.spec_id.product_ids:
            for line in product.line_linear_ids:
                if not line.profile_id or line.length_mm <= 0:
                    continue
                key = (line.profile_id.id, round(line.length_mm, 1))
                qty = (line.qty or 0) * (product.qty or 0)
                if qty <= 0:
                    continue
                rows.setdefault(key, {"qty": 0, "names": set()})
                rows[key]["qty"] += qty
                if line.detail_name:
                    rows[key]["names"].add(line.detail_name)

        if not rows:
            raise UserError(_("В расчёте нет линейного проката с длиной."))

        if not self.partner_id and self.spec_id.partner_id:
            self.partner_id = self.spec_id.partner_id
        # Результат считали по прежним отрезкам — к новым он не относится.
        self.result_ids.unlink()
        self.part_ids.unlink()
        self.env["pmk.cut.part"].create([
            {
                "plan_id": self.id,
                "profile_id": profile_id,
                "length_mm": length,
                "qty": data["qty"],
                # Имена деталей склеиваем: в раскрое важно, что это за отрезок,
                # но перечислять по одному — только раздувать таблицу.
                "name": ", ".join(sorted(data["names"]))[:120],
            }
            for (profile_id, length), data in sorted(rows.items(), key=lambda kv: -kv[0][1])
        ])
        self.invalidate_recordset(["part_ids"])
        # Заготовки, заведённые руками, не трогаем: какие обрезки лежат на
        # складе, знает человек, а не расчёт. Хлыст из прайса — добавляем
        # (шаг 35): что продаёт поставщик, знает прайс. Только типоразмерам
        # без заготовок — то же правило, что у «Рассчитать»: удалённый
        # человеком хлыст из прайса повторное заполнение не вернёт, и «только
        # эти 5 хлыстов» не превратятся в «5 хлыстов и сколько угодно 12 м».
        self._pmk_add_price_bars()
        return True

    # ------------------------------------------------------------------
    # Расчёт
    # ------------------------------------------------------------------

    def action_compute(self):
        for plan in self:
            plan._compute_plan()
        return True

    def _compute_plan(self):
        self.ensure_one()
        if not self.part_ids:
            raise UserError(_("Нечего резать: не задано ни одного отрезка."))

        # Шаг 35: отрезки ввели руками — типоразмеру без единой заготовки
        # хлыст по длине из прайса добавляется сам, как при «Заполнить из
        # расчёта» (одно правило — _pmk_bare_profiles). Типоразмер, у которого
        # заготовки уже есть, не трогаем: их набор — решение человека
        # (например, «только эти 5 хлыстов»).
        self._pmk_add_price_bars()

        self.result_ids.unlink()

        profiles = self.part_ids.mapped("profile_id")
        created = []
        for profile in profiles:
            parts = self.part_ids.filtered(lambda p, pr=profile: p.profile_id == pr)
            stocks = self.stock_ids.filtered(lambda s, pr=profile: s.profile_id == pr)

            # Доводка шага 35: типоразмер без заготовок (длины хлыста в прайсе
            # нет — «в городе нет», или моста нет) расчёт НЕ останавливает.
            # Сигнал, а не запрет: его отрезки встают в «Не размещено» с
            # пометкой «нет заготовок» — это видно плашкой над вкладками, в
            # таблице «Результат», на листе раскроя («НЕ РАЗМЕЩЕНО») и серой
            # строкой во вкладке «Заготовки». Остальные типоразмеры
            # считаются. Раньше одна такая позиция роняла ошибкой весь расчёт.
            # Пустой набор заготовок cut_plan разбирает сам: всё — в
            # неразмещённые, заготовок 0.
            res = cut_plan(
                [{
                    "length": s.length_mm,
                    # 0 — «сколько нужно»: заготовка не ограничена, докупим
                    # столько, сколько понадобится (None для cut_plan). Пустым
                    # поле не бывает — целое поле хранит стёртое число нулём.
                    # Число больше нуля — столько штук есть, не больше.
                    "qty": s.qty or None,
                    "name": s.name or s.display_name,
                    "priority": s.priority,
                } for s in stocks],
                [{"length": p.length_mm, "qty": p.qty, "name": p.name} for p in parts],
                kerf=self.kerf_mm,
                min_useful=self.min_useful_mm,
            )
            created.append(self._result_values(profile, res, no_stock=not stocks))

        self.env["pmk.cut.result"].create(created)
        _logger.info("pmk_cut: %s — посчитано групп: %s", self.name, len(created))
        return True

    def _result_values(self, profile, res, no_stock=False):
        mass = profile.mass_per_meter or 0.0
        to_kg = lambda mm: mm / MM_IN_M * mass  # noqa: E731

        return {
            "plan_id": self.id,
            "profile_id": profile.id,
            "bars_used": res["bars_used"],
            "stock_mm": res["total_stock"],
            "parts_mm": res["total_parts"],
            "kerf_mm": res["total_kerf"],
            "scrap_mm": res["scrap"],
            "weight_total": to_kg(res["total_stock"]),
            "weight_parts": to_kg(res["total_parts"]),
            "leftover_weight": to_kg(sum(res["useful_leftovers"])),
            "scrap_weight": to_kg(res["scrap"]),
            # Отход — ТОЛЬКО безвозвратные потери. Годный остаток уходит на
            # склад и металлом быть не перестаёт; считать его отходом значит
            # пугать цифрой 22% там, где реально потеряно полкилограмма.
            "waste_ratio": round(
                100.0 * res["scrap"] / res["total_stock"], 2) if res["total_stock"] else 0.0,
            "lower_bound": res["lower_bound"],
            "layout_html": self._layout_html(res),
            "leftovers_text": self._leftovers_text(res),
            "unplaced_text": self._unplaced_text(res, no_stock=no_stock),
            "result_json": json.dumps(res, ensure_ascii=False),
        }

    # ------------------------------------------------------------------
    # Представление результата
    # ------------------------------------------------------------------

    def _layout_html(self, res):
        """Схемы раскроя полосками — цеху понятнее числа в столбик.

        Показываем схему и сколько раз её повторить: сто одинаковых строк
        читать невозможно, а «вот так режь, двенадцать раз» — можно.
        """
        from markupsafe import Markup, escape

        if not res["patterns"]:
            return False

        blocks = []
        for pattern in res["patterns"]:
            total = pattern["stock_length"] or 1
            cells = []
            for piece in pattern["pieces"]:
                width = 100.0 * piece / total
                cells.append(
                    '<div class="pmk-cut__piece" style="width:%.3f%%" title="%s мм">%s</div>'
                    % (width, escape(self._fmt(piece)), escape(self._fmt(piece)))
                )
            if pattern["leftover"] > 0:
                width = 100.0 * pattern["leftover"] / total
                kind = "useful" if pattern["leftover"] >= self.min_useful_mm else "scrap"
                cells.append(
                    '<div class="pmk-cut__rest pmk-cut__rest--%s" style="width:%.3f%%" title="%s мм">%s</div>'
                    % (kind, width, escape(self._fmt(pattern["leftover"])),
                       escape(self._fmt(pattern["leftover"])))
                )
            blocks.append(
                '<div class="pmk-cut__pattern">'
                # «повторить 2 раз» не согласуется, а склонять числительное
                # в разметке нечем — ставим знак умножения, он не склоняется.
                '<div class="pmk-cut__head"><b>%s мм</b> &#215; %s</div>'
                '<div class="pmk-cut__bar">%s</div></div>'
                % (escape(self._fmt(pattern["stock_length"])), pattern["count"], "".join(cells))
            )
        return Markup('<div class="pmk-cut">%s</div>' % "".join(blocks))

    def _leftovers_text(self, res):
        if not res["useful_leftovers"]:
            return False
        return ", ".join("%s мм" % self._fmt(x) for x in res["useful_leftovers"])

    def _unplaced_text(self, res, no_stock=False):
        if not res["unplaced"]:
            return False
        text = "; ".join(
            "%s мм — %s шт" % (self._fmt(u["length"]), u["qty"]) for u in res["unplaced"])
        # Доводка шага 35: у типоразмера нет ни одной заготовки — так и
        # пишем. Голое «1450 мм — 6 шт» читалось бы как «деталь длиннее
        # хлыста» или «хлыстов не хватило».
        return "нет заготовок: %s" % text if no_stock else text

    @staticmethod
    def _fmt(value):
        value = float(value or 0)
        return str(int(value)) if value == int(value) else ("%.1f" % value)


class PmkCutStock(models.Model):
    """Заготовка: целый хлыст или обрезок со склада — разницы для расчёта нет."""

    _name = "pmk.cut.stock"
    _description = "Заготовка раскроя"
    _order = "priority, sequence, id"

    plan_id = fields.Many2one("pmk.cut.plan", "Раскрой", required=True, ondelete="cascade")
    sequence = fields.Integer("№", default=10)
    profile_id = fields.Many2one("pmk.metal.profile", "Типоразмер", required=True)
    length_mm = fields.Float("Длина, мм", required=True, digits=(10, 1))
    # Шаг 35: подпись говорила «Пусто или 0 — не ограничено», а в колонке
    # стоял «0»: целое поле пустым не бывает. Честно: 0 значит «сколько
    # нужно» — расчёт возьмёт столько, сколько понадобится (cutting.py, qty
    # None), число — не больше стольких штук.
    qty = fields.Integer(
        "В наличии, шт", default=0,
        help="Сколько таких заготовок есть. 0 — сколько нужно: расчёт возьмёт "
             "столько, сколько понадобится (докупим). Пустым поле не бывает — "
             "стёртое число сохраняется нулём.")
    name = fields.Char(
        "Название",
        help="Например «Хлыст 6 м» или «Обрезок от РК-00007». Хлыст, который "
             "добавила система по длине из прайса, помечен «(из прайса)» — "
             "это докупка, а не то, что лежит на складе.")
    # Доводка шага 35: хлыст из прайса получает очерёдность 100 — в дело
    # последним (cut_plan.PRICE_BAR_PRIORITY); подсказка говорит об этом.
    priority = fields.Integer(
        "Очерёдность", default=10,
        help="Меньше — раньше идёт в дело. Обрезкам со склада ставьте 1, "
             "чтобы расходовались первыми. Хлыст из прайса (докупка) стоит с "
             "очерёдностью 100 — идёт в дело последним, после своих.")


class PmkCutPart(models.Model):
    """Отрезок: что нужно получить."""

    _name = "pmk.cut.part"
    _description = "Отрезок раскроя"
    _order = "sequence, id"

    plan_id = fields.Many2one("pmk.cut.plan", "Раскрой", required=True, ondelete="cascade")
    sequence = fields.Integer("№", default=10)
    profile_id = fields.Many2one("pmk.metal.profile", "Типоразмер", required=True)
    length_mm = fields.Float("Длина, мм", required=True, digits=(10, 1))
    qty = fields.Integer("Количество", required=True, default=1)
    name = fields.Char("Деталь")


class PmkCutResult(models.Model):
    """Результат по одному типоразмеру."""

    _name = "pmk.cut.result"
    _description = "Результат раскроя"
    _order = "id"

    plan_id = fields.Many2one("pmk.cut.plan", "Раскрой", required=True, ondelete="cascade")
    profile_id = fields.Many2one("pmk.metal.profile", "Типоразмер", required=True)

    bars_used = fields.Integer("Заготовок")
    stock_mm = fields.Float("Взято, мм", digits=(12, 1))
    parts_mm = fields.Float("В деталях, мм", digits=(12, 1))
    kerf_mm = fields.Float("В пропил, мм", digits=(12, 1))
    scrap_mm = fields.Float("В лом, мм", digits=(12, 1))

    weight_total = fields.Float("Взято, кг", digits=(12, 2))
    weight_parts = fields.Float("В деталях, кг", digits=(12, 2))
    leftover_weight = fields.Float("В годные остатки, кг", digits=(12, 2))
    scrap_weight = fields.Float("В лом, кг", digits=(12, 2))
    waste_ratio = fields.Float("Отход, %", digits=(5, 2))
    # Шаг 35: отход словом для таблицы «Результат» — больше 10 % жёлтой
    # плашкой и словом «много», ноль серым (cutting.waste_label). Не хранится:
    # следует за waste_ratio.
    waste_label = fields.Char("Отход", compute="_compute_waste_label")
    waste_level = fields.Selection(
        [("zero", "Ничего"), ("ok", "Норма"), ("high", "Много")],
        "Уровень отхода", compute="_compute_waste_label")
    # Грубая нижняя граница: показывает, есть ли куда ужиматься вообще.
    lower_bound = fields.Integer("Теоретический минимум")

    layout_html = fields.Html("Схемы раскроя", sanitize=False)
    leftovers_text = fields.Char("Годные остатки")
    unplaced_text = fields.Char("Не размещено")
    result_json = fields.Text("Расчёт (json)")

    @api.depends("waste_ratio")
    def _compute_waste_label(self):
        for result in self:
            result.waste_label, result.waste_level = waste_label_of(result.waste_ratio)
