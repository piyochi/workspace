#!/bin/bash

# ticketv2 APPのログをまとめてダウンロードする
# ./app_download_logs.sh [パターン] [日付] [gzip]
# ./app_download_logs.sh
# ./app_download_logs.sh sidekiq
# ./app_download_logs.sh sidekiq 20250109
# ./app_download_logs.sh sidekiq 20250109 true

# パターン (デフォルト: *)
PATTERN="${1:-*}"

# 日付 (デフォルト: today)
DATE="${2:-today}"

# 日付部分の組み立て
if [ "$DATE" = "today" ]; then
  FILE_PATTERN="$PATTERN"
else
  FILE_PATTERN="$PATTERN-$DATE"
fi

if [ "$3" = "true" ]; then
  GZ=true
else
  GZ=false
fi

LOG_DIR="ticket_v2/shared/logs/"
if [ $GZ = true ]; then
  LOG_DIR+="old/"
  FILE_PATTERN="$FILE_PATTERN.gz"
fi

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
  DOWNLOAD_DIR="./old_logs/$server/"
  mkdir -p "$DOWNLOAD_DIR"

  echo "download $server."

  scp "$server:$LOG_DIR$FILE_PATTERN" "$DOWNLOAD_DIR"

  # 未圧縮なら圧縮する
  if [ $GZ = false ]; then
    gzip "$DOWNLOAD_DIR"*
  fi
done
