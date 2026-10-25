FROM node:22-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DISPLAY=:99 PATH=/opt/venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip xvfb libgtk-3-0 libnss3 libasound2 libatk-bridge2.0-0 \
    libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libxshmfence1 \
    libdrm2 libxfixes3 libxkbcommon0 libxss1 libnotify4 ca-certificates gosu tini \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN python3 -m venv /opt/venv \
    && pip install --no-cache-dir -r requirements.txt \
    && npm install --no-save --omit=dev electron@44.4.5 \
    && node node_modules/electron/install.js \
    && test -x node_modules/electron/dist/electron \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /app/.local /tmp/.X11-unix \
    && chmod 1777 /tmp/.X11-unix \
    && chown -R app:app /app
COPY --chown=app:app server.py hls.py catalog_updater.py anime_metadata.py mal.py shiki.py browser_bridge.py browser_sessions.py hidden_browser.js catalog.json ./
COPY --chown=app:app public ./public
COPY --chown=app:app licenses ./licenses
COPY --chown=app:app LICENSE ./LICENSE
COPY tools/collect_runtime_licenses.py /tmp/collect_runtime_licenses.py
RUN /opt/venv/bin/python /tmp/collect_runtime_licenses.py /app/licenses/runtime && rm /tmp/collect_runtime_licenses.py
COPY docker/app-entrypoint.sh /usr/local/bin/app-entrypoint
RUN chmod +x /usr/local/bin/app-entrypoint
ENV CRUNCHY_LOCAL_ELECTRON=/app/node_modules/electron/dist/electron \
    CRUNCHY_LOCAL_ELECTRON_NO_SANDBOX=1 \
    CRUNCHY_LOCAL_BIND=0.0.0.0 \
    CRUNCHY_LOCAL_CATALOG_DIR=/var/lib/crunchy-local/catalog \
    CRUNCHY_LOCAL_TEMP_DIR=/dev/shm \
    CRUNCHY_LOCAL_OAUTH_APPS_PATH=/run/crunchy-local/oauth_apps.json
EXPOSE 8765
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/local/bin/app-entrypoint"]
