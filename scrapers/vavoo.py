# -*- coding: utf-8 -*-
import os
import re
import time
from resources.lib import multiquest, log
from resources.lib.control import addonProfile

SITE_ID       = 'vavoo'
SITE_NAME     = 'Vavoo'
SITE_DOMAIN   = 'vavoo.to'
TYPE          = 'both'
GLOBAL_SEARCH = False

_BASE_URL    = 'https://vavoo.to'
_URL_ITEM    = _BASE_URL + '/mediahubmx-item.json'
_URL_SOURCE  = _BASE_URL + '/mediahubmx-source.json'
_URL_RESOLVE = _BASE_URL + '/mediahubmx-resolve.json'
_URL_CATALOG = _BASE_URL + '/mediahubmx-catalog.json'
_PING_URL    = 'https://www.vavoo.tv/api/app/ping'
_APP_VERSION = '4.2.2'
_APP_PACKAGE = 'tv.vavoo.app'
_UA          = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) vavoo/4.2.2 Chrome/146.0.7680.166 Electron/41.1.0 Safari/537.36'
_SIG_TTL     = 840
_REGION      = 'XX'

_SIG_CACHE_FILE = os.path.join(addonProfile(), '.vavoo_sig_cache')
_UUID_FILE      = os.path.join(addonProfile(), '.vavoo_device_id')

_S_SEASONS  = '__vavoo_seasons__:'
_S_EPISODES = '__vavoo_episodes__:'

_TMDB_BASE  = 'https://api.themoviedb.org/3'
_TMDB_IMAGE = 'https://image.tmdb.org/t/p/w300'
_TMDB_KEY   = ''


def _lang_label(langs):
    if 'de' in langs: return ' (DE)'
    if 'en' in langs: return ' (EN)'
    return ''


def _quality_label(tag):
    t = (tag or '').upper()
    if '4K' in t or '2160' in t: return '4K'
    if '1080' in t:               return '1080p'
    if '720' in t:                return '720p'
    return tag or 'HD'


def _get_uuid():
    if os.path.isfile(_UUID_FILE):
        cached = open(_UUID_FILE).read().strip()
        if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$', cached, re.I):
            return cached
    b = bytearray(os.urandom(16))
    b[6] = (b[6] & 0x0f) | 0x40
    b[8] = (b[8] & 0x3f) | 0x80
    h = b.hex()
    uid = '%s-%s-%s-%s-%s' % (h[0:8], h[8:12], h[12:16], h[16:20], h[20:32])
    try:
        open(_UUID_FILE, 'w').write(uid + '\n')
    except Exception:
        pass
    return uid


def _get_sig():
    if os.path.isfile(_SIG_CACHE_FILE):
        age = time.time() - os.path.getmtime(_SIG_CACHE_FILE)
        if age < _SIG_TTL:
            sig = open(_SIG_CACHE_FILE).read().strip()
            if sig:
                return sig

    ts  = int(time.time() * 1000)
    uid = _get_uuid()
    ping_headers = {
        'User-Agent':      _UA,
        'Accept':          '*/*',
        'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
        'Origin':          'https://vavoo.to',
        'Referer':         'https://vavoo.to/',
        'Connection':      'keep-alive',
        'Content-Type':    'application/json',
    }
    ping_data = {
        'reason': 'app-focus', 'locale': 'de', 'theme': 'dark',
        'metadata': {
            'device':  {'type': 'desktop', 'uniqueId': uid},
            'os':      {'name': 'linux', 'version': 'x86_64', 'abis': ['x64'], 'host': 'localhost'},
            'app':     {'platform': 'electron'},
            'version': {'package': _APP_PACKAGE, 'binary': _APP_VERSION, 'js': _APP_VERSION},
        },
        'appFocusTime': 0, 'playerActive': False, 'playDuration': 0,
        'devMode': False, 'hasAddon': True, 'castConnected': False,
        'package': _APP_PACKAGE, 'version': _APP_VERSION, 'process': 'app',
        'firstAppStart': ts, 'lastAppStart': ts,
        'ipLocation': None, 'adblockEnabled': True,
        'proxy': {'supported': ['ss'], 'engine': 'Mu', 'enabled': False, 'autoServer': True},
        'iap': {'supported': False},
    }
    try:
        r = multiquest.post(_PING_URL, json=ping_data, headers=ping_headers, timeout=10)
        r.raise_for_status()
        sig = r.json().get('addonSig', '')
        if sig:
            try:
                open(_SIG_CACHE_FILE, 'w').write(sig)
            except Exception:
                pass
            return sig
    except Exception:
        log.error()

    if os.path.isfile(_SIG_CACHE_FILE):
        sig = open(_SIG_CACHE_FILE).read().strip()
        if sig:
            return sig

    return ''


def _base_payload():
    return {'language': 'de', 'region': _REGION, 'clientVersion': '3.1.0'}


def _api_headers(sig):
    return {
        'user-agent':           'MediaHubMX/2',
        'content-type':         'application/json; charset=utf-8',
        'accept-encoding':      'gzip',
        'mediahubmx-signature': sig,
    }


def _vavoo_post(url, payload, sig):
    ts = str(int(time.time() * 1000))
    try:
        r = multiquest.post(url + '?_t=' + ts, json=payload, headers=_api_headers(sig), timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        log.error()
        return None


def _resolve(stream_url, sig):
    payload = _base_payload()
    payload['url'] = stream_url
    data = _vavoo_post(_URL_RESOLVE, payload, sig)
    for _ in range(5):
        if isinstance(data, list) and data:
            return data[0].get('url', '')
        if isinstance(data, dict) and data.get('url'):
            return data['url']
        if isinstance(data, dict) and data.get('data', {}).get('url'):
            return data['data']['url']
        if isinstance(data, dict) and data.get('kind') == 'taskRequest':
            task_id     = data.get('id', '')
            task_data   = data.get('data', {})
            fetch_url   = task_data.get('url', '')
            params      = task_data.get('params', {})
            method      = params.get('method', 'GET').upper()
            req_headers = params.get('headers', {})
            try:
                if method == 'POST':
                    r = multiquest.post(fetch_url, headers=req_headers, timeout=15)
                else:
                    r = multiquest.get(fetch_url, headers=req_headers, timeout=15)
                resp_pl = _base_payload()
                resp_pl.update({
                    'kind': 'taskResponse', 'id': task_id,
                    'data': {'text': r.text, 'status': r.status_code},
                })
            except Exception as e:
                resp_pl = _base_payload()
                resp_pl.update({
                    'kind': 'taskResponse', 'id': task_id,
                    'data': {'error': str(e)},
                })
            data = _vavoo_post(_URL_RESOLVE, resp_pl, sig)
            continue
        break
    return ''


def _tmdb_get(path):
    if not _TMDB_KEY:
        return {}
    try:
        r = multiquest.get(
            _TMDB_BASE + path,
            params={'api_key': _TMDB_KEY, 'language': 'de-DE'},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def _parse_series_url(url):
    from urllib.parse import parse_qs
    qs    = parse_qs(url)
    imdb  = qs.get('imdb',  [''])[0]
    tmdb  = qs.get('tmdb',  [''])[0]
    title = qs.get('name',  [''])[0]
    return imdb, tmdb, title


def _series_ids(imdb, tmdb):
    ids = {}
    if imdb: ids['imdb_id'] = imdb
    if tmdb: ids['tmdb_id'] = str(tmdb)
    return ids


def _get_seasons(url):
    imdb, tmdb, title = _parse_series_url(url)
    ids = _series_ids(imdb, tmdb)
    if not ids:
        return []
    seasons = []
    if tmdb and _TMDB_KEY:
        data = _tmdb_get('/tv/%s' % tmdb)
        for s in (data.get('seasons') or []):
            num = s.get('season_number', 0)
            if num == 0:
                continue
            ep_count    = s.get('episode_count', 0)
            air_date    = s.get('air_date', '')
            plot        = s.get('overview', '') or ('%d Episoden' % ep_count if ep_count else '')
            poster_path = s.get('poster_path', '')
            thumb       = (_TMDB_IMAGE + poster_path) if poster_path else ''
            seasons.append({
                'title':       'Staffel %d' % num,
                'url':         _S_EPISODES + '%s&season=%d' % (url, num),
                'poster':      thumb,
                'year':        air_date[:4] if air_date else '',
                'plot':        plot,
                'mediatype':   'season',
                'next_func':   'load',
                'is_playable': False,
            })
        return seasons
    sig = _get_sig()
    if not sig:
        return []
    for s in range(1, 26):
        payload = _base_payload()
        payload.update({
            'type': 'series', 'ids': ids, 'name': title,
            'nameTranslations': {},
            'episode': {'season': s, 'episode': 1},
        })
        mirrors = _vavoo_post(_URL_SOURCE, payload, sig)
        if not (isinstance(mirrors, list) and mirrors):
            if s == 1:
                continue
            break
        seasons.append({
            'title':       'Staffel %d' % s,
            'url':         _S_EPISODES + '%s&season=%d' % (url, s),
            'mediatype':   'season',
            'next_func':   'load',
            'is_playable': False,
        })
    return seasons


def _get_episodes(encoded):
    from urllib.parse import parse_qs
    qs     = parse_qs(encoded)
    imdb   = qs.get('imdb',   [''])[0]
    tmdb   = qs.get('tmdb',   [''])[0]
    title  = qs.get('name',   [''])[0]
    season = int(qs.get('season', ['1'])[0])
    ids    = _series_ids(imdb, tmdb)
    if not ids:
        return []
    episodes = []
    if tmdb and _TMDB_KEY:
        data = _tmdb_get('/tv/%s/season/%d' % (tmdb, season))
        for ep in (data.get('episodes') or []):
            num      = ep.get('episode_number', 0)
            ep_title = ep.get('name', '') or ('E%02d' % num)
            plot     = ep.get('overview', '')
            air_date = ep.get('air_date', '')
            still    = ep.get('still_path', '')
            thumb    = (_TMDB_IMAGE + still) if still else ''
            label    = 'E%02d – %s' % (num, ep_title) if ep_title != ('E%02d' % num) else 'E%02d' % num
            episodes.append({
                'title':       label,
                'url':         '%s&episode=%d' % (encoded, num),
                'poster':      thumb,
                'year':        air_date[:4] if air_date else '',
                'plot':        plot,
                'mediatype':   'episode',
                'next_func':   'get_hosters',
                'is_playable': True,
            })
        return episodes
    sig = _get_sig()
    if not sig:
        return []
    for ep in range(1, 51):
        payload = _base_payload()
        payload.update({
            'type': 'series', 'ids': ids, 'name': title,
            'nameTranslations': {},
            'episode': {'season': season, 'episode': ep},
        })
        mirrors = _vavoo_post(_URL_SOURCE, payload, sig)
        if not (isinstance(mirrors, list) and mirrors):
            if ep == 1:
                continue
            break
        episodes.append({
            'title':       'E%02d' % ep,
            'url':         '%s&episode=%d' % (encoded, ep),
            'mediatype':   'episode',
            'next_func':   'get_hosters',
            'is_playable': True,
        })
    return episodes


def _catalog_items(data, base_url, sort):
    items = []
    for m in (data.get('items') or []):
        ids   = m.get('ids', {})
        imdb  = ids.get('imdb_id', '')
        tmdb  = str(ids.get('tmdb_id', ''))
        name  = m.get('name', '')
        thumb = (m.get('images') or {}).get('poster', '')
        yr    = str(m.get('releaseYear', ''))
        is_tv = m.get('type', '') == 'series'
        if imdb:
            item_url = 'imdb=%s&type=%s' % (imdb, 'series' if is_tv else 'movie')
        elif tmdb:
            item_url = 'tmdb=%s&type=%s' % (tmdb, 'series' if is_tv else 'movie')
        else:
            item_url = 'name=%s&type=%s' % (name, 'series' if is_tv else 'movie')
        desc = m.get('description', '')
        if is_tv:
            items.append({
                'title':       name,
                'url':         _S_SEASONS + item_url,
                'poster':      thumb,
                'year':        yr,
                'plot':        desc,
                'mediatype':   'tvshow',
                'next_func':   'load',
                'is_playable': False,
            })
        else:
            items.append({
                'title':       name,
                'url':         item_url,
                'poster':      thumb,
                'year':        yr,
                'plot':        desc,
                'mediatype':   'movie',
                'next_func':   'get_hosters',
                'is_playable': True,
            })
    next_cursor = data.get('nextCursor')
    if next_cursor:
        items.append({
            'title':       '[B]>>> Weiter[/B]',
            'url':         '%s|sort=%s|cursor=%s' % (base_url, sort, next_cursor),
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def _browse_entries(url):
    catalog_id = url
    cursor     = None
    sort       = 'popularity'
    if '|cursor=' in url:
        rest, cursor = url.split('|cursor=', 1)
        catalog_id, sort = rest.split('|sort=', 1) if '|sort=' in rest else (rest, sort)
    elif '|sort=' in url:
        catalog_id, sort = url.split('|sort=', 1)
    sig = _get_sig()
    if not sig:
        return []
    payload = _base_payload()
    payload.update({
        'catalogId': catalog_id,
        'id':        '',
        'adult':     False,
        'search':    '',
        'sort':      sort,
        'filter':    {},
        'cursor':    cursor,
    })
    data = _vavoo_post(_URL_CATALOG, payload, sig)
    if not data:
        return []
    return _catalog_items(data, catalog_id, sort)


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Trending Heute (Filme)',  'url': 'tmdb.movie|sort=trendingDay',   'next_func': 'load', 'is_playable': False},
            {'title': 'Trending Woche (Filme)',  'url': 'tmdb.movie|sort=trendingWeek',  'next_func': 'load', 'is_playable': False},
            {'title': 'Beliebt (Filme)',         'url': 'tmdb.movie|sort=popularity',    'next_func': 'load', 'is_playable': False},
            {'title': 'Trending Heute (Serien)', 'url': 'tmdb.series|sort=trendingDay',  'next_func': 'load', 'is_playable': False},
            {'title': 'Trending Woche (Serien)', 'url': 'tmdb.series|sort=trendingWeek', 'next_func': 'load', 'is_playable': False},
            {'title': 'Beliebt (Serien)',        'url': 'tmdb.series|sort=popularity',   'next_func': 'load', 'is_playable': False},
        ]
    if url.startswith(_S_SEASONS):
        return _get_seasons(url[len(_S_SEASONS):])
    if url.startswith(_S_EPISODES):
        return _get_episodes(url[len(_S_EPISODES):])
    return _browse_entries(url)


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if url:
        from urllib.parse import parse_qs
        qs = parse_qs(url)
        if not imdb:   imdb    = qs.get('imdb',    [''])[0]
        if not tmdb:   tmdb    = qs.get('tmdb',    [''])[0]
        if not title:  title   = qs.get('name',    [''])[0]
        if not season: season  = int(qs.get('season',  ['0'])[0])
        if not episode:episode = int(qs.get('episode', ['0'])[0])
        item_type = qs.get('type', ['movie'])[0]
    else:
        item_type = 'movie' if season == 0 else 'series'

    if not imdb and not tmdb:
        return []

    sig = _get_sig()
    if not sig:
        return []

    ids = _series_ids(imdb, tmdb)
    ep  = {} if season == 0 else {'season': season, 'episode': episode}

    item_payload = _base_payload()
    item_payload.update({
        'type': item_type, 'ids': ids, 'name': title,
        'nameTranslations': {}, 'episode': ep,
    })
    item_data = _vavoo_post(_URL_ITEM, item_payload, sig)
    if isinstance(item_data, dict):
        src_payload = dict(item_data)
        src_payload['language']      = 'de'
        src_payload['region']        = _REGION
        src_payload['clientVersion'] = '3.1.0'
        ids   = {**item_data.get('ids', {}), **ids}
        title = title or item_data.get('name', '')
    else:
        src_payload = dict(item_payload)

    types_to_try = ['series'] if season > 0 else (['movie', 'series'] if item_type == 'movie' else [item_type])

    mirrors = None
    for t in types_to_try:
        src_payload.update({'type': t, 'ids': ids, 'name': title,
                            'nameTranslations': {}, 'episode': ep})
        mirrors = _vavoo_post(_URL_SOURCE, src_payload, sig)
        if isinstance(mirrors, list) and mirrors:
            break
        mirrors = None

    if not isinstance(mirrors, list):
        return []

    _DIRECT_EXTS = ('.m3u8', '.mp4', '.mkv', '.ts', '.avi', '.mov', '.mpd')

    def _is_direct(u):
        from urllib.parse import urlparse
        path = urlparse(u.split('|')[0]).path.lower()
        return any(path.endswith(e) for e in _DIRECT_EXTS)

    result = []
    for m in mirrors:
        if not isinstance(m, dict):
            continue
        hurl = m.get('url', '')
        if not hurl:
            continue
        from urllib.parse import urlparse
        _host   = re.sub(r'^www\.', '', urlparse(hurl).hostname or '')
        _hname  = _host.split('.')[0].capitalize() if _host else (m.get('name') or SITE_NAME)
        name    = _hname + _lang_label(m.get('languages', []))
        quality = _quality_label(m.get('tag', ''))
        result.append((name, hurl, _is_direct(hurl), quality, ''))
    return result


def search(query='', params=None):
    return []
