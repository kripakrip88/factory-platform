"""Поиск по словам (FTS5 trigram): находит по части слова, без морфологии. Результат — цепочки переписки
(путь к Markdown), а не отдельные письма: Claude читает найденные цепочки целиком."""
import re


def _fts_query(text):
    words = [w for w in re.findall(r"[\w@.\-]+", text, flags=re.U) if len(w) >= 3]
    if not words:
        return None
    return " AND ".join('"%s"' % w.replace('"', '""') for w in words)


def search(db, text, who=None, since=None, until=None, direction=None, limit=10):
    q = _fts_query(text) if text else None
    where, args = [], []
    if who:
        where.append("(m.from_addr LIKE ? OR m.from_name LIKE ? OR m.counterpart LIKE ? OR m.to_addrs LIKE ?)")
        args += ["%" + who.lower() + "%", "%" + who + "%", "%" + who.lower() + "%", "%" + who.lower() + "%"]
    if since:
        where.append("m.date >= ?")
        args.append(since)
    if until:
        where.append("m.date < ?")
        args.append(until + "T99")
    if direction:
        where.append("m.direction = ?")
        args.append(direction)
    cond = (" AND " + " AND ".join(where)) if where else ""
    if q:
        sql = ("SELECT m.thread_id, m.date, m.subject, m.counterpart, "
               "snippet(fts, -1, '«', '»', ' … ', 14) AS snip, bm25(fts) AS score "
               "FROM fts JOIN messages m ON m.key = fts.key WHERE fts MATCH ?" + cond + " ORDER BY score LIMIT 400")
        rows = db.execute(sql, [q] + args).fetchall()
    else:
        sql = ("SELECT m.thread_id, m.date, m.subject, m.counterpart, substr(m.body_new, 1, 160) AS snip, 0 AS score "
               "FROM messages m WHERE 1=1" + cond + " ORDER BY m.date DESC LIMIT 400")
        rows = db.execute(sql, args).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["thread_id"] in seen:
            continue
        seen.add(r["thread_id"])
        t = db.execute("SELECT * FROM threads WHERE thread_id=?", (r["thread_id"],)).fetchone()
        out.append({
            "thread": r["thread_id"], "md": t["md_path"] if t else None,
            "subject": t["subject"] if t else r["subject"], "counterpart": t["counterpart"] if t else r["counterpart"],
            "first": t["first_date"] if t else r["date"], "last": t["last_date"] if t else r["date"],
            "count": t["count"] if t else 1, "hit_date": r["date"],
            "snippet": re.sub(r"\s+", " ", r["snip"] or "").strip(),
        })
        if len(out) >= limit:
            break
    return out
