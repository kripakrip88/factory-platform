# -*- coding: utf-8 -*-
"""Сопоставление строки прайса поставщика с нашим справочником.

Главная мысль: это НЕ задача для ИИ. Номенклатура металлопроката
структурирована — вид + размеры + марка, — и после нормализации размеры
совпадают точно. ИИ нужен только на остатке, который не разобрался правилами.

Порядок:
  1. нормализация      — привести написание к одному виду
  2. вид проката       — по ключевым словам
  3. размеры           — вытащить числа
  4. сопоставление     — точное совпадение по (вид, размеры)
  5. остаток           — то, что не разобралось; сюда и зовём ИИ
"""
import json
import re
import unicodedata

# ── 1. НОРМАЛИЗАЦИЯ ────────────────────────────────────────────────────────

# Разделители размеров: латинская x, кириллическая х, звёздочка, знак умножения.
SEPARATORS = str.maketrans({"×": "x", "х": "x", "Х": "x", "X": "x", "*": "x", "•": "x"})

# Сокращения, которые встречаются в прайсах. Порядок важен: длинные раньше.
ABBR = [
    (r"\bпроф\.?\s*тр\.?\b", "профильная труба"),
    (r"\bпрофтруба\b", "профильная труба"),
    (r"\bтр\.?\s*проф\.?\b", "профильная труба"),
    (r"\bпроф\.?\b", "профильная"),
    (r"\bтр\.?\b", "труба"),
    (r"\bуг\.?\b", "уголок"),
    (r"\bшв\.?\b", "швеллер"),
    (r"\bдвут\.?\b", "двутавр"),
    (r"\bбалка\b", "двутавр"),
    (r"\bарм\.?\b", "арматура"),
    (r"\bкв\.?\b", "квадрат"),
    (r"\bшестигр\.?\b", "шестигранник"),
    (r"\bравнопол\w*\b", "равнополочный"),
    (r"\bнеравнопол\w*\b", "неравнополочный"),
    (r"\bр/п\b", "равнополочный"),
    (r"\bн/п\b", "неравнополочный"),
    (r"\bг/к\b", "горячекатаный"),
    (r"\bх/к\b", "холоднокатаный"),
    (r"\bоцинк\w*\b", "оцинкованный"),
    (r"\bбесшов\w*\b", "бесшовная"),
    (r"\bбесш\.?(?![а-яё])", "бесшовная"),
    (r"\bб/ш\b", "бесшовная"),
    (r"\bэлектросвар\w*\b", "электросварная"),
    (r"\bэ/с\b", "электросварная"),
    (r"\bводогаз\w*\b", "вгп"),
    (r"\bв/г\b", "вгп"),
]

GOST_RE = re.compile(r"гост\s*[\dр\s\.\-]+(?:-\d+)?", re.I)
GRADE_RE = re.compile(
    r"\b(ст\s?3\s?сп|ст\s?3\s?пс|ст\s?3|09г2с|10хснд|15хснд|17г1с|40х|ст\s?20|s355|s235)\b", re.I)
PRICE_RE = re.compile(r"\b\d[\d\s]*[,\.]?\d*\s*(?:руб|р\.|₽)\b", re.I)


def normalise(raw):
    """Привести строку к единому виду и вынуть из неё ГОСТ, марку и цену."""
    s = unicodedata.normalize("NFKC", raw or "").strip().lower()
    s = s.translate(SEPARATORS)

    grade = None
    m = GRADE_RE.search(s)
    if m:
        grade = re.sub(r"\s+", "", m.group(1)).upper()
        s = s[:m.start()] + " " + s[m.end():]

    gost = None
    m = GOST_RE.search(s)
    if m:
        gost = m.group(0).strip()
        s = s[:m.start()] + " " + s[m.end():]

    s = PRICE_RE.sub(" ", s)

    for pattern, repl in ABBR:
        s = re.sub(pattern, repl, s)

    # Дробные через запятую -> через точку, но только между цифрами:
    # «40,5» станет «40.5», а «уголок, швеллер» не тронем.
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)
    # Пробелы вокруг разделителя размеров убираем: «40 x 20» -> «40x20»
    s = re.sub(r"\s*x\s*", "x", s)
    s = re.sub(r"[;,]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return {"text": s, "grade": grade, "gost": gost}


# ── 2. ВИД ПРОКАТА ─────────────────────────────────────────────────────────
# Порядок правил важен: более узкие раньше общих.
TYPE_RULES = [
    ("Труба ВГП", [r"\bвгп\b", r"\bду\s?\d"]),
    ("Труба профильная прямоугольная", [r"профильная.*труба|труба.*профильная"]),
    ("Труба профильная квадратная", [r"профильная.*труба|труба.*профильная"]),
    ("Труба круглая", [r"\bтруба\b"]),
    ("Уголок неравнополочный", [r"уголок.*неравнополочный|неравнополочный.*уголок"]),
    ("Уголок равнополочный", [r"\bуголок\b"]),
    ("Швеллер", [r"\bшвеллер\b"]),
    ("Двутавр", [r"\bдвутавр\b"]),
    ("Арматура", [r"\bарматура\b"]),
    ("Шестигранник", [r"\bшестигранник\b"]),
    ("Квадрат", [r"\bквадрат\b"]),
    ("Круг", [r"\bкруг\b"]),
]


def detect_type(text):
    for name, patterns in TYPE_RULES:
        for p in patterns:
            if re.search(p, text):
                return name
    return None


# ── 3. РАЗМЕРЫ ─────────────────────────────────────────────────────────────
NUM = r"\d+(?:\.\d+)?"

# Приставки к размеру: диаметр, условный проход, «под ключ», номер.
# Их надо снять ДО поиска чисел: в «ду25x3.2» между «у» и «2» нет границы
# слова, и связка размеров не находится вовсе. На этом спотыкалась ВГП.
SIZE_PREFIX = re.compile(r"\b(?:d|ф|ø|o|ду|dу|s|№|no)\s*(?=\d)", re.I)


def extract_numbers(text):
    """Числа размера: связка через x либо одиночное число."""
    t = SIZE_PREFIX.sub(" ", text)
    m = re.search(r"(%s(?:x%s)+)" % (NUM, NUM), t)
    if m:
        return [float(x) for x in m.group(1).split("x")]
    nums = re.findall(r"\b(%s)\b" % NUM, t)
    return [float(nums[0])] if nums else []


# Швеллер и двутавр записываются номером и буквой серии: 10П, 20Б1, 15К2.
# Это не размер в миллиметрах, а обозначение профиля по ГОСТ.
# Номер бывает дробным — 6,5У; буква бывает двойной — 16аУ, 18аП.
LETTER_SIZE = re.compile(r"\b(\d+(?:\.\d+)?)\s*([а-яё]{1,2}\s?\d?)\b", re.I)
LETTER_TYPES = ("Швеллер", "Двутавр")


def extract_letter_size(text):
    m = LETTER_SIZE.search(SIZE_PREFIX.sub(" ", text))
    if not m:
        return None
    return (float(m.group(1)), re.sub(r"\s+", "", m.group(2)).lower())


def profile_key(kind, size_label):
    """Ключ позиции справочника: вид + числа + буквы.

    У швеллера и двутавра размер это номер и серия — «20Б1», «15К2». Цифра
    в серии к размеру не относится, и если её посчитать числом, ключ
    разъезжается: «20Б1» превращается в (20, 1) вместо (20) + «б1».
    """
    s = (size_label or "").lower().translate(SEPARATORS)
    s = re.sub(r"\s*бесш\w*", "", s).strip()
    s = SIZE_PREFIX.sub("", s)
    m = re.fullmatch(r"(%s)\s*([а-яё]{1,2}\d?)" % NUM, s)
    if m:
        return (kind, (float(m.group(1)),), m.group(2))
    nums = [float(x) for x in re.findall(NUM, s)]
    letters = "".join(re.findall(r"[а-яё]+\d?", s))
    return (kind, tuple(nums), letters)


# ── 4. СОПОСТАВЛЕНИЕ ───────────────────────────────────────────────────────
SHEET_KINDS = [
    ("Оцинкованный тонколистовой", [r"оцинкован"]),
    ("Просечно-вытяжной", [r"просечно|пвл"]),
    ("Рифлёный", [r"рифл"]),
    ("Гладкий", [r"\bлист\b"]),
]


class Matcher:
    def __init__(self, reference):
        self.by_type_nums = {}
        self.by_type_letters = {}
        for p in reference["profiles"]:
            kind, nums, letters = profile_key(p["type"], p["size"])
            self.by_type_nums.setdefault((kind, nums), []).append(p)
            if letters:
                self.by_type_letters.setdefault((kind, nums, letters), []).append(p)
        self.sheets = reference["sheets"]

    # ------------------------------------------------------------------
    def match(self, raw):
        norm = normalise(raw)
        text = norm["text"]
        result = {"raw": raw, "text": text, "grade": norm["grade"], "gost": norm["gost"],
                  "type": None, "nums": [], "status": "не разобрано", "matches": []}

        sheet = self._match_sheet(text)
        if sheet:
            result.update(sheet)
            return result

        kind = detect_type(text)
        result["type"] = kind
        if not kind:
            result["status"] = "вид не опознан"
            return result

        # Швеллер и двутавр: номер плюс буква серии.
        if kind in LETTER_TYPES:
            ls = extract_letter_size(text)
            if not ls:
                # Номер без серии — «швеллер 14». Показываем все полки этого
                # номера: выбрать должен человек, гадать тут нельзя.
                nums = extract_numbers(text)
                if not nums:
                    result["status"] = "размер не найден"
                    return result
                cands = [c for (k, n, _l), items in self.by_type_letters.items()
                         if k == kind and n == (nums[0],) for c in items]
                result["nums"] = nums[:1]
                result["status"] = "неоднозначно" if cands else "размера нет в справочнике"
                result["matches"] = cands
                return result
            result["nums"] = [ls[0]]
            cands = self.by_type_letters.get((kind, (ls[0],), ls[1]), [])
            if not cands:   # «швеллер 10» без буквы — покажем все варианты полок
                cands = [c for (k, n, l), items in self.by_type_letters.items()
                         if k == kind and n == (ls[0],) for c in items]
                result["status"] = "неоднозначно" if cands else "размера нет в справочнике"
                result["matches"] = cands
                return result
            result["status"] = "совпало" if len(cands) == 1 else "неоднозначно"
            result["matches"] = cands
            return result

        nums = extract_numbers(text)
        result["nums"] = nums
        if not nums:
            result["status"] = "размер не найден"
            return result

        # Профильная труба: квадратная или прямоугольная решают числа,
        # а не слова. 40x40x2 квадратная, 40x20x2 прямоугольная.
        if kind.startswith("Труба профильная") and len(nums) >= 3:
            kind = ("Труба профильная квадратная" if nums[0] == nums[1]
                    else "Труба профильная прямоугольная")
            result["type"] = kind

        cands = self.by_type_nums.get((kind, tuple(nums)), [])
        if not cands:
            result["status"] = "размера нет в справочнике"
            return result

        # Круглая труба: бесшовная и электросварная лежат в справочнике
        # отдельными позициями, отличие зашито в размер («108x4 бесш»).
        # Слово из прайса и решает, какую из двух брать.
        if kind == "Труба круглая" and len(cands) > 1:
            seamless = bool(re.search(r"бесшовная", text))
            picked = [c for c in cands if ("бесш" in c["size"]) == seamless]
            if len(picked) == 1:
                result["status"] = "совпало"
                result["matches"] = picked
                return result

        result["status"] = "совпало" if len(cands) == 1 else "неоднозначно"
        result["matches"] = cands
        return result

    # ------------------------------------------------------------------
    def _match_sheet(self, text):
        if not re.search(r"\bлист\b|\bрулон\b|\bштрипс\b|\bпвл\b", text):
            return None
        kind = next((name for name, pats in SHEET_KINDS
                     if any(re.search(p, text) for p in pats)), None)
        if not kind:
            return None
        m = re.search(r"(%s)\s*(?:мм)?" % NUM, text)
        if not m:
            return {"type": "Лист " + kind, "status": "толщина не найдена"}
        th = float(m.group(1))
        cands = [s for s in self.sheets if s["type"] == kind and abs(s["th"] - th) < 0.001]
        return {"type": "Лист " + kind, "nums": [th],
                "status": "совпало" if len(cands) == 1 else
                          ("неоднозначно" if cands else "толщины нет в справочнике"),
                "matches": [{"size": "%s %s мм" % (c["type"], c["th"]), "id": c["id"],
                             "type": c["type"], "mass": c["mass"]} for c in cands]}


if __name__ == "__main__":
    import sys
    ref = json.load(open(sys.argv[1], encoding="utf-8"))
    matcher = Matcher(ref)
    for line in sys.argv[2:]:
        r = matcher.match(line)
        first = r["matches"][0]["size"] if r["matches"] else "—"
        print("%-52s -> %-30s %-14s %s" % (
            line[:52], (r["type"] or "?"), first, r["status"]))
