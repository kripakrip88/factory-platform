# -*- coding: utf-8 -*-
"""Лид из письма: название без «RE:», адрес без имени, имя — отдельно
(разбор UX, шаг 27, 02.10.2026).

ЗАЧЕМ. Кнопка «Лид» в почте брала тему и отправителя как есть. В списке
лидов стояло «RE: Запрос…», «FW: Заявка…», «: заказ», в «Эл. почте» — сырое
«Имя <адрес>», а «Имя контакта» оставалось пустым (ночной осмотр 29.09).
Здесь — правила; модель (models/mail_client_message.py, _pmk_create_lead),
миграция 19.0.1.0.6 (лиды, заведённые раньше) и схема связей (pmk_flow,
подпись узла письма) зовут их сами.

ЧИСТЫЕ ФУНКЦИИ БЕЗ ODOO, как quote_fold: их гоняет голый питон
(tests/test_lead_text_rules.py) до всякого деплоя.

ЧТО НЕ ТРОГАЕМ. Письмо в ленте лида (message_post) остаётся каким пришло —
со своей темой и отправителем: это само письмо, а не карточка лида.
"""
import re

# Приставки ответа и пересылки в начале темы — сколько угодно подряд, в любом
# регистре, с номером ответа («Re[2]:», «Re(2):»), точкой («Пересл.:») и
# пробелом перед двоеточием («Fwd :»). Русские так пишет русский Outlook,
# остальные — почтовые программы других языков, которые бывают у
# поставщиков: AW/WG — немецкие, TR — французская, RV — испанская, SV —
# скандинавская. Без двоеточия приставкой не считается: «Ответ по запросу…»
# (лид 9) — это тема, а не приставка.
_PREFIX = re.compile(
    r"^\s*(?:(?:re|fwd?|aw|wg|tr|rv|sv|отв|ответ|пересл)\.?\s*"
    r"(?:\[\d+\]|\(\d+\))?\s*[:：]\s*)+",
    re.IGNORECASE)
# Знаки, которыми тема начинается после снятой приставки или сама по себе
# («: заказ», лид 15). Тире — только с пробелом за ним: «-10% на лист»
# остаётся как есть.
_LEADING_PUNCT = re.compile(r"^(?:[\s:;,.]|[-–—](?=\s))+")

# «Имя <адрес>» — адрес в угловых скобках; голый адрес — без них.
_ANGLE_ADDRESS = re.compile(r"<\s*([^<>\s@]+@[^<>\s]+?)\s*>")
_BARE_ADDRESS = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
_LETTER = re.compile(r"[^\W\d_]")


def _capitalized(text):
    """Первая буква заглавная — только у обычного слова: первое слово
    целиком строчное и в нём не меньше четырёх букв («запрос» → «Запрос»).

    Короткое слово строчными — скорее сокращение, написанное наспех: «ммк»,
    «спк», «кп» не превращаем в «Ммк», «Спк», «Кп». Слово со смешанным
    регистром — имя собственное: «iPhone», «eBay» не превращаем в «IPhone».
    Клиентский текст не искажаем: сомневаемся — оставляем как написано.
    Цена правила в обе стороны: короткое обычное слово останется строчным
    («акт сверки» — не искажение, просто без украшения), а сокращение из
    четырёх букв строчными станет с заглавной («гост» → «Гост»)."""
    word = text.split(None, 1)[0]
    if text[0].islower() and word.islower() and len(_LETTER.findall(word)) >= 4:
        return text[0].upper() + text[1:]
    return text


def clean_subject(subject):
    """Тема письма → название лида.

    Снимает в начале «Re:», «RE:», «Fw:», «FW:», «Fwd:», «AW:», «WG:»,
    «TR:», «RV:», «SV:», «Отв:», «Ответ:», «Пересл.:» — сколько угодно раз, в
    том числе «Re[2]:» и «Re(2):», — а за ними ведущие «: ; , .» и тире с
    пробелом. Если что-то сняли и первое слово обычное, первая буква
    становится заглавной («RE: запрос МЦ СИЗ» → «Запрос МЦ СИЗ» — так лид 14
    переименовали руками); сокращения и имена — как написаны («Fwd: RE:
    ммк» → «ммк», «re: iPhone» → «iPhone»), см. _capitalized.
    Ничего не осталось («RE:») — пустая строка: название решает тот, кто
    зовёт («Без темы»). «Трубы: прайс» и «Заявка: лист» — без изменений.
    """
    original = (subject or "").strip()
    text = original
    while True:
        stripped = _LEADING_PUNCT.sub("", _PREFIX.sub("", text)).strip()
        if stripped == text:
            break
        text = stripped
    if text and text != original:
        text = _capitalized(text)
    return text


def _clean_name(raw):
    """Имя перед «<адрес>»: без кавычек и лишних пробелов. Имя-адрес
    («vld12@bvbmail.ru <vld12@bvbmail.ru>», лид 19), имя без единой буквы и
    нераскодированное «=?UTF-8?…» — не имя."""
    name = (raw or "").strip().rstrip(",;").strip()
    name = name.strip("\"'«»").strip().replace('\\"', '"')
    name = re.sub(r"\s+", " ", name)
    if not name or "@" in name or name.startswith("=?") or not _LETTER.search(name):
        return ""
    return name


def split_sender(text):
    """«Имя <адрес>» → (имя, адрес). Берётся первый отправитель.

    Голый адрес — ("", адрес); ни одного адреса — ("", ""). Адрес — как
    написан, регистр не меняем (нормализованный ядро считает само,
    email_normalized)."""
    text = (text or "").strip()
    if not text:
        return "", ""
    match = _ANGLE_ADDRESS.search(text)
    if match:
        return _clean_name(text[:match.start()]), match.group(1)
    bare = _BARE_ADDRESS.search(text)
    return "", bare.group(0) if bare else ""


def contact_name(name, address, own_addresses=()):
    """Имя для «Имя контакта» лида — или пусто.

    Наши ящики (pmkpark@mail.ru, zakaz@pmkpark.ru) и почта организации имени
    не дают: письмо, пересланное коллегой («Владимир Голубенко»
    <pmkpark@mail.ru>, лиды 3 и 5), не делает его контактом клиента.
    own_addresses — нормализованные (строчные) адреса завода."""
    if not name:
        return ""
    if (address or "").strip().lower() in set(own_addresses or ()):
        return ""
    return name


def _space_marks(text):
    """Номера букв (без пробелов), перед которыми в тексте стоит пробел."""
    marks, count = set(), 0
    for index, char in enumerate(text):
        if char.isspace():
            continue
        if index and text[index - 1].isspace():
            marks.add(count)
        count += 1
    return marks


def better_spelling(name, candidates):
    """То же имя из писем «Почты», если у нас в нём пробел посреди слова.

    Лиды 5–11 боевой базы завёл алиас ядра (zakaz@ → лид, выключен 28.09):
    имя из заголовка «От» он раскодировал с пробелом на стыке кусков —
    «Киселёв Николай Сергеев ич». Те же письма в «Почте» (vendor/mail_client)
    раскодированы верно: «Киселёв Николай Сергеевич». Берём вариант из
    письма, только если буквы те же один в один, а лишние пробелы у нас —
    посреди слова (за пробелом строчная буква: «ев ич», «Никол аевна»).
    Пробел перед заглавной («Иван Петров» против «ИванПетров» в письме) —
    граница слов, его не трогаем. Иначе имя как было — ничего не угадываем.
    candidates — имена из писем с тем же адресом, свежие первыми."""
    name = (name or "").strip()
    if not name:
        return name
    letters = re.sub(r"\s+", "", name)
    ours = _space_marks(name)
    for candidate in candidates or ():
        candidate = re.sub(r"\s+", " ", (candidate or "").strip())
        if not candidate or re.sub(r"\s+", "", candidate) != letters:
            continue
        theirs = _space_marks(candidate)
        extra = ours - theirs
        if theirs < ours and all(letters[mark].islower() for mark in extra):
            return candidate
    return name


def cleanup_values(name, email_from, current_contact, has_person=False, own_addresses=()):
    """Что поправить у лида, заведённого до шага 27 (миграция 19.0.1.0.6).

    • название — только если начинается с приставки или знака препинания;
    • «Эл. почта» — только если в ней «Имя <адрес>»: остаётся адрес;
    • «Имя контакта» — только если пусто, у лида нет контакта-человека
      (has_person; иначе имя ставит ядро из контакта) и имя не нашего ящика.
    Повторный вызов на исправленном ничего не находит (идемпотентно)."""
    values = {}
    original = (name or "").strip()
    cleaned = clean_subject(original)
    if cleaned and cleaned != original:
        values["name"] = cleaned
    sender, address = split_sender(email_from)
    if address and address != (email_from or "").strip():
        values["email_from"] = address
    if not (current_contact or "").strip() and not has_person:
        person = contact_name(sender, address, own_addresses)
        if person:
            values["contact_name"] = person
    return values
