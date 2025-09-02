#!/opt/homebrew/bin/bash

set -euo pipefail

# --- 設定セクション ---
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

COMPOSE_FILE="${DIR}/../ticket_v2_api/docker/docker-compose.yml"
SERVICE="mysql_tools"
MYSQL_USER="root"
MYSQL_PASS="root"
DUMP_DIR="${DIR}/dumps"

# データベース名 → 接続ホスト名 のマッピング
declare -A DBS=(
  ["ticket_v2_api_local"]="ticket_v2_api_db"
  ["ticket_v2_api_portal_local"]="ticket_v2_api_portal_db"
  ["ticket_v2_api_promoter_local_1"]="ticket_v2_api_promoter_db"
  ["ticket_v2_api_promoter_local_4"]="ticket_v2_api_promoter_db"
  ["ticket_v2_api_promoter_local_5"]="ticket_v2_api_promoter_db"
  ["ticket_v2_api_promoter_local_6"]="ticket_v2_api_promoter_db"
  # 本番環境のデータベース
  # ["ticket_v2_api"]="ticket_v2_api_db"
  # ["ticket_v2_api_portal"]="ticket_v2_api_portal_db"
  # ["ticket_v2_api_promoter_4"]="ticket_v2_api_promoter_db"
  # ["ticket_v2_api_promoter_5"]="ticket_v2_api_promoter_db"
  # ["ticket_v2_api_promoter_6"]="ticket_v2_api_promoter_db"
)
# -----------------------

usage() {
  cat <<EOF
Usage: $(basename "$0") {dump|restore} [DATE_STR]

  dump     : 全DBをダンプ
  restore  : 全DBをリストア
  DATE_STR : ファイル名に付与する日付（省略時は本日 YYYYMMDD）
EOF
  exit 1
}

# --- 引数チェック ---
if [ $# -lt 1 ] || ([[ "$1" != "dump" ]] && [[ "$1" != "restore" ]]); then
  usage
fi

ACTION="$1"; shift

# DATE_STR：第１引数（既に shift後の$1）があればそれ、なければ今日の日付
if [ $# -ge 1 ] && [[ -n "${1}" ]]; then
  DATE_STR="$1"
else
  DATE_STR="$(date +'%Y%m%d')"
fi

dump_all() {
  mkdir -p "$DUMP_DIR"
  for db in "${!DBS[@]}"; do
    host="${DBS[$db]:-}"
    if [[ -z "$host" ]]; then
      echo "[warn] '$db' の接続ホストが未定義です。スキップします。"
      continue
    fi
    out="$DUMP_DIR/${db}_${DATE_STR}.sql"
    echo "[dump] ${db} ← ${host} → ${out}"
    docker compose -f "$COMPOSE_FILE" run --rm --remove-orphans "$SERVICE" \
      mysqldump \
        --single-transaction \
        --quick \
        --routines \
        --triggers \
        --set-gtid-purged=OFF \
        --skip-generated-invisible-primary-key \
        --complete-insert \
        -u"$MYSQL_USER" -p"$MYSQL_PASS" \
        -h"$host" "$db" \
      > "$out"
  done
  echo "→ ダンプ完了: $DUMP_DIR に保存"
}

restore_all() {
  for db in "${!DBS[@]}"; do
    host="${DBS[$db]:-}"
    if [[ -z "$host" ]]; then
      echo "[warn] '$db' の接続ホストが未定義です。スキップします。"
      continue
    fi
    sqlfile="$DUMP_DIR/${db}_${DATE_STR}.sql"
    if [[ ! -f "$sqlfile" ]]; then
      echo "[skip] $sqlfile が見つかりません。"
      continue
    fi
    echo "[recreate] ${db} on ${host}… (DROP → CREATE)"
    # DBを一旦削除して作り直す
    docker compose -f "$COMPOSE_FILE" run --rm -T --remove-orphans "$SERVICE" \
      mysql -u"$MYSQL_USER" -p"$MYSQL_PASS" -h"$host" \
      -e "DROP DATABASE IF EXISTS \`$db\`;"
    docker compose -f "$COMPOSE_FILE" run --rm -T --remove-orphans "$SERVICE" \
      mysql -u"$MYSQL_USER" -p"$MYSQL_PASS" -h"$host" \
      -e "CREATE DATABASE \`$db\`;"

    echo "[restore] ${db} ← ${sqlfile}"
    # インポート
    docker compose -f "$COMPOSE_FILE" run --rm -T --remove-orphans "$SERVICE" \
        mysql -u"$MYSQL_USER" -p"$MYSQL_PASS" -h"$host" "$db" \
      < "$sqlfile"
  done
  echo "→ リストア完了"
}

# --- 実行 ---
if [[ "$ACTION" == "dump" ]]; then
  dump_all
else
  restore_all
fi
