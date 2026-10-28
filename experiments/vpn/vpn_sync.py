#!/usr/bin/env python3
"""Синхронизация VPN-сервера с Odoo (модуль pmk_vpn). Только стандартная библиотека.

Раз в минуту:
  1. забирает у Xray прирост трафика и адреса, с которых сидят сотрудники;
  2. адреса сверх лимита (3 устройства) отключает — только у этого ключа;
  3. отдаёт всё это в Odoo (POST /pmk_vpn/sync) и получает список ключей;
  4. добавляет в Xray новые ключи и убирает лишние — без перезапуска, у
     остальных соединения не рвутся.

Управляет только ключами вида «u<номер>» (сотрудники из Odoo). Остальные —
например личный ключ Антона «anton» — не трогает, не считает и не ограничивает.

Нет связи с Odoo — работают ключи из последнего удачного ответа, трафик
копится и уходит со следующей удачной отправкой.

Запуск:  vpn_sync.py                  — раз в INTERVAL секунд, бесконечно (systemd)
         vpn_sync.py --once           — один проход
         vpn_sync.py --prepare-config — включить API и статистику в конфиге Xray
Настройки — переменные окружения (/etc/vpn-sync/env), см. README.md.
"""
import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

MANAGED = re.compile(r"^u\d+$")
TAG_TCP = "reality-tcp"
TAG_XHTTP = "xhttp"
RULE_PREFIX = "lim-"
FLOW_TCP = "xtls-rprx-vision"

log = logging.getLogger("vpn-sync")


def env(name, default=None):
    return os.environ.get(name, default)


# ── Xray ──────────────────────────────────────────────────────────────────


class Xray:
    """Тонкая обёртка над `xray api …`. runner подменяется в тестах."""

    def __init__(self, api_addr, binary="xray", runner=None):
        self.api_addr = api_addr
        self.binary = binary
        self.runner = runner or self._run

    @staticmethod
    def _run(args, timeout=10):
        res = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if res.returncode != 0:
            raise RuntimeError("%s: %s" % (" ".join(args[:3]), (res.stderr or res.stdout).strip()))
        return res.stdout

    def api(self, cmd, *args):
        out = self.runner([self.binary, "api", cmd, "--server=" + self.api_addr, *args])
        return out

    def api_json(self, cmd, *args):
        out = self.api(cmd, *args).strip()
        # Перед JSON xray иногда печатает строки-пояснения — берём с первой «{».
        start = out.find("{")
        return json.loads(out[start:]) if start >= 0 else {}

    def users(self, tag):
        """{email: uuid} ключей сотрудников во входе tag."""
        data = self.api_json("inbounduser", "-tag=" + tag)
        result = {}
        for u in data.get("users") or []:
            email = u.get("email") or ""
            if MANAGED.match(email):
                result[email] = (u.get("account") or {}).get("id")
        return result

    def add_users(self, inbound, clients):
        """inbound — описание входа из конфига (tag, listen, port, protocol)."""
        spec = {"inbounds": [{
            "tag": inbound["tag"], "listen": inbound.get("listen", "0.0.0.0"),
            "port": inbound["port"], "protocol": inbound["protocol"],
            "settings": {"clients": clients, "decryption": "none"}}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(spec, fh)
            path = fh.name
        try:
            self.api("adu", path)
        finally:
            os.unlink(path)

    def remove_users(self, tag, emails):
        if emails:
            self.api("rmu", "-tag=" + tag, *sorted(emails))

    def traffic(self):
        """{email: [вверх, вниз]} прирост с прошлого раза (счётчики сбрасываются)."""
        data = self.api_json("statsquery", "-pattern", "user>>>", "-reset")
        result = {}
        for st in data.get("stat") or []:
            parts = (st.get("name") or "").split(">>>")
            if len(parts) != 4 or not MANAGED.match(parts[1]):
                continue
            pair = result.setdefault(parts[1], [0, 0])
            pair[0 if parts[3] == "uplink" else 1] += int(st.get("value") or 0)
        return result

    def online(self):
        """{email: [адреса]} — кто сейчас подключён и откуда."""
        data = self.api_json("statsonlineiplist", "-all")
        result = {}
        for u in data.get("users") or []:
            email = u.get("email") or ""
            if MANAGED.match(email):
                result[email] = sorted({i["ip"] for i in u.get("ips") or [] if i.get("ip")})
        return result

    def rule_tags(self):
        data = self.api_json("lsrules")
        return {r.get("ruleTag") for r in data.get("rules") or []
                if (r.get("ruleTag") or "").startswith(RULE_PREFIX)}

    def add_block(self, tag, email, ip):
        spec = {"routing": {"rules": [{"ruleTag": tag, "type": "field", "user": [email],
                                       "source": [ip], "outboundTag": "block"}]}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(spec, fh)
            path = fh.name
        try:
            self.api("adrules", "-append", path)
        finally:
            os.unlink(path)

    def remove_rules(self, tags):
        if tags:
            self.api("rmrules", *sorted(tags))

    def public_key(self, private_key):
        out = self.runner([self.binary, "x25519", "-i", private_key])
        # Xray 26: «Password (PublicKey): …»; старые — «Public key: …».
        m = re.search(r"^(?:Password(?: \(PublicKey\))?|Public key)\s*:\s*(\S+)", out, re.M | re.I)
        return m.group(1) if m else None


# ── чистая логика (проверяется тестами без Xray) ──────────────────────────


def rule_tag(email, ip):
    return RULE_PREFIX + email + "-" + re.sub(r"[^0-9A-Za-z]", "_", ip)


def plan_blocks(online, first_seen, blocks, limit, now, block_seconds):
    """Какие адреса сейчас не пускать.

    online     — {email: [адреса]} сейчас;
    first_seen — {email: {адрес: когда впервые увидели}} — меняется на месте;
    blocks     — {ruleTag: {"email", "ip", "until"}} прошлого прохода;
    → новые blocks. Пускаем первые limit адресов по времени появления: кто
    подключился раньше, тот и остаётся; лишний — отключён на block_seconds
    (и дольше, пока он лишний).
    """
    for email in list(first_seen):
        if email not in online:
            del first_seen[email]
    for email, ips in online.items():
        seen = first_seen.setdefault(email, {})
        for ip in list(seen):
            if ip not in ips:
                del seen[ip]
        for ip in ips:
            seen.setdefault(ip, now)

    result = {tag: b for tag, b in blocks.items() if b["until"] > now}
    for email, seen in first_seen.items():
        ordered = sorted(seen, key=lambda ip: (seen[ip], ip))
        allowed = set(ordered[:limit])
        for ip in ordered:
            tag = rule_tag(email, ip)
            if ip in allowed:
                # Старое устройство ушло — отключённый раньше входит в лимит.
                result.pop(tag, None)
            else:
                result[tag] = {"email": email, "ip": ip, "until": now + block_seconds}
    return result


def plan_users(desired, current):
    """desired, current — {email: uuid}. → (удалить, добавить)."""
    remove = {e for e, u in current.items() if desired.get(e) != u}
    add = {e: u for e, u in desired.items() if current.get(e) != u}
    return remove, add


def server_info(config, host, xray):
    """Параметры для ссылок — из конфига Xray. Odoo собирает по ним QR-коды."""
    info = {"host": host}
    for ib in config.get("inbounds") or []:
        stream = ib.get("streamSettings") or {}
        reality = stream.get("realitySettings") or {}
        if ib.get("tag") == TAG_TCP:
            info["port_tcp"] = ib["port"]
            info["sni"] = (reality.get("serverNames") or [None])[0]
            info["sid"] = (reality.get("shortIds") or [None])[0]
            if reality.get("privateKey"):
                info["pbk"] = xray.public_key(reality["privateKey"])
        elif ib.get("tag") == TAG_XHTTP:
            info["port_xhttp"] = ib["port"]
            info["xhttp_path"] = (stream.get("xhttpSettings") or {}).get("path")
    return info


# ── проход ────────────────────────────────────────────────────────────────


class Agent:

    def __init__(self, xray, config_path, state_path, odoo_url, token, host,
                 block_seconds=900, post=None):
        self.xray = xray
        self.config_path = config_path
        self.state_path = state_path
        self.odoo_url = odoo_url
        self.token = token
        self.host = host
        self.block_seconds = block_seconds
        self.post = post or self._post
        self._server = None

    # состояние — между проходами и перезапусками
    def load_state(self):
        try:
            with open(self.state_path) as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            state = {}
        for k, v in (("users", {}), ("first_seen", {}), ("blocks", {}),
                     ("pending", {}), ("limit", 3)):
            state.setdefault(k, v)
        return state

    def save_state(self, state):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(state, fh)
        os.replace(tmp, self.state_path)

    def config(self):
        with open(self.config_path) as fh:
            return json.load(fh)

    def _post(self, payload):
        req = urllib.request.Request(
            self.odoo_url, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json", "X-Pmk-Vpn-Token": self.token})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())

    def cycle(self, now=None):
        now = int(now or time.time())
        state = self.load_state()
        config = self.config()
        inbounds = {ib.get("tag"): ib for ib in config.get("inbounds") or []}
        if self._server is None:
            self._server = server_info(config, self.host, self.xray)

        # 1. трафик и адреса
        for email, (up, down) in self.xray.traffic().items():
            pend = state["pending"].setdefault(email, [0, 0])
            pend[0] += up
            pend[1] += down
        online = self.xray.online()

        # 2. лишние устройства
        state["blocks"] = plan_blocks(online, state["first_seen"], state["blocks"],
                                      int(state["limit"]), now, self.block_seconds)
        blocked = {}
        for b in state["blocks"].values():
            blocked.setdefault(b["email"], []).append(b["ip"])

        # 3. Odoo
        stats = {}
        for email in set(state["pending"]) | set(online):
            up, down = state["pending"].get(email, [0, 0])
            stats[email] = {"up": up, "down": down, "ips": online.get(email, [])}
        try:
            resp = self.post({"server": self._server, "stats": stats, "blocked": blocked})
            state["pending"] = {}
            state["users"] = {u["email"]: u["uuid"] for u in resp.get("users") or []
                              if MANAGED.match(u.get("email") or "") and u.get("uuid")}
            state["limit"] = int(resp.get("limit") or state["limit"])
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.warning("Odoo недоступен (%s) — ключи из прошлого ответа", exc)

        # 4. ключи в Xray
        for tag in (TAG_TCP, TAG_XHTTP):
            ib = inbounds.get(tag)
            if not ib:
                continue
            remove, add = plan_users(state["users"], self.xray.users(tag))
            if remove:
                self.xray.remove_users(tag, remove)
                log.info("%s: убраны %s", tag, ", ".join(sorted(remove)))
            if add:
                clients = [dict({"id": u, "email": e},
                                **({"flow": FLOW_TCP} if tag == TAG_TCP else {}))
                           for e, u in sorted(add.items())]
                self.xray.add_users(ib, clients)
                log.info("%s: добавлены %s", tag, ", ".join(sorted(add)))

        # 5. правила отключения лишних адресов
        present = self.xray.rule_tags()
        wanted = set(state["blocks"])
        self.xray.remove_rules(present - wanted)
        for tag in sorted(wanted - present):
            b = state["blocks"][tag]
            self.xray.add_block(tag, b["email"], b["ip"])
            log.info("лишнее устройство: %s %s отключено", b["email"], b["ip"])

        self.save_state(state)
        return state


# ── подготовка конфига Xray ───────────────────────────────────────────────


def prepare_config(path, api_addr):
    """Включить в конфиге API, статистику по пользователям и метки входов.

    Идемпотентно. Возвращает True, если конфиг изменён (нужен перезапуск Xray).
    """
    with open(path) as fh:
        config = json.load(fh)
    before = json.dumps(config, sort_keys=True)
    config["api"] = {"tag": "api", "listen": api_addr,
                     "services": ["HandlerService", "StatsService", "RoutingService"]}
    config.setdefault("stats", {})
    level = config.setdefault("policy", {}).setdefault("levels", {}).setdefault("0", {})
    level.update({"statsUserUplink": True, "statsUserDownlink": True, "statsUserOnline": True})
    for ib in config.get("inbounds") or []:
        net = (ib.get("streamSettings") or {}).get("network")
        if not ib.get("tag"):
            ib["tag"] = TAG_XHTTP if net == "xhttp" else TAG_TCP
    outs = config.setdefault("outbounds", [])
    if not any(o.get("tag") == "block" for o in outs):
        outs.append({"protocol": "blackhole", "tag": "block"})
    config.setdefault("routing", {}).setdefault("rules", [])
    if json.dumps(config, sort_keys=True) == before:
        return False
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--prepare-config", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    config_path = env("XRAY_CONFIG", "/usr/local/etc/xray/config.json")
    api_addr = env("XRAY_API", "127.0.0.1:10085")
    if args.prepare_config:
        changed = prepare_config(config_path, api_addr)
        print("changed" if changed else "unchanged")
        return 0

    for name in ("ODOO_URL", "SYNC_TOKEN", "VPN_HOST"):
        if not env(name):
            log.error("не задан %s (/etc/vpn-sync/env)", name)
            return 2
    agent = Agent(Xray(api_addr, env("XRAY_BIN", "xray")), config_path,
                  env("STATE", "/var/lib/vpn-sync/state.json"),
                  env("ODOO_URL"), env("SYNC_TOKEN"), env("VPN_HOST"),
                  block_seconds=int(env("BLOCK_MINUTES", "15")) * 60)
    interval = int(env("INTERVAL", "60"))
    while True:
        try:
            agent.cycle()
        except Exception:  # noqa: BLE001 — один сбойный проход не роняет службу
            log.exception("проход не удался")
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
