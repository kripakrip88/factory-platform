# -*- coding: utf-8 -*-
"""Схема связей документов: во что превратилась заявка и где цепочка оборвалась.

ОТКУДА. Форк codeerts_transaction_flow_visualizer (CODEerts, LGPL-3,
19.0.1.0.2). От автора — обход графа в ширину, осторожное чтение полей
(_optional_rel) и цвета штатных состояний. Наше — документы завода, этапы
и человеческая вторая строка узла.

КАК СТРОИТСЯ. Ничего не хранится: при каждом открытии — обход от открытого
документа по связям из _neighbors, от имени текущего пользователя, без sudo.
Чего человек не видит в системе, того нет и на схеме.

СКРЫТОЕ ПРАВАМИ — НЕ ТО ЖЕ, ЧТО ОТСУТСТВУЮЩЕЕ. Документ без прав на схему не
попадает, но сам факт, что связь есть, схема сообщает (restricted). Иначе
технолог без CRM видел бы у расчёта со сделкой «связанных документов нет» —
а это неправда. sudo здесь только считает: ни имени, ни номера скрытого
документа наружу не уходит.

ЭТАПЫ. Колонку на схеме задаёт не расстояние от открытого документа, а место
документа в жизни заказа (словарь _STAGES). Раньше колонка равнялась шагу
обхода, и сделка (шаг назад) вставала в одну колонку с раскроем (шаг вперёд):
выходила звезда вокруг документа, а не цепочка этапов.
"""

from collections import deque

from odoo import api, fields, models
from odoo.exceptions import AccessError

# Разбор «Имя <адрес>» — тот же, что у кнопки «Лид»: pmk_mail_ui в
# зависимостях модуля (поле письма pmk_lead_id).
from odoo.addons.pmk_mail_ui.tools import lead_text

_STATE_COLOR = {
    'draft': 'grey', 'sent': 'grey', 'cancel': 'red',
    'sale': 'blue', 'done': 'green', 'purchase': 'blue',
    'to approve': 'blue', 'confirmed': 'blue', 'progress': 'blue',
    'assigned': 'blue', 'waiting': 'grey', 'posted': 'green',
    'paid': 'green', 'in_payment': 'green', 'not_paid': 'blue',
}

# Место документа в цепочке завода: (ранг колонки, подпись колонки).
#
# Одинаковый ранг — параллельные работы по одному заказу: раскрой проката,
# лазер и производство идут одновременно, а не друг за другом. Пустые ранги
# клиент сжимает, поэтому дыры в нумерации ничего не стоят — их оставляем под
# этапы, которых пока нет (КП отдельным документом, отгрузка).
#
# ⚠️ СЛОВАРЬ — ЕДИНСТВЕННОЕ МЕСТО, ГДЕ ЗАПИСАН ПОРЯДОК ЭТАПОВ. Клиент рисует
# колонки по полю stage узла и своего порядка не знает. Новый документ на
# схеме = строка здесь + ветка в _neighbors.
_STAGES = {
    'mail.client.message': (0, 'Письмо'),
    'crm.lead': (1, 'Сделка'),
    'pmk.metal.spec': (2, 'Расчёт'),
    # Заказ клиента — по-заводски «Счёт покупателю» (шаги 58 и З-2,
    # 08.10.2026): выставляется сам из расчёта при «КП отправлено».
    'sale.order': (3, 'Счёт покупателю'),
    'pmk.cut.plan': (4, 'Раскрой'),
    'pmk.laser.job': (4, 'Лазер'),
    # Доборка — изготовление гнутых планок по сделке, работа цеха рядом с
    # раскроем и лазером (разбор UX, шаг 35: поле «Сделка» у доборки,
    # счётчик «Доборки» на сделке — pmk_deal, dobor_link.py). Вторая строка
    # узла — штатное состояние: Черновик / В работе / Изготовлен.
    'pmk.dobor.order': (4, 'Доборка'),
    'mrp.production': (4, 'Производство'),
    'project.project': (4, 'Проект'),
    'project.task': (4, 'Задача'),
    'purchase.order': (5, 'Закупка'),
    'stock.picking': (6, 'Склад'),
    'account.move': (7, 'Счёт'),
}

# Документы, от которых можно открыть схему. Письмо среди них не для кнопки —
# у письма нет своей формы, — а чтобы обход не спотыкался, если его передадут.
_SUPPORTED_MODELS = tuple(_STAGES)

# Состояние задания лазеру по plan_state — короткими словами.
# ⚠️ ПОДПИСИ СВОИ, А НЕ ИЗ selection: узел пишет их строчными. С шага 36
# разбора UX (02.10.2026) слова те же, что у значков в списке заданий и у
# норматива: «Норматив есть», «Норматив грубый», «Нет норматива», «Рез не
# разобран» (pmk_laser, job.py plan_state и norm.py mode) — одно понятие,
# одно слово.
# ⚠️ ЦВЕТ — ИЗ ЧЕТЫРЁХ ЦВЕТОВ СХЕМЫ, А НЕ ИЗ СПИСКА ЗАДАНИЙ (доводка шага
# 36: прежний комментарий утверждал обратное). У схемы четыре цвета
# (README, «Что написано на узле»): серый — ничего не ясно, синий — в работе,
# зелёный — дошло до результата, красный — дыра. Норматив есть — зелёный,
# грубый — синий («в работе»: планировать можно, норматив уточняется
# замерами), остальное — серое. В списке заданий и «Загрузке» у «Норматив
# грубый» жёлтый тон темы (decoration-warning) — жёлтого у схемы нет; одно
# понятие держит слово, повторённое на обоих. Один цвет везде — решение
# владельца (вопрос в docs/disabled-features.md, шаг 36).
_LASER_PLAN = {
    'ok': ('норматив есть', 'green'),
    'rough': ('норматив грубый', 'blue'),
    'no_norm': ('нет норматива', 'grey'),
    'no_drawing': ('рез не разобран', 'grey'),
}

# Предохранители от запроса «покажи всё». Клиент их не передаёт, но метод
# открыт наружу через RPC, а обход без потолка на связанной базе — это
# полная выборка нескольких таблиц за один клик.
_MAX_DEPTH_CAP = 6
_MAX_NODES_CAP = 200


def _num(value, digits=0):
    """Число по-русски: неразрывный пробел между разрядами, запятая в дроби."""
    text = '{:,.{d}f}'.format(value or 0.0, d=digits)
    return text.replace(',', ' ').replace('.', ',')


def _weight(kg):
    """Вес: до тонны — в килограммах, дальше — в тоннах."""
    if kg >= 1000:
        return '%s т' % _num(kg / 1000.0, 2)
    return '%s кг' % _num(kg)


def _field(record, fname, default=None):
    """Значение поля, если оно есть у модели.

    Цены расчёта объявлены не в калькуляторе, а в мосте номенклатуры
    (pmk_bridge/models/spec_cost.py): без моста их просто нет, и схема
    должна работать и так.
    """
    return record[fname] if fname in record._fields else default


class PmkFlowBuilder(models.AbstractModel):
    _name = 'pmk.flow.builder'
    _description = 'Схема связей документов'

    @api.model
    def _node_id(self, record) -> str:
        return '%s,%s' % (record._name, record.id)

    # ------------------------------------------------------------------
    # Вторая строка узла: состояние документа
    # ------------------------------------------------------------------

    @api.model
    def _state_field(self, record) -> str:
        # A posted invoice is more informative shown by its payment status
        # (paid / in_payment / not_paid) than by the generic 'posted' state.
        if record._name == 'account.move' and record.state == 'posted' \
                and 'payment_state' in record._fields and record.payment_state:
            return 'payment_state'
        for fname in ('state', 'payment_state'):
            if fname in record._fields:
                return fname
        return ''

    @api.model
    def _state_label(self, record, fname, raw) -> str:
        """Human-readable, translated label for a selection value."""
        if not fname or not raw:
            return ''
        selection = dict(record.fields_get([fname])[fname].get('selection') or [])
        return selection.get(raw, raw)

    @api.model
    def _std_state(self, record):
        """Состояние штатного документа Odoo — как было у автора модуля."""
        fname = self._state_field(record)
        raw = record[fname] if fname else ''
        return self._state_label(record, fname, raw), _STATE_COLOR.get(raw, 'grey')

    @api.model
    def _pmk_state(self, record):
        """Состояние документа завода: (текст, цвет) или None для штатных.

        ⚠️ ПОЛЯ state У НАШИХ ДОКУМЕНТОВ НЕТ. У расчёта его нет вовсе, у
        раскроя тоже, у задания лазеру вместо него plan_state/measure_state.
        Штатная ветка без этой функции красила их серым и оставляла вторую
        строку пустой — узел не говорил ничего, кроме номера.

        Цвета строго из четырёх: серый — ещё ничего не ясно, синий — в
        работе, зелёный — дошло до результата, красный — есть дыра, которую
        надо закрыть человеку.
        """
        model = record._name
        if model == 'pmk.metal.spec':
            # Порядок проверок — по тяжести. Цена клиенту при неполной
            # закупке всё равно красная: себестоимость занижена, и КП по ней
            # отправлять нельзя (решение владельца 24.09.2026).
            missing = _field(record, 'no_price_count', 0)
            if _field(record, 'price_incomplete') or missing:
                return 'нет цен: %d' % missing, 'red'
            customer = _field(record, 'price_customer_total', 0.0)
            if customer > 0:
                return 'цена клиенту %s ₽' % _num(customer), 'green'
            metal = _field(record, 'total_cost_fact', 0.0)
            if metal:
                return 'металл %s ₽' % _num(metal), 'blue'
            if record.total_weight:
                return 'вес %s' % _weight(record.total_weight), 'grey'
            return 'пустой', 'grey'

        if model == 'pmk.cut.plan':
            # Без результата отход равен нулю — и «отход 0%» читался бы как
            # идеальный раскрой, хотя его просто не считали.
            if not record.result_ids:
                return 'не посчитан', 'grey'
            if record.has_unplaced:
                return 'есть неразмещённые', 'red'
            return 'отход %s%%' % _num(record.waste_ratio, 1), 'blue'

        if model == 'pmk.laser.job':
            # Сломанный баланс важнее любого норматива: он значит, что
            # обрезки оприходованы с ошибкой, а это металл и деньги.
            if record.balance_broken:
                return 'баланс не сходится', 'red'
            return _LASER_PLAN.get(record.plan_state, ('', 'grey'))

        if model == 'crm.lead':
            # won_status считает само ядро CRM (выиграна по стадии, проиграна
            # по архиву с нулевой вероятностью) — не повторяем его правило.
            status = _field(record, 'won_status')
            stage = record.stage_id.name or ''
            if status == 'lost':
                return 'проиграна', 'red'
            if status == 'won':
                return stage or 'выиграна', 'green'
            if record.type == 'lead':
                return stage or 'лид', 'grey'
            return stage or 'без стадии', 'blue'

        if model == 'mail.client.message':
            if record.date:
                local = fields.Datetime.context_timestamp(record, record.date)
                return 'письмо от %s' % local.strftime('%d.%m.%Y'), 'grey'
            return 'письмо', 'grey'

        return None

    @api.model
    def _hint(self, record, kind, state) -> str:
        """Подсказка при наведении: полное имя и от кого документ.

        В узле имя режется по ширине, а тема письма или название сделки
        бывают длинными — целиком они видны только здесь.
        """
        lines = ['%s: %s' % (kind, record.display_name or '—')]
        if state:
            lines.append(state)
        partner = _field(record, 'partner_id')
        if partner:
            lines.append(partner.display_name)
        elif _field(record, 'email_from'):
            lines.append(record.email_from)
        return '\n'.join(lines)

    @api.model
    def _letter_label(self, record):
        """Первая строка узла письма — от кого, а не тема (разбор UX, шаг 27).

        Лид из письма называется по его теме — с шага 27 ещё и без «RE:», —
        и на «Связях» рядом стояли два одинаковых узла «Запрос стоимости
        изготов…»: «Письмо» и «Сделка» (ночной осмотр 29.09, СМ-00024). Тема
        осталась в подсказке при наведении (_hint), дата — второй строкой
        («письмо от 16.09.2026»). Имя — из «Имя <адрес>» отправителя (те же
        правила, что у кнопки «Лид», pmk_mail_ui/tools/lead_text.py); нет
        имени — карточка контакта, адрес, тема.
        """
        name, address = lead_text.split_sender(record.email_from or '')
        if not name:
            try:
                partner = _field(record, 'partner_id')
                name = partner.name if partner else ''
            except AccessError:
                # Карточка контакта под правами — обойдёмся адресом.
                name = ''
        return name or address or record.subject or '(без темы)'

    @api.model
    def _open_target(self, record):
        """Какую запись открывать кликом по узлу, если у узла нет open_action.

        ⚠️ У ПИСЬМА СВОЕЙ ФОРМЫ НЕТ. Автоформу Odoo, собранную из всех полей,
        открывать НЕЛЬЗЯ: в ней оказалось бы body_html, которое почтовый
        модуль хранит без очистки и чистит только на отдаче (см. pmk_mail_ui,
        _pmk_create_lead). С шага 53 письмо открывается в самой почте
        (_letter_action: окно почты чистит письмо на отдаче, как всегда), а
        лид здесь — запасной путь, если почты нет: туда при создании лида
        письмо переложено целиком, с вложениями.
        """
        if record._name == 'mail.client.message':
            # Лид, который человек не может открыть, — не цель для клика:
            # узел останется на схеме, но переход вёл бы в ошибку доступа.
            return self._optional_rel(record, 'pmk_lead_id')._filtered_access('read')
        return record

    @api.model
    def _node_for(self, record) -> dict:
        rank, kind = _STAGES.get(record._name, (99, record._description or record._name))
        try:
            state, color = self._pmk_state(record) or self._std_state(record)
            hint = self._hint(record, kind, state)
        except AccessError:
            # Документ виден, а поле для второй строки — нет (стадия, партнёр
            # под группой). Лучше узел без подписи, чем схема, упавшая целиком.
            state, color, hint = '', 'grey', kind
        target = self._open_target(record)
        open_action = False
        if record._name == 'mail.client.message':
            label = self._letter_label(record)
            open_action = self._letter_action(record)
            if open_action:
                hint = '%s\nЩелчок — письмо в почте' % hint
            elif target:
                hint = '%s\nЩелчок откроет сделку: этого письма нет в вашей почте' % hint
        else:
            label = record.display_name or '—'
        return {
            'id': self._node_id(record),
            'model': record._name,
            'res_id': record.id,
            'label': label,
            'state': state,
            'color': color,
            'kind': kind,
            'stage': rank,
            'hint': hint,
            'open_model': target._name if target else False,
            'open_res_id': target.id if target else False,
            # Действие клиента вместо формы записи (письмо — окно почты).
            # Есть — клиент открывает его, open_model / open_res_id остаются
            # запасным путём на случай старого клиента.
            'open_action': open_action,
        }

    @api.model
    def _letter_action(self, record):
        """Окно почты, открытое на этом письме (разбор UX, шаг 53).

        Клик по «Письму» на «Связях» вёл в лид, а лид — та же запись, что
        потом становится сделкой: человек жал «Письмо» и попадал в сделку.
        Теперь — «Продажи → Почта» (действие pmk_mail_ui.action_mail_sale:
        там и кнопка «Лид», и доступ к ней по правам) с номером письма в
        params: почта сама выберет его папку и откроет письмо
        (pmk_mail_ui/static/src/js/step53_open.js). Показ письма — штатное
        окно почты, тело очищено на отдаче, как при обычном открытии.

        Почта не может показать письмо — False: клик ведёт по-старому в
        лид, подсказка узла говорит об этом. Так, если действия нет
        (pmk_mail_ui без меню) и если папки письма нет в дереве почты
        человека (pmk_mail_ui, _pmk_tree_folder_id): ящик чужой или папка не
        подписана — письмо перенесли на mail.ru в папку, которой в Odoo нет.
        Иначе почта молча открылась бы на «Входящих» без письма.
        """
        if not record._pmk_tree_folder_id():
            return False
        try:
            action = self.env['ir.actions.actions']._for_xml_id('pmk_mail_ui.action_mail_sale')
        except (ValueError, AccessError):
            return False
        action = dict(action)
        action['params'] = dict(action.get('params') or {}, pmk_message_id=record.id)
        return action

    # ------------------------------------------------------------------
    # Связи
    # ------------------------------------------------------------------

    @api.model
    def _optional_rel(self, record, fname, hidden=None):
        """Read an OPTIONAL relation, tolerating a field this user is not allowed to read.

        `fname in record._fields` proves the field EXISTS, not that the current user may READ it. A field
        declared with `groups=` raises AccessError on access for anyone outside those groups, so the
        presence test is not a sufficient guard. The Flow Map is a read-only overview: a relation the user
        cannot see is left out of the graph, which is what they would see anyway. Returns an EMPTY
        recordset (never None) so every caller can append unconditionally.

        hidden — список-копилка из _neighbors: сюда пишется, что связь скрыта
        правами. ⚠️ ТОЛЬКО ЕСЛИ ПОЛЕ НЕ ПУСТОЕ. Закрытое группой поле ещё не
        значит, что за ним что-то есть: project_ids закрыт для всех вне
        Проектов, и без проверки через sudo каждый заказ у такого человека
        жаловался бы на скрытые связи, которых нет.
        """
        field = record._fields.get(fname)
        if field is None:
            return record.browse()
        try:
            return record[fname]
        except AccessError:
            if hidden is not None and record.sudo()[fname]:
                hidden.append(record._name + '.' + fname)
            comodel = getattr(field, 'comodel_name', None)
            return self.env[comodel].browse() if comodel else record.browse()

    @api.model
    def _search_linked(self, model_name, domain, hidden=None):
        """Документы модели model_name по domain — те, что человек может читать.

        ⚠️ ПРАВО НА МОДЕЛЬ ПРОВЕРЯЕТСЯ ДО ПОИСКА. search от имени человека без
        прав на модель падает AccessError, а таких людей на заводе большинство:
        у технолога нет почты и CRM. Обычный случай, а не авария — поиск
        пропускаем.

        Но «не нашли» и «не имеете права видеть» — разные ответы. search
        молча отбрасывает и то, что закрыто правилами записей (чужой почтовый
        ящик, «только свои» заказы). Поэтому тот же поиск считаем через sudo:
        если там больше, связи есть, но скрыты, — отмечаем в hidden. limit —
        чтобы не пересчитывать тысячи, когда достаточно знать «больше или нет».
        """
        if model_name not in self.env:
            return []
        Model = self.env[model_name]
        found = Model.search(domain) if Model.has_access('read') else Model.browse()
        if hidden is not None and \
                Model.sudo().search_count(domain, limit=len(found) + 1) > len(found):
            hidden.append(model_name)
        return found

    @api.model
    def _referrers(self, model_name, fname, record_id, hidden=None):
        """Документы модели model_name, которые ссылаются на record_id полем fname.

        Права и скрытые связи — в _search_linked. Модуля может не быть вовсе
        (проекты), и поля тоже — например, ссылки лазера на расчёт до
        обновления pmk_laser: тогда связей этого вида действительно нет.
        """
        if model_name not in self.env or fname not in self.env[model_name]._fields:
            return []
        return self._search_linked(model_name, [(fname, '=', record_id)], hidden)

    @api.model
    def _neighbors(self, record):
        """Соседи документа: (список видимых записей, есть ли скрытые правами)."""
        model = record._name
        linked = []
        # Копилка скрытых связей: что в ней — неважно, важно, что не пусто.
        hidden = []
        if model == 'sale.order':
            if 'invoice_ids' in record._fields:
                linked.append(record.invoice_ids)
            if 'picking_ids' in record._fields:
                linked.append(record.picking_ids)
            if hasattr(record, '_get_purchase_orders'):
                linked.append(record._get_purchase_orders())
            # Optional: lights up only when sale_project is installed.
            # Read these via _optional_rel, NEVER directly. Core declares them with `groups=`, so a direct
            # read raises AccessError for anyone outside Project: `project_ids` on every supported version,
            # and `tasks_ids` from 19.0 onward (17.0/18.0 sale_project declare it without `groups=`).
            linked.append(self._optional_rel(record, 'project_ids', hidden))
            linked.append(self._optional_rel(record, 'tasks_ids', hidden))
            # Наше: заказ ← сделка (поле sale_crm) и заказ → задания лазеру.
            linked.append(self._optional_rel(record, 'opportunity_id', hidden))
            linked.append(self._referrers('pmk.laser.job', 'sale_order_id', record.id, hidden))
            # Шаг З-2 (pmk_orders): счёт ← расчёт, счёт → строка «Заказов в
            # работе». Полей нет без pmk_orders — _optional_rel/_referrers
            # это переносят. Прежние редакции на схеме не показываем: у них
            # нет сделки, а к расчёту ведёт только действующий счёт.
            linked.append(self._optional_rel(record, 'pmk_spec_id', hidden))
            linked.append(self._referrers('project.task', 'pmk_sale_order_id', record.id, hidden))
        elif model == 'project.project':
            if 'sale_order_id' in record._fields and record.sale_order_id:
                linked.append(record.sale_order_id)
            if 'task_ids' in record._fields:
                linked.append(record.task_ids)
        elif model == 'project.task':
            if 'sale_order_id' in record._fields and record.sale_order_id:
                linked.append(record.sale_order_id)
            if 'project_id' in record._fields and record.project_id:
                linked.append(record.project_id)
            # Строка «Заказов в работе» (pmk_orders, шаг З-2): свой счёт и сделка.
            linked.append(self._optional_rel(record, 'pmk_sale_order_id', hidden))
            linked.append(self._optional_rel(record, 'pmk_deal_id', hidden))
        elif model == 'purchase.order':
            if 'invoice_ids' in record._fields:
                linked.append(record.invoice_ids)
            if 'picking_ids' in record._fields:
                linked.append(record.picking_ids)
            if hasattr(record, '_get_sale_orders'):
                linked.append(record._get_sale_orders())
        elif model == 'mrp.production':
            if 'sale_line_id' in record._fields:
                linked.append(record.sale_line_id.order_id)
            if 'move_finished_ids' in record._fields:
                linked.append(record.move_finished_ids.move_dest_ids.picking_id)
            if 'move_raw_ids' in record._fields:
                linked.append(record.move_raw_ids.move_orig_ids.picking_id)
        elif model == 'stock.picking':
            if 'sale_id' in record._fields and record.sale_id:
                linked.append(record.sale_id)
            if 'purchase_id' in record._fields and record.purchase_id:
                linked.append(record.purchase_id)
        elif model == 'account.move':
            # The id MUST be wrapped in a list. `invoice_ids` is a computed field with a custom search
            # method; 19.0 survives a bare int only because odoo/orm/domains.py:1314-1317 quietly wraps a
            # non-collection value and logs "should have a list value". On 17.0/18.0 there is no such
            # normalisation and sale/models/sale_order.py feeds it straight to list(value), so a bare int
            # raised TypeError: 'int' object is not iterable and the Flow Map died on any invoice.
            linked.append(self._search_linked(
                'sale.order', [('invoice_ids', 'in', [record.id])], hidden))
            linked.append(self._search_linked(
                'purchase.order', [('invoice_ids', 'in', [record.id])], hidden))

        # ─── Документы завода ────────────────────────────────────────────
        elif model == 'mail.client.message':
            # Письмо знает свой лид: поле ставит кнопка «Создать лида»
            # (pmk_mail_ui/models/mail_client_message.py).
            linked.append(self._optional_rel(record, 'pmk_lead_id', hidden))
        elif model == 'crm.lead':
            # Письма, из которых сделан лид. Лиды, пришедшие на алиас zakaz@
            # без кнопки, этой ссылки не имеют — их письмо лежит в чате лида.
            linked.append(self._referrers('mail.client.message', 'pmk_lead_id', record.id, hidden))
            # Расчёты металлопроката висят на сделке (модуль pmk_deal).
            linked.append(self._optional_rel(record, 'spec_ids', hidden))
            # Доборки — тоже (pmk_deal, шаг 35): счётчик «Доборки» над формой
            # и схема на вкладке «Связи» говорят одно и то же.
            linked.append(self._optional_rel(record, 'dobor_ids', hidden))
            # Заказы клиента из сделки (sale_crm). Поле opportunity_id у
            # заказа появляется только с sale_crm — отсюда проверка поля.
            linked.append(self._referrers('sale.order', 'opportunity_id', record.id, hidden))
            # Строки «Заказов в работе» сделки (pmk_orders, шаг З-2) — и те,
            # что появились без счёта.
            linked.append(self._referrers('project.task', 'pmk_deal_id', record.id, hidden))
        elif model == 'pmk.metal.spec':
            linked.append(self._optional_rel(record, 'opportunity_id', hidden))
            # Счёт покупателю из расчёта (pmk_orders, шаг З-2) — только
            # действующий: прежние редакции хранят тот же расчёт.
            if 'sale.order' in self.env and 'pmk_is_revision' in self.env['sale.order']._fields:
                linked.append(self._search_linked(
                    'sale.order', [('pmk_spec_id', '=', record.id), ('pmk_is_revision', '=', False)],
                    hidden))
            # Раскрой сортамента ссылается на расчёт полем «Расчёт» (spec_id).
            linked.append(self._referrers('pmk.cut.plan', 'spec_id', record.id, hidden))
            # Задание лазеру ссылается на расчёт с 27.09.2026 (pmk_laser, spec_id).
            linked.append(self._referrers('pmk.laser.job', 'spec_id', record.id, hidden))
        elif model == 'pmk.cut.plan':
            linked.append(self._optional_rel(record, 'spec_id', hidden))
        elif model == 'pmk.dobor.order':
            # Доборка знает свою сделку (pmk_deal, шаг 35).
            linked.append(self._optional_rel(record, 'opportunity_id', hidden))
        elif model == 'pmk.laser.job':
            linked.append(self._optional_rel(record, 'spec_id', hidden))
            linked.append(self._optional_rel(record, 'sale_order_id', hidden))

        seen, out = set(), []
        for rs in linked:
            # ⚠️ ФИЛЬТР ПО ПРАВАМ ОБЯЗАТЕЛЕН И ДЛЯ ССЫЛОК. Прочитать поле
            # «Сделка» у расчёта может любой, а вот имя самой сделки человек
            # без CRM прочитать не может — и display_name узла уронил бы всю
            # схему. Отсекаем здесь, одним местом для всех веток. Отсечённое
            # отмечаем: связь есть, её просто не показать.
            # Разность, а не сравнение длин: _filtered_access возвращает
            # набор без повторов, и повтор в rs выглядел бы как скрытая запись.
            if isinstance(rs, models.BaseModel) and rs:
                allowed = rs._filtered_access('read')
                if rs - allowed:
                    hidden.append(rs._name)
                rs = allowed
            for rec in rs:
                key = (rec._name, rec.id)
                if not rec.id or key in seen or (rec._name == model and rec.id == record.id):
                    continue
                seen.add(key)
                out.append(rec)
        return out, bool(hidden)

    @api.model
    def get_flow_graph(self, res_model, res_id, max_depth: int = 4,
                       max_nodes: int = 60) -> dict:
        """Узлы и связи вокруг документа.

        Глубина 4, а не 3, как у автора: цепочка завода длиннее штатной.
        От расчёта до писем — два шага (расчёт → сделка → письмо), до
        соседнего расчёта той же сделки и его раскроя — три. С тремя
        уровнями раскрой соседнего расчёта обрезался бы молча.
        """
        empty = {'nodes': [], 'edges': [], 'truncated': False, 'restricted': False}
        # Модель из словаря может быть не установлена (проекты) — тогда и
        # документа такого нет, и схемы тоже.
        if res_model not in _SUPPORTED_MODELS or res_model not in self.env:
            return empty
        max_depth = max(0, min(int(max_depth), _MAX_DEPTH_CAP))
        max_nodes = max(1, min(int(max_nodes), _MAX_NODES_CAP))
        anchor = self.env[res_model].browse(res_id).exists()
        if not anchor:
            return empty
        nodes, edges, edge_seen = {}, [], set()
        truncated = restricted = False
        nodes[self._node_id(anchor)] = self._node_for(anchor)
        frontier = deque([(anchor, 0)])
        while frontier:
            record, depth = frontier.popleft()
            if depth >= max_depth:
                continue
            try:
                neighbours, hidden = self._neighbors(record)
            except AccessError:
                # Штатные ветки ходят по складским движениям и счетам. Кто к
                # ним не допущен, увидит схему без этого куска — и пометку,
                # что кусок скрыт правами, а не отсутствует.
                restricted = True
                continue
            if hidden:
                restricted = True
            for neigh in neighbours:
                nid = self._node_id(neigh)
                ekey = tuple(sorted((self._node_id(record), nid)))
                if ekey not in edge_seen:
                    edge_seen.add(ekey)
                    edges.append({'from': self._node_id(record), 'to': nid})
                if nid not in nodes:
                    if len(nodes) >= max_nodes:
                        truncated = True
                        continue
                    nodes[nid] = self._node_for(neigh)
                    frontier.append((neigh, depth + 1))
        valid = set(nodes)
        edges = [e for e in edges if e['from'] in valid and e['to'] in valid]
        return {
            'nodes': list(nodes.values()),
            'edges': edges,
            'truncated': truncated,
            'restricted': restricted,
        }
