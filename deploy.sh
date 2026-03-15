#!/usr/bin/env bash
set -euo pipefail

#========================================
# DPA Web アプリ デプロイスクリプト（Mac 側）
#----------------------------------------
# 使い方:
#  1. 下の VPS_IP を自分の VPS の IP に書き換える
#  2. chmod +x deploy.sh
#  3. ./deploy.sh
#========================================

VPS_IP="160.251.207.174"
REMOTE_USER="root"
REMOTE_DIR="/opt/dpa_app"

if [[ "$VPS_IP" == "YOUR_VPS_IP" ]]; then
  echo "ERROR: deploy.sh 内の VPS_IP を実際の VPS IP アドレスに書き換えてください。" >&2
  exit 1
fi

echo "===> Deploying to ${REMOTE_USER}@${VPS_IP}:${REMOTE_DIR}"

# リモート側のディレクトリを作成
ssh "${REMOTE_USER}@${VPS_IP}" "mkdir -p '${REMOTE_DIR}'"

# rsync でプロジェクトを同期（不要・機密ファイルは除外）
rsync -avz --delete \
  --exclude '.git' \
  --exclude '.gitignore' \
  --exclude '.venv' \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache' \
  --exclude '.DS_Store' \
  --exclude '.env' \
  --exclude 'terminals' \
  --exclude 'agent-transcripts' \
  ./ "${REMOTE_USER}@${VPS_IP}:${REMOTE_DIR}/"

echo "===> Files synced. Running remote setup script..."

# リモート側のセットアップスクリプトを実行
ssh "${REMOTE_USER}@${VPS_IP}" "bash '${REMOTE_DIR}/scripts/setup_server.sh'"

echo "===> Deploy completed."

