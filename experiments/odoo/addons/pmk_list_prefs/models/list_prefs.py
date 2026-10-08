# -*- coding: utf-8 -*-
"""Колонки у каждого (разбор UX, шаг 55, 08.10.2026): настройка списков.

Одна запись — настройка одного списка:
  • user_id  — чья; ПУСТО — «у всех по умолчанию» (её пишет только
               администратор, base.group_system);
  • view_key — какой список: «list|<модель>|<id вида>|<id действия>» для
               основного окна, «x2m|<модель документа>|<поле>|<id вида
               формы>» для таблицы внутри формы (static/src/js/
               list_prefs_rules.js, viewKey). Действие в ключе разводит
               «Клиентов» и «Поставщиков» — у них один вид;
  • prefs    — {"v": 1, "order": [...], "widths": {ключ: px},
               "visible": {ключ: bool}} (там же, шапка файла).

Кто что видит (security/list_prefs_rules.xml): свои записи человек читает и
пишет сам, общие только читает; администратор — все. Настройки уходят в
браузер вместе со страницей (ir_http.py, session_info) — список сразу
рисуется как надо.

Своя настройка сохраняется вместе с правкой (pmk_save, change): запись в
базе уже есть — правка сливается с ней, поэтому старый кэш другой вкладки
браузера не затирает чужие ширины и порядок.

Каждый метод чистит настройку (_pmk_clean): только три известных ключа,
ограничения длины, ширина 40…2000 px. Мусор от старой версии страницы или
ручной записи не ломает список — колонки, которых нет в виде, браузер
просто пропускает.
"""
import json
import re

from psycopg2 import errors as pg_errors

from odoo import api, fields, models
from odoo.exceptions import AccessError, ConcurrencyError, ValidationError

VIEW_KEY_RE = re.compile(r"^(list|x2m)\|[\w.|-]{1,250}$")
MODEL_RE = re.compile(r"^[a-z0-9_.]{1,128}$")
MAX_JSON = 20000
MAX_ITEMS = 300
MAX_KEY = 128
MIN_WIDTH = 40
MAX_WIDTH = 2000

ADMIN_ONLY = "Сделать так у всех может только администратор."


def _clean_key(key):
    return (
        isinstance(key, str)
        and 0 < len(key) <= MAX_KEY
        and not any(ord(ch) < 32 for ch in key)
    )


class PmkListPrefs(models.Model):
    _name = "pmk.list.prefs"
    _description = "Настройка колонок списка"
    _rec_name = "view_key"
    _order = "view_key, user_id"

    user_id = fields.Many2one(
        "res.users", string="Пользователь", ondelete="cascade", index=True,
        help="Пусто — настройка «у всех по умолчанию»: её видят те, у кого "
             "нет своей настройки этого списка.")
    view_key = fields.Char("Список", required=True, index=True)
    res_model = fields.Char("Модель", help="Для чтения человеком: чей это список.")
    prefs = fields.Json("Настройка")

    _own_unique = models.UniqueIndex(
        "(user_id, view_key) WHERE user_id IS NOT NULL",
        "У человека одна настройка на список.")
    _common_unique = models.UniqueIndex(
        "(view_key) WHERE user_id IS NULL",
        "Общая настройка у списка одна.")

    # ─── Проверки ────────────────────────────────────────────────────────
    @api.model
    def _pmk_check_key(self, view_key):
        if not isinstance(view_key, str) or len(view_key) > 256 or not VIEW_KEY_RE.match(view_key):
            raise ValidationError("Неизвестный список: %r." % (view_key,))
        return view_key

    @api.model
    def _pmk_model_name(self, res_model):
        return res_model if isinstance(res_model, str) and MODEL_RE.match(res_model) else False

    @api.model
    def _pmk_clean(self, prefs):
        """Настройка в виде версии 1, без мусора. Порча — ValidationError."""
        if prefs is None:
            prefs = {}
        if not isinstance(prefs, dict):
            raise ValidationError("Настройка колонок — словарь, а не %s." % type(prefs).__name__)
        if len(json.dumps(prefs, ensure_ascii=False, default=str)) > MAX_JSON:
            raise ValidationError("Настройка колонок слишком большая.")
        order = []
        for key in prefs.get("order") or []:
            if _clean_key(key) and key not in order:
                order.append(key)
            if len(order) >= MAX_ITEMS:
                break
        widths = {}
        raw_widths = prefs.get("widths") or {}
        if isinstance(raw_widths, dict):
            for key, value in raw_widths.items():
                if not _clean_key(key) or isinstance(value, bool):
                    continue
                try:
                    width = int(round(float(value)))
                except (TypeError, ValueError):
                    continue
                if width <= 0:
                    continue
                widths[key] = min(MAX_WIDTH, max(MIN_WIDTH, width))
                if len(widths) >= MAX_ITEMS:
                    break
        visible = {}
        raw_visible = prefs.get("visible") or {}
        if isinstance(raw_visible, dict):
            for key, value in raw_visible.items():
                if _clean_key(key) and isinstance(value, bool):
                    visible[key] = value
                    if len(visible) >= MAX_ITEMS:
                        break
        return {"v": 1, "order": order, "widths": widths, "visible": visible}

    @api.constrains("view_key", "prefs")
    def _check_pmk_prefs(self):
        for rec in self:
            self._pmk_check_key(rec.view_key)
            if rec.prefs is not None and not isinstance(rec.prefs, dict):
                raise ValidationError("Настройка колонок — словарь.")
            if len(json.dumps(rec.prefs or {}, ensure_ascii=False, default=str)) > MAX_JSON:
                raise ValidationError("Настройка колонок слишком большая.")

    def _pmk_is_admin(self):
        return self.env.su or self.env.user.has_group("base.group_system")

    def _pmk_check_owner(self, vals):
        """Чужую или общую запись завести/переписать может только
        администратор (правила доступа это тоже держат — здесь понятный
        текст ошибки и защита от смены владельца записью)."""
        if "user_id" not in vals or self._pmk_is_admin():
            return
        if vals.get("user_id") != self.env.uid:
            raise AccessError(ADMIN_ONLY)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._pmk_check_owner(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._pmk_check_owner(vals)
        return super().write(vals)

    @api.model
    def _pmk_apply_change(self, stored, change):
        """Правка из браузера поверх хранимой настройки (то же, что
        changePrefs в list_prefs_rules.js): visible / widths — слить (ширина
        None — снять), order — заменить, resetWidths — снять все ширины."""
        base = self._pmk_clean(stored if isinstance(stored, dict) else {})
        order = change.get("order")
        if isinstance(order, list):
            base["order"] = order
        if change.get("resetWidths") is True:
            base["widths"] = {}
        widths = change.get("widths")
        if isinstance(widths, dict):
            for key, value in widths.items():
                if value is None:
                    base["widths"].pop(key, None)
                else:
                    base["widths"][key] = value
        visible = change.get("visible")
        if isinstance(visible, dict):
            for key, value in visible.items():
                if isinstance(value, bool):
                    base["visible"][key] = value
        return self._pmk_clean(base)

    # ─── Методы для браузера ─────────────────────────────────────────────
    def _pmk_upsert(self, user_id, view_key, res_model, clean, change=None):
        """Завести или переписать запись; вернуть то, что теперь хранится.

        change (только своя настройка) — правка из браузера: запись уже
        есть — правка сливается с ней (кэш вкладки мог устареть: другая
        вкладка сохранила своё), а не затирает её целиком.
        """
        domain = [("view_key", "=", view_key), ("user_id", "=", user_id)]
        model_name = self._pmk_model_name(res_model)
        record = self.search(domain, limit=1)
        if record:
            if isinstance(change, dict) and not change.get("replace"):
                clean = self._pmk_apply_change(record.prefs, change)
            record.write({"prefs": clean, "res_model": model_name})
            return clean
        try:
            with self.env.cr.savepoint():
                self.create({"prefs": clean, "res_model": model_name,
                             "user_id": user_id, "view_key": view_key})
        except pg_errors.UniqueViolation as exc:
            # Две вкладки одновременно завели первую настройку списка. В
            # этой транзакции (REPEATABLE READ) запись соседа не видна —
            # повторный поиск ничего не найдёт и правка пропадёт молча.
            # ConcurrencyError: ядро (service/model.py, retrying) повторит
            # весь запрос в новой транзакции, там запись найдётся и правка
            # сольётся с ней.
            raise ConcurrencyError(
                "Настройка колонок «%s» сохранялась одновременно — повтор." % view_key
            ) from exc
        return clean

    @api.model
    def pmk_save(self, view_key, res_model=False, prefs=None, change=None):
        """Своя настройка списка: завести или обновить. Возвращает то, что
        теперь хранится.

        prefs — настройка целиком, как её видит вкладка; change — сама
        правка. Своей записи ещё нет — сохраняется prefs (копия общей или
        того, что было на экране, плюс правка). Есть — правка сливается с
        хранимой: старый кэш другой вкладки не затирает чужие ширины и
        порядок.
        """
        key = self._pmk_check_key(view_key)
        clean = self._pmk_clean(prefs)
        if change is not None and change is not False and not isinstance(change, dict):
            raise ValidationError("Правка настройки колонок — словарь.")
        return self._pmk_upsert(self.env.uid, key, res_model, clean,
                                change if isinstance(change, dict) else None)

    @api.model
    def pmk_reset(self, view_key):
        """«Вернуть общую / штатную»: своя настройка списка снимается."""
        key = self._pmk_check_key(view_key)
        self.search([("view_key", "=", key), ("user_id", "=", self.env.uid)]).unlink()
        return True

    @api.model
    def pmk_save_common(self, view_key, res_model=False, prefs=None):
        """«Сделать так у всех» — только администратор.

        Своя настройка администратора по этому списку снимается: он сразу
        видит то, что увидят все. Возвращает чистую настройку и сколько
        внутренних пользователей её увидят (у кого нет своей).
        """
        if not self._pmk_is_admin():
            raise AccessError(ADMIN_ONLY)
        key = self._pmk_check_key(view_key)
        clean = self._pmk_clean(prefs)
        self._pmk_upsert(False, key, res_model, clean)
        self.search([("view_key", "=", key), ("user_id", "=", self.env.uid)]).unlink()
        return {"prefs": clean, "users_on_common": self._pmk_users_on_common(key)}

    @api.model
    def pmk_reset_common(self, view_key):
        """«Убрать общую» — только администратор."""
        if not self._pmk_is_admin():
            raise AccessError(ADMIN_ONLY)
        key = self._pmk_check_key(view_key)
        self.search([("view_key", "=", key), ("user_id", "=", False)]).unlink()
        return True

    @api.model
    def _pmk_users_on_common(self, view_key):
        """Внутренние активные пользователи без своей настройки списка."""
        own = self.sudo().search([("view_key", "=", view_key), ("user_id", "!=", False)])
        return self.env["res.users"].sudo().search_count([
            ("share", "=", False),
            ("id", "not in", own.user_id.ids),
        ])

    @api.model
    def _pmk_session_prefs(self):
        """Для страницы: свои и общие настройки текущего человека."""
        rows = self.sudo().search_read(
            ["|", ("user_id", "=", self.env.uid), ("user_id", "=", False)],
            ["user_id", "view_key", "prefs"],
        )
        own, common = {}, {}
        for row in rows:
            if not isinstance(row["prefs"], dict):
                continue
            (own if row["user_id"] else common)[row["view_key"]] = row["prefs"]
        return {"own": own, "common": common}
