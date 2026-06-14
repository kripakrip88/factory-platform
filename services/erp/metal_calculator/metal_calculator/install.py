# Copyright (c) 2026, Factory Platform and contributors
# -*- coding: utf-8 -*-

import frappe

from metal_calculator.seed import seed_all


def after_install():
	"""Заливаем справочники ГОСТ сразу после установки аппы."""
	created = seed_all()
	frappe.logger().info(f"metal_calculator: seeded {created}")
