#!/bin/bash
gunicorn -w 4 -b 0.0.0.0:5000 main:app \
  --keyfile=/etc/ssl/private/private.key \
  --certfile=/etc/ssl/private/certificate.crt
