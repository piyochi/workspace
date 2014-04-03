#!/bin/bash

PW='skt4st7548'

expect -c "
  set timeout 5

  spawn scp 15-nagayoshi:${1} ${2}
  expect \"nagayoshi@113.35.71.114's password: \" {
    send \"${PW}\n\"
  }
  expect \"nagayoshi@113.35.71.123's password: \" {
    send \"${PW}\n\"
  }
  expect \"nagayoshi@192.168.11.15's password: \" {
    send \"${PW}\n\"
  }

  interact
"


