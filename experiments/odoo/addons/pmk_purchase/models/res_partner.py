# -*- coding: utf-8 -*-
import datetime
import logging

import pytz
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Сроки запросов считаем в днях по заводскому времени, а не по UTC и не по
# часовому поясу того, кто спросил. Решение «пора ли писать» принимает
# плановое задание, и работает оно от системного пользователя, у которого
# часового пояса нет вовсе: по его часам понедельник 09:10 во Владивостоке —
# ещё воскресенье. Список в браузере обязан показывать ту же дату, что увидит
# задание, иначе «следующий запрос 5 октября» и реальное письмо разойдутся.
TZ = "Asia/Vladivostok"


def _local_today():
    return datetime.datetime.now(pytz.timezone(TZ)).date()


def _local_date(value):
    """Дата по заводскому времени из хранимого в UTC момента."""
    if not value:
        return False
    return pytz.UTC.localize(value).astimezone(pytz.timezone(TZ)).date()


class ResPartner(models.Model):
    _inherit = "res.partner"

    # ------------------------------------------------------------------
    # участие в запросе прайсов
    # ------------------------------------------------------------------
    pmk_price_supplier = fields.Boolean(
        "Поставщик прайсов",
        help="Участвует в регулярном запросе актуальных цен.",
        index="btree_not_null",
    )
    pmk_supply_ids = fields.Many2many(
        "pmk.supply.category",
        string="Что возит",
        help="По этим группам у поставщика и спрашиваем цены.",
    )
    # Ручной выключатель рассылки. Отдельно от «поставщик прайсов»: в реестре
    # держим всех найденных, а письма уходят только отмеченным. Снабженец
    # правит этот флажок сам, в том числе пачкой из списка.
    pmk_price_mailing = fields.Boolean(
        "В рассылке",
        help="Письмо с запросом прайса уходит только тем, у кого включено.",
        index="btree_not_null",
    )
    pmk_price_request_date = fields.Datetime(
        "Последний запрос отправлен",
        readonly=True,
        help="Когда мы последний раз просили прайс. От него (или от "
             "последнего прайса, если тот пришёл не в ответ на запрос) "
             "считается следующий запрос.",
    )

    pmk_has_stock = fields.Boolean(
        "Склад на Дальнем Востоке",
        help="Есть своя площадка, а не только офис. Короткое плечо поставки.",
    )

    # ------------------------------------------------------------------
    # адрес для запроса
    # ------------------------------------------------------------------
    # Держим отдельно от `email` намеренно. Список поставщиков собран из
    # открытых источников: пока адрес не подтверждён, он не должен попадать
    # ни в одну штатную рассылку Odoo. Пустой `email` это гарантирует.
    pmk_price_email = fields.Char(
        "Адрес для запроса прайса",
        help="Куда писать за ценами. В основное поле «Email» переносится "
             "только после подтверждения.",
    )
    pmk_price_email_state = fields.Selection(
        [
            ("draft", "Не подтверждён"),
            ("confirmed", "Подтверждён"),
            ("invalid", "Не работает"),
        ],
        string="Состояние адреса",
        default="draft",
        required=True,
        help="Рассылка уходит только на подтверждённые адреса.",
    )
    pmk_price_email_source = fields.Char(
        "Источник адреса",
        help="Страница, с которой адрес взят. Нужна, чтобы адрес можно было "
             "перепроверить, а не верить на слово.",
    )

    # ------------------------------------------------------------------
    # периодичность
    # ------------------------------------------------------------------
    # «Оживить таблицы» (29.09.2026): список поставщиков открывается
    # сгруппированным, и Odoo складывал периодичность в строке группы
    # («Трубы — 70 дней»). Сумма дней бессмысленна — строку группы оставляем
    # пустой.
    pmk_price_period_days = fields.Integer(
        "Периодичность, дней",
        default=14,
        aggregator=None,
        help="Как часто просить свежий прайс. Ноль — не просить автоматически.",
    )
    # Разбор UX, шаг 13 (29.09.2026). Раньше это поле было ручным с
    # подписью «заполняется при приёме файла», но при приёме его никто не
    # заполнял — ни загрузчик прайсов, ни человек. Пустое у всех, и фильтр
    # «Прайса ещё не было» показывал в том числе Металлсервис с его 1554
    # ценами.
    #
    # Теперь дата берётся из самих цен: у каждой строки прайса есть «Действует
    # с» (date_start), загрузчик ставит туда дату прайса поставщика. Самая
    # свежая из них и есть «Последний прайс». Руками её не правим: дата, не
    # подкреплённая ценами в системе, обманула бы расчёт себестоимости,
    # который берёт цены именно отсюда.
    pmk_price_row_ids = fields.One2many(
        "product.supplierinfo", "partner_id", string="Строки прайса")
    pmk_price_last_date = fields.Date(
        "Последний прайс",
        compute="_compute_pmk_price_last_date",
        store=True,
        help="Дата самого свежего прайса этого поставщика, загруженного в "
             "систему. Берётся из цен поставщика: поле «Действует с».",
    )
    # НЕ ХРАНИТСЯ, и это главное исправление шага 13. Хранимое поле
    # замораживало «сегодня»: у поставщика без прайса в базе навсегда
    # оставалось 20.09 — день, когда поле посчиталось впервые. И считалось оно
    # только от даты прайса, а запрос не учитывало совсем: у Металлсервиса
    # «следующий запрос» 20.09 стоял раньше «последнего» 21.09.
    #
    # Теперь срок идёт от последнего события — отправленного запроса или
    # пришедшего прайса, что свежее, — и по нему же решает рассылка
    # (`_pmk_price_due`). Поставщиков в реестре десятки, поэтому поиск по полю
    # (фильтр «Пора запросить прайс») считается в Python без потерь.
    pmk_price_next_date = fields.Date(
        "Следующий запрос",
        compute="_compute_pmk_price_next_date",
        search="_search_pmk_price_next_date",
        help="Последний запрос плюс периодичность. Прайс, пришедший в ответ "
             "на запрос, срок не сдвигает, а присланный сам по себе — "
             "отодвигает. Не было ни запроса, ни прайса — сегодня. У тех, "
             "кому рассылка пишет сама, здесь день, когда уйдёт письмо: "
             "рассылка ходит по расписанию, раз в неделю.",
    )

    @api.depends("pmk_price_row_ids.date_start")
    def _compute_pmk_price_last_date(self):
        # Одним запросом на всех: загрузчик прайса пишет строки сотнями, и
        # перебор строк по одной на каждую пересчитанную карточку растянул бы
        # заливку.
        latest = dict(self.env["product.supplierinfo"].sudo()._read_group(
            [("partner_id", "in", self.ids), ("date_start", "!=", False)],
            ["partner_id"], ["date_start:max"]))
        for partner in self:
            partner.pmk_price_last_date = latest.get(partner._origin) or False

    def _pmk_price_due_date(self, today):
        """С какого дня пора просить прайс, или False — просить не нужно.

        Отсчёт — от нашего последнего запроса. Прайс, пришедший в ответ на
        него (в пределах периода после запроса), срок НЕ сдвигает: рассылка
        ходит по понедельникам, а прайс датирован днём ответа, и отсчёт от
        него уводил срок со вторника на вторник — очередной понедельник
        оказывался «ещё рано», и двухнедельный запрос уходил раз в три
        недели (разбор проверки шага 13). Прайс, присланный сам по себе —
        позже, чем через период после запроса, или вовсе без запроса, —
        отодвигает срок: свежие цены у нас уже есть.
        """
        self.ensure_one()
        if not self.pmk_price_supplier or self.pmk_price_period_days <= 0:
            return False
        period = relativedelta(days=self.pmk_price_period_days)
        request = _local_date(self.pmk_price_request_date)
        price = self.pmk_price_last_date
        if request and price and request <= price < request + period:
            base = request
        else:
            base = max([d for d in (request, price) if d], default=False)
        if not base:
            # Ни запроса, ни прайса — спрашивать можно сегодня.
            return today
        return base + period

    def _pmk_price_robot_schedule(self):
        """(день ближайшего прогона рассылки, шаг в днях) или None.

        None — рассылка сама не пишет: выключен рубильник или задание, либо
        расписание не в днях и неделях. Тогда срок показываем как есть.
        """
        if self.env["ir.config_parameter"].sudo().get_param(
                "pmk.price_request.enabled", "0") != "1":
            return None
        cron = self.env.ref("pmk_purchase.cron_price_request",
                            raise_if_not_found=False)
        cron = cron and cron.sudo()
        if not cron or not cron.active or not cron.nextcall:
            return None
        step = {"days": 1, "weeks": 7}.get(cron.interval_type, 0) * cron.interval_number
        if step <= 0:
            return None
        return _local_date(cron.nextcall), step

    def _pmk_price_robot_writes(self):
        """Возьмёт ли рассылка этого поставщика — те же условия, что в
        `_cron_send_price_requests`, кроме срока."""
        self.ensure_one()
        return bool(self.pmk_price_supplier and self.pmk_price_mailing
                    and self.pmk_price_email and not self.is_blacklisted
                    and (self.message_bounce or 0) < 3)

    def _pmk_price_next_value(self, today, schedule=None):
        """Дата в колонке «Следующий запрос».

        Кому рассылка пишет сама — день прогона, в который письмо уйдёт:
        первый прогон не раньше срока. Иначе колонка показывала бы «сегодня»
        или «просрочено» всю неделю до понедельника, хотя всё идёт по плану.
        Остальным — сам срок: им писать человеку.
        """
        self.ensure_one()
        due = self._pmk_price_due_date(today)
        if not due or not schedule or not self._pmk_price_robot_writes():
            return due
        run, step = schedule
        if due <= run:
            return run
        return run + relativedelta(days=-(-(due - run).days // step) * step)

    @api.depends("pmk_price_supplier", "pmk_price_period_days",
                 "pmk_price_last_date", "pmk_price_request_date",
                 "pmk_price_mailing", "pmk_price_email")
    def _compute_pmk_price_next_date(self):
        today = _local_today()
        schedule = self._pmk_price_robot_schedule()
        for partner in self:
            partner.pmk_price_next_date = partner._pmk_price_next_value(today, schedule)

    def _search_pmk_price_next_date(self, operator, value):
        compare = {
            "<": lambda d, v: d < v,
            "<=": lambda d, v: d <= v,
            ">": lambda d, v: d > v,
            ">=": lambda d, v: d >= v,
        }
        if operator not in compare and operator != "in":
            # Отрицания («не равно», «не в списке») Odoo соберёт сам через
            # «in»: вернуть NotImplemented — штатный способ это попросить.
            return NotImplemented
        today = _local_today()
        schedule = self._pmk_price_robot_schedule()
        suppliers = self.with_context(active_test=False).search(
            [("pmk_price_supplier", "=", True)])
        dates = {p.id: p._pmk_price_next_value(today, schedule) for p in suppliers}

        if operator == "in":
            wanted = {fields.Date.to_date(v) if v else False for v in value}
            ids = [pid for pid, d in dates.items() if d in wanted]
            if False in wanted:
                # Срока нет и у всех, кто вне реестра прайсов.
                return ["|", ("id", "in", ids), ("pmk_price_supplier", "=", False)]
            return [("id", "in", ids)]

        limit = fields.Date.to_date(value)
        if not limit:
            return [("id", "in", [])]
        return [("id", "in", [pid for pid, d in dates.items()
                              if d and compare[operator](d, limit)])]

    def _pmk_price_due(self, today=None):
        """Пора ли рассылке писать: срок наступил. Срок тот же, что в колонке
        «Следующий запрос», — колонка лишь округляет его до дня прогона."""
        self.ensure_one()
        today = today or _local_today()
        due = self._pmk_price_due_date(today)
        return bool(due) and due <= today

    # ------------------------------------------------------------------
    # действия
    # ------------------------------------------------------------------
    def action_pmk_confirm_price_email(self):
        """Подтвердить адрес и перенести его в основное поле.

        Перенос в `email` — это и есть разрешение писать: до него ни одна
        штатная рассылка Odoo до контрагента не дотянется.
        """
        for partner in self:
            if not partner.pmk_price_email:
                continue
            partner.pmk_price_email_state = "confirmed"
            if not partner.email:
                partner.email = partner.pmk_price_email

    def action_pmk_invalidate_price_email(self):
        """Адрес не работает: снимаем подтверждение и убираем из рассылки."""
        for partner in self:
            partner.pmk_price_email_state = "invalid"
            if partner.email and partner.email == partner.pmk_price_email:
                partner.email = False

    # ------------------------------------------------------------------
    # управление рассылкой руками
    # ------------------------------------------------------------------
    def action_pmk_mailing_on(self):
        """Включить в рассылку. Без адреса включать нечего."""
        without = self.filtered(lambda p: not p.pmk_price_email)
        if without:
            raise UserError(_(
                "Нельзя включить в рассылку без адреса для запроса прайса:\n\n%s",
                "\n".join("— %s" % p.display_name for p in without[:10])))
        self.write({"pmk_price_mailing": True})

    def action_pmk_mailing_off(self):
        self.write({"pmk_price_mailing": False})

    def action_pmk_period_weekly(self):
        self.write({"pmk_price_period_days": 7})

    def action_pmk_period_biweekly(self):
        self.write({"pmk_price_period_days": 14})

    # ------------------------------------------------------------------
    # рассылка
    # ------------------------------------------------------------------
    @api.model
    def _cron_send_price_requests(self):
        """Еженедельный запрос актуальных прайсов.

        Три предохранителя, и каждый снимается отдельно:
          1. рубильник `pmk.price_request.enabled` — пока не '1', ничего не уходит;
          2. флажок «В рассылке» на каждом поставщике — ставит человек;
          3. потолок писем за прогон `pmk.price_request.max_per_run`.

        Письма НЕ отправляются здесь, а кладутся в очередь Odoo
        (`force_send=False`). Разгребает её штатное задание «Mail: Email Queue
        Manager» — снять с него «Активно» значит мгновенно остановить всю
        исходящую почту, письма останутся в очереди.
        """
        ICP = self.env["ir.config_parameter"].sudo()
        if ICP.get_param("pmk.price_request.enabled", "0") != "1":
            _logger.info("Рассылка прайсов выключена: pmk.price_request.enabled != 1")
            return False

        template = self.env.ref(
            "pmk_purchase.mail_template_price_request", raise_if_not_found=False)
        if not template:
            _logger.warning("Шаблон письма запроса прайса не найден")
            return False

        limit = int(ICP.get_param("pmk.price_request.max_per_run", "30") or 30)
        now = fields.Datetime.now()
        today = _local_today()

        candidates = self.search([
            ("pmk_price_supplier", "=", True),
            ("pmk_price_mailing", "=", True),
            ("pmk_price_email", "!=", False),
            # Штатная защита Odoo: чёрный список рассылок и счётчик отказов
            # доставки. Ядро само их не применит — домен наш.
            ("is_blacklisted", "=", False),
            ("message_bounce", "<", 3),
        ])
        # «Последний прайс» хранится и пересчитывается, когда цены меняет ORM.
        # Строки цен, удалённые каскадом в базе (удаление карточки товара,
        # откат заливки) или перенесённые SQL-ом, пересчёта не зовут —
        # перед решением «писать или нет» освежаем дату сами.
        self.env.add_to_compute(self._fields["pmk_price_last_date"], candidates)

        # Срок — тот же, что в колонке «Следующий запрос» (шаг 13 разбора
        # UX). Раньше здесь считались целые сутки между моментами: задание
        # просыпается в 23:10:00 UTC, а отметка прошлого запроса стоит на
        # 23:10:09 — за 14 дней набегало 13 полных суток, и поставщик
        # пропускал срок. Двухнедельный запрос уходил раз в три недели.
        # Теперь сравниваются календарные дни по заводскому времени, и
        # свежий прайс отодвигает запрос: у кого цены только что пришли,
        # того не дёргаем.
        targets = candidates.filtered(lambda p: p._pmk_price_due(today))
        dropped = len(targets) - limit
        targets = targets[:limit]

        sent = 0
        for partner in targets:
            try:
                template.send_mail(
                    partner.id,
                    force_send=False,          # в очередь, а не напрямую
                    email_values={"email_to": partner.pmk_price_email},
                )
            except Exception as exc:           # один сбой не должен рвать прогон
                _logger.warning("Запрос прайса для %s не поставлен в очередь: %s",
                                partner.display_name, exc)
                continue
            # Отметку ставим в той же транзакции, что и письмо: откат снимет оба.
            partner.pmk_price_request_date = now
            sent += 1

        if dropped > 0:
            # Молчаливое усечение читается как «разослали всем» — говорим вслух.
            _logger.info("Запросы прайсов: отложено до следующего прогона %s штук "
                         "(потолок %s за прогон)", dropped, limit)
        _logger.info("Запросы прайсов: поставлено в очередь %s из %s подходящих",
                     sent, len(candidates))
        return sent


class MergePartnerAutomatic(models.TransientModel):
    """Объединение контрагентов переносит строки цен SQL-ом, мимо ORM, и
    «Последний прайс» у оставшейся карточки иначе остался бы прежним."""

    _inherit = "base.partner.merge.automatic.wizard"

    def _merge(self, partner_ids, dst_partner=None, extra_checks=True):
        result = super()._merge(partner_ids, dst_partner=dst_partner,
                                extra_checks=extra_checks)
        survivors = self.env["res.partner"].browse(partner_ids).exists()
        if survivors:
            self.env.add_to_compute(
                survivors._fields["pmk_price_last_date"], survivors)
        return result

