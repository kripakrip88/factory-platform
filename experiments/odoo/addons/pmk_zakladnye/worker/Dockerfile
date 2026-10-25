# Чертёжный процесс закладных (odoo-zk-worker, 25.10.2026): только Python + PyMuPDF + шрифт.
# Образ Odoo не трогаем — PyMuPDF нужен одному этому процессу. Код берётся из папки модулей
# (/mnt/third-party/pmk_zakladnye, только чтение), очередь — общая папка данных Odoo.
#
# Шрифт чертежей — Liberation Sans Narrow Italic (решение Антона: свободный, метрически
# = Arial Narrow). Он есть в пакете fonts-liberation (версия 1.x — в fonts-liberation2 узкого нет).
# PyMuPDF закреплён: на 1.26.5 сверены эталоны вёрстки (проверка «линия через надпись» — 0 из 786).
#
# Пользователь — uid 100 / gid 101, как odoo в образе Odoo: файлы задания Odoo должен
# прочитать и удалить.
FROM python:3.12.7-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && test -f /usr/share/fonts/truetype/liberation/LiberationSansNarrow-Italic.ttf

RUN pip install --no-cache-dir pymupdf==1.26.5

RUN groupadd -g 101 odoo && useradd -u 100 -g 101 -M -d /nonexistent odoo
USER odoo

ENTRYPOINT ["python3", "/mnt/third-party/pmk_zakladnye/worker/worker.py"]
CMD ["/var/lib/odoo/zakladnye"]
