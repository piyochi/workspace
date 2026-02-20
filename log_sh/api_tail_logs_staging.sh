#!/bin/bash

# ログをまとめて監視する (staging)
# ./api_tail_logs_staging.sh

# Ctrl+C (SIGINT) / kill (SIGTERM) 時に全プロセスをまとめて止めるトラップ
cleanup() {
  echo "Stopping all tails..."
  echo $(jobs -p)
  # ジョブ一覧の PID に SIGTERM を送る
  kill $(jobs -p) 2>/dev/null
  exit
}
trap cleanup SIGINT SIGTERM

# 監視対象ディレクトリ
LOG_DIR="ticket_v2_api/shared/log/"

SERVERS=()
SERVERS+=("ticketv2.api-front01.staging")
SERVERS+=("ticketv2.api-back01.staging")
SERVERS+=("ticketv2.bat.staging")
SERVERS+=("ticketv2.dj01.staging")

for server in "${SERVERS[@]}"; do
  ssh "$server" \
    "find ${LOG_DIR} -maxdepth 1 -type f ! -name '*.gz' -print0 | xargs -0 tail -F" \
    | sed "s/^/[${server}] /" &
done

# 全ジョブ終了まで待機
wait
