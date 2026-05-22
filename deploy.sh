#!/usr/bin/env bash
set -euo pipefail

#========================================
# DPA Web アプリ デプロイスクリプト（Mac 側）
#----------------------------------------
# 【初回・レガシー専用】日常のデプロイは VPS で git pull を使う（docs/OPERATIONS.md 参照）。
#
# 使い方:
#  1. 環境変数を設定: VPS_IP, REMOTE_USER, REMOTE_DIR
#  2. chmod +x deploy.sh
#  3. ./deploy.sh
#
# 例:
#  VPS_IP=1.2.3.4 REMOTE_USER=root REMOTE_DIR=/opt/dpa_app ./deploy.sh
#========================================

: "${VPS_IP:?ERROR: VPS_IP 環境変数を設定してください}"
: "${REMOTE_USER:?ERROR: REMOTE_USER 環境変数を設定してください}"
: "${REMOTE_DIR:?ERROR: REMOTE_DIR 環境変数を設定してください}"

echo "===> Deploying to ${REMOTE_USER}@${VPS_IP}:${REMOTE_DIR}"

# リモート側のディレクトリを作成
ssh "${REMOTE_USER}@${VPS_IP}" "mkdir -p '${REMOTE_DIR}'"

# rsync でプロジェクトを同期（機密・生成物は除外）
# 注意: --delete は意図的に使わない。リモート側の data/ や手動配置した機密を消す危険があるため。
rsync -avz \
  --exclude '.git' \
  --exclude '.gitignore' \
  --exclude 'venv' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache' \
  --exclude '.DS_Store' \
  --exclude '.env' \
  --exclude '.env.*' \
  --exclude 'token.json' \
  --exclude 'credentials.json' \
  --exclude 'data/' \
  --exclude 'output/' \
  --exclude 'terminals' \
  --exclude 'agent-transcripts' \
  ./ "${REMOTE_USER}@${VPS_IP}:${REMOTE_DIR}/"

echo "===> Files synced. Running remote setup script..."

# リモート側のセットアップスクリプトを実行
ssh "${REMOTE_USER}@${VPS_IP}" "bash '${REMOTE_DIR}/scripts/setup_server.sh'"

echo "===> Deploy completed."
