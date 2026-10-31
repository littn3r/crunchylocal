"""Shikimori OAuth, lists and ratings for the local player."""

import json
import os
import re
import secrets
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urljoin

from curl_cffi import requests
from anime_metadata import mal_anime, mal_image, image_url, score as valid_score


HOSTS = {"one": "https://shikimori.io", "rip": "https://shikimori.rip"}
RIP_HOSTS = ("https://shikimori.rip", "https://shikirip.top", "https://shikimori.net")
USER_AGENT = "Crunchy Local (personal local player)"
SHIKI_SCORES = {}
SHIKI_SCORES_LOCK = threading.RLock()
ANIME_DETAILS = {}
ANIME_DETAILS_LOCK = threading.RLock()
RIP_POSTERS = {}
RIP_POSTERS_LOCK = threading.RLock()
PUBLIC_ANIME = {}
PUBLIC_ANIME_LOCK = threading.RLock()
CATALOG_SEASONS = {}
CATALOG_SEASONS_LOCK = threading.RLock()
ANIME_POSTERS = {}
ANIME_POSTERS_LOCK = threading.RLock()

STATUSES = {"planned", "watching", "rewatching", "completed", "on_hold", "dropped"}


def community_score(stats):
    """Arithmetic mean of IO user votes, as in the Shiki Rating userscript."""
    if not isinstance(stats, list) or not stats:
        return None
    weighted = count = 0
    seen = set()
    for row in stats:
        try:
            value, votes = row["name"], row["value"]
            if any(isinstance(v, bool) or not isinstance(v, (int, str)) for v in (value, votes)):
                return None
            value, votes = int(value), int(votes)
        except (KeyError, TypeError, ValueError):
            return None
        if not 1 <= value <= 10 or votes < 0 or value in seen:
            return None
        seen.add(value)
        weighted += value * votes
        count += votes
    return round(weighted / count, 2) if count else None


class ShikimoriBridge:
    def __init__(self, root, catalog_by_mal, catalog=(), accounts=None, oauth_states=None, user_caches=None, season_loader=None):
        self.root = Path(root)
        catalog=tuple(catalog)
        self.catalog_by_mal = catalog_by_mal
        self.catalog_by_title = {self._title_key(item["title"]): item for item in catalog}
        self.catalog_by_id = {item['id']:item for item in (*catalog, *catalog_by_mal.values())}
        self.catalog_groups=[]
        for item in self.catalog_by_id.values():
            title_key=self._title_key(item['title'])
            anchor=re.sub(r'\s+(?:series|collection)$','',title_key)
            if len(anchor.split())>=3 and (int(item.get('seasons') or 1)>1 or anchor!=title_key):
                self.catalog_groups.append((anchor,item))
        self.season_loader = season_loader
        apps_path = Path(os.environ.get("CRUNCHY_LOCAL_OAUTH_APPS_PATH") or self.root / "oauth_apps.json")
        self.oauth_apps = json.loads(apps_path.read_text(encoding="utf-8")) if apps_path.exists() else {}
        self.lock = threading.RLock()
        self.accounts = {provider: dict((accounts or {}).get(provider) or {}) for provider in HOSTS}
        self.oauth_states = oauth_states if oauth_states is not None else {}
        self.rate_cache = user_caches.setdefault("rates", {}) if user_caches is not None else {}
        self.list_cache = user_caches.setdefault("lists", {}) if user_caches is not None else {}
        self.rating_cache = SHIKI_SCORES
        self.mal_rating_cache = {}
        self.season_cache = {}

    def _provider(self, provider):
        if provider not in HOSTS:
            raise RuntimeError("Неизвестный адрес Shikimori.")
        return provider

    def _host(self, provider):
        host = self.accounts[provider].get("host")
        return host if provider == "rip" and host in RIP_HOSTS else HOSTS[provider]

    def _http(self, provider, method, path, **kwargs):
        # Forward credentials only between the explicitly verified RIP mirrors.
        kwargs.setdefault("impersonate", "chrome")
        for _ in range(3):
            response = requests.request(method, self._host(provider) + path, allow_redirects=False, **kwargs)
            if response.headers.get("cf-mitigated") == "challenge":
                raise RuntimeError("Cloudflare блокирует запросы плеера к Shikimori. Попробуйте позже или используйте другую сеть для сервера плеера.")
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            target = urlsplit(urljoin(self._host(provider) + path, response.headers.get("Location", "")))
            host = "https://" + target.netloc
            if provider != "rip" or target.scheme != "https" or host not in RIP_HOSTS or target.path != urlsplit(path).path or target.query != urlsplit(path).query:
                raise RuntimeError("Shikimori перенаправил запрос на неподдерживаемый адрес.")
            self.accounts[provider]["host"] = host
        raise RuntimeError("Слишком много перенаправлений Shikimori.")

    @staticmethod
    def _title_key(title):
        title = unicodedata.normalize('NFKD', str(title or '')).casefold()
        title = ''.join(c for c in title if not unicodedata.combining(c))
        return " ".join(re.findall(r"[^\W_]+", title))

    @classmethod
    def _season_title_key(cls, title):
        key = cls._title_key(title)
        key = re.sub(r"(?<=[a-z])(?=[1-9][0-9]*$)", " ", key)
        key = re.sub(r'\b(\d+)(?:st|nd|rd|th) season\b', r'season \1', key)
        if not re.search(r'\b(?:season|part) \d+$', key):
            key = re.sub(r'\s+([2-9]\d*)$', r' season \1', key)
        return re.sub(r'\s+season 1$', '', key)

    def _credentials(self, provider):
        bundled = self.oauth_apps.get(provider) or {}
        return bundled.get("client_id"), bundled.get("client_secret")

    def _catalog_match(self, english_title):
        key = self._title_key(english_title)
        local = self.catalog_by_title.get(key)
        if local:
            return local
        base = re.sub(r"\s+(?:season|series)\s+\d+(?:\s+part\s+\d+)?$", "", key)
        base = re.sub(r"\s+\d+(?:st|nd|rd|th)\s+season(?:\s+part\s+\d+)?$", "", base)
        base = re.sub(r"\s+(?:the\s+)?final\s+season(?:\s+part\s+\d+)?$", "", base)
        base = re.sub(r"\s+(?:part\s+)?[2-9](?:\s+part\s+\d+)?$", "", base)
        if base != key and base in self.catalog_by_title:
            return self.catalog_by_title[base]
        # A grouped Crunchyroll series may have differently named films/seasons.
        grouped = []
        for anchor,item in self.catalog_groups:
            if key == anchor or key.startswith(anchor + ' '):grouped.append(item)
        return grouped[0] if len(grouped) == 1 else None

    def _catalog_seasons(self, local):
        if not self.season_loader:return []
        key=(local['id'],local.get('title'),local.get('mal_id'),local.get('seasons'))
        with CATALOG_SEASONS_LOCK:
            cached=CATALOG_SEASONS.get(key)
            if cached and cached[0]>time.time():return cached[1]
        try:
            data=self.season_loader(local['id'])
            seasons=data.get('data') or []
            if not isinstance(seasons,list):return []
            seasons=[s for s in seasons if s.get('id') and s.get('title')]
        except Exception:return []
        if seasons:
            with CATALOG_SEASONS_LOCK:
                if len(CATALOG_SEASONS)>=4000:CATALOG_SEASONS.pop(next(iter(CATALOG_SEASONS)))
                CATALOG_SEASONS[key]=(time.time()+3600,seasons)
        return seasons

    def catalog_matches(self, animes):
        """Match each external entry to an actual season, never to a franchise's latest ID."""
        candidates={}
        titles={}
        for anime_id,anime in animes.items():
            titles[anime_id]=[t for t in (anime.get('english'),anime.get('name'),*(anime.get('synonyms') or [])) if t]
            local=self.catalog_by_mal.get(anime_id)
            if local:candidates[local['id']]=local
            for title in titles[anime_id]:
                local=self._catalog_match(title)
                if local:candidates[local['id']]=local
        index={}
        loaded={}
        for local in candidates.values():
            seasons=self._catalog_seasons(local) if int(local.get('seasons') or 1)>1 else []
            loaded[local['id']]=seasons
            for season in seasons:
                title=season['title'];number=season.get('season_number') or season.get('season_sequence_number')
                if re.fullmatch(r'(?:season|сезон)\s*\d+',title.strip(),re.I):title=local['title']+' '+title
                aliases=[title]
                if number and self._title_key(title)==self._title_key(local['title']):
                    aliases=[local['title']+' Season '+str(number)]
                for alias in aliases:
                    index.setdefault(self._season_title_key(alias),{})[(local['id'],season['id'])]=(local,season)
        result={}
        for anime_id,anime in animes.items():
            found={}
            for title in titles[anime_id]:found.update(index.get(self._season_title_key(title),{}))
            if len(found)==1:
                local,season=next(iter(found.values()))
                result[anime_id]={'crunchy_id':local['id'],'season_id':season['id'],'season_title':season['title']}
                continue
            # Without season metadata only a genuine single-season catalog entry is safe.
            local=self.catalog_by_mal.get(anime_id)
            if not local:
                for title in titles[anime_id]:
                    local=self._catalog_match(title)
                    if local:break
            same_entry=local and (anime_id==local.get('mal_id') or any(self._season_title_key(t)==self._season_title_key(local['title']) for t in titles[anime_id]))
            if same_entry and not loaded.get(local['id']) and int(local.get('seasons') or 1)<=1:
                result[anime_id]={'crunchy_id':local['id'],'season_id':None,'season_title':local['title']}
        return result

    def _save(self):
        # The HTTP response writes the changed account into its browser's encrypted cookie.
        pass

    def status(self):
        with self.lock:
            return {provider: {"configured": bool(all(self._credentials(provider))),
                               "connected": bool(account.get("refresh_token") and account.get("user_id")),
                               "name": account.get("name", ""), "user_id": account.get("user_id"),
                               "error": account.get("error", ""), "host": self._host(provider)}
                    for provider, account in self.accounts.items()}

    def configure(self, provider, client_id, client_secret):
        raise RuntimeError("Данные OAuth-приложения задаются владельцем сервера.")

    def disconnect(self, provider):
        provider = self._provider(provider)
        with self.lock:
            account = self.accounts[provider]
            for field in ("access_token", "refresh_token", "expires_at", "user_id", "name"):
                account.pop(field, None)
            self.rate_cache.pop(provider, None)
            self.list_cache.pop(provider, None)
            account.pop("error", None)
            self._save()
        return self.status()

    def _request(self, provider, method, path, *, data=None, auth=False):
        provider = self._provider(provider)
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer " + self._access(provider)
        try:
            response = self._http(provider, method, path, headers=headers,
                                        json=data, timeout=25)
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError("Shikimori сейчас недоступен. Повторите попытку позже.") from None
        if response.status_code == 401 and auth:
            with self.lock:
                self.accounts[provider]["expires_at"] = 0
            headers["Authorization"] = "Bearer " + self._access(provider)
            response = self._http(provider, method, path, headers=headers,
                                        json=data, timeout=25)
        if response.status_code >= 400:
            if response.status_code == 429:
                raise RuntimeError("Shikimori временно ограничил запросы. Подождите минуту.")
            raise RuntimeError("Shikimori вернул ошибку HTTP %s." % response.status_code)
        return response.json() if response.content else {}

    def _access(self, provider):
        with self.lock:
            account = self.accounts[provider]
            if not account.get("refresh_token"):
                raise RuntimeError("Подключите список Shikimori в настройках.")
            if account.get("access_token") and account.get("expires_at", 0) > time.time() + 60:
                return account["access_token"]
            client_id, client_secret = self._credentials(provider)
            payload = {"grant_type": "refresh_token", "client_id": client_id,
                       "client_secret": client_secret,
                       "refresh_token": account["refresh_token"]}
            try:
                response = self._http(provider, "POST", "/oauth/token",
                                         headers={"User-Agent": USER_AGENT}, data=payload, timeout=25)
            except RuntimeError:
                raise
            except Exception:
                raise RuntimeError("Не удалось обновить вход в Shikimori.") from None
            if response.status_code != 200:
                raise RuntimeError("Сессия Shikimori истекла. Подключите список повторно.")
            result = response.json()
            account["access_token"] = result["access_token"]
            account["refresh_token"] = result.get("refresh_token", account["refresh_token"])
            account["expires_at"] = time.time() + int(result.get("expires_in", 86400))
            self._save()
            return account["access_token"]

    def start(self, provider, redirect, owner_sid, domain=None):
        provider = self._provider(provider)
        if domain is not None:
            if provider != "rip" or domain not in RIP_HOSTS:
                raise RuntimeError("Неизвестное зеркало Shikimori.")
            self.accounts[provider]["host"] = domain
        with self.lock:
            account = self.accounts[provider]
            client_id, client_secret = self._credentials(provider)
            if not client_id or not client_secret:
                raise RuntimeError("OAuth-приложение для этого адреса Shikimori не настроено.")
            state = secrets.token_urlsafe(32)
            self.oauth_states[state] = (provider, redirect, time.time() + 600, owner_sid, self._host(provider))
            account.pop("error", None)
            return self._host(provider) + "/oauth/authorize?" + urlencode({
                "client_id": client_id, "redirect_uri": redirect,
                "response_type": "code", "scope": "user_rates", "state": state})

    def callback(self, state, code, error, owner_sid):
        with self.lock:
            pending = self.oauth_states.get(state)
            if not pending or pending[2] < time.time() or pending[3] != owner_sid:
                raise RuntimeError("Время входа в Shikimori истекло. Начните заново.")
            self.oauth_states.pop(state, None)
        provider, redirect = pending[:2]
        if len(pending) > 4 and provider == "rip":
            self.accounts[provider]["host"] = pending[4]
        if error or not code:
            self.accounts[provider]["error"] = "Доступ к списку не был разрешён."
            return provider
        with self.lock:
            account = self.accounts[provider]
            client_id, client_secret = self._credentials(provider)
            payload = {"grant_type": "authorization_code", "client_id": client_id,
                       "client_secret": client_secret, "code": code,
                       "redirect_uri": redirect}
        try:
            response = self._http(provider, "POST", "/oauth/token",
                                     headers={"User-Agent": USER_AGENT}, data=payload, timeout=25)
            if response.status_code != 200:
                raise RuntimeError("Shikimori отклонил код входа. Проверьте Redirect URI в настройках OAuth-приложения.")
            token = response.json()
            with self.lock:
                account["access_token"] = token["access_token"]
                account["refresh_token"] = token["refresh_token"]
                account["expires_at"] = time.time() + int(token.get("expires_in", 86400))
            user = self._request(provider, "GET", "/api/users/whoami", auth=True)
            with self.lock:
                account["user_id"] = int(user["id"])
                account["name"] = user.get("nickname") or user.get("name") or "Shikimori"
                account.pop("error", None)
                self.rate_cache.pop(provider, None)
                self.list_cache.pop(provider, None)
                self._save()
        except Exception as exc:
            with self.lock:
                account["error"] = str(exc)
                for field in ("access_token", "refresh_token", "expires_at", "user_id", "name"):
                    account.pop(field, None)
                self._save()
        return provider

    def _rates(self, provider, force=False):
        provider = self._provider(provider)
        with self.lock:
            cached = self.rate_cache.get(provider)
            user_id = self.accounts[provider].get("user_id")
        if not user_id:
            raise RuntimeError("Подключите список Shikimori.")
        if cached and not force and cached[0] > time.time():
            return cached[1]
        rates = self._request(provider, "GET", "/api/v2/user_rates?" + urlencode({
            "user_id": user_id, "target_type": "Anime"}), auth=True)
        if not isinstance(rates, list):
            raise RuntimeError("Shikimori вернул неожиданный формат списка.")
        rates = [rate for rate in rates if rate.get("target_type") == "Anime"]
        with self.lock:
            self.rate_cache[provider] = (time.time() + 300, rates)
        return rates

    def rate(self, provider, mal_id):
        if mal_id <= 0:
            raise RuntimeError("Некорректный ID аниме.")
        return next((rate for rate in self._rates(provider) if int(rate.get("target_id") or 0) == mal_id), None)

    def list(self, provider, force=False):
        provider = self._provider(provider)
        with self.lock:
            cached = self.list_cache.get(provider)
        if cached and not force and cached[0] > time.time():
            return cached[1]
        rates = self._rates(provider, force=force)
        ids = [int(rate["target_id"]) for rate in rates if rate.get("target_id")]
        details = self._anime_details(provider, ids)
        missing=[i for i in ids if not details.get(i)]
        if missing:details.update({i:d for i,d in self._anime_details('one' if provider=='rip' else 'rip',missing).items() if d})
        posters = self.anime_posters(ids)
        matches = self.catalog_matches(details)
        items = []
        for rate in rates:
            mal_id = int(rate.get("target_id") or 0)
            remote = details.get(mal_id, {})
            match=matches.get(mal_id,{})
            local=self.catalog_by_id.get(match.get('crunchy_id'))
            matched_title = match.get('season_title') or remote.get("english") or remote.get('name') or ""
            poster_data = posters.get(mal_id, {})
            poster = poster_data.get("originalUrl") or poster_data.get("mainUrl") or ""
            poster_fallback = poster_data.get("mainUrl") or ""
            items.append({"mal_id": mal_id, "crunchy_id": local["id"] if local else None,
                          "season_id":match.get('season_id'),"season_title":match.get('season_title'),
                          "english_title": matched_title,
                          "title_en": remote.get("english") or remote.get("name") or (local or {}).get("title") or "Anime %s" % mal_id,
                          "title": remote.get("russian") or (local or {}).get("title") or remote.get("name") or "Аниме %s" % mal_id,
                          "poster": poster,
                          "poster_fallback": poster_fallback if poster_fallback != poster else "",
                          "catalog_poster": poster_data.get('malUrl') or '',
                          "year": (local or {}).get("year"), "total_episodes": remote.get("episodes") or (local or {}).get("episodes"),
                          "mal_score": remote.get("score"), "rate": rate,
                          "url": (remote.get("url") if str(remote.get("url") or "").startswith("https://")
                                  else self._host(provider) + (remote.get("url") or "/animes/%s" % mal_id))})
        items.sort(key=lambda x: x["rate"].get("updated_at") or "", reverse=True)
        result = {"items": items, "total": len(items),
                  "available": sum(bool(item["crunchy_id"]) for item in items)}
        with self.lock:
            self.list_cache[provider] = (time.time() + 300, result)
        return result

    @staticmethod
    def _store_rip_posters(animes):
        now = time.time()
        with RIP_POSTERS_LOCK:
            for anime in animes:
                poster = anime.get('poster') or {}
                urls = {}
                for field in ('originalUrl', 'mainUrl'):
                    value = poster.get(field) or ''
                    url = urljoin(HOSTS['rip'], value) if value else ''
                    if url and urlsplit(url).scheme == 'https' and 'https://' + urlsplit(url).netloc in RIP_HOSTS:
                        urls[field] = url
                RIP_POSTERS[int(anime['id'])] = (now + 86400, urls)

    def _anime_details(self, provider, ids):
        """Cache public metadata separately from private ratings and statuses."""
        with ANIME_DETAILS_LOCK:
            now = time.time()
            pending = list(dict.fromkeys(value for value in ids if ANIME_DETAILS.get((provider, value), (0, {}))[0] < now))
            for start in range(0, len(pending), 50):
                batch = pending[start:start + 50]
                query = '{ animes(ids: "%s", limit: %s) { id name russian english synonyms score episodes url poster { originalUrl mainUrl } } }' % (
                    ','.join(map(str, batch)), len(batch))
                try:
                    response = self._request(provider, 'POST', '/api/graphql', data={'query': query})
                    if response.get('errors'):
                        continue
                    animes = response.get('data', {}).get('animes', [])
                    for anime in animes:
                        ANIME_DETAILS[(provider, int(anime['id']))] = (now + 3600, anime)
                    returned = {int(anime['id']) for anime in animes}
                    for value in batch:
                        if value not in returned:
                            ANIME_DETAILS[(provider, value)] = (now + 600, {})
                    if provider == 'rip':
                        self._store_rip_posters(animes)
                except (RuntimeError, ValueError, KeyError):
                    continue
                if start + 50 < len(pending):
                    time.sleep(0.25)
            if len(ANIME_DETAILS) > 20000:
                for key in list(ANIME_DETAILS):
                    if ANIME_DETAILS[key][0] < now:
                        ANIME_DETAILS.pop(key, None)
            return {value: dict(ANIME_DETAILS.get((provider, value), (0, {}))[1]) for value in ids}

    def _rip_posters(self, ids, force=False):
        """Public RIP artwork, independent of the user's list/OAuth provider."""
        ids = list(dict.fromkeys(int(value) for value in ids if int(value) > 0))
        with RIP_POSTERS_LOCK:
            now = time.time()
            pending = [value for value in ids if force or RIP_POSTERS.get(value, (0, {}))[0] < now]
            for start in range(0, len(pending), 50):
                batch = pending[start:start + 50]
                query = '{ animes(ids: "%s", limit: %s) { id poster { originalUrl mainUrl } } }' % (
                    ','.join(map(str, batch)), len(batch))
                try:
                    response = self._http('rip', 'POST', '/api/graphql', json={'query': query},
                                          headers={'User-Agent': USER_AGENT}, timeout=20)
                    if response.status_code != 200:
                        continue
                    data = response.json()
                    if data.get('errors'):
                        continue
                    animes = data.get('data', {}).get('animes', [])
                    self._store_rip_posters(animes)
                    returned = {int(anime['id']) for anime in animes}
                    for value in batch:
                        if value not in returned:
                            RIP_POSTERS[value] = (now + 600, {})
                except (RuntimeError, ValueError, KeyError, requests.RequestsError):
                    continue
                if start + 50 < len(pending):
                    time.sleep(0.25)
            if len(RIP_POSTERS) > 10000:
                for value in list(RIP_POSTERS):
                    if RIP_POSTERS[value][0] < now:
                        RIP_POSTERS.pop(value, None)
            return {value: dict(RIP_POSTERS.get(value, (0, {}))[1]) for value in ids}

    def anime_posters(self, ids, mal_pictures=None):
        """Season-specific public artwork: IO, RIP, then MAL, including unlisted anime."""
        ids=list(dict.fromkeys(int(i) for i in ids if 0<int(i)<=9999999))
        with ANIME_POSTERS_LOCK:
            pending=[i for i in ids if ANIME_POSTERS.get(i,(0,{}))[0]<time.time()]
        if pending:
            details=self._anime_details('one',pending)
            artwork={}
            for i in pending:
                poster=(details.get(i) or {}).get('poster') or {}
                artwork[i]={k:image_url(poster.get(k),HOSTS['one']) for k in ('originalUrl','mainUrl')}
            missing=[i for i in pending if not any(artwork[i].values())]
            if missing:
                for i,p in self._rip_posters(missing).items():
                    for k in ('originalUrl','mainUrl'):
                        source=image_url(p.get(k),HOSTS['rip'])
                        if source:artwork[i][k]=source
            missing=[]
            for i in pending:
                source=mal_image((mal_pictures or {}).get(i),'anime')
                if source:artwork[i]['malUrl']=source
                if not any(artwork[i].values()):missing.append(i)
            def from_mal(i):
                try:
                    data,_=mal_anime(self,i)
                    picture=data.get('main_picture') or {};jpg=((data.get('images') or {}).get('jpg') or {})
                    return i,mal_image(picture.get('large') or picture.get('medium') or jpg.get('large_image_url') or jpg.get('image_url'),'anime')
                except Exception:return i,''
            if missing:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for i,source in pool.map(from_mal,missing):
                        if source:artwork[i]['malUrl']=source
            with ANIME_POSTERS_LOCK:
                for i,p in artwork.items():
                    if not p.get('originalUrl'):p['originalUrl']=p.get('mainUrl') or p.get('malUrl') or ''
                    if len(ANIME_POSTERS)>=10000:ANIME_POSTERS.pop(next(iter(ANIME_POSTERS)))
                    ANIME_POSTERS[i]=(time.time()+(86400 if p['originalUrl'] else 300),p)
        with ANIME_POSTERS_LOCK:
            return {i:dict(ANIME_POSTERS.get(i,(0,{}))[1]) for i in ids}

    def match_season(self, provider, title, episode_count=0, base_mal_id=0):
        provider = self._provider(provider)
        title = str(title or "").strip()[:180]
        if not title:
            return {"items": [], "matched_id": 0}
        cache_key = (provider, title, int(episode_count or 0), int(base_mal_id or 0))
        cached = self.season_cache.get(cache_key)
        if cached and cached[0] > time.time():
            return cached[1]
        # Matching is public and independent of the user's list/OAuth host.
        provider='one'
        results = self._request(provider, "GET", "/api/animes?" + urlencode({"search": title, "limit": 15}))
        if not isinstance(results, list):
            raise RuntimeError("Shikimori вернул неожиданный ответ поиска.")
        ids = [int(item["id"]) for item in results if item.get("id")]
        english = {}
        if ids:
            english=self._anime_details(provider,ids)
        posters = self.anime_posters(ids)
        title_key = self._season_title_key(title)
        candidates = []
        for result in results:
            anime_id = int(result.get("id") or 0)
            if not anime_id:
                continue
            extra = english.get(anime_id, {})
            name = extra.get("english") or result.get("name") or ""
            anime_episodes = int(extra.get("episodes") or result.get("episodes") or 0)
            aired_episodes = int(result.get("episodes_aired") or 0)
            aliases=[name,result.get('name'),extra.get('name'),*(extra.get('synonyms') or [])]
            exact = any(t and self._season_title_key(t) == title_key for t in aliases)
            same_episodes = bool(episode_count and int(episode_count) in (anime_episodes, aired_episodes))
            score = (100 if exact else 0) + (20 if same_episodes else 0)
            if anime_id == int(base_mal_id or 0):
                score += 5
            if not exact and title_key in self._season_title_key(name):
                score += 10
            poster_data = posters.get(anime_id, {})
            poster = poster_data.get('originalUrl') or poster_data.get('mainUrl') or ''
            candidates.append({"mal_id": anime_id, "title": result.get("russian") or name,
                               "english_title": name, "title_en": name, "episodes": anime_episodes,
                               "poster": poster, "score": score,
                               "url": self._host(provider) + "/animes/%s" % anime_id})
        candidates.sort(key=lambda item: item["score"], reverse=True)
        best = candidates[0] if candidates else None
        exacts=[c for c in candidates if c['score']>=100]
        matched_id = exacts[0]['mal_id'] if len(exacts)==1 else 0
        response = {"items": candidates[:12], "matched_id": matched_id}
        self.season_cache[cache_key] = (time.time() + 3600, response)
        return response

    def update_rate(self, provider, mal_id, fields):
        provider = self._provider(provider)
        if mal_id <= 0 or mal_id > 9999999:
            raise RuntimeError("Некорректный ID аниме.")
        allowed = {}
        if "episodes" in fields:
            episodes = int(fields["episodes"])
            if not 0 <= episodes <= 10000:
                raise RuntimeError("Некорректное число серий.")
            allowed["episodes"] = episodes
        if "score" in fields:
            score = int(fields["score"])
            if not 0 <= score <= 10:
                raise RuntimeError("Оценка должна быть от 0 до 10.")
            allowed["score"] = score
        if "status" in fields:
            if fields["status"] not in STATUSES:
                raise RuntimeError("Некорректный статус просмотра.")
            allowed["status"] = fields["status"]
        if not allowed:
            raise RuntimeError("Нет изменений для синхронизации.")
        current = self.rate(provider, mal_id)
        if current:
            result = self._request(provider, "PATCH", "/api/v2/user_rates/%s" % current["id"],
                                   data={"user_rate": allowed}, auth=True)
        else:
            with self.lock:
                user_id = self.accounts[provider]["user_id"]
            initial = {"user_id": user_id, "target_id": mal_id, "target_type": "Anime",
                       "status": "watching", **allowed}
            result = self._request(provider, "POST", "/api/v2/user_rates",
                                   data={"user_rate": initial}, auth=True)
        with self.lock:
            self.rate_cache.pop(provider, None)
            self.list_cache.pop(provider, None)
        return result

    def public_anime(self, mal_id, provider=None):
        """Public Russian metadata can fall back to IO without forwarding OAuth."""
        if not 0 < mal_id <= 9999999:
            raise RuntimeError("Некорректный ID аниме.")
        providers = (self._provider(provider),) if provider else ("rip", "one")
        key = (provider, mal_id) if provider else mal_id
        with PUBLIC_ANIME_LOCK:
            cached = PUBLIC_ANIME.get(key)
            if cached and cached[0] > time.time():
                return cached[1], cached[2]
        for index, provider in enumerate(providers):
            try:
                with PUBLIC_ANIME_LOCK:
                    cached = PUBLIC_ANIME.get((provider, mal_id))
                anime = cached[1] if cached and cached[0] > time.time() else self._request(provider, "GET", "/api/animes/%s" % mal_id)
                if int(anime.get("id") or 0) != mal_id:
                    raise ValueError("Anime ID mismatch")
            except Exception:
                if index == len(providers) - 1:
                    raise
                continue
            with PUBLIC_ANIME_LOCK:
                while len(PUBLIC_ANIME) >= 4000:
                    PUBLIC_ANIME.pop(next(iter(PUBLIC_ANIME)))
                entry = (time.time() + (3600 if len(providers) == 1 or provider == "rip" else 300), anime, provider)
                PUBLIC_ANIME[key] = PUBLIC_ANIME[(provider, mal_id)] = entry
            return anime, provider

    def shiki_score(self, provider, mal_id):
        self._provider(provider)
        provider = "one"
        if mal_id <= 0 or mal_id > 9999999:
            raise RuntimeError("Некорректный ID аниме.")
        key = ("io-user-mean", mal_id)
        with SHIKI_SCORES_LOCK:
            cached = self.rating_cache.get(key)
        if cached and cached[0] > time.time():
            return cached[1]["shikimori"]
        score = None
        try:
            anime, _ = self.public_anime(mal_id, provider=provider)
            score = community_score(anime.get("rates_scores_stats"))
        except Exception:
            pass
        with SHIKI_SCORES_LOCK:
            self.rating_cache[key] = (time.time() + (86400 if score is not None else 300),
                                      {"shikimori": score})
        return score

    def ratings(self, provider, mal_id):
        self._provider(provider)
        provider = "one"
        score = self.shiki_score(provider, mal_id)
        result = {"mal": None, "shikimori": score, "mal_id": mal_id,
                  "mal_source": None,
                  "shikimori_url": self._host(provider) + "/animes/%s" % mal_id,
                  "mal_url": "https://myanimelist.net/anime/%s" % mal_id}
        mal_fallback = None
        try:
            anime, _ = self.public_anime(mal_id, provider=provider)
            anime_path = anime.get("url") or ""
            if re.fullmatch(r"/animes/[A-Za-z0-9_-]+", anime_path):
                result["shikimori_url"] = self._host(provider) + anime_path
            mal_fallback = valid_score(anime.get("score"))
        except Exception:
            pass
        with self.lock:
            cached = self.mal_rating_cache.get(mal_id)
        if cached and cached[0] > time.time() and cached[1] is not None:
            result["mal"], result["mal_source"] = cached[1:]
            return result
        try:
            anime, source = mal_anime(self, mal_id)
            result["mal"] = valid_score(anime.get("score"))
            if result["mal"] is not None:
                result["mal_source"] = source
        except Exception:
            pass
        if result["mal"] is None and mal_fallback is not None:
            result["mal"] = mal_fallback
            result["mal_source"] = "Shikimori"
        with self.lock:
            self.mal_rating_cache[mal_id] = (time.time() + (21600 if result["mal"] is not None else 300),
                                             result["mal"], result["mal_source"])
        return result
