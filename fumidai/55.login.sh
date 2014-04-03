#!/bin/bash

PW='skt4st7548'

expect -c "
  set timeout 5

  spawn ssh 55-nagayoshi
  expect \"nagayoshi@113.35.71.114's password: \" {
    send \"${PW}\n\"
  }
  expect \"nagayoshi@113.35.71.123's password: \" {
    send \"${PW}\n\"
  }
  expect \"Enter passphrase for key '/home/nagayoshi/.ssh/nagayoshi_id_rsa': \" {
    send \"kaizoku0\n\"
  }

  interact
"


