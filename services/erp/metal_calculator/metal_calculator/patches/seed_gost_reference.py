# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-
"""Патч: догрузить справочники ГОСТ (идемпотентно). Запускается на bench migrate."""

from metal_calculator.seed import seed_all


def execute():
	seed_all()
