"""Вложения → текст для поиска и чтения. Только то, что дёшево и надёжно:
PDF с текстовым слоем (pdftotext), DOCX, XLSX/XLS, TXT/CSV. Сканы и картинки — только имя (распознавание — отдельно).
Тяжёлые файлы обрабатываются с лимитом времени, чтобы один кривой PDF не вешал сборщик."""
import io
import warnings
import os
import re
import subprocess
import tempfile

MAX_CHARS = 40000          # на одно вложение
MAX_ROWS = 300             # строк на лист таблицы
# крупнее — текст не извлекаем (память: сервер 3,8 ГБ, сборщику дано 700 МБ); файл остаётся в оригинале письма
MAX_BYTES = {".pdf": 30 << 20, ".xlsx": 8 << 20, ".xlsm": 8 << 20, ".xls": 8 << 20, ".docx": 15 << 20}
TEXT_EXT = {".txt", ".csv"}


def _clean(text):
    text = text.replace("\x0c", "\n").replace(" ", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _pdf(data):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        try:
            r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-l", "40", f.name, "-"],
                               capture_output=True, timeout=60)
        except FileNotFoundError:
            return None, "нет pdftotext"
        except subprocess.TimeoutExpired:
            return None, "pdf: таймаут"
    text = _clean(r.stdout.decode("utf-8", "replace"))
    if len(re.sub(r"\s", "", text)) < 40:
        return None, "скан или картинка в PDF — текста нет"
    return text, ""


def _docx(data):
    try:
        import docx
    except ImportError:
        return None, "нет python-docx"
    d = docx.Document(io.BytesIO(data))
    out = [p.text for p in d.paragraphs if p.text.strip()]
    for t in d.tables:
        for row in t.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            if any(cells):
                out.append("| " + " | ".join(cells) + " |")
    return _clean("\n".join(out)), ""


def _rows_to_md(name, rows):
    rows = [r for r in rows if any(str(c).strip() for c in r if c is not None)][:MAX_ROWS]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    lines = ["### Лист: %s" % name]
    for r in rows:
        cells = ["" if c is None else str(c).replace("\n", " ").replace("|", "/") for c in r]
        cells += [""] * (width - len(cells))
        while cells and not cells[-1]:
            cells.pop()
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _xlsx(data):
    warnings.filterwarnings("ignore", module="openpyxl")
    try:
        import openpyxl
    except ImportError:
        return None, "нет openpyxl"
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts = [_rows_to_md(ws.title, ws.iter_rows(values_only=True, max_row=MAX_ROWS * 2)) for ws in wb.worksheets]
    return _clean("\n\n".join(p for p in parts if p)), ""


def _xls(data):
    try:
        import xlrd
    except ImportError:
        return None, "нет xlrd"
    wb = xlrd.open_workbook(file_contents=data)
    parts = []
    for sh in wb.sheets():
        rows = [sh.row_values(i) for i in range(min(sh.nrows, MAX_ROWS * 2))]
        parts.append(_rows_to_md(sh.name, rows))
    return _clean("\n\n".join(p for p in parts if p)), ""


def extract(filename, content_type, data):
    """→ (text|None, note)."""
    ext = os.path.splitext(filename or "")[1].lower()
    if len(data) > MAX_BYTES.get(ext, 20 << 20):
        return None, "крупный файл (%d МБ) — текст не извлекался" % (len(data) >> 20)
    try:
        if ext == ".pdf" or content_type == "application/pdf":
            text, note = _pdf(data)
        elif ext == ".docx":
            text, note = _docx(data)
        elif ext in (".xlsx", ".xlsm"):
            text, note = _xlsx(data)
        elif ext == ".xls":
            text, note = _xls(data)
        elif ext in TEXT_EXT or content_type.startswith("text/"):
            for enc in ("utf-8", "cp1251"):
                try:
                    text = data.decode(enc)
                    break
                except UnicodeDecodeError:
                    text = None
            text, note = (_clean(text) if text else None), ""
        else:
            return None, "не текст (%s)" % (ext or content_type)
    except Exception as e:  # битый файл не должен ронять сборщик
        return None, "ошибка чтения: %s" % type(e).__name__
    if text and len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n\n…(обрезано, полный файл — в оригинале письма)"
    return text, note
