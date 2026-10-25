"""Crunchyroll API requests through an invisible Chromium helper."""

import atexit
import base64
import json
import os
from pathlib import Path
import select
import subprocess
import tempfile
import threading
import urllib.parse
from uuid import uuid4


WEB_SCRIPT = """async (request) => {
  const auth = await fetch('/auth/v1/token', {
    method: 'POST',
    headers: {Authorization: request.client, 'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams({
      grant_type: request.authenticated ? 'etp_rt_cookie' : 'client_id',
      ...(request.authenticated ? {device_id: request.deviceId, device_type: 'Chrome on Mac'} : {})
    }),
    credentials: 'include', cache: 'no-store'
  });
  let authData = {};
  try { authData = await auth.json(); } catch {}
  if (!auth.ok || !authData.access_token || !request.path) {
    return {authStatus: auth.status, authChallenge: auth.headers.get('cf-mitigated'),
      authData: {access_token: authData.access_token || '', profile_id: authData.profile_id || '',
        refresh_token: authData.refresh_token || '', expires_in: authData.expires_in || 0,
        error: authData.error || ''}};
  }
  const body = request.body == null ? undefined : request.encoding === 'base64'
    ? Uint8Array.from(atob(request.body), char => char.charCodeAt(0)) : request.body;
  const headers = {...request.headers, Authorization: 'Bearer ' + authData.access_token};
  const response = await fetch(request.path, {
    method: request.method, headers, body, credentials: 'include', cache: 'no-store'
  });
  const bytes = new Uint8Array(await response.arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 32768)
    binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return {authStatus: auth.status, authChallenge: auth.headers.get('cf-mitigated'),
    authData: {access_token: authData.access_token || '', profile_id: authData.profile_id || '', refresh_token: authData.refresh_token || '',
      expires_in: authData.expires_in || 0},
    response: {status: response.status, headers: Object.fromEntries(response.headers), body: btoa(binary)}};
}"""


class BrowserResponse:
    def __init__(self, result):
        self.status_code = result["status"]
        self.headers = result["headers"]
        self.content = base64.b64decode(result["body"])

    def json(self):
        return json.loads(self.content)


class BrowserBridge:
    def __init__(self, origin, web_client, anon_client):
        self.origin = origin
        self.web_client = web_client
        self.anon_client = anon_client
        self.lock = threading.Lock()
        self.process = None
        self.profile = None
        atexit.register(self.close)

    def close(self):
        process, self.process = self.process, None
        if process:
            try:
                process.stdin.close()
                process.wait(timeout=2)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=2)
        if self.profile:
            self.profile.cleanup()
            self.profile = None

    def start(self):
        if self.process and self.process.poll() is None:
            return
        self.close()
        root = Path(__file__).resolve().parent
        binary = Path(os.environ.get("CRUNCHY_LOCAL_ELECTRON", "/app/node_modules/electron/dist/electron"))
        if not binary.is_file():
            raise RuntimeError("Chromium runtime is missing. Rebuild the Docker app image.")
        self.profile = tempfile.TemporaryDirectory(prefix="crunchy-local-hidden-",
                                                   dir=os.environ.get("CRUNCHY_LOCAL_TEMP_DIR") or None)
        environment = os.environ.copy()
        environment["CRUNCHY_LOCAL_USER_DATA"] = self.profile.name
        arguments = [str(binary)]
        if os.environ.get("CRUNCHY_LOCAL_ELECTRON_NO_SANDBOX") == "1":
            arguments.append("--no-sandbox")
        arguments.append(str(root / "hidden_browser.js"))
        self.process = subprocess.Popen(
            arguments,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, env=environment,
        )

    def remote_login(self, owner, action, input=None):
        with self.lock:
            self.start()
            job_id = uuid4().hex
            payload = {"id": job_id, "owner": owner, "action": action, "input": input}
            try:
                self.process.stdin.write(json.dumps(payload) + "\n")
                self.process.stdin.flush()
                if not select.select([self.process.stdout], [], [], 15)[0]:
                    self.close()
                    raise RuntimeError("Окно входа не ответило. Начните вход заново.")
                message = json.loads(self.process.stdout.readline())
                if message.get("id") != job_id:
                    self.close()
                    raise RuntimeError("Окно входа потеряло соединение. Начните заново.")
                if message.get("error"):
                    raise RuntimeError(message["error"])
                return message.get("result") or {}
            except (BrokenPipeError, OSError, ValueError):
                self.close()
                raise RuntimeError("Окно входа потеряло соединение. Начните заново.") from None

    def request(self, method="GET", path=None, headers=None, data=None, cookie="", device_id=""):
        clean_headers = {key: value for key, value in (headers or {}).items()
                         if key.lower() not in ("origin", "referer", "cookie", "host", "content-length", "authorization")}
        if isinstance(data, dict):
            body, encoding = urllib.parse.urlencode(data), "text"
            clean_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif isinstance(data, bytes):
            body, encoding = base64.b64encode(data).decode("ascii"), "base64"
        else:
            body, encoding = data, "text"
        options = {"client": self.web_client if cookie else self.anon_client,
                   "authenticated": bool(cookie), "deviceId": device_id,
                   "method": method, "path": path, "headers": clean_headers,
                   "body": body, "encoding": encoding}
        with self.lock:
            for attempt in range(2):
                try:
                    self.start()
                    job_id = uuid4().hex
                    self.process.stdin.write(json.dumps({"id": job_id, "cookie": cookie,
                                                         "options": options, "script": WEB_SCRIPT}) + "\n")
                    self.process.stdin.flush()
                    if not select.select([self.process.stdout], [], [], 45)[0]:
                        raise TimeoutError("Истекло время ожидания скрытого Chromium.")
                    line = self.process.stdout.readline()
                    if not line:
                        raise RuntimeError("Скрытый Chromium завершился без ответа.")
                    message = json.loads(line)
                    if message.get("id") != job_id:
                        raise RuntimeError("Скрытый Chromium вернул ответ на другой запрос.")
                    if message.get("error"):
                        raise RuntimeError(message["error"])
                    result = message["result"]
                    break
                except (BrokenPipeError, OSError, TimeoutError, ValueError) as error:
                    self.close()
                    if attempt:
                        raise RuntimeError("Скрытый Chromium не выполнил запрос: " + str(error)[:160]) from None
        if result["authStatus"] >= 400 or not result["authData"].get("profile_id") and cookie:
            if result.get("authChallenge") == "challenge":
                raise RuntimeError("Crunchyroll запросил проверку в отдельном Chrome. Попробуйте другую сеть.")
            raise RuntimeError("Crunchyroll не принял сохранённый вход. Подключите аккаунт заново.")
        return result["authData"], BrowserResponse(result["response"]) if result.get("response") else None
