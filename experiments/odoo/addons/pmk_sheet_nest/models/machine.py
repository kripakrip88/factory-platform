# -*- coding: utf-8 -*-
"""Профиль станка для раскроя (время в сводке «станок, мин») — 15.10.2026.

Профиль — скорости резки и врезки по толщине, холостой ход, гравировка: данные завода,
в открытый репозиторий не кладутся — живут в базе, правит администратор. Первый профиль
(3 кВт) собран по 559 программам станка — предварительный: время в сводке — нижняя граница,
уточняется по статистике. Проверка — тем же sheet_nest.machine.load, что у движка (отдельным
процессом: движок в процесс Odoo не импортируем).
"""
import json
import os
import subprocess
import sys

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .run import LIB_DIR

_CHECK = ("import sys, json; sys.path.insert(0, sys.argv[1]); "
          "from sheet_nest import machine\n"
          "try:\n    machine.load(json.loads(sys.stdin.read()))\n"
          "except machine.MachineError as e:\n    print(e); sys.exit(2)")


class LaserMachineProfile(models.Model):
    _inherit = "pmk.laser.machine"

    nest_profile_json = fields.Text(
        "Профиль для раскроя (JSON)", groups="base.group_system",
        help="Скорости резки и врезки по толщине, холостой ход, гравировка — для времени в сводке "
             "раскроя. Данные завода: только в базе, в репозиторий не кладутся. Формат — "
             "pmk_sheet_nest/lib (sheet_nest/machine.py).")
    nest_profile_info = fields.Char("Профиль раскроя", compute="_compute_nest_profile_info")

    @api.depends("nest_profile_json")
    def _compute_nest_profile_info(self):
        for machine in self.sudo():
            p = machine._nest_profile()
            if not p:
                machine.nest_profile_info = False
                continue
            bits = [p.get("name") or "профиль"]
            if p.get("preliminary"):
                bits.append("предварительный")
            bits.append("толщин %d" % len(p.get("cut") or []))
            if p.get("source"):
                bits.append(str(p["source"]))
            if p.get("updated"):
                bits.append("от %s" % p["updated"])
            machine.nest_profile_info = " · ".join(bits)

    def _nest_profile(self):
        self.ensure_one()
        raw = self.sudo().nest_profile_json
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    @api.constrains("nest_profile_json")
    def _check_nest_profile(self):
        for machine in self.sudo():
            raw = machine.nest_profile_json
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except ValueError as e:
                raise ValidationError("Профиль станка «%s»: не JSON (%s)." % (machine.name, e))
            if not os.path.isdir(os.path.join(LIB_DIR, "sheet_nest")):
                continue
            proc = subprocess.run([sys.executable, "-c", _CHECK, LIB_DIR], input=json.dumps(data),
                                  capture_output=True, text=True, timeout=30)
            if proc.returncode == 2:
                raise ValidationError(proc.stdout.strip() or "Профиль станка не прошёл проверку.")
            if proc.returncode:
                raise ValidationError("Профиль станка не проверить: %s" % (proc.stderr.strip()[-300:]))

    @api.model
    def _nest_profiles(self, first=None):
        """Профили всех станков с профилем — станок программы первым (input.json "machines")."""
        machines = self.sudo().search([("nest_profile_json", "!=", False)])
        if first:
            machines = (first.sudo() & machines) | (machines - first.sudo())
        return [p for p in (m._nest_profile() for m in machines) if p]
