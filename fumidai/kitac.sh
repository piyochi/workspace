#!/bin/bash

PW='skt4st7548'
SPPW='kmqgo4QMdw8x'
FPPW='EiWvmJnp6'
SPDEVPW='r4IrwQyv3cve'

expect -c "
  set timeout 5

  spawn ssh kitac.${1}
  expect \"Are you sure you want to continue connecting (yes/no)?\" {
    send \"yes\n\"
  }
  expect \"nagayoshi@113.35.71.114's password: \" {
    send \"${PW}\n\"
  }
  expect \"nagayoshi@113.35.71.123's password: \" {
    send \"${PW}\n\"
  }
  expect \"nagayoshi@192.168.11.93's password: \" {
    send \"${PW}\n\"
  }
  expect \"coric1@64.56.178.135's password: \" {
    send \"${SPPW}\n\"
  }
  expect \"coric1@10.2.85.11's password: \" {
    send \"${SPPW}\n\"
  }
  expect \"coric1@10.2.85.51's password: \" {
    send \"${SPPW}\n\"
  }
  expect \"t-media1@64.56.178.135's password: \" {
    send \"${FPPW}\n\"
  }
  expect \"t-media1@10.2.85.11's password: \" {
    send \"${FPPW}\n\"
  }
  expect \"t-media1@10.2.85.51's password: \" {
    send \"${FPPW}\n\"
  }
  expect \"dev-coric1@64.56.178.140's password: \" {
    send \"${SPDEVPW}\n\"
  }
  expect \"t-media1@64.56.178.141's password: \" {
    send \"${FPPW}\n\"
  }
  expect \"coric1@64.56.178.138's password: \" {
    send \"${SPPW}\n\"
  }
  expect \"dev-coric1@64.56.178.138's password: \" {
    send \"${SPDEVPW}\n\"
  }

  interact
"


