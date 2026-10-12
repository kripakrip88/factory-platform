# -*- coding: utf-8 -*-
"""МойСклад → Odoo: организации, контрагенты, счета покупателям, отгрузки.

Только чтение МоегоСклада (API remap 1.2). Токен — системный параметр
pmk_moysklad.token. Каждая запись Odoo помнит свой id в МоёмСкладе (pmk_ms_id):
повторный прогон обновляет, а не дублирует.

Синхронизация — по полю updated МоегоСклада: крон раз в 10 минут берёт всё,
что изменилось с прошлого раза (pmk_moysklad.last_* — строка времени самого
МоегоСклада, московское время, без пересчёта поясов). Первый перенос «за всё
время» — тем же методом с пустой меткой (sync_all), из odoo shell, партиями.

Решения Антона 12.10.2026:
- номенклатуру не переносим: строка счёта — текстом на служебный товар;
- налог строки — как в МоёмСкладе (сумма сходится); режим организации —
  Чулков НДС 20% до 2026, 22% с 2026, остальные без НДС; несовпадение и
  «НДС сверху» — пометкой (ошибки выставления);
- «Не актуальна» → счёт отменён; статус МоегоСклада — отдельной колонкой.
"""
import gzip
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.pmk_org.tools import regime as rg

_logger = logging.getLogger(__name__)

API = "https://api.moysklad.ru/api/remap/1.2/"
PAGE = 100

# Группа изделия по словам названия строки — порядок важен (первое совпадение).
GROUP_RULES = [
    ("tpr", r"тпр|колод|стремянк|соединительн\w* элемент|мс-\d"),
    ("embed", r"заклад|\bзд\s?-?\d|\bмн\s?-?\d|анкер|болт фундамент"),
    ("vent", r"зонт|дефлект|вентил"),
    ("fence", r"огражд|ворот|калитк|панел|3d|3д|столб|егоз|заглушк|секци|сетк|забор"),
    ("roof", r"кровел|снегозад|водост|желоб|жёлоб|кассет|отлив|отмет|планк|добор|капельн|"
             r"кон[её]к|ендов|колено|воронк|тройник|мостик"),
    ("steel", r"балк|ферм|колонн|лестниц|площадк|стойк|ригел|прогон|связ|каркас|навес|кмд|"
              r"металлоконструк|\bмк\b|оголовок|опор|рам[аы]\b|кронштейн"),
    ("service", r"покраск|окраск|цинкован|доставк|транспорт|монтаж|услуг|резк|гибк|работ"),
    ("fastener", r"болт|гайк|шайб|саморез|скоб|крепл|костыл|шпильк|дюбел"),
    ("rolled", r"лист|пластин|труб|уголок|швеллер|двутавр|арматур|полос|круг"),
]

# Ставка НДС строки → режим, чей налог ставим строке.
RATE_REGIME = {22: "vat22", 20: "vat20", 5: "usn5", 7: "usn7", 0: "usn0"}

# Режимы наших организаций по ИНН (Антон 12.10.2026). Остальные — УСН без НДС.
ORG_REGIMES = {
    "272107382162": [("2020-01-01", "vat20"), ("2026-01-01", "vat22")],  # ИП Чулков
}


def group_of(name):
    low = (name or "").lower()
    for code, rx in GROUP_RULES:
        if re.search(rx, low):
            return code
    return "other"


def ms_id(meta_or_row):
    """Id МоегоСклада из строки или ссылки meta."""
    meta = meta_or_row.get("meta", meta_or_row) if isinstance(meta_or_row, dict) else {}
    href = meta.get("href") or ""
    return href.rstrip("/").rsplit("/", 1)[-1].split("?")[0] or False


def lead_days(text):
    nums = [int(n) for n in re.findall(r"\d+", text or "")]
    return max(nums) if nums else 0


def ms_date(value):
    """«2026-10-12 13:05:01.000» → datetime (московское время МоегоСклада, как есть)."""
    if not value:
        return False
    return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")


class PmkMoysklad(models.AbstractModel):
    _name = "pmk.moysklad"
    _description = "МойСклад → Odoo"

    # ------------------------------------------------------------ API
    @api.model
    def _ms_commit(self):
        """Перенос «за всё время» — тысячи записей: фиксируем по частям. В тестах нельзя."""
        if not (self.env.context.get("pmk_ms_no_commit")
                or getattr(threading.current_thread(), "testing", False)):
            self.env.cr.commit()

    @api.model
    def _ms_get(self, path, params=None):
        token = self.env["ir.config_parameter"].sudo().get_param("pmk_moysklad.token")
        if not token:
            raise UserError("Нет токена МоегоСклада: системный параметр pmk_moysklad.token.")
        url = API + path
        if params:
            # Фильтр — кодировать целиком («>=», «:», пробел), иначе МойСклад отвечает 400.
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
                params, safe=",", quote_via=urllib.parse.quote)
        for attempt in range(6):
            req = urllib.request.Request(url, headers={
                "Authorization": "Bearer " + token, "Accept-Encoding": "gzip"})
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    return json.loads(raw)
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:  # лимит запросов / сбой — подождать
                    time.sleep(2 + attempt * 3)
                    continue
                raise UserError("МойСклад ответил %s на %s" % (e.code, path)) from e
            except urllib.error.URLError:
                time.sleep(2 + attempt * 3)
        raise UserError("МойСклад не отвечает: %s" % path)

    @api.model
    def _ms_rows(self, entity, updated_since=None, expand=None, extra_filter=None):
        """Все строки сущности (постранично), по возрастанию updated."""
        flt = []
        if updated_since:
            flt.append("updated>=%s" % updated_since[:19])  # без миллисекунд — иначе 400
        if extra_filter:
            flt.append(extra_filter)
        params = {"limit": PAGE, "order": "updated,asc"}
        if flt:
            params["filter"] = ";".join(flt)
        if expand:
            params["expand"] = expand
        offset = 0
        while True:
            params["offset"] = offset
            data = self._ms_get("entity/%s" % entity, params)
            rows = data.get("rows", [])
            yield from rows
            offset += PAGE
            if offset >= data.get("meta", {}).get("size", 0) or not rows:
                break

    # ------------------------------------------------------------ организации
    @api.model
    def _sync_orgs(self):
        # ИНН — как в МоёмСкладе, без проверки контрольной суммы (опечатку покажет DaData).
        Org = self.env["pmk.org"].with_context(active_test=False, tracking_disable=True,
                                               no_vat_validation=True)
        out = {}
        for row in self._ms_rows("organization"):
            mid, inn = ms_id(row), row.get("inn") or ""
            org = Org.search([("pmk_ms_id", "=", mid)], limit=1) or \
                (inn and Org.search([("inn", "=", inn)], limit=1)) or \
                Org.search([("name", "=ilike", row.get("name", "").strip())], limit=1)
            regimes = ORG_REGIMES.get(inn, [("2020-01-01", "usn0")])
            if not org:
                org = Org.create({
                    "name": row.get("name") or row.get("legalTitle"),
                    "org_type": "ip" if len(inn) == 12 else "ooo",
                    "signer_name": row.get("director") or False,
                    "signer_position": row.get("directorPosition") or False,
                    "regime_ids": [(0, 0, {"date_from": d, "regime": r}) for d, r in regimes],
                })
                org.write({"inn": inn or False, "ogrn": row.get("ogrnip") or row.get("ogrn") or False,
                           "legal_address": row.get("legalAddress") or False})
            else:
                have = {(str(r.date_from), r.regime) for r in org.regime_ids}
                org.write({"regime_ids": [(0, 0, {"date_from": d, "regime": r})
                                          for d, r in regimes if (d, r) not in have]})
                if inn and not org.inn:
                    org.inn = inn
            org.pmk_ms_id = mid
            out[mid] = org
        return out

    # ------------------------------------------------------------ контрагенты
    @api.model
    def _partner_vals(self, row):
        inn = (row.get("inn") or "").strip()
        vals = {
            "name": (row.get("name") or row.get("legalTitle") or "Без названия").strip(),
            "is_company": row.get("companyType") != "individual",
            "pmk_ms_id": ms_id(row),
        }
        extra = {
            "vat": inn, "kpp": row.get("kpp"), "ogrn": row.get("ogrn") or row.get("ogrnip"),
            "pmk_legal_name": row.get("legalTitle"), "pmk_legal_address": row.get("legalAddress"),
            "street": row.get("actualAddress"), "email": row.get("email"), "phone": row.get("phone"),
        }
        return vals, {k: v.strip() for k, v in extra.items() if isinstance(v, str) and v.strip()}

    @api.model
    def _norm(self, name):
        return re.sub(r"[^a-zа-я0-9]", "", (name or "").lower().replace("ё", "е"))

    @api.model
    def _match_partner(self, row, cache):
        Partner = self.env["res.partner"].with_context(active_test=False)
        mid = ms_id(row)
        found = Partner.search([("pmk_ms_id", "=", mid)], limit=1)
        if found:
            return found
        inn = (row.get("inn") or "").strip()
        if inn:
            dom = [("vat", "=", inn), ("parent_id", "=", False)]
            if row.get("kpp"):
                found = Partner.search(dom + [("kpp", "=", row["kpp"])], limit=1)
            found = found or Partner.search(dom, limit=1)
            if found and not found.pmk_ms_id:
                return found
        if "names" not in cache:
            cache["names"] = {}
            for p in Partner.search([("pmk_ms_id", "=", False), ("parent_id", "=", False)]):
                cache["names"].setdefault(self._norm(p.name), p)
        return cache["names"].pop(self._norm(row.get("name")), Partner.browse())

    @api.model
    def _upsert_partner(self, row, cache):
        Partner = self.env["res.partner"].with_context(
            active_test=False, tracking_disable=True, mail_create_nolog=True, no_vat_validation=True)
        vals, extra = self._partner_vals(row)
        partner = self._match_partner(row, cache)
        tag = cache.get("tag")
        if partner:
            # Своё не затираем: пустые поля дополняем, id МоегоСклада ставим.
            upd = {k: v for k, v in extra.items() if not partner[k]}
            upd["pmk_ms_id"] = vals["pmk_ms_id"]
            partner.with_context(tracking_disable=True, no_vat_validation=True).write(upd)
        else:
            vals.update(extra)
            partner = Partner.create(vals)
        if tag and tag not in partner.category_id:
            partner.category_id = [(4, tag.id)]
        return partner

    @api.model
    def _sync_partners(self, since=None):
        cache = {"tag": self.env.ref("pmk_moysklad.partner_tag_ms", raise_if_not_found=False)}
        last, n = since, 0
        for row in self._ms_rows("counterparty", updated_since=since):
            self._upsert_partner(row, cache)
            last, n = row.get("updated") or last, n + 1
            if n % 200 == 0:
                self._ms_commit()
        return n, last

    @api.model
    def _partner_by_ms(self, meta, cache):
        mid = ms_id(meta)
        href = (meta.get("meta", meta) or {}).get("href", "")
        if "/organization/" in href:  # покупатель — наша же организация
            org = self.env["pmk.org"].with_context(active_test=False).search([("pmk_ms_id", "=", mid)], limit=1)
            if org:
                return org.partner_id
        Partner = self.env["res.partner"].with_context(active_test=False)
        partner = Partner.search([("pmk_ms_id", "=", mid)], limit=1)
        if partner:
            return partner
        try:  # контрагент новее прошлой синхронизации — забираем по ссылке
            row = self._ms_get("entity/counterparty/%s" % mid)
        except UserError:
            # Удалён в МоёмСкладе, а счёт на него остался — заглушка, чтобы счёт перенёсся.
            return Partner.with_context(tracking_disable=True, mail_create_nolog=True).create({
                "name": "Контрагент удалён в МоёмСкладе", "is_company": True, "pmk_ms_id": mid,
                "category_id": [(4, cache["tag"].id)] if cache.get("tag") else False})
        return self._upsert_partner(row, cache)

    # ------------------------------------------------------------ счета
    @api.model
    def _taxes(self):
        company = self.env.company
        out = {}
        for regime in rg.RATES:
            out[regime] = self.env["account.tax"].sudo().search([
                ("pmk_regime", "=", regime), ("type_tax_use", "=", "sale"),
                ("company_id", "=", company.id)], limit=1)
        return out

    @api.model
    def _line_regime(self, inv, pos):
        enabled = pos.get("vatEnabled", inv.get("vatEnabled"))
        rate = int(round(pos.get("vat") or 0)) if enabled else 0
        return RATE_REGIME.get(rate, "usn0"), rate

    @api.model
    def _invoice_vals(self, inv, orgs, ctx):
        attrs = {a.get("name", "").strip(" :"): a.get("value") for a in inv.get("attributes", [])}
        attrs = {k: (v.get("name") if isinstance(v, dict) else v) for k, v in attrs.items()}
        org = orgs.get(ms_id(inv["organization"])) or self.env["pmk.org"]
        partner = self._partner_by_ms(inv["agent"], ctx)
        state = (inv.get("state") or {}).get("name") or False
        when = ms_date(inv.get("moment"))
        delivery = attrs.get("Условия доставки") or ""
        vals = {
            "name": inv.get("name"),
            "partner_id": partner.id,
            "pmk_org_id": org.id or False,
            # Время МоегоСклада — московское (UTC+3), Odoo хранит UTC.
            "date_order": when - timedelta(hours=3) if when else fields.Datetime.now(),
            "user_id": False,
            "note": inv.get("description") or False,
            "pmk_ms_id": ms_id(inv),
            "pmk_ms_state": state,
            "pmk_ms_updated": inv.get("updated"),
            "pmk_ms_sum": (inv.get("sum") or 0) / 100.0,
            "pmk_ms_shipped_sum": (inv.get("shippedSum") or 0) / 100.0,
            "pmk_ms_contract": attrs.get("Договор поставки") or False,
            "pmk_ms_object": attrs.get("Объект") or False,
            "pmk_ms_weight": attrs.get("Вес продукции") or False,
            "pmk_payment_note": attrs.get("Условия оплаты") or False,
            "pmk_lead_days": lead_days(attrs.get("Срок изготовления")),
        }
        if delivery:
            pickup = delivery.lower().startswith("самовывоз")
            vals["pmk_delivery"] = "pickup" if pickup else "delivery"
            vals["pmk_delivery_address"] = delivery[:250]
        # Строки: текстом на служебный товар; налог — как в МоёмСкладе.
        taxes, product = ctx["taxes"], ctx["product"]
        lines, rates = [], set()
        for seq, pos in enumerate(inv.get("positions", {}).get("rows", []), 1):
            item = pos.get("assortment") or {}
            name = (item.get("name") or "Позиция").strip()
            uom = ((item.get("uom") or {}).get("name") or "").strip()
            if uom and uom.lower() not in ("шт", "шт."):
                name = "%s (%s)" % (name, uom)
            regime, rate = self._line_regime(inv, pos)
            rates.add(rate)
            lines.append((0, 0, {
                "sequence": seq,
                "product_id": product.id,
                "name": name,
                "product_uom_qty": pos.get("quantity") or 0.0,
                "price_unit": (pos.get("price") or 0) / 100.0,
                "discount": pos.get("discount") or 0.0,
                "tax_ids": [(6, 0, taxes[regime].ids)],
                "pmk_ms_group": group_of(name),
            }))
        vals["order_line"] = lines
        # Расхождения с режимом организации (ошибки выставления) — пометкой.
        notes = []
        if org and when:
            row = org._pmk_regime_at(when.date())
            expect = int(rg.RATES[row.regime]) if row else None
            other = sorted(r for r in rates if r != expect)
            if expect is not None and other:
                notes.append("НДС в строках %s вместо %s%%" % (
                    ", ".join("%s%%" % r if r else "без НДС" for r in other), expect))
        if inv.get("vatEnabled") and inv.get("vatIncluded") is False:
            notes.append("НДС сверху, а не в цене")
        vals["pmk_ms_note"] = "; ".join(notes) or False
        return vals, state

    @api.model
    def _sync_invoices(self, since=None):
        Order = self.env["sale.order"].with_context(
            active_test=False, tracking_disable=True, mail_create_nolog=True, mail_notrack=True)
        ctx = {
            "tag": self.env.ref("pmk_moysklad.partner_tag_ms", raise_if_not_found=False),
            "taxes": self._taxes(),
            "product": self.env.ref("pmk_moysklad.product_ms_line"),
        }
        orgs = {o.pmk_ms_id: o for o in self.env["pmk.org"].with_context(active_test=False).search(
            [("pmk_ms_id", "!=", False)])}
        last, n, failed = since, 0, 0
        Param = self.env["ir.config_parameter"].sudo()
        for inv in self._ms_rows("invoiceout", updated_since=since,
                                 expand="positions.assortment.uom,state"):
            try:
                with self.env.cr.savepoint():
                    self._upsert_invoice(inv, orgs, ctx, Order)
            except Exception as e:  # один счёт не останавливает перенос
                failed += 1
                _logger.warning("pmk_moysklad: счёт %s не перенесён: %s", inv.get("name"), e)
            last, n = inv.get("updated") or last, n + 1
            if n % 100 == 0:
                Param.set_param("pmk_moysklad.last_invoices", last)
                self._ms_commit()
                _logger.info("pmk_moysklad: счетов %s (до %s), не перенесено %s", n, last, failed)
        return n, last

    @api.model
    def _upsert_invoice(self, inv, orgs, ctx, Order):
        vals, state = self._invoice_vals(inv, orgs, ctx)
        order = Order.search([("pmk_ms_id", "=", vals["pmk_ms_id"])], limit=1)
        if order:
            if order.state == "cancel":
                order.write({"state": "draft"})
            order.order_line.unlink()
            order.write(vals)
        else:
            order = Order.create(vals)
        # Налог строки — как в МоёмСкладе: пересчёт налога по организации (pmk_org,
        # _compute_tax_ids) мог его заменить при создании — ставим ещё раз.
        for line, (_c, _i, lv) in zip(order.order_line.sorted("sequence"), vals["order_line"]):
            if line.tax_ids.ids != lv["tax_ids"][0][2]:
                line.tax_ids = lv["tax_ids"]
        diff = abs(order.amount_total - vals["pmk_ms_sum"])
        if diff > 0.05:
            order.pmk_ms_note = "; ".join(filter(None, [
                order.pmk_ms_note, "сумма в Odoo %.2f, в МоёмСкладе %.2f" % (
                    order.amount_total, vals["pmk_ms_sum"])]))
        if state == "Не актуальна" and order.state != "cancel":
            order.write({"state": "cancel"})
        return order

    # ------------------------------------------------------------ отгрузки
    @api.model
    def _sync_demands(self, since=None):
        """Отгрузка — отметкой в счёте: дата последней отгрузки по счёту."""
        Order = self.env["sale.order"].with_context(active_test=False, tracking_disable=True)
        last, n = since, 0
        for dem in self._ms_rows("demand", updated_since=since):
            when = ms_date(dem.get("moment"))
            for meta in dem.get("invoicesOut") or []:
                order = Order.search([("pmk_ms_id", "=", ms_id(meta))], limit=1)
                if order and when and (not order.pmk_ms_shipped_date
                                       or order.pmk_ms_shipped_date < when.date()):
                    order.pmk_ms_shipped_date = when.date()
            last, n = dem.get("updated") or last, n + 1
        return n, last

    # ------------------------------------------------------------ запуск
    @api.model
    def sync_all(self, full=False):
        """Организации → контрагенты → счета → отгрузки, с прошлой метки (full — с нуля)."""
        Param = self.env["ir.config_parameter"].sudo()
        report = {}
        self._sync_orgs()
        for key, method in (("partners", self._sync_partners), ("invoices", self._sync_invoices),
                            ("demands", self._sync_demands)):
            since = None if full else (Param.get_param("pmk_moysklad.last_%s" % key) or None)
            n, last = method(since)
            if last:
                Param.set_param("pmk_moysklad.last_%s" % key, last)
            self._ms_commit()
            report[key] = n
        Param.set_param("pmk_moysklad.last_run", fields.Datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        _logger.info("pmk_moysklad: синхронизация %s", report)
        return report

    @api.model
    def _cron_sync(self):
        if not self.env["ir.config_parameter"].sudo().get_param("pmk_moysklad.token"):
            return
        if not self.env["ir.config_parameter"].sudo().get_param("pmk_moysklad.last_invoices"):
            return  # первый перенос «за всё время» — из shell, не кроном
        self.sync_all()
