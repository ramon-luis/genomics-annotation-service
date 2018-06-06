#!/usr/bin/env python

from gas import app

if __name__ == '__main__':
  app.run(host=app.config['GAS_APP_HOST'],
    port=app.config['GAS_HOST_PORT'],
    ssl_context=(app.config['SSL_CERT_PATH'], app.config['SSL_KEY_PATH']))

### EOF
