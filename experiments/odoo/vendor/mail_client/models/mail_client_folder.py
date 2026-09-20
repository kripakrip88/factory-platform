# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
import logging
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
        """Bring this folder in line with the server."""
        self.ensure_one()
        status = connection.select(self.imap_path, readonly=True)

        if self.uid_validity and status['uid_validity'] != self.uid_validity:
            # Every stored UID just became meaningless. This happens on server
            # migration or a Maildir restore - not a theoretical case.
            _logger.warning(
                "Mail Client: UIDVALIDITY changed on %s/%s (%s -> %s); resyncing.",
                self.account_id.email, self.imap_path, self.uid_validity,
                status['uid_validity'],
            )
            self._invalidate_folder()

        # Read this *after* a possible invalidation: a folder that was just
        # reset is starting over, and reconciling it against a set we have not
        # fetched yet would delete everything we are about to create.
        first_sync = not self.uid_next

        self.uid_validity = status['uid_validity'] or 0
        self._fetch_new_messages(connection, status)
        if not first_sync:
            self._reconcile_existing(connection, status)

        self.write({
            'uid_next': status['uid_next'] or self.uid_next,
            'highest_mod_seq': str(status['mod_seq'] or 0),
            'last_sync_date': fields.Datetime.now(),
        })
        self._refresh_counters()

    def _invalidate_folder(self):
        self.ensure_one()
        self.message_ids.unlink()
        self.write({'uid_next': 0, 'highest_mod_seq': '0'})

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
        self.ensure_one()
        start = self._starting_uid(connection)
        if start is None:
            return  # nothing in the sync window
        upper = status['uid_next'] - 1 if status['uid_next'] else None
        if upper is not None and upper < start:
            return

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
        """Apply flag changes and remove messages deleted on the server."""
        self.ensure_one()
        previous_mod_seq = int(self.highest_mod_seq or 0)

        if previous_mod_seq and status['mod_seq']:
            try:
                changed, vanished = connection.fetch_flags_since(previous_mod_seq)
            except ImapError as exc:
                _logger.warning("Mail Client: CHANGEDSINCE failed on %s: %s", self.imap_path, exc)
                return
            self._apply_flag_changes(changed)
            if connection.supports_qresync:
                self._remove_uids(vanished)
                return

        # No CONDSTORE state yet, or no QRESYNC to report deletions: fall back
        # to comparing UID sets. Slower, but keeps generic servers working.
        self._reconcile_by_uid_diff(connection, status)

    def _reconcile_by_uid_diff(self, connection, status):
        self.ensure_one()
        local_uids = self._all_local_uids()
        if not local_uids:
            return
        # Skip the expensive listing when the counts already agree.
        if status['exists'] and status['exists'] == len(local_uids):
            return
        try:
            remote_uids = set(connection.search_all_uids())
        except ImapError as exc:
            _logger.warning("Mail Client: UID SEARCH failed on %s: %s", self.imap_path, exc)
            return
        if not remote_uids and status['exists']:
            # The server says the folder is not empty but returned no UIDs.
            # Something is wrong with the response; deleting everything on the
            # strength of it would be irreversible.
            _logger.warning(
                "Mail Client: inconsistent UID SEARCH on %s (EXISTS=%s, no UIDs); "
                "skipping deletion pass.", self.imap_path, status['exists'],
            )
            return
        self._remove_uids(local_uids - remote_uids)

    def _backfill_structures(self, connection, limit=BACKFILL_BATCH_SIZE):
        """Read BODYSTRUCTURE for messages stored before we asked for it.

        Without this the attachment filter would only be right about mail that
        arrived after the upgrade, and would quietly hide everything older.
        Returns how many messages were settled, so the cron can tell whether
        there is more to do.
        """
        self.ensure_one()
        pending = self.env['mail.client.message'].search(
            [('folder_id', '=', self.id), ('structure_state', '=', 'unknown')],
            order='imap_uid desc', limit=limit,
        )
        if not pending:
            return 0

        uids = pending.mapped('imap_uid')
        structures = self._fetch_structures(connection, uids)
        if not structures:
            return 0

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
        return settled

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
        self.ensure_one()
        if not changed:
            return
        # Bounded by what actually changed, not by the size of the folder.
        messages = self.env['mail.client.message'].search([
            ('folder_id', '=', self.id),
            ('imap_uid', 'in', [entry['uid'] for entry in changed]),
        ])
        by_uid = {m.imap_uid: m for m in messages}
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

    def _remove_uids(self, uids):
        self.ensure_one()
        uids = [u for u in uids or []]
        if not uids:
            return
        messages = self.env['mail.client.message'].search([
            ('folder_id', '=', self.id), ('imap_uid', 'in', uids),
        ])
        if messages:
            _logger.info("Mail Client: removing %s message(s) deleted on the server in %s",
                         len(messages), self.imap_path)
            messages.unlink()

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
                        message_filter=None):
        """Domain shared by the folder view and the unified inbox."""
        domain = self._filter_domain(message_filter)
        if folder_id:
            domain.append(('folder_id', '=', folder_id))
        elif account_ids:
            # Unified inbox: every subscribed inbox the user can reach.
            inboxes = self.search([
                ('account_id', 'in', account_ids),
                ('role', '=', 'inbox'),
                ('subscribed', '=', True),
            ])
            domain.append(('folder_id', 'in', inboxes.ids))
        if before:
            domain.append(('date', '<', before))
        if search:
            domain += ['|', '|',
                       ('subject', 'ilike', search),
                       ('email_from', 'ilike', search),
                       ('preview', 'ilike', search)]
        return domain

    @api.model
    def get_messages(self, folder_id=None, limit=50, before=None, search=None,
                     threaded=False, unified=False, message_filter=None):
        """Keyset-paginated message list.

        Paging on ``date`` rather than OFFSET keeps the query fast on mailboxes
        with tens of thousands of messages.

        ``message_filter`` narrows the list to one of MESSAGE_FILTERS. Combined
        with threading it selects *conversations*: a conversation is listed when
        any of its messages in this folder matches, and the row shown is the
        newest matching one - so filtering on unread opens on the message that
        is actually unread rather than on a reply you have already read.
        """
        Message = self.env['mail.client.message']
        limit = min(limit or 50, 200)

        if unified:
            # Same scope as the sidebar: own and shared mailboxes only, never
            # everything an administrator's record rule would allow.
            accounts = self.env['mail.client.account']._accessible_accounts()
            domain = self._message_domain(
                account_ids=accounts.ids, search=search, before=before,
                message_filter=message_filter)
            title = _("All Inboxes")
            folder_id = False
            account_ids = accounts.ids
        else:
            folder = self.browse(folder_id).exists()
            if not folder:
                raise UserError(_("This folder no longer exists."))
            folder.check_access('read')
            domain = self._message_domain(
                folder_id=folder.id, search=search, before=before,
                message_filter=message_filter)
            title = folder.name
            # Scope for conversation contents: threads reach into Sent, but
            # never into somebody else's mailbox that happens to sit on the
            # same mailing list.
            account_ids = folder.account_id.ids

        if threaded:
            payload, has_more = Message._threaded_page(domain, limit, account_ids)
        else:
            messages = Message.search(domain, order='date desc, id desc', limit=limit)
            payload = messages._to_list_payload()
            has_more = len(messages) == limit

        return {
            'folder_id': folder_id,
            'folder_name': title,
            'messages': payload,
            'has_more': has_more,
            'threaded': bool(threaded),
            'filter': message_filter or 'all',
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
