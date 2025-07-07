#!/bin/bash

# ログをまとめて監視する
# ./tail_logs.sh

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
LOG_DIR="ticket_v2/shared/logs/"

SERVERS=()
SERVERS+=("ticketv2.app01.production")
SERVERS+=("ticketv2.app02.production")
SERVERS+=("ticketv2.group01.production")
SERVERS+=("ticketv2.group02.production")
SERVERS+=("ticketv2.event01.production")
SERVERS+=("ticketv2.event02.production")
SERVERS+=("ticketv2.user_group01.production")
SERVERS+=("ticketv2.user_group02.production")
SERVERS+=("ticketv2.panel01.production")
SERVERS+=("ticketv2.panel02.production")

for server in "${SERVERS[@]}"; do
  ssh "$server" \
    "find ${LOG_DIR} -maxdepth 1 -type f ! -name '*.gz' -print0 | xargs -0 tail -F" \
    | sed "s/^/[${server}] /" &
done

# 全ジョブ終了まで待機
wait
