#!/bin/bash
# Подготовка чистого Ubuntu 24.04 под pmk-main (повтор того, что сделано руками 15.11.2026).
# Запуск от root на новом сервере: bash bootstrap.sh   — идемпотентно.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# Зеркало Бегета отвечало 502 — берём штатные archive.ubuntu.com из ubuntu.sources.
if grep -q '^deb .*public-mirrors.beget.ru' /etc/apt/sources.list 2>/dev/null; then
  cp -n /etc/apt/sources.list /etc/apt/sources.list.beget.bak
  sed -i 's|^deb |# beget-mirror 502 (15.11.2026): deb |' /etc/apt/sources.list
fi

timedatectl set-timezone Europe/Moscow
hostnamectl set-hostname pmk-main
apt-get update -qq || true
apt-get install -y -qq ca-certificates curl gnupg git ufw htop ncdu jq rsync unzip zstd bind9-dnsutils whois

if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq || true
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
mkdir -p /etc/docker
[ -f /etc/docker/daemon.json ] || cat > /etc/docker/daemon.json <<'J'
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "20m", "max-file": "5"},
  "live-restore": true
}
J
systemctl enable --now docker

if [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi
echo "vm.swappiness=10" > /etc/sysctl.d/90-swap.conf

ufw allow OpenSSH; ufw allow 80/tcp; ufw allow 443/tcp; ufw --force enable

mkdir -p /opt/git /opt/edge /opt/site /opt/1c /opt/backups/odoo /opt/backups/site /opt/backups/1c
[ -d /opt/git/factory-platform.git ] || git init -q --bare /opt/git/factory-platform.git
echo "готово: дальше git push с Mac в /opt/git/factory-platform.git, clone в /opt/factory-platform"
