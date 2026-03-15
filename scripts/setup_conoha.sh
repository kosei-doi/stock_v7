#!/usr/bin/env bash
#========================================
# ConoHa VPS 初回セットアップ（GitHub Clone 後に1回だけ実行）
# 前提: /opt/dpa_app に git clone 済み
#========================================
set -euo pipefail

APP_DIR="/opt/dpa_app"
SERVICE_NAME="dpa_web"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

cd "${APP_DIR}"

echo "===> Creating venv and installing dependencies..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo "===> Ensuring data/output dirs and config..."
mkdir -p data output
[[ ! -f config.yaml ]] && cp config_example.yaml config.yaml

echo "===> Installing systemd service..."
cp scripts/dpa_web.service "${SERVICE_PATH}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "===> Done. DPA Web is running on port 8000."
systemctl status "${SERVICE_NAME}" --no-pager || true
