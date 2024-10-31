#!/bin/bash

# 検索対象のサーバー
SEARCH_SERVER="master"

# 対象ディレクトリ
# TARGET_DIR="/mnt/s3/log/"
TARGET_DIR="/mnt/efs_first/log/"

# second or first
PROJECT=("second" "first")

if ! `echo ${PROJECT[@]} | grep -q "$1"` ; then
  echo "$1 not in (${PROJECT[@]})"
  exit
fi
TARGET_PROJECT=$1

# 検索するファイル名 production.log.20230615.gz
if [ "$2" = "" ]; then
  echo "second argument is required."
  exit
fi
TARGET_FILE="$2"

# 第3引数以降を取得
ARGS="${@:3}"

# hostnameリストパス
HOSTNAME_LIST="host_list.txt"

# 検索対象のサーバー
SERVERS=()
# SERVERS+=("pay.web21")
# SERVERS+=("pay.web22")
# SERVERS+=("pay.web23")
# SERVERS+=("pay.web24")
# SERVERS+=("pay.web25")
# SERVERS+=("pay.web26")
# SERVERS+=("pay.web27")
# SERVERS+=("pay.web28")
# SERVERS+=("pay.web29")
## SERVERS+=("pay.web30")
## SERVERS+=("pay.web31")
## SERVERS+=("pay.web32")
# SERVERS+=("pay.bat7")
# SERVERS+=("pay.bat8")
# SERVERS+=("pay.bat9")
# SERVERS+=("pay.bat10")
# SERVERS+=("pay.bat11")
# SERVERS+=("pay.bat12")
# SERVERS+=("pay.bat13")
# SERVERS+=("furiwake.web2")
# SERVERS+=("furiwake.web3")
# SERVERS+=("free.bat5")
# SERVERS+=("free.bat6")
# SERVERS+=("free.bat7")
# SERVERS+=("free.bat8")
# SERVERS+=("free.bat9")
# SERVERS+=("cron2")
# SERVERS+=("free.web7")
# SERVERS+=("free.web8")
# SERVERS+=("free.web9")
# SERVERS+=("icon.web1")
# SERVERS+=("icon.web2")
# SERVERS+=("icon.bat2")
SERVERS+=("api.web3")
SERVERS+=("api.web4")
SERVERS+=("api.web5")
SERVERS+=("api.web6")
# SERVERS+=("api.bat6")
# SERVERS+=("api.bat7")
# SERVERS+=("api.bat8")
# SERVERS+=("api.bat9")
# SERVERS+=("api.bat10")
# SERVERS+=("api.bat11")
# SERVERS+=("nnc.web4")
# SERVERS+=("nnc.bat8")

# 連想配列宣言
declare -A HOSTNAME_HASH

# ファイルの内容を読み込み、連想配列に格納
while IFS=: read -r server hostname; do
  server=$(echo "$server" | tr -d '[:space:]')
  hostname=$(echo "$hostname" | tr -d '[:space:]' | sed 's/-/_/g')
  
  HOSTNAME_HASH["$server"]="$hostname"
  # SERVERS+=("$server")
done < "$HOSTNAME_LIST"

COMMAND=("gzip -dc ")
for server in ${SERVERS[@]}; do
  COMMAND+=("${TARGET_DIR}${TARGET_PROJECT}/${HOSTNAME_HASH[$server]}/${TARGET_FILE}")
done
COMMAND+=(" ${ARGS}")

echo "${COMMAND[@]}"
# ssh $SEARCH_SERVER "${COMMAND[@]}"

