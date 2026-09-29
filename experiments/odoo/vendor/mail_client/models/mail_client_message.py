# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
import logging
import re
from datetime import datetime, timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools.mail import email_normalize, html_sanitize, plaintext2html

from ..tools import bodystructure
from ..tools.imap_client import ImapError

_logger = logging.getLogger(__name__)

# Rewrites remote asset URLs so the browser never requests them. Tracking
# pixels are the reason; the user can opt in per message.
#
# Attributes are only half the story: newsletters routinely pull images through
# CSS instead, and a block that stops <img src> but not
# style="background-image:url(...)" still tells the sender the mail was opened.
# Deliberately not anchored on the opening "<": re.sub resumes scanning after
# each match, so anchoring on the tag start would block only the *first*
# remote attribute per tag and let <img srcset=... src=...> through.
_RE_REMOTE_ATTR = re.compile(
    r'(\s)(src|srcset|background|poster)(\s*=\s*["\']\s*https?://)',
    re.IGNORECASE,
)
_RE_REMOTE_CSS_URL = re.compile(
    r'url\(\s*["\']?\s*https?://[^)"\']*["\']?\s*\)',
    re.IGNORECASE,
)
_RE_MESSAGE_ID = re.compile(r'<[^>]+>')
_RE_EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')

# ПРАВКА ПМК (шаг 18, Г10): «ждёт ответа / ждём клиента» — только по письмам
# последних AWAITING_DAYS дней (решение владельца 30.09.2026: 7 дней). Без
# окна «ждёт ответа» — 1218 переписок из 1779, то есть вся история ящика.
AWAITING_DAYS = 7
# Роботы ответа не ждут: уведомления, отказы доставки.
_RE_ROBOT = re.compile(r'no-?reply|mailer-daemon', re.IGNORECASE)


class MailClientMessage(models.Model):
    _name = 'mail.client.message'
    _description = 'Mail Client Message'
    _order = 'date desc, id desc'
    _rec_name = 'subject'

    account_id = fields.Many2one(
        'mail.client.account', required=True, ondelete='cascade', index=True,
    )
    folder_id = fields.Many2one(
        'mail.client.folder', required=True, ondelete='cascade', index=True,
    )
    imap_uid = fields.Integer(required=True, index=True)

    message_id = fields.Char(index=True)
    thread_key = fields.Char(index=True)
    subject = fields.Char()
    date = fields.Datetime(index=True)
    size = fields.Integer()

    email_from = fields.Char(index=True)
    email_to = fields.Text()
    email_cc = fields.Text()
    partner_id = fields.Many2one('res.partner', ondelete='set null', index=True)

    preview = fields.Char()
    body_html = fields.Html(sanitize=False, sanitize_attributes=False)
    body_state = fields.Selection(
        [('header_only', 'Headers only'), ('fetched', 'Fetched'), ('failed', 'Failed')],
        default='header_only', required=True, index=True,
    )
    has_attachment = fields.Boolean()
    images_allowed = fields.Boolean(
        help="Whether remote images in this message may be loaded.",
    )

    flag_seen = fields.Boolean(index=True)
    flag_flagged = fields.Boolean()
    flag_answered = fields.Boolean()
    flag_draft = fields.Boolean()
    flag_deleted = fields.Boolean()

    spam_score = fields.Float()
    is_spam = fields.Boolean()

    references = fields.Char(help="Raw References header, used to thread replies.")
    tag_ids = fields.Many2many('mail.client.tag', string='Tags')
    client_attachment_ids = fields.One2many(
        'mail.client.attachment', 'message_id', string='Attachments',
    )
    structure_state = fields.Selection(
        [('unknown', 'Not inspected'), ('parsed', 'Parsed'), ('failed', 'Failed')],
        default='unknown', required=True,
        help="Whether the MIME structure has been read from the server yet.",
    )
    is_dirty = fields.Boolean(
        help="Set while a local change is still waiting to reach the server.",
    )

    _uid_folder_uniq = models.Constraint(
        'UNIQUE(folder_id, imap_uid)',
        "A message with this UID already exists in this folder.",
    )

    def init(self):
        # Composite indexes the ORM will not create on its own but that every
        # list query depends on.
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS mail_client_message_folder_date_idx
                ON mail_client_message (folder_id, date DESC);
            CREATE INDEX IF NOT EXISTS mail_client_message_account_msgid_idx
                ON mail_client_message (account_id, message_id);
        """)

    # ------------------------------------------------------------------
    @api.model
    def _compute_thread_key_value(self, entry):
        """Derive a stable conversation key from the RFC 5322 reference chain.

        Never returns empty: grouping by a NULL key would collapse every
        message that lacks headers into one enormous fake conversation.
        """
        references = _RE_MESSAGE_ID.findall(entry.get('references') or '')
        if references:
            return references[0][:255]
        in_reply_to = _RE_MESSAGE_ID.findall(entry.get('in_reply_to') or '')
        if in_reply_to:
            return in_reply_to[0][:255]
        message_id = (entry.get('message_id') or '').strip()
        if message_id:
            return message_id[:255]
        # No usable headers at all: keep the message in a conversation of its own.
        return 'uid:%s' % entry.get('uid', 0)

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        messages._resolve_partners()
        return messages

    def _resolve_partners(self):
        """Best-effort match of the sender against an existing contact."""
        Partner = self.env['res.partner']
        for message in self:
            if message.partner_id or not message.email_from:
                continue
            match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', message.email_from)
            if not match:
                continue
            partner = Partner.search([('email', '=ilike', match.group(0))], limit=1)
            if partner:
                message.partner_id = partner

    # ------------------------------------------------------------------
    # body
    # ------------------------------------------------------------------
    def _fetch_body(self):
        """Download the body of a header-only message, plus its part list.

        Only the text parts are transferred: BODYSTRUCTURE tells us which part
        numbers they are, so a message with a 20 MB attachment costs a couple
        of kilobytes to read.
        """
        self.ensure_one()
        # The body and the MIME structure are two separate things. A message
        # read before attachments were supported has a body but no part list,
        # and short-circuiting on body_state alone would leave it that way
        # forever - its attachments would stay permanently unreachable.
        needs_body = self.body_state != 'fetched'
        needs_structure = self.structure_state != 'parsed'
        if not needs_body and not needs_structure:
            return True

        connection = None
        try:
            connection = self.account_id._open_connection()
            connection.select(self.folder_id.imap_path, readonly=True)
            parts = connection.fetch_structure(self.imap_uid)
            html, text = self._fetch_text_parts(connection, parts) if needs_body else ('', '')
        except (ImapError, UserError) as exc:
            _logger.warning("Mail Client: body fetch failed for UID %s: %s", self.imap_uid, exc)
            self.write({
                'body_state': 'failed' if needs_body else self.body_state,
                'structure_state': 'failed',
            })
            return False
        finally:
            if connection:
                connection.close()

        attachments = bodystructure.attachments(parts)
        values = {'structure_state': 'parsed', 'has_attachment': bool(attachments)}
        if needs_body:
            if html:
                values['body_html'] = html_sanitize(html)
            elif text:
                values['body_html'] = plaintext2html(text)
            else:
                values['body_html'] = ''
            values['preview'] = self._build_preview(text or html)
            values['body_state'] = 'fetched'

        self.write(values)
        self._sync_attachment_records(attachments)
        return True

    def _fetch_text_parts(self, connection, parts):
        """Download only the displayable parts described by BODYSTRUCTURE."""
        self.ensure_one()
        html_part, text_part = bodystructure.pick_body_parts(parts)
        if not html_part and not text_part:
            # Not a MIME message, or nothing recognisable: fall back to the
            # whole body rather than showing the user a blank pane.
            html, text, _has_attachment = connection.fetch_body(self.imap_uid)
            return html, text

        def _download(part):
            if not part:
                return ''
            raw = connection.fetch_part(
                self.imap_uid, part['part_number'], part['encoding'],
            )
            charset = part.get('charset') or 'utf-8'
            try:
                return raw.decode(charset, errors='replace')
            except LookupError:
                return raw.decode('utf-8', errors='replace')

        return _download(html_part), _download(text_part)

    def _sync_attachment_records(self, parts):
        """Record the attachment list without downloading any of it."""
        self.ensure_one()
        Attachment = self.env['mail.client.attachment'].sudo()
        existing = {a.part_number: a for a in self.client_attachment_ids}
        values_list = []
        for sequence, part in enumerate(parts, start=10):
            if part['part_number'] in existing:
                continue
            values_list.append({
                'message_id': self.id,
                'sequence': sequence,
                'name': part['filename'] or _("part %s", part['part_number']),
                'part_number': part['part_number'],
                'content_type': part['content_type'],
                'encoding': part['encoding'],
                'file_size': part['size'],
            })
        if values_list:
            Attachment.create(values_list)

    def _quoted_body(self):
        """Return this message wrapped as a quotation, for replies."""
        self.ensure_one()
        header = _(
            "On %(date)s, %(sender)s wrote:",
            date=self.date and fields.Datetime.to_string(self.date) or '',
            sender=self.email_from or '',
        )
        return Markup(
            '<p><br/></p><p>%s</p><blockquote style="margin:0 0 0 .8ex;'
            'border-left:2px solid #ccc;padding-left:1ex;">%s</blockquote>'
        ) % (header, Markup(self.body_html or ''))

    # ------------------------------------------------------------------
    # mutations
    # ------------------------------------------------------------------
    def _set_flag(self, flag, value):
        """Apply a flag locally and queue it for the server.

        The local write happens first so the interface reacts immediately; the
        outbox carries the change to IMAP on the next sync.
        """
        field_by_flag = {
            '\\Seen': 'flag_seen',
            '\\Flagged': 'flag_flagged',
            '\\Answered': 'flag_answered',
        }
        field = field_by_flag.get(flag)
        for message in self:
            if field:
                message.sudo().write({field: value, 'is_dirty': True})
            if message.account_id.sync_mode == 'two_way':
                self.env['mail.client.sync.op'].queue(
                    message, 'set_flag' if value else 'unset_flag', {'flags': [flag]},
                )
        return True

    def _set_tag(self, tag, value):
        """Apply or remove a tag locally and queue the keyword for the server."""
        self.ensure_one()
        if tag.account_id != self.account_id:
            raise UserError(_("That tag belongs to a different mailbox."))

        command = fields.Command.link(tag.id) if value else fields.Command.unlink(tag.id)
        self.sudo().write({'tag_ids': [command], 'is_dirty': True})
        if self.account_id.sync_mode == 'two_way':
            self.env['mail.client.sync.op'].queue(
                self,
                'set_flag' if value else 'unset_flag',
                {'flags': [tag.imap_keyword]},
            )
        return True

    def _check_two_way(self, action):
        """Refuse a mutation that cannot be carried to the server.

        Only the outbox entry used to be gated on the sync mode, while the
        local unlink below happened either way. On a read-only account that
        removed the message from Odoo and left it untouched on the server - and
        because the folder resumes from ``uid_next``, its UID is never fetched
        again. The mail was simply gone from Odoo, permanently, with no trace
        of why. Read-only means read-only in both directions.
        """
        self.ensure_one()
        if self.account_id.sync_mode != 'two_way':
            raise UserError(_(
                "'%(email)s' is set to read only, so %(action)s here would remove "
                "the message from Odoo without touching the mail server - and it "
                "would not come back.\n\n"
                "Set this mailbox's Sync Mode to Two-way to act on mail from Odoo.",
                email=self.account_id.email, action=action,
            ))

    def _move_to(self, folder):
        self.ensure_one()
        if folder == self.folder_id:
            return False
        self._check_two_way(_("moving mail"))
        self.env['mail.client.sync.op'].queue(
            self, 'move', {'target_path': folder.imap_path, 'target_folder_id': folder.id},
        )
        # Reflect the move locally straight away. The UID belongs to the old
        # folder, so it is cleared: the next sync of the target folder will
        # create the message again with its real UID there.
        self.sudo().unlink()
        return True

    def _delete(self):
        """Move to Trash, or expunge when already there."""
        self.ensure_one()
        trash = self.account_id.folder_ids.filtered(lambda f: f.role == 'trash')[:1]
        if trash and self.folder_id != trash:
            return self._move_to(trash)

        self._check_two_way(_("deleting mail"))
        self.env['mail.client.sync.op'].queue(self, 'delete', {})
        self.sudo().unlink()
        return True

    @staticmethod
    def _build_preview(raw):
        if not raw:
            return False
        text = re.sub(r'<[^>]+>', ' ', raw)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:255] or False

    @api.model
    def _has_remote_assets(self, html):
        if not html:
            return False
        return bool(_RE_REMOTE_ATTR.search(html) or _RE_REMOTE_CSS_URL.search(html))

    @api.model
    def _block_remote_assets(self, html):
        """Neutralise every way an email can pull an image off the network.

        The stored body is never modified, so allowing images later simply
        renders the original again.
        """
        blocked = _RE_REMOTE_ATTR.sub(r'\1data-blocked-\2\3', html)
        return _RE_REMOTE_CSS_URL.sub('url(about:blank)', blocked)

    def _display_body(self):
        """Return the body as it should be rendered, with remote assets handled."""
        self.ensure_one()
        body = self.body_html or ''
        if not body:
            return ''
        if not self.images_allowed:
            body = self._block_remote_assets(body)
        return body

    # ------------------------------------------------------------------
    # client action RPC
    # ------------------------------------------------------------------
    def _to_list_payload(self):
        """Compact representation for the middle pane.

        ПРАВКА ПМК (шаг 18): ``email_to`` (первые 512 знаков) и
        ``is_outgoing`` — у нашего письма строка показывает «Кому: …», а не
        себя отправителем («Владимир Голубенко» на каждой строке
        «Отправленных»).
        """
        return [{
            'id': message.id,
            'subject': message.subject or _("(no subject)"),
            'email_from': message.email_from or '',
            'email_to': (message.email_to or '')[:512],
            'is_outgoing': message._is_outgoing(),
            'date': message.date and fields.Datetime.to_string(message.date),
            'preview': message.preview or '',
            'flag_seen': message.flag_seen,
            'flag_flagged': message.flag_flagged,
            'flag_answered': message.flag_answered,
            'has_attachment': message.has_attachment,
            'is_spam': message.is_spam,
            'partner_id': message.partner_id.id or False,
            'partner_name': message.partner_id.display_name or '',
        } for message in self]

    def _is_outgoing(self):
        """ПРАВКА ПМК (шаг 18): письмо наше — лежит в «Отправленных» или
        «Черновиках» либо отправлено с адреса самого ящика.

        По адресу — потому что копии наших писем лежат и во «Входящих»
        (102 у pmkpark@ на 29.09), а у дубля, которого оставит
        _without_duplicates, папка может оказаться любой. Общий признак для
        строки списка («Кому: …»), «ждёт ответа» и переписки (шаг 20).
        """
        self.ensure_one()
        if self.folder_id.role in ('sent', 'drafts'):
            return True
        own = email_normalize(self.account_id.email or '')
        return bool(own) and email_normalize(self.email_from or '') == own

    # ------------------------------------------------------------------
    # ПРАВКА ПМК (шаг 18, Г10): кто кому должен ответить
    # ------------------------------------------------------------------
    @api.model
    def _awaiting_since(self):
        return fields.Datetime.now() - timedelta(days=AWAITING_DAYS)

    def _awaiting_by_thread(self, since=None):
        """{ключ переписки: 'us' | 'client' | False} по этим письмам.

        Одно правило на плашку строки и на фильтр «Ждут ответа». Письма
        берутся в порядке «дата ↓, id ↓», решает первое подходящее:
        черновики (отметка или папка) и тихие папки (_is_quiet: Спам,
        Корзина, у pmk_mail_ui — рассылки mail.ru) пропускаются; старше
        окна — плашки нет; наше (_is_outgoing) — ждём клиента; от робота
        (no-reply, mailer-daemon) — плашки нет; иначе — ждёт нашего ответа.

        Копии одного письма в двух папках — одно письмо, как в
        _threaded_page, но отбрасываются ПОСЛЕ пропуска: иначе оставшейся
        копией могла бы оказаться спамная, и письмо пропало бы из расчёта.
        Отметка flag_answered не годится: у входящих последних писем она не
        стоит ни разу (замер 29.09).
        """
        since = since or self._awaiting_since()
        candidates = self.filtered(lambda m: (
            m.thread_key
            and not m.flag_draft
            and m.folder_id.role != 'drafts'
            and not m.folder_id._is_quiet()
        ))
        ordered = candidates.sorted(
            key=lambda m: (m.date or datetime.min, m.id), reverse=True)
        verdict = {}
        for message in ordered._without_duplicates():
            key = message.thread_key
            if key in verdict:
                continue
            if not message.date or message.date < since:
                verdict[key] = False
            elif message._is_outgoing():
                verdict[key] = 'client'
            elif _RE_ROBOT.search(message.email_from or ''):
                verdict[key] = False
            else:
                verdict[key] = 'us'
        return verdict

    @api.model
    def _awaiting_domain(self, account_ids):
        """Домен фильтра «Ждут ответа»: переписки этих ящиков, где последнее
        слово за клиентом (то же правило, что у плашки строки).

        Один запрос по окну AWAITING_DAYS (около 240 писем за 7 дней на
        29.09, отбор на SQL — 13 мс по индексу date), потом разбор в памяти.
        Спам, Корзину и Черновики отсекаем уже в запросе — правило их всё
        равно пропускает, а писем там больше, чем во всём остальном.
        """
        if not account_ids:
            return [('id', 'in', [])]
        since = self._awaiting_since()
        recent = self.search_fetch([
            ('account_id', 'in', list(account_ids)),
            ('date', '>=', since),
            ('folder_id.role', 'not in', ('spam', 'trash', 'drafts')),
        ], ['thread_key', 'date', 'email_from', 'flag_draft', 'folder_id',
            'account_id', 'message_id'], order='date desc, id desc')
        verdict = recent._awaiting_by_thread(since)
        keys = sorted(key for key, value in verdict.items() if value == 'us')
        return [('thread_key', 'in', keys), ('account_id', 'in', list(account_ids))]

    # ------------------------------------------------------------------
    # conversations
    # ------------------------------------------------------------------
    def _without_duplicates(self):
        """Drop copies of the same message that live in more than one folder.

        Gmail's folders are really labels, so a message sits in INBOX *and* in
        [Gmail]/All Mail. The RFC 5322 Message-ID identifies the message
        itself, which survives that; excluding folders by role would not, and
        would undercount a real Archive folder on a Dovecot server.

        The first copy wins, so callers control which one is kept through the
        order they search in.
        """
        seen, keep = set(), []
        for message in self:
            if message.message_id:
                identity = (message.account_id.id, message.message_id)
                if identity in seen:
                    continue
                seen.add(identity)
            keep.append(message.id)
        return self.browse(keep)

    @api.model
    def _threaded_page(self, domain, limit, account_ids=None, before=None):
        """One row per conversation, newest first.

        ``domain`` decides *which* conversations appear and in what order, so
        opening Inbox lists the conversations that have something in Inbox.
        Their contents are then counted across the whole account, because half
        of every exchange lives in Sent: counted per folder, a two-message
        conversation looks like two unrelated single messages.

        The row itself stays a message from ``domain``. Acting on a row -
        delete, move, mark read - must not silently reach into Sent.

        ПРАВКА ПМК (шаг 18, Б1): ``before`` — дата последней строки прошлой
        страницы — ограничивает переписку по её последнему письму (having
        date:max < before), а не письма в домене: иначе переписка с первой
        страницы возвращалась на следующей своим более старым письмом.
        Дата строки и есть date:max её писем из ``domain``, так что ключ
        страницы у JS прежний.

        ПРАВКА ПМК (шаг 18, Г10): строка несёт ``awaiting`` — 'us' (ждёт
        нашего ответа), 'client' (ждём клиента) или False; считается по тем же
        письмам переписки, что и счётчики, без лишних запросов на письмо. У
        строки из тихой папки (Спам, Корзина…) плашки нет.
        """
        having = [('date:max', '<', fields.Datetime.to_datetime(before))] if before else ()
        groups = self._read_group(
            domain, ['thread_key'], ['__count', 'date:max'],
            having=having, order='date:max desc', limit=limit,
        )
        if not groups:
            return [], False

        keys = [group[0] for group in groups]

        local = self.search(
            Domain.AND([domain, [('thread_key', 'in', keys)]]),
            order='date desc, id desc',
        )
        latest = {}
        for message in local:
            latest.setdefault(message.thread_key, message)

        wide = Domain([('thread_key', 'in', keys)])
        # ПРАВКА ПМК (шаг 18): «is not None» — пустой набор ящиков не
        # означает «все ящики базы» (см. _message_domain).
        if account_ids is not None:
            wide &= Domain([('account_id', 'in', list(account_ids))])
        found = self.search(wide, order='date desc, id desc')
        members = found._without_duplicates()
        awaiting = found._awaiting_by_thread()

        counts, unread, flagged, attachments = {}, {}, {}, {}
        for message in members:
            key = message.thread_key
            counts[key] = counts.get(key, 0) + 1
            unread[key] = unread.get(key, 0) + (0 if message.flag_seen else 1)
            flagged[key] = flagged.get(key, False) or message.flag_flagged
            attachments[key] = attachments.get(key, False) or message.has_attachment

        payload = []
        for key in keys:
            message = latest.get(key)
            if not message:
                continue
            row = message._to_list_payload()[0]
            row.update({
                'thread_key': key,
                'thread_count': counts.get(key, 1),
                # A conversation is unread while any message in it is.
                'flag_seen': not unread.get(key),
                'unread_count': unread.get(key, 0),
                'flag_flagged': flagged.get(key, False),
                'has_attachment': attachments.get(key, False),
                'awaiting': (False if message.folder_id._is_quiet()
                             else awaiting.get(key, False)),
            })
            payload.append(row)
        return payload, len(groups) == limit

    @api.model
    def get_thread(self, message_id):
        """Every message of the conversation this one belongs to.

        Deliberately account-wide rather than folder-wide: a conversation is
        the exchange, and the replies are in Sent.

        ПРАВКА ПМК (шаг 20, 30.09.2026): переписка видна под письмом целиком
        (panes/conversation.js), поэтому у строки ещё:
        ``folder_role`` (роль папки письма), ``body_state`` (тело уже
        загружено или придёт с сервера при развороте); ``is_outgoing`` и
        ``email_to`` строка несёт с шага 18 (_to_list_payload) — по ним
        «мы» и подложка наших писем.

        Из копий одного письма в двух папках (у pmkpark@ 103 пары «Входящие
        + Отправленные») остаётся ОТКРЫТОЕ: окно разворачивает письмо, по
        которому щёлкнули, и ищет его в переписке по id. Раньше оставалась
        первая копия по id, и открытое письмо могло в переписке не
        найтись. Порядок и состав прежние: старые сверху, копии — одно
        письмо.
        """
        message = self._checked(message_id, 'read')
        if not message.thread_key:
            return message._thread_payload()
        members = self.search([
            ('account_id', '=', message.account_id.id),
            ('thread_key', '=', message.thread_key),
        ], order='date asc, id asc')
        kept = (message | members)._without_duplicates()
        return kept.sorted(
            key=lambda m: (m.date or datetime.min, m.id))._thread_payload()

    def _thread_payload(self):
        """ПРАВКА ПМК (шаг 20): строка переписки — строка списка плюс роль
        папки и состояние тела."""
        payload = self._to_list_payload()
        for row, message in zip(payload, self):
            row.update({
                'folder_role': message.folder_id.role or False,
                'body_state': message.body_state,
            })
        return payload

    @api.model
    def get_message_detail(self, message_id):
        message = self.browse(message_id).exists()
        if not message:
            raise UserError(_("This message no longer exists."))
        message.check_access('read')

        # ПРАВКА ПМК (шаг 20): и после 'failed' — читаем заново. Один сбой
        # связи (_fetch_body ставит 'failed') навсегда оставлял письмо «не
        # удалось загрузить»; с перепиской под письмом старые письма
        # разворачиваются по одному, и заходов в ящик — и сбоев — больше.
        # Чтение по-прежнему только на просмотр: EXAMINE и BODY.PEEK,
        # отметку \Seen на сервере оно не ставит.
        if message.body_state in ('header_only', 'failed') \
                or message.structure_state == 'unknown':
            # Lazy fetch: this is the moment the content is actually needed.
            # 'structure_state' is checked too, so a message read before
            # attachments were supported picks up its part list on next open.
            message.sudo()._fetch_body()
            message.invalidate_recordset()

        return {
            'id': message.id,
            'subject': message.subject or _("(no subject)"),
            'email_from': message.email_from or '',
            'email_to': message.email_to or '',
            'email_cc': message.email_cc or '',
            'date': message.date and fields.Datetime.to_string(message.date),
            'body': message._display_body(),
            'body_state': message.body_state,
            # ПРАВКА ПМК (шаг 20): начало текста — для строки свёрнутого
            # письма в переписке после первого разворота (превью считается,
            # когда тело пришло с сервера).
            'preview': message.preview or '',
            'has_blocked_images': bool(
                not message.images_allowed
                and self._has_remote_assets(message.body_html)
            ),
            'has_attachment': message.has_attachment,
            'is_spam': message.is_spam,
            'spam_score': message.spam_score,
            'flag_seen': message.flag_seen,
            'flag_flagged': message.flag_flagged,
            'folder_id': message.folder_id.id,
            'partner_id': message.partner_id.id or False,
            'partner_name': message.partner_id.display_name or '',
            'tags': [{
                'id': tag.id, 'name': tag.name, 'color': tag.color,
            } for tag in message.tag_ids],
            'attachments': [{
                'id': attachment.id,
                'name': attachment.name,
                'content_type': attachment.content_type or '',
                'size': attachment.file_size,
                'state': attachment.state,
            } for attachment in message.client_attachment_ids],
        }

    @api.model
    def allow_images(self, message_id):
        message = self.browse(message_id).exists()
        if not message:
            raise UserError(_("This message no longer exists."))
        message.check_access('read')
        message.sudo().images_allowed = True
        return self.get_message_detail(message_id)

    # ------------------------------------------------------------------
    # contact context
    # ------------------------------------------------------------------
    @api.model
    def get_contact_context(self, message_id, limit=8):
        """Who wrote this, and what else they have written.

        Built from res.partner and this module's own message table only - no
        dependency on any Odoo application, so it works on a bare install.
        """
        message = self._checked(message_id, 'read')
        address = _RE_EMAIL.search(message.email_from or '')
        address = address.group(0).lower() if address else ''

        partner = message.partner_id
        history = self.search([
            ('account_id', '=', message.account_id.id),
            ('email_from', 'ilike', address),
            ('id', '!=', message.id),
        ], order='date desc, id desc', limit=limit) if address else self.browse()

        total = self.search_count([
            ('account_id', '=', message.account_id.id),
            ('email_from', 'ilike', address),
        ]) if address else 0

        return {
            'email': address,
            'partner': {
                'id': partner.id,
                'name': partner.display_name,
                'company': partner.parent_id.display_name or '',
                # Odoo 19 merged 'mobile' into 'phone'.
                'phone': partner.phone or '',
                'city': partner.city or '',
                'country': partner.country_id.display_name or '',
                'image_url': '/web/image/res.partner/%s/avatar_128' % partner.id,
            } if partner else None,
            'message_count': total,
            'history': [{
                'id': item.id,
                'subject': item.subject or _("(no subject)"),
                'date': item.date and fields.Datetime.to_string(item.date),
                'folder': item.folder_id.name,
                'flag_seen': item.flag_seen,
            } for item in history],
        }

    # ------------------------------------------------------------------
    # mutation RPC
    # ------------------------------------------------------------------
    def _checked(self, message_id, operation='write'):
        message = self.browse(message_id).exists()
        if not message:
            raise UserError(_("This message no longer exists."))
        message.check_access(operation)
        return message

    @api.model
    def set_seen(self, message_id, value=True):
        message = self._checked(message_id)
        message._set_flag('\\Seen', value)
        return {'id': message.id, 'flag_seen': value}

    @api.model
    def set_flagged(self, message_id, value=True):
        message = self._checked(message_id)
        message._set_flag('\\Flagged', value)
        return {'id': message.id, 'flag_flagged': value}

    @api.model
    def move_to_folder(self, message_id, folder_id):
        message = self._checked(message_id)
        folder = self.env['mail.client.folder'].browse(folder_id).exists()
        if not folder or folder.account_id != message.account_id:
            raise UserError(_("That folder does not belong to this mailbox."))
        folder.check_access('read')
        message._move_to(folder)
        return {'id': message_id, 'moved': True}

    @api.model
    def delete_message(self, message_id):
        message = self._checked(message_id)
        message._delete()
        return {'id': message_id, 'deleted': True}

    # ------------------------------------------------------------------
    # bulk actions
    # ------------------------------------------------------------------
    def _checked_many(self, message_ids, operation='write'):
        messages = self.browse(message_ids or []).exists()
        if not messages:
            raise UserError(_("None of those messages exist any more."))
        messages.check_access(operation)
        return messages

    @api.model
    def set_seen_bulk(self, message_ids, value=True):
        messages = self._checked_many(message_ids)
        messages._set_flag('\\Seen', value)
        return {'ids': messages.ids, 'flag_seen': value}

    @api.model
    def set_flagged_bulk(self, message_ids, value=True):
        messages = self._checked_many(message_ids)
        messages._set_flag('\\Flagged', value)
        return {'ids': messages.ids, 'flag_flagged': value}

    @api.model
    def move_bulk(self, message_ids, folder_id):
        messages = self._checked_many(message_ids)
        folder = self.env['mail.client.folder'].browse(folder_id).exists()
        if not folder:
            raise UserError(_("That folder no longer exists."))
        folder.check_access('read')
        moved = []
        for message in messages:
            if message.account_id != folder.account_id:
                # Silently skipping would lose mail; naming the mailbox does not.
                raise UserError(_(
                    "'%(subject)s' belongs to %(email)s and cannot be moved into a "
                    "folder of another mailbox.",
                    subject=message.subject or '', email=message.account_id.email,
                ))
            moved.append(message.id)
            message._move_to(folder)
        return {'ids': moved, 'moved': True}

    @api.model
    def delete_bulk(self, message_ids):
        messages = self._checked_many(message_ids)
        deleted = messages.ids
        for message in messages:
            message._delete()
        return {'ids': deleted, 'deleted': True}

    @api.model
    def set_tag(self, message_id, tag_id, value=True):
        message = self._checked(message_id)
        tag = self.env['mail.client.tag'].browse(tag_id).exists()
        if not tag:
            raise UserError(_("That tag no longer exists."))
        message._set_tag(tag, value)
        return self._tag_payload(message)

    @api.model
    def create_tag(self, message_id, name):
        """Create a tag from the composer and apply it in one step."""
        message = self._checked(message_id)
        name = (name or '').strip()
        if not name:
            raise UserError(_("Give the tag a name."))
        Tag = self.env['mail.client.tag'].sudo()
        keyword = Tag._sanitize_keyword(name)
        tag = Tag.search([
            ('account_id', '=', message.account_id.id),
            ('imap_keyword', '=ilike', keyword),
        ], limit=1)
        if not tag:
            tag = Tag.create({
                'account_id': message.account_id.id,
                'name': name,
                'imap_keyword': keyword,
            })
        message._set_tag(tag, True)
        return self._tag_payload(message)

    @api.model
    def get_available_tags(self, message_id):
        message = self._checked(message_id, 'read')
        tags = self.env['mail.client.tag'].search([
            ('account_id', '=', message.account_id.id),
        ])
        applied = set(message.tag_ids.ids)
        return [{
            'id': tag.id,
            'name': tag.name,
            'color': tag.color,
            'applied': tag.id in applied,
        } for tag in tags]

    @api.model
    def _tag_payload(self, message):
        message.invalidate_recordset(['tag_ids'])
        return {
            'id': message.id,
            'tags': [{
                'id': tag.id, 'name': tag.name, 'color': tag.color,
            } for tag in message.tag_ids],
        }

    @api.model
    def get_bulk_move_targets(self, message_ids):
        messages = self._checked_many(message_ids, 'read')
        accounts = messages.account_id
        if len(accounts) != 1:
            return []
        folders = accounts.folder_ids.filtered(lambda f: f.subscribed)
        return [{
            'id': folder.id, 'name': folder.name, 'role': folder.role,
        } for folder in folders.sorted(key=lambda f: (f._role_rank(), f.name.lower()))]

    @api.model
    def get_move_targets(self, message_id):
        message = self._checked(message_id, 'read')
        folders = message.account_id.folder_ids.filtered(
            lambda f: f.subscribed and f != message.folder_id
        )
        return [{
            'id': folder.id,
            'name': folder.name,
            'role': folder.role,
        } for folder in folders.sorted(key=lambda f: (f._role_rank(), f.name.lower()))]
