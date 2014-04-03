#!/bin/bash

expect -c "
  set timeout 5

  spawn ssh nagayoshi@113.35.71.114
  expect \"nagayoshi@113.35.71.114's password: \" {
    send \"skt4st7548\n\"
  }

  interact
"


