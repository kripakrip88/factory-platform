"""CLI:
  python -m mailindex sync [--limit N]   — забрать новые письма + пересобрать изменившиеся цепочки
  python -m mailindex build             — только пересобрать цепочки
  python -m mailindex reparse           — перечитать все письма из сохранённых оригиналов (после правки разбора)
  python -m mailindex search "текст" [--who X] [--since 2025-01-01] [--until …] [--in|--out] [-n 10] [--json]
  python -m mailindex stats
"""
import argparse
import fcntl
import json
import sys
import time
from datetime import datetime, timezone

from . import store, threads
from .config import Config


def _log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def cmd_sync(cfg, db, args):
    from .imap import Fetcher
    from .ingest import Ingest
    lock = open(cfg.data_dir / ".sync.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        _log("предыдущий запуск ещё идёт — выхожу")
        return 0
    f = Fetcher(cfg, db, _log)
    ing = Ingest(cfg, db, _log)
    f.connect()
    try:
        n = f.run(ing.store_raw, limit=args.limit)
    finally:
        f.close()
    _log("новых писем: %d" % n)
    if n or args.force_build:
        cmd_build(cfg, db, args)
    (cfg.data_dir / "last_ok").write_text(datetime.now(timezone.utc).isoformat(timespec="seconds") + " %d\n" % n)
    return 0


def cmd_build(cfg, db, args):
    t = threads.assign(db)
    c = threads.render_all(cfg, db, _log)
    _log("цепочек: %d, перерисовано: %d" % (t, c))
    return 0


def cmd_reparse(cfg, db, args):
    from .ingest import Ingest
    ing = Ingest(cfg, db, _log)
    keys = [r[0] for r in db.execute("SELECT key FROM messages")]
    for i, k in enumerate(keys, 1):
        ing.reparse(k)
        if i % 500 == 0:
            db.commit()
            _log("перечитано %d/%d" % (i, len(keys)))
    db.execute("UPDATE threads SET sig=NULL")   # перечитали — перерисовать все цепочки
    db.commit()
    return cmd_build(cfg, db, args)


def cmd_search(cfg, db, args):
    from .search import search
    direction = "in" if args.inbound else ("out" if args.outbound else None)
    res = search(db, " ".join(args.text), who=args.who, since=args.since, until=args.until,
                 direction=direction, limit=args.n)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    if not res:
        print("ничего не найдено")
        return 1
    for r in res:
        print("%s — %s · %s · писем %s · %s…%s" % (
            r["md"] and str(cfg.md_dir / r["md"]), r["subject"], r["counterpart"], r["count"],
            (r["first"] or "")[:10], (r["last"] or "")[:10]))
        if r["snippet"]:
            print("    " + r["snippet"][:300])
    return 0


def cmd_stats(cfg, db, args):
    q = lambda s: db.execute(s).fetchone()[0]
    print("писем: %d (входящих %d, наших %d)" % (
        q("SELECT count(*) FROM messages"), q("SELECT count(*) FROM messages WHERE direction='in'"),
        q("SELECT count(*) FROM messages WHERE direction='out'")))
    print("цепочек: %d; вложений: %d, из них с текстом %d" % (
        q("SELECT count(*) FROM threads"), q("SELECT count(*) FROM attachments"),
        q("SELECT count(*) FROM attachments WHERE text_path IS NOT NULL")))
    print("период: %s — %s" % (q("SELECT min(date) FROM messages"), q("SELECT max(date) FROM messages")))
    for r in db.execute("SELECT name, last_uid, last_sync FROM folders ORDER BY name"):
        print("  %-40s uid %-8s %s" % (r["name"], r["last_uid"], r["last_sync"]))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="mailindex")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--limit", type=int, help="не больше N последних писем на папку (для пробы)")
    s.add_argument("--force-build", action="store_true")
    sub.add_parser("build")
    sub.add_parser("reparse")
    sub.add_parser("stats")
    s = sub.add_parser("search")
    s.add_argument("text", nargs="*")
    s.add_argument("--who")
    s.add_argument("--since")
    s.add_argument("--until")
    s.add_argument("--in", dest="inbound", action="store_true")
    s.add_argument("--out", dest="outbound", action="store_true")
    s.add_argument("-n", type=int, default=10)
    s.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    cfg = Config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    db = store.connect(cfg.db_path)
    return {"sync": cmd_sync, "build": cmd_build, "reparse": cmd_reparse,
            "search": cmd_search, "stats": cmd_stats}[args.cmd](cfg, db, args)


if __name__ == "__main__":
    sys.exit(main())
