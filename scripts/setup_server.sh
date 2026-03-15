#!/usr/bin/env bash
set -euo pipefail

#========================================
# DPA Web アプリ サーバーセットアップスクリプト（VPS 側）
#----------------------------------------
# 前提:
#  - root ユーザーで実行
#  - アプリコードは /opt/dpa_app に配置済み（deploy.sh が rsync 済み）
#========================================

APP_DIR="/opt/dpa_app"
SERVICE_NAME="dpa_web"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

echo "===> Updating apt package index..."
apt update -y

echo "===> Installing Python runtime and build tools..."
DEBIAN_FRONTEND=noninteractive apt install -y \
  python3 \
  python3-venv \
  python3-pip

cd "${APP_DIR}"

echo "===> Creating Python virtual environment..."
python3 -m venv venv

echo "===> Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo "===> Installing systemd service..."
if [[ ! -f "scripts/dpa_web.service" ]]; then
  echo "ERROR: scripts/dpa_web.service が見つかりません。" >&2
  exit 1
fi

cp "scripts/dpa_web.service" "${SERVICE_PATH}"

echo "===> Reloading systemd and starting service..."
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "===> Setup completed. Service status:"
systemctl status "${SERVICE_NAME}" --no-pager || true

