# -*- coding: utf-8 -*-
"""Разбор управляющего файла лазера CypCut (.lxds).

Зачем отдельным модулем на чистом питоне, без Odoo: файл раскроя приходит
раньше, чем заказ заводится в систему, и технологу с мастером нужно уметь
посмотреть его прямо в командной строке — «что тут за детали и сколько листов».
Модуль импортируется моделью участка, но от неё не зависит.

Что отсюда берём и почему именно это.

Файл — обычный ZIP с XML внутри. Достоверны в нём:
  * Nest2D/Parts/content.xml      — состав заказа: имя детали и количество;
  * Nest2D/Results/content.xml    — сводка раскладок;
  * Nest2D/Results/<N>/content.xml — раскладка: использование листа, сколько
    таких листов (PlateAmount), габарит (ExtMax);
  * Nest2D/Plates/content.xml     — какой лист заряжали;
  * Shapes2D/content.xml          — геометрия документа, по числу контуров;
  * info.xml                      — версия CypCut, оператор, время сохранения.

Не достоверен Technical/content.xml. У технолога в CypCut только демо-режимы:
этот блок побайтово одинаков во всех присланных файлах (один MD5, см.
DEMO_TECHNICAL_MD5), в нём всегда Thickness="1.5" и «черная сталь» — и на
двойке, и на тройке, и на десятке. Поэтому толщину берём из ИМЕНИ файла:
технолог пишет её первой («3мм Сталкер Площадка ГРПШ…») для оператора станка,
и вот это значение живое.

Деньги считаем по правилам владельца:
  * полезная площадь = габарит листа x использование x число листов;
  * полезный вес = полезная площадь x масса квадрата из справочника pmk_calc.
    Именно из справочника, а не через плотность: у рифлёного квадрат тяжелее
    плоского на 5-7%, у просечно-вытяжного металла 37-63% габарита, и
    справочник это уже знает, а плотность 7.85 — нет;
  * премия операторам от полезного веса: 500 ₽/т на листе от 3 мм
    включительно, 3000 ₽/т до 3 мм; делится поровну между операторами смены.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# Эталонный MD5 блока Technical/content.xml. Совпал побайтово на всех трёх
# присланных файлах (10 мм, 2 мм, 3 мм) — это и есть отпечаток демо-режимов:
# технолог сохраняет раскрой с одними и теми же параметрами резки независимо
# от металла. Совпадение = «параметрам резки из этого файла верить нельзя».
DEMO_TECHNICAL_MD5 = "bbbcec16c304738104d4a85a4a895254"

# Правило премии, слова владельца: «500 руб/т на листе от 3 мм включительно,
# 3000 руб/т до 3 мм». Граница именно включительная, тройка идёт по 500.
PREMIUM_BOUNDARY_MM = 3.0
PREMIUM_RATE_THICK = 500.0   # ₽ за тонну полезного веса, лист >= 3 мм
PREMIUM_RATE_THIN = 3000.0   # ₽ за тонну полезного веса, лист < 3 мм

# Справочник масс квадрата живёт в соседнем модуле расчётов. Своей копии здесь
# намеренно нет: две копии одного справочника рано или поздно разъедутся, и
# разъедутся они молча — в деньгах.
SHEET_REFERENCE_PATH = (
    Path(__file__).resolve().parents[2] / "pmk_calc" / "data" / "pmk.metal.sheet.csv"
)
DEFAULT_SHEET_TYPE = "Гладкий"

# Толщина листа, которую вообще может резать лазер. Рамка нужна не для красоты:
# в имени файла кроме толщины попадаются другие миллиметры — «Площадка ГРПШ
# шириной 1500мм». Без рамки парсер честно вернул бы 1500 мм.
MIN_THICKNESS_MM = 0.3
MAX_THICKNESS_MM = 60.0

# Обязательные части архива. Если их нет — перед нами не раскрой CypCut, и
# сказать об этом надо фразой, а не трейсбеком.
REQUIRED_MEMBERS = ("info.xml", "Nest2D/content.xml", "Nest2D/Results/content.xml")


class LxdsError(Exception):
    """Ошибка, которую можно показать человеку: битый файл, не тот формат,
    нет толщины в имени, нет позиции в справочнике."""


# --------------------------------------------------------------------------
# Данные, которые достаём из файла
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Part:
    """Позиция заказа: как её назвал технолог и сколько штук заявлено.

    amount_used отличается от amount, когда в раскладку влезли не все детали —
    это и есть «часть заказа осталась на следующий лист».
    """

    name: str
    amount: int
    amount_used: int


@dataclass(frozen=True)
class Nest:
    """Одна раскладка = одна картинка на листе.

    plate_amount — сколько РАЗ эту картинку режут. В файле кронштейнов одна
    раскладка на 89.2% повторена 7 раз, и это семь листов, а не один: если
    считать раскладки, а не листы, полезный вес занизится в семь раз.
    """

    index: int
    width_mm: float
    height_mm: float
    utilization_pct: float
    plate_amount: int
    part_count: int

    @property
    def sheet_area_m2(self) -> float:
        """Габаритная площадь одного листа этой раскладки."""
        return self.width_mm * self.height_mm / 1_000_000.0

    @property
    def useful_area_m2(self) -> float:
        """Полезная площадь всех листов раскладки: габарит x использование x листы."""
        return self.sheet_area_m2 * self.utilization_pct / 100.0 * self.plate_amount

    @property
    def gross_area_m2(self) -> float:
        """Сколько металла ушло со склада под эту раскладку (с отходом)."""
        return self.sheet_area_m2 * self.plate_amount


@dataclass(frozen=True)
class Economics:
    """Деньги и вес по правилам владельца. Отдельным объектом, потому что
    считается не всегда: без толщины в имени файла считать нечего."""

    sheet_type: str
    thickness_mm: float
    mass_per_sqm: float
    reference_gost: str
    useful_area_m2: float
    useful_mass_kg: float
    premium_rate: float
    premium_total_rub: float
    operators: Tuple[str, ...]
    premium_per_operator_rub: float


@dataclass
class Layout:
    """Разобранный файл раскроя целиком."""

    path: Path
    file_name: str
    app_name: str
    app_version: str
    operator: str
    computer: str
    # Время сохранения. CypCut пишет его с суффиксом «Z», но это ЛОКАЛЬНОЕ
    # время станка: у всех трёх файлов SaveTime совпадает секунда в секунду с
    # временем файла внутри ZIP, а оно локальное. Перевод «из UTC» сдвинул бы
    # смену на 10 часов и увёл вечерние раскрои на следующие сутки.
    saved_at: Optional[datetime]
    saved_at_raw: str
    technical_md5: str
    demo_modes: bool
    technical_declared: Dict[str, str]
    thickness_mm: Optional[float]
    thickness_source: str
    parts: List[Part]
    nests: List[Nest]
    plate_label: str
    contours: int
    shape_census: Dict[str, int]
    warnings: List[str] = field(default_factory=list)
    economics: Optional[Economics] = None

    @property
    def sheet_count(self) -> int:
        return sum(nest.plate_amount for nest in self.nests)

    @property
    def useful_area_m2(self) -> float:
        return sum(nest.useful_area_m2 for nest in self.nests)

    @property
    def gross_area_m2(self) -> float:
        return sum(nest.gross_area_m2 for nest in self.nests)

    @property
    def parts_declared(self) -> int:
        return sum(part.amount for part in self.parts)

    @property
    def parts_nested(self) -> int:
        """Сколько деталей реально разложено по листам: сумма деталей на
        раскладке, умноженная на число листов раскладки."""
        return sum(nest.part_count * nest.plate_amount for nest in self.nests)


# --------------------------------------------------------------------------
# Низкий уровень: ZIP, XML, числа
# --------------------------------------------------------------------------


def _open_archive(path: Path) -> zipfile.ZipFile:
    """Открыть .lxds, переведя любую поломку в человеческую фразу."""
    if not path.exists():
        raise LxdsError(f"Файла нет: {path}")
    if path.is_dir():
        raise LxdsError(f"Это папка, а не файл раскроя: {path}")
    if path.stat().st_size == 0:
        raise LxdsError(f"Файл пустой (0 байт): {path.name}")
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise LxdsError(
            f"«{path.name}» — не управляющий файл CypCut: внутри не ZIP-контейнер. "
            f"Так выглядит либо повреждённый файл, либо чужой формат (.dxf, .nc, .lxd)."
        ) from None
    except OSError as err:
        raise LxdsError(f"Не удалось открыть «{path.name}»: {err}") from None

    names = set(archive.namelist())
    missing = [member for member in REQUIRED_MEMBERS if member not in names]
    if missing:
        archive.close()
        raise LxdsError(
            f"«{path.name}» — ZIP открылся, но это не раскрой CypCut: "
            f"внутри нет {', '.join(missing)}."
        )
    return archive


def _read_member(archive: zipfile.ZipFile, name: str, file_name: str) -> bytes:
    """Прочитать часть архива. Отсутствие и битый CRC — разные беды, и
    называются они по-разному."""
    try:
        return archive.read(name)
    except KeyError:
        raise LxdsError(f"В «{file_name}» нет части {name} — файл неполный.") from None
    except (zipfile.BadZipFile, OSError) as err:
        raise LxdsError(
            f"Часть {name} в «{file_name}» не читается (повреждение архива): {err}"
        ) from None


def _parse_xml(raw: bytes, name: str, file_name: str) -> ET.Element:
    try:
        return ET.fromstring(raw)
    except ET.ParseError as err:
        raise LxdsError(f"Испорченный XML в {name} файла «{file_name}»: {err}") from None


def _to_float(value: Optional[str], default: float = 0.0) -> float:
    """Числа в CypCut приходят и с точкой («66.7010838»), и с запятой («0,2»):
    файл пишет программа на Delphi, часть значений сериализуется в локали."""
    if value is None:
        return default
    text = value.strip().replace(",", ".")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _to_int(value: Optional[str], default: int = 0) -> int:
    return int(_to_float(value, float(default)))


# --------------------------------------------------------------------------
# Толщина из имени файла
# --------------------------------------------------------------------------

_THICKNESS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:мм|mm)", re.IGNORECASE)


def parse_thickness_from_name(file_name: str) -> Tuple[Optional[float], str]:
    """Достать толщину листа из имени файла.

    Технолог ставит её первой — «10мм Виталий Отводы…», «2мм СМП810
    Кронштейны…»: имя читает оператор станка, и первое, что ему нужно знать,
    это какой лист заряжать. Отсюда правило: сначала ищем миллиметры в начале
    имени, и только если там их нет — первые подходящие по всему имени.

    Рамка MIN/MAX обязательна. «3мм Сталкер Площадка ГРПШ шириной 1500мм
    Раскрой» содержит вторые миллиметры, и это ширина изделия, а не толщина.

    Возвращает (толщина или None, фраза-объяснение откуда взялась).
    """
    stem = Path(file_name).stem
    matches = list(_THICKNESS_RE.finditer(stem))
    if not matches:
        return None, (
            "в имени файла нет миллиметров — толщину не определить "
            "(Technical в .lxds демонстрационный, оттуда брать нельзя)"
        )

    head = matches[0]
    plausible = [m for m in matches
                 if MIN_THICKNESS_MM <= _to_float(m.group(1)) <= MAX_THICKNESS_MM]

    if head.start() == 0 and head in plausible:
        value = _to_float(head.group(1))
        return value, f"из имени файла: «{head.group(0)}» в начале имени"

    if plausible:
        chosen = plausible[0]
        value = _to_float(chosen.group(1))
        skipped = [m.group(0) for m in matches if m is not chosen]
        note = f"из имени файла: «{chosen.group(0)}»"
        if skipped:
            note += f" (пропущено как не толщина: {', '.join(skipped)})"
        return value, note

    found = ", ".join(m.group(0) for m in matches)
    return None, (
        f"в имени файла есть миллиметры ({found}), но ни одни не похожи на "
        f"толщину листа ({MIN_THICKNESS_MM}–{MAX_THICKNESS_MM} мм)"
    )


# --------------------------------------------------------------------------
# Справочник масс квадрата
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SheetGrade:
    sheet_type: str
    thickness_mm: float
    size_label: str
    gost: str
    mass_per_sqm: float


def load_sheet_reference(path: Path = SHEET_REFERENCE_PATH) -> List[SheetGrade]:
    """Прочитать pmk.metal.sheet.csv модуля расчётов."""
    if not path.exists():
        raise LxdsError(
            f"Нет справочника листа: {path}. Без него полезный вес не посчитать — "
            f"масса квадрата берётся оттуда, а не из плотности."
        )
    rows: List[SheetGrade] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            mass = _to_float(row.get("mass_per_sqm"))
            if mass <= 0:
                continue
            rows.append(SheetGrade(
                sheet_type=(row.get("sheet_type") or "").strip(),
                thickness_mm=_to_float(row.get("thickness_mm")),
                size_label=(row.get("size_label") or "").strip(),
                gost=(row.get("gost") or "").strip(),
                mass_per_sqm=mass,
            ))
    if not rows:
        raise LxdsError(f"Справочник листа пуст: {path}")
    return rows


def find_sheet_grade(
    thickness_mm: float,
    sheet_type: str = DEFAULT_SHEET_TYPE,
    size_label: Optional[str] = None,
    reference: Optional[Sequence[SheetGrade]] = None,
) -> SheetGrade:
    """Найти строку справочника под толщину и вид листа.

    Если под толщину есть несколько строк (у просечно-вытяжного 5 мм это 506,
    508 и 510 — масса отличается в полтора раза), молча брать первую нельзя:
    просим уточнить типоразмер.
    """
    rows = list(reference) if reference is not None else load_sheet_reference()
    same_type = [row for row in rows if row.sheet_type == sheet_type]
    if not same_type:
        kinds = sorted({row.sheet_type for row in rows})
        raise LxdsError(f"Нет вида листа «{sheet_type}». Есть: {', '.join(kinds)}")

    # Толщины в CSV и в имени файла — числа с плавающей точкой (0.35, 1.5),
    # сравнивать их через == нельзя.
    matches = [row for row in same_type if abs(row.thickness_mm - thickness_mm) < 1e-6]
    if not matches:
        have = ", ".join(_format_number(row.thickness_mm) for row in same_type)
        raise LxdsError(
            f"В справочнике нет листа «{sheet_type}» толщиной {_format_number(thickness_mm)} мм. "
            f"Есть: {have}"
        )
    if size_label:
        matches = [row for row in matches if row.size_label == size_label]
        if not matches:
            raise LxdsError(
                f"Нет листа «{sheet_type}» {_format_number(thickness_mm)} мм "
                f"с типоразмером «{size_label}»"
            )
    if len(matches) > 1:
        labels = ", ".join(row.size_label or "без типоразмера" for row in matches)
        raise LxdsError(
            f"Лист «{sheet_type}» {_format_number(thickness_mm)} мм есть в нескольких "
            f"исполнениях ({labels}) — укажите типоразмер, масса квадрата у них разная."
        )
    return matches[0]


def premium_rate(thickness_mm: float) -> float:
    """Ставка премии, ₽ за тонну полезного веса. От 3 мм включительно — 500."""
    return PREMIUM_RATE_THICK if thickness_mm >= PREMIUM_BOUNDARY_MM else PREMIUM_RATE_THIN


# --------------------------------------------------------------------------
# Разбор файла
# --------------------------------------------------------------------------


def _read_info(archive: zipfile.ZipFile, file_name: str) -> Dict[str, str]:
    root = _parse_xml(_read_member(archive, "info.xml", file_name), "info.xml", file_name)
    app = root.find("Application")
    saved = root.find("SavedBy")
    return {
        "app_name": (app.get("AppName", "") if app is not None else ""),
        "app_version": (app.get("AppVer", "") if app is not None else ""),
        "operator": (saved.get("User", "") if saved is not None else ""),
        "computer": (saved.get("Computer", "") if saved is not None else ""),
        "save_time": (saved.get("SaveTime", "") if saved is not None else ""),
    }


def _parse_save_time(raw: str) -> Optional[datetime]:
    """«2026-09-08T15:47:26Z» → naive datetime без сдвига.

    Суффикс Z здесь декоративный: у всех присланных файлов это время совпадает
    с временем записи внутри ZIP, а оно локальное, хабаровское. Считать его UTC
    значит перенести вечернюю смену на следующие сутки.
    """
    if not raw:
        return None
    text = raw.strip().rstrip("Zz")
    for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def _read_parts(archive: zipfile.ZipFile, file_name: str) -> List[Part]:
    """Состав заказа. Nest2D/Parts/content.xml может отсутствовать у пустого
    раскроя — это не повод падать, это просто «деталей нет»."""
    if "Nest2D/Parts/content.xml" not in archive.namelist():
        return []
    root = _parse_xml(
        _read_member(archive, "Nest2D/Parts/content.xml", file_name),
        "Nest2D/Parts/content.xml", file_name,
    )
    parts = []
    for node in root.findall("NestPart"):
        amount = _to_int(node.get("Amount"))
        parts.append(Part(
            name=(node.get("Name") or "без имени").strip(),
            amount=amount,
            amount_used=_to_int(node.get("AmountUsed"), amount),
        ))
    return parts


def _read_nests(archive: zipfile.ZipFile, file_name: str,
                warnings: List[str]) -> List[Nest]:
    """Раскладки. Сводка Nest2D/Results/content.xml и подробности в
    Nest2D/Results/<N>/content.xml дублируют друг друга — читаем обе и сверяем.
    Расхождение означает, что файл правили на ходу, и молчать о нём нельзя.
    """
    root = _parse_xml(
        _read_member(archive, "Nest2D/Results/content.xml", file_name),
        "Nest2D/Results/content.xml", file_name,
    )
    names = set(archive.namelist())
    nests: List[Nest] = []
    for node in root.findall("NestResult"):
        index = _to_int(node.get("Index"), len(nests) + 1)
        width = _to_float(node.get("SizeX"))
        height = _to_float(node.get("SizeY"))
        utilization = _to_float(node.get("Utilization"))
        plate_amount = _to_int(node.get("PlanCount"), 1)
        part_count = _to_int(node.get("PartCount"))

        member = f"Nest2D/Results/{index}/content.xml"
        if member in names:
            detail = _parse_xml(_read_member(archive, member, file_name), member, file_name)
            detail_amount = _to_int(detail.get("PlateAmount"), plate_amount)
            detail_util = _to_float(detail.get("Utilization"), utilization)
            ext_max = detail.find("ExtMax")
            if ext_max is not None:
                detail_w = _to_float(ext_max.get("X"), width)
                detail_h = _to_float(ext_max.get("Y"), height)
                if (abs(detail_w - width) > 0.5 or abs(detail_h - height) > 0.5) and width:
                    warnings.append(
                        f"раскладка {index}: габарит в сводке {width:.0f}x{height:.0f}, "
                        f"в самой раскладке {detail_w:.0f}x{detail_h:.0f} — взят второй"
                    )
                width, height = detail_w or width, detail_h or height
            if detail_amount != plate_amount:
                warnings.append(
                    f"раскладка {index}: листов в сводке {plate_amount}, "
                    f"в раскладке {detail_amount} — взято {detail_amount}"
                )
                plate_amount = detail_amount
            if abs(detail_util - utilization) > 1e-6:
                warnings.append(
                    f"раскладка {index}: использование в сводке {utilization:.4f}%, "
                    f"в раскладке {detail_util:.4f}% — взято второе"
                )
                utilization = detail_util
        else:
            warnings.append(f"раскладка {index}: нет {member}, данные только из сводки")

        if width <= 0 or height <= 0:
            raise LxdsError(
                f"В «{file_name}» у раскладки {index} нет габарита листа — "
                f"полезную площадь считать не от чего."
            )
        nests.append(Nest(
            index=index, width_mm=width, height_mm=height,
            utilization_pct=utilization, plate_amount=max(plate_amount, 1),
            part_count=part_count,
        ))
    if not nests:
        raise LxdsError(
            f"В «{file_name}» нет ни одной раскладки — детали в файл загружены, "
            f"но на лист не разложены."
        )
    return nests


def _read_plate_label(archive: zipfile.ZipFile, file_name: str) -> str:
    """Какой лист заряжали — строкой для отчёта."""
    if "Nest2D/Plates/content.xml" not in archive.namelist():
        return ""
    root = _parse_xml(
        _read_member(archive, "Nest2D/Plates/content.xml", file_name),
        "Nest2D/Plates/content.xml", file_name,
    )
    labels = []
    for node in root.findall("NestPlate"):
        poly = node.find("LwPolyline")
        if poly is None:
            continue
        xs = [_to_float(p.get("X")) for p in poly.findall("Point")]
        ys = [_to_float(p.get("Y")) for p in poly.findall("Point")]
        if xs and ys:
            labels.append(
                f"{max(xs):.0f}x{max(ys):.0f} мм x{_to_int(node.get('Amount'), 1)}"
            )
    return "; ".join(labels)


def _read_shapes(archive: zipfile.ZipFile, file_name: str) -> Tuple[int, Dict[str, int]]:
    """Перепись геометрии документа.

    Контуры считаем по тегам LwPolyline — это замкнутые контуры деталей и
    вырезов. Рядом лежат Circle (круглые отверстия), Line и PolyBezier, и их
    возвращаем отдельной переписью: круг — тоже контур и тоже прокол, а прокол
    это время станка. Считается геометрия ДОКУМЕНТА, не умноженная на число
    листов: это знаменатель для замера, а не наряд.
    """
    if "Shapes2D/content.xml" not in archive.namelist():
        return 0, {}
    root = _parse_xml(
        _read_member(archive, "Shapes2D/content.xml", file_name),
        "Shapes2D/content.xml", file_name,
    )
    census: Dict[str, int] = {}
    for node in root:
        if node.tag == "MD5":
            continue
        census[node.tag] = census.get(node.tag, 0) + 1
    return census.get("LwPolyline", 0), census


def read_layout(path: Path) -> Layout:
    """Разобрать .lxds. Без денег — только то, что написано в файле."""
    path = Path(path)
    archive = _open_archive(path)
    try:
        file_name = path.name
        warnings: List[str] = []

        info = _read_info(archive, file_name)
        technical_raw = _read_member(archive, "Technical/content.xml", file_name) \
            if "Technical/content.xml" in archive.namelist() else b""
        technical_md5 = hashlib.md5(technical_raw).hexdigest() if technical_raw else ""
        declared: Dict[str, str] = {}
        if technical_raw:
            tech_root = _parse_xml(technical_raw, "Technical/content.xml", file_name)
            material = tech_root.find(".//MaterialParams")
            if material is not None:
                declared = {
                    "thickness": material.get("Thickness", ""),
                    "material": material.get("MaterialName", ""),
                    "nozzle": material.get("NozzleSpec", ""),
                }

        parts = _read_parts(archive, file_name)
        nests = _read_nests(archive, file_name, warnings)
        contours, census = _read_shapes(archive, file_name)
        thickness, thickness_source = parse_thickness_from_name(file_name)

        layout = Layout(
            path=path,
            file_name=file_name,
            app_name=info["app_name"],
            app_version=info["app_version"],
            operator=info["operator"],
            computer=info["computer"],
            saved_at=_parse_save_time(info["save_time"]),
            saved_at_raw=info["save_time"],
            technical_md5=technical_md5,
            demo_modes=(technical_md5 == DEMO_TECHNICAL_MD5),
            technical_declared=declared,
            thickness_mm=thickness,
            thickness_source=thickness_source,
            parts=parts,
            nests=nests,
            plate_label=_read_plate_label(archive, file_name),
            contours=contours,
            shape_census=census,
            warnings=warnings,
        )
    finally:
        archive.close()

    # Сходимость состава: сумма деталей на раскладках, умноженная на число
    # листов, обязана совпасть с заявленным количеством. Не совпало — раскрой
    # покрывает заказ не целиком, и замер по нему нельзя относить ко всему
    # заказу. На всех трёх присланных файлах сходится: 30, 380 и 12 деталей.
    if layout.parts and layout.parts_nested != layout.parts_declared:
        layout.warnings.append(
            f"деталей заявлено {layout.parts_declared}, разложено "
            f"{layout.parts_nested} — раскрой покрывает заказ не полностью"
        )
    return layout


def compute_economics(
    layout: Layout,
    operators: Sequence[str] = (),
    sheet_type: str = DEFAULT_SHEET_TYPE,
    size_label: Optional[str] = None,
    reference: Optional[Sequence[SheetGrade]] = None,
) -> Economics:
    """Полезный вес и премия по правилам владельца."""
    if layout.thickness_mm is None:
        raise LxdsError(
            f"«{layout.file_name}»: {layout.thickness_source}. "
            f"Без толщины полезный вес и премию считать не от чего."
        )
    grade = find_sheet_grade(layout.thickness_mm, sheet_type, size_label, reference)
    useful_area = layout.useful_area_m2
    useful_mass = useful_area * grade.mass_per_sqm
    rate = premium_rate(layout.thickness_mm)
    total = useful_mass / 1000.0 * rate
    crew = tuple(name.strip() for name in operators if name and name.strip())
    # «Операторы делят премию пополам» — делим на фактический состав смены, а
    # не на жёсткую двойку: смена бывает и одна, и втроём, и менять из-за этого
    # код нельзя.
    per_operator = total / len(crew) if crew else total
    return Economics(
        sheet_type=grade.sheet_type,
        thickness_mm=layout.thickness_mm,
        mass_per_sqm=grade.mass_per_sqm,
        reference_gost=grade.gost,
        useful_area_m2=useful_area,
        useful_mass_kg=useful_mass,
        premium_rate=rate,
        premium_total_rub=total,
        operators=crew,
        premium_per_operator_rub=per_operator,
    )


def analyze(
    path: Path,
    operators: Sequence[str] = (),
    sheet_type: str = DEFAULT_SHEET_TYPE,
    size_label: Optional[str] = None,
    reference: Optional[Sequence[SheetGrade]] = None,
) -> Layout:
    """Разобрать файл и досчитать деньги.

    Если толщины в имени нет — разбор всё равно возвращается целиком, просто
    без денег и с записью в warnings: половина пользы (состав, листы, контуры)
    от этого не пропадает.
    """
    layout = read_layout(path)
    try:
        layout.economics = compute_economics(
            layout, operators, sheet_type, size_label, reference)
    except LxdsError as err:
        layout.warnings.append(str(err))
    return layout


# --------------------------------------------------------------------------
# Отчёт для командной строки
# --------------------------------------------------------------------------


def _format_number(value: float, digits: int = 2) -> str:
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


def _plural(count: int, one: str, few: str, many: str) -> str:
    tail_100 = count % 100
    tail_10 = count % 10
    if 11 <= tail_100 <= 14:
        return many
    if tail_10 == 1:
        return one
    if 2 <= tail_10 <= 4:
        return few
    return many


def format_report(layout: Layout) -> str:
    lines: List[str] = [f"=== {layout.file_name}"]

    stamp = layout.saved_at.strftime("%d.%m.%Y %H:%M") if layout.saved_at else layout.saved_at_raw
    lines.append(
        f"{layout.app_name} {layout.app_version}, оператор {layout.operator or '?'} "
        f"({layout.computer or '?'}), сохранено {stamp} — местное время станка"
    )

    if layout.thickness_mm is not None:
        lines.append(f"Толщина: {_format_number(layout.thickness_mm)} мм — {layout.thickness_source}")
    else:
        lines.append(f"Толщина: не определена — {layout.thickness_source}")

    declared = layout.technical_declared
    if layout.demo_modes:
        shown = f"{declared.get('thickness', '?')} мм, {declared.get('material', '?')}"
        lines.append(
            f"Режимы резки: ДЕМОНСТРАЦИОННЫЕ (Technical MD5 {layout.technical_md5[:12]}… — "
            f"эталонный). В файле записано «{shown}» — это не про этот металл, не верить."
        )
    elif layout.technical_md5:
        lines.append(
            f"Режимы резки: Technical отличается от эталона демо "
            f"(MD5 {layout.technical_md5[:12]}…) — возможно, настоящие, проверить у технолога."
        )

    lines.append(
        f"Детали: {len(layout.parts)} "
        f"{_plural(len(layout.parts), 'позиция', 'позиции', 'позиций')}, "
        f"{layout.parts_declared} шт заявлено / {layout.parts_nested} шт разложено"
    )
    for part in layout.parts:
        tail = "" if part.amount_used == part.amount else f" (в раскрой вошло {part.amount_used})"
        lines.append(f"   {part.amount:>5} шт  {part.name}{tail}")

    lines.append(
        f"Листы: {layout.sheet_count} "
        f"{_plural(layout.sheet_count, 'лист', 'листа', 'листов')}"
        + (f" — {layout.plate_label}" if layout.plate_label else "")
    )
    for nest in layout.nests:
        lines.append(
            f"   раскладка {nest.index}: {nest.width_mm:.0f}x{nest.height_mm:.0f} мм "
            f"x{nest.plate_amount}, использование {nest.utilization_pct:.1f}%, "
            f"деталей на листе {nest.part_count}"
        )

    census = ", ".join(f"{tag} {count}" for tag, count in sorted(layout.shape_census.items()))
    lines.append(f"Контуры: {layout.contours} (геометрия документа: {census or 'пусто'})")

    lines.append(
        f"Площадь: полезная {_format_number(layout.useful_area_m2, 3)} м² "
        f"из {_format_number(layout.gross_area_m2, 3)} м² металла "
        f"(отход {_format_number(layout.gross_area_m2 - layout.useful_area_m2, 3)} м²)"
    )

    money = layout.economics
    if money:
        lines.append(
            f"Масса квадрата: {_format_number(money.mass_per_sqm)} кг/м² "
            f"({money.sheet_type} {_format_number(money.thickness_mm)} мм, {money.reference_gost})"
        )
        lines.append(
            f"Полезный вес: {money.useful_mass_kg:.1f} кг "
            f"(округлённо {round(money.useful_mass_kg)} кг)"
        )
        bound = "от 3 мм" if money.premium_rate == PREMIUM_RATE_THICK else "до 3 мм"
        lines.append(
            f"Премия: {money.premium_rate:.0f} ₽/т (лист {bound}) → "
            f"{round(money.premium_total_rub)} ₽ (точно {money.premium_total_rub:.2f})"
        )
        if money.operators:
            share = ", ".join(
                f"{name} {money.premium_per_operator_rub:.2f} ₽" for name in money.operators)
            lines.append(f"   поровну на {len(money.operators)}: {share}")

    for warning in layout.warnings:
        lines.append(f"   ! {warning}")
    return "\n".join(lines)


def to_dict(layout: Layout) -> dict:
    """Плоское представление — для n8n, модели Odoo и для diff в тестах."""
    data = {
        "file": layout.file_name,
        "app": f"{layout.app_name} {layout.app_version}".strip(),
        "operator": layout.operator,
        "computer": layout.computer,
        "saved_at": layout.saved_at.isoformat(sep=" ") if layout.saved_at else None,
        "thickness_mm": layout.thickness_mm,
        "thickness_source": layout.thickness_source,
        "technical_md5": layout.technical_md5,
        "demo_modes": layout.demo_modes,
        "technical_declared": layout.technical_declared,
        "parts": [{"name": p.name, "amount": p.amount, "amount_used": p.amount_used}
                  for p in layout.parts],
        "parts_declared": layout.parts_declared,
        "parts_nested": layout.parts_nested,
        "nests": [{"index": n.index, "width_mm": n.width_mm, "height_mm": n.height_mm,
                   "utilization_pct": n.utilization_pct, "plate_amount": n.plate_amount,
                   "part_count": n.part_count,
                   "useful_area_m2": round(n.useful_area_m2, 6)} for n in layout.nests],
        "sheet_count": layout.sheet_count,
        "contours": layout.contours,
        "shape_census": layout.shape_census,
        "useful_area_m2": round(layout.useful_area_m2, 6),
        "gross_area_m2": round(layout.gross_area_m2, 6),
        "warnings": layout.warnings,
    }
    if layout.economics:
        money = layout.economics
        data["economics"] = {
            "sheet_type": money.sheet_type,
            "mass_per_sqm": money.mass_per_sqm,
            "useful_mass_kg": round(money.useful_mass_kg, 3),
            "premium_rate": money.premium_rate,
            "premium_total_rub": round(money.premium_total_rub, 2),
            "operators": list(money.operators),
            "premium_per_operator_rub": round(money.premium_per_operator_rub, 2),
        }
    return data


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Разбор управляющего файла лазера CypCut (.lxds): состав "
                    "заказа, листы, полезный вес, премия операторам.")
    parser.add_argument("files", nargs="+", help="файлы .lxds")
    parser.add_argument("--operator", action="append", default=[], metavar="ФАМИЛИЯ",
                        help="оператор смены (повторяйте по числу операторов — "
                             "премия делится между ними поровну)")
    parser.add_argument("--sheet-type", default=DEFAULT_SHEET_TYPE,
                        help=f"вид листа из справочника (по умолчанию «{DEFAULT_SHEET_TYPE}»)")
    parser.add_argument("--size-label", default=None,
                        help="типоразмер для рифлёного/просечно-вытяжного листа")
    parser.add_argument("--json", action="store_true", help="выдать JSON вместо отчёта")
    args = parser.parse_args(argv)

    try:
        reference = load_sheet_reference()
    except LxdsError as err:
        print(f"Ошибка: {err}", file=sys.stderr)
        return 2

    layouts, failed = [], 0
    for name in args.files:
        try:
            layouts.append(analyze(Path(name), args.operator, args.sheet_type,
                                   args.size_label, reference))
        except LxdsError as err:
            # Разбор пачки не должен останавливаться из-за одного чужого файла.
            print(f"Ошибка: {err}", file=sys.stderr)
            failed += 1

    if args.json:
        print(json.dumps([to_dict(item) for item in layouts], ensure_ascii=False, indent=2))
    else:
        for item in layouts:
            print(format_report(item))
            print()
        if len(layouts) > 1:
            digests = {item.technical_md5 for item in layouts if item.technical_md5}
            if len(digests) == 1:
                print(f"Technical/content.xml во всех {len(layouts)} файлах ОДИН И ТОТ ЖЕ "
                      f"(MD5 {digests.pop()}) — режимы резки демонстрационные.")
            else:
                print(f"Technical/content.xml различается: {len(digests)} вариантов.")
    # Ненулевой код, если хоть один файл не разобрался: пачку гоняют из n8n,
    # и тихий успех при выпавшем файле там ничем не отличается от честного.
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
