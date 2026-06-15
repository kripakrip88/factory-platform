app_name = "metal_calculator"
app_title = "Калькулятор металла"
app_publisher = "Factory Platform"
app_description = "Калькулятор веса металлопроката (конструкционная сталь). Вес строго из справочников ГОСТ."
app_email = "kripakrip88@gmail.com"
app_license = "Proprietary"
frappe_version = ">=16.0.0 <17.0.0"

# Fixtures
# --------
# Воркспейс «Калькуляторы» создаётся в after_install обычным get_doc().insert()
# (см. install.py). Через fixtures НЕ грузим: force-импортёр Frappe v16 терял
# обязательное поле `type` у дочернего Workspace Shortcut → MandatoryError.
fixtures = []

# Installation
# ------------
# После установки аппы заливаем справочники ГОСТ (идемпотентно).
after_install = "metal_calculator.install.after_install"

# Uninstallation
# --------------
# Удаление аппы не должно ронять остальной ERPNext — стандартная очистка frappe.
