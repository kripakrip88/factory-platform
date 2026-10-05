# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
import logging
from collections import Counter
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools import bodystructure
from ..tools.imap_client import ImapError

_logger = logging.getLogger(__name__)

# How many UIDs to request per FETCH. Large enough to keep round trips low,
# small enough that one batch never blows up memory on a busy mailbox.
FETCH_BATCH_SIZE = 500

# How many older messages one backfill run describes per folder. Smaller than a
# fetch batch: this runs behind the user's back on a mailbox that already
# works, so it should never be the reason a sync slot runs long.
BACKFILL_BATCH_SIZE = 200

ROLE_ORDER = {
    'inbox': 0, 'drafts': 1, 'sent': 2, 'archive': 3, 'spam': 4, 'trash': 5, 'other': 6,
}

# ПРАВКА ПМК (шаг 18, 30.09.2026): «тихие» папки — их непрочитанное не зовёт
# читать. Счётчик у них серый, без плашки, в итог свёрнутого ящика не входит,
# а письмо из такой папки не делает переписку «ждёт ответа». Надстройка
# добавляет свои папки через _is_quiet() (pmk_mail_ui: сортировщики mail.ru).
QUIET_ROLES = ('spam', 'trash')

# ПРАВКА ПМК (шаг 41, А7, 05.10.2026): поиск идёт по всем папкам ящика, кроме
# этих, — как в Mail.ru. В самих Спаме и Корзине поиск — только по ним.
SEARCH_SKIP_ROLES = ('spam', 'trash')

# Quick filters for the message list.
#
# Every one of these reads a column that is filled in at sync time, so it is
# right for messages nobody has opened yet - which, in a header-first store, is
# nearly all of them. That is why the sync reads BODYSTRUCTURE for each batch
# and why _backfill_structures exists: 'attachments' would otherwise only know
# about mail somebody had already opened, and would hide the rest.
MESSAGE_FILTERS = {
    'all': [],
    'unread': [('flag_seen', '=', False)],
    'read': [('flag_seen', '=', True)],
    'flagged': [('flag_flagged', '=', True)],
    'attachments': [('has_attachment', '=', True)],
    'contact': [('partner_id', '!=', False)],
    # ПРАВКА ПМК (шаг 18, Г10): переписки, где последнее слово за клиентом и
    # ответа от нас нет. Постоянного условия нет — домен собирает
    # _message_domain из mail.client.message._awaiting_domain по ящикам.
    'awaiting': [],
}


class MailClientFolder(models.Model):
    _name = 'mail.client.folder'
    _description = 'Mail Client Folder'
    _order = 'account_id, name'
    _parent_store = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    account_id = fields.Many2one(
        'mail.client.account', required=True, ondelete='cascade', index=True,
    )
    parent_id = fields.Many2one('mail.client.folder', ondelete='cascade', index=True)
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('mail.client.folder', 'parent_id')

    imap_path = fields.Char(required=True, help="Raw mailbox name as the server knows it.")
    delimiter = fields.Char(default='/')
    role = fields.Selection(
        [('inbox', 'Inbox'), ('sent', 'Sent'), ('drafts', 'Drafts'),
         ('trash', 'Trash'), ('spam', 'Spam'), ('archive', 'Archive'),
         ('other', 'Other')],
        default='other', required=True,
    )
    subscribed = fields.Boolean(default=True)

    uid_validity = fields.Integer(readonly=True, copy=False)
    uid_next = fields.Integer(readonly=True, copy=False)
    highest_mod_seq = fields.Char(
        readonly=True, copy=False,
        help="Stored as text: MODSEQ is a 64-bit counter that outgrows Odoo's Integer.",
    )
    last_sync_date = fields.Datetime(readonly=True, copy=False)

    message_ids = fields.One2many('mail.client.message', 'folder_id')
    total_count = fields.Integer(readonly=True, copy=False)
    unread_count = fields.Integer(readonly=True, copy=False)

    _path_account_uniq = models.Constraint(
        'UNIQUE(account_id, imap_path)',
        "A folder with this path already exists on this account.",
    )

    def _role_rank(self):
        self.ensure_one()
        return ROLE_ORDER.get(self.role, 9)

    def _is_quiet(self):
        """ПРАВКА ПМК (шаг 18): крючок «тихой» папки — Спам и Корзина.

        Надстройка расширяет его своими папками (pmk_mail_ui — сортировщики
        mail.ru). Читается в get_inbox_state (серый счётчик) и в расчёте
        «ждёт ответа» (_awaiting_by_thread): письмо из тихой папки переписку
        не решает.
        """
        self.ensure_one()
        return self.role in QUIET_ROLES

    @api.model
    def _list_digests(self, inboxes):
        """ПРАВКА ПМК (шаг 18): крючок «рассылки одной строкой».

        Вызывается для первой страницы «Входящих» (или «Все входящие») без
        поиска и фильтра; ``inboxes`` — показанные папки «Входящие». Ответ —
        список ``{folder_id, name, unread, total, date, senders}``: строка
        списка на папку, которая открывает эту папку. У модуля почты таких
        папок нет — пусто; pmk_mail_ui отдаёт сортировщики mail.ru.
        """
        return []

    @api.model
    def _unified_inboxes(self, account_ids):
        """«Входящие» ящиков для «Все входящие» (подписанные)."""
        return self.search([
            ('account_id', 'in', list(account_ids or [])),
            ('role', '=', 'inbox'),
            ('subscribed', '=', True),
        ])

    @api.model
    def _search_scope_folders(self, account_ids):
        """ПРАВКА ПМК (шаг 41, А7): где ищет поиск «по всем папкам».

        Подписанные папки этих ящиков, кроме Спама и Корзины
        (SEARCH_SKIP_ROLES): в Спаме у pmkpark@ больше трёх тысяч писем, и
        найденное там забивало бы ответ. Те же папки, что видны в дереве."""
        return self.search([
            ('account_id', 'in', list(account_ids or [])),
            ('subscribed', '=', True),
            ('role', 'not in', SEARCH_SKIP_ROLES),
        ])

    @api.model
    def _unread_by_folder(self, folder_ids):
        if not folder_ids:
            return {}
        groups = self.env['mail.client.message']._read_group(
            [('folder_id', 'in', folder_ids), ('flag_seen', '=', False)],
            ['folder_id'], ['__count'],
        )
        return {folder.id: count for folder, count in groups}

    # ------------------------------------------------------------------
    # sync
    # ------------------------------------------------------------------
    def _sync_messages(self, connection):
        """Bring this folder in line with the server.

        ПРАВКА ПМК (шаг 22): возвращает, что проход изменил в письмах папки,
        — Counter(new=…, removed=…, flags=…). _sync_pass складывает их по
        папкам, и сигнал шины говорит почте, есть ли что перечитывать.
        """
        self.ensure_one()
        changes = Counter()
        status = connection.select(self.imap_path, readonly=True)

        if self.uid_validity and status['uid_validity'] != self.uid_validity:
            # Every stored UID just became meaningless. This happens on server
            # migration or a Maildir restore - not a theoretical case.
            _logger.warning(
                "Mail Client: UIDVALIDITY changed on %s/%s (%s -> %s); resyncing.",
                self.account_id.email, self.imap_path, self.uid_validity,
                status['uid_validity'],
            )
            changes['removed'] += self._invalidate_folder()

        # Read this *after* a possible invalidation: a folder that was just
        # reset is starting over, and reconciling it against a set we have not
        # fetched yet would delete everything we are about to create.
        first_sync = not self.uid_next

        self.uid_validity = status['uid_validity'] or 0
        changes['new'] += self._fetch_new_messages(connection, status) or 0
        if not first_sync:
            changes.update(self._reconcile_existing(connection, status) or {})

        self.write({
            'uid_next': status['uid_next'] or self.uid_next,
            'highest_mod_seq': str(status['mod_seq'] or 0),
            'last_sync_date': fields.Datetime.now(),
        })
        self._refresh_counters()
        return changes

    def _invalidate_folder(self):
        """ПРАВКА ПМК (шаг 22): возвращает, сколько писем убрано."""
        self.ensure_one()
        removed = len(self.message_ids)
        self.message_ids.unlink()
        self.write({'uid_next': 0, 'highest_mod_seq': '0'})
        return removed

    def _starting_uid(self, connection):
        """Where to begin on a first sync, honouring the account's sync window."""
        self.ensure_one()
        if self.uid_next:
            return self.uid_next
        window = self.account_id.sync_window_days
        if window > 0:
            since = fields.Date.context_today(self) - timedelta(days=window)
            uids = connection.search_since(since)
            return min(uids) if uids else None
        return 1

    def _fetch_new_messages(self, connection, status):
        """ПРАВКА ПМК (шаг 22): возвращает, сколько писем заведено."""
        self.ensure_one()
        start = self._starting_uid(connection)
        if start is None:
            return 0  # nothing in the sync window
        upper = status['uid_next'] - 1 if status['uid_next'] else None
        if upper is not None and upper < start:
            return 0

        Message = self.env['mail.client.message']
        created = 0

        for low, high in self._uid_batches(start, upper):
            try:
                fetched = connection.fetch_headers(low, high)
            except ImapError as exc:
                _logger.warning("Mail Client: header fetch %s:%s failed on %s: %s",
                                low, high, self.imap_path, exc)
                break

            # Ask only about the UIDs in this batch. Loading every message of
            # the folder would make each sync cost grow with the size of the
            # mailbox, for a check that concerns at most FETCH_BATCH_SIZE rows.
            candidates = [e['uid'] for e in fetched if e['uid'] >= start]
            known = set(self._existing_uids(candidates))

            new_uids = [uid for uid in candidates if uid not in known]
            structures = self._fetch_structures(connection, new_uids)

            values_list = []
            for entry in fetched:
                # "start:*" always yields at least the last message even when
                # nothing is new; drop anything we already hold.
                if entry['uid'] < start or entry['uid'] in known:
                    continue
                known.add(entry['uid'])
                values = self._prepare_message_values(entry)
                values.update(self._structure_values(structures, entry['uid']))
                values_list.append(values)
            if values_list:
                Message.create(values_list)
                created += len(values_list)

        if created:
            _logger.info("Mail Client: %s new message(s) in %s/%s",
                         created, self.account_id.email, self.imap_path)
        return created

    @staticmethod
    def _fetch_structures(connection, uids):
        """BODYSTRUCTURE for a set of UIDs, or nothing if the server balks.

        Never fatal: knowing whether a message has attachments is worth one
        round trip per batch, but not worth losing the messages themselves over
        - a server that cannot answer leaves them marked unknown, and the
        backfill cron picks them up later.
        """
        if not uids:
            return {}
        try:
            return connection.fetch_structures(uids)
        except ImapError as exc:
            _logger.warning("Mail Client: structure fetch failed: %s", exc)
            return {}

    @staticmethod
    def _structure_values(structures, uid):
        """Values describing a message's MIME structure, if we managed to read it."""
        parts = structures.get(uid)
        if parts is None:
            return {}
        return {
            'has_attachment': bool(bodystructure.attachments(parts)),
            'structure_state': 'parsed',
        }

    @staticmethod
    def _uid_batches(start, upper):
        if upper is None:
            yield start, '*'
            return
        low = start
        while low <= upper:
            high = min(low + FETCH_BATCH_SIZE - 1, upper)
            yield low, high
            low = high + 1

    def _tag_command_from_flags(self, flags):
        """Map the server's keyword flags onto tag records."""
        self.ensure_one()
        Tag = self.env['mail.client.tag'].sudo()
        keywords = Tag._keywords_from_flags(flags)
        if not keywords:
            return [fields.Command.clear()]
        tags = Tag.browse()
        for keyword in keywords:
            tags |= Tag._get_or_create(self.account_id, keyword)
        return [fields.Command.set(tags.ids)]

    def _prepare_message_values(self, entry):
        self.ensure_one()
        flags = {f.lower() for f in entry['flags']}
        return {
            'account_id': self.account_id.id,
            'folder_id': self.id,
            'imap_uid': entry['uid'],
            'message_id': entry['message_id'][:255] or False,
            'references': (entry.get('references') or '')[:1024] or False,
            'thread_key': self.env['mail.client.message']._compute_thread_key_value(entry),
            'subject': entry['subject'][:512] or False,
            'email_from': entry['email_from'][:512] or False,
            'email_to': entry['email_to'] or False,
            'email_cc': entry['email_cc'] or False,
            'date': entry['date'],
            'size': entry['size'],
            'flag_seen': '\\seen' in flags,
            'flag_flagged': '\\flagged' in flags,
            'flag_answered': '\\answered' in flags,
            'flag_draft': '\\draft' in flags,
            'flag_deleted': '\\deleted' in flags,
            'spam_score': entry['spam_score'],
            'is_spam': entry['is_spam'] or self.role == 'spam',
            'body_state': 'header_only',
            'tag_ids': self._tag_command_from_flags(entry['flags']),
        }

    def _reconcile_existing(self, connection, status):
        """Apply flag changes and remove messages deleted on the server.

        ПРАВКА ПМК (шаг 22): возвращает Counter(flags=…, removed=…) — сколько
        писем получили новые отметки и сколько убрано.
        """
        self.ensure_one()
        changes = Counter()
        previous_mod_seq = int(self.highest_mod_seq or 0)

        if previous_mod_seq and status['mod_seq']:
            try:
                changed, vanished = connection.fetch_flags_since(previous_mod_seq)
            except ImapError as exc:
                _logger.warning("Mail Client: CHANGEDSINCE failed on %s: %s", self.imap_path, exc)
                return changes
            changes['flags'] += self._apply_flag_changes(changed) or 0
            if connection.supports_qresync:
                changes['removed'] += self._remove_uids(vanished) or 0
                return changes

        # No CONDSTORE state yet, or no QRESYNC to report deletions: fall back
        # to comparing UID sets. Slower, but keeps generic servers working.
        changes['removed'] += self._reconcile_by_uid_diff(connection, status) or 0
        return changes

    def _reconcile_by_uid_diff(self, connection, status):
        """ПРАВКА ПМК (шаг 22): возвращает, сколько писем убрано."""
        self.ensure_one()
        local_uids = self._all_local_uids()
        if not local_uids:
            return 0
        # Skip the expensive listing when the counts already agree.
        if status['exists'] and status['exists'] == len(local_uids):
            return 0
        try:
            remote_uids = set(connection.search_all_uids())
        except ImapError as exc:
            _logger.warning("Mail Client: UID SEARCH failed on %s: %s", self.imap_path, exc)
            return 0
        if not remote_uids and status['exists']:
            # The server says the folder is not empty but returned no UIDs.
            # Something is wrong with the response; deleting everything on the
            # strength of it would be irreversible.
            _logger.warning(
                "Mail Client: inconsistent UID SEARCH on %s (EXISTS=%s, no UIDs); "
                "skipping deletion pass.", self.imap_path, status['exists'],
            )
            return 0
        return self._remove_uids(local_uids - remote_uids)

    def _backfill_structures(self, connection, limit=BACKFILL_BATCH_SIZE):
        """Read BODYSTRUCTURE for messages stored before we asked for it.

        Without this the attachment filter would only be right about mail that
        arrived after the upgrade, and would quietly hide everything older.
        Returns how many messages were settled, so the cron can tell whether
        there is more to do.
        """
        return self._backfill_structures_batch(connection, limit)[0]

    def _backfill_structures_batch(self, connection, limit=BACKFILL_BATCH_SIZE):
        """ПРАВКА ПМК (шаг 22): тело _backfill_structures без изменений по
        существу, но ответ — (settled, written): сколько писем описано и
        сколько записано вообще, вместе с помеченными 'failed'. Дочитка
        ящика (mail.client.account._backfill_structures) фиксирует папку по
        written: запись 'failed' при settled = 0 раньше оставалась
        незафиксированной, когда блокировка ящика уже снята.
        """
        self.ensure_one()
        pending = self.env['mail.client.message'].search(
            [('folder_id', '=', self.id), ('structure_state', '=', 'unknown')],
            order='imap_uid desc', limit=limit,
        )
        if not pending:
            return 0, 0

        uids = pending.mapped('imap_uid')
        structures = self._fetch_structures(connection, uids)
        if not structures:
            return 0, 0

        settled = 0
        for message in pending:
            values = self._structure_values(structures, message.imap_uid)
            if values:
                settled += 1
            else:
                # The server answered for the batch but said nothing usable
                # about this one. Leaving it 'unknown' would put it back at the
                # head of the next run for ever, and the backfill would stop
                # making progress once only such messages remained.
                values = {'structure_state': 'failed'}
            message.write(values)
        return settled, len(pending)

    def search_on_server(self, term, limit=100):
        """Run the search on the mail server and store any headers we lack.

        Returns the number of messages newly brought in, so the caller can
        rerun the ordinary local query afterwards.
        """
        self.ensure_one()
        connection = None
        try:
            connection = self.account_id._open_connection()
            connection.select(self.imap_path, readonly=True)
            uids = connection.search_text(term)
            if not uids:
                return 0
            # Newest first, and bounded: a bare word can match thousands.
            uids = sorted(uids, reverse=True)[:limit]
            missing = sorted(set(uids) - set(self._existing_uids(uids)))
            if not missing:
                return 0

            created = 0
            for index in range(0, len(missing), FETCH_BATCH_SIZE):
                batch = missing[index:index + FETCH_BATCH_SIZE]
                fetched = connection.fetch_headers(min(batch), max(batch))
                wanted = set(batch)
                structures = self._fetch_structures(connection, batch)
                values_list = []
                for entry in fetched:
                    if entry['uid'] not in wanted:
                        continue
                    values = self._prepare_message_values(entry)
                    values.update(self._structure_values(structures, entry['uid']))
                    values_list.append(values)
                if values_list:
                    self.env['mail.client.message'].create(values_list)
                    created += len(values_list)
            return created
        except (ImapError, UserError) as exc:
            _logger.warning("Mail Client: server search failed on %s: %s",
                            self.imap_path, exc)
            raise UserError(_("The mail server could not run that search:\n\n%s", exc)) from exc
        finally:
            if connection:
                connection.close()

    def _existing_uids(self, uids):
        """Return the subset of ``uids`` already stored in this folder.

        Reads one column instead of browsing records: the caller only needs
        integers, and prefetching every field of every message is what made
        syncing a large mailbox expensive.
        """
        self.ensure_one()
        if not uids:
            return []
        rows = self.env['mail.client.message'].search_read(
            [('folder_id', '=', self.id), ('imap_uid', 'in', list(uids))],
            ['imap_uid'],
        )
        return [row['imap_uid'] for row in rows]

    def _all_local_uids(self):
        """Every UID stored in this folder, as plain integers."""
        self.ensure_one()
        rows = self.env['mail.client.message'].search_read(
            [('folder_id', '=', self.id)], ['imap_uid'],
        )
        return {row['imap_uid'] for row in rows}

    def _apply_flag_changes(self, changed):
        """ПРАВКА ПМК (шаг 22): возвращает, скольким письмам записаны
        отметки (или метки)."""
        self.ensure_one()
        if not changed:
            return 0
        # Bounded by what actually changed, not by the size of the folder.
        messages = self.env['mail.client.message'].search([
            ('folder_id', '=', self.id),
            ('imap_uid', 'in', [entry['uid'] for entry in changed]),
        ])
        by_uid = {m.imap_uid: m for m in messages}
        written = 0
        for entry in changed:
            message = by_uid.get(entry['uid'])
            if not message:
                continue
            flags = {f.lower() for f in entry['flags']}
            values = {
                'flag_seen': '\\seen' in flags,
                'flag_flagged': '\\flagged' in flags,
                'flag_answered': '\\answered' in flags,
                'flag_draft': '\\draft' in flags,
                'flag_deleted': '\\deleted' in flags,
            }
            has_changes = any(message[field] != value for field, value in values.items())

            # Keywords can be changed from any client, so labels applied in
            # SOGo or on a phone have to land here too.
            Tag = self.env['mail.client.tag'].sudo()
            remote = {k.lower() for k in Tag._keywords_from_flags(entry['flags'])}
            local = {k.lower() for k in message.tag_ids.mapped('imap_keyword')}
            if remote != local:
                values['tag_ids'] = self._tag_command_from_flags(entry['flags'])
                has_changes = True

            if has_changes:
                message.write(values)
                written += 1
        return written

    def _remove_uids(self, uids):
        """ПРАВКА ПМК (шаг 22): возвращает, сколько писем убрано."""
        self.ensure_one()
        uids = [u for u in uids or []]
        if not uids:
            return 0
        messages = self.env['mail.client.message'].search([
            ('folder_id', '=', self.id), ('imap_uid', 'in', uids),
        ])
        if messages:
            _logger.info("Mail Client: removing %s message(s) deleted on the server in %s",
                         len(messages), self.imap_path)
            messages.unlink()
        return len(messages)

    def _refresh_counters(self):
        for folder in self:
            folder.total_count = self.env['mail.client.message'].search_count(
                [('folder_id', '=', folder.id)])
            folder.unread_count = self.env['mail.client.message'].search_count(
                [('folder_id', '=', folder.id), ('flag_seen', '=', False)])

    # ------------------------------------------------------------------
    # client action RPC
    # ------------------------------------------------------------------
    @api.model
    def _filter_domain(self, message_filter):
        """Translate a quick-filter name into domain leaves."""
        if not message_filter or message_filter == 'all':
            return []
        if message_filter not in MESSAGE_FILTERS:
            # A closed vocabulary, so an unknown name is a bug in the caller.
            # Falling back to 'all' would answer with an unfiltered list under
            # an active filter button, which reads as the filter being broken.
            raise UserError(_("Unknown message filter: %s", message_filter))
        return list(MESSAGE_FILTERS[message_filter])

    @api.model
    def _message_domain(self, folder_id=None, account_ids=None, search=None, before=None,
                        message_filter=None, folder_ids=None, before_id=None):
        """Domain shared by the folder view and the unified inbox.

        ПРАВКА ПМК (шаг 41, 05.10.2026):
        - ``folder_ids`` — поиск «по всем папкам» (А7): письма этих папок
          (_search_scope_folders), а не одной открытой и не «Входящих» ящиков;
          ``account_ids`` при этом — ящики, на которые смотрит фильтр «Ждут
          ответа»;
        - ``before_id`` — второй ключ страницы (Б1, _keyset_domain). Без него
          — как было: только дата.
        """
        domain = self._filter_domain(message_filter)
        if folder_ids is not None:
            domain.append(('folder_id', 'in', list(folder_ids)))
        elif folder_id:
            domain.append(('folder_id', '=', folder_id))
        # ПРАВКА ПМК (шаг 18, 30.09.2026): было «elif account_ids:» — пустой
        # список ящиков (у пользователя нет своего ящика) читался как «без
        # ограничения», и «Все входящие» отдавали письма всей базы, включая
        # Спам и Отправленные чужих ящиков (правило администратора [(1,'=',1)]).
        # Пустой список — это «нет ящиков», значит, и писем нет.
        elif account_ids is not None:
            # Unified inbox: every subscribed inbox the user can reach.
            domain.append(('folder_id', 'in', self._unified_inboxes(account_ids).ids))
        if message_filter == 'awaiting':
            # ПРАВКА ПМК (шаг 18, Г10): переписки ящиков, которые на экране.
            scope = (self.browse(folder_id).account_id.ids if folder_id
                     else list(account_ids or []))
            domain += self.env['mail.client.message']._awaiting_domain(scope)
        domain += self._keyset_domain(before, before_id)
        if search:
            # ПРАВКА ПМК (шаг 18, Г11): ищем и по получателю — «Кому» и
            # «Копия». Иначе в «Отправленных» письмо клиенту не найти по его
            # адресу: там в «От» везде наш ящик.
            domain += ['|', '|', '|', '|',
                       ('subject', 'ilike', search),
                       ('email_from', 'ilike', search),
                       ('email_to', 'ilike', search),
                       ('email_cc', 'ilike', search),
                       ('preview', 'ilike', search)]
        return domain

    @api.model
    def _keyset_domain(self, before, before_id=None):
        """ПРАВКА ПМК (шаг 41, Б1): «старше последней строки» для порядка
        «дата ↓, id ↓».

        Раньше ключом страницы была одна дата (``date < before``), и письма с
        той же датой, что у последней строки, на следующую страницу не
        попадали никогда (в базе 19 групп писем с равной датой в одной папке,
        43 письма). С ``before_id`` ключ составной — (дата, id), и порядок
        равных определён. Без ``before_id`` — как было (старый клиент)."""
        if not before:
            return []
        if not before_id:
            return [('date', '<', before)]
        return ['|', ('date', '<', before),
                '&', ('date', '=', before), ('id', '<', before_id)]

    @api.model
    def get_messages(self, folder_id=None, limit=50, before=None, search=None,
                     threaded=False, unified=False, message_filter=None,
                     before_id=None, search_everywhere=False):
        """Keyset-paginated message list.

        Paging on ``date`` rather than OFFSET keeps the query fast on mailboxes
        with tens of thousands of messages.

        ``message_filter`` narrows the list to one of MESSAGE_FILTERS. Combined
        with threading it selects *conversations*: a conversation is listed when
        any of its messages in this folder matches, and the row shown is the
        newest matching one - so filtering on unread opens on the message that
        is actually unread rather than on a reply you have already read.

        ПРАВКА ПМК (шаг 41, 05.10.2026):
        - ``before_id`` — второй ключ страницы (Б1, _keyset_domain). Без
          переписок — id последней строки; в режиме переписок —
          ``thread_max_id`` последней строки (наибольший id писем переписки в
          списке, _threaded_page). Раньше равные даты на границе страницы
          терялись, а порядок переписок с равной датой был не определён;
        - ``search_everywhere`` — поиск по всем папкам ящика (у «Все
          входящие» — всех доступных ящиков), кроме Спама и Корзины (А7,
          _search_scope_folders). Открыты Спам или Корзина — ищем только в
          них. Ответ говорит, где искали: ``scope`` — 'everywhere' или
          'folder' (без поиска — False). Без переписок копии одного письма в
          двух папках («Входящие» + «Отправленные», 103 пары у pmkpark@) —
          одна строка (_first_copies; остаётся копия во «Входящих»).
        """
        Message = self.env['mail.client.message']
        limit = min(limit or 50, 200)
        # ПРАВКА ПМК (шаг 18, Б1): в режиме переписок «старше последней
        # строки» — это условие на ПЕРЕПИСКУ (её последнее письмо), а не на
        # письма. В домене оно пропускало на вторую страницу переписку с
        # первой — её более старым письмом («Загрузить ещё» повторяло 234
        # переписки «Входящих» pmkpark@). Переписки получают before в
        # _threaded_page (having date:max < before). С шага 41 ключ страницы
        # к домену добавляется ниже, после выбора режима: поиску «везде»
        # нужен и домен без него (_first_copies).
        everywhere = bool(search) and bool(search_everywhere)
        scope = 'folder'

        if unified:
            # Same scope as the sidebar: own and shared mailboxes only, never
            # everything an administrator's record rule would allow.
            accounts = self.env['mail.client.account']._accessible_accounts()
            scope_folders = None
            if everywhere:
                scope_folders = self._search_scope_folders(accounts.ids).ids
                scope = 'everywhere'
            domain = self._message_domain(
                account_ids=accounts.ids, folder_ids=scope_folders, search=search,
                message_filter=message_filter)
            title = _("All Inboxes")
            folder_id = False
            account_ids = accounts.ids
            inboxes = self._unified_inboxes(accounts.ids)
        else:
            folder = self.browse(folder_id).exists()
            if not folder:
                raise UserError(_("This folder no longer exists."))
            folder.check_access('read')
            if everywhere and folder.role not in SEARCH_SKIP_ROLES:
                domain = self._message_domain(
                    account_ids=folder.account_id.ids,
                    folder_ids=self._search_scope_folders(folder.account_id.ids).ids,
                    search=search, message_filter=message_filter)
                scope = 'everywhere'
            else:
                domain = self._message_domain(
                    folder_id=folder.id, search=search, message_filter=message_filter)
            title = folder.name
            # Scope for conversation contents: threads reach into Sent, but
            # never into somebody else's mailbox that happens to sit on the
            # same mailing list.
            account_ids = folder.account_id.ids
            inboxes = folder.filtered(lambda f: f.role == 'inbox')

        if unified and not account_ids:
            # ПРАВКА ПМК (шаг 18): нет ни своего, ни общего ящика — пустой
            # список, и никаких «широких» запросов без ящиков.
            payload, has_more = [], False
        elif threaded:
            payload, has_more = Message._threaded_page(
                domain, limit, account_ids, before=before, before_id=before_id)
        else:
            page = Message.search(domain + self._keyset_domain(before, before_id),
                                  order='date desc, id desc', limit=limit)
            has_more = len(page) == limit
            if scope == 'everywhere':
                kept = page._first_copies(domain)
                # Страница из одних повторов (их оставленные копии — на
                # другой странице): берём следующую, иначе ключ страницы у
                # клиента не сдвинется и «Загрузить ещё» приносило бы пустоту
                # по кругу.
                for __ in range(5):
                    if kept or not has_more or not page[-1].date:
                        break
                    last = page[-1]
                    page = Message.search(
                        domain + self._keyset_domain(last.date, last.id),
                        order='date desc, id desc', limit=limit)
                    has_more = len(page) == limit
                    kept = page._first_copies(domain)
                page = kept
            payload = page._to_list_payload()

        # ПРАВКА ПМК (шаг 18): рассылки одной строкой — только на первой
        # странице «Входящих» без поиска и фильтра (крючок _list_digests).
        digests = []
        if inboxes and not before and not search and (message_filter or 'all') == 'all':
            digests = self._list_digests(inboxes)

        return {
            'folder_id': folder_id,
            'folder_name': title,
            'messages': payload,
            'has_more': has_more,
            'threaded': bool(threaded),
            'filter': message_filter or 'all',
            'digests': digests,
            # ПРАВКА ПМК (шаг 41): где искали — шапка списка и метка папки у
            # строки (mail_client_action.js, searchScope).
            'scope': scope if search else False,
        }

    @api.model
    def search_server(self, folder_id, term):
        """Pull matching headers down from the server, then report the count."""
        folder = self.browse(folder_id).exists()
        if not folder:
            raise UserError(_("This folder no longer exists."))
        folder.check_access('read')
        created = folder.sudo().search_on_server(term)
        return {'fetched': created}
