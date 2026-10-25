"""Cached public anime information from Shikimori RIP and MAL via Jikan."""
import re
import threading
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from curl_cffi import requests

CACHE = {}
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

def normalize_shiki(data, roles, anime_id, rating=None):
    if int(data.get('id') or 0)!=anime_id:raise ValueError('Anime ID mismatch')
    characters=[]
    for role in sorted(roles,key=lambda r:'Main' not in (r.get('roles') or [])):
        c=role.get('character') or {}
        if not c.get('id'):continue
        image=c.get('image') or {}
        characters.append({'id':c['id'],'name':c.get('russian') or c.get('name') or '',
            'image':url(image.get('original') or image.get('preview')),'url':url(c.get('url')),
            'role':(role.get('roles_russian') or role.get('roles') or [''])[0]})
    return {'id':anime_id,'source':'Shikimori','source_url':url(data.get('url') or f'/animes/{anime_id}'),
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

def rip_character_images(shiki,characters):
    # REST character images can be missing placeholders; GraphQL contains current posters.
    ids=list(dict.fromkeys(int(c['id']) for c in characters))
    for start in range(0,len(ids),12):
        batch=ids[start:start+12]
        query='{ '+ ' '.join(f'c{i}: characters(ids: "{i}", limit: 1) {{ id poster {{ originalUrl mainUrl }} }}' for i in batch)+' }'
        response=shiki._http('rip','POST','/api/graphql',json={'query':query},headers={'User-Agent':'Crunchy Local'},timeout=12)
        response.raise_for_status();payload=response.json().get('data') or {}
        for c in characters:
            found=payload.get('c'+str(c['id'])) or []
            if not found or int(found[0].get('id') or 0)!=int(c['id']):continue
            poster=found[0].get('poster') or {}
            source=url(poster.get('originalUrl') or poster.get('mainUrl'))
            if source and '/uploads/poster/characters/' in source:c['image']=source
    for c in characters:
        if '/assets/globals/missing_' in c.get('image',''):c['image']=''

def anime_information(shiki, anime_id, language):
    if not 0<anime_id<=9999999:raise ValueError('Invalid anime ID')
    language='ru' if language=='ru' else 'en';key=(anime_id,language)
    with LOCK:
        cached=CACHE.get(key)
        if cached and cached[0]>time.time():return cached[1]
    warnings=[]
    if language=='ru':
        response=shiki._http('rip','GET',f'/api/animes/{anime_id}',headers={'User-Agent':'Crunchy Local'},timeout=12)
        response.raise_for_status();data=response.json()
        try:
            response=shiki._http('rip','GET',f'/api/animes/{anime_id}/roles',headers={'User-Agent':'Crunchy Local'},timeout=12)
            response.raise_for_status();roles=response.json()
        except Exception:roles=[];warnings.append('characters')
        try:rating=shiki.shiki_score('rip',anime_id)
        except Exception:rating=None
        result=normalize_shiki(data,roles,anime_id,rating)
        try:rip_character_images(shiki,result['characters'])
        except Exception:
            warnings.append('characters')
            for c in result['characters']:
                if '/assets/globals/missing_' in c.get('image',''):c['image']=''
    else:
        client_id=(shiki.oauth_apps.get('mal') or {}).get('client_id')
        if client_id:
            fields='alternative_titles,start_date,synopsis,mean,genres,num_episodes,studios,status,media_type,average_episode_duration'
            response=requests.get(f'https://api.myanimelist.net/v2/anime/{anime_id}',params={'fields':fields},
                                  headers={'X-MAL-CLIENT-ID':client_id},timeout=12)
            response.raise_for_status();official=response.json()
            data={**official,'mal_id':official.get('id'),'title_english':(official.get('alternative_titles') or {}).get('en'),
                  'score':official.get('mean'),'episodes':official.get('num_episodes'),
                  'aired':{'from':official.get('start_date')},'type':official.get('media_type'),
                  'duration':f"{round(official['average_episode_duration']/60)} min." if official.get('average_episode_duration') else ''}
        else:data=jikan(f'anime/{anime_id}/full')
        try:roles=mal_characters(anime_id)
        except Exception:
            try:roles=jikan(f'anime/{anime_id}/characters')
            except Exception:roles=[];warnings.append('characters')
        result=normalize_mal(data,roles,anime_id)
        result['character_source']='MyAnimeList'
    if language=='ru':
        try:
            posters=shiki._rip_posters([anime_id]).get(anime_id,{})
            result['poster']=posters.get('originalUrl') or posters.get('mainUrl') or ''
        except Exception:result['poster']=''
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
