"""Сборщик: IMAP ТОЛЬКО ЧТЕНИЕ. EXAMINE (не SELECT) + BODY.PEEK[] — письма не помечаются прочитанными,
флаги и папки в ящике не меняются. Помнит last_uid по каждой папке, после обрыва продолжает с места."""
import base64
import hashlib
import imaplib
import re
import time
from datetime import datetime, timezone

LIST_RE = re.compile(r'\((?P<flags>[^)]*)\) (?P<delim>"[^"]*"|NIL) (?P<name>.+)$')


def decode_mutf7(s):
    """IMAP modified UTF-7 (RFC 3501 5.1.3) → str."""
    out, i = [], 0
    while i < len(s):
        if s[i] == "&":
            j = s.index("-", i)
            if j == i + 1:
                out.append("&")
            else:
                b64 = s[i + 1:j].replace(",", "/")
                b64 += "=" * (-len(b64) % 4)
                out.append(base64.b64decode(b64).decode("utf-16-be"))
            i = j + 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _quote(path):
    return path if path.startswith('"') else '"%s"' % path.replace("\\", "\\\\").replace('"', '\\"')


class Fetcher:
    def __init__(self, cfg, db, log=print):
        self.cfg, self.db, self.log = cfg, db, log
        self.im = None

    def connect(self):
        if not self.cfg.user or not self.cfg.password:
            raise SystemExit("нет MAIL_USER/MAIL_PASS (файл /etc/mail-index/imap.env)")
        self.im = imaplib.IMAP4_SSL(self.cfg.host, self.cfg.port, timeout=120)
        self.im.login(self.cfg.user, self.cfg.password)

    def close(self):
        if self.im:
            try:
                self.im.logout()
            except Exception:
                pass

    def folders(self):
        typ, data = self.im.list()
        res = []
        for raw in data or []:
            line = raw.decode() if isinstance(raw, bytes) else str(raw)
            m = LIST_RE.match(line)
            if not m:
                continue
            flags = m.group("flags")
            path = m.group("name").strip()
            name = decode_mutf7(path.strip('"'))
            if "\\Noselect" in flags or any(f in flags for f in self.cfg.skip_flags):
                continue
            short = name.split("/")[-1]
            if name in self.cfg.skip_names or short in self.cfg.skip_names:
                continue
            res.append((path, name))
        return res

    def _uids(self, path, last_uid):
        if last_uid:
            typ, data = self.im.uid("SEARCH", None, "UID %d:*" % (last_uid + 1))
        elif self.cfg.since:
            d = datetime.strptime(self.cfg.since, "%Y-%m-%d").strftime("%d-%b-%Y")
            typ, data = self.im.uid("SEARCH", None, "SINCE", d)
        else:
            typ, data = self.im.uid("SEARCH", None, "ALL")
        uids = [int(x) for x in (data[0] or b"").split()] if typ == "OK" else []
        return sorted(u for u in uids if u > last_uid)

    def run(self, store_raw, limit=None):
        """store_raw(raw_bytes, folder_name, uid) -> key. Возвращает число новых писем."""
        total = 0
        for path, name in self.folders():
            row = self.db.execute("SELECT uidvalidity, last_uid FROM folders WHERE path=?", (path,)).fetchone()
            typ, _ = self.im.select(_quote(path), readonly=True)   # EXAMINE
            if typ != "OK":
                self.log("  папка недоступна: %s" % name)
                continue
            uv = int(self.im.untagged_responses.get("UIDVALIDITY", [b"0"])[0])
            last = row["last_uid"] if row and row["uidvalidity"] == uv else 0
            if row and row["uidvalidity"] != uv:
                self.log("  %s: UIDVALIDITY сменился — папка перечитывается (дубли отсекаются по Message-ID)" % name)
            uids = self._uids(path, last)
            if limit:
                uids = uids[-limit:]
            if uids:
                self.log("  %s: новых %d" % (name, len(uids)))
            for i in range(0, len(uids), self.cfg.batch):
                chunk = uids[i:i + self.cfg.batch]
                for uid, raw in self._fetch(chunk):
                    store_raw(raw, name, uid)
                    total += 1
                last = max(last, chunk[-1])
                self.db.execute(
                    "INSERT INTO folders(path,name,uidvalidity,last_uid,last_sync) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(path) DO UPDATE SET name=excluded.name, uidvalidity=excluded.uidvalidity, "
                    "last_uid=excluded.last_uid, last_sync=excluded.last_sync",
                    (path, name, uv, last, datetime.now(timezone.utc).isoformat(timespec="seconds")))
                self.db.commit()
                time.sleep(0.3)     # mail.ru режет частые запросы
            if not uids:
                self.db.execute(
                    "INSERT INTO folders(path,name,uidvalidity,last_uid,last_sync) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(path) DO UPDATE SET last_sync=excluded.last_sync, uidvalidity=excluded.uidvalidity",
                    (path, name, uv, last, datetime.now(timezone.utc).isoformat(timespec="seconds")))
                self.db.commit()
        return total

    def _fetch(self, uids):
        # сначала размеры — чтобы не тянуть гигантов целиком
        typ, data = self.im.uid("FETCH", ",".join(map(str, uids)), "(RFC822.SIZE)")
        sizes = {}
        for it in data or []:
            s = it.decode() if isinstance(it, bytes) else ""
            m = re.search(r"UID (\d+).*RFC822\.SIZE (\d+)|RFC822\.SIZE (\d+).*UID (\d+)", s)
            if m:
                uid = int(m.group(1) or m.group(4))
                sizes[uid] = int(m.group(2) or m.group(3))
        limit = self.cfg.max_message_mb * 1048576
        for uid in uids:
            if sizes.get(uid, 0) > limit:
                # гигант: заголовок + первые 300 КБ тела (текст письма обычно в начале, вложения дальше)
                typ, data = self.im.uid("FETCH", str(uid), "(BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.300000>)")
                parts = [x[1] for x in data or [] if isinstance(x, tuple)]
                if len(parts) == 2:
                    head = parts[0].rstrip(b"\r\n") + b"\r\nX-Mail-Index-Truncated: %d\r\n\r\n" % sizes[uid]
                    yield uid, head + parts[1]
                continue
            typ, data = self.im.uid("FETCH", str(uid), "(BODY.PEEK[])")
            for x in data or []:
                if isinstance(x, tuple) and x[1]:
                    yield uid, x[1]
                    break


def raw_key(raw, message_id):
    if message_id:
        return message_id.strip().strip("<>").lower()
    return "sha1:" + hashlib.sha1(raw).hexdigest()
