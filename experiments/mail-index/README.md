# mail-index — почта pmkpark@ → цепочки переписки для анализа ИИ

Статус: **этап 1 (отладка на последних 3 месяцах)**, ветка `feature/mail-index`. Сервер: claude-vps.
Решение Антона 17.11.2026: только ящик pmkpark@mail.ru; сначала скрипты и отладка без ИИ, модели — потом.

## Что делает

1. **Сборщик** (`mailindex sync`, таймер каждые 10 мин) — IMAP mail.ru **только чтение**: `EXAMINE` + `BODY.PEEK[]`,
   письма не помечаются прочитанными, в ящике ничего не меняется. Помнит последний UID по каждой папке.
   Спам, корзина, черновики — не берутся.
2. **Оригинал** — `.eml.zst` в `/srv/mail-index/eml/ГГГГ/ММ/` (позже — в облако Яндекса, этап 4).
3. **Разбор** — шапка, текст (plain, иначе HTML → текст), подпись отдельно, цитата отдельно.
   Вложения PDF (с текстом) / DOCX / XLSX / XLS / TXT → `md/att/…`. Сканы и картинки — только имя.
4. **Цепочки** — по Message-ID (References / In-Reply-To), без них — по теме и собеседнику за 90 дней.
   Один файл на переписку: `md/threads/ГГГГ/ДАТА_тема_id.md` — обе стороны по порядку, «ответ через N ч».
   Цитата показывается, только если цитируемого письма в архиве нет; ответы по пунктам и пересылки не режутся.
5. **Поиск** — SQLite FTS5 (trigram, по части слова): `mail-search "закладные МН" --who stroy --since 2025-01-01`.

## Этапы

| # | Что | ИИ |
|---|---|---|
| 1 | сборщик + Markdown + цепочки, отладка на 3 месяцах | нет |
| 2 | поиск `mail-search` для Claude в Телеграме | нет |
| 3 | таймер, сигнал в Телеграм при сбое, утренняя сводка | нет |
| 4 | вся история с 2019 по ночам + архив .eml в Яндекс | нет |
| 5 | векторы → Qdrant (поиск по смыслу), ключ Beget | да |
| 6 | разметка писем (тип, клиент, изделие, сумма) | да |

## Установка (claude-vps, root)

```bash
bash deploy/install.sh
# пароль приложения mail.ru — Антон, скрытым вводом:
#   /etc/mail-index/imap.env: MAIL_USER=pmkpark@mail.ru, MAIL_PASS=…  (root:root 600 — Claude в Телеграме его не читает)
set -a; . /etc/mail-index/settings.env; . /etc/mail-index/imap.env; set +a
sudo -E -u mailidx /opt/mail-index/venv/bin/python -m mailindex sync --limit 30   # проба
systemctl enable --now mail-index-sync.timer
```

Нагрузка: `Nice=15`, `IOSchedulingClass=idle`, `CPUQuota=60%`, `MemoryMax=700M`. Odoo не трогается — сервер другой,
ящик читается напрямую.

## Команды

```
python -m mailindex sync [--limit N]   новые письма + пересборка изменившихся цепочек
python -m mailindex build              пересобрать цепочки
python -m mailindex reparse            перечитать все письма из оригиналов (после правки разбора)
python -m mailindex stats
python -m mailindex search "текст" [--who X] [--since Д] [--until Д] [--in|--out] [-n 10] [--json]
```

Тесты: `python3 -m unittest discover tests`.
