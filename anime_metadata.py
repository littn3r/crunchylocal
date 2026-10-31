"""Cached public anime information from Shikimori RIP and MAL via Jikan."""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from curl_cffi import requests

CACHE = {}
MAL_DATA = {}
MAL_PORTRAITS = {}
LOCK = threading.RLock()
JIKAN_LOCK = threading.Lock()
JIKAN_LAST = 0
JIKAN_RETRY_AT = 0

class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style'):self.hidden+=1
        if tag in ('br','p','div') and not self.hidden:self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
        if tag in ('p','div') and not self.hidden:self.parts.append('\n')
    def handle_data(self, data):
        if not self.hidden:self.parts.append(data)

def plain(value):
    parser=PlainText();parser.feed(str(value or ''))
    return re.sub(r'\n[ \t]*\n+', '\n\n', ''.join(parser.parts)).strip()

def url(value, base='https://shikimori.rip'):
    value=urljoin(base,str(value or '')) if value else ''
    return value if urlsplit(value).scheme=='https' and not urlsplit(value).username else ''

def image_url(value, base='https://shikimori.rip'):
    source=url(value,base)
    return '' if '/assets/globals/missing_' in source else source

def score(value):
    try:
        result=float(value)
        return result if 0<result<=10 else None
    except (ValueError,TypeError):return None

def names(values, russian=False):
    return [str((v.get('russian') if russian else '') or v.get('name') or '') for v in values or [] if isinstance(v,dict) and (v.get('name') or v.get('russian'))]

def jikan(path):
    global JIKAN_LAST, JIKAN_RETRY_AT
    # Serialize public metadata requests to respect Jikan's request limits.
    with JIKAN_LOCK:
        if time.monotonic() < JIKAN_RETRY_AT:
            raise RuntimeError('Jikan is temporarily unavailable')
        delay=max(0,0.4-(time.monotonic()-JIKAN_LAST))
        if delay:time.sleep(delay)
        try:
            response=requests.get('https://api.jikan.moe/v4/'+path,timeout=6)
            response.raise_for_status();return response.json()['data']
        except Exception:
            JIKAN_RETRY_AT=time.monotonic()+60
            raise
        finally:JIKAN_LAST=time.monotonic()

def mal_anime(shiki, anime_id):
    """Share public MAL data between title information and player ratings."""
    with LOCK:
        cached=MAL_DATA.get(anime_id)
        if cached and cached[0]>time.time():return cached[1],cached[2]
    client_id=(shiki.oauth_apps.get('mal') or {}).get('client_id')
    data=None
    if client_id:
        try:
            fields='alternative_titles,start_date,synopsis,mean,genres,num_episodes,studios,status,media_type,average_episode_duration'
            response=requests.get(f'https://api.myanimelist.net/v2/anime/{anime_id}',params={'fields':fields},
                                  headers={'X-MAL-CLIENT-ID':client_id},timeout=12)
            response.raise_for_status();official=response.json()
            if int(official.get('id') or 0)!=anime_id:raise ValueError('Anime ID mismatch')
            data={**official,'mal_id':official.get('id'),'title_english':(official.get('alternative_titles') or {}).get('en'),
                  'score':official.get('mean'),'episodes':official.get('num_episodes'),
                  'aired':{'from':official.get('start_date')},'type':official.get('media_type'),
                  'duration':f"{round(official['average_episode_duration']/60)} min." if official.get('average_episode_duration') else ''}
        except Exception:pass
    source='MyAnimeList' if data is not None else 'Jikan'
    if data is None:data=jikan(f'anime/{anime_id}/full')
    if int(data.get('mal_id') or 0)!=anime_id:raise ValueError('Anime ID mismatch')
    with LOCK:
        if len(MAL_DATA)>=2000:MAL_DATA.pop(next(iter(MAL_DATA)))
        MAL_DATA[anime_id]=(time.time()+3600,data,source)
    return data,source

def normalize_shiki(data, roles, anime_id, rating=None, base='https://shikimori.rip'):
    if int(data.get('id') or 0)!=anime_id:raise ValueError('Anime ID mismatch')
    characters=[]
    for role in sorted(roles,key=lambda r:'Main' not in (r.get('roles') or [])):
        c=role.get('character') or {}
        if not c.get('id'):continue
        image=c.get('image') or {}
        characters.append({'id':c['id'],'name':c.get('russian') or c.get('name') or '',
            'image':image_url(image.get('original') or image.get('preview'),base),'url':url(c.get('url'),base),
            'role':(role.get('roles_russian') or role.get('roles') or [''])[0]})
    return {'id':anime_id,'source':'Shikimori','source_url':url(data.get('url') or f'/animes/{anime_id}',base),
        'title':data.get('russian') or data.get('name') or '',
        'description':plain(data.get('description_html') or data.get('description')),
        'studios':names(data.get('studios')),'genres':names(data.get('genres'),True),
        'score':rating,'mal_score':score(data.get('score')),'episodes':data.get('episodes'),
        'aired':data.get('aired_on'),'status':data.get('status'),'kind':data.get('kind'),
        'duration':data.get('duration'),'characters':characters[:36]}

def normalize_mal(data, roles, anime_id):
    if int(data.get('mal_id') or 0)!=anime_id:raise ValueError('Anime ID mismatch')
    characters=[]
    for role in sorted(roles,key=lambda r:r.get('role')!='Main'):
        c=role.get('character') or {}
        if not c.get('mal_id'):continue
        characters.append({'id':c['mal_id'],'name':c.get('name') or '',
            'image':url((c.get('images',{}).get('jpg') or {}).get('image_url')),
            'url':url(c.get('url')),'role':role.get('role') or ''})
    return {'id':anime_id,'source':'MyAnimeList','source_url':f'https://myanimelist.net/anime/{anime_id}',
        'title':data.get('title_english') or data.get('title') or '',
        'description':plain(data.get('synopsis')),'studios':names(data.get('studios')),
        'genres':names((data.get('genres') or [])+(data.get('themes') or [])),
        'score':score(data.get('score')),'episodes':data.get('episodes'),
        'aired':((data.get('aired') or {}).get('from') or '')[:10],
        'status':data.get('status'),'kind':data.get('type'),'duration':data.get('duration'),
        'characters':characters[:36]}

class ImageTag(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.attrs={}
    def handle_starttag(self,tag,attrs):
        if tag=='img':self.attrs=dict(attrs)

def mal_character_rows(markup):
    rows=[];seen=set()
    pattern=r'<a\b[^>]*href=["\'](https://myanimelist\.net/character/(\d+)/[^"\']*)["\'][^>]*>\s*(<img\b[^>]*>)\s*</a>'
    for match in re.finditer(pattern,markup,re.I):
        character_id=int(match.group(2))
        if character_id in seen:continue
        image=ImageTag();image.feed(match.group(3));attrs=image.attrs
        source=attrs.get('data-src') or attrs.get('src') or ''
        if urlsplit(source).hostname!='cdn.myanimelist.net' or '/images/characters/' not in source:continue
        source=re.sub(r'/r/\d+x\d+/', '/', source).split('?')[0]
        block=markup[match.end():match.end()+2500].split('<td align="right"',1)[0]
        role='Main' if re.search(r'\bMain(?:&nbsp;|\s|<)',block) else 'Supporting'
        rows.append({'role':role,'character':{'mal_id':character_id,'name':attrs.get('alt') or '',
            'url':match.group(1),'images':{'jpg':{'image_url':source}}}})
        seen.add(character_id)
    return rows

def mal_characters(anime_id):
    response=requests.get(f'https://myanimelist.net/anime/{anime_id}/_/characters',impersonate='chrome',timeout=15)
    response.raise_for_status()
    if len(response.content)>6*1024*1024:raise ValueError('Character page is too large')
    rows=mal_character_rows(response.text)
    if not rows:raise ValueError('Character page has no usable portraits')
    return rows

def mal_image(value,kind):
    source=image_url(value)
    if urlsplit(source).hostname!='cdn.myanimelist.net' or f'/images/{kind}/' not in source:return ''
    return re.sub(r'/r/\d+x\d+/', '/', source).split('?')[0]

class MALPortraitMeta(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.image='';self.page=''
    def handle_starttag(self,tag,attrs):
        if tag!='meta':return
        attrs=dict(attrs)
        if attrs.get('property')=='og:image':self.image=attrs.get('content') or ''
        if attrs.get('property')=='og:url':self.page=attrs.get('content') or ''

def mal_portrait(character_id):
    if not 0<character_id<=9999999:return ''
    with LOCK:
        cached=MAL_PORTRAITS.get(character_id)
        if cached and cached[0]>time.time():return cached[1]
    source='';verified=False
    try:
        response=requests.get(f'https://myanimelist.net/character/{character_id}',impersonate='chrome',timeout=6)
        response.raise_for_status()
        if len(response.content)>6*1024*1024:raise ValueError('Character page is too large')
        meta=MALPortraitMeta();meta.feed(response.text)
        page=urlsplit(meta.page)
        if page.hostname=='myanimelist.net' and re.match(rf'^/character/{character_id}(?:/|$)',page.path):
            verified=True
            source=mal_image(meta.image,'characters')
    except Exception:pass
    if not source and not verified:
        try:
            data=jikan(f'characters/{character_id}')
            if int(data.get('mal_id') or 0)==character_id:
                source=mal_image(((data.get('images') or {}).get('jpg') or {}).get('image_url'),'characters')
        except Exception:pass
    with LOCK:
        if len(MAL_PORTRAITS)>=4000:MAL_PORTRAITS.pop(next(iter(MAL_PORTRAITS)))
        MAL_PORTRAITS[character_id]=(time.time()+(86400 if source else 300),source)
    return source

def fill_mal_images(shiki,anime_id,result,warnings):
    """Fill only missing Shikimori images, matching MAL characters by ID."""
    if not result.get('poster'):
        try:
            data,_=mal_anime(shiki,anime_id)
            picture=data.get('main_picture') or {}
            jpg=((data.get('images') or {}).get('jpg') or {})
            result['poster']=mal_image(picture.get('large') or picture.get('medium') or jpg.get('large_image_url') or jpg.get('image_url'),'anime')
            if result['poster']:result['poster_source']='MyAnimeList'
        except Exception:warnings.append('poster')
    missing=[c for c in result['characters'] if not c.get('image')]
    if not missing:return
    try:rows=mal_characters(anime_id)
    except Exception:
        try:rows=jikan(f'anime/{anime_id}/characters')
        except Exception:rows=[]
    images={}
    for row in rows if isinstance(rows,list) else []:
        if not isinstance(row,dict):continue
        character=row.get('character') or {}
        if not isinstance(character,dict):continue
        source=mal_image(((character.get('images') or {}).get('jpg') or {}).get('image_url'),'characters')
        try:identifier=int(character.get('mal_id') or 0)
        except (ValueError,TypeError):continue
        if source:images[identifier]=source
    unresolved=list(dict.fromkeys(int(c['id']) for c in missing if not images.get(int(c['id']))))
    if unresolved:
        with ThreadPoolExecutor(max_workers=4) as pool:
            images.update(zip(unresolved,pool.map(mal_portrait,unresolved)))
    for character in missing:
        source=images.get(int(character['id']))
        if source:character.update(image=source,image_source='MyAnimeList')
    if any(not c.get('image') for c in missing):warnings.append('images')

def shiki_character_images(shiki,characters,provider='rip'):
    # REST character images can be missing placeholders; GraphQL contains current posters.
    ids=list(dict.fromkeys(int(c['id']) for c in characters))
    for start in range(0,len(ids),12):
        batch=ids[start:start+12]
        query='{ '+ ' '.join(f'c{i}: characters(ids: "{i}", limit: 1) {{ id poster {{ originalUrl mainUrl }} }}' for i in batch)+' }'
        response=shiki._http(provider,'POST','/api/graphql',json={'query':query},headers={'User-Agent':'Crunchy Local'},timeout=12)
        response.raise_for_status();payload=response.json().get('data') or {}
        for c in characters:
            found=payload.get('c'+str(c['id'])) or []
            if not found or int(found[0].get('id') or 0)!=int(c['id']):continue
            poster=found[0].get('poster') or {}
            source=image_url(poster.get('originalUrl') or poster.get('mainUrl'),shiki._host(provider))
            if source and '/uploads/poster/characters/' in source:c['image']=source

def shiki_poster(shiki,anime_id,provider):
    query='{ animes(ids: "%s", limit: 1) { id poster { originalUrl mainUrl } } }' % anime_id
    response=shiki._http(provider,'POST','/api/graphql',json={'query':query},headers={'User-Agent':'Crunchy Local'},timeout=12)
    response.raise_for_status()
    for anime in (response.json().get('data') or {}).get('animes') or []:
        if int(anime.get('id') or 0)!=anime_id:continue
        poster=anime.get('poster') or {}
        return image_url(poster.get('originalUrl') or poster.get('mainUrl'),shiki._host(provider))
    return ''

def anime_information(shiki, anime_id, language):
    if not 0<anime_id<=9999999:raise ValueError('Invalid anime ID')
    language='ru' if language=='ru' else 'en';key=(anime_id,language)
    with LOCK:
        cached=CACHE.get(key)
        if cached and cached[0]>time.time():return cached[1]
    warnings=[]
    if language=='ru':
        data,provider=shiki.public_anime(anime_id)
        base=shiki._host(provider)
        if provider!='rip':warnings.append('source')
        try:
            response=shiki._http(provider,'GET',f'/api/animes/{anime_id}/roles',headers={'User-Agent':'Crunchy Local'},timeout=12)
            response.raise_for_status();roles=response.json()
        except Exception:roles=[];warnings.append('characters')
        try:rating=shiki.shiki_score('one',anime_id)
        except Exception:rating=None
        result=normalize_shiki(data,roles,anime_id,rating,base)
        result['score_url']=url(f'/animes/{anime_id}',shiki._host('one'))
        try:
            shiki_character_images(shiki,result['characters'],provider)
        except Exception:
            warnings.append('characters')
            for c in result['characters']:
                if '/assets/globals/missing_' in c.get('image',''):c['image']=''
    else:
        data,_=mal_anime(shiki,anime_id)
        try:roles=mal_characters(anime_id)
        except Exception:
            try:roles=jikan(f'anime/{anime_id}/characters')
            except Exception:roles=[];warnings.append('characters')
        result=normalize_mal(data,roles,anime_id)
        result['character_source']='MyAnimeList'
    if language=='ru':
        result['poster']=image_url((data.get('image') or {}).get('original'),base)
        try:result['poster']=shiki_poster(shiki,anime_id,provider) or result['poster']
        except Exception:warnings.append('poster')
        try:fill_mal_images(shiki,anime_id,result,warnings)
        except Exception:warnings.append('images')
    else:
        result['poster']=url((data.get('main_picture') or {}).get('large') or
            (((data.get('images') or {}).get('jpg') or {}).get('large_image_url')) or '')
    result['warnings']=warnings
    with LOCK:
        if len(CACHE)>=2000:CACHE.pop(next(iter(CACHE)))
        CACHE[key]=(time.time()+(300 if warnings else 3600),result)
    return result

MATCHES = {}

def title_key(value):
    import unicodedata
    text=unicodedata.normalize('NFKD',str(value or '')).casefold()
    return ''.join(c for c in text if c.isalnum() and not unicodedata.combining(c))

def resolve_anime_id(shiki, series):
    """Resolve catalog gaps using exact alternative titles; never select a fuzzy sequel."""
    if series.get('mal_id'):return int(series['mal_id'])
    key=(series['id'],series.get('title'),series.get('year'))
    with LOCK:
        cached=MATCHES.get(key)
        if cached and cached[0]>time.time():return cached[1]
    expected=title_key(series.get('title'))
    client_id=(shiki.oauth_apps.get('mal') or {}).get('client_id')
    matches=[]
    if client_id:
        response=requests.get('https://api.myanimelist.net/v2/anime',
            params={'q':str(series.get('title') or '')[:64],'limit':20,'fields':'alternative_titles,start_date'},
            headers={'X-MAL-CLIENT-ID':client_id},timeout=12)
        response.raise_for_status()
        for row in response.json().get('data') or []:
            anime=row.get('node') or {};alternatives=anime.get('alternative_titles') or {}
            titles=[anime.get('title'),alternatives.get('en'),*(alternatives.get('synonyms') or [])]
            if expected and any(title_key(t)==expected for t in titles):matches.append(anime)
    if not matches:
        found=shiki.match_season('rip',series.get('title') or '',series.get('episodes') or 0)
        matches=[{'id':row['mal_id']} for row in found.get('items') or [] if row.get('score',0)>=100 and
            any(title_key(row.get(k))==expected for k in ('title','title_en','english_title'))]
    if len(matches)>1:
        same_year=[m for m in matches if str(m.get('start_date') or '')[:4]==str(series.get('year'))]
        matches=same_year
    identifier=int(matches[0]['id']) if len(matches)==1 else 0
    with LOCK:
        if len(MATCHES)>=2000:MATCHES.pop(next(iter(MATCHES)))
        MATCHES[key]=(time.time()+(86400 if identifier else 300),identifier)
    return identifier
