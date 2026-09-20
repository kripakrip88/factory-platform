# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Symmetric encryption for mail server credentials.

The encryption key lives in ``odoo.conf``, never in the database. That is the
whole point: a stolen database dump must not be enough to recover the Dovecot
master password.
"""
import base64
import hashlib
import logging
import secrets

from odoo.exceptions import UserError
from odoo.tools import config
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - cryptography ships with Odoo
    Fernet = None
    InvalidToken = Exception

CONFIG_KEY = 'mail_client_secret_key'
PREFIX = 'fernet$'


def generate_secret():
    """Return a fresh random secret suitable for ``odoo.conf``.

    Any passphrase works - _cipher() derives a valid Fernet key from whatever
    is configured - but a random 32-byte value is what an administrator should
    actually use.
    """
    return secrets.token_urlsafe(32)


def _cipher():
    if Fernet is None:
        raise UserError(_(
            "The 'cryptography' Python package is required to store mail server "
            "credentials but is not installed."
        ))
    secret = config.get(CONFIG_KEY)
    if not secret:
        # The suggestion below is regenerated every time this message is shown.
        # Say so explicitly: an administrator who sees a different value on each
        # attempt would otherwise assume the key is unstable.
        raise UserError(_(
            "Mail Client credential encryption is not configured.\n\n"
            "Add a line like this to your odoo.conf, then restart Odoo:\n\n"
            "    %(key)s = %(suggestion)s\n\n"
            "Any random string works - the value above is only an example, freshly "
            "generated each time this message appears. Pick one, then never change "
            "it: the stored credentials can only be read back with the same key.\n\n"
            "The key is deliberately kept outside the database so that a database "
            "dump alone cannot reveal your mail server passwords. Back it up "
            "separately from your database backups.",
            key=CONFIG_KEY,
            suggestion=generate_secret(),
        ))
    # Accept any passphrase from odoo.conf and derive a valid Fernet key from it.
    derived = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(derived)


def encrypt(value):
    """Encrypt ``value``; returns a prefixed token, or the input if empty."""
    if not value:
        return value
    if value.startswith(PREFIX):
        return value  # already encrypted, do not double-wrap
    return PREFIX + _cipher().encrypt(value.encode()).decode()


def decrypt(value):
    """Decrypt a token produced by :func:`encrypt`."""
    if not value:
        return value
    if not value.startswith(PREFIX):
        # Written before encryption was configured, or restored from a plain dump.
        _logger.warning("Mail Client: reading an unencrypted credential.")
        return value
    try:
        return _cipher().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        raise UserError(_(
            "Stored mail server credentials cannot be decrypted. The '%s' value in "
            "odoo.conf has changed or is missing. Restore the original key, or "
            "re-enter the credentials.", CONFIG_KEY
        ))
