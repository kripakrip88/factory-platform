#!/usr/bin/env python3
"""
Готовит docker-compose.prod.patched.yml из их docker-compose.prod.yml.

ЗАЧЕМ. В их стеке единственный сервис, публикующий порты, — caddy, и он берёт
80/443 в mode: host. У нас эти порты держит infra-nginx (erppark.ru, d.erppark.ru,
n8n.erppark.ru) — Carbon бы их просто не получил, а прод остался бы без входа.

ЧТО ДЕЛАЕМ. Caddy оставляем (его маршрутизация по Host и security-заголовки нам
подходят), но отдаём ему ОДИН порт 8083 вместо 80/443/443udp. TLS терминирует
наш infra-nginx на трёх поддоменах и проксирует на 8083, сохраняя заголовок Host,
по которому Caddy разводит запросы на erp / mes / kong. В .env хосты задаются с
префиксом http:// — так Caddy не включает собственный ACME и не пытается занять 443.
X-Forwarded-Proto от nginx Caddy примет: у него в Caddyfile уже стоит
`trusted_proxies static private_ranges`, а наш nginx приходит из 172.18.0.0/16.

ПОЧЕМУ ТЕКСТОВОЙ ЗАМЕНОЙ, А НЕ ЧЕРЕЗ YAML. У них в файле YAML-анchors
(*shim, *restart, *app-deploy). Прогон через PyYAML их развернёт и перепишет весь
файл; при обновлении апстрима diff станет нечитаемым. Точечная замена оставляет
остальные ~600 строк байт-в-байт их, поэтому любое их изменение видно сразу.

ПОЧЕМУ НЕ OVERRIDE-ФАЙЛОМ. `docker stack deploy -c a -c b` списки не заменяет,
а ДОПОЛНЯЕТ — порты 80/443 остались бы вместе с 8083.

Идемпотентно: повторный запуск ничего не портит.
"""
import sys
from pathlib import Path

# Их блок портов caddy — ровно как в апстриме на коммите 7daffaab.
ORIGINAL = """    ports:
      - target: 80
        published: 80
        mode: host
      - target: 443
        published: 443
        mode: host
      - target: 443
        published: 443
        protocol: udp
        mode: host
"""

REPLACEMENT = """    ports:
      # ПРАВКА (factory-platform): вместо 80/443/443udp — один порт 8083.
      # 80/443 на этой машине держит infra-nginx (erppark.ru и др.); TLS делает он,
      # Caddy получает HTTP и разводит по Host. См. patch-compose.py.
      - target: 80
        published: ${CADDY_HTTP_PORT:-8083}
        mode: host
"""

MARKER = "ПРАВКА (factory-platform)"


def main() -> int:
    if len(sys.argv) != 3:
        print("использование: patch-compose.py <исходный yml> <результат>", file=sys.stderr)
        return 2

    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    if not src.is_file():
        print(f"❌ не найден {src}", file=sys.stderr)
        return 1

    text = src.read_text(encoding="utf-8")

    if MARKER in text:
        print("✓ исходник уже пропатчен — копирую как есть")
        dst.write_text(text, encoding="utf-8")
        return 0

    count = text.count(ORIGINAL)
    if count != 1:
        print(
            f"❌ ожидался ровно 1 блок портов caddy, найдено {count}.\n"
            "   Апстрим изменил docker-compose.prod.yml — сверить блок ports у caddy\n"
            "   и обновить ORIGINAL в этом скрипте. Патч НЕ применён.",
            file=sys.stderr,
        )
        return 1

    patched = text.replace(ORIGINAL, REPLACEMENT, 1)

    # Страховка: 443 не должен остаться опубликованным нигде.
    for bad in ("published: 443", "published: 80\n"):
        if bad in patched:
            print(f"❌ после патча остался «{bad.strip()}» — проверить вручную", file=sys.stderr)
            return 1

    dst.write_text(patched, encoding="utf-8")
    print(f"✓ пропатчено: {dst}")
    print("  caddy: 80/443/443udp → ${CADDY_HTTP_PORT:-8083} (mode: host)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
