#!/bin/bash

# 稼働中のfirst/delayed_jobの数
CURRENT_FIRST_COUNT=1
# 稼働中のsecond/delayed_jobの数
CURRENT_SECOND_COUNT=10

SERVERS+=("pay.bat7")
SERVERS+=("pay.bat8")
SERVERS+=("pay.bat9")
SERVERS+=("pay.bat10")
SERVERS+=("pay.bat11")
SERVERS+=("pay.bat12")
SERVERS+=("pay.bat13")
SERVERS+=("free.bat5")
SERVERS+=("free.bat6")
SERVERS+=("free.bat7")
SERVERS+=("free.bat8")
SERVERS+=("free.bat9")
SERVERS+=("api.bat6")
SERVERS+=("api.bat7")
SERVERS+=("api.bat8")
SERVERS+=("api.bat9")
SERVERS+=("api.bat10")
SERVERS+=("api.bat11")
SERVERS+=("api.bat12")
SERVERS+=("icon.bat2")
#SERVERS+=("nnc.bat6")
#SERVERS+=("nnc.bat7")
SERVERS+=("nnc.bat8")

for server in ${SERVERS[@]}; do
  if ssh $server exit > /dev/null 2>&1; then
    # 接続に成功

    first_count=$(ssh $server "ps aux | grep 'first/delayed_job' | grep -v grep | grep -v 'ps aux' | wc -l")
    second_count=$(ssh $server "ps aux | grep 'second/delayed_job' | grep -v grep | grep -v 'ps aux' | wc -l")

    if [ $CURRENT_FIRST_COUNT -eq $first_count ]; then
      echo -e "\033[34mOK!\033[0m check $server. first -----> count: ${first_count}"
    else
      echo -e "\033[31mNG!\033[0m check $server. first -----> count: ${first_count}"
    fi

    if [ $CURRENT_SECOND_COUNT -eq $second_count ]; then
      echo -e "\033[34mOK!\033[0m check $server. second -----> count: ${second_count}"
    else
      echo -e "\033[31mNG!\033[0m check $server. second -----> count: ${second_count}"
    fi
  else
    # 接続に失敗
    echo "SSH connection failed. ${server}"
  fi
done
