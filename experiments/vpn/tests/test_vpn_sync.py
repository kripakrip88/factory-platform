"""Синхронизация VPN-сервера — на подставном Xray и подставном Odoo.

Запуск: python3 -m unittest discover -s experiments/vpn/tests
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import vpn_sync  # noqa: E402

# Ссылки из модуля Odoo — файл без импорта odoo, проверяем здесь же.
_spec = importlib.util.spec_from_file_location(
    "pmk_vpn_links", os.path.join(HERE, "../../odoo/addons/pmk_vpn/models/links.py"))
links = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(links)

CONFIG = {
    "inbounds": [
        {"tag": "reality-tcp", "listen": "0.0.0.0", "port": 443, "protocol": "vless",
         "settings": {"clients": [{"id": "A-1", "email": "anton", "flow": "xtls-rprx-vision"}]},
         "streamSettings": {"network": "tcp", "security": "reality", "realitySettings": {
             "dest": "127.0.0.1:8444", "serverNames": ["example.ru"],
             "privateKey": "PRIV", "shortIds": ["ab12"]}}},
        {"tag": "xhttp", "listen": "0.0.0.0", "port": 8443, "protocol": "vless",
         "settings": {"clients": [{"id": "A-1", "email": "anton-x"}]},
         "streamSettings": {"network": "xhttp", "security": "reality",
                            "xhttpSettings": {"path": "/p4th"},
                            "realitySettings": {"serverNames": ["example.ru"]}}},
    ],
    "outbounds": [{"protocol": "freedom", "tag": "direct"},
                  {"protocol": "blackhole", "tag": "block"}],
}


def _load(path):
    with open(path) as fh:
        return json.load(fh)


class FakeXray:
    """Отвечает как `xray api …` (форматы сняты с Xray 26.10.21)."""

    def __init__(self):
        self.users = {"reality-tcp": {"anton": "A-1"}, "xhttp": {"anton-x": "A-1"}}
        self.flows = {}
        self.stats = {}            # email → [up, down]
        self.online = {}           # email → [ip]
        self.rules = {}            # ruleTag → (email, ip)
        self.calls = []

    def __call__(self, args, timeout=10):
        if args[1] == "x25519":
            return "PrivateKey: PRIV\nPassword (PublicKey): PUBKEY\nHash32: zzz\n"
        cmd, rest = args[2], args[4:]
        self.calls.append(cmd)
        if cmd == "inbounduser":
            tag = rest[0].split("=", 1)[1]
            us = self.users.get(tag, {})
            if not us:
                return "{}\n"
            return json.dumps({"users": [
                {"account": {"_TypedMessage_": "xray.proxy.vless.Account", "id": u},
                 "email": e} for e, u in us.items()]})
        if cmd == "adu":
            spec = _load(rest[0])
            for ib in spec["inbounds"]:
                assert ib.get("port"), "adu без порта Xray не принимает"
                for c in ib["settings"]["clients"]:
                    self.users[ib["tag"]][c["email"]] = c["id"]
                    self.flows[(ib["tag"], c["email"])] = c.get("flow")
            return "Added %d user(s) in total.\n" % len(spec["inbounds"])
        if cmd == "rmu":
            tag = rest[0].split("=", 1)[1]
            for e in rest[1:]:
                self.users[tag].pop(e, None)
            return ""
        if cmd == "statsquery":
            out = [{"name": "user>>>%s>>>traffic>>>uplink" % e, "value": v[0]}
                   for e, v in self.stats.items()]
            out += [{"name": "user>>>%s>>>traffic>>>downlink" % e, "value": v[1]}
                    for e, v in self.stats.items()]
            self.stats = {}
            return json.dumps({"stat": out}) if out else "{}"
        if cmd == "statsonlineiplist":
            if not self.online:
                return "{}"
            return json.dumps({"users": [
                {"email": e, "ips": [{"ip": ip, "lastSeen": 1} for ip in ips]}
                for e, ips in self.online.items()]})
        if cmd == "lsrules":
            return json.dumps({"rules": [{"ruleTag": t, "tag": "block"} for t in self.rules]})
        if cmd == "adrules":
            for r in _load(rest[1])["routing"]["rules"]:
                self.rules[r["ruleTag"]] = (r["user"][0], r["source"][0])
            return "{}"
        if cmd == "rmrules":
            for t in rest:
                self.rules.pop(t, None)
            return "{}"
        raise AssertionError("неожиданная команда " + cmd)


class AgentTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.dir, "config.json")
        with open(self.config_path, "w") as fh:
            json.dump(CONFIG, fh)
        self.fx = FakeXray()
        self.sent = []
        self.reply = {"users": [], "limit": 3}
        self.down = False
        self.agent = vpn_sync.Agent(
            vpn_sync.Xray("127.0.0.1:10085", runner=self.fx), self.config_path,
            os.path.join(self.dir, "state.json"), "https://odoo/pmk_vpn/sync", "t",
            "203.0.113.5", block_seconds=900, post=self._post)

    def _post(self, payload):
        self.sent.append(payload)
        if self.down:
            raise urllib.error.URLError("down")
        return self.reply

    def test_server_info_sent_to_odoo(self):
        self.agent.cycle(now=1000)
        server = self.sent[0]["server"]
        self.assertEqual(server, {"host": "203.0.113.5", "port_tcp": 443, "sni": "example.ru",
                                  "sid": "ab12", "pbk": "PUBKEY", "port_xhttp": 8443,
                                  "xhttp_path": "/p4th"})
        self.assertTrue(links.server_ready(server))

    def test_users_added_to_both_inbounds_with_right_flow(self):
        self.reply = {"users": [{"email": "u12", "uuid": "U-12"}], "limit": 3}
        self.agent.cycle(now=1000)
        self.assertEqual(self.fx.users["reality-tcp"]["u12"], "U-12")
        self.assertEqual(self.fx.users["xhttp"]["u12"], "U-12")
        self.assertEqual(self.fx.flows[("reality-tcp", "u12")], "xtls-rprx-vision")
        self.assertIsNone(self.fx.flows[("xhttp", "u12")])

    def test_personal_key_never_touched(self):
        self.reply = {"users": [{"email": "u12", "uuid": "U-12"}]}
        self.fx.stats = {"anton": [5, 5]}
        self.fx.online = {"anton": ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4", "5.5.5.5"]}
        self.agent.cycle(now=1000)
        self.assertEqual(self.fx.users["reality-tcp"]["anton"], "A-1")
        self.assertEqual(self.fx.users["xhttp"]["anton-x"], "A-1")
        self.assertNotIn("anton", self.sent[0]["stats"])
        self.assertFalse(self.fx.rules)

    def test_removed_and_changed_keys(self):
        self.fx.users["reality-tcp"].update({"u1": "OLD", "u2": "X"})
        self.reply = {"users": [{"email": "u1", "uuid": "NEW"}]}
        self.agent.cycle(now=1000)
        self.assertEqual(self.fx.users["reality-tcp"].get("u1"), "NEW")
        self.assertNotIn("u2", self.fx.users["reality-tcp"])

    def test_no_restart_storm_when_nothing_changes(self):
        self.reply = {"users": [{"email": "u12", "uuid": "U-12"}]}
        self.agent.cycle(now=1000)
        self.fx.calls.clear()
        self.agent.cycle(now=1060)
        self.assertNotIn("adu", self.fx.calls)
        self.assertNotIn("rmu", self.fx.calls)

    def test_odoo_down_keeps_keys_and_traffic(self):
        self.reply = {"users": [{"email": "u12", "uuid": "U-12"}]}
        self.agent.cycle(now=1000)
        self.down = True
        self.fx.stats = {"u12": [100, 1000]}
        self.agent.cycle(now=1060)
        self.fx.users["reality-tcp"].pop("u12")   # Xray перезапустился — ключи из API пропали
        self.fx.stats = {"u12": [1, 1]}
        self.agent.cycle(now=1120)
        self.assertEqual(self.fx.users["reality-tcp"]["u12"], "U-12")
        self.down = False
        self.agent.cycle(now=1180)
        self.assertEqual(self.sent[-1]["stats"]["u12"]["down"], 1001)
        self.agent.cycle(now=1240)
        self.assertNotIn("u12", self.sent[-1]["stats"])  # отправленное не повторяется

    def test_fourth_device_blocked_only_for_that_key(self):
        self.reply = {"users": [{"email": "u12", "uuid": "U-12"}], "limit": 3}
        self.agent.cycle(now=1000)
        self.fx.online = {"u12": ["10.0.0.1", "10.0.0.2", "10.0.0.3"]}
        self.agent.cycle(now=1060)
        self.assertFalse(self.fx.rules)
        self.fx.online = {"u12": ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"]}
        self.agent.cycle(now=1120)
        self.assertEqual(list(self.fx.rules.values()), [("u12", "10.0.0.4")])
        self.assertEqual(self.sent[-1]["blocked"], {"u12": ["10.0.0.4"]})
        # Первое устройство ушло — четвёртое входит в лимит, правило снимается.
        self.fx.online = {"u12": ["10.0.0.2", "10.0.0.3", "10.0.0.4"]}
        self.agent.cycle(now=1180)
        self.assertFalse(self.fx.rules)

    def test_block_restored_after_xray_restart(self):
        self.reply = {"users": [{"email": "u12", "uuid": "U-12"}], "limit": 1}
        self.agent.cycle(now=1000)
        self.fx.online = {"u12": ["10.0.0.1", "10.0.0.2"]}
        self.agent.cycle(now=1060)
        self.assertEqual(len(self.fx.rules), 1)
        self.fx.rules.clear()                       # перезапуск Xray
        self.agent.cycle(now=1120)
        self.assertEqual(len(self.fx.rules), 1)

    def test_prepare_config_idempotent(self):
        cfg = dict(CONFIG, inbounds=[dict(CONFIG["inbounds"][0], tag=None)])
        with open(self.config_path, "w") as fh:
            json.dump(cfg, fh)
        self.assertTrue(vpn_sync.prepare_config(self.config_path, "127.0.0.1:10085"))
        self.assertFalse(vpn_sync.prepare_config(self.config_path, "127.0.0.1:10085"))
        data = _load(self.config_path)
        self.assertEqual(data["inbounds"][0]["tag"], "reality-tcp")
        self.assertTrue(data["policy"]["levels"]["0"]["statsUserOnline"])
        self.assertEqual(data["api"]["listen"], "127.0.0.1:10085")


class LinksTest(unittest.TestCase):

    def test_links_match_working_key(self):
        """Ссылка — того же вида, что и проверенный вручную рабочий ключ 27.10."""
        server = {"host": "31.77.141.89", "sni": "mediagenstvo.ru", "pbk": "PBK",
                  "sid": "sid1", "port_tcp": 443, "port_xhttp": 8443,
                  "xhttp_path": "/d0966e7e961e"}
        self.assertEqual(
            links.vless_main("U", server, "Media"),
            "vless://U@31.77.141.89:443?encryption=none&flow=xtls-rprx-vision"
            "&security=reality&sni=mediagenstvo.ru&fp=chrome&pbk=PBK&sid=sid1&type=tcp#Media")
        self.assertEqual(
            links.vless_reserve("U", server, "Media-2"),
            "vless://U@31.77.141.89:8443?encryption=none&security=reality"
            "&sni=mediagenstvo.ru&fp=chrome&pbk=PBK&sid=sid1&type=xhttp"
            "&path=%2Fd0966e7e961e&mode=auto#Media-2")

    def test_human_bytes(self):
        self.assertEqual(links.human_bytes(0), "0 Б")
        self.assertEqual(links.human_bytes(1536), "1,5 КБ")
        self.assertEqual(links.human_bytes(3 * 1024 ** 3), "3,0 ГБ")


if __name__ == "__main__":
    unittest.main()
