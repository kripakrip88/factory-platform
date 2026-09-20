# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
{
    'name': "Mail Client",
    'version': '19.0.1.0.0',
    'category': 'Productivity/Mail Client',
    'author': 'Albirru Solutions (Irwan Syah)',
    'maintainer': 'Albirru Solutions',
    'support': '1rw4n.5y4h1919@gmail.com',
    'website': 'https://www.albirru.com/',
    'images': ['static/description/banner.png'],
    'license': 'LGPL-3',
    'summary': "Free & open-source email client inside Odoo 19: three-pane inbox, "
               "two-way IMAP sync, shared team mailboxes, built for self-hosted "
               "mail servers (mailcow/Dovecot) with Gmail & Microsoft 365 support.",
    'description': """
Mail Client - A Real Email Client Inside Odoo
=============================================

Read, write, and organise email without leaving Odoo. Built first for
self-hosted mail servers (mailcow / Dovecot), with Gmail and Microsoft 365
supported through Odoo's own OAuth2 mixins.

Why this module is different
----------------------------
*   **Built for your own server.** Dovecot always advertises QRESYNC,
    CONDSTORE, MOVE, SPECIAL-USE and COMPRESS=DEFLATE, so sync uses the fast
    path by default instead of the slow generic fallback other clients need.
*   **No user passwords in the database.** With a Dovecot master user, one
    admin-only credential reaches every mailbox. Users never type their mail
    password into Odoo, and changing it never breaks anything.
*   **Header-first storage.** Only headers are synced; bodies and attachments
    are fetched on demand. A 20,000-message mailbox costs roughly 40 MB in the
    database instead of ~1.6 GB.
*   **True two-way sync.** Read/unread, flags, tags, moves and deletes travel
    back to the server through a resumable outbox, so Odoo and Thunderbird,
    SOGo or your phone never disagree.
*   **Shared team mailboxes.** info@, sales@ and support@ with per-user roles
    (viewer / agent / manager) enforced by record rules.
*   **Free and open source.** LGPL-3, no tiers, no subscription, no paywalled
    features.

Key Features
------------
*   Three-pane inbox (folders / message list / reading pane) as an OWL client
    action, paginated by keyset so very large mailboxes stay fast.
*   Conversation threading, a unified inbox across every mailbox, and per-
    mailbox signatures.
*   Search on the mail server as well as in Odoo, so messages outside the sync
    window are still found.
*   Tags backed by real IMAP keywords, and a contact panel built without any
    dependency on other Odoo applications.
*   Download any message as a .eml file, fetched from the server on demand.
*   Incremental IMAP sync via QRESYNC, with correct UIDVALIDITY handling on
    server migration or backup restore.
*   Rich composer built on Odoo's own html_editor, with correct RFC 5322
    threading (In-Reply-To / References) and APPEND to the Sent folder.
*   Attachments stay on the server until opened: BODYSTRUCTURE gives their
    name, type and size for free, and only the part you click is downloaded.
*   Sandboxed email rendering: server-side sanitising, no scripts, remote
    images blocked by default.
*   Spam banners read straight from Rspamd headers - no AI, no extra cost,
    and more accurate than either.
*   Full audit log of every mailbox opened with the master credential.

Optional companion modules
--------------------------
*   ``mail_client_mailcow`` - provision mailboxes and aliases from Odoo through
    the mailcow REST API, including HR-driven onboarding and offboarding.
*   ``mail_client_piler`` - jump from any message or contact into your piler
    archive search.

See README.md for setup, usage and architecture notes.
    """,

    # google_gmail & microsoft_outlook are auto_install=True and depend only on
    # 'mail', so they are always present. Depending on them costs nothing and
    # gives us OAuth2 for Gmail + M365 out of the box.
    'depends': [
        'mail',
        'contacts',
        'html_editor',
        'bus',
        'google_gmail',
        'microsoft_outlook',
    ],

    'data': [
        # --- security ---
        'security/mail_client_security.xml',
        'security/ir.model.access.csv',
        # --- data ---
        'data/ir_cron.xml',
        # --- views ---
        'views/mail_client_server_views.xml',
        'views/mail_client_account_views.xml',
        'views/mail_client_sync_op_views.xml',
        'views/mail_client_audit_views.xml',
        'views/mail_client_menus.xml',
    ],

    'assets': {
        'web.assets_backend': [
            'mail_client/static/src/**/*.js',
            'mail_client/static/src/**/*.xml',
            'mail_client/static/src/scss/mail_client.scss',
        ],
        # Served when the color_scheme cookie is "dark"
        'web.assets_web_dark': [
            'mail_client/static/src/scss/mail_client.dark.scss',
        ],
        'web.assets_unit_tests': [
            'mail_client/static/tests/**/*',
        ],
    },

    'application': True,
    'auto_install': False,
    'installable': True,
}
