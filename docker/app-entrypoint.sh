#!/bin/sh
set -eu
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix
mkdir -p /run/crunchy-local
if [ -f /run/secrets/oauth_apps.json ]; then
  install -m 600 -o app -g app /run/secrets/oauth_apps.json /run/crunchy-local/oauth_apps.json
fi
chown app:app /run/crunchy-local
if [ -n "${CRUNCHY_LOCAL_CATALOG_DIR:-}" ]; then
  mkdir -p "$CRUNCHY_LOCAL_CATALOG_DIR"
  chown app:app "$CRUNCHY_LOCAL_CATALOG_DIR"
fi
exec gosu app sh -c 'Xvfb :99 -screen 0 1280x800x24 -nolisten tcp & exec python server.py'
