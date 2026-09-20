# -*- coding: utf-8 -*-
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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
        help="Когда мы последний раз просили прайс. По нему считается, "
             "не пора ли спросить снова.",
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
    pmk_price_period_days = fields.Integer(
        "Периодичность, дней",
        default=14,
        help="Как часто просить свежий прайс. Ноль — не просить автоматически.",
    )
    pmk_price_last_date = fields.Date(
        "Последний прайс",
        help="Дата последнего полученного прайса. Заполняется при приёме файла.",
    )
    pmk_price_next_date = fields.Date(
        "Следующий запрос",
        compute="_compute_pmk_price_next_date",
        store=True,
        help="Считается от даты последнего прайса и периодичности.",
    )

    @api.depends("pmk_price_last_date", "pmk_price_period_days", "pmk_price_supplier")
    def _compute_pmk_price_next_date(self):
        for partner in self:
            if not partner.pmk_price_supplier or partner.pmk_price_period_days <= 0:
                partner.pmk_price_next_date = False
                continue
            if not partner.pmk_price_last_date:
                # Прайса ещё не было — запрашивать можно хоть сегодня.
                partner.pmk_price_next_date = fields.Date.context_today(partner)
                continue
            partner.pmk_price_next_date = partner.pmk_price_last_date + relativedelta(
                days=partner.pmk_price_period_days)

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

        candidates = self.search([
            ("pmk_price_supplier", "=", True),
            ("pmk_price_mailing", "=", True),
            ("pmk_price_email", "!=", False),
            # Штатная защита Odoo: чёрный список рассылок и счётчик отказов
            # доставки. Ядро само их не применит — домен наш.
            ("is_blacklisted", "=", False),
            ("message_bounce", "<", 3),
        ])

        def due(partner):
            if not partner.pmk_price_request_date:
                return True
            period = partner.pmk_price_period_days or 0
            if period <= 0:
                return True
            return (now - partner.pmk_price_request_date).days >= period

        targets = candidates.filtered(due)
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
