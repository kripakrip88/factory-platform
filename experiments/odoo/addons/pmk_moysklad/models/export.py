# -*- coding: utf-8 -*-
"""Счёт Odoo → МойСклад (этап 6 плана «сделка → счёт», решения Антона 22.10.2026).

  • когда — сразу при создании счёта (номер «01233» сразу занят и в МС);
  • статус в МС — «Из Odoo» (завёл Антон), отмена в Odoo — «Не актуальна»;
  • строки — товары МС: товар с тем же названием есть — берём его, нет — создаём в группе
    «Из Odoo» (группа — системный параметр pmk_moysklad.odoo_folder_id, создана через API);
  • контрагент — по id МС, иначе по ИНН, иначе создаём;
  • организация — та же, что в счёте Odoo; НДС — по режиму организации на дату счёта, «в цене».

Главный для такого счёта — Odoo: синхронизация МС → Odoo берёт у него только статус, сумму и
отгрузки (moysklad.py, _upsert_invoice), строки не переписывает. Правка счёта в Odoo (строки,
клиент, организация, дата, отмена) ставит его в очередь заново — выгрузка обновляет документ МС.

Сеть — только в фоне (правило «доработка не тормозит систему»): создание и правка счёта лишь
ставят отметку «ждёт выгрузки», крон раз в 2 минуты отправляет очередь.

Режим — системный параметр pmk_moysklad.export_mode:
  off  — ничего (по умолчанию: включает Антон);
  dry  — «вхолостую»: всё читаем из МС (товары, контрагента, статус), что отправили бы — в ленту
         счёта, в МС НЕ пишем (копия odoo_stage);
  live — пишем в МС.
"""
import gzip
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.pmk_org.tools import regime as rg

from .moysklad import API, ms_id

_logger = logging.getLogger(__name__)

MODE_PARAM = "pmk_moysklad.export_mode"
FOLDER_PARAM = "pmk_moysklad.odoo_folder_id"
STATE_ODOO = "Из Odoo"
STATE_CANCEL = "Не актуальна"
BATCH = 20
# Поля счёта, правка которых меняет документ МС.
EXPORT_FIELDS = {"order_line", "partner_id", "pmk_org_id", "date_order", "state", "name", "note"}
# Единица строки Odoo → единица МС (по названию в справочнике МС).
UOM_MS = {"units": "шт", "единицы": "шт", "шт": "шт", "kg": "кг", "кг": "кг", "t": "т", "т": "т",
          "m": "м", "м": "м", "m²": "м2", "м²": "м2", "m2": "м2", "м2": "м2"}
EXPORT_STATES = [("pending", "Ждёт выгрузки"), ("done", "Выгружен"), ("dry", "Вхолостую"),
                 ("error", "Ошибка выгрузки")]


class MsWriteError(Exception):
    pass


def meta(kind, mid, path=None):
    return {"meta": {"href": API + (path or "entity/%s/%s" % (kind, mid)), "type": kind,
                     "mediaType": "application/json"}}


class SaleOrderMsExport(models.Model):
    _inherit = "sale.order"

    pmk_ms_from_odoo = fields.Boolean("Сделан в Odoo", copy=False, readonly=True,
                                      help="Счёт создан в Odoo и выгружается в МойСклад: главный — Odoo.")
    pmk_ms_export_state = fields.Selection(EXPORT_STATES, "Выгрузка в МойСклад", copy=False, readonly=True,
                                           index=True)
    pmk_ms_export_note = fields.Char("Выгрузка: подробности", copy=False, readonly=True)
    pmk_ms_export_at = fields.Datetime("Выгружен", copy=False, readonly=True)

    # ─── Очередь ────────────────────────────────────────────────────────
    def _pmk_ms_exportable(self):
        """Счёт, сделанный в Odoo: не пришёл из МС и не прежняя редакция."""
        self.ensure_one()
        return (self.pmk_ms_from_odoo or not self.pmk_ms_id) and not self.pmk_is_revision

    def _pmk_ms_queue(self):
        for order in self.sudo():
            if order._pmk_ms_exportable() and order.pmk_ms_export_state != "pending":
                super(SaleOrderMsExport, order).write({"pmk_ms_from_odoo": True, "pmk_ms_export_state": "pending"})

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders.filtered(lambda o: not o.pmk_ms_id)._pmk_ms_queue()
        return orders

    def write(self, vals):
        res = super().write(vals)
        if EXPORT_FIELDS & set(vals) and not self.env.context.get("pmk_ms_sync"):
            self.filtered("pmk_ms_from_odoo")._pmk_ms_queue()
        return res

    # ─── Крон ───────────────────────────────────────────────────────────
    @api.model
    def _cron_ms_export(self):
        mode = self.env["ir.config_parameter"].sudo().get_param(MODE_PARAM) or "off"
        if mode not in ("dry", "live"):
            return
        orders = self.sudo().search([("pmk_ms_export_state", "=", "pending")], limit=BATCH, order="id")
        if not orders:
            return
        ms = self.env["pmk.moysklad"].sudo()
        cache = {}
        for order in orders:
            try:
                with self.env.cr.savepoint():
                    order._pmk_ms_export_one(ms, mode, cache)
            except Exception as exc:  # noqa: BLE001 — один счёт не останавливает очередь
                _logger.warning("pmk_moysklad: выгрузка %s не вышла: %s", order.name, exc)
                super(SaleOrderMsExport, order).write({
                    "pmk_ms_export_state": "error", "pmk_ms_export_note": str(exc)[:250]})
            ms._ms_commit()

    def _pmk_ms_export_one(self, ms, mode, cache):
        self.ensure_one()
        dry = mode != "live"
        notes = []
        body = self._pmk_ms_payload(ms, dry, cache, notes)
        if dry:
            text = "Вхолостую (в МС не записано): %s %s «%s», %s строк(и) на %.2f ₽%s" % (
                "обновили бы" if self.pmk_ms_id else "создали бы", "счёт", body.get("name"),
                len(body.get("positions", [])), self.amount_total, ("; " + "; ".join(notes)) if notes else "")
            self.message_post(body=text)
            super(SaleOrderMsExport, self).write({"pmk_ms_export_state": "dry", "pmk_ms_export_note": text[:250]})
            return
        if self.pmk_ms_id:
            ms._ms_write("PUT", "entity/invoiceout/%s" % self.pmk_ms_id, body)
            what = "обновлён"
        else:
            row = ms._ms_write("POST", "entity/invoiceout", body)
            super(SaleOrderMsExport, self).write({"pmk_ms_id": row["id"], "pmk_ms_updated": row.get("updated")})
            what = "создан"
        if body.get("state"):
            super(SaleOrderMsExport, self).write({"pmk_ms_state": STATE_CANCEL if self.state == "cancel"
                                                  else STATE_ODOO})
        note = "Счёт %s в МоёмСкладе%s" % (what, ("; " + "; ".join(notes)) if notes else "")
        self.message_post(body=note)
        super(SaleOrderMsExport, self).write({"pmk_ms_export_state": "done", "pmk_ms_export_note": note[:250],
                                              "pmk_ms_export_at": fields.Datetime.now()})

    # ─── Документ МС ────────────────────────────────────────────────────
    def _pmk_ms_payload(self, ms, dry, cache, notes):
        self.ensure_one()
        org = self.pmk_org_id
        if not org or not org.pmk_ms_id:
            raise MsWriteError("у организации счёта нет связи с МоимСкладом")
        # Статус: при создании — «Из Odoo», отмена — «Не актуальна», вернули из отмены — снова
        # «Из Odoo». Иначе не трогаем: «Оплачен» и прочие ставит Владимир в МС.
        want = None
        if self.state == "cancel":
            want = STATE_CANCEL if self.pmk_ms_state != STATE_CANCEL or not self.pmk_ms_id else None
        elif not self.pmk_ms_id or self.pmk_ms_state == STATE_CANCEL:
            want = STATE_ODOO
        state = ms._ms_invoice_state(want, cache) if want else None
        agent = self._pmk_ms_agent(ms, dry, cache, notes)
        day = (self.date_order or fields.Datetime.now())
        regime = org._pmk_regime_at(day.date())
        rate = int(rg.RATES[regime.regime]) if regime else 0
        positions = []
        long_names = []
        for line in self.order_line.filtered(lambda l: not l.display_type).sorted("sequence"):
            name = (line.name or "").strip() or "Позиция"
            if len(name) > 255:
                long_names.append(name)
            product = ms._ms_product(name[:255], self._pmk_ms_uom(line), dry, cache, notes)
            pos = {"quantity": line.product_uom_qty, "price": round(line.price_unit * 100),
                   "discount": line.discount or 0, "vat": rate, "vatEnabled": bool(rate),
                   "assortment": product}
            positions.append(pos)
        description = "Счёт из Odoo" + (" · сделка %s" % self.opportunity_id.display_name
                                        if self.opportunity_id else "")
        if self.note:
            description += "\n" + str(self.note)
        if long_names:
            description += "\nПолные названия строк: " + "; ".join(long_names)
        body = {
            "name": self.name,
            "moment": (day + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),  # МС — московское
            "organization": meta("organization", org.pmk_ms_id),
            "agent": agent,
            "vatEnabled": bool(rate),
            "vatIncluded": True,
            "description": description[:4000],
            "positions": positions,
        }
        if state:
            body["state"] = state
        return body

    def _pmk_ms_uom(self, line):
        name = (line.product_uom_id.name or "").strip().lower()
        return UOM_MS.get(name, "шт")

    def _pmk_ms_agent(self, ms, dry, cache, notes):
        partner = self.partner_id.commercial_partner_id
        if partner.pmk_ms_id:
            return meta("counterparty", partner.pmk_ms_id)
        inn = (partner.vat or "").strip()
        if inn:
            rows = ms._ms_get("entity/counterparty", {"filter": "inn=%s" % inn, "limit": 1}).get("rows", [])
            if rows:
                if not dry:
                    self._pmk_ms_link_partner(partner, rows[0]["id"])
                return meta("counterparty", rows[0]["id"])
        elif ";" not in (partner.name or ""):
            # Без ИНН — только точное название; не нашли — не заводим: в МС был бы дубль без ИНН
            # (в Odoo бывают старые карточки-двойники без ИНН — ГЕО-ИНВЕСТ на копии, 22.10.2026).
            rows = ms._ms_get("entity/counterparty", {"filter": "name=%s" % partner.name, "limit": 1}).get("rows", [])
            if rows:
                if not dry:
                    self._pmk_ms_link_partner(partner, rows[0]["id"])
                return meta("counterparty", rows[0]["id"])
        if not inn:
            raise MsWriteError("у клиента «%s» нет ИНН, а в МоёмСкладе такого нет — выберите в счёте "
                               "карточку клиента с ИНН или впишите ИНН" % partner.display_name)
        notes.append("контрагент «%s» новый — заведён в МС" % partner.display_name if not dry
                     else "контрагента «%s» в МС нет — завели бы" % partner.display_name)
        if dry:
            return meta("counterparty", "dry-new")
        body = {"name": partner.name, "inn": inn,
                "companyType": "legal" if len(inn) == 10 else (
                    "entrepreneur" if (partner.name or "").upper().startswith("ИП") else "individual")}
        row = ms._ms_write("POST", "entity/counterparty", body)
        self._pmk_ms_link_partner(partner, row["id"])
        return meta("counterparty", row["id"])

    def _pmk_ms_link_partner(self, partner, mid):
        """Карточке — id МС, если он не занят другой карточкой (двойники в Odoo бывают)."""
        Partner = self.env["res.partner"].sudo().with_context(active_test=False)
        if not Partner.search_count([("pmk_ms_id", "=", mid), ("id", "!=", partner.id)], limit=1):
            partner.sudo().pmk_ms_id = mid


class PmkMoyskladWrite(models.AbstractModel):
    _inherit = "pmk.moysklad"

    @api.model
    def _ms_write(self, method, path, body):
        """POST/PUT в МойСклад. Только из выгрузки счетов (режим live)."""
        token = self.env["ir.config_parameter"].sudo().get_param("pmk_moysklad.token")
        if not token:
            raise MsWriteError("нет токена МоегоСклада")
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        for attempt in range(5):
            req = urllib.request.Request(API + path, data=data, method=method, headers={
                "Authorization": "Bearer " + token, "Accept-Encoding": "gzip",
                "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    time.sleep(2 + attempt * 3)
                    continue
                detail = e.read()[:400].decode("utf-8", "replace")
                try:
                    detail = "; ".join(x.get("error", "") for x in json.loads(detail).get("errors", []))
                except ValueError:
                    pass
                raise MsWriteError("МойСклад ответил %s: %s" % (e.code, detail)) from e
        raise MsWriteError("МойСклад не отвечает")

    @api.model
    def _ms_invoice_state(self, name, cache):
        states = cache.get("states")
        if states is None:
            data = self._ms_get("entity/invoiceout/metadata")
            states = cache["states"] = {s["name"]: s["id"] for s in data.get("states", [])}
        if name not in states:
            raise MsWriteError("в МоёмСкладе нет статуса счёта «%s»" % name)
        return meta("state", states[name], "entity/invoiceout/metadata/states/%s" % states[name])

    @api.model
    def _ms_uom(self, name, cache):
        uoms = cache.setdefault("uoms", {})
        if name not in uoms:
            rows = self._ms_get("entity/uom", {"filter": "name=%s" % name, "limit": 1}).get("rows", [])
            uoms[name] = rows[0]["id"] if rows else False
        return uoms[name]

    @api.model
    def _ms_product(self, name, uom, dry, cache, notes):
        """Товар МС по точному названию; нет — создаём в группе «Из Odoo»."""
        products = cache.setdefault("products", {})
        if name in products:
            return products[name]
        rows = []
        if ";" not in name:  # «;» — разделитель условий фильтра МС: такие названия не ищем
            rows = self._ms_get("entity/product", {"filter": "name=%s" % name, "limit": 1}).get("rows", [])
        if rows:
            products[name] = meta("product", rows[0]["id"])
            return products[name]
        folder = self.env["ir.config_parameter"].sudo().get_param(FOLDER_PARAM)
        if not folder:
            raise MsWriteError("не задана группа товаров «Из Odoo» (pmk_moysklad.odoo_folder_id)")
        if dry:
            notes.append("новый товар «%s» — завели бы в группе «Из Odoo»" % name[:60])
            products[name] = meta("product", "dry-new")
            return products[name]
        body = {"name": name, "productFolder": meta("productfolder", folder)}
        uom_id = self._ms_uom(uom, cache)
        if uom_id:
            body["uom"] = meta("uom", uom_id)
        row = self._ms_write("POST", "entity/product", body)
        notes.append("новый товар «%s»" % name[:60])
        products[name] = meta("product", row["id"])
        return products[name]


class SaleOrderLineMsExport(models.Model):
    _inherit = "sale.order.line"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.order_id.filtered("pmk_ms_from_odoo")._pmk_ms_queue()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if {"name", "product_uom_qty", "price_unit", "discount", "product_uom_id", "sequence"} & set(vals):
            self.order_id.filtered("pmk_ms_from_odoo")._pmk_ms_queue()
        return res

    def unlink(self):
        orders = self.order_id.filtered("pmk_ms_from_odoo")
        res = super().unlink()
        orders.exists()._pmk_ms_queue()
        return res
