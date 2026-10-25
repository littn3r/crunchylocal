"""Validate, cache and publish public catalog snapshots without blocking playback."""
import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

SOURCE_URL = 'https://raw.githubusercontent.com/af-chacon/CrunchyRollAdvancedSearch/main/frontend/public/anime.json'
MAX_BYTES = 64 * 1024 * 1024


def integer(value, maximum=10000000):
    if isinstance(value,bool):return 0
    try:
        number=float(value)
        return int(number) if math.isfinite(number) and number.is_integer() and 0<=number<=maximum else 0
    except (TypeError,ValueError,OverflowError):return 0


def image_url(images, kind):
    candidates=[]
    for group in images.get(kind,[]):
        for image in group if isinstance(group,list) else []:
            if not isinstance(image,dict):continue
            url=image.get('source') or ''
            parsed=urlsplit(url)
            if parsed.scheme=='https' and (parsed.hostname or '').endswith('.crunchyroll.com') and not parsed.username:
                candidates.append((integer(image.get('width')),url))
    return max(candidates,default=(0,''))[1]


def validate_items(items, minimum=100):
    if not isinstance(items,list) or not minimum<=len(items)<=20000:raise ValueError('Catalog has an invalid number of entries.')
    seen=set()
    for item in items:
        if not isinstance(item,dict) or not re.fullmatch(r'[A-Z0-9]{5,20}',str(item.get('id',''))) or not isinstance(item.get('title'),str) or not item['title'].strip():raise ValueError('Catalog entry has an invalid ID or title.')
        if item['id'] in seen:raise ValueError('Catalog contains duplicate series IDs.')
        seen.add(item['id'])
        for field in ['description','poster','wide','slug']:
            if not isinstance(item.get(field),str):raise ValueError('Catalog entry has invalid text fields.')
        for field in ['year','episodes','seasons','rating','popularity']:
            value=item.get(field)
            if not isinstance(value,int) or isinstance(value,bool) or value<0:raise ValueError('Catalog entry has invalid numeric fields.')
        if not isinstance(item.get('genres'),list) or any(not isinstance(genre,str) for genre in item['genres']):raise ValueError('Catalog entry has invalid genres.')
        if item.get('mal_id') is not None and (not isinstance(item['mal_id'],int) or item['mal_id']<=0):raise ValueError('Catalog entry has an invalid MAL ID.')
    return items


def normalize(raw, minimum=100):
    if not isinstance(raw,list) or not minimum<=len(raw)<=20000:raise ValueError('Upstream catalog has an invalid format or size.')
    items=[]
    for row in raw:
        if not isinstance(row,dict) or row.get('type')!='series' or not isinstance(row.get('series_metadata'),dict):raise ValueError('Upstream catalog schema changed; update was rejected.')
        meta=row['series_metadata'];anime=row.get('anilist') or {};images=row.get('images') or {}
        date=anime.get('start_date') or {}
        maturity=meta.get('extended_maturity_rating') or {}
        genres=anime.get('genres') or meta.get('tenant_categories') or []
        items.append({'id':row.get('id'),'title':row.get('title'),'description':row.get('description') or '',
            'poster':image_url(images,'poster_tall'),'wide':image_url(images,'poster_wide'),
            'year':integer(date.get('year') or meta.get('series_launch_year'),9999),
            'episodes':integer(meta.get('episode_count') or anime.get('episodes'),100000),
            'seasons':integer(meta.get('season_count'),10000),'genres':genres,
            'rating':integer(anime.get('average_score'),100),'popularity':integer(anime.get('popularity')),
            'dubbed':bool(meta.get('is_dubbed')),'subbed':bool(meta.get('is_subbed')),
            'slug':row.get('slug_title') or row.get('slug') or '',
            'age_rating':str(maturity.get('rating') or 'unrated'),'mal_id':integer(anime.get('mal_id')) or None})
    items.sort(key=lambda item:item['title'].casefold())
    return validate_items(items,minimum)


@dataclass(frozen=True)
class Snapshot:
    items: tuple
    by_id: dict
    by_mal_id: dict
    genres: tuple
    years: tuple
    version: str


def snapshot(items):
    years=[item['year'] for item in items if item.get('year')]
    digest=hashlib.sha256(json.dumps(items,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return Snapshot(tuple(items),{item['id']:item for item in items},
        {item['mal_id']:item for item in items if item.get('mal_id')},
        tuple(sorted({genre for item in items for genre in item['genres']})),
        (min(years),max(years)) if years else (1990,time.localtime().tm_year),digest)


class CatalogStore:
    def __init__(self, root, cache_dir=None, interval=86400, minimum=100):
        self.root=Path(root)
        self.cache_dir=Path(cache_dir or self.root/'.local'/'catalog')
        self.cache_path=self.cache_dir/'catalog-cache.json'
        self.minimum=minimum;self.interval=max(3600,min(int(interval),604800))
        self.lock=threading.Lock();self.stop_event=threading.Event();self.thread=None
        self.snapshot=snapshot(validate_items(json.loads((self.root/'catalog.json').read_text()),minimum))
        self.meta={'checked_at':0,'updated_at':0,'etag':'','last_modified':''}
        try:
            cached=json.loads(self.cache_path.read_text())
            if cached.get('source')!=SOURCE_URL or cached.get('format')!=1:raise ValueError('Unsupported cached catalog format.')
            self.snapshot=snapshot(validate_items(cached['items'],minimum))
            self.meta.update({key:cached.get(key) or self.meta[key] for key in self.meta})
            for key in ['checked_at','updated_at']:
                if not isinstance(self.meta[key],(float,int)) or self.meta[key]>time.time()+300:raise ValueError('Invalid cached catalog timestamp.')
        except FileNotFoundError:pass
        except Exception:
            self.snapshot=snapshot(validate_items(json.loads((self.root/'catalog.json').read_text()),minimum))
            self.meta={'checked_at':0,'updated_at':0,'etag':'','last_modified':''}
            print('Catalog: cached snapshot is invalid; using the bundled catalog.',flush=True)
        self.last_error=''

    def status(self):
        return {'source':SOURCE_URL,'count':len(self.snapshot.items),'version':self.snapshot.version,
            'checked_at':self.meta['checked_at'],'updated_at':self.meta['updated_at'],
            'interval_seconds':self.interval,'last_modified':self.meta['last_modified'],'last_error':self.last_error}

    def _download(self):
        headers={'User-Agent':'Crunchy Local catalog updater','Accept':'application/json','Accept-Encoding':'identity'}
        if self.meta['etag']:headers['If-None-Match']=self.meta['etag']
        if self.meta['last_modified']:headers['If-Modified-Since']=self.meta['last_modified']
        request=urllib.request.Request(SOURCE_URL,headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=45) as response:
                if response.status!=200:raise ValueError('Catalog server returned HTTP %s.'%response.status)
                size=int(response.headers.get('Content-Length') or 0)
                if size>MAX_BYTES:raise ValueError('Catalog download exceeds the size limit.')
                body=response.read(MAX_BYTES+1)
                if len(body)>MAX_BYTES:raise ValueError('Catalog download exceeds the size limit.')
                return json.loads(body),response.headers.get('ETag',''),response.headers.get('Last-Modified','')
        except urllib.error.HTTPError as error:
            if error.code==304:return None,self.meta['etag'],self.meta['last_modified']
            raise

    def _persist(self, current, meta):
        self.cache_dir.mkdir(parents=True,exist_ok=True)
        temporary=self.cache_dir/'catalog-cache.json.tmp'
        data={'format':1,'source':SOURCE_URL,'items':list(current.items),**meta}
        try:
            with temporary.open('w',encoding='utf-8') as output:
                json.dump(data,output,ensure_ascii=False,separators=(',',':'))
                output.flush();os.fsync(output.fileno())
            os.replace(temporary,self.cache_path)
        finally:
            temporary.unlink(missing_ok=True)

    def refresh(self):
        with self.lock:
            try:
                raw,etag,modified=self._download()
                current=self.snapshot
                if raw is not None:
                    items=normalize(raw,self.minimum)
                    if len(items)<max(self.minimum,len(current.items)*0.8):raise ValueError('Catalog shrank by more than 20%; keeping the previous snapshot.')
                    current=snapshot(items)
                changed=current.version!=self.snapshot.version
                now=time.time()
                meta={'checked_at':now,'updated_at':now if changed else self.meta['updated_at'], 'etag':etag,'last_modified':modified}
                # Publish only after a complete validated snapshot is safely cached.
                self._persist(current,meta)
                self.snapshot=current;self.meta=meta;self.last_error=''
                print('Catalog: %s (%s series).'%('updated' if changed else 'up to date',len(current.items)),flush=True)
                return True
            except Exception as error:
                self.last_error=str(error)
                print('Catalog: update failed; keeping the previous snapshot (%s).'%type(error).__name__,flush=True)
                return False

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.stop_event.clear()
        self.thread=threading.Thread(target=self._run,name='catalog-updater',daemon=True)
        self.thread.start()

    def _run(self):
        wait=0
        while not self.stop_event.wait(wait):
            wait=self.interval if self.refresh() else min(3600,self.interval)

    def stop(self):
        self.stop_event.set()
