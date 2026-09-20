# -*- coding: utf-8 -*-
"""Сквозной прогон модуля на живых файлах — без Odoo и без базы.

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ test_lxds.py. Тот проверяет РАЗБОР файла: что из архива
вынуто то самое и посчитано верно. Здесь проверяется СБОРКА: что цифры,
которые покажет пользователю модель Odoo, равны контрольным цифрам владельца.
Дорога считается ровно так, как её проходит models/job.py:

    lxds.read_layout(файл)                     — разбор .lxds
    -> раскладка, повторённая N раз            — job._sheet_commands
    -> money.sheet_area_m2 / useful_area_m2    — sheet._compute_metal
    -> money.mass_kg по кг/м² из pmk_calc      — sheet._compute_metal
    -> сумма по листам                         — job._compute_metal
    -> money.premium_rub                       — job._compute_premium
    -> money.split_rub                         — operator._compute_amount

ЧТО ЗАМЕНЕНО ЗАГЛУШКОЙ И ПОЧЕМУ ЭТО ЧЕСТНО. Не выполняется ровно одна вещь —
ORM: вместо sheet.write() значения складываются в список. Сами формулы берутся
из НАСТОЯЩЕГО models/money.py, тот импортируется отсюда как есть, вместе с его
`from ..tools.lxds import ...`. Подмены арифметики нет: если money.py поедет,
поедет и этот прогон.

Масса квадрата читается из data/pmk.metal.sheet.csv модуля pmk_calc — из того
самого файла, который Odoo грузит в pmk.metal.sheet. Сверено с базой стенда
20.09.2026: Гладкий 2 мм = 15.7, 3 мм = 23.55, 10 мм = 78.5 кг/м² — те же
числа, что в CSV.

Запуск:
    python3 experiments/odoo/addons/pmk_laser/tools/selfcheck.py <папка с .lxds>

Код возврата 0 — все контрольные цифры сошлись, 1 — разошлись.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent


def _load_module_parts():
    """Поднять tools.lxds и models.money как части пакета, но без Odoo.

    Прямой `import pmk_laser.models.money` не годится: интерпретатор сначала
    выполнит pmk_laser/__init__.py, тот потянет models/__init__.py, а оттуда
    job.py с `from odoo import ...`. Odoo здесь нет и быть не должно — весь
    смысл прогона в том, что он идёт на голом python.

    Поэтому пакет собирается вручную из двух подпапок. Файлы при этом
    выполняются настоящие, и относительный импорт `..tools.lxds` внутри
    money.py разрешается в настоящий tools/lxds.py.
    """
    root = types.ModuleType("pmk_laser_selfcheck")
    root.__path__ = [str(MODULE_ROOT)]
    sys.modules["pmk_laser_selfcheck"] = root

    models_pkg = types.ModuleType("pmk_laser_selfcheck.models")
    models_pkg.__path__ = [str(MODULE_ROOT / "models")]
    sys.modules["pmk_laser_selfcheck.models"] = models_pkg

    lxds = importlib.import_module("pmk_laser_selfcheck.tools.lxds")
    money = importlib.import_module("pmk_laser_selfcheck.models.money")
    return lxds, money


LXDS, MONEY = _load_module_parts()

# Вид листа по умолчанию — как в models/job.py: из имени файла вид не виден,
# режут обычно чёрную сталь гладким листом.
DEFAULT_SHEET_TYPE = "Гладкий"

# Контрольные цифры владельца, посчитанные им вручную по этим же трём файлам.
# Ключ — начало имени файла, дальше: листов, полезный вес в кг, премия в рублях.
CONTROL = {
    "10мм": {"sheets": 4, "mass_kg": 1476, "premium_rub": 738},
    "2мм": {"sheets": 8, "mass_kg": 418, "premium_rub": 1252},
    "3мм": {"sheets": 1, "mass_kg": 77, "premium_rub": 39},
}


def _round_half_up(value: float, digits: int = 0) -> float:
    """Округление «половина вверх», как считают на бумаге.

    Встроенный round() округляет половину к чётному: round(2.5) даёт 2. В
    сверке с цифрами, посчитанными человеком, это лишний источник расхождения,
    поэтому правило задано явно.
    """
    factor = 10.0 ** digits
    shifted = value * factor
    result = int(shifted + 0.5) if shifted >= 0 else -int(-shifted + 0.5)
    return result / factor if digits else float(result)


def control_mass_kg(mass_kg: float) -> int:
    """Полезный вес в том виде, в каком его назвал владелец.

    ОКРУГЛЕНИЕ ДВУХШАГОВОЕ, и это не подгонка под ответ, а разбор его справки.
    На кронштейнах точное значение 417,474 кг. Владелец назвал 418, но премию
    назвал 1252 ₽ — а 1252 ₽ получается ТОЛЬКО из 417,474 (417,474/1000x3000 =
    1252,42). Из 418 кг вышло бы 1254 ₽. Значит считал он по точному весу, а
    «418» в справке — это 417,474 -> 417,5 -> 418, вес показан с одним знаком
    и уже с него прочитан целым.

    Правило одно на все три файла, исключений нет:
        1476,423 -> 1476,4 -> 1476    417,474 -> 417,5 -> 418    77,338 -> 77,3 -> 77
    """
    return int(_round_half_up(_round_half_up(mass_kg, 1)))


class Sheet:
    """Физический лист — то же, что строка pmk.laser.job.sheet.

    Поля и формулы повторяют sheet._compute_metal один в один.
    """

    def __init__(self, number, nest_index, width_mm, length_mm, utilization_pct, mass_per_sqm):
        self.number = number
        self.nest_index = nest_index
        self.width_mm = width_mm
        self.length_mm = length_mm
        self.utilization_pct = utilization_pct
        self.area_m2 = MONEY.sheet_area_m2(width_mm, length_mm)
        self.useful_area_m2 = MONEY.useful_area_m2(self.area_m2, utilization_pct)
        self.mass_kg = MONEY.mass_kg(self.area_m2, mass_per_sqm)
        self.useful_mass_kg = MONEY.mass_kg(self.useful_area_m2, mass_per_sqm)


def build_job(path: Path, operators=(), sheet_type=DEFAULT_SHEET_TYPE, reference=None):
    """Собрать задание из файла раскроя: листы, металл, премия, доли.

    Возвращает словарь с теми же величинами, что показывает форма задания.
    """
    layout = LXDS.read_layout(path)
    if layout.thickness_mm is None:
        raise LXDS.LxdsError(f"«{layout.file_name}»: {layout.thickness_source}")

    # Масса квадрата — из справочника pmk_calc, а не через плотность.
    grade = LXDS.find_sheet_grade(layout.thickness_mm, sheet_type, None, reference)

    # Раскладку разворачиваем в физические листы: одна раскладка, повторённая
    # семь раз, — это семь листов на столе. Считать раскладки вместо листов
    # значит занизить полезный вес ровно в семь раз (job._sheet_commands).
    sheets = []
    for nest in layout.nests:
        for _copy in range(nest.plate_amount):
            sheets.append(Sheet(
                number=len(sheets) + 1,
                nest_index=nest.index,
                width_mm=nest.width_mm,
                length_mm=nest.height_mm,
                utilization_pct=nest.utilization_pct,
                mass_per_sqm=grade.mass_per_sqm,
            ))

    gross_area = sum(s.area_m2 for s in sheets)
    useful_area = sum(s.useful_area_m2 for s in sheets)
    mass = sum(s.mass_kg for s in sheets)
    useful_mass = sum(s.useful_mass_kg for s in sheets)
    premium = MONEY.premium_rub(useful_mass, layout.thickness_mm)

    return {
        "layout": layout,
        "sheets": sheets,
        "grade": grade,
        "thickness_mm": layout.thickness_mm,
        "gross_area_m2": gross_area,
        "useful_area_m2": useful_area,
        "mass_kg": mass,
        "useful_mass_kg": useful_mass,
        "utilization_pct": 100.0 * useful_area / gross_area if gross_area else 0.0,
        "premium_rate_rub": MONEY.premium_rate(layout.thickness_mm),
        "premium_rub": premium,
        "shares": MONEY.split_rub(premium, len(operators)),
    }


def _control_for(file_name: str):
    for prefix, expected in CONTROL.items():
        if file_name.startswith(prefix):
            return expected
    return None


def check_folder(folder: Path) -> int:
    files = sorted(folder.glob("*.lxds"))
    if not files:
        print(f"В «{folder}» нет ни одного .lxds")
        return 1

    reference = LXDS.load_sheet_reference()
    print(f"Справочник pmk_calc: {len(reference)} позиций листа "
          f"({LXDS.SHEET_REFERENCE_PATH.name})\n")

    failures = 0
    day_sheets = day_mass = day_premium = 0.0

    for path in files:
        job = build_job(path, operators=("Оператор 1", "Оператор 2"), reference=reference)
        layout = job["layout"]
        print(f"{path.name}")
        print(f"  толщина {job['thickness_mm']:g} мм ({layout.thickness_source}), "
              f"{job['grade'].sheet_type.lower()}, {job['grade'].mass_per_sqm:g} кг/м²")
        for sheet in job["sheets"]:
            print(f"    лист {sheet.number}: {sheet.width_mm:.0f}x{sheet.length_mm:.0f}, "
                  f"раскладка {sheet.nest_index}, использование {sheet.utilization_pct:.4f}%, "
                  f"полезно {sheet.useful_area_m2:.3f} м² = {sheet.useful_mass_kg:.2f} кг")
        print(f"  ИТОГО листов: {len(job['sheets'])}, куплено {job['gross_area_m2']:.2f} м² "
              f"= {job['mass_kg']:.1f} кг, полезно {job['useful_area_m2']:.3f} м² "
              f"= {job['useful_mass_kg']:.2f} кг ({job['utilization_pct']:.1f}%)")
        print(f"  ПРЕМИЯ: {job['premium_rate_rub']:.0f} ₽/т x {job['useful_mass_kg']:.3f} кг "
              f"= {job['premium_rub']:.2f} ₽, на двоих "
              f"{' + '.join('%.2f' % share for share in job['shares'])}")

        expected = _control_for(path.name)
        if not expected:
            print("  контрольной цифры на этот файл нет — пропуск сверки\n")
            continue

        got = {
            "sheets": len(job["sheets"]),
            "mass_kg": control_mass_kg(job["useful_mass_kg"]),
            "premium_rub": int(_round_half_up(job["premium_rub"])),
        }
        bad = {key: (got[key], value) for key, value in expected.items() if got[key] != value}
        if bad:
            failures += 1
            for key, (mine, control) in bad.items():
                print(f"  РАСХОЖДЕНИЕ {key}: посчитано {mine}, у владельца {control}")
        else:
            print(f"  СВЕРКА: листов {got['sheets']} / {got['mass_kg']} кг / "
                  f"{got['premium_rub']} ₽ — сходится с контролем")
        print()

        day_sheets += len(job["sheets"])
        day_mass += job["useful_mass_kg"]
        day_premium += job["premium_rub"]

    print(f"ЗА ДЕНЬ: {day_sheets:.0f} листов, {day_mass:.0f} кг полезного веса, "
          f"{day_premium:.0f} ₽ премии")
    print("РАСХОЖДЕНИЙ НЕТ" if not failures else f"РАСХОЖДЕНИЙ: {failures}")
    return 1 if failures else 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("Укажите папку с файлами раскроя .lxds:\n"
              "    python3 experiments/odoo/addons/pmk_laser/tools/selfcheck.py <папка>")
        return 1
    return check_folder(Path(argv[0]).expanduser())


if __name__ == "__main__":
    sys.exit(main())
