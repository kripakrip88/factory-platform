import html
import re

from odoo import models, api
from odoo.exceptions import AccessError
from odoo.tools.translate import _


class TeamInboxBasicMessage(models.Model):
    """Query engine only — no fields, no rows ever created; it exists just
    to hang @api.model methods off something reachable via the ORM and
    controller. Incoming/Outgoing listing, search, record links, and
    attachments; nothing stateful (no read-tracking, no starring, no
    labels — that's the Pro tier). Left as a normal (auto-managed) table
    rather than _auto=False: an empty unused table is harmless, whereas
    _auto=False logs a scary "model has no table" error on every install
    since nothing here calls search()/browse() on this model itself."""
    _name = 'teaminboxbasic.message'
    _description = 'Team Inbox Basic — Message Query'

    MODEL_TABLE = {
        'crm.lead':        ('crm_lead',        'name'),
        'sale.order':      ('sale_order',      'name'),
        'account.move':    ('account_move',    'name'),
        'helpdesk.ticket': ('helpdesk_ticket', 'name'),
        'res.partner':     ('res_partner',     'name'),
        'stock.picking':   ('stock_picking',   'name'),
        'purchase.order':  ('purchase_order',  'name'),
    }

    # ── Access guard ─────────────────────────────────────────────────────
    # These methods are reached via custom controller routes, not the
    # standard ORM CRUD path — ir.model.access is never consulted for a
    # raw cr.execute() call, so every entrypoint checks group membership
    # (and, for a single message, real access to its linked record) itself.

    def _ensure_teaminbox_access(self):
        if not self.env.user.has_group('northlight_teaminbox.group_teaminboxbasic_user'):
            raise AccessError(_("You don't have access to Team Inbox."))

    def _check_message_access(self, message_id):
        self._ensure_teaminbox_access()
        self.env.cr.execute(
            "SELECT model, res_id FROM mail_message WHERE id = %s", (int(message_id),))
        row = self.env.cr.dictfetchone()
        if not row:
            return None, None
        if row['model'] and row['res_id']:
            if row['model'] not in self.env or \
                    not self.env[row['model']].search([('id', '=', row['res_id'])]):
                raise AccessError(_("You don't have access to this message."))
        return row['model'], row['res_id']

    def _access_clause(self, from_sql, where_sql, params, alias):
        """Keeps only rows whose linked record the current user can really
        access, per that model's own Odoo access rights and record rules
        (multi-company included). See Team Inbox Pro's teaminbox.read for
        the full rationale — same mechanism, copied here since this module
        doesn't depend on Pro."""
        self.env.cr.execute(f"""
            SELECT DISTINCT {alias}.model, {alias}.res_id
            FROM {from_sql}
            WHERE {where_sql} AND {alias}.model IS NOT NULL AND {alias}.res_id IS NOT NULL
        """, params)
        by_model = {}
        for row in self.env.cr.dictfetchall():
            if row['res_id']:
                by_model.setdefault(row['model'], []).append(row['res_id'])

        clauses, extra_params = [], []
        for model, res_ids in by_model.items():
            if model not in self.env:
                continue
            try:
                accessible = self.env[model].search([('id', 'in', res_ids)]).ids
            except Exception:
                continue
            if accessible:
                clauses.append(f"({alias}.model = %s AND {alias}.res_id = ANY(%s))")
                extra_params += [model, accessible]

        sql = f"({alias}.model IS NULL OR {alias}.res_id IS NULL"
        if clauses:
            sql += " OR " + " OR ".join(clauses)
        sql += ")"
        return sql, extra_params

    # ── Formatting helpers ───────────────────────────────────────────────

    @staticmethod
    def _fmt_addr(name, email):
        email = (email or '').strip()
        name = (name or '').strip()
        if '<' in email:
            return email
        if name and email:
            return f'{name} <{email}>'
        return email or name or ''

    @staticmethod
    def _html_to_preview(html_fragment, max_len):
        text = html.unescape(re.sub(r'<[^>]+>', ' ', html_fragment or ''))
        last_open = text.rfind('<')
        if last_open != -1 and text.find('>', last_open) == -1:
            text = text[:last_open]
        return re.sub(r'\s+', ' ', text).strip()[:max_len]

    def _build_record_url(self, base_url, model, res_id):
        return f"{base_url}/web#model={model}&id={res_id}&view_type=form"

    def _live_names(self, model_ids):
        live_names = {}
        for model, res_ids in model_ids.items():
            if model not in self.MODEL_TABLE:
                continue
            table, col = self.MODEL_TABLE[model]
            try:
                self.env.cr.execute(
                    f"SELECT id, {col} AS name FROM {table} WHERE id = ANY(%s)",
                    (list(set(res_ids)),))
                for row in self.env.cr.dictfetchall():
                    live_names[(model, row['id'])] = row['name']
            except Exception:
                pass
        return live_names

    def _quick_search_sql(self, alias):
        a = alias
        return f"""(
            {a}.subject ILIKE %s
            OR {a}.email_from ILIKE %s
            OR EXISTS (
                SELECT 1 FROM res_partner p2
                LEFT JOIN res_partner comp ON comp.id = COALESCE(p2.parent_id, p2.id)
                WHERE p2.id = {a}.author_id AND comp.name ILIKE %s
            )
        )"""

    def _get_partner_data(self, message_ids, outgoing_ids, base_url=''):
        if not message_ids:
            return {}, {}

        linked_map = {mid: [] for mid in message_ids}
        recip = {mid: {'to_map': {}, 'cc_map': {}} for mid in outgoing_ids}

        self.env.cr.execute("""
            SELECT rel.mail_message_id,
                   rp.id    AS partner_id,
                   rp.name  AS partner_name,
                   rp.email AS partner_email
            FROM mail_message_res_partner_rel rel
            JOIN res_partner rp ON rp.id = rel.res_partner_id
            WHERE rel.mail_message_id = ANY(%s)
        """, (message_ids,))
        for r in self.env.cr.dictfetchall():
            mid = r['mail_message_id']
            linked_map[mid].append({
                'model': 'res.partner',
                'res_id': r['partner_id'],
                'name': r['partner_name'],
                'url': self._build_record_url(base_url, 'res.partner', r['partner_id']),
            })
            if mid in recip:
                email_key = (r['partner_email'] or '').lower().strip()
                display = self._fmt_addr(r['partner_name'], r['partner_email'])
                if email_key:
                    recip[mid]['to_map'][email_key] = display
                elif r['partner_name']:
                    recip[mid]['to_map'][r['partner_name'].lower()] = r['partner_name']

        if outgoing_ids:
            self.env.cr.execute("""
                SELECT mail_message_id, email_to, email_cc
                FROM mail_mail
                WHERE mail_message_id = ANY(%s)
            """, (outgoing_ids,))
            for r in self.env.cr.dictfetchall():
                mid = r['mail_message_id']
                if mid not in recip:
                    continue
                for raw_field, bucket in ((r['email_to'], 'to_map'), (r['email_cc'], 'cc_map')):
                    if not raw_field:
                        continue
                    for entry in raw_field.split(','):
                        entry = entry.strip()
                        if not entry:
                            continue
                        m = re.search(r'<([^>]+)>', entry)
                        bare = m.group(1).lower() if m else entry.lower()
                        if bare not in recip[mid][bucket]:
                            recip[mid][bucket][bare] = entry

        still_empty = [mid for mid in recip if not recip[mid]['to_map']]
        if still_empty:
            self.env.cr.execute("""
                SELECT n.mail_message_id, rp.id AS partner_id,
                       rp.name AS partner_name, rp.email AS partner_email
                FROM mail_notification n
                JOIN res_partner rp ON rp.id = n.res_partner_id
                WHERE n.mail_message_id = ANY(%s)
            """, (still_empty,))
            for r in self.env.cr.dictfetchall():
                mid = r['mail_message_id']
                email_key = (r['partner_email'] or '').lower().strip()
                display = self._fmt_addr(r['partner_name'], r['partner_email'])
                if email_key:
                    recip[mid]['to_map'].setdefault(email_key, display)
                elif r['partner_name']:
                    recip[mid]['to_map'].setdefault(r['partner_name'].lower(), r['partner_name'])

        recipients_out = {}
        for mid in message_ids:
            if mid in recip:
                recipients_out[mid] = {
                    'to': ', '.join(recip[mid]['to_map'].values()),
                    'cc': ', '.join(recip[mid]['cc_map'].values()),
                }
            else:
                recipients_out[mid] = {'to': '', 'cc': ''}

        return linked_map, recipients_out

    def _get_attachments(self, res_model, res_id):
        if not res_model or not res_id:
            return []
        try:
            res_id = int(res_id)
        except (TypeError, ValueError):
            return []
        self.env.cr.execute("""
            SELECT id, name, mimetype, file_size
            FROM ir_attachment
            WHERE res_model = %s AND res_id = %s
            ORDER BY create_date DESC
        """, (res_model, res_id))
        return [{
            'id': r['id'],
            'name': r['name'] or '',
            'mimetype': r['mimetype'] or '',
            'file_size': r['file_size'] or 0,
        } for r in self.env.cr.dictfetchall()]

    # ── mail.message tab predicate ──────────────────────────────────────

    @classmethod
    def _mm_type_clause(cls, direction, alias='m'):
        a = alias
        dispatched = f"""(
            EXISTS (SELECT 1 FROM mail_mail mm WHERE mm.mail_message_id = {a}.id)
            OR EXISTS (SELECT 1 FROM mail_notification mn
                       WHERE mn.mail_message_id = {a}.id
                         AND mn.notification_type = 'email')
        )"""
        if direction == 'in':
            return f"{a}.message_type = 'email'"
        return f"""(
            {a}.message_type = 'email_outgoing'
            OR ({a}.message_type = 'comment' AND {dispatched})
        )"""

    # ── Main data query ──────────────────────────────────────────────────

    @api.model
    def get_data(self, direction, limit=25, offset=0, search='', sort='desc',
                 date_from='', date_to='', base_url=''):
        self._ensure_teaminbox_access()
        limit = min(int(limit), 25)
        offset = int(offset)
        order = 'DESC' if sort == 'desc' else 'ASC'

        where = self._mm_type_clause(direction)
        params = []

        if search and search.strip():
            s = f'%{search.strip()}%'
            where += " AND " + self._quick_search_sql('m')
            params += [s, s, s]

        if date_from:
            where += " AND m.date >= %s"
            params.append(date_from)
        if date_to:
            where += " AND m.date <= %s"
            params.append(date_to + ' 23:59:59')

        access_sql, access_p = self._access_clause('mail_message m', where, params, 'm')
        where += " AND " + access_sql
        params += access_p

        self.env.cr.execute(f"""
            SELECT m.id, m.date, m.subject, m.email_from,
                   m.model, m.res_id,
                   LEFT(COALESCE(m.body, ''), 1200) AS body_head,
                   p.name AS author_name,
                   m.message_type AS msg_type
            FROM mail_message m
            LEFT JOIN res_partner p ON p.id = m.author_id
            WHERE {where}
            ORDER BY m.date {order}
            LIMIT %s OFFSET %s
        """, params + [limit, offset])

        rows = self.env.cr.dictfetchall()
        if not rows:
            return []

        msg_ids = [r['id'] for r in rows]
        outgoing_ids = [r['id'] for r in rows if r['msg_type'] in ('email_outgoing', 'comment')]

        model_ids = {}
        for r in rows:
            if r['model'] and r['res_id']:
                model_ids.setdefault(r['model'], []).append(r['res_id'])
        live_names = self._live_names(model_ids)

        linked_map, recipients_map = self._get_partner_data(msg_ids, msg_ids, base_url)

        primary_link = {}
        for r in rows:
            if r['model'] and r['res_id']:
                name = (live_names.get((r['model'], r['res_id']))
                        or f"{r['model']} #{r['res_id']}")
                primary_link[r['id']] = {
                    'model': r['model'], 'res_id': r['res_id'], 'name': name,
                    'url': self._build_record_url(base_url, r['model'], r['res_id']),
                }
        for mid, link in primary_link.items():
            existing = {(l['model'], l['res_id']) for l in linked_map[mid]}
            if (link['model'], link['res_id']) not in existing:
                linked_map[mid].insert(0, link)

        result = []
        for row in rows:
            rec = recipients_map.get(row['id'], {'to': '', 'cc': ''})
            result.append({
                'id': row['id'],
                'date': row['date'].isoformat() if row['date'] else '',
                'subject': row['subject'] or '',
                'body': '',
                'preview': self._html_to_preview(row['body_head'], 140),
                'email_from': row['email_from'] or '',
                'author_name': row['author_name'] or '',
                'email_to': rec['to'],
                'email_cc': rec['cc'],
                'linked_records': linked_map.get(row['id'], []),
                'res_model': row['model'] or '',
                'res_id': row['res_id'] or 0,
            })
        return result

    # ── Stats ────────────────────────────────────────────────────────────

    @api.model
    def get_stats(self):
        self._ensure_teaminbox_access()
        base_where = "m.message_type IN ('email', 'email_outgoing', 'comment')"
        access_sql, access_p = self._access_clause('mail_message m', base_where, [], 'm')
        self.env.cr.execute(f"""
            SELECT
                SUM(CASE WHEN m.message_type = 'email' THEN 1 ELSE 0 END) AS total_in,
                SUM(CASE WHEN m.message_type = 'email_outgoing'
                              OR (m.message_type = 'comment'
                                  AND (
                                      EXISTS (SELECT 1 FROM mail_mail mm
                                              WHERE mm.mail_message_id = m.id)
                                      OR EXISTS (SELECT 1 FROM mail_notification mn
                                                 WHERE mn.mail_message_id = m.id
                                                   AND mn.notification_type = 'email')
                                  ))
                         THEN 1 ELSE 0 END) AS total_out
            FROM mail_message m
            WHERE {base_where} AND {access_sql}
        """, access_p)
        row = self.env.cr.dictfetchone() or {}
        return {
            'total_in': row.get('total_in') or 0,
            'total_out': row.get('total_out') or 0,
        }

    # ── Body ─────────────────────────────────────────────────────────────

    @api.model
    def get_message_body(self, message_id):
        model, res_id = self._check_message_access(message_id)
        self.env.cr.execute(
            "SELECT body FROM mail_message WHERE id = %s", (int(message_id),))
        row = self.env.cr.fetchone()
        return {
            'body': (row[0] or '') if row else '',
            'attachments': self._get_attachments(model, res_id),
        }
