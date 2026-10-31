"""Official MyAnimeList API; account tokens live in encrypted browser cookies."""
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from curl_cffi import requests

OAUTH_LOCK = threading.RLock()
STATUSES = {'planned':'plan_to_watch', 'watching':'watching', 'completed':'completed', 'on_hold':'on_hold', 'dropped':'dropped'}

class MALBridge:
    def __init__(self, root, shiki, account=None, oauth_states=None, caches=None):
        path = Path(os.environ.get('CRUNCHY_LOCAL_OAUTH_APPS_PATH') or Path(root)/'oauth_apps.json')
        self.app = (json.loads(path.read_text()).get('mal') or {}) if path.exists() else {}
        self.account = dict(account or {})
        self.shiki = shiki
        self.states = oauth_states if oauth_states is not None else {}
        self.cache = caches if caches is not None else {}
        self.lock = self.cache.setdefault('mal_lock', threading.RLock())
        self.catalog_version=self.cache.get('catalog_version','')

    def status(self):
        return {'configured':bool(self.app.get('client_id')), 'connected':bool(self.account.get('refresh_token') and self.account.get('user_id')), 'name':self.account.get('name',''), 'user_id':self.account.get('user_id'), 'error':self.account.get('error',''), 'host':'https://myanimelist.net'}

    def start(self, redirect, sid):
        if not self.app.get('client_id'):raise RuntimeError('OAuth-приложение MAL не настроено.')
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        with OAUTH_LOCK:
            for key,value in list(self.states.items()):
                if value['until'] < time.time():self.states.pop(key,None)
            if len(self.states)>=512:raise RuntimeError('Слишком много попыток входа. Подождите 5 минут.')
            self.states[state]={'redirect':redirect,'sid':sid,'verifier':verifier,'until':time.time()+600}
        return 'https://myanimelist.net/v1/oauth2/authorize?'+urlencode({'response_type':'code','client_id':self.app['client_id'],'redirect_uri':redirect,'state':state,'code_challenge':verifier,'code_challenge_method':'plain'})

    def _token(self, fields):
        payload={'client_id':self.app.get('client_id',''),**fields}
        if self.app.get('client_secret'):payload['client_secret']=self.app['client_secret']
        try:
            response=requests.post('https://myanimelist.net/v1/oauth2/token',data=payload,timeout=25,allow_redirects=False)
            if response.status_code!=200:raise RuntimeError('MAL отклонил вход. Проверьте настройки приложения или войдите повторно.')
            result=response.json()
            return {'access_token':result['access_token'],'refresh_token':result['refresh_token'],'expires_at':time.time()+int(result.get('expires_in',3600))}
        except RuntimeError:raise
        except Exception:raise RuntimeError('Не удалось связаться с MAL. Повторите попытку позже.') from None

    def callback(self, state, code, error, sid):
        with OAUTH_LOCK:
            pending=self.states.get(state)
            if not pending or pending['until']<time.time() or pending['sid']!=sid:raise RuntimeError('Время входа в MAL истекло. Начните заново.')
            self.states.pop(state)
        if error or not code:
            self.account['error']='Доступ к списку не был разрешён.'
            return
        token=self._token({'grant_type':'authorization_code','code':code,'redirect_uri':pending['redirect'],'code_verifier':pending['verifier']})
        previous=self.account.copy()
        self.account.update(token)
        try:
            user=self._request('GET','/users/@me')
            self.account.update(user_id=int(user['id']),name=user.get('name') or 'MAL',error='')
            self.cache.pop('mal_list',None)
        except Exception:
            self.account=previous
            raise

    def disconnect(self):
        self.account={}
        self.cache.pop('mal_list',None)
        self.cache.pop('mal_refresh',None)
        return self.status()

    def _access(self, force=False):
        with self.lock:
            if not self.account.get('refresh_token'):raise RuntimeError('Подключите MAL в настройках.')
            refreshed=self.cache.get('mal_refresh')
            if not force and refreshed and refreshed[0]==self.account['refresh_token'] and refreshed[1]['expires_at']>time.time()+60:self.account.update(refreshed[1])
            if not force and self.account.get('access_token') and self.account.get('expires_at',0)>time.time()+60:return self.account['access_token']
            old=self.account['refresh_token']
            token=self._token({'grant_type':'refresh_token','refresh_token':old})
            self.account.update(token)
            self.cache['mal_refresh']=(old,token)
            return token['access_token']

    def _request(self, method, path, data=None):
        if not path.startswith('/') or path.startswith('//'):raise RuntimeError('Некорректный запрос MAL.')
        headers={'Authorization':'Bearer '+self._access(), 'Accept':'application/json'}
        try:
            response=requests.request(method,'https://api.myanimelist.net/v2'+path,headers=headers,data=data,timeout=25,allow_redirects=False)
            if response.status_code==401:
                self.account['expires_at']=0
                headers['Authorization']='Bearer '+self._access(force=True)
                response=requests.request(method,'https://api.myanimelist.net/v2'+path,headers=headers,data=data,timeout=25,allow_redirects=False)
            if response.status_code>=300:raise RuntimeError('MAL: HTTP %s'%response.status_code)
            return response.json()
        except RuntimeError:raise
        except Exception:raise RuntimeError('Не удалось связаться с MAL. Повторите попытку позже.') from None

    @staticmethod
    def normalize(value):
        return {'status':'rewatching' if value.get('is_rewatching') else {v:k for k,v in STATUSES.items()}.get(value.get('status'),'planned'), 'episodes':int(value.get('num_episodes_watched') or 0),'score':int(value.get('score') or 0),'updated_at':value.get('updated_at','')}

    @staticmethod
    def valid_id(anime_id):
        if not isinstance(anime_id,int) or isinstance(anime_id,bool) or not 0<anime_id<=9999999:raise RuntimeError('Некорректный ID аниме.')

    def rate(self, anime_id):
        self.valid_id(anime_id)
        value=self._request('GET','/anime/%s?fields=my_list_status'%anime_id).get('my_list_status')
        return self.normalize(value) if value else None

    def list(self, force=False):
        with self.lock:
            cached=self.cache.get('mal_list')
            if not force and cached and cached[0]>time.time() and len(cached)>2 and cached[2]==self.catalog_version:return cached[1]
            rows=[]
            path='/users/@me/animelist?'+urlencode({'fields':'list_status,num_episodes,alternative_titles,mean','limit':1000,'sort':'list_updated_at','nsfw':'true'})
            seen=set()
            while path:
                if path in seen or len(seen)>=100:raise RuntimeError('MAL вернул некорректную пагинацию списка.')
                seen.add(path)
                data=self._request('GET',path)
                rows.extend(data.get('data',[]))
                next_url=data.get('paging',{}).get('next')
                path=''
                if next_url:
                    url=urlsplit(next_url)
                    if url.scheme!='https' or url.netloc!='api.myanimelist.net' or url.path!='/v2/users/@me/animelist':raise RuntimeError('MAL вернул некорректную пагинацию списка.')
                    path='/users/@me/animelist?'+url.query
            nodes={int(row['node']['id']):row['node'] for row in rows}
            posters=self.shiki.anime_posters(list(nodes),{i:(a.get('main_picture') or {}).get('large') or (a.get('main_picture') or {}).get('medium') for i,a in nodes.items()})
            metadata=self.shiki._anime_details('one',list(nodes))
            matches=self.shiki.catalog_matches({i:{'id':i,'name':a.get('title'),'english':(a.get('alternative_titles') or {}).get('en') or (metadata.get(i) or {}).get('english'),
                'synonyms':[*((a.get('alternative_titles') or {}).get('synonyms') or []),
                            (metadata.get(i) or {}).get('english'),(metadata.get(i) or {}).get('name'),*((metadata.get(i) or {}).get('synonyms') or [])]} for i,a in nodes.items()})
            items=[]
            for row in rows:
                anime=row['node'];anime_id=int(anime['id']);title=anime.get('alternative_titles',{}).get('en') or (metadata.get(anime_id) or {}).get('english') or anime['title']
                match=matches.get(anime_id,{})
                artwork=posters.get(anime_id,{})
                items.append({'mal_id':anime_id,'crunchy_id':match.get('crunchy_id'),'season_id':match.get('season_id'),'season_title':match.get('season_title'),'title':title,'title_en':title,'english_title':match.get('season_title') or title,'total_episodes':anime.get('num_episodes') or 0,'rate':self.normalize(row.get('list_status',{})),'mal_score':anime.get('mean'),'poster':artwork.get('originalUrl') or artwork.get('mainUrl') or artwork.get('malUrl') or (anime.get('main_picture') or {}).get('large') or (anime.get('main_picture') or {}).get('medium') or '', 'poster_fallback':artwork.get('mainUrl',''),'catalog_poster':artwork.get('malUrl') or (anime.get('main_picture') or {}).get('large') or (anime.get('main_picture') or {}).get('medium') or '', 'url':'https://myanimelist.net/anime/%s'%anime_id})
            result={'items':items,'total':len(items),'available':sum(bool(x['crunchy_id']) for x in items)}
            self.cache['mal_list']=(time.time()+300,result,self.catalog_version)
            return result

    def update_rate(self, anime_id, fields):
        self.valid_id(anime_id)
        data={}
        if 'status' in fields:
            status=fields['status']
            if status not in (*STATUSES,'rewatching'):raise RuntimeError('Некорректный статус просмотра.')
            data['status']=STATUSES.get(status,'watching')
            data['is_rewatching']='true' if status=='rewatching' else 'false'
        for source,target,maximum in [('episodes','num_watched_episodes',10000),('score','score',10)]:
            if source in fields:
                value=fields[source]
                if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=maximum:raise RuntimeError('Некорректное число серий.' if source=='episodes' else 'Оценка должна быть от 0 до 10.')
                data[target]=value
        if not data:raise RuntimeError('Нет изменений для синхронизации.')
        result=self.normalize(self._request('PATCH','/anime/%s/my_list_status'%anime_id,data))
        self.cache.pop('mal_list',None)
        return result


def sync_rates(shiki, mal, providers, anime_id, fields, automatic=False):
    if not isinstance(providers,list) or not providers or any(p not in ('one','rip','mal') for p in providers):raise RuntimeError('Выберите сервисы синхронизации.')
    MALBridge.valid_id(anime_id)
    if automatic:
        count=fields.get('episodes')
        if isinstance(count,bool) or not isinstance(count,int) or not 0<=count<=10000:raise RuntimeError('Некорректное число серий.')
    results, errors={},{}
    for provider in dict.fromkeys(providers):
        try:
            update={key:value for key,value in fields.items() if key in ('status','episodes','score')}
            if automatic:
                existing=mal.rate(anime_id) if provider=='mal' else shiki.rate(provider,anime_id)
                existing=existing or {}
                update={'episodes':max(int(existing.get('episodes') or 0),int(fields.get('episodes') or 0)), 'status':existing.get('status') or 'watching'}
                if update['status']=='planned':update['status']='watching'
            results[provider]=mal.update_rate(anime_id,update) if provider=='mal' else shiki.update_rate(provider,anime_id,update)
        except Exception as exc:errors[provider]=str(exc)
    return {'results':results,'errors':errors}
