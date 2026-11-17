"""Приём сырого письма: сохранить оригинал (.eml.zst), разобрать, записать в базу, вложения → текст."""
import gzip
import hashlib
import re
from pathlib import Path

from . import attach, quotes
from .imap import raw_key
from .parse import PARSED_VERSION, parse

try:
    import zstandard
    _ZC = zstandard.ZstdCompressor(level=10)
    _ZD = zstandard.ZstdDecompressor()
except ImportError:  # pragma: no cover
    zstandard = None


def _compress(raw):
    return (_ZC.compress(raw), ".eml.zst") if zstandard else (gzip.compress(raw, 6), ".eml.gz")


def read_raw(path):
    data = Path(path).read_bytes()
    if str(path).endswith(".zst"):
        return _ZD.decompress(data, max_output_size=512 * 1048576)
    return gzip.decompress(data)


def _h(key):
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _safe(name, n=60):
    name = re.sub(r"[^\w.\- ]+", "_", name or "file", flags=re.U).strip(" ._") or "file"
    return name[:n]


class Ingest:
    def __init__(self, cfg, db, log=print):
        self.cfg, self.db, self.log = cfg, db, log
        self.own = cfg.own_addresses
        self.new_keys = []

    def store_raw(self, raw, folder, uid):
        mid = re.search(rb"^Message-ID:\s*(<[^>\r\n]+>)", raw[:65536], re.I | re.M)
        key = raw_key(raw, mid.group(1).decode("ascii", "replace") if mid else "")
        self.db.execute("INSERT OR REPLACE INTO locations(key, folder, uid) VALUES(?,?,?)", (key, folder, uid))
        if self.db.execute("SELECT 1 FROM messages WHERE key=?", (key,)).fetchone():
            return key          # то же письмо в другой папке — оригинал уже есть
        rec = parse(raw, self.own, self.cfg.tz)
        year, month = (rec["date"][:4] or "0000"), (rec["date"][5:7] or "00")
        blob, ext = _compress(raw)
        eml = self.cfg.eml_dir / year / month / (_h(key) + ext)
        eml.parent.mkdir(parents=True, exist_ok=True)
        eml.write_bytes(blob)
        self._save(key, rec, len(raw), str(eml.relative_to(self.cfg.data_dir)))
        self.new_keys.append(key)
        return key

    def _save(self, key, rec, size, eml_rel):
        q = quotes.split(rec["body"])
        att_texts = []
        self.db.execute("DELETE FROM attachments WHERE key=?", (key,))
        for idx, part in enumerate(rec["attachments"]):
            fname = part.get_filename() or "вложение_%d" % (idx + 1)
            try:
                data = part.get_payload(decode=True) or b""
            except Exception:
                data = b""
            text, note = attach.extract(fname, part.get_content_type(), data) if data else (None, "пусто")
            text_rel = None
            if text:
                p = self.cfg.md_dir / "att" / (rec["date"][:4] or "0000") / _h(key) / ("%02d_%s.md" % (idx + 1, _safe(fname)))
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("# Вложение: %s\n\nПисьмо: %s · %s\n\n%s\n" % (fname, rec["date"], rec["subject"], text),
                             encoding="utf-8")
                text_rel = str(p.relative_to(self.cfg.md_dir))
                att_texts.append("%s\n%s" % (fname, text))
            else:
                att_texts.append(fname)
            self.db.execute(
                "INSERT INTO attachments(key, idx, filename, content_type, size, text_path, text_chars, note) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (key, idx, fname, part.get_content_type(), len(data), text_rel, len(text or ""), note))
        self.db.execute(
            "INSERT OR REPLACE INTO messages(key, message_id, in_reply_to, refs, date, from_addr, from_name, to_addrs, "
            "cc_addrs, subject, direction, counterpart, body_new, quote, quote_kind, signature, has_attachments, size, "
            "eml_path, thread_id, parsed_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)",
            (key, rec["message_id"], rec["in_reply_to"], rec["refs"], rec["date"], rec["from_addr"], rec["from_name"],
             rec["to_addrs"], rec["cc_addrs"], rec["subject"], rec["direction"], rec["counterpart"], q["new"],
             q["quote"], q["kind"], q["signature"], 1 if rec["attachments"] else 0, size, eml_rel, PARSED_VERSION))
        self.db.execute("DELETE FROM fts WHERE key=?", (key,))
        self.db.execute("INSERT INTO fts(key, subject, sender, body, attachments) VALUES(?,?,?,?,?)",
                        (key, rec["subject"], "%s %s" % (rec["from_name"], rec["from_addr"]), q["new"],
                         "\n\n".join(att_texts)))

    def reparse(self, key):
        """Перечитать письмо из сохранённого оригинала (когда улучшили разбор)."""
        row = self.db.execute("SELECT eml_path, size FROM messages WHERE key=?", (key,)).fetchone()
        raw = read_raw(self.cfg.data_dir / row["eml_path"])
        self._save(key, parse(raw, self.own, self.cfg.tz), row["size"], row["eml_path"])
