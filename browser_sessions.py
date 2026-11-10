"""Encrypted client-side session management. Authentication tokens are not persisted to disk."""

import json
import os
from http.cookies import SimpleCookie
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


COOKIE_NAMES = {"cr": "cl_cr", "one": "cl_shiki_one", "rip": "cl_shiki_rip", "mal": "cl_mal"}


class BrowserSessions:
    def __init__(self, root):
        configured = os.environ.get("CRUNCHY_LOCAL_SESSION_KEY", "").strip()
        if configured:
            key = configured.encode("ascii")
        else:
            path = Path(root) / ".local" / "session.key"
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "wb") as output:
                    output.write(Fernet.generate_key())
            except FileExistsError:
                pass
            key = path.read_bytes().strip()
        self.cipher = Fernet(key)

    def read(self, header, name):
        jar = SimpleCookie()
        try:
            jar.load(header or "")
            raw = jar[COOKIE_NAMES[name]].value
            value = json.loads(self.cipher.decrypt(raw.encode("ascii"), ttl=60 * 60 * 24 * 90))
            return value if isinstance(value, dict) else {}
        except (KeyError, InvalidToken, ValueError, TypeError, UnicodeError):
            return {}

    def header(self, name, value, secure=True):
        cookie = SimpleCookie()
        cookie[COOKIE_NAMES[name]] = self.cipher.encrypt(json.dumps(value, separators=(",", ":")).encode()).decode() if value else ""
        morsel = cookie[COOKIE_NAMES[name]]
        morsel["path"] = "/"
        morsel["httponly"] = True
        morsel["samesite"] = "Lax"
        morsel["secure"] = secure
        morsel["max-age"] = 60 * 60 * 24 * 90 if value else 0
        return morsel.OutputString()
