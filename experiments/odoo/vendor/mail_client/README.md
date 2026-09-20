# Mail Client

**A real email client inside Odoo 19.** Read, write and organise mail without
leaving Odoo — built first for self-hosted mail servers (mailcow / Dovecot),
with Gmail and Microsoft 365 supported through Odoo's own OAuth2 mixins.

| | |
|---|---|
| **Technical name** | `mail_client` |
| **Version** | 19.0.1.0.0 |
| **License** | LGPL-3 — free and open source, no tiers, no paywalled features |
| **Author** | Albirru Solutions (Irwan Syah) |
| **Depends on** | `mail`, `contacts`, `html_editor`, `bus`, `google_gmail`, `microsoft_outlook` |

---

## Table of Contents

1. [What it does](#what-it-does)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Using the inbox](#using-the-inbox)
6. [Writing mail](#writing-mail)
7. [Shared mailboxes](#shared-mailboxes)
8. [How synchronisation works](#how-synchronisation-works)
9. [Security](#security)
10. [Architecture notes](#architecture-notes)
11. [Troubleshooting](#troubleshooting)
12. [Known limitations](#known-limitations)
13. [Changelog](#changelog)
14. [Support](#support)

---

## What it does

### Reading and organising

- **Three-pane inbox** — folders, message list and reading pane, as an OWL
  client action. The folder sidebar can be pinned or hidden to reclaim width.
- **Keyset pagination**, so a mailbox with tens of thousands of messages stays
  responsive: each page asks for what is older than the last row on screen,
  rather than an `OFFSET` the database has to count past.
- **Conversation threading** — group a folder into conversations, or keep the
  flat list.
- **Unified inbox** across every mailbox you have access to, with each account
  foldable in the sidebar.
- **Bulk actions** — tick several messages and mark read/unread, star, move or
  delete them in one go, without opening any of them.
- **Tags** backed by real IMAP keywords, so they survive in Thunderbird, SOGo
  or your phone.
- **Quick filters** — narrow the list to unread, read, starred, mail carrying
  attachments, or mail from a known contact, on its own or on top of a search.
- **Search in Odoo, or on the mail server** — server-side search finds messages
  older than your sync window, which were never copied into Odoo.
- **Contact panel** built without any dependency on other Odoo applications:
  recent conversations, addresses and a link to the partner record if one
  exists.
- **Download the original** message as a `.eml` file, fetched from the server
  on demand.

### Writing

- Rich composer built on Odoo's own `html_editor`, with a **toggle to HTML
  source** when you need full control of the markup.
- **Recipient autocomplete** against your Odoo contacts, while still accepting
  any address typed by hand.
- **Drafts** — close the composer and the draft is kept; empty drafts are
  garbage-collected automatically.
- **Attachments** uploaded from Odoo, and correct **RFC 5322 threading**
  (`In-Reply-To` / `References`) so replies land in the right conversation in
  every other client.
- Sent messages are **APPENDed to the Sent folder** on the server, so they
  appear everywhere, not just in Odoo.
- **Per-mailbox signatures**, optionally suppressed on replies.

### Synchronisation

- **True two-way sync.** Read/unread, flags, tags, moves and deletes travel
  back to the server through a resumable outbox — Odoo and your other mail
  clients never disagree.
- **Incremental IMAP sync via QRESYNC/CONDSTORE**, with correct `UIDVALIDITY`
  handling when a server is migrated or a backup restored.
- **Header-first storage.** Only headers are synced; bodies and attachments are
  fetched when you open them. A 20,000-message mailbox costs roughly **40 MB**
  in the database instead of ~1.6 GB.
- **Push endpoint** so a Dovecot delivery script can trigger a sync within
  seconds instead of waiting for the cron.

### Administration

- **Shared team mailboxes** (`info@`, `sales@`, `support@`) with per-user roles
  — viewer, agent, manager — enforced by record rules, not just by hiding
  buttons.
- **Dovecot master user support**: one admin-only credential reaches every
  mailbox, so users never type their mail password into Odoo.
- **Full audit log** of every mailbox opened with the master credential.
- **Spam banners read straight from Rspamd headers** — no AI, no extra cost.

---

## Requirements

- Odoo 19.0 (Community or Enterprise)
- Python: no packages beyond Odoo's own dependencies (`cryptography` ships with
  Odoo and is used for credential encryption)
- An IMAP server. Anything IMAP4rev1 works; Dovecot is the fast path because it
  always advertises `QRESYNC`, `CONDSTORE`, `MOVE`, `SPECIAL-USE` and
  `COMPRESS=DEFLATE`.
- An outgoing mail server configured in Odoo (*Settings → Technical → Outgoing
  Mail Servers*) for sending.

---

## Installation

**1. Copy the module** into your addons path and update the app list.

**2. Add an encryption key to `odoo.conf`** — do this *before* installing:

```ini
[options]
mail_client_secret_key = <a Fernet key>
```

Generate one with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> **This key never lives in the database.** Mail passwords are encrypted with
> it, so a database dump alone cannot reveal them. Keep it with your server
> configuration and back it up: **lose the key and every stored password must
> be re-entered.** Changing the key has the same effect.
>
> Accounts that use OAuth2 (Gmail, Microsoft 365) or a Dovecot master user
> store no per-user password, so the key matters least in exactly the setup
> this module recommends.

**3. Install** the *Mail Client* app.

**4. Grant access.** Under a user's *Access Rights*, the **Mail Client**
privilege offers:

| Group | Can |
|---|---|
| **User** | Use the inbox for their own and shared mailboxes |
| **Shared Mailbox Agent** | The above, plus act in shared mailboxes |
| **Administrator** | The above, plus *Configuration* (accounts, pending operations, access log) |

Mail server records themselves are restricted to Odoo system administrators.

---

## Configuration

### Step 1 — Mail Server (self-hosted only)

*Mail → Configuration → Mail Servers*

Skip this entirely for Gmail and Microsoft 365 accounts; their hosts are fixed
and OAuth2 replaces the password.

| Field | Notes |
|---|---|
| **IMAP Host / Port** | `993` for SSL/TLS, `143` for STARTTLS |
| **Encryption** | Must match the port. Port 993 with STARTTLS will simply hang until it times out. |
| **Authentication** | **Master user** or **Per-account password** |

**Master user** is the recommended mode for mailcow. Dovecot lets one
administrative credential open any mailbox, using a login of the form
`user@domain*master@mailcow.local`:

| Field | Example |
|---|---|
| Master User | `master` |
| Master Realm | `mailcow.local` |
| Master Password | the master password from your mailcow configuration |

The advantages are real: users never hand their mail password to Odoo, a user
changing their password breaks nothing, and every access is written to the
audit log.

**Per-account password** stores one encrypted password per account instead.
Use it for generic IMAP servers that have no master-user facility.

Use **Test Connection** before saving. On success the module records the
server's advertised capabilities and shows whether QRESYNC and MOVE are
available.

### Step 2 — Mail Account

*Mail → Configuration → Mail Accounts*

| Field | Notes |
|---|---|
| **Account Type** | Self-hosted (mailcow / Dovecot), Generic IMAP, Gmail, or Microsoft 365 |
| **Email Address** | The mailbox address — also the IMAP login under master auth |
| **Owner** | Leave empty to make this a shared mailbox (see below) |
| **Outgoing Server** | Optional. When empty, the owner's personal outgoing server is used, then the server default. |
| **Sync Mode** | *Read only* mirrors the server into Odoo; *Two-way* also pushes your changes back. Move and delete are only offered under *Two-way* — see [Known limitations](#known-limitations) |
| **Sync Window (days)** | Default 90. `0` fetches everything — expect a long first run. |
| **Automatic Sync** | Untick to exclude this mailbox from the cron |

Press **Sync Now** for the first run. Then open the **Folders** tab and tick
the folders you want mirrored — INBOX, Sent and Drafts are subscribed
automatically, the rest are up to you. Every extra folder costs sync time.

### Step 3 — Gmail and Microsoft 365

Two routes are available.

**OAuth2 (no password stored).** Set *Account Type* to Gmail or Microsoft 365,
configure the provider credentials in Odoo's own settings (the standard
`google_gmail` / `microsoft_outlook` setup), then press **Authorise**. The
account shows *Linked* once a refresh token exists. **Revoke** clears it.

**App password.** Set *Account Type* to Generic IMAP, create a mail server
pointing at `imap.gmail.com:993` (SSL) or `outlook.office365.com:993` with
per-account authentication, and store a Google App Password or equivalent.
This route is the more thoroughly tested of the two — see
[Known limitations](#known-limitations).

For Gmail, also make sure IMAP is enabled in *Gmail → Settings → Forwarding and
POP/IMAP*, and consider leaving `[Gmail]/All Mail` unsubscribed: it duplicates
every message in every other folder.

### Step 4 — Signatures

Signatures live on the account, not the user, because someone answering from
`sales@` signs differently than from their own address. Open a mail account's
**Signatures** tab, mark one as default, and untick *Use on reply* if you want
replies to stay clean.

### Step 5 — Instant delivery (optional)

The cron syncs every two minutes. For near-instant arrival, generate a **push
token** on the account (visible to system administrators) and call the
resulting URL from a Dovecot delivery script:

```
https://odoo.example.com/mail_client/notify?token=<token>&email=<mailbox>
```

The endpoint validates the token, then asks the sync scheduled action to run
immediately and returns `202 Accepted` straight away — it never performs the
sync inside the request, so a slow mailbox cannot tie up a web worker. It
rejects anything without a valid token. **Revoke Token** disables it again.

---

## Using the inbox

*Mail → Inbox*

```
┌──────────────┬───────────────────────┬──────────────────────────────┐
│  Accounts    │   Message list        │   Reading pane               │
│  & folders   │   ─────────────       │   ──────────────             │
│              │   ☐ tick to select    │   subject / from / date      │
│  ▾ irwan@…   │   ☐ several at once   │   body (remote images off)   │
│    Inbox  12 │   ☑ then act on all   │   attachments, loaded lazily │
│    Sent      │                       │   contact panel              │
│  ▸ sales@…   │                       │                              │
└──────────────┴───────────────────────┴──────────────────────────────┘
```

- **Hide folders** (the toggle above the sidebar) widens the list and reading
  pane; the choice is remembered.
- **Account headers fold and unfold**, which matters when one owner has several
  mailboxes.
- **Tick messages** in the list to reveal the bulk toolbar: mark read/unread,
  star, move to folder, delete. *Select all* ticks the visible page.
- **Conversations** groups the folder into threads. A thread shows its message
  count; open it to see every message inline.
- **Filter** narrows the list to one of:

  | Filter | Shows |
  |---|---|
  | All | Everything in the folder (the default) |
  | Unread | Messages you have not opened |
  | Read | Messages you have |
  | Starred | Messages flagged `\Flagged` on the server |
  | Has attachments | Messages carrying a real attachment |
  | From a contact | Senders matching a contact in Odoo |

  The filter combines with the search box, and applies to the unified inbox as
  well as to a single folder. It resets to *All* on every visit, so a mailbox is
  never silently narrowed when you come back to it days later.

  With **Conversations** on, the filter picks conversations rather than
  messages: a thread is listed when any of its messages in this folder matches,
  the row shown is the newest one that did, and the count badge still describes
  the whole thread.

  *Has attachments* means a real attachment, not an inline signature logo:
  an `inline` part referenced from the HTML by `cid:` does not count. It is
  read from the message's MIME structure during synchronisation, so it is
  right for mail nobody has opened. Messages that predate the upgrade are
  described in the background — see
  [How synchronisation works](#how-synchronisation-works).
- **Search on server** looks beyond what is stored in Odoo — useful for
  anything older than your sync window.
- **Remote images are blocked by default.** A banner offers *Show images* per
  message; the choice is remembered for that message.
- **Download original** saves the raw `.eml`, fetched from the server at that
  moment.

Every action is applied in Odoo immediately and queued for the server in the
background, so nothing blocks on the network. Pending work is visible under
*Configuration → Pending Operations*.

---

## Writing mail

**New Message** opens the composer. **Reply**, **Reply All** and **Forward**
prefill it from the message you are reading.

- **To / Cc / Bcc** autocomplete against your contacts. Anything not in Odoo
  can be typed directly — press Enter or comma to commit an address.
- **`</>` toggles HTML source** when the rich editor is not enough.
- **Attachments** are added from the composer's attachment area.
- **Closing the composer keeps a draft** if anything was typed. Drafts appear
  in the sidebar under their account.
- On send, the message goes out through the resolved outgoing server and is
  APPENDed to the Sent folder. It appears in your other mail clients too.

**Which outgoing server is used**, in order:

1. the account's own *Outgoing Server*, if set
2. the owner's personal outgoing server (`ir.mail_server` with that user as
   owner)
3. the mail server record's default
4. Odoo's system default

The module refuses to send if the chosen server is not allowed to use the From
address, rather than letting the mail bounce later.

---

## Shared mailboxes

Leave **Owner** empty on an account and it becomes shared. Add users on the
**Access** tab with a role:

| Role | Read | Flag, tag, move, delete, reply | Manage folders & access |
|---|:---:|:---:|:---:|
| **Viewer** | ✓ | | |
| **Agent** | ✓ | ✓ | |
| **Manager** | ✓ | ✓ | ✓ |

Roles are enforced by record rules on every model, so they hold for RPC and
exports, not just for the UI. Removing a user's access removes their visibility
immediately.

---

## How synchronisation works

Two directions, deliberately separate.

**Server → Odoo (fetch).** For each subscribed folder, the module asks for what
changed since the last known modification sequence. With QRESYNC that is one
round trip returning only new and changed messages; without it, a UID range
scan. Headers, flags and message structure are stored; bodies and attachment
payloads are not.

The MIME structure is read for the whole batch in a single `BODYSTRUCTURE`
command, which is what lets the list show a paperclip — and the *Has
attachments* filter answer correctly — for mail nobody has opened. No content is
transferred by it. Mail stored before this existed is described by the
*Describe Older Messages* cron, a bounded number of messages per folder per run,
which stops on its own once there is nothing left to describe. Until it has
caught up, the attachment filter under-reports on old mail; nothing else is
affected.

**Odoo → server (push).** Every mutation you make is written to an outbox row
(`Configuration → Pending Operations`) and executed by the cron. Operations are
idempotent and resumable: an interrupted sync leaves no half-applied state, and
the next run continues. **Push always runs before fetch**, so the server is
never asked about a state Odoo has not yet sent.

**`UIDVALIDITY` changes** — after a server migration or a backup restore — are
detected and invalidate the local cache for that folder, which is then rebuilt
from scratch. This is the case that silently corrupts naive IMAP clients.

**Cron jobs** installed (all adjustable under *Settings → Technical →
Scheduled Actions*):

| Job | Interval |
|---|---|
| Synchronise Mailboxes | 2 minutes |
| Describe Older Messages | 15 minutes |
| Trim Completed Operations | daily |
| Remove Empty Drafts | daily |
| Trim Access Log | weekly |

---

## Security

- **Credentials are encrypted** with a Fernet key read from `odoo.conf`, never
  stored in the database. Master and per-account passwords are additionally
  restricted to the system administrators group.
- **Message bodies are sanitised server-side.** Scripts, event handlers and
  frames are stripped before the body reaches the browser.
- **Remote content is blocked by default**, including CSS `background-image`,
  so simply opening a message does not confirm your address to a sender.
- **Every use of the master credential is logged** — which mailbox, by whom,
  when — under *Configuration → Access Log*.
- **Record rules, not hidden buttons.** Access is enforced in the ORM.
- **The push endpoint is unauthenticated by design** but useless without the
  per-account token, and only ever queues a sync.

---

## Architecture notes

A few decisions worth knowing if you intend to read or extend the code.

**IMAP is the source of truth.** Odoo is a cache plus a workflow layer, not the
owner of your mail. Anything the module cannot push to the server is a bug, not
a feature. This is what keeps Odoo, Thunderbird, SOGo and a phone in agreement.

**Header-first, body on demand.** Storing every body would put roughly 1.6 GB
in the database for a 20,000-message mailbox. Storing headers plus the
BODYSTRUCTURE — which gives attachment names, types and sizes for free, without
downloading them — costs about 40 MB. Bodies are fetched when opened, and
attachments only when clicked. On a self-hosted server the extra round trip is
a few milliseconds.

**The outbox.** User actions must never block on the network, and a network
failure must never lose an action. Both follow from writing mutations to a
queue and letting the cron drain it.

**Optimised for Dovecot, degrading gracefully.** Where the server advertises
QRESYNC, CONDSTORE, MOVE or SPECIAL-USE, the fast path is used. Where it does
not, a slower generic path takes over. The fallback exists, but it does not
dictate the design.

**Nothing in the stack is duplicated.** Archiving is piler's job, at the MTA
level. Anti-spam is Rspamd's job, and the module simply reads the headers it
already writes. Mailbox provisioning belongs to the mailcow API. This module
orchestrates; it does not imitate.

**Odoo core is reused, not reimplemented.** OAuth2 comes from `google_gmail`
and `microsoft_outlook`, SMTP from `ir.mail_server`, the editor from
`html_editor`, and realtime notification from `bus`.

**Source layout**

```
models/     ORM: server, account, folder, message, part, tag,
            signature, access, sync op, audit, compose
tools/      imap_client.py  — IMAP with QRESYNC, XOAUTH2, MOVE
            bodystructure.py — BODYSTRUCTURE parser
            crypto.py        — Fernet credential encryption
static/src/ OWL client action: folder tree, message list,
            reading pane, composer
tests/      Python tests
static/tests/  JavaScript tests (hoot)
```

Run the Python suite with:

```bash
odoo -d <db> -i mail_client --test-enable --test-tags /mail_client
```

And the JavaScript suite (needs Chrome):

```bash
odoo -d <db> -u mail_client,web --test-enable \
     --test-tags "/web:WebSuite.test_unit_desktop[@mail_client]"
```

---

## Troubleshooting

**Connection times out after ~30 seconds.**
Port and encryption disagree — almost always port `993` with STARTTLS
selected. Use `993` + SSL/TLS, or `143` + STARTTLS.

**"Connection failed" with a master user.**
Check the realm. The login sent is `mailbox@domain*master_user@realm`; the
realm must match the master user's domain in your Dovecot configuration
(`mailcow.local` by default). Confirm the master user is enabled in mailcow.

**INBOX does not appear in the folder list.**
INBOX is subscribed automatically on the first sync — some servers omit it from
`LSUB` even though it always exists. If it is still missing, sync once more and
check the Folders tab; the toggle there is editable.

**Everything vanished and came back after a server move.**
Expected. `UIDVALIDITY` changed, so the folder cache was invalidated and
rebuilt. No mail was lost — the server is the source of truth.

**"The server X cannot be forced as the owner does not use it anymore."**
This is Odoo core's own check on `ir.mail_server.owner_user_id`: a personal
outgoing server must belong to a user who actually uses it. Set the owner on
the outgoing mail server record itself, not only here.

**Passwords stopped working after a restore.**
`mail_client_secret_key` is missing from `odoo.conf` or has changed. Restore
the original key, or re-enter every stored password.

**Attachments are listed but will not open.**
The body and the structure are fetched separately. Open the message once to
trigger the fetch; if it persists, check that the account still authenticates.

**Sent mail does not appear in Sent.**
Sync the account — the APPEND happens on the server, and Odoo only sees it on
the next fetch.

**New mail only arrives when I press Sync Now.**
Check that *Mail Client: Synchronise Mailboxes* is active under *Settings →
Technical → Scheduled Actions*, and that the mailbox has **Automatic Sync**
ticked. For a Gmail or Microsoft 365 account, also confirm it shows *Linked* —
an account that was never authorised is skipped by the cron, because retrying
it every two minutes would achieve nothing.

---

## Known limitations

- **OAuth2 for Gmail and Microsoft 365 is covered by unit tests but has not
  been verified against live accounts.** The app-password route through Generic
  IMAP is the better-tested path today.
- **No IMAP IDLE.** New mail arrives on the cron interval, or immediately if
  you wire up the push URL.
- **Read-only mailboxes are read-only in both directions.** Under *Read only*
  sync mode the move and delete controls are hidden, and the server refuses
  both if called anyway: removing a message from Odoo while leaving it on the
  IMAP server would make it vanish for good, because a folder resumes from
  `UIDNEXT` and never looks at that UID again. Flags and tags still apply
  locally; they simply are not pushed. Switch to *Two-way* to act on mail.
- **No CalDAV/CardDAV**, no calendar, no contact sync — this module is about
  mail.
- **No bridge into Chatter or other Odoo apps.** Logging mail against records
  stays Odoo's own job, deliberately; this module does not intercept it.
- **Not an archive.** For legal retention, archive at the MTA level. This
  module mirrors a mailbox and follows it, including deletions.

Two companion modules are planned but not part of this package:
`mail_client_mailcow` (provision mailboxes and aliases through the mailcow REST
API) and `mail_client_piler` (jump from a message into a piler archive search).

---

## Changelog

### 19.0.1.0.0 — first public release

Everything described in this README ships in this release. In summary:

- **Reading** — three-pane inbox, unified All Inboxes, conversation threading,
  quick filters, bulk actions, IMAP-keyword tags, server-side search, `.eml`
  download.
- **Writing** — composer on `html_editor` with an HTML source toggle, recipient
  autocomplete, drafts mirrored to the server, RFC 5322 threading, APPEND to
  Sent, per-mailbox signatures.
- **Sync** — incremental QRESYNC/CONDSTORE with a generic fallback, two-way
  outbox for flags, tags, moves and deletes, `UIDVALIDITY` handling,
  header-first storage, push endpoint. The sync cron covers self-hosted, Gmail
  and Microsoft 365 mailboxes alike.
- **Administration** — Dovecot master user, shared mailboxes with viewer /
  agent / manager rules, Fernet-encrypted credentials, sandboxed rendering,
  remote-image blocking, append-only audit log, Rspamd spam banners.

Verified against mailcow/Dovecot and a live Gmail account on Odoo 19.0
Community. 228 Python tests and a JavaScript suite ship with the module.

See [Known limitations](#known-limitations) for what is deliberately not
included.

---

## Support

Issues and questions: **1rw4n.5y4h1919@gmail.com** ·
[albirru.com](https://www.albirru.com/)

Licensed under **LGPL-3**. You may use, modify and redistribute it, including
commercially. If you improve it, improvements are welcome back.

Copyright 2026 Albirru Solutions (Irwan Syah)
