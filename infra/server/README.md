# Сервер pmk-main — 45.153.188.84 (с 15.11.2026)

Бегет, Санкт-Петербург (AS198610, сеть RU-BEGET-20190913 45.153.188.0/22). 6 vCPU, 11 ГБ RAM,
4 ГБ swap, 145 ГБ NVMe, Ubuntu 24.04. Замена VPS 155.212.143.179, погибшего при атаке на Бегет 02.11.2026.
Доступ: ключ `id_factory`, алиас `ssh odoo-new` (ControlMaster — sshd под постоянным подбором пароля,
отдельные подключения иногда рвутся на обмене баннером).

## Что на сервере

| Система | Папка | Docker-проект | Порт (только 172.17.0.1) | Домен |
|---|---|---|---|---|
| Общий вход nginx 80/443 + Let's Encrypt | /opt/edge | `edge` | 80, 443 наружу | все |
| Odoo 19 боевой | /opt/experiments/odoo | `odoo` | 8084 (+8085 websocket) | erppark.ru |
| Odoo — копия для проверки | /opt/experiments/odoo/dryrun | `odoo-stage` | 127.0.0.1:8099 | туннель с Mac |
| Сайт pmkpark.ru (Битрикс) | /opt/site (infra/site) | `site` | 8090 | pmkpark.ru — с 16.11.2026 |
| 1С | /opt/1c | `onec` | 8091 (веб-публикация) | 1c.erppark.ru — заготовка |
| Бэкапы | /opt/backups/{odoo,site,1c} | — | — | — |

Код: GitHub с сервера по HTTPS недоступен (15.11.2026, см. ниже), поэтому на сервере свой bare-репозиторий
`/opt/git/factory-platform.git` — в него пушат с Mac (`git push odoo-new:/opt/git/factory-platform.git
<ветка>`), чекаут `/opt/factory-platform` берёт `origin` оттуда. deploy.sh работает как раньше.

## Бюджет памяти (11 ГБ + 4 ГБ swap)

| | лимит | обычно |
|---|---|---|
| Odoo app (2 http + cron) | 2,5 ГБ | ~1 ГБ |
| Odoo db | 768 МБ | ~300 МБ |
| раскрой / ассистент / чертежи | 3 ГБ / 768 МБ / 512 МБ | ~0,3 ГБ |
| копия Odoo (workers 0) | 1,5 ГБ | ~0,6 ГБ |
| сайт: nginx+php-fpm+MySQL | 2 ГБ | ~1 ГБ |
| 1С: сервер + PostgreSQL для 1С | 4 ГБ | 2–3 ГБ |
| edge nginx | 256 МБ | ~20 МБ |

Всё вместе в обычной работе ≈ 6–7 ГБ. Если 1С разрастётся — раскрою (`NEST_PROCS`) снизить до 2.

## Подготовка ОС (сделано 15.11.2026, повторить на новом сервере — bootstrap.sh)

- Зеркало apt Бегета (public-mirrors.beget.ru) отвечало 502 — строки в /etc/apt/sources.list закомментированы
  (копия sources.list.beget.bak), обновления идут с archive.ubuntu.com (ubuntu.sources).
- Docker CE из download.docker.com, логи контейнеров 5×20 МБ, live-restore.
- swap 4 ГБ, swappiness 10; часовой пояс Europe/Moscow; hostname pmk-main.
- ufw: 22, 80, 443. Порты контейнеров привязаны к 172.17.0.1 — Docker идёт в обход ufw.
- fail2ban (sshd) — из образа Бегета, за сутки 40 банов.

## Сеть (проверка 16.11.2026)

- 13–15.11 github.com (443/80) и api.moysklad.ru были недоступны — пакеты терялись на стороне
  получателя (Telia / MSK-IX). 16.11 повторная проверка: оба отвечают за 0,05–0,4 с, `git ls-remote`
  по https проходит, MTU 1500 в порядке. Было временным у Бегета после атаки; обходов не ставили.
- api.anthropic.com — 403 «Request not allowed» (Anthropic не пускает IP из РФ). Обход — туннель:
  - служба `anthropic-relay` (systemd): `ssh -N -L 172.17.0.1:8443:api.anthropic.com:443
    relay@31.77.141.89` (NL, сервер личного VPN), ключ `/root/.ssh/id_relay`;
  - на NL — пользователь `relay` без консоли, в authorized_keys `restrict,port-forwarding,
    permitopen="api.anthropic.com:443",from="45.153.188.84"` — ничего, кроме этого адреса;
  - TLS сквозной до Anthropic (сертификат настоящий), ключ API на NL не виден;
  - в контейнерах odoo и ai-worker `extra_hosts: api.anthropic.com:host-gateway`, в Odoo
    `pmk_ai.api_base = https://api.anthropic.com:8443`; ufw пускает к 8443 только 172.16.0.0/12;
  - проверка: `curl --resolve api.anthropic.com:8443:172.17.0.1 https://api.anthropic.com:8443/v1/models`
    → 401 (без ключа) за ~0,3 с. Упал туннель — `systemctl status anthropic-relay`.
- Работают напрямую: GitHub, МойСклад, Телеграм, DaData, Docker Hub, pypi, git.ruodoo.ru, Let's Encrypt.

## RuOdoo: выпуск 2026-11-08 против наших модулей (15.11.2026)

Публичный репозиторий RuOdoo хранит только последний выпуск (история не доступна), а в выпуске 2026-10-15:
- `l10n_ru_upd_xml` помечен `installable: False` («устаревший механизм УПД»), но на нём стоят `pmk_bridge`
  (поле ОКЕИ единиц) и `pmk_partner`. На сервере в чекауте RuOdoo флаг вручную возвращён в True
  (`git -C /opt/experiments/odoo/ruodoo diff`). После `git pull` RuOdoo — повторить, иначе наши модули не
  загрузятся. Правильный путь — уйти с этого модуля на `rsbu_fns_reporting` (отдельная задача).
- `l10n_ru_act_rev` (акты сверки) выведен по безопасности — со старой базы удалён (button_immediate_uninstall).
- `l10n_ru_advance_payments` теперь требует `l10n_latam_check` и `docx_report` — на старой базе доставить `-i`.

## Бэкап вне Бегета — Yandex Object Storage (16.11.2026)

`infra/server/backup-offsite.sh`, cron 04:20 (после `backup-stand.sh` в 03:40), журнал `/var/log/odoo-offsite.log`.
Ночной дамп базы → `odoo/db/` (бакет удаляет старше 30 дней), вложения по файлам, только новые → `odoo/filestore/`,
разово дамп 22.10 → `archive/`. Ключ — `/root/.yc-backup.env` (YC_KEY_ID, YC_SECRET, YC_BUCKET; chmod 600),
сервисный аккаунт с ролью `storage.uploader` (удалять не может), в бакете версионирование. ~2 ГБ ≈ 3 ₽/мес.
Отметка последнего успеха — `/var/lib/pmk-offsite/last_ok`. Восстановление — в шапке скрипта.

## Сайт pmkpark.ru (с 16.11.2026)

Перенесён с 141.133.188.220 (ISPmanager; остаётся запасным ~неделю). Стек `infra/site`: PHP 8.3.35 + Apache
(mod_php, .htaccess как было) + MySQL 8.0.46, база сокетом — файлы Битрикса без правок. Данные таблицы
`b_user_session` (1,6 ГБ сессий) не переносились. Письма форм — модуль wsrubi.smtp → smtp.yandex.ru:587.
Восстановить базу из дампа: `bash infra/site/site-restore.sh <дамп.sql.gz>`. Дамп — `infra/site/backup-site.sh`, 03:50.

## Восстановление из одного места

Всё (код, RuOdoo, образы Docker, зашифрованные секреты, базы, вложения, файлы сайта) — в бакете Яндекса,
см. `RESTORE.md` и `restore-all.sh`. Комплект обновляет `backup-kit.sh` (шаг ночной выгрузки), только изменившееся.
Пароль комплекта — /root/.backup-passphrase и у Антона в менеджере паролей. Сторож `backup-check.sh` (09:00)
пишет Антону в Телеграм, если ночной бэкап не прошёл.

## 1С (с 16.11.2026)

Бухгалтерия предприятия 3.0, 1–2 пользователя → ФАЙЛОВАЯ база `/opt/1c/bases/buh` + веб-публикация `/buh`
(Apache 2.4 на хосте, только 172.17.0.1:8091; кластер 1С не запущен, порты 1540+ закрыты). Платформа 8.3.27.2342
из `deb64_8_3_27_2342.zip` (releases.1c.ru, логин ИТС Антона) — копия в `/opt/1c/dist` и в бакете `kit/1c/`.
- Установка: `infra/1c/install-1c.sh`; загрузить базу: `infra/1c/restore-1c.sh <файл.dt>` (старая → buh.before-…).
- Выгрузка 03:30: `infra/1c/backup-1c.sh` (Apache на время останавливается) → `/opt/backups/1c` → бакет `1c/db/`.
- Грабли: ufw — правило 172.16.0.0/12 → 172.17.0.1:8091 (nginx в Docker, Apache на хосте); кэш 1С пишется в
  /var/www/.1cv8 (иначе «вход в приложение невозможен»).
- Лицензии (ПРОФ, программные) привязываются к «железу»: после переезда/восстановления — повторная активация.
