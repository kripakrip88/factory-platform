# -*- coding: utf-8 -*-
# Copyright 2026 Albirru Solutions (Irwan Syah)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html)
"""Thin IMAP wrapper around :mod:`imaplib`, tuned for Dovecot.

Design notes:

* QRESYNC/CONDSTORE is the primary path. Dovecot enables both by default, so
  ``UID FETCH ... (CHANGEDSINCE n VANISHED)`` gives us changed flags *and*
  deletions in a single round trip.
* When the server does not advertise QRESYNC we fall back to comparing the
  local and remote UID sets. It is slower, but it keeps generic IMAP servers
  usable instead of failing outright.
* Nothing here touches the Odoo ORM. Keeping the protocol layer free of
  recordsets makes it testable on its own and keeps transaction handling in
  the models, where it belongs.
"""
import base64
import binascii
import email
import imaplib
import logging
import quopri
import re
import socket
import ssl
import time
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

from . import bodystructure
from .imap_utf7 import imap_utf7_decode, imap_utf7_encode

_logger = logging.getLogger(__name__)

# imaplib caps a single read at _MAXLINE, 1 MB by default - enough for headers
# but not for a message carrying an attachment, which arrives as one literal.
# That cap is a denial-of-service guard, so it is raised for our own sessions
# only: assigning imaplib._MAXLINE would lift it for every other consumer in
# the Odoo process, core fetchmail included.
MAX_LINE = 10_000_000


class _BoundedReadMixin:
    """Apply :data:`MAX_LINE` to this connection instead of to imaplib."""

    _maxline = MAX_LINE

    def readline(self):
        line = self.file.readline(self._maxline + 1)
        if len(line) > self._maxline:
            raise self.error("got more than %d bytes" % self._maxline)
        return line


class _IMAP4(_BoundedReadMixin, imaplib.IMAP4):
    pass


class _IMAP4_SSL(_BoundedReadMixin, imaplib.IMAP4_SSL):
    pass


HEADER_FIELDS = (
    'SUBJECT FROM TO CC REPLY-TO DATE MESSAGE-ID IN-REPLY-TO REFERENCES '
    'X-SPAM X-SPAM-FLAG X-SPAM-STATUS X-SPAMD-RESULT X-RSPAMD-SCORE'
)

_RE_LIST = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?P<delim>"[^"]*"|NIL)\s+(?P<name>.+)$')
_RE_UID = re.compile(rb'\bUID\s+(\d+)')
_RE_FLAGS = re.compile(rb'\bFLAGS\s+\(([^)]*)\)')
_RE_SIZE = re.compile(rb'\bRFC822\.SIZE\s+(\d+)')
_RE_INTERNALDATE = re.compile(rb'\bINTERNALDATE\s+"([^"]+)"')

_WRONG_ENCRYPTION_HINT = (
    " Port 993 requires TLS from the very first byte, so set Encryption to "
    "SSL/TLS. With STARTTLS or None the server waits for a TLS handshake while "
    "the client waits for a greeting, and neither ever arrives."
)


class ImapError(Exception):
    """Raised for protocol-level failures the caller is expected to report."""


def _decode_header(raw):
    """Decode an RFC 2047 header into a plain string, defensively."""
    if not raw:
        return ''
    try:
        return str(make_header(decode_header(raw))).strip()
    except (UnicodeDecodeError, LookupError, ValueError):
        # Real-world mail breaks RFC 2047 regularly; never fail the whole batch.
        return raw.strip()


def _join_addresses(message, field):
    values = message.get_all(field, [])
    if not values:
        return ''
    parts = []
    for name, addr in getaddresses([_decode_header(v) for v in values]):
        parts.append('%s <%s>' % (name, addr) if name else addr)
    return ', '.join(p for p in parts if p)


def _parse_uid_set(raw):
    """Expand an IMAP uid-set such as ``41,43:46`` into a list of ints."""
    uids = []
    if not raw:
        return uids
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode('ascii', errors='ignore')
    raw = raw.replace('(EARLIER)', '').strip()
    for chunk in raw.split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ':' in chunk:
            low, _, high = chunk.partition(':')
            try:
                start, stop = int(low), int(high)
            except ValueError:
                continue
            if start > stop:
                start, stop = stop, start
            uids.extend(range(start, stop + 1))
        else:
            try:
                uids.append(int(chunk))
            except ValueError:
                continue
    return uids


def _iter_fetch_items(data):
    """Yield ``(attributes, literal)`` pairs from an imaplib FETCH response.

    imaplib returns a flat list where a message carrying a literal appears as
    a ``(prefix, payload)`` tuple followed by a stray ``b')'``.
    """
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2:
            yield bytes(item[0]), bytes(item[1])
        elif isinstance(item, (bytes, bytearray)):
            raw = bytes(item).strip()
            if raw and raw != b')':
                yield raw, None


def _compact_uid_set(uids):
    """Render UIDs as an IMAP sequence set, collapsing runs into ranges.

    ``[4, 5, 6, 9]`` becomes ``"4:6,9"``. Consecutive UIDs are the normal case
    right after a sync, and spelling them out one by one would make the command
    line grow with the size of the batch.
    """
    ordered = sorted({int(uid) for uid in uids or []})
    if not ordered:
        return ''
    runs = []
    start = previous = ordered[0]
    for uid in ordered[1:]:
        if uid == previous + 1:
            previous = uid
            continue
        runs.append((start, previous))
        start = previous = uid
    runs.append((start, previous))
    return ','.join(
        str(low) if low == high else '%s:%s' % (low, high) for low, high in runs
    )


def _iter_fetch_records(data):
    """Yield ``(uid, raw)`` - one reassembled blob per message.

    Same flattening as above, seen from the other end: over a UID *range* the
    items of several messages arrive in one list, and a message carrying a
    literal spills across more than one of them. A record therefore begins at
    every item whose unquoted part announces a UID, and swallows the following
    items that do not.

    The UID is looked for in the attributes rather than in the reassembled
    blob, so a literal - a filename, say - can never masquerade as the start of
    the next message.
    """
    uid, raw = None, b''
    for attributes, literal in _iter_fetch_items(data):
        chunk = attributes
        if literal is not None:
            # Put the literal back where the server took it from, quoted, so
            # the tokenizer sees it as an ordinary string.
            chunk += b'"' + literal + b'"'
        match = _RE_UID.search(attributes)
        if match:
            if uid is not None:
                yield uid, raw
            uid, raw = int(match.group(1)), chunk
        elif uid is not None:
            raw += chunk
    if uid is not None:
        yield uid, raw


class ImapConnection:
    """Context manager wrapping a single authenticated IMAP session."""

    def __init__(self, host, port, encryption, login, password, timeout=30,
                 oauth_string=None):
        self.host = host
        self.port = port
        self.encryption = encryption
        self.login_name = login
        self.password = password
        # When set, XOAUTH2 replaces LOGIN entirely: Gmail and Microsoft 365
        # have no password to send.
        self.oauth_string = oauth_string
        self.timeout = timeout
        self.imap = None
        self.capabilities = set()
        self.selected = None
        # Dovecot advertises a reduced CAPABILITY set before authentication:
        # QRESYNC, CONDSTORE, MOVE and SPECIAL-USE only appear once logged in.
        # Anything reading self.capabilities has to know which of the two it got.
        self.authenticated = False

    # ------------------------------------------------------------------
    # connection lifecycle
    # ------------------------------------------------------------------
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def connect(self, authenticate=True):
        """Open the session. With ``authenticate=False`` only the transport and
        CAPABILITY are probed, which is what a connection test can do when no
        mailbox has been configured yet."""
        self._open()
        if authenticate:
            self._authenticate()

        self._refresh_capabilities()
        if 'QRESYNC' in self.capabilities and 'ENABLE' in self.capabilities:
            try:
                self.imap.enable('QRESYNC')
            except (imaplib.IMAP4.error, OSError) as exc:
                _logger.info("QRESYNC could not be enabled on %s: %s", self.host, exc)
                self.capabilities.discard('QRESYNC')
        return self

    def _open(self):
        """Establish the transport, translating the two failures that actually
        happen in the field into something an administrator can act on."""
        try:
            # ПРАВКА ПМК: imaplib без ssl_context берёт _create_stdlib_context(),
            # у которого check_hostname=False и verify_mode=CERT_NONE — то есть
            # сертификат сервера не проверяется вовсе, и посредник может забрать
            # пароль от ящика. Передаём контекст с полной проверкой.
            _ctx = ssl.create_default_context()
            if self.encryption == 'ssl':
                self.imap = _IMAP4_SSL(self.host, self.port, timeout=self.timeout,
                                       ssl_context=_ctx)
            else:
                self.imap = _IMAP4(self.host, self.port, timeout=self.timeout)
                if self.encryption == 'starttls':
                    self.imap.starttls(ssl_context=_ctx)
        except (socket.timeout, TimeoutError) as exc:
            hint = ''
            if self.encryption != 'ssl' and self.port == 993:
                # Port 993 speaks TLS from the first byte. Opening it in plain
                # mode leaves both ends waiting for the other, until the socket
                # timeout fires with no other clue as to why.
                hint = _WRONG_ENCRYPTION_HINT
            elif self.port not in (143, 993):
                hint = (" The port is neither 143 (STARTTLS) nor 993 (SSL/TLS); "
                        "check that the server really listens there.")
            raise ImapError(
                "Timed out after %ss connecting to %s:%s using %s.%s"
                % (self.timeout, self.host, self.port, self.encryption.upper(), hint)
            ) from exc
        except ssl.SSLError as exc:
            hint = ''
            if self.encryption == 'ssl' and self.port == 143:
                hint = (" Port 143 expects a plain connection upgraded with "
                        "STARTTLS, not SSL/TLS from the start.")
            raise ImapError(
                "TLS handshake with %s:%s failed: %s%s" % (self.host, self.port, exc, hint)
            ) from exc
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ImapError(
                "Cannot reach %s:%s (%s): %s"
                % (self.host, self.port, self.encryption.upper(), exc)
            ) from exc

    def _authenticate(self):
        try:
            if self.oauth_string:
                # Same handshake core uses for fetchmail; the token is built by
                # the Odoo mixin that owns the refresh token.
                self.imap.authenticate('XOAUTH2', lambda challenge: self.oauth_string)
            else:
                self.imap.login(self.login_name, self.password)
            self.authenticated = True
        except imaplib.IMAP4.error as exc:
            if self.oauth_string:
                raise ImapError(
                    "OAuth2 sign-in rejected for '%s': %s\n\n"
                    "The authorisation may have been revoked or expired; "
                    "re-authorise the mailbox." % (self.login_name, exc)
                ) from exc
            raise ImapError(
                "Login rejected for '%s': %s" % (self.login_name, exc)
            ) from exc
        except OSError as exc:
            raise ImapError("Login to %s failed: %s" % (self.host, exc)) from exc

    def close(self):
        if not self.imap:
            return
        try:
            if self.selected:
                self.imap.close()
            self.imap.logout()
        except (imaplib.IMAP4.error, OSError):
            pass  # the session is being torn down anyway
        finally:
            self.imap = None
            self.selected = None

    def _refresh_capabilities(self):
        try:
            typ, data = self.imap.capability()
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ImapError(str(exc)) from exc
        if typ != 'OK':
            raise ImapError("Server refused CAPABILITY")
        raw = b' '.join(data).decode('ascii', errors='ignore')
        self.capabilities = {c.upper() for c in raw.split()}

    @property
    def supports_qresync(self):
        return 'QRESYNC' in self.capabilities

    @property
    def supports_move(self):
        return 'MOVE' in self.capabilities

    # ------------------------------------------------------------------
    # folders
    # ------------------------------------------------------------------
    def list_folders(self):
        """Return dicts with ``path``, ``name``, ``delimiter``, ``flags``, ``subscribed``."""
        try:
            typ, listed = self.imap.list()
            if typ != 'OK':
                raise ImapError("LIST failed")
            sub_typ, subscribed_raw = self.imap.lsub()
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ImapError(str(exc)) from exc

        subscribed = set()
        if sub_typ == 'OK':
            for line in subscribed_raw or []:
                parsed = self._parse_list_line(line)
                if parsed:
                    subscribed.add(parsed['path'])

        folders = []
        for line in listed or []:
            parsed = self._parse_list_line(line)
            if not parsed:
                continue
            if '\\NOSELECT' in parsed['flags'] or '\\NONEXISTENT' in parsed['flags']:
                continue
            parsed['subscribed'] = parsed['path'] in subscribed
            folders.append(parsed)
        return folders

    @staticmethod
    def _parse_list_line(line):
        if isinstance(line, tuple):  # literal-encoded mailbox name
            line = line[0] + b'"' + line[1] + b'"'
        if not isinstance(line, (bytes, bytearray)):
            return None
        match = _RE_LIST.match(bytes(line).strip())
        if not match:
            return None
        flags = {f.decode('ascii', 'ignore').upper() for f in match.group('flags').split()}
        delim_raw = match.group('delim')
        delimiter = '' if delim_raw == b'NIL' else delim_raw.decode('ascii', 'ignore').strip('"')
        name = match.group('name').decode('ascii', errors='ignore').strip()
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1]
        return {
            'path': imap_utf7_decode(name),
            'raw_path': name,
            'delimiter': delimiter,
            'flags': flags,
        }

    def select(self, path, readonly=True, uid_validity=None, mod_seq=None):
        """SELECT a mailbox and return its status counters.

        When ``uid_validity``/``mod_seq`` are supplied and QRESYNC is available,
        the server is asked to replay changes since that point.
        """
        mailbox = self._quote(path)
        command = 'EXAMINE' if readonly else 'SELECT'
        args = [mailbox]
        use_qresync = (
            self.supports_qresync and uid_validity and mod_seq
        )
        if use_qresync:
            args.append('(QRESYNC (%d %d))' % (uid_validity, mod_seq))

        # imaplib.select() does two pieces of bookkeeping that we must replicate,
        # because passing QRESYNC parameters forces us to go around it:
        #   * flush stale untagged responses, so counters from the previously
        #     selected folder cannot leak into this one;
        #   * record that the mailbox was opened read-only. EXAMINE makes the
        #     server report [READ-ONLY], and imaplib raises on the *next*
        #     command if it does not know we asked for that.
        self.imap.untagged_responses = {}
        self.imap.is_readonly = readonly

        try:
            typ, _data = self.imap._simple_command(command, *args)
        except (imaplib.IMAP4.error, OSError) as exc:
            self.imap.state = 'AUTH'  # no mailbox is selected any more
            self.selected = None
            raise ImapError("%s %s: %s" % (command, path, exc)) from exc
        if typ != 'OK':
            self.imap.state = 'AUTH'
            self.selected = None
            raise ImapError("%s %s refused by server" % (command, path))

        self.imap.state = 'SELECTED'
        self.selected = path

        status = {
            'uid_validity': self._response_int('UIDVALIDITY'),
            'uid_next': self._response_int('UIDNEXT'),
            'mod_seq': self._response_int('HIGHESTMODSEQ') or 0,
            'exists': self._response_int('EXISTS') or 0,
            'vanished': [],
            'qresync_used': bool(use_qresync),
        }
        # EXISTS arrives as a bare untagged number, not a response code.
        typ, data = self.imap.response('EXISTS')
        if data and data[0] is not None:
            try:
                status['exists'] = int(data[0])
            except (TypeError, ValueError):
                pass
        if use_qresync:
            _typ, vanished = self.imap.response('VANISHED')
            for entry in vanished or []:
                status['vanished'].extend(_parse_uid_set(entry))
        # A QRESYNC SELECT also replays changed messages as untagged FETCH lines.
        # imaplib keeps those queued and would hand them to the *next* FETCH
        # command, silently mixing two result sets. Drain them here; folder sync
        # asks for changes explicitly via fetch_flags_since().
        self.imap.response('FETCH')
        return status

    def _response_int(self, code):
        _typ, data = self.imap.response(code)
        if not data or data[0] is None:
            return None
        raw = data[0]
        if isinstance(raw, (bytes, bytearray)):
            raw = bytes(raw).split(b']')[0].strip()
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _quote(path):
        encoded = imap_utf7_encode(path)
        return '"%s"' % encoded.replace('\\', '\\\\').replace('"', '\\"')

    # ------------------------------------------------------------------
    # messages
    # ------------------------------------------------------------------
    def fetch_headers(self, uid_from, uid_to='*'):
        """Fetch envelope-level data for a UID range. Bodies are NOT downloaded."""
        criteria = '(UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER.FIELDS (%s)])' % HEADER_FIELDS
        typ, data = self._uid('FETCH', '%s:%s' % (uid_from, uid_to), criteria)
        if typ != 'OK':
            raise ImapError("UID FETCH failed")

        messages = []
        for attributes, literal in _iter_fetch_items(data):
            parsed = self._parse_header_item(attributes, literal)
            if parsed:
                messages.append(parsed)
        return messages

    def _parse_header_item(self, attributes, literal):
        uid_match = _RE_UID.search(attributes)
        if not uid_match:
            return None
        record = {
            'uid': int(uid_match.group(1)),
            'flags': [],
            'size': 0,
            'subject': '',
            'email_from': '',
            'email_to': '',
            'email_cc': '',
            'message_id': '',
            'in_reply_to': '',
            'references': '',
            'date': None,
            'spam_score': None,
            'is_spam': False,
        }

        flags_match = _RE_FLAGS.search(attributes)
        if flags_match:
            record['flags'] = [
                f.decode('ascii', 'ignore') for f in flags_match.group(1).split()
            ]
        size_match = _RE_SIZE.search(attributes)
        if size_match:
            record['size'] = int(size_match.group(1))

        if literal:
            try:
                headers = email.message_from_bytes(literal)
            except Exception:  # noqa: BLE001 - never let one message kill the batch
                _logger.exception("Unparseable headers for UID %s", record['uid'])
                headers = None
            if headers is not None:
                record['subject'] = _decode_header(headers.get('Subject', ''))
                record['email_from'] = _join_addresses(headers, 'From')
                record['email_to'] = _join_addresses(headers, 'To')
                record['email_cc'] = _join_addresses(headers, 'Cc')
                record['message_id'] = (headers.get('Message-ID') or '').strip()
                record['in_reply_to'] = (headers.get('In-Reply-To') or '').strip()
                record['references'] = (headers.get('References') or '').strip()
                record['date'] = self._parse_date(headers.get('Date'))
                record.update(self._parse_spam_headers(headers))

        if not record['date']:
            record['date'] = self._parse_internaldate(attributes)
        return record

    @staticmethod
    def _parse_date(raw):
        if not raw:
            return None
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            return parsed
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _now():
        """Naive UTC, which is what Odoo stores in a Datetime field.

        datetime.utcnow() would be shorter but is deprecated as of Python 3.12
        precisely because the value it returns is naive while looking aware.
        """
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @classmethod
    def _parse_internaldate(cls, attributes):
        match = _RE_INTERNALDATE.search(attributes)
        if not match:
            return cls._now()
        parsed = imaplib.Internaldate2tuple(b'INTERNALDATE "%s"' % match.group(1))
        if not parsed:
            return cls._now()
        return datetime.fromtimestamp(
            time.mktime(parsed), tz=timezone.utc,
        ).replace(tzinfo=None)

    @staticmethod
    def _parse_spam_headers(headers):
        """Surface what Rspamd already decided instead of guessing again.

        The antispam layer is better at this than we
        would ever be, and it has already done the work.
        """
        result = {'spam_score': None, 'is_spam': False}
        flag = (headers.get('X-Spam-Flag') or '').strip().lower()
        if flag in ('yes', 'true'):
            result['is_spam'] = True
        if (headers.get('X-Spam') or '').strip().lower() == 'yes':
            result['is_spam'] = True

        raw_score = headers.get('X-Rspamd-Score') or headers.get('X-Spamd-Result') or ''
        match = re.search(r'-?\d+\.?\d*', raw_score)
        if match:
            try:
                result['spam_score'] = float(match.group(0))
            except ValueError:
                pass
        return result

    def fetch_flags_since(self, mod_seq):
        """Return ``(changed, vanished)`` using CONDSTORE/QRESYNC."""
        criteria = '(FLAGS)'
        suffix = '(CHANGEDSINCE %d%s)' % (mod_seq, ' VANISHED' if self.supports_qresync else '')
        typ, data = self._uid('FETCH', '1:*', criteria, suffix)
        if typ != 'OK':
            raise ImapError("UID FETCH CHANGEDSINCE failed")

        changed = []
        for attributes, _literal in _iter_fetch_items(data):
            uid_match = _RE_UID.search(attributes)
            flags_match = _RE_FLAGS.search(attributes)
            if not uid_match:
                continue
            changed.append({
                'uid': int(uid_match.group(1)),
                'flags': [f.decode('ascii', 'ignore') for f in flags_match.group(1).split()]
                if flags_match else [],
            })

        vanished = []
        if self.supports_qresync:
            _typ, raw = self.imap.response('VANISHED')
            for entry in raw or []:
                vanished.extend(_parse_uid_set(entry))
        return changed, vanished

    def search_all_uids(self):
        """Full UID listing - the fallback used when QRESYNC is unavailable."""
        typ, data = self._uid('SEARCH', None, 'ALL')
        if typ != 'OK':
            raise ImapError("UID SEARCH failed")
        uids = []
        for chunk in data or []:
            if chunk:
                uids.extend(int(u) for u in chunk.split())
        return uids

    def search_since(self, since_date):
        """Return UIDs of messages received on or after ``since_date``."""
        criterion = since_date.strftime('%d-%b-%Y')
        typ, data = self._uid('SEARCH', None, 'SINCE', criterion)
        if typ != 'OK':
            raise ImapError("UID SEARCH SINCE failed")
        uids = []
        for chunk in data or []:
            if chunk:
                uids.extend(int(u) for u in chunk.split())
        return uids

    def fetch_body(self, uid):
        """Download one full message and return ``(html, text, has_attachment)``.

        Deliberately simple: fetch the message, extract the displayable
        parts, and store only those. Attachment payloads are parsed but not
        persisted - :meth:`fetch_part` addresses those individually, so a
        20 MB attachment is never pulled in just to read the body.
        """
        typ, data = self._uid('FETCH', str(uid), '(BODY.PEEK[])')
        if typ != 'OK':
            raise ImapError("UID FETCH body failed")

        raw = None
        for _attributes, literal in _iter_fetch_items(data):
            if literal:
                raw = literal
                break
        if raw is None:
            return '', '', False

        try:
            message = email.message_from_bytes(raw)
        except Exception as exc:  # noqa: BLE001
            raise ImapError("Message could not be parsed: %s" % exc) from exc
        return self._extract_body(message)

    @staticmethod
    def _extract_body(message):
        html_parts, text_parts, has_attachment = [], [], False

        for part in message.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            disposition = (part.get_content_disposition() or '').lower()
            filename = part.get_filename()
            if disposition == 'attachment' or (filename and disposition != 'inline'):
                has_attachment = True
                continue

            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or 'utf-8'
            try:
                decoded = payload.decode(charset, errors='replace')
            except (LookupError, UnicodeDecodeError):
                decoded = payload.decode('utf-8', errors='replace')

            if part.get_content_type() == 'text/html':
                html_parts.append(decoded)
            elif part.get_content_type() == 'text/plain':
                text_parts.append(decoded)

        return '\n'.join(html_parts), '\n'.join(text_parts), has_attachment

    # ------------------------------------------------------------------
    # structure and single-part retrieval
    # ------------------------------------------------------------------
    def fetch_structure(self, uid):
        """Return the MIME parts of a message without downloading content."""
        typ, data = self._uid('FETCH', str(uid), '(BODYSTRUCTURE)')
        if typ != 'OK':
            raise ImapError("UID FETCH BODYSTRUCTURE failed")

        raw = b''
        for attributes, literal in _iter_fetch_items(data):
            raw += attributes
            if literal:
                raw += b'"' + literal + b'"'
        if not raw:
            return []
        marker = raw.upper().find(b'BODYSTRUCTURE')
        if marker == -1:
            return []
        try:
            return bodystructure.parse_parts(raw[marker + len(b'BODYSTRUCTURE'):])
        except bodystructure.BodyStructureError as exc:
            raise ImapError("Unreadable BODYSTRUCTURE for UID %s: %s" % (uid, exc)) from exc

    def fetch_structures(self, uids):
        """Return ``{uid: parts}`` for the given UIDs.

        BODYSTRUCTURE is the only thing that says whether a message carries
        attachments, and asking per message costs a round trip each - which is
        why that answer used to arrive only when a message was opened. Asked
        for a whole batch it costs one round trip, cheap enough to run during
        an ordinary sync, and the reply stays small because no content is
        transferred.

        The UIDs are sent as an explicit set rather than as ``min:max``: once a
        backfill has settled most of a folder the ones left are scattered, and
        a range spanning them would make the server describe everything in
        between.

        Messages whose structure cannot be read are simply absent from the
        result: one unparseable message must not cost the caller the batch.
        """
        uid_set = _compact_uid_set(uids)
        if not uid_set:
            return {}
        typ, data = self._uid('FETCH', uid_set, '(BODYSTRUCTURE)')
        if typ != 'OK':
            raise ImapError("UID FETCH BODYSTRUCTURE failed")

        structures = {}
        for uid, raw in _iter_fetch_records(data):
            marker = raw.upper().find(b'BODYSTRUCTURE')
            if marker == -1:
                continue
            try:
                structures[uid] = bodystructure.parse_parts(
                    raw[marker + len(b'BODYSTRUCTURE'):])
            except bodystructure.BodyStructureError as exc:
                _logger.warning(
                    "Mail Client: unreadable BODYSTRUCTURE for UID %s: %s", uid, exc)
        return structures

    def fetch_raw(self, uid):
        """Download the complete original message, headers included."""
        typ, data = self._uid('FETCH', str(uid), '(BODY.PEEK[])')
        if typ != 'OK':
            raise ImapError("UID FETCH raw message failed")
        for _attributes, literal in _iter_fetch_items(data):
            if literal:
                return literal
        return b''

    def search_text(self, term, since_date=None):
        """Ask the server to search, so messages never fetched are found too.

        Odoo can only match what it stores, and this client deliberately stores
        headers. Anything older than the sync window, or any word that appears
        only in a body, is invisible locally - but not to the server.
        """
        term = (term or '').strip()
        if not term:
            return []
        # ПРАВКА ПМК: вычищаем переводы строк — иначе строка поиска уезжает
        # в протокол отдельной командой (imaplib этого не проверяет).
        term = term.replace("\r", " ").replace("\n", " ")
        # Quote for the protocol: a stray double quote would end the string.
        quoted = '"%s"' % term.replace('\\', '\\\\').replace('"', '\\"')
        criteria = ['OR', 'OR', 'SUBJECT', quoted, 'FROM', quoted, 'TEXT', quoted]
        if since_date:
            criteria = ['SINCE', since_date.strftime('%d-%b-%Y')] + criteria

        typ, data = self._uid('SEARCH', None, *criteria)
        if typ != 'OK':
            raise ImapError("UID SEARCH failed")
        uids = []
        for chunk in data or []:
            if chunk:
                uids.extend(int(u) for u in chunk.split())
        return uids

    def fetch_part(self, uid, part_number, encoding=''):
        """Download and decode a single MIME part."""
        typ, data = self._uid('FETCH', str(uid), '(BODY.PEEK[%s])' % part_number)
        if typ != 'OK':
            raise ImapError("UID FETCH part %s failed" % part_number)

        payload = None
        for _attributes, literal in _iter_fetch_items(data):
            if literal is not None:
                payload = literal
                break
        if payload is None:
            return b''

        encoding = (encoding or '').lower()
        try:
            if encoding == 'base64':
                return base64.b64decode(payload, validate=False)
            if encoding == 'quoted-printable':
                return quopri.decodestring(payload)
        except (binascii.Error, ValueError) as exc:
            raise ImapError(
                "Part %s of UID %s is not valid %s: %s" % (part_number, uid, encoding, exc)
            ) from exc
        return payload

    # ------------------------------------------------------------------
    # mutations - every one of these needs a writable mailbox
    # ------------------------------------------------------------------
    def store_flags(self, uid, flags, add=True):
        """Add or remove IMAP flags on one message."""
        if not flags:
            return
        operator = '+FLAGS.SILENT' if add else '-FLAGS.SILENT'
        typ, _data = self._uid('STORE', str(uid), operator, '(%s)' % ' '.join(flags))
        if typ != 'OK':
            raise ImapError("UID STORE %s on %s failed" % (operator, uid))

    def move(self, uid, target_path):
        """Move a message, preferring RFC 6851 MOVE.

        Dovecot supports MOVE, so the COPY/STORE/EXPUNGE dance below is only
        there for other servers - it is not atomic and can duplicate a message
        if the connection drops midway.
        """
        mailbox = self._quote(target_path)
        if self.supports_move:
            typ, _data = self._uid('MOVE', str(uid), mailbox)
            if typ != 'OK':
                raise ImapError("UID MOVE %s to %s failed" % (uid, target_path))
            return

        typ, _data = self._uid('COPY', str(uid), mailbox)
        if typ != 'OK':
            raise ImapError("UID COPY %s to %s failed" % (uid, target_path))
        self.store_flags(uid, ['\\Deleted'], add=True)
        self.expunge(uid)

    def expunge(self, uid=None):
        """Expunge deleted messages, restricted to ``uid`` when supported."""
        if uid is not None and 'UIDPLUS' in self.capabilities:
            typ, _data = self._uid('EXPUNGE', str(uid))
            if typ != 'OK':
                raise ImapError("UID EXPUNGE %s failed" % uid)
            return
        try:
            self.imap.expunge()
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ImapError("EXPUNGE failed: %s" % exc) from exc

    def append(self, folder_path, raw_message, flags=('\\Seen',), when=None):
        """Upload a message into a folder - used to file sent mail."""
        flag_string = '(%s)' % ' '.join(flags) if flags else None
        date_string = imaplib.Time2Internaldate(when or time.time())
        try:
            typ, data = self.imap.append(
                self._quote(folder_path), flag_string, date_string, raw_message,
            )
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ImapError("APPEND to %s failed: %s" % (folder_path, exc)) from exc
        if typ != 'OK':
            raise ImapError("APPEND to %s refused: %s" % (folder_path, data))
        return self._appended_uid(data)

    @staticmethod
    def _appended_uid(data):
        """Extract the new UID from an APPENDUID response (RFC 4315).

        Knowing where the message landed is what lets a re-saved draft replace
        the previous copy instead of piling duplicates into the Drafts folder.
        """
        for entry in data or []:
            if isinstance(entry, (bytes, bytearray)):
                match = re.search(rb'APPENDUID\s+\d+\s+(\d+)', bytes(entry))
                if match:
                    return int(match.group(1))
        return None

    # ------------------------------------------------------------------
    def _uid(self, command, *args):
        try:
            filtered = [a for a in args if a is not None]
            return self.imap.uid(command, *filtered)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ImapError("UID %s: %s" % (command, exc)) from exc
