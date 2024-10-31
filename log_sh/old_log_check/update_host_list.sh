#!/bin/bash

# サーバーリストパス
SERVER_LIST="server_list.txt"

# hostnameリストパス
HOSTNAME_LIST="host_list.txt"

# 空にする
> "$HOSTNAME_LIST"

# サーバーリストを配列に読み込む
IFS=$'\r\n' GLOBIGNORE='*' command eval 'SERVERS=($(cat $SERVER_LIST))'

# ホスト名取得
for server in ${SERVERS[@]}; do
  hostname=$(ssh $server 'hostname')
  if [ $? -eq 0 ]; then
    echo "$server:$hostname"
    echo "$server:$hostname" >> "$HOSTNAME_LIST"
  else
    echo "\033[31mNG!\033[0m Failed to connect to $server"
  fi
done

