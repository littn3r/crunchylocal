#!/usr/bin/env python3
"""Crunchyroll catalog and browser-DRM playback bridge for this Mac and its LAN."""

import base64
import html
import hmac
import hashlib
import ipaddress
import json
import os
import re
import socket
import signal
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from curl_cffi import requests
from browser_bridge import BrowserBridge
from browser_sessions import BrowserSessions
from shiki import ShikimoriBridge
from mal import MALBridge, sync_rates
from catalog_updater import CatalogStore
from anime_metadata import anime_information, resolve_anime_id
from hls import rewrite_manifest, select_quality


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
CATALOG_STORE = CatalogStore(ROOT, cache_dir=os.environ.get("CRUNCHY_LOCAL_CATALOG_DIR"),
                             interval=int(os.environ.get("CRUNCHY_LOCAL_CATALOG_INTERVAL", "86400")))
FEATURED_CACHE = {"until": 0, "items": [], "source": "catalog"}
CR_RATING_CACHE = {}
AGE_RATINGS = ["ALL", "PG", "12", "14", "16", "18", "unrated"]
SESSIONS = BrowserSessions(ROOT)
OAUTH_STATES = {}
MAL_OAUTH_STATES = {}
STREAMS = {}
STREAMS_LOCK = threading.RLock()
SHIKI_CACHES = {}
AUTH_LATEST = {}
LOGIN_ATTEMPTS = {}
LOGIN_ATTEMPTS_LOCK = threading.Lock()
AUTH_REFRESH_LOCK = threading.RLock()
API = "https://www.crunchyroll.com"
WEB_CLIENT = "Basic bm9haWhkZXZtXzZpeWcwYThsMHE6"
ANON_CLIENT = "Basic Y3Jfd2ViOg=="
BROWSER = BrowserBridge(API, WEB_CLIENT, ANON_CLIENT)
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{4,40}$")


class RequestState(threading.local):
    def __init__(self):
        self.lock = threading.RLock()
        self.cookie = self.access_token = self.anon_token = ""
        self.access_until = self.anon_until = 0
        self.stream_id = self.stream_token = ""
        self.subtitles = {}
        self.device_id = str(uuid4())
        self.browser_login_status = "idle"
        self.browser_login_error = ""
        self.browser_login_cancel = threading.Event()
        self.browser_required = False


State = RequestState()


def cr_request(method, path, headers=None, data=None, cookies=None):
    try:
        response = requests.request(method, API + path, headers=headers or {}, data=data,
                                    cookies=cookies or {}, impersonate="chrome", timeout=30)
    except Exception:
        raise RuntimeError("Не удалось связаться с Crunchyroll.") from None
    if response.status_code >= 400:
        if response.headers.get("cf-mitigated") == "challenge":
            raise RuntimeError("Crunchyroll отклонил прямой запрос проверкой Cloudflare.")
        try:
            code = response.json().get("error", "")
        except Exception:
            code = ""
        if code == "invalid_grant":
            raise RuntimeError("Сессия Crunchyroll истекла. Войдите повторно.")
        if response.status_code == 420 and path.startswith("/playback/"):
            raise RuntimeError("Достигнут лимит одновременных просмотров Crunchyroll. Закройте другие воспроизведения и попробуйте снова через несколько минут.")
        raise RuntimeError("Crunchyroll: HTTP %s%s" % (response.status_code, " (" + str(code) + ")" if code else ""))
    return response


def call_cr(path, method="GET", body=None, headers=None, authenticated=False, raw=False):
    if authenticated and State.cookie and State.browser_required:
        return browser_call_cr(path, method, body, headers, raw)
    try:
        token = get_token(authenticated)
        req_headers = {"Authorization": "Bearer " + token, "Accept": "application/json", "Referer": API + "/"}
        if headers:
            req_headers.update(headers)
        response = cr_request(method, path, headers=req_headers, data=body,
                              cookies={"etp_rt": State.cookie} if authenticated else None)
        return response.content if raw else (response.json() if response.content else {})
    except RuntimeError as error:
        if authenticated and State.cookie and "проверкой Cloudflare" in str(error):
            State.browser_required = True
            return browser_call_cr(path, method, body, headers, raw)
        raise


def browser_call_cr(path, method, body, headers, raw):
    with AUTH_REFRESH_LOCK:
        with STREAMS_LOCK:
            latest = AUTH_LATEST.get(State.sid) or {}
            if latest.get("cookie"):
                State.cookie = latest["cookie"]
        auth, response = BROWSER.request(method, path, headers, body,
                                         cookie=State.cookie, device_id=State.device_id)
        State.access_token = auth.get("access_token") or ""
        State.access_until = time.time() + int(auth.get("expires_in") or 300)
        if auth.get("refresh_token"):
            State.cookie = auth["refresh_token"]
        with STREAMS_LOCK:
            AUTH_LATEST[State.sid] = {"cookie": State.cookie, "until": time.time() + 3600}
        if response.status_code >= 400:
            if response.headers.get("cf-mitigated") == "challenge":
                raise RuntimeError("Crunchyroll запросил дополнительную проверку. Попробуйте другую сеть.")
            if response.status_code == 420 and path.startswith("/playback/"):
                raise RuntimeError("Достигнут лимит одновременных просмотров Crunchyroll. Закройте другие воспроизведения и попробуйте снова через несколько минут.")
            raise RuntimeError("Crunchyroll: HTTP %s" % response.status_code)
        return response.content if raw else (response.json() if response.content else {})


def get_token(authenticated=False):
    with State.lock:
        if authenticated:
            if not State.cookie:
                raise RuntimeError("Подключите аккаунт Crunchyroll в настройках.")
            if State.access_token and State.access_until > time.time() + 30:
                return State.access_token
            if State.browser_required:
                with AUTH_REFRESH_LOCK:
                    with STREAMS_LOCK:
                        latest = AUTH_LATEST.get(State.sid) or {}
                        if latest.get("cookie"):
                            State.cookie = latest["cookie"]
                    auth, _ = BROWSER.request(cookie=State.cookie, device_id=State.device_id)
                    State.access_token = auth.get("access_token") or ""
                    State.access_until = time.time() + int(auth.get("expires_in") or 300)
                    if auth.get("refresh_token"):
                        State.cookie = auth["refresh_token"]
                    with STREAMS_LOCK:
                        AUTH_LATEST[State.sid] = {"cookie": State.cookie, "until": time.time() + 3600}
                return State.access_token
            data = {
                "grant_type": "etp_rt_cookie",
                "device_id": State.device_id,
                "device_type": "Chrome on Mac",
            }
            headers = {"Authorization": WEB_CLIENT, "Origin": API}
            cookies = {"etp_rt": State.cookie}
        else:
            if State.anon_token and State.anon_until > time.time() + 30:
                return State.anon_token
            data = {"grant_type": "client_id"}
            headers = {
                "Authorization": ANON_CLIENT,
                "Origin": API,
            }
            cookies = None
        result = cr_request("POST", "/auth/v1/token", headers=headers, data=data, cookies=cookies).json()
        token = result.get("access_token")
        if not token:
            raise RuntimeError("Crunchyroll не выдал токен доступа.")
        if authenticated and not result.get("profile_id"):
            raise RuntimeError("Вход на Crunchyroll ещё не завершён. Выберите профиль в открытом окне.")
        until = time.time() + int(result.get("expires_in", 300))
        if authenticated:
            State.access_token, State.access_until = token, until
            if result.get("refresh_token"):
                State.cookie = result["refresh_token"]
        else:
            State.anon_token, State.anon_until = token, until
        return token


def cms(path):
    query = "?locale=en-US&preferred_audio_language=ja-JP&ratings=true"
    if State.cookie:
        try:
            return call_cr("/content/v2/cms/" + path + query, authenticated=True)
        except RuntimeError as error:
            if not any(code in str(error) for code in ("HTTP 401", "HTTP 403")):
                raise
    return call_cr("/content/v2/cms/" + path + query)


def crunchy_rating(series_id):
    cached = CR_RATING_CACHE.get(series_id)
    if cached and cached[0] > time.time():
        return cached[1]
    rating = None
    total = None
    try:
        details = call_cr("/content-reviews/v2/rating/series/%s" % series_id,
                          authenticated=bool(State.cookie))
        average = float(details.get("average"))
        if 0 <= average <= 5:
            rating = average
            total = int(details.get("total") or 0)
    except (RuntimeError, ValueError, TypeError, AttributeError, IndexError):
        pass
    result = {"rating": rating, "total": total}
    CR_RATING_CACHE[series_id] = (time.time() + (3600 if rating is not None else 300), result)
    return result


def featured_items():
    catalog = CATALOG_STORE.snapshot
    with State.lock:
        if FEATURED_CACHE["until"] > time.time() and FEATURED_CACHE.get("catalog_version") == catalog.version:
            return {"items": FEATURED_CACHE["items"], "source": FEATURED_CACHE["source"]}
    items = []
    source = "catalog"
    try:
        home = call_cr("/f/v1/home", authenticated=bool(State.cookie))
        collection = next((node for node in home.get("children", [])
                           if node.get("type") == "HeroCollection"), {})
        seen = set()
        for node in collection.get("children", []):
            props = node.get("props") or {}
            item_id = props.get("contentId")
            local = catalog.by_id.get(item_id)
            if node.get("type") != "HeroMediaCard" or not local or item_id in seen:
                continue
            seen.add(item_id)
            image = props.get("wideImage") or ""
            if not image.startswith("/") or image.startswith("//"):
                image = ""
            wide = re.sub(r"/thumbnail/\d+x\d+/", "/thumbnail/1920x1080/", local.get("wide") or "")
            items.append({"id": item_id, "title": props.get("title") or local["title"],
                          "year": local.get("year"), "episodes": local.get("episodes"),
                          "genres": local.get("genres") or [], "image": API + image if image else local.get("wide"),
                          "fallback_image": wide or local.get("poster")})
        if items:
            source = "crunchyroll"
    except (RuntimeError, ValueError, TypeError):
        pass
    if not items:
        recent = [item for item in catalog.items if item.get("year") and item["year"] >= time.localtime().tm_year - 1]
        recent.sort(key=lambda item: item.get("popularity") or 0, reverse=True)
        items = [{"id": item["id"], "title": item["title"], "year": item.get("year"),
                  "episodes": item.get("episodes"), "genres": item.get("genres") or [],
                  "image": re.sub(r"/thumbnail/\d+x\d+/", "/thumbnail/1920x1080/", item.get("wide") or "") or item.get("poster"),
                  "fallback_image": item.get("wide") or item.get("poster")}
                 for item in recent[:6]]
    with State.lock:
        FEATURED_CACHE.update({"until": time.time() + (3600 if source == "crunchyroll" else 300),
                               "items": items, "source": source, "catalog_version": catalog.version})
    return {"items": items, "source": source}


def stop_stream():
    with State.lock:
        episode, token = State.stream_id, State.stream_token
        State.stream_id = State.stream_token = ""
        State.subtitles = {}
    if episode and token:
        try:
            path = "/playback/v1/token/%s/%s" % (episode, urllib.parse.quote(token, safe=""))
            call_cr(path, method="DELETE", authenticated=True)
        except Exception:
            pass


def close_active_streams():
    """Release this application's in-memory leases before a server restart."""
    with STREAMS_LOCK:
        streams = list(STREAMS.items())
        STREAMS.clear()
    for sid, stream in streams:
        with STREAMS_LOCK:
            account = AUTH_LATEST.get(sid) or {}
        if not account.get('cookie'):
            continue
        State.sid, State.cookie = sid, account['cookie']
        State.device_id = stream.get('device_id') or str(uuid4())
        State.browser_required = True
        State.stream_id, State.stream_token = stream['id'], stream['token']
        State.access_token, State.access_until = '', 0
        stop_stream()


def safe_media_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise RuntimeError("Недопустимый адрес видеопотока.")
    for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(item[4][0]).is_global:
            raise RuntimeError("Недопустимый адрес видеопотока.")
    return url


def ass_to_vtt(source):
    columns = []
    style_columns = []
    styles = {}
    cues = []
    section = ""
    resolution = {"x": 0, "y": 0}

    def stamp(value):
        found = re.fullmatch(r"(\d+):(\d{1,2}):(\d{1,2})\.(\d{1,3})", value.strip())
        if not found:
            return None
        h, m, s, fractional = found.groups()
        return "%02d:%02d:%02d.%s" % (int(h), int(m), int(s), fractional.ljust(3, "0")[:3])

    def number(value, fallback=0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    def percent(value):
        return max(0, min(100, value))

    def position(row, caption):
        style = styles.get(row.get("style", "").lower(), {})
        alignment = int(number(style.get("alignment"), 2))
        overrides = " ".join(re.findall(r"\{([^}]*)\}", row.get("text", "")))
        override_alignment = re.search(r"\\an([1-9])\b", overrides)
        if override_alignment:
            alignment = int(override_alignment.group(1))
        if alignment not in range(1, 10):
            alignment = 2

        width = resolution["x"] or 384
        height = resolution["y"] or 288
        font_size = number(style.get("fontsize"), height / 18)
        lines = caption.split("\n")
        longest = max(len(line) for line in lines)
        text_width = max(12, min(90, longest * font_size * 0.6 / width * 100 + 8))
        text_height = max(3, len(lines) * font_size * 1.3 / height * 100)
        horizontal = (alignment - 1) % 3
        vertical = (alignment - 1) // 3  # 0: bottom, 1: middle, 2: top
        margin_l = number(row.get("marginl")) or number(style.get("marginl"), 0)
        margin_r = number(row.get("marginr")) or number(style.get("marginr"), 0)
        margin_v = number(row.get("marginv")) or number(style.get("marginv"), 0)

        absolute = re.search(r"\\pos\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)", overrides)
        if not absolute:
            absolute = re.search(r"\\move\(\s*([\d.]+)\s*,\s*([\d.]+)", overrides)
        if absolute:
            x = number(absolute.group(1)) / width * 100
            y = number(absolute.group(2)) / height * 100
            left = x - (0 if horizontal == 0 else text_width / 2 if horizontal == 1 else text_width)
            top = y - (text_height if vertical == 0 else text_height / 2 if vertical == 1 else 0)
            left = percent(left)
            top = percent(top)
            text_width = min(text_width, 100 - left)
            return "line:%.2f%%,start position:%.2f%%,line-left size:%.2f%% align:%s" % (
                top, left, text_width, ("left", "center", "right")[horizontal])

        left = percent(margin_l / width * 100)
        right = percent(margin_r / width * 100)
        region_width = max(10, 100 - left - right)
        if vertical == 0:
            # Dialogue stays above the player controls, including in fullscreen.
            bottom = min(92, 100 - margin_v / height * 100)
            line = "line:%.2f%%,end" % bottom
        elif vertical == 1:
            line = "line:%.2f%%,start" % percent(50 - text_height / 2)
        else:
            line = "line:%.2f%%,start" % percent(margin_v / height * 100)
        return "%s position:%.2f%%,line-left size:%.2f%% align:%s" % (
            line, left, region_width, ("left", "center", "right")[horizontal])

    for line in source.splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line.lower()
        elif section == "[script info]" and line.lower().startswith("playresx:"):
            resolution["x"] = number(line.split(":", 1)[1])
        elif section == "[script info]" and line.lower().startswith("playresy:"):
            resolution["y"] = number(line.split(":", 1)[1])
        elif section.startswith("[v4") and line.lower().startswith("format:"):
            style_columns = [x.strip().lower() for x in line.split(":", 1)[1].split(",")]
        elif section.startswith("[v4") and style_columns and line.lower().startswith("style:"):
            values = [x.strip() for x in line.split(":", 1)[1].lstrip().split(",", len(style_columns) - 1)]
            if len(values) == len(style_columns):
                style = dict(zip(style_columns, values))
                styles[style.get("name", "").lower()] = style
        elif section == "[events]" and line.lower().startswith("format:"):
            columns = [x.strip().lower() for x in line.split(":", 1)[1].split(",")]
        elif section == "[events]" and columns and line.lower().startswith("dialogue:"):
            values = [x.strip() for x in line.split(":", 1)[1].lstrip().split(",", len(columns) - 1)]
            if len(values) != len(columns):
                continue
            row = dict(zip(columns, values))
            start, end = stamp(row.get("start", "")), stamp(row.get("end", ""))
            if not start or not end:
                continue
            if re.search(r"\\p[1-9]", row.get("text", "")):
                continue  # Vector drawings cannot be represented as WebVTT text.
            caption = re.sub(r"\{[^}]*\}", "", row.get("text", ""))
            caption = html.escape(caption.replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")).strip()
            if caption:
                cues.append("%s --> %s %s\n%s" % (start, end, position(row, caption), caption))
    if not cues:
        raise RuntimeError("В файле субтитров нет читаемых реплик.")
    return ("WEBVTT\n\n" + "\n\n".join(cues) + "\n").encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "CrunchyLocal/1.0"

    def init_context(self):
        incoming = self.headers.get("Cookie", "")
        self.catalog = CATALOG_STORE.snapshot
        self.original_accounts = {name: SESSIONS.read(incoming, name) for name in ("one", "rip")}
        self.original_cr = SESSIONS.read(incoming, "cr")
        self.original_mal = SESSIONS.read(incoming, "mal")
        self.sid = self.original_cr.get("sid") or uuid4().hex
        State.sid = self.sid
        with STREAMS_LOCK:
            latest = AUTH_LATEST.get(self.sid) or {}
            if latest.get("until", 0) <= time.time():
                AUTH_LATEST.pop(self.sid, None)
                latest = {}
        State.cookie = latest.get("cookie") or self.original_cr.get("cookie", "")
        State.device_id = self.original_cr.get("device_id") or str(uuid4())
        State.browser_required = bool(State.cookie)
        with STREAMS_LOCK:
            caches = SHIKI_CACHES.setdefault(self.sid, {"until": time.time() + 3600})
            caches["until"] = time.time() + 3600
            if caches.get("catalog_version") != self.catalog.version:
                caches.pop("lists", None)
                caches.pop("mal_list", None)
                caches["catalog_version"] = self.catalog.version
            if len(SHIKI_CACHES) > 1024:
                for key, value in list(SHIKI_CACHES.items()):
                    if value["until"] < time.time():
                        SHIKI_CACHES.pop(key, None)
            stream = STREAMS.get(self.sid) or {}
            if stream.get("until", 0) < time.time():
                STREAMS.pop(self.sid, None)
                stream = {}
            State.stream_id = stream.get("id", "")
            State.stream_token = stream.get("token", "")
            State.subtitles = stream.get("subtitles", {})
            self.initial_stream = (State.stream_id, State.stream_token)
        self.shiki = ShikimoriBridge(ROOT, self.catalog.by_mal_id, self.catalog.items,
                                     accounts=self.original_accounts, oauth_states=OAUTH_STATES,
                                     user_caches=caches)
        self.mal = MALBridge(ROOT, self.shiki, self.original_mal, MAL_OAUTH_STATES, caches)
        self.context_ready = True

    def end_headers(self):
        if getattr(self, "context_ready", False):
            account = {"sid": self.sid, "device_id": State.device_id}
            if State.cookie:
                account["cookie"] = State.cookie
            if account != self.original_cr:
                self.send_header("Set-Cookie", SESSIONS.header("cr", account, self.cookie_secure()))
            with STREAMS_LOCK:
                if State.cookie:
                    AUTH_LATEST[self.sid] = {"cookie": State.cookie, "until": time.time() + 3600}
                else:
                    AUTH_LATEST.pop(self.sid, None)
            if self.mal.account != self.original_mal:
                self.send_header("Set-Cookie", SESSIONS.header("mal", self.mal.account, self.cookie_secure()))
            for provider in ("one", "rip"):
                current = self.shiki.accounts[provider]
                if current != self.original_accounts[provider]:
                    self.send_header("Set-Cookie", SESSIONS.header(provider, current, self.cookie_secure()))
            with STREAMS_LOCK:
                if (State.stream_id, State.stream_token) != self.initial_stream:
                    if State.stream_id and State.stream_token:
                        STREAMS[self.sid] = {"id": State.stream_id, "token": State.stream_token,
                                             "subtitles": State.subtitles, "device_id": State.device_id, "until": time.time() + 7200}
                    else:
                        STREAMS.pop(self.sid, None)
        super().end_headers()

    def cookie_secure(self):
        return self.public_origin().startswith("https://") or not self.headers.get("Host", "").startswith(("127.0.0.1:", "localhost:"))

    def public_origin(self):
        host = self.headers.get("Host", "")
        # Keep localhost playback and OAuth on localhost while an HTTPS proxy is enabled.
        if host.split(':')[0] in ('localhost', '127.0.0.1') and self.headers.get('X-Forwarded-Proto') != 'https':
            return 'http://' + host
        return os.environ.get("CRUNCHY_LOCAL_PUBLIC_ORIGIN", "").rstrip("/") or "http://" + host

    def log_message(self, fmt, *args):
        if not self.path.startswith(("/api/", "/shiki/callback", "/mal/callback")):
            super().log_message(fmt, *args)

    def json_response(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def bytes_response(self, data, content_type="application/octet-stream", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def valid_host(self):
        address = self.server.server_address[0]
        hosts = {"%s:%s" % (address, self.server.server_port)}
        if address in ("127.0.0.1", "0.0.0.0"):
            hosts.add("127.0.0.1:%s" % self.server.server_port)
            hosts.add("localhost:%s" % self.server.server_port)
        configured = urllib.parse.urlsplit(os.environ.get("CRUNCHY_LOCAL_PUBLIC_ORIGIN", ""))
        if configured.netloc:
            hosts.add(configured.netloc)
        return self.headers.get("Host", "") in hosts

    def authorized(self):
        origin = self.headers.get("Origin", "")
        return (self.valid_host() and self.headers.get("X-Local-Player") == "1"
                and origin in ("", self.public_origin(), "http://" + self.headers["Host"]))

    def authorized_stop_beacon(self):
        # sendBeacon cannot add the API header; require an explicit same-origin POST.
        origin = self.headers.get("Origin", "")
        return (urllib.parse.urlsplit(self.path).path == "/api/stop" and self.valid_host()
                and bool(origin) and origin in (self.public_origin(), "http://" + self.headers.get("Host", "")))

    def media_proxy_url(self, url, playlist=False):
        proof = {"sid": self.sid, "stream": hashlib.sha256(State.stream_token.encode()).hexdigest(),
                 "resource": hashlib.sha256(url.encode()).hexdigest()}
        ticket = SESSIONS.cipher.encrypt(json.dumps(proof).encode()).decode()
        return ("/api/hls" if playlist else "/api/media") + "?" + urllib.parse.urlencode({"url": url, "ticket": ticket})

    def native_media_authorized(self, path):
        if path not in ("/api/media", "/api/hls") or not State.stream_token or not State.cookie:
            return False
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        url = (query.get("url") or [""])[0]
        ticket = (query.get("ticket") or [""])[0]
        if len(ticket) > 2048 or len(url) > 4000: return False
        try:
            proof = json.loads(SESSIONS.cipher.decrypt(ticket.encode(), ttl=7200))
            return (proof.get("sid") == self.sid
                    and hmac.compare_digest(proof.get("stream", ""), hashlib.sha256(State.stream_token.encode()).hexdigest())
                    and hmac.compare_digest(proof.get("resource", ""), hashlib.sha256(url.encode()).hexdigest()))
        except Exception:
            return False

    def do_GET(self):
        if not self.valid_host():
            self.send_error(403)
            return
        self.init_context()
        path = urllib.parse.urlsplit(self.path).path
        if path == "/mal/callback":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                self.mal.callback((query.get("state") or [""])[0], (query.get("code") or [""])[0], (query.get("error") or [""])[0], self.sid)
            except RuntimeError as error:
                self.mal.account["error"] = str(error)
            self.send_response(303)
            self.send_header("Location", "/?shiki=mal")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path == "/shiki/callback":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                provider = self.shiki.callback((query.get("state") or [""])[0],
                                          (query.get("code") or [""])[0],
                                          (query.get("error") or [""])[0], self.sid)
            except RuntimeError:
                self.bytes_response(('<!doctype html>'
                    '<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
                    '<title>Вход в Shikimori не завершён</title><script src="/i18n.js"></script></head>'
                    '<body><h1>Вход в Shikimori не завершён</h1><a href="/">Вернуться на главную</a></body></html>'
                    ).encode("utf-8"), "text/html; charset=utf-8", 400)
                return
            self.send_response(303)
            self.send_header("Location", "/?shiki=" + provider)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path.startswith("/api/"):
            if not self.authorized() and not self.native_media_authorized(path):
                self.json_response({"error": "Недоступный запрос."}, 403)
                return
            try:
                self.api_get(path)
            except Exception as error:
                if path == "/api/media":
                    print("Media proxy error: %s" % error, flush=True)
                self.json_response({"error": str(error)}, 502)
            return
        if path == "/":
            path = "/index.html"
        file = (PUBLIC / path.lstrip("/")).resolve()
        if PUBLIC not in file.parents or not file.is_file():
            self.send_error(404)
            return
        content_type = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".wasm": "application/wasm"}.get(file.suffix, "application/octet-stream")
        self.bytes_response(file.read_bytes(), content_type)

    def api_get(self, path):
        if path == "/api/subtitle":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            language = (query.get("lang") or [""])[0]
            with State.lock:
                subtitle = State.subtitles.get(language)
            if not subtitle or not subtitle.get("url"):
                raise RuntimeError("Субтитры не найдены.")
            url = safe_media_url(subtitle["url"])
            response = requests.get(url, headers={"Authorization": "Bearer " + get_token(True),
                                                  "Referer": "https://static.crunchyroll.com/"},
                                    impersonate="chrome", timeout=30)
            if response.status_code != 200 or len(response.content) > 8 * 1024 * 1024:
                raise RuntimeError("Не удалось загрузить субтитры.")
            if subtitle.get("format", "").lower() == "vtt" or response.content.startswith(b"WEBVTT"):
                payload = response.content
            elif (query.get("raw") or [""])[0] == "1":
                self.bytes_response(response.content, "text/plain; charset=utf-8")
                return
            else:
                payload = ass_to_vtt(response.content.decode("utf-8-sig", "replace"))
            self.bytes_response(payload, "text/vtt; charset=utf-8")
        elif path == "/api/hls":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            url = (query.get("url") or [""])[0]
            if len(url) > 4000: raise RuntimeError("Invalid HLS URL.")
            safe_media_url(url)
            parsed = urllib.parse.urlsplit(url)
            if parsed.hostname == "www.crunchyroll.com" and parsed.path.startswith("/playback/"):
                payload = call_cr(parsed.path + ("?" + parsed.query if parsed.query else ""), authenticated=True, raw=True)
            else:
                for _ in range(5):
                    response = requests.get(url, impersonate="chrome", timeout=30, allow_redirects=False)
                    if response.status_code in (301, 302, 303, 307, 308):
                        url = safe_media_url(urllib.parse.urljoin(url, response.headers.get("Location", "")))
                        continue
                    if response.status_code != 200: raise RuntimeError("HLS playlist is unavailable.")
                    payload = response.content
                    break
                else: raise RuntimeError("Too many HLS redirects.")
            if len(payload) > 2 * 1024 * 1024: raise RuntimeError("HLS playlist is too large.")
            quality = int((query.get('quality') or ['0'])[0])
            if quality < 0 or quality > 4320: raise RuntimeError('Invalid video quality.')
            playlist = rewrite_manifest(select_quality(payload.decode("utf-8-sig"), quality), url, self.media_proxy_url)
            self.bytes_response(playlist.encode(), "application/vnd.apple.mpegurl")
        elif path == "/api/media":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            url = (query.get("url") or [""])[0]
            if len(url) > 4000:
                raise RuntimeError("Слишком длинный адрес видеопотока.")
            safe_media_url(url)
            for _ in range(5):
                headers = {"Referer": "https://static.crunchyroll.com/"}
                cookies = None
                # CDN URLs are already signed; native HLS sends no account credentials.
                if urllib.parse.urlsplit(url).hostname == 'www.crunchyroll.com':
                    headers['Authorization'] = 'Bearer ' + get_token(True)
                    cookies = {"etp_rt": State.cookie}
                if self.headers.get("Range"):
                    headers["Range"] = self.headers["Range"]
                response = requests.get(url, headers=headers, cookies=cookies,
                                        impersonate="chrome", timeout=30, allow_redirects=False)
                if response.status_code in (301, 302, 303, 307, 308):
                    url = safe_media_url(urllib.parse.urljoin(url, response.headers.get("Location", "")))
                    continue
                if response.status_code >= 400:
                    raise RuntimeError("Видеосервер вернул HTTP %s." % response.status_code)
                payload = response.content
                if len(payload) > 32 * 1024 * 1024:
                    raise RuntimeError("Сегмент видео слишком большой.")
                self.send_response(response.status_code)
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/octet-stream"))
                self.send_header("Content-Length", str(len(payload)))
                if response.headers.get("Content-Range"):
                    self.send_header("Content-Range", response.headers["Content-Range"])
                self.send_header("Cache-Control", "private, max-age=60")
                self.end_headers()
                self.wfile.write(payload)
                break
            else:
                raise RuntimeError("Слишком много перенаправлений видеопотока.")
        elif path == "/api/status":
            self.json_response({"connected": bool(State.cookie), "catalog_count": len(self.catalog.items), "catalog_version": self.catalog.version,
                                "shikimori": self.shiki.status()})
        elif path == "/api/catalog/status":
            self.json_response(CATALOG_STORE.status())
        elif path == "/api/filters":
            self.json_response({"genres": self.catalog.genres, "ratings": AGE_RATINGS,
                                "years": self.catalog.years})
        elif path == "/api/featured":
            self.json_response(featured_items())
        elif path == "/api/shiki/status":
            self.json_response({**self.shiki.status(), "mal": self.mal.status()})
        elif path == "/api/shiki/list":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            provider = (query.get("provider") or ["one"])[0]
            force = (query.get("refresh") or ["0"])[0] == "1"
            self.json_response(self.mal.list(force) if provider == "mal" else self.shiki.list(provider, force=force))
        elif path == "/api/shiki/season":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            self.json_response(self.shiki.match_season("rip" if (query.get("provider") or ["one"])[0] == "mal" else (query.get("provider") or ["one"])[0],
                                                  (query.get("title") or [""])[0],
                                                  int((query.get("episodes") or ["0"])[0]),
                                                  int((query.get("mal_id") or ["0"])[0])))
        elif path == "/api/shiki/rate":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            provider = (query.get("provider") or ["one"])[0]
            anime_id = int((query.get("mal_id") or ["0"])[0])
            self.json_response(self.mal.rate(anime_id) if provider == "mal" else self.shiki.rate(provider, anime_id))
        elif path == "/api/shiki/score":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            self.json_response({"score": self.shiki.shiki_score((query.get("provider") or ["one"])[0],
                                                         int((query.get("mal_id") or ["0"])[0]))})
        elif path == "/api/anime-info":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            anime_id = int((query.get("mal_id") or ["0"])[0])
            language = (query.get("lang") or ["en"])[0]
            series_id = (query.get("series") or [""])[0]
            if series_id:
                self.valid_id(series_id)
                series = self.catalog.by_id.get(series_id)
                if not series:
                    self.json_response({"error": "Series not found"}, 404)
                    return
                anime_id = resolve_anime_id(self.shiki, series)
            if not anime_id:
                self.json_response({"matched": False})
                return
            self.json_response(anime_information(self.shiki, anime_id, language))
        elif path == "/api/ratings":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            self.json_response(self.shiki.ratings("rip" if (query.get("provider") or ["one"])[0] == "mal" else (query.get("provider") or ["one"])[0],
                                            int((query.get("mal_id") or ["0"])[0])))
        elif path == "/api/browser-login/status":
            with State.lock:
                self.json_response({"status": State.browser_login_status,
                                    "error": State.browser_login_error,
                                    "connected": bool(State.cookie)})
        elif path == "/api/search":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            phrase = (query.get("q") or [""])[0].strip().casefold()[:100]
            genre = (query.get("genre") or [""])[0]
            age = (query.get("age") or [""])[0]
            order = (query.get("sort") or ["popular"])[0]
            def number(name, default, low=0, high=9999):
                try:
                    return max(low, min(high, int((query.get(name) or [str(default)])[0])))
                except ValueError:
                    return default
            year_min, year_max = number("year_min", 0), number("year_max", 9999)
            episodes_min, episodes_max = number("episodes_min", 0), number("episodes_max", 9999)
            seasons_min, seasons_max = number("seasons_min", 0), number("seasons_max", 9999)
            matches = [x for x in self.catalog.items if
                       (not phrase or phrase in x["title"].casefold() or phrase in x["description"].casefold())
                       and (not genre or genre in x["genres"])
                       and (not age or (x["age_rating"] or "unrated") == age)
                       and year_min <= (x["year"] or 0) <= year_max
                       and episodes_min <= (x["episodes"] or 0) <= episodes_max
                       and seasons_min <= (x["seasons"] or 0) <= seasons_max]
            if order == "title":
                matches.sort(key=lambda x: x["title"].casefold())
            elif order == "new":
                matches.sort(key=lambda x: x["year"] or 0, reverse=True)
            else:
                matches.sort(key=lambda x: (x["popularity"], x["rating"]), reverse=True)
            offset = number("offset", 0, 0, 100000)
            limit = number("limit", 36, 1, 60)
            self.json_response({"total": len(matches), "items": matches[offset:offset + limit]})
        elif path.startswith("/api/related/"):
            item_id = path.split("/")[3]
            self.valid_id(item_id)
            source = self.catalog.by_id.get(item_id)
            if not source:
                self.json_response({"error": "Сериал не найден."}, 404)
                return
            genres = set(source.get("genres") or [])
            def related_score(item):
                other = set(item.get("genres") or [])
                overlap = len(genres & other)
                union = len(genres | other) or 1
                year_gap = abs((source.get("year") or 0) - (item.get("year") or 0))
                return (overlap / union * 12 + overlap * 2.5,
                        -min(year_gap, 25), item.get("popularity") or 0)
            candidates = [item for item in self.catalog.items if item["id"] != item_id and genres.intersection(item.get("genres") or [])]
            candidates.sort(key=related_score, reverse=True)
            self.json_response({"items": candidates[:30]})
        elif path.startswith("/api/series/") and path.endswith("/rating"):
            item_id = path.split("/")[3]
            self.valid_id(item_id)
            if item_id not in self.catalog.by_id:
                self.json_response({"error": "Сериал не найден."}, 404)
            else:
                self.json_response(crunchy_rating(item_id))
        elif path.startswith("/api/series/") and path.endswith("/seasons"):
            item_id = path.split("/")[3]
            self.valid_id(item_id)
            seasons = cms("series/%s/seasons" % item_id)
            if not seasons.get("data"):
                details = cms("series/%s" % item_id).get("data") or []
                series_details = details[0] if details else {}
                seasons["availability_status"] = series_details.get("availability_status")
                seasons["media_count"] = series_details.get("media_count") or 0
            self.json_response(seasons)
        elif path.startswith("/api/seasons/") and path.endswith("/episodes"):
            item_id = path.split("/")[3]
            self.valid_id(item_id)
            self.json_response(cms("seasons/%s/episodes" % item_id))
        elif path.startswith("/api/series/"):
            item_id = path.split("/")[3]
            self.valid_id(item_id)
            self.json_response(self.catalog.by_id.get(item_id) or {"error": "Сериал не найден."}, 200 if item_id in self.catalog.by_id else 404)
        else:
            self.json_response({"error": "Не найдено."}, 404)

    def valid_id(self, value):
        if not ID_PATTERN.fullmatch(value):
            raise RuntimeError("Некорректный идентификатор.")

    def read_body(self, limit=4096):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > limit:
            raise RuntimeError("Слишком большой запрос.")
        return self.rfile.read(length)

    def do_POST(self):
        if not self.authorized() and not self.authorized_stop_beacon():
            self.json_response({"error": "Недоступный запрос."}, 403)
            return
        self.init_context()
        path = urllib.parse.urlsplit(self.path).path
        try:
            if path in ("/api/login/start", "/api/login/frame", "/api/login/input", "/api/login/cancel"):
                if not self.public_origin().startswith("https://") and self.headers.get("Host", "").split(":")[0] not in ("localhost", "127.0.0.1"):
                    self.json_response({"error": "Для входа откройте плеер через HTTPS."}, 400)
                    return
                action = path.rsplit("/", 1)[-1]
                if action == "start":
                    now = time.time()
                    with LOGIN_ATTEMPTS_LOCK:
                        for key, stamps in list(LOGIN_ATTEMPTS.items()):
                            recent = [stamp for stamp in stamps if stamp > now - 300]
                            if recent: LOGIN_ATTEMPTS[key] = recent
                            else: LOGIN_ATTEMPTS.pop(key, None)
                        attempts = LOGIN_ATTEMPTS.setdefault(self.client_address[0], [])
                        if len(attempts) >= 5:
                            self.json_response({"error": "Слишком много попыток входа. Подождите 5 минут."}, 429)
                            return
                        attempts.append(now)
                body = json.loads(self.read_body(8192) or b"{}")
                result = BROWSER.remote_login(self.sid, "login_" + action, input=body.get("input"))
                cookie = result.pop("cookie", "")
                if cookie:
                    with AUTH_REFRESH_LOCK:
                        auth, _ = BROWSER.request(cookie=cookie, device_id=State.device_id)
                        State.cookie = auth.get("refresh_token") or cookie
                        State.access_token = auth.get("access_token") or ""
                        State.access_until = time.time() + int(auth.get("expires_in") or 300)
                        State.browser_required = True
                        with STREAMS_LOCK:
                            AUTH_LATEST[self.sid] = {"cookie": State.cookie, "until": time.time() + 3600}
                    result = {"status": "connected", "connected": True}
                self.json_response(result)
            elif path == "/api/connect":
                cookie = json.loads(self.read_body()).get("cookie", "").strip()
                if not cookie or len(cookie) > 4096 or not re.fullmatch(r"[A-Za-z0-9._~%+-]+", cookie):
                    raise RuntimeError("Вставьте значение cookie etp_rt.")
                with AUTH_REFRESH_LOCK:
                    auth, _ = BROWSER.request(cookie=cookie, device_id=State.device_id)
                    State.cookie = auth.get("refresh_token") or cookie
                    State.access_token = auth.get("access_token") or ""
                    State.access_until = time.time() + int(auth.get("expires_in") or 300)
                    State.browser_required = True
                    with STREAMS_LOCK:
                        AUTH_LATEST[self.sid] = {"cookie": State.cookie, "until": time.time() + 3600}
                self.json_response({"connected": True})
            elif path == "/api/browser-login/start":
                raise RuntimeError("На общем сервере подключите собственную сессию через cookies.txt.")
            elif path == "/api/browser-login/cancel":
                State.browser_login_cancel.set()
                self.json_response({"ok": True})
            elif path == "/api/lists/rate":
                data = json.loads(self.read_body(8192))
                self.json_response(sync_rates(self.shiki, self.mal, data.get("providers"), int(data.get("mal_id") or 0), data, automatic=data.get("automatic") is True))
            elif path == "/api/shiki/config":
                data = json.loads(self.read_body(8192))
                self.json_response(self.shiki.configure(data.get("provider"), data.get("client_id", ""),
                                                   data.get("client_secret", "")))
            elif path == "/api/shiki/start":
                data = json.loads(self.read_body())
                url = self.mal.start(self.public_origin() + "/mal/callback", self.sid) if data.get("provider") == "mal" else self.shiki.start(data.get("provider"), self.public_origin() + "/shiki/callback", self.sid, domain=data.get("domain"))
                self.json_response({"url": url})
            elif path == "/api/shiki/disconnect":
                data = json.loads(self.read_body())
                if data.get("provider") == "mal": self.mal.disconnect()
                else: self.shiki.disconnect(data.get("provider"))
                self.json_response({**self.shiki.status(), "mal": self.mal.status()})
            elif path == "/api/shiki/rate":
                data = json.loads(self.read_body())
                self.json_response(self.mal.update_rate(int(data.get("mal_id") or 0), data) if data.get("provider") == "mal" else self.shiki.update_rate(data.get("provider"), int(data.get("mal_id") or 0), data))
            elif path == "/api/disconnect":
                stop_stream()
                with State.lock:
                    State.cookie = State.access_token = ""
                    State.browser_required = False
                self.json_response({"connected": False})
            elif path.startswith("/api/play/"):
                item_id = path.split("/")[3]
                self.valid_id(item_id)
                stop_stream()
                settings = json.loads(self.read_body() or b"{}")
                platform = settings.get("platform", "firefox")
                if platform not in ("firefox", "safari"): raise RuntimeError("Unsupported playback platform.")
                data = call_cr("/playback/v3/%s/web/%s/play" % (item_id, platform), authenticated=True)
                if not data.get("url") or not data.get("token"):
                    raise RuntimeError(data.get("error") or "Crunchyroll не вернул ссылку на видео.")
                with State.lock:
                    State.stream_id, State.stream_token = item_id, data["token"]
                    State.subtitles = data.get("subtitles") or {}
                source = self.public_origin() + self.media_proxy_url(data["url"], True) if platform == "safari" else data["url"]
                self.json_response({"url": source, "subtitles": data.get("subtitles") or {}, "drm": "fairplay" if platform == "safari" else "widevine"})
            elif path == "/api/keepalive":
                with State.lock:
                    episode, token = State.stream_id, State.stream_token
                if episode and token:
                    query = urllib.parse.urlencode({"playhead": json.loads(self.read_body()).get("playhead", 0)})
                    url = "/playback/v1/token/%s/%s/keepAlive?%s" % (episode, urllib.parse.quote(token, safe=""), query)
                    call_cr(url, method="PATCH", body=b"", authenticated=True)
                self.json_response({"ok": True})
            elif path == "/api/stop":
                stop_stream()
                self.json_response({"ok": True})
            elif path == "/api/license/fairplay":
                with State.lock:
                    episode, token = State.stream_id, State.stream_token
                if not episode or not token: raise RuntimeError("Playback session is not active.")
                challenge = self.read_body(1024 * 1024)
                payload = call_cr("/license/v1/license/fairPlay", method="POST", body=challenge,
                    authenticated=True, raw=True, headers={
                        "Content-Type": "application/octet-stream", "X-Cr-Content-Id": episode,
                        "X-Cr-Video-Token": token, "Origin": "https://www.crunchyroll.com",
                        "Referer": "https://www.crunchyroll.com/"})
                if not payload: raise RuntimeError("Crunchyroll did not return a FairPlay license.")
                self.bytes_response(payload, "application/octet-stream")
            elif path == "/api/license":
                with State.lock:
                    episode, token = State.stream_id, State.stream_token
                if not episode or not token:
                    raise RuntimeError("Видеосеанс не запущен.")
                challenge = self.read_body(1024 * 1024)
                payload = call_cr("/license/v1/license/widevine", method="POST", body=challenge, authenticated=True, headers={
                    "Content-Type": "application/octet-stream",
                    "X-Cr-Content-Id": episode,
                    "X-Cr-Video-Token": token,
                    "Origin": "https://static.crunchyroll.com",
                    "Referer": "https://static.crunchyroll.com/",
                })
                if not payload.get("license"):
                    raise RuntimeError("Crunchyroll не вернул лицензию видео.")
                self.bytes_response(base64.b64decode(payload["license"]))
            else:
                self.json_response({"error": "Не найдено."}, 404)
        except Exception as error:
            self.json_response({"error": str(error)}, 502)


def main():
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    port = int(os.environ.get("CRUNCHY_LOCAL_PORT", "8765"))
    bind = os.environ.get("CRUNCHY_LOCAL_BIND", "127.0.0.1")
    if bind not in ("127.0.0.1", "0.0.0.0"):
        raise ValueError("Некорректный адрес сервера.")
    lan_ip = os.environ.get("CRUNCHY_LOCAL_LAN_IP", "").strip()
    if lan_ip and lan_ip != "127.0.0.1":
        address = ipaddress.ip_address(lan_ip)
        if address.version != 4 or not address.is_private or address.is_loopback:
            raise ValueError("Укажите частный IPv4-адрес локальной сети.")
    server = ThreadingHTTPServer((bind, port), Handler)
    lan_server = None
    if lan_ip and lan_ip != "127.0.0.1" and bind != "0.0.0.0":
        try:
            lan_server = ThreadingHTTPServer((lan_ip, port), Handler)
        except OSError:
            server.server_close()
            raise
        threading.Thread(target=lan_server.serve_forever, daemon=True).start()
    CATALOG_STORE.start()
    print("Crunchy Local: http://127.0.0.1:%s" % port, flush=True)
    if lan_server:
        print("Crunchy Local (LAN): http://%s:%s" % (lan_ip, port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        CATALOG_STORE.stop()
        close_active_streams()
        server.server_close()
        if lan_server:
            lan_server.shutdown()
            lan_server.server_close()


if __name__ == "__main__":
    main()
