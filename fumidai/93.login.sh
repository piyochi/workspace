#!/bin/bash

PW='skt4st7548'

expect -c "
  set timeout 5

  spawn ssh 93-nagayoshi
  expect \"nagayoshi@113.35.71.114's password: \" {
    send \"${PW}\n\"
  }
  expect \"nagayoshi@113.35.71.123's password: \" {
    send \"${PW}\n\"
  }
  expect \"nagayoshi@192.168.11.93's password: \" {
    send \"${PW}\n\"
  }

  interact
"


