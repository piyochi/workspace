#!/bin/bash

# ログをまとめてダウンロードする
# ./log_download.sh 対象プロジェクト 対象の日付 gzipされているかどうか
# ./log_download.sh second today
# ./log_download.sh second 20210310
# ./log_download.sh second 20210310 true

PROJECT=("second" "first")

if ! `echo ${PROJECT[@]} | grep -q "$1"` ; then
  echo "$1 not in (${PROJECT[@]})"
  exit
fi

TARGET_PROJECT=$1

if [ "$2" = "" ]; then
  echo "second argument is required."
  exit
elif [ "$2" = "today" ]; then
  TARGET_FILE="production.log"
else
  TARGET_FILE="production.log.$2"
fi

if [ "$3" = "true" ]; then
  GZ=true
else
  GZ=false
fi

LOG_DIR="$TARGET_PROJECT/shared/log/"
if [ $GZ = true ]; then
  LOG_DIR+="old/"
  LOG_FILE="$TARGET_FILE.gz"
else
  LOG_FILE="$TARGET_FILE"
fi

SERVERS=()
## SERVERS+=("pay.web1")
## SERVERS+=("pay.web2")
## SERVERS+=("pay.web7")
## SERVERS+=("pay.web8")
## SERVERS+=("pay.web9")
## SERVERS+=("pay.web10")
## SERVERS+=("pay.web11")
## SERVERS+=("pay.web12")
## SERVERS+=("pay.web18")
## SERVERS+=("pay.web19")
## SERVERS+=("pay.web13")
## SERVERS+=("pay.web20")
# SERVERS+=("pay.web21")
# SERVERS+=("pay.web22")
# SERVERS+=("pay.web23")
# SERVERS+=("pay.web24")
# SERVERS+=("pay.web25")
# SERVERS+=("pay.web26")
# SERVERS+=("pay.web27")
# SERVERS+=("pay.web28")
# SERVERS+=("pay.web29")
# SERVERS+=("pay.web30")
# SERVERS+=("pay.web31")
# SERVERS+=("pay.web32")
## SERVERS+=("pay.web14")
## SERVERS+=("pay.web15")
# SERVERS+=("pay.bat7")
# SERVERS+=("pay.bat8")
# SERVERS+=("pay.bat9")
# SERVERS+=("pay.bat10")
# SERVERS+=("pay.bat11")
# SERVERS+=("pay.bat12")
# SERVERS+=("pay.bat13")
# SERVERS+=("pay.bat14")
# SERVERS+=("pay.bat15")
# SERVERS+=("pay.bat16")
# SERVERS+=("furiwake.web2")
# SERVERS+=("furiwake.web3")
# SERVERS+=("free.bat5")
# SERVERS+=("free.bat6")
# SERVERS+=("free.bat7")
# SERVERS+=("free.bat8")
# SERVERS+=("free.bat9")
## SERVERS+=("cron1")
# SERVERS+=("cron2")
# SERVERS+=("free.web7")
# SERVERS+=("free.web8")
# SERVERS+=("free.web9")
# SERVERS+=("icon.web1")
# SERVERS+=("icon.web2")
# SERVERS+=("icon.bat1")
## SERVERS+=("api.web1")
## SERVERS+=("api.web2")
# SERVERS+=("api.web3")
# SERVERS+=("api.web4")
# SERVERS+=("api.web5")
# SERVERS+=("api.web6")
# SERVERS+=("api.bat6")
# SERVERS+=("api.bat7")
# SERVERS+=("api.bat8")
# SERVERS+=("api.bat9")
# SERVERS+=("api.bat10")
# SERVERS+=("api.bat11")
# SERVERS+=("nnc.web3")
SERVERS+=("nnc.web4")
# SERVERS+=("nnc.bat6")
# SERVERS+=("nnc.bat7")
SERVERS+=("nnc.bat8")

for server in ${SERVERS[@]}; do
  DOWNLOAD_DIR="/tmp/nagayoshi/log/$server/$TARGET_PROJECT/"
  mkdir -p "$DOWNLOAD_DIR"

  echo "download $server."

  scp $server:$LOG_DIR$LOG_FILE $DOWNLOAD_DIR

  # 未圧縮なら圧縮する
  if [ $GZ = false ]; then
    gzip $DOWNLOAD_DIR$LOG_FILE
  fi
done

# 旧ログは /mnt/s3/log/second or first から直接gzip -dc するのが早い
