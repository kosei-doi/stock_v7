#!/usr/bin/env bash
# 本番 VPS 向け JSON → SQLite 移行ラッパー（DB-8）
# 用法: APP_DIR=/opt/dpa_app ./scripts/migrate_production.sh [--archive-json] [--no-stop]
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/dpa_app}"
ARCHIVE_JSON=0
STOP_SERVICE=1

for arg in "$@"; do
  case "$arg" in
    --archive-json) ARCHIVE_JSON=1 ;;
    --no-stop) STOP_SERVICE=0 ;;
    *)
      echo "未知の引数: $arg" >&2
      echo "用法: $0 [--archive-json] [--no-stop]" >&2
      exit 1
      ;;
  esac
done

cd "${APP_DIR}"
PY="${APP_DIR}/venv/bin/python"
if [[ ! -x "${PY}" ]]; then
  PY=python3
fi

echo "===> APP_DIR=${APP_DIR}"

if [[ "${STOP_SERVICE}" -eq 1 ]] && systemctl is-active --quiet dpa_web 2>/dev/null; then
  echo "===> Stopping dpa_web..."
  sudo systemctl stop dpa_web
fi

echo "===> Dry-run (件数確認)"
"${PY}" scripts/migrate_json_to_db.py --data-dir "${APP_DIR}" --dry-run

echo ""
read -r -p "import を実行しますか? [y/N] " ans
if [[ "${ans}" != "y" && "${ans}" != "Y" ]]; then
  echo "中止しました。"
  exit 0
fi

IMPORT_ARGS=(--data-dir "${APP_DIR}")
if [[ "${ARCHIVE_JSON}" -eq 1 ]]; then
  IMPORT_ARGS+=(--archive-json)
fi

echo "===> Import"
"${PY}" scripts/migrate_json_to_db.py "${IMPORT_ARGS[@]}"

echo "===> Verify JSON vs DB"
"${PY}" scripts/verify_db_migration.py --data-dir "${APP_DIR}"

echo ""
echo "===> 次のステップ"
echo "  1. /etc/dpa-app/dpa.env に以下を設定:"
echo "     DPA_PERSISTENCE=sqlite"
echo "     DPA_DATABASE_URL=sqlite:////opt/dpa_app/data/dpa.db"
echo "  2. sudo systemctl start dpa_web"
echo "  3. docs/OPERATIONS.md の「移行後の整合チェック」を実施"

if [[ "${STOP_SERVICE}" -eq 1 ]]; then
  echo ""
  read -r -p "dpa_web を起動しますか? [y/N] " start_ans
  if [[ "${start_ans}" == "y" || "${start_ans}" == "Y" ]]; then
    sudo systemctl start dpa_web
    systemctl status dpa_web --no-pager || true
  fi
fi

echo "===> Done."
