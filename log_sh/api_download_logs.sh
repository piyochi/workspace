#!/bin/bash

# ticketv2 APIのログをまとめてダウンロードする
# ./api_download_logs.sh [パターン] [日付] [gzip]
# ./api_download_logs.sh
# ./api_download_logs.sh all
# ./api_download_logs.sh all 20250109
# ./api_download_logs.sh sidekiq
# ./api_download_logs.sh sidekiq 20250109
# ./api_download_logs.sh sidekiq 20250109 true

# パターン (デフォルト: all = *)
PATTERN="${1:-all}"
if [ "$PATTERN" = "all" ]; then
  PATTERN="*"
fi

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

LOG_DIR="ticket_v2_api/shared/log/"
if [ $GZ = true ]; then
  LOG_DIR+="old/"
  FILE_PATTERN="$FILE_PATTERN.gz"
fi

SERVERS=()
SERVERS+=("ticketv2.api.back01.production")
SERVERS+=("ticketv2.api.back02.production")
# SERVERS+=("ticketv2.api.back03.production")
# SERVERS+=("ticketv2.api.back04.production")
SERVERS+=("ticketv2.api.front01.production")
SERVERS+=("ticketv2.api.front02.production")
SERVERS+=("ticketv2.api.bat.production")
SERVERS+=("ticketv2.api.dj01.production")
SERVERS+=("ticketv2.api.dj02.production")

for server in "${SERVERS[@]}"; do
  DOWNLOAD_DIR="./old_logs/$server/"
  mkdir -p "$DOWNLOAD_DIR"

  echo "download $server."

  rsync -avz "$server:$LOG_DIR$FILE_PATTERN" "$DOWNLOAD_DIR"

  # 未圧縮なら圧縮する
  if [ $GZ = false ]; then
    gzip "$DOWNLOAD_DIR"*
  fi
done
