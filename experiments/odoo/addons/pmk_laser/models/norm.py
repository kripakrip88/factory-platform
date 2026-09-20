# -*- coding: utf-8 -*-
"""Норматив резки: станок x вид листа x толщина.

Норматив здесь НЕ ВВОДЯТ, а выводят из замеров обратным счётом. Паспортные
режимы станка для этого не годятся: в файлах технолога они демонстрационные, а
на участке всё равно режут медленнее паспорта — с холостыми перемещениями,
подстройками и реальной оптикой.

ЖЕЛЕЗНОЕ ПРАВИЛО. Толщина, на которой нет ни одного замера, показывает
«норматива нет» — и не подставляет среднее по соседним толщинам. Двойка и
десятка режутся с разницей в разы, и усреднение между ними дало бы число,
которое выглядит как норматив, считается как норматив и врёт как норматив. По
такому плану поставят срок заказчику. Пустое честнее выдуманного — то же
правило, что в площади окраски и в разборе прайсов.

ПОЧЕМУ ВЫБОРКА СТРОИТСЯ ПО ЗАДАНИЯМ, А НЕ ПО ЛИСТАМ. Замер живёт на листе,
а знаменатель (метры реза, проколы) известен по заданию целиком: какая деталь
на каком листе, файл раскроя открытым текстом не говорит. Разложить метры по
листам «пропорционально заполнению» было бы догадкой, а догадка в знаменателе
портит норматив тише всего. Поэтому в статистику идёт задание, у которого
замерены ВСЕ листы: тогда сумма замеров и общий знаменатель — про один и тот
же металл.
"""

from collections import defaultdict

from odoo import _, api, fields, models

from . import timing

THICKNESS_TOLERANCE_MM = 0.001


class LaserNorm(models.Model):
    _name = "pmk.laser.norm"
    _description = "Норматив лазерной резки"
    _order = "machine_id, sheet_type, thickness_mm"
    _rec_name = "display_name"

    machine_id = fields.Many2one("pmk.laser.machine", "Станок", required=True, index=True, ondelete="cascade")
    sheet_type = fields.Char("Вид листа", required=True)
    thickness_mm = fields.Float("Толщина, мм", required=True, digits=(6, 2))

    mode = fields.Selection(
        [(timing.MODE_NONE, "Норматива нет"),
         (timing.MODE_AGGREGATE, "Рез и проколы не разделены"),
         (timing.MODE_FULL, "Норматив выведен")],
        "Состояние", default=timing.MODE_NONE, required=True, readonly=True)
    reason = fields.Char(
        "Почему так", readonly=True,
        help="Если норматив неполный — здесь написано, какого замера не хватает.")

    sample_count = fields.Integer("Заданий в выборке", readonly=True)
    skipped_count = fields.Integer(
        "Отброшено", readonly=True,
        help="Замеры без знаменателя или с нулевым временем. Они не считаются "
             "нулями, их просто нет в выборке.")
    last_sample = fields.Date("Последний замер", readonly=True)

    min_per_m = fields.Float(
        "Минут на метр реза", readonly=True, digits=(8, 4),
        help="Переносимая величина: столько минут уходит на метр реза вместе с "
             "проколами и холостым ходом. Есть всегда, когда есть хоть один "
             "полный замер.")
    speed_mm_min = fields.Float(
        "Скорость, мм/мин", readonly=True, digits=(10, 1),
        help="Эффективная скорость участка, а не паспортная скорость луча: "
             "холостые перемещения сидят внутри. Для планирования стола нужна "
             "именно она.")
    pierce_time_s = fields.Float("Прокол, с", readonly=True, digits=(8, 2))
    spread_pct = fields.Float(
        "Разброс, %", readonly=True, digits=(6, 1),
        help="Наибольшее расхождение факта с моделью. Пока держится в пределах "
             "десятка процентов — нормативу можно планировать смену.")

    display_name = fields.Char(compute="_compute_display_name")

    _norm_unique = models.UniqueIndex(
        "(machine_id, sheet_type, thickness_mm)",
        "Норматив на этот станок, вид листа и толщину уже есть.",
    )

    @api.depends("machine_id.name", "sheet_type", "thickness_mm")
    def _compute_display_name(self):
        for norm in self:
            norm.display_name = "%s · %s %g мм" % (
                norm.machine_id.name or "", (norm.sheet_type or "").lower(), norm.thickness_mm)

    # ==================================================================
    # Поиск норматива
    # ==================================================================

    @api.model
    def _lookup(self, machine, sheet_type, thickness_mm):
        """Найти норматив. Пустой набор означает «норматива нет».

        Толщина ищется ТОЧНАЯ. Ближайшая, округлённая и средняя по соседним не
        ищутся ни при каких условиях — это и есть железное правило участка.
        Допуск в одну тысячную миллиметра нужен только потому, что толщина
        хранится числом с плавающей точкой.
        """
        if not machine or not sheet_type or not thickness_mm:
            return self.browse()
        return self.search([
            ("machine_id", "=", machine.id),
            ("sheet_type", "=", sheet_type),
            ("thickness_mm", ">=", thickness_mm - THICKNESS_TOLERANCE_MM),
            ("thickness_mm", "<=", thickness_mm + THICKNESS_TOLERANCE_MM),
            ("mode", "!=", timing.MODE_NONE),
        ], limit=1)

    # ==================================================================
    # Обратный счёт из замеров
    # ==================================================================

    @api.model
    def _collect_samples(self):
        """Собрать выборку: ключ (станок, вид, толщина) -> список замеров.

        Берутся только задания с замеренными листами и разобранным чертежом.
        Задание с половиной замеров не берётся вовсе: сумма замеров относилась
        бы к половине листов, а знаменатель — ко всему заданию.
        """
        jobs = self.env["pmk.laser.job"].search([
            ("measure_state", "=", "done"),
            ("cut_length_m", ">", 0.0),
            ("machine_id", "!=", False),
            ("sheet_id", "!=", False),
        ])
        samples = defaultdict(list)
        last_date = {}
        for job in jobs:
            usable = job.measure_ids.filtered(lambda m: m.state == "done" and not m.excluded)
            minutes = sum(usable.mapped("cut_minutes"))
            key = (job.machine_id.id, job.sheet_type, round(job.thickness_mm, 3))
            samples[key].append((job.cut_length_m, job.pierce_count, minutes))
            if job.date and (key not in last_date or job.date > last_date[key]):
                last_date[key] = job.date
        return samples, last_date

    @api.model
    def _sync_from_measures(self):
        """Пересчитать все нормативы по накопленным замерам.

        Нормативы, под которые замеров больше нет (задание удалили, замеры
        исключили), не удаляются, а честно переводятся в «норматива нет»:
        исчезнувшая строка выглядела бы как «такого станка не бывает», а
        пустая — как «мерить ещё не начинали».
        """
        samples, last_date = self._collect_samples()
        touched = self.browse()

        for key, rows in samples.items():
            machine_id, sheet_type, thickness = key
            fit = timing.fit_norm(rows)
            norm = self.search([
                ("machine_id", "=", machine_id),
                ("sheet_type", "=", sheet_type),
                ("thickness_mm", ">=", thickness - THICKNESS_TOLERANCE_MM),
                ("thickness_mm", "<=", thickness + THICKNESS_TOLERANCE_MM),
            ], limit=1)
            values = {
                "mode": fit["mode"],
                "reason": fit["reason"],
                "sample_count": fit["sample_count"],
                "skipped_count": fit["skipped"],
                "min_per_m": fit["min_per_m"],
                "speed_mm_min": fit["speed_mm_min"],
                "pierce_time_s": fit["pierce_time_s"],
                "spread_pct": fit["spread_pct"],
                "last_sample": last_date.get(key),
            }
            if norm:
                norm.write(values)
            else:
                values.update({
                    "machine_id": machine_id,
                    "sheet_type": sheet_type,
                    "thickness_mm": thickness,
                })
                norm = self.create(values)
            touched |= norm

        stale = self.search([("id", "not in", touched.ids), ("sample_count", ">", 0)])
        stale.write({
            "mode": timing.MODE_NONE, "sample_count": 0, "skipped_count": 0,
            "min_per_m": 0.0, "speed_mm_min": 0.0, "pierce_time_s": 0.0, "spread_pct": 0.0,
            "reason": _("замеров по этой толщине больше нет"),
        })

        self._replan_jobs(touched | stale)
        return touched

    @api.model
    def _replan_jobs(self, norms):
        """Пересчитать план у заданий, которых коснулась смена норматива.

        План хранится в базе — иначе экран загрузки участка не смог бы его
        суммировать по дням и станкам. Хранимое поле само не пересчитается от
        чужой таблицы, поэтому пересчёт ставится явно.
        """
        if not norms:
            return
        jobs = self.env["pmk.laser.job"].search([
            ("machine_id", "in", norms.mapped("machine_id").ids),
            ("sheet_type", "in", norms.mapped("sheet_type")),
        ])
        if not jobs:
            return
        for name in ("planned_minutes", "plan_state"):
            self.env.add_to_compute(jobs._fields[name], jobs)

    def action_sync(self):
        """Кнопка «Пересчитать по замерам»."""
        self._sync_from_measures()
        return True
