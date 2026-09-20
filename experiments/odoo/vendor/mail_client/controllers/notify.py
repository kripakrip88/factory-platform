# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Push endpoint for the mail server.

The cron polls every two minutes, which is fine but not immediate. Because the
mail server is yours, it can simply tell Odoo when something arrives - a
possibility no Gmail or Microsoft 365 user has.

The endpoint deliberately accepts *only a trigger*. It never receives message
content: the sync still fetches everything over authenticated IMAP, so a
forged call can at worst cause an unnecessary sync of a mailbox that already
belongs to the token holder.

It also never performs the sync itself. Running one inline would hold an HTTP
worker for as long as the mailbox takes to fetch - minutes, on a first run -
while committing per folder in the middle of the request. Instead the sync cron
is asked to run now, and the request returns immediately.
"""
import logging
import time

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Minimum seconds between two honoured triggers for the same mailbox. A busy
# mailing list would otherwise fire a sync per delivered message.
THROTTLE_SECONDS = 10

# Mailbox -> timestamp of the last accepted trigger. Per worker, which is all
# this needs to be: the point is to blunt bursts, not to be exact.
_last_trigger = {}


class MailClientNotify(http.Controller):

    @http.route('/mail_client/notify', type='http', auth='none',
                methods=['POST', 'GET'], csrf=False, save_session=False)
    def notify(self, token=None, email=None, **kwargs):
        """Trigger a sync for one mailbox.

        Example, from a Dovecot delivery script:

            curl -s -X POST https://odoo.example.com/mail_client/notify \\
                 -d token=<account token> -d email=user@example.org
        """
        if not token:
            return request.make_response('missing token', status=400)

        env = request.env(su=True)
        account = env['mail.client.account'].search([
            ('notify_token', '=', token),
            ('active_sync', '=', True),
        ], limit=1)

        # Compare the mailbox too when it is supplied: it turns a leaked token
        # into a mistake that is visible in the log rather than a silent one.
        if not account or (email and account.email.lower() != email.strip().lower()):
            _logger.info("Mail Client: rejected notify call for %r", email)
            return request.make_response('unknown token', status=403)

        now = time.monotonic()
        previous = _last_trigger.get(account.id, 0)
        if now - previous < THROTTLE_SECONDS:
            return request.make_response('throttled', status=202)
        _last_trigger[account.id] = now

        _logger.info("Mail Client: sync triggered for %s by the mail server", account.email)
        cron = env.ref('mail_client.ir_cron_mail_client_sync', raise_if_not_found=False)
        if not cron:
            # The scheduled action was deleted. Say so rather than reporting a
            # success that will never produce a sync.
            _logger.warning("Mail Client: the sync cron is missing; trigger ignored.")
            return request.make_response('sync cron missing', status=503)
        # Ask the cron runner to pick this up now instead of at its next slot.
        # 202: accepted, not yet done - which is exactly what happened.
        cron._trigger()
        return request.make_response('queued', status=202)
