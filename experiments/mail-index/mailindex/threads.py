"""Цепочки переписки: письма группируются по Message-ID (References / In-Reply-To), без них — по теме и
собеседнику в пределах 90 дней. Каждая цепочка → один Markdown-файл: обе стороны по порядку, с временем ответа.
Перерисовываются только изменившиеся цепочки (хэш состава)."""
import hashlib
import re
from datetime import datetime, timedelta

from .quotes import first_level

PREFIX = re.compile(r"^\s*((re|fw|fwd|ha|отв|ответ|пересл|переслано|aw|wg)\s*(\[\d+\]|\(\d+\))?\s*:\s*)+", re.I)
SUBJECT_WINDOW = timedelta(days=90)
QUOTE_MAX = 3000
# Служебные папки и отправители: уведомления, рассылки, чеки — не переписка с клиентами → md/service/
SERVICE_FOLDERS = {"INBOX/Newsletters", "INBOX/Receipts", "INBOX/Social", "INBOX/News", "Модуль рассылка",
                   "INBOX/Авито Фарпост Юла"}
SERVICE_FROM = re.compile(r"(no-?reply|noreply|do-?not-?reply|mailer-daemon|notif|news(letter)?@|info@.*(bank|ozon|"
                          r"wildberries|avito|farpost)|robot@|postmaster@)", re.I)


def is_service(db, msgs):
    for m in msgs:
        folders = {r[0] for r in db.execute("SELECT folder FROM locations WHERE key=?", (m["key"],))}
        if m["direction"] == "out":
            return False
        if not (folders and folders <= SERVICE_FOLDERS) and not SERVICE_FROM.search(m["from_addr"] or ""):
            return False
    return True


def norm_subject(s):
    s = PREFIX.sub("", s or "")
    return re.sub(r"\s+", " ", s).strip().lower()


def _dt(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _slug(s, n=50):
    s = re.sub(r"[^\w\- ]+", "", norm_subject(s) or "без темы", flags=re.U)
    return re.sub(r"\s+", "-", s).strip("-")[:n] or "без-темы"


def _human_delta(d):
    mins = int(d.total_seconds() // 60)
    if mins < 60:
        return "%d мин" % max(mins, 0)
    h, m = divmod(mins, 60)
    if h < 48:
        return "%d ч %d мин" % (h, m) if m else "%d ч" % h
    return "%d дн" % (h // 24)


def _fmt(dt):
    return dt.strftime("%d.%m.%Y %H:%M") if dt else "дата неизвестна"


def assign(db):
    """Проставить thread_id всем письмам. Полный пересчёт: 40 тыс. писем — секунды."""
    rows = db.execute("SELECT key, message_id, in_reply_to, refs, date, subject, counterpart FROM messages "
                      "ORDER BY date, key").fetchall()
    by_mid, thread_of, last_by_subject = {}, {}, {}
    for r in rows:
        mid = (r["message_id"] or "").strip().strip("<>").lower()
        cands = [x for x in (r["refs"] or "").split() if x] + ([r["in_reply_to"]] if r["in_reply_to"] else [])
        tid = None
        for c in cands:          # первым — корень цепочки (References идут от старых к новым)
            if c in by_mid:
                tid = thread_of[by_mid[c]]
                break
        skey = (norm_subject(r["subject"]), r["counterpart"] or "")
        dt = _dt(r["date"])
        if tid is None and skey[0]:
            prev = last_by_subject.get(skey)
            if prev and dt and prev[1] and dt - prev[1] <= SUBJECT_WINDOW:
                tid = prev[0]
        if tid is None:
            tid = hashlib.sha1(r["key"].encode()).hexdigest()[:12]
        thread_of[r["key"]] = tid
        if mid:
            by_mid.setdefault(mid, r["key"])
        if skey[0] and dt:
            last_by_subject[skey] = (tid, dt)
    db.executemany("UPDATE messages SET thread_id=? WHERE key=?", [(t, k) for k, t in thread_of.items()])
    db.commit()
    return len(set(thread_of.values()))


def render_all(cfg, db, log=print):
    known_mids = {(r[0] or "").strip().strip("<>").lower() for r in db.execute("SELECT message_id FROM messages")}
    tids = [r[0] for r in db.execute("SELECT DISTINCT thread_id FROM messages WHERE thread_id IS NOT NULL")]
    changed = 0
    for tid in tids:
        msgs = db.execute("SELECT * FROM messages WHERE thread_id=? ORDER BY date, key", (tid,)).fetchall()
        sig = hashlib.sha1(("|".join("%s:%s" % (m["key"], m["parsed_version"]) for m in msgs)).encode()).hexdigest()
        old = db.execute("SELECT sig, md_path FROM threads WHERE thread_id=?", (tid,)).fetchone()
        if old and old["sig"] == sig and old["md_path"] and (cfg.md_dir / old["md_path"]).exists():
            continue
        path = _render(cfg, db, tid, msgs, known_mids, is_service(db, msgs))
        if old and old["md_path"] and old["md_path"] != path:
            (cfg.md_dir / old["md_path"]).unlink(missing_ok=True)
        cp = next((m["counterpart"] for m in msgs if m["counterpart"]), "")
        db.execute(
            "INSERT OR REPLACE INTO threads(thread_id, subject, counterpart, first_date, last_date, count, "
            "last_direction, md_path, sig) VALUES(?,?,?,?,?,?,?,?,?)",
            (tid, msgs[0]["subject"], cp, msgs[0]["date"], msgs[-1]["date"], len(msgs), msgs[-1]["direction"],
             path, sig))
        changed += 1
    # цепочки, которых больше нет (письма переехали в другую цепочку)
    for r in db.execute("SELECT thread_id, md_path FROM threads WHERE thread_id NOT IN "
                        "(SELECT DISTINCT thread_id FROM messages WHERE thread_id IS NOT NULL)").fetchall():
        if r["md_path"]:
            (cfg.md_dir / r["md_path"]).unlink(missing_ok=True)
        db.execute("DELETE FROM threads WHERE thread_id=?", (r["thread_id"],))
    db.commit()
    return changed


def _who(m):
    if m["direction"] == "out":
        to = m["to_addrs"].split(",")[0].strip() if m["to_addrs"] else "?"
        return "Мы — %s → %s" % (m["from_name"] or m["from_addr"], to)
    name = m["from_name"] or m["from_addr"]
    return "%s <%s> → нам" % (name, m["from_addr"]) if m["from_name"] else "%s → нам" % m["from_addr"]


def _title(s):
    return PREFIX.sub("", s or "").strip() or "(без темы)"


def _render(cfg, db, tid, msgs, known_mids, service=False):
    first, last = _dt(msgs[0]["date"]), _dt(msgs[-1]["date"])
    subject = _title(msgs[0]["subject"])
    cp = next((m["counterpart"] for m in msgs if m["counterpart"]), "")
    cp_name = next((m["from_name"] for m in msgs if m["direction"] == "in" and m["from_name"]), "")
    n_in = sum(1 for m in msgs if m["direction"] == "in")
    lines = [
        "---",
        "thread: %s" % tid,
        "subject: %s" % subject.replace("\n", " "),
        "counterpart: %s" % cp,
        "first: %s" % (msgs[0]["date"] or ""),
        "last: %s" % (msgs[-1]["date"] or ""),
        "messages: %d (от собеседника %d, наших %d)" % (len(msgs), n_in, len(msgs) - n_in),
        "last_from: %s" % ("мы" if msgs[-1]["direction"] == "out" else "собеседник"),
        "---",
        "",
        "# %s" % subject,
        "",
        "Собеседник: %s%s · %d писем · %s — %s" % (
            (cp_name + " ") if cp_name else "", "<%s>" % cp if cp else "", len(msgs),
            first.strftime("%d.%m.%Y") if first else "?", last.strftime("%d.%m.%Y") if last else "?"),
        "",
    ]
    prev = None
    for m in msgs:
        dt = _dt(m["date"])
        gap = ""
        if prev is not None and dt and prev[1]:
            d = dt - prev[1]
            gap = (" · ответ через %s" if m["direction"] != prev[0] else " · ещё через %s") % _human_delta(d)
        lines.append("## %s · %s%s" % (_fmt(dt), _who(m), gap))
        if m["subject"] and norm_subject(m["subject"]) != norm_subject(subject):
            lines.append("Тема: %s" % m["subject"])
        lines.append("")
        lines.append(m["body_new"] or "_(пустое письмо)_")
        if m["quote_kind"] == "quote" and m["quote"]:
            parent = m["in_reply_to"] or ((m["refs"] or "").split() or [""])[-1]
            if not parent or parent not in known_mids:
                q, deeper = first_level(m["quote"])
                if q:
                    q = q[:QUOTE_MAX] + ("\n…" if len(q) > QUOTE_MAX else "")
                    lines += ["", "> _Цитата (письма, на которое отвечают, в архиве нет):_"] + \
                             ["> " + l if l.strip() else ">" for l in q.split("\n")]
                    if deeper:
                        lines.append("> _…ниже в цитате более ранняя переписка — полностью в оригинале письма_")
        atts = db.execute("SELECT filename, text_path, note FROM attachments WHERE key=? ORDER BY idx",
                          (m["key"],)).fetchall()
        if atts:
            items = []
            for a in atts:
                if a["text_path"]:
                    items.append("[%s](<../../%s>)" % (a["filename"], a["text_path"]))
                else:
                    items.append("%s%s" % (a["filename"], " (%s)" % a["note"] if a["note"] else ""))
            lines += ["", "Вложения: " + "; ".join(items)]
        lines.append("")
        prev = (m["direction"], dt)
    year = first.strftime("%Y") if first else "0000"
    rel = "%s/%s/%s_%s_%s.md" % ("service" if service else "threads", year, first.strftime("%Y-%m-%d") if first else "0000-00-00",
                                       _slug(subject), tid[:8])
    p = cfg.md_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return rel
