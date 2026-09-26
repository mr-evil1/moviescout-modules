# -*- coding: utf-8 -*-
import json
import os
import re
import time
import unicodedata
import urllib.parse
import uuid

import xbmcaddon
import xbmcgui

from resources.lib import log, multiquest

SITE_ID       = 'plutotv'
SITE_NAME     = 'Pluto TV'
SITE_DOMAIN   = 'pluto.tv'
TYPE          = 'both'
GLOBAL_SEARCH = True
ACTIVE        = True


try:
    _ICON = xbmcaddon.Addon().getAddonInfo('icon')
except Exception:
    _ICON = ''

_UA          = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36')
_APP_VERSION = '10.11.4'
_REGION      = 'at'
_COUNTRY     = 'AT'
_PAGE_SIZE   = 50

_GQL_VIDEO    = 'https://pluto.tv/api/tn/video/graphql/'
_GQL_HUBS     = 'https://pluto.tv/api/tn/hubs/graphql/'
_PLAYOUT_BASE = 'https://ipv4.pluto.tv/api/tn/video/playout'
_IMAGE_BASE   = 'https://wwwimage-us.plutostatic.tv/thumbnails/photos/'

_PERSISTED_HASHES = {
    'browseNav':                 '115f7da5643358551d2ac07f18f72878559a8a8155de64bf3a3d0eaca9494cf3',
    'CollectionApiResponse':     '0f33cd7f1a1a95af404710c5554d9e46c9a6da05256297c3b7271cf09a31b636',
    'GetHybridCarouselData':     '410e9a46a5fb8a10e27a0cfd28b5e2df99ad3277dbd26a88da4592e7e0aefa05',
    'GetSearchVideoCarousel':    '8cd1256a8d4c65ebff9a8fe308462bf8f7d5323178032dd2563caa2f70e5dee0',
    'GetVODContent':             '83cd9a7dd069413377771f9d9dc822d7ed5eacecf67c1cad09a2008fbe6d49f0',
    'PaginatedFullEpisodesData': 'b617f32ac555297f2875080c2f22a24d64490f3529d58bbd169a30d87848d86f',
    'ChannelsMany':              'ec82d7e84d8400d8af7a77290207ca69cc31f411ca97787541ae8b10e7eec6e5',
    'channelCategories':         '5a9d1efaaa793d2b5799ec3764128838b5fe584aecf4a85b53740b1f79492e8d',
    'StreamingUrl':              'd2210e84a51ed4a4382c15720a7366ee955d6354ee76039f58a34ecf274134b7',
}

_LIVE_HASHES    = dict(_PERSISTED_HASHES)
_GQL_FAILED_OPS = set()
_DISCOVERY_COOLDOWN_SEC = 300


def _hash_cache_path():
    try:
        import xbmcvfs
        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
        return os.path.join(profile, 'plutotv_hashes.json')
    except Exception:
        return ''


def _load_hash_cache():
    path = _hash_cache_path()
    if not path:
        return
    try:
        if os.path.isfile(path):
            with open(path) as f:
                cached = json.load(f)
            hashes = {k: v for k, v in cached.items() if k != '_ts'}
            _LIVE_HASHES.update(hashes)
            log.log('[PlutoTV] Hashes aus Cache geladen: %d' % len(hashes))
    except Exception as e:
        log.log('[PlutoTV] Hash-Cache Ladefehler: %s' % e, log.LOGWARNING)


def _last_discovery_ts():
    path = _hash_cache_path()
    if not path or not os.path.isfile(path):
        return 0
    try:
        with open(path) as f:
            return json.load(f).get('_ts', 0)
    except Exception:
        return 0


def _save_hash_cache():
    path = _hash_cache_path()
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = dict(_LIVE_HASHES)
        data['_ts'] = time.time()
        with open(path, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        log.log('[PlutoTV] Hash-Cache Speicherfehler: %s' % e, log.LOGWARNING)


def _discover_hashes():
    log.log('[PlutoTV] Starte Hash-Discovery von pluto.tv')
    body, status = _http_get('https://pluto.tv/', timeout=20)
    if not body:
        log.log('[PlutoTV] Discovery: Hauptseite nicht erreichbar', log.LOGWARNING)
        return False

    js_urls = re.findall(r'src=["\']([^"\']*\.js[^"\']*)["\']', body)
    js_urls = ['https://pluto.tv' + u if u.startswith('/') else u for u in js_urls]
    log.log('[PlutoTV] Discovery: %d JS-Bundles gefunden' % len(js_urls))

    op_names = set(_PERSISTED_HASHES.keys())
    found    = {}
    hex64    = re.compile(r'[0-9a-f]{64}')

    for url in js_urls:
        chunk, _ = _http_get(url, timeout=30)
        if not chunk or len(chunk) < 5000:
            continue
        for m in hex64.finditer(chunk):
            window = chunk[max(0, m.start() - 400): m.start() + 400]
            for op in op_names:
                if op in window and op not in found:
                    found[op] = m.group(0)
        if found:
            log.log('[PlutoTV] Discovery in %s: %s' % (url.split('/')[-1], list(found.keys())))
        if len(found) >= len(op_names):
            break

    if found:
        _LIVE_HASHES.update(found)
        _save_hash_cache()
        log.log('[PlutoTV] Discovery abgeschlossen: %d/%d Hashes aktualisiert' % (len(found), len(op_names)))
        return True
    log.log('[PlutoTV] Discovery: keine Hashes gefunden', log.LOGWARNING)
    return False


_load_hash_cache()

_REQUEST_SOURCE = {
    'browseNav':                 'browse-nav',
    'CollectionApiResponse':     'collection',
    'GetHybridCarouselData':     'poster-grid-data-at',
    'GetSearchVideoCarousel':    'search-video-carousel',
    'GetVODContent':             'search-vod-content',
    'PaginatedFullEpisodesData': 'full-episodes-pagination',
    'ChannelsMany':              'live-tv-channels',
    'channelCategories':         'channel-categories-request',
    'StreamingUrl':              'streaming-url-request',
}

_ANON_PARAMS = {
    'userRegistrationCountry': _COUNTRY,
    'userState':               'ANONYMOUS',
    'packageCode':             'NEW_FREE_PACKAGE',
    'userProfileType':         'ADULT',
    'billingVendor':           'cbscomp',
}

_BOOT_BASE     = 'https://boot.pluto.tv/v4/start'
_WV_LICENSE    = 'https://service-concierge.clusters.pluto.tv/v1/wv'
_DEVICE_CACHE  = [None]
_SESSION_CACHE = {'id': None, 'exp': 0}
_JWT_CACHE     = {'token': '', 'exp': 0}


def _get_device_id():
    if _DEVICE_CACHE[0]:
        return _DEVICE_CACHE[0]
    try:
        import xbmcvfs
        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
        path = os.path.join(profile, 'plutotv_device.json')
        if os.path.isfile(path):
            with open(path) as f:
                d = json.load(f).get('device_id', '')
            if d:
                _DEVICE_CACHE[0] = d
                return d
        d = str(uuid.uuid4())
        os.makedirs(profile, exist_ok=True)
        with open(path, 'w') as f:
            json.dump({'device_id': d}, f)
        _DEVICE_CACHE[0] = d
        return d
    except Exception:
        d = str(uuid.uuid4())
        _DEVICE_CACHE[0] = d
        return d


def _headers(extra=None):
    h = {
        'User-Agent':               _UA,
        'Accept':                   'application/json',
        'Content-Type':             'application/json',
        'Accept-Language':          'de-AT,de;q=0.9',
        'Origin':                   'https://pluto.tv',
        'Referer':                  'https://pluto.tv/',
        'apollo-require-preflight': 'true',
    }
    if extra:
        for k, v in extra.items():
            if v is None:
                h.pop(k, None)
            else:
                h[k] = v
    return h


def _http_get(url, params=None, timeout=15, extra_headers=None):
    try:
        r = multiquest.get(url, params=params, headers=_headers(extra_headers), timeout=timeout)
        log.log('[PlutoTV] HTTP %d %s' % (r.status_code, url.split('?')[0]))
        return r.text, r.status_code
    except Exception as e:
        log.log('[PlutoTV] HTTP Fehler %s | url=%s' % (e, url.split('?')[0]), log.LOGWARNING)
        return '', 0


def _stream_cookie():
    return '; '.join([
        'ptv_device_id=%s' % _get_device_id(),
        'ptv_session_id=%s' % _get_session_id(),
        'CBS_ST=ANONYMOUS',
        'CBS_RR=%s' % _COUNTRY,
        'ptv_drm_capabilities=widevine%3AL3',
        'ptv_client_dnt=false',
    ])


def _gql(base, operation, variables, _retry=False, auth=''):
    params = {
        'operationName': operation,
        'variables':     json.dumps(variables),
    }
    h = _LIVE_HASHES.get(operation)
    if h:
        params['extensions'] = json.dumps({'tnPersistedDocumentHash': h})
    extra = {}
    if operation == 'StreamingUrl':
        extra['Cookie'] = _stream_cookie()
    elif auth:
        extra['Authorization'] = 'Bearer %s' % auth
    rs = _REQUEST_SOURCE.get(operation)
    if rs:
        if operation in ('GetSearchVideoCarousel', 'GetVODContent'):
            q = re.sub(r'[\r\n]+', ' ', str(variables.get('query', '')))
            q = q.encode('latin-1', 'ignore').decode('latin-1')
            rs = '%s-%s' % (rs, q)
        extra['request-source'] = rs
    extra['x-apollo-operation-name'] = operation
    body, status = _http_get(base, params=params, extra_headers=extra)
    if not body or status >= 400:
        log.log('[PlutoTV] GQL %s HTTP %d leer=%s' % (operation, status, not body), log.LOGWARNING)
        return None
    try:
        data = json.loads(body)
    except Exception as e:
        log.log('[PlutoTV] GQL %s JSON Fehler: %s | body[:200]=%s' % (operation, e, body[:200]), log.LOGWARNING)
        return None
    if operation == 'StreamingUrl':
        su = ((data.get('data') or {}).get('streamingUrl') or {})
        log.log('[PlutoTV] StreamingUrl success=%s paths=%d invalidIp=%s isInVPN=%s' % (
            su.get('success'), len(su.get('stitcherPaths') or []), su.get('invalidIp'), su.get('isInVPN')))
    errors = data.get('errors')
    if errors:
        log.log('[PlutoTV] GQL %s Fehler: %s' % (operation, errors), log.LOGWARNING)
        is_server_error = any(
            (e.get('extensions', {}).get('code') == 'INTERNAL_SERVER_ERROR')
            for e in errors if isinstance(e, dict)
        )
        if is_server_error and not _retry and operation not in _GQL_FAILED_OPS:
            age = time.time() - _last_discovery_ts()
            if age > _DISCOVERY_COOLDOWN_SEC:
                if _discover_hashes():
                    return _gql(base, operation, variables, _retry=True, auth=auth)
            _GQL_FAILED_OPS.add(operation)
        if not (data.get('data') or {}):
            return None
    return data


def _image(path, w=300):
    if not path:
        return _ICON
    if path.startswith('http'):
        return path
    return '%sw%d-q80/%s?format=webp' % (_IMAGE_BASE, w, path)


_GDPR_CONSENT = (
    'CQrDBAAQrDBAAFUABAENCxFgAP_gAEPgACiQMSsR_C5dbWlj-TZ3abskeYxP1nhi4sAxAgaAkiAF'
    'SLKUIAQEx2EQJAyIICACGRIAqhDBIQNkEAAUQUAAIIAFKABMYAyU4BIIIABAgBMBAAJACEACgogg'
    'AAAIAgAfBAQgmAqEYdKMWFQAwIgCAkAgIAAAAIAFAQMABAEIZAKAERAEwggAEQgAgAIBAAAAQBgIA'
    'AEBAgAAACEABAAAAAQAEAABAAAAEAQACCAAoAAAAAAAAiAAAAAEAACgAAAAAAAAAAAAAAAAIMBMR_C5'
    'dbWlj-TBXYbskOYxf1ngC4sAxAAaAoiAFSLKUIAQA12EQJEiIICAAGRAAohBBIAEoEAgEQEABAI'
    'AFKABsAAwQ4BIIAABAgBMBQABAAEACgoggAAAIAAAeBAQgiQiEYNKEWFQAQIAiAkAgIIAAAIAEA'
    'QMABAEIYAIAEBAEwgACEAgAgAIBAAAAABgIEAABAAAAAKEABAAAAAQAEAARAAAAEAQAACAAoAAEAA'
    'CAQiAAAAAEAACgAAAAAAAAAAEAQJABAYyOgAgMZJQAQGMlIAIDGQA.IMSsR_C5dbWlj-TZ3abskeY'
    'xf1nhi4sAxAgaAsiAFSLKUIAQE12EQJEyIICACGRIAqhDBIQNsEAgUQUABIIAFKABsYAyU4BIIIAB'
    'AgBMBQAJACEACkoggAAAIAgAfBAQgmQqEYdKMWFQAwIgiAkAgIIAAAIAFAQMABAEIZAKAERAEwggC'
    'EQgAgAIBAAAAQBgIEAEBAgAAAKEABAAAAAQAEAARAAAAEAQACCAAoAAEAACAQiAAAAAEAACgAAAAAAAA'
    'AAEAAAAAIAA.f_wACHwAAAAA'
)


def _get_session_id():
    now = time.time()
    if _SESSION_CACHE['id'] and _SESSION_CACHE['exp'] > now:
        return _SESSION_CACHE['id']
    sid = str(uuid.uuid4())
    _SESSION_CACHE['id'] = sid
    _SESSION_CACHE['exp'] = now + 3600
    return sid


def _get_session_jwt():
    now = time.time()
    if _JWT_CACHE['token'] and _JWT_CACHE['exp'] > now + 60:
        return _JWT_CACHE['token']
    did = _get_device_id()
    sid = _SESSION_CACHE.get('id') or str(uuid.uuid4())
    params = {
        'appVersion':              _APP_VERSION,
        'deviceVersion':           _APP_VERSION,
        'clientID':                did,
        'deviceId':                did,
        'deviceType':              'web',
        'deviceMake':              'Chrome',
        'deviceModel':             'web',
        'appName':                 'web',
        'marketingRegion':         _COUNTRY,
        'userState':               'ANONYMOUS',
        'userRegistrationCountry': _COUNTRY,
        'drmCapabilities':         'widevine:L3',
        'gdpr':                    '1',
        'gdprConsent':             _GDPR_CONSENT,
        'sid':                     sid,
        'serverSideAds':           'true',
        'clientModelNumber':       '1.0.0',
        'language':                'de',
    }
    body, status = _http_get(_BOOT_BASE, params=params, timeout=15)
    if not body or status >= 400:
        log.log('[PlutoTV] Boot JWT Fehler HTTP %d' % status, log.LOGWARNING)
        return ''
    try:
        data = json.loads(body)
        sp = data.get('stitcherParams') or ''
        paln = ''
        if isinstance(sp, str) and sp:
            paln = dict(urllib.parse.parse_qsl(sp)).get('paln', '')
        elif isinstance(sp, dict):
            paln = sp.get('paln', '') or sp.get('jwt', '')
        jwt = paln or data.get('sessionToken') or data.get('sessionJwt') or ''
        if jwt:
            _JWT_CACHE['token'] = jwt
            _JWT_CACHE['exp'] = now + 82800
            _SESSION_CACHE['id'] = sid
            _SESSION_CACHE['exp'] = now + 82800
            log.log('[PlutoTV] Boot JWT erhalten (len=%d, quelle=%s)' % (
                len(jwt), 'paln' if paln else 'sessionToken'))
            return jwt
        log.log('[PlutoTV] Boot JWT: kein Token | keys=%s' % list(data.keys()), log.LOGWARNING)
    except Exception as e:
        log.log('[PlutoTV] Boot JWT JSON Fehler: %s' % e, log.LOGWARNING)
    return ''


def _license_key(jwt=''):
    hdrs = [
        ('Content-Type', 'application/octet-stream'),
        ('User-Agent',   _UA),
        ('Origin',       'https://pluto.tv'),
        ('Referer',      'https://pluto.tv/'),
    ]
    if jwt:
        hdrs.insert(0, ('Authorization', 'Bearer %s' % jwt))
    hdr = '&'.join('%s=%s' % (k, urllib.parse.quote(v, safe='')) for k, v in hdrs)
    return '%s|%s|R{SSM}|' % (_WV_LICENSE, hdr)


def _build_stream_url(stitch_path, jwt=''):
    params_dict = {
        'includeExtendedEvents': 'true',
        'gdpr':                  '1',
        'gdprConsent':           _GDPR_CONSENT,
        '_fw_gdpr_consent':      _GDPR_CONSENT,
    }
    if jwt:
        params_dict['paln'] = jwt
    else:
        params_dict['sid'] = _get_session_id()
    params = urllib.parse.urlencode(params_dict)
    return '%s%s?%s' % (_PLAYOUT_BASE, stitch_path, params)


def _get_stitch_path(content_id, content_type='vod'):
    jwt = _get_session_jwt()
    drm_modes = [('widevine', 'L3'), ('none', 'none')]
    best_hls = ''
    for drm_type, drm_level in drm_modes:
        data = _gql(_GQL_VIDEO, 'StreamingUrl', {
            'params': {
                'appVersion':  _APP_VERSION,
                'contentId':   content_id,
                'contentType': content_type,
                'drm':         drm_type,
                'drmLevel':    drm_level,
                'streamType':  'stitcher',
            }
        }, auth=jwt)
        if not data:
            continue
        paths = (data.get('data', {}).get('streamingUrl', {}).get('stitcherPaths') or [])
        hls = next((p['path'] for p in paths if p.get('type') == 'hls'), '')
        mpd = next((p['path'] for p in paths if p.get('type') == 'mpd'), '')
        log.log('[PlutoTV] stitch contentId=%s drm=%s paths=%d hls=%s mpd=%s' % (
            content_id, drm_type, len(paths), bool(hls), bool(mpd)))
        if mpd:
            return mpd, 'mpd'
        if hls and not best_hls:
            best_hls = hls
    return best_hls, 'hls' if best_hls else ''


def _browse_nav():
    data = _gql(_GQL_HUBS, 'browseNav', {'extraParams': {}})
    if not data:
        return [], []
    nav = (data.get('data', {}).get('browseNav', {}).get('globalMenu') or {})
    return nav.get('movieBrowseNav', []), nav.get('showBrowseNav', [])


def _collection(slug):
    data = _gql(_GQL_HUBS, 'CollectionApiResponse', {
        'slug':            slug,
        'isChildCategory': False,
        'extraParams':     {},
    })
    if not data:
        return []
    return (data.get('data', {}).get('collection', {}).get('hubCarousels') or [])


def _carousel_data(token, carousel_id='', carousel_type='', model='universalContent',
                   position=0, title='', href='', start=0, rows=_PAGE_SIZE):
    if carousel_type == 'grid':
        params = {
            'carouselPresentationStyle': 'grid',
            'carouselType':              carousel_type,
            'isContentHighlightEnabled': True,
            'model':                     model,
            'position':                  str(position),
            'title':                     title,
            'start':                     str(start),
            'rows':                      str(rows),
        }
    else:
        params = {
            'carouselId':                carousel_id,
            'carouselPresentationStyle': 'default',
            'carouselType':              carousel_type,
            'isContentHighlightEnabled': True,
            'isSubscriber':              False,
            'model':                     model,
            'packageCode':               'NEW_FREE_PACKAGE',
            'title':                     title,
            'start':                     str(start),
            'rows':                      str(rows),
        }
        if href:
            params['href'] = href
    data = _gql(_GQL_HUBS, 'GetHybridCarouselData', {
        'token':          urllib.parse.quote(token, safe=''),
        'carouselParams': params,
    })
    if not data:
        log.log('[PlutoTV] _carousel_data keine Antwort für carouselId=%s' % carousel_id, log.LOGWARNING)
        return [], 0
    result = ((data.get('data') or {}).get('carouselData') or {}).get('result') or {}
    if not result:
        log.log('[PlutoTV] _carousel_data result leer | keys=%s' % list(data.get('data', {}).keys()), log.LOGWARNING)
        return [], 0
    items = result.get('data') or []
    total = int(result.get('total') or 0)
    log.log('[PlutoTV] _carousel_data carouselId=%s raw=%d total=%d' % (carousel_id, len(items), total))
    return items, total


def _channels_many(category_slug=None, start=0, rows=500):
    p = dict(_ANON_PARAMS,
             dma=0,
             platformType='Desktop',
             showListing=True,
             hideChannelsWithoutListings=True,
             rows=rows,
             numOfUpcomingListings=1,
             filterLockedChannels=False,
             start=start)
    if category_slug:
        p['channelCategorySlug'] = category_slug
    data = _gql(_GQL_VIDEO, 'ChannelsMany', {'params': p})
    if not data:
        return []
    return (data.get('data', {}).get('channels', {}).get('channels') or [])


def _channel_categories():
    data = _gql(_GQL_VIDEO, 'channelCategories', {
        'params': dict(_ANON_PARAMS, vendorCode=''),
    })
    if not data:
        return []
    return (data.get('data', {}).get('channelCategories', {}).get('channelCategories') or [])


def _paginated_episodes(show_id, season_num, begin=0):
    data = _gql(_GQL_HUBS, 'PaginatedFullEpisodesData', {
        'showId':    str(show_id),
        'seasonNum': str(season_num),
        'begin':     begin,
        'withApiRaw': False,
    })
    if not data:
        return [], []
    fe = (data.get('data', {}).get('fullEpisodes') or {})
    return fe.get('availableSeasonNums', []), fe.get('episodes', [])


def _norm(text):
    t = unicodedata.normalize('NFKD', str(text or '')).casefold()
    return ''.join(ch for ch in t if ch.isalnum())


def _title_matches(query, title):
    q = _norm(query)
    if not q:
        return True
    t = _norm(title)
    if q in t:
        return True
    words = [w for w in (_norm(x) for x in str(query).split()) if w]
    return len(words) > 1 and all(w in t for w in words)


def _search_results(query):
    seen = set()
    vod  = []
    data = _gql(_GQL_HUBS, 'GetVODContent', {'query': query})
    if data:
        raw = ((data.get('data') or {}).get('searchVODContent') or {}).get('data') or []
        for e in raw:
            eid = e.get('movieId') or e.get('id')
            if not eid or eid in seen:
                continue
            seen.add(eid)
            vod.append(e)
    hits = [e for e in vod if _title_matches(query, e.get('title') or e.get('movieTitle') or '')]
    if hits:
        vod = hits
    live = []
    data = _gql(_GQL_HUBS, 'GetSearchVideoCarousel', {'query': query})
    if data:
        raw = ((data.get('data') or {}).get('searchVideoCarousel') or {}).get('data') or []
        for e in raw:
            cid = e.get('id')
            if not cid or cid in seen or e.get('contentType') != 'channel':
                continue
            if _title_matches(query, e.get('channelName') or ''):
                seen.add(cid)
                live.append(e)
    log.log('[PlutoTV] Suche vod=%d live=%d' % (len(vod), len(live)))
    return vod + live



_REST_VOD_BASE = 'https://api.pluto.tv/v3/vod/categories'
_REST_VOD_CACHE = {'data': None, 'ts': 0}
_REST_VOD_TTL   = 1800


def _rest_vod_all():
    now = time.time()
    if _REST_VOD_CACHE['data'] is not None and (now - _REST_VOD_CACHE['ts']) < _REST_VOD_TTL:
        return _REST_VOD_CACHE['data']
    params = {
        'includeItems':            'true',
        'deviceType':              'web',
        'userState':               'ANONYMOUS',
        'userRegistrationCountry': _COUNTRY,
        'userProfileType':         'ADULT',
        'packageCode':             'NEW_FREE_PACKAGE',
        'offset':                  0,
        'limit':                   500,
    }
    body, status = _http_get(_REST_VOD_BASE, params=params, timeout=20,
                             extra_headers={'Content-Type': None})
    if not body or status >= 400:
        log.log('[PlutoTV] REST VOD Fehler HTTP %d' % status, log.LOGWARNING)
        return []
    try:
        cats = json.loads(body).get('categories', [])
        _REST_VOD_CACHE['data'] = cats
        _REST_VOD_CACHE['ts']   = now
        log.log('[PlutoTV] REST VOD: %d Kategorien' % len(cats))
        return cats
    except Exception as e:
        log.log('[PlutoTV] REST VOD JSON Fehler: %s' % e, log.LOGWARNING)
        return []


def _item_from_rest(entry):
    itype = (entry.get('type') or '').lower()
    name  = entry.get('name') or entry.get('title') or ''
    desc  = entry.get('description') or entry.get('summary') or ''
    cid   = entry.get('_id') or ''
    if not cid or not name:
        return None
    images = entry.get('covers') or entry.get('images') or []
    thumb  = ''
    for img in images:
        if isinstance(img, dict):
            thumb = img.get('url') or img.get('path') or ''
            if thumb:
                break
    if not thumb:
        poster = entry.get('poster') or {}
        if isinstance(poster, dict):
            thumb = poster.get('path') or ''
        elif isinstance(poster, str):
            thumb = poster
    if thumb and not thumb.startswith('http'):
        thumb = _image(thumb)

    if itype == 'movie':
        return {
            'title':       name,
            'url':         'movie:%s' % cid,
            'poster':      thumb, 'icon': thumb, 'fanart': thumb,
            'plot':        desc,  'mediatype': 'movie',
            'is_playable': True,  'next_func': 'get_hosters',
        }
    if itype in ('series', 'show'):
        return {
            'title':       name,
            'url':         'show:%s' % cid,
            'poster':      thumb, 'icon': thumb, 'fanart': thumb,
            'plot':        desc,  'mediatype': 'tvshow',
            'is_playable': False, 'next_func': 'showSeasons',
        }
    return None


def _rest_carousel_fallback(carousel_id, kind=''):
    cats  = _rest_vod_all()
    if not cats:
        return []
    slug = carousel_id.lower().replace('-', '').replace('_', '').replace(' ', '')

    best_cat  = None
    best_score = 0
    for cat in cats:
        cat_id   = (cat.get('_id') or '').lower().replace('-', '').replace('_', '').replace(' ', '')
        cat_name = (cat.get('name') or '').lower().replace('-', '').replace('_', '').replace(' ', '')
        cat_slug = (cat.get('slug') or '').lower().replace('-', '').replace('_', '').replace(' ', '')
        score = 0
        if slug == cat_id or slug == cat_name or slug == cat_slug:
            score = 3
        elif slug in cat_id or slug in cat_name or slug in cat_slug:
            score = 2
        elif cat_id in slug or cat_name in slug or cat_slug in slug:
            score = 1
        if score > best_score:
            best_score = score
            best_cat   = cat

    if not best_cat:
        log.log('[PlutoTV] REST Fallback: keine Kategorie für carouselId=%s' % carousel_id, log.LOGWARNING)
        return []

    raw_items = best_cat.get('items') or best_cat.get('content') or []
    items = []
    for entry in raw_items:
        item = _item_from_rest(entry)
        if item:
            if kind == 'movie' and item.get('mediatype') != 'movie':
                continue
            if kind == 'show' and item.get('mediatype') != 'tvshow':
                continue
            items.append(item)
    log.log('[PlutoTV] REST Fallback carouselId=%s → cat=%s count=%d' % (
        carousel_id, best_cat.get('name'), len(items)))
    return items

def _item_from_entry(entry):
    ct    = entry.get('contentType', '')
    title = (entry.get('title') or entry.get('movieTitle') or
             entry.get('showTitle') or entry.get('channelName') or '')
    thumb = entry.get('thumb') or entry.get('thumbLandscape') or ''
    hero  = entry.get('hero') or thumb
    desc  = entry.get('description') or ''
    year  = ''
    ad = entry.get('airDate') or entry.get('airDateISO') or ''
    if ad:
        m = re.search(r'(\d{4})', str(ad))
        if m:
            year = m.group(1)

    if ct == 'movie':
        cid = entry.get('movieId') or entry.get('contentId') or entry.get('id') or ''
        if not cid:
            return None
        return {
            'title':       title,
            'url':         'movie:%s' % cid,
            'poster':      thumb,
            'icon':        thumb,
            'fanart':      hero,
            'plot':        desc,
            'year':        year,
            'mediatype':   'movie',
            'is_playable': True,
            'next_func':   'get_hosters',
        }

    if ct == 'show':
        show_id = entry.get('id') or ''
        if not show_id:
            return None
        return {
            'title':       title,
            'url':         'show:%s' % show_id,
            'poster':      thumb,
            'icon':        thumb,
            'fanart':      hero,
            'plot':        desc,
            'mediatype':   'tvshow',
            'is_playable': False,
            'next_func':   'showSeasons',
        }

    if ct == 'channel':
        cid = entry.get('id') or ''
        if not cid:
            return None
        logo = entry.get('logo') or entry.get('filePathLogo') or thumb
        name = entry.get('channelName') or title
        now  = entry.get('title') or ''
        if now and name != now:
            desc = '[B]%s[/B]\n%s' % (now, desc)
        return {
            'title':       '[COLOR gold][B]%s[/B][/COLOR]' % name,
            'url':         'live:%s' % cid,
            'poster':      logo,
            'icon':        logo,
            'fanart':      thumb,
            'plot':        desc,
            'mediatype':   'video',
            'is_playable': True,
            'next_func':   'get_hosters',
        }

    log.log('[PlutoTV] _item_from_entry unbekannter contentType=%s title=%s' % (ct, title))
    return None


def load(url='', params=None):
    return [
        {
            'title':       'Filme',
            'url':         'movies',
            'plot':        'Alle Filme auf Pluto TV (AVOD, kostenlos).',
            'is_playable': False,
            'next_func':   'showGenres',
            'poster':      _ICON,
            'icon':        _ICON,
        },
        {
            'title':       'Serien',
            'url':         'shows',
            'plot':        'Alle Serien auf Pluto TV.',
            'is_playable': False,
            'next_func':   'showGenres',
            'poster':      _ICON,
            'icon':        _ICON,
        },
        {
            'title':       'Live TV',
            'url':         'live',
            'plot':        'Alle Live TV Kanäle (ungrupiert).',
            'is_playable': False,
            'next_func':   'get_live',
            'poster':      _ICON,
            'icon':        _ICON,
        },
        {
            'title':       'Live TV nach Ländern',
            'url':         '',
            'plot':        'Live TV Kanäle nach Land und Untergruppe gruppiert.',
            'is_playable': False,
            'next_func':   'get_live_channels',
            'poster':      _ICON,
            'icon':        _ICON,
        },
        {
            'title':       'Suche',
            'url':         '',
            'plot':        'Pluto TV durchsuchen.',
            'is_playable': False,
            'next_func':   'search',
            'poster':      _ICON,
            'icon':        _ICON,
        },
    ]


def showGenres(url='', params=None):
    movie_nav, show_nav = _browse_nav()
    is_movie = (url == 'movies')
    nav = movie_nav if is_movie else show_nav
    kind = 'movie' if is_movie else 'show'
    items = []
    for entry in nav:
        label = entry.get('label') or ''
        slug  = entry.get('slug') or ''
        if not slug:
            continue
        items.append({
            'title':       label,
            'url':         'genre:%s:%s' % (kind, slug),
            'plot':        label,
            'is_playable': False,
            'next_func':   'showCarousels',
            'poster':      _ICON,
            'icon':        _ICON,
        })
    log.log('[PlutoTV] showGenres kind=%s count=%d' % (kind, len(items)))
    return items


def showCarousels(url='', params=None):
    if not url.startswith('genre:'):
        return []
    rest  = url[6:]
    kind  = rest.split(':')[0]
    slug  = rest.split(':', 1)[1] if ':' in rest else ''
    carousels = _collection(slug)
    items = []
    for c in carousels:
        token       = c.get('token') or ''
        title       = c.get('title') or ''
        carousel_id = c.get('carouselId') or ''
        c_type      = c.get('carouselType') or ''
        model       = c.get('model') or 'universalContent'
        position    = c.get('position') or 0
        if not token or not title:
            continue
        encoded_token = urllib.parse.quote(token, safe='')
        href          = c.get('href') or ''
        encoded_href  = urllib.parse.quote(href, safe='')
        encoded_title = urllib.parse.quote(title, safe='')
        items.append({
            'title':       title,
            'url':         'carousel:%s:%s:%s:%s:%s:%s:%s:%s' % (
                           kind, encoded_token, carousel_id, c_type,
                           model, position, encoded_href, encoded_title),
            'plot':        title,
            'is_playable': False,
            'next_func':   'showEntries',
            'poster':      _ICON,
            'icon':        _ICON,
        })
    log.log('[PlutoTV] showCarousels slug=%s count=%d' % (slug, len(items)))
    return items


def showEntries(url='', params=None):
    if not url.startswith('carousel:'):
        return []
    parts = url[9:].split(':', 8)
    if len(parts) < 4:
        return []
    _kind       = parts[0]
    token       = urllib.parse.unquote(parts[1])
    carousel_id = parts[2]
    c_type      = parts[3]
    model       = parts[4] if len(parts) > 4 else 'universalContent'
    position    = parts[5] if len(parts) > 5 else '0'
    href        = urllib.parse.unquote(parts[6]) if len(parts) > 6 else ''
    title       = urllib.parse.unquote(parts[7]) if len(parts) > 7 else ''
    start       = int(parts[8]) if len(parts) > 8 else 0
    entries, total = _carousel_data(token, carousel_id=carousel_id, carousel_type=c_type,
                                    model=model, position=position, title=title, href=href,
                                    start=start, rows=_PAGE_SIZE)
    if not entries:
        return _rest_carousel_fallback(carousel_id, kind=_kind)
    items = []
    skipped = []
    for e in entries:
        item = _item_from_entry(e)
        if item:
            items.append(item)
        else:
            skipped.append(e.get('contentType', '?'))
    if skipped:
        log.log('[PlutoTV] showEntries carouselId=%s übersprungen contentTypes=%s' % (carousel_id, skipped), log.LOGWARNING)
    log.log('[PlutoTV] showEntries carouselId=%s count=%d (raw=%d total=%d start=%d)' % (
        carousel_id, len(items), len(entries), total, start))
    next_start = start + _PAGE_SIZE
    if total > next_start:
        encoded_token = urllib.parse.quote(token, safe='')
        encoded_href  = urllib.parse.quote(href, safe='')
        encoded_title = urllib.parse.quote(title, safe='')
        next_url = 'carousel:%s:%s:%s:%s:%s:%s:%s:%s:%d' % (
            _kind, encoded_token, carousel_id, c_type,
            model, position, encoded_href, encoded_title, next_start)
        remaining = total - next_start
        items.append({
            'title':       '>> Weiter (noch %d)' % remaining,
            'url':         next_url,
            'plot':        'Nächste Seite laden',
            'is_playable': False,
            'next_func':   'showEntries',
        })
    return items


def showSeasons(url='', params=None):
    if not url.startswith('show:'):
        return []
    show_id = url[5:].split(':')[0]
    season_nums, _ = _paginated_episodes(show_id, '1')
    if not season_nums:
        return showEpisodes('show:%s:1' % show_id)
    if len(season_nums) == 1:
        return showEpisodes('show:%s:%s' % (show_id, season_nums[0]))
    items = []
    for s in season_nums:
        items.append({
            'title':       'Staffel %s' % s,
            'url':         'show:%s:%s' % (show_id, s),
            'plot':        'Staffel %s' % s,
            'mediatype':   'season',
            'season':      int(s) if str(s).isdigit() else 1,
            'is_playable': False,
            'next_func':   'showEpisodes',
            'poster':      _ICON,
            'icon':        _ICON,
        })
    log.log('[PlutoTV] showSeasons showId=%s seasons=%s' % (show_id, season_nums))
    return items


def showEpisodes(url='', params=None):
    if not url.startswith('show:'):
        return []
    parts      = url[5:].split(':')
    show_id    = parts[0]
    season_num = parts[1] if len(parts) > 1 else '1'
    _, episodes = _paginated_episodes(show_id, season_num)
    items = []
    for ep in episodes:
        cid = ep.get('contentId') or ''
        if not cid:
            continue
        title   = ep.get('title') or ep.get('label') or ''
        ep_num  = ep.get('episodeNum') or 0
        s_num   = ep.get('seasonNum') or season_num
        thumb   = ep.get('thumb') or ''
        items.append({
            'title':       title,
            'url':         'episode:%s' % cid,
            'poster':      thumb,
            'icon':        thumb,
            'fanart':      thumb,
            'plot':        ep.get('description') or ep.get('shortDescription') or '',
            'mediatype':   'episode',
            'season':      int(s_num)  if str(s_num).isdigit()  else 1,
            'episode':     int(ep_num) if str(ep_num).isdigit() else 0,
            'is_playable': True,
            'next_func':   'get_hosters',
        })
    log.log('[PlutoTV] showEpisodes showId=%s season=%s count=%d' % (show_id, season_num, len(items)))
    return items


_LIVE_FEED_URL   = 'https://i.mjh.nz/PlutoTV/.channels.json.gz'
_LIVE_FEED_CACHE = {'data': None, 'ts': 0}
_LIVE_FEED_TTL   = 300
_LIVE_ALL        = '__all__'


def _live_feed():
    import gzip
    now = time.time()
    if _LIVE_FEED_CACHE['data'] is not None and (now - _LIVE_FEED_CACHE['ts']) < _LIVE_FEED_TTL:
        return _LIVE_FEED_CACHE['data']
    try:
        req = urllib.request.Request(
            _LIVE_FEED_URL,
            headers={'User-Agent': _UA, 'Accept-Encoding': 'gzip'},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
        try:
            body = gzip.decompress(raw).decode('utf-8', 'replace')
        except Exception:
            body = raw.decode('utf-8', 'replace')
        data = json.loads(body)
        _LIVE_FEED_CACHE['data'] = data
        _LIVE_FEED_CACHE['ts']   = now
        log.log('[PlutoTV] Live-Feed geladen: %d Regionen' % len(data.get('regions', {})))
        return data
    except Exception as e:
        log.log('[PlutoTV] Live-Feed Fehler: %s' % e, log.LOGWARNING)
        return {}


def _live_channel_items(channels, group_filter=None):
    items = []
    for ch_id, ch in sorted(channels.items(),
                             key=lambda x: (x[1].get('chno', 0), x[1].get('name', ''))):
        ch_group = ch.get('group') or ''
        if group_filter is not None and ch_group != group_filter:
            continue
        name   = ch.get('name') or ch_id
        logo   = ch.get('logo') or _ICON
        art    = ch.get('art') or logo
        chno   = ch.get('chno') or ''
        desc   = ch.get('description') or ''
        region = ch.get('_region_name', '')
        label  = '%s | %s' % (chno, name) if chno else name
        plot   = '[B]%s — %s[/B]\n%s' % (region, ch_group, desc) if region else desc
        pb_id  = ch.get('id') or ch_id
        items.append({
            'title':       label,
            'url':         'live:%s' % pb_id,
            'poster':      logo,
            'icon':        logo,
            'fanart':      art,
            'plot':        plot,
            'mediatype':   'video',
            'is_playable': True,
            'next_func':   'get_hosters',
        })
    return items


def get_live_channels(url='', params=None):
    data    = _live_feed()
    regions = data.get('regions') or {}

    all_channels = {}
    for code, region in regions.items():
        for ch_id, ch in (region.get('channels') or {}).items():
            ch['_region_name'] = region.get('name', code)
            all_channels[ch_id] = ch

    parts = (url or '').split(':', 2)
    sub   = parts[0] if parts else ''

    if not sub:
        items = []
        all_count = len(all_channels)
        items.append({
            'title':       'Alle (%d)' % all_count,
            'url':         'groups:%s' % _LIVE_ALL,
            'poster':      _ICON,
            'icon':        _ICON,
            'plot':        'Alle Live-Kanäle aller Länder.',
            'is_playable': False,
            'next_func':   'get_live_channels',
        })
        for code in sorted(regions, key=lambda c: regions[c].get('name', c)):
            region = regions[code]
            count  = len(region.get('channels') or {})
            items.append({
                'title':       '%s (%d)' % (region.get('name', code), count),
                'url':         'groups:%s' % code,
                'poster':      _ICON,
                'icon':        _ICON,
                'plot':        region.get('name', code),
                'is_playable': False,
                'next_func':   'get_live_channels',
            })
        log.log('[PlutoTV] get_live_channels Länder: %d' % len(items))
        return items

    if sub == 'groups':
        region_code = parts[1] if len(parts) > 1 else _LIVE_ALL
        if region_code == _LIVE_ALL:
            channels = all_channels
        else:
            channels = dict(regions.get(region_code, {}).get('channels') or {})
            for ch in channels.values():
                ch['_region_name'] = regions.get(region_code, {}).get('name', region_code)

        groups = {}
        for ch in channels.values():
            g = ch.get('group') or 'Sonstige'
            groups[g] = groups.get(g, 0) + 1

        total = sum(groups.values())
        items = []
        items.append({
            'title':       'Alle (%d)' % total,
            'url':         'channels:%s:%s' % (region_code, _LIVE_ALL),
            'poster':      _ICON,
            'icon':        _ICON,
            'plot':        'Alle Kanäle dieses Landes.',
            'is_playable': False,
            'next_func':   'get_live_channels',
        })
        for g in sorted(groups):
            items.append({
                'title':       '%s (%d)' % (g, groups[g]),
                'url':         'channels:%s:%s' % (region_code, g),
                'poster':      _ICON,
                'icon':        _ICON,
                'plot':        g,
                'is_playable': False,
                'next_func':   'get_live_channels',
            })
        log.log('[PlutoTV] get_live_channels Gruppen region=%s: %d' % (region_code, len(items)))
        return items

    if sub == 'channels':
        region_code  = parts[1] if len(parts) > 1 else _LIVE_ALL
        group_filter = parts[2] if len(parts) > 2 else _LIVE_ALL
        if region_code == _LIVE_ALL:
            channels = all_channels
        else:
            channels = dict(regions.get(region_code, {}).get('channels') or {})
            for ch in channels.values():
                ch['_region_name'] = regions.get(region_code, {}).get('name', region_code)
        flt   = None if group_filter == _LIVE_ALL else group_filter
        items = _live_channel_items(channels, group_filter=flt)
        log.log('[PlutoTV] get_live_channels Kanäle region=%s group=%s count=%d' % (
            region_code, group_filter, len(items)))
        return items

    log.log('[PlutoTV] get_live_channels unbekannter sub=%s' % sub, log.LOGWARNING)
    return []


def get_live(url='', params=None):
    channels = _channels_many()
    log.log('[PlutoTV] get_live raw channels=%d' % len(channels))
    items = []
    seen  = set()
    no_id = 0
    for ch in channels:
        ch_id = (ch.get('videoContentId') or
                 (ch.get('currentListing') or [{}])[0].get('contentCANVideo', {}).get('contentId') or '')
        if not ch_id:
            no_id += 1
            continue
        if ch_id in seen:
            continue
        seen.add(ch_id)
        name  = ch.get('channelName') or ch_id
        logo  = (ch.get('resolvedfilePathLogoSelected') or
                 ch.get('resolvedfilePathLogo') or
                 _image(ch.get('filePathLogo') or ''))
        listing = (ch.get('currentListing') or [{}])[0]
        plot  = listing.get('description') or ch.get('description') or ''
        now_playing = listing.get('title') or ''
        if now_playing:
            plot = '[B]%s[/B]\n%s' % (now_playing, plot)
        items.append({
            'title':       name,
            'url':         'live:%s' % ch_id,
            'poster':      logo,
            'icon':        logo,
            'fanart':      logo,
            'plot':        plot,
            'mediatype':   'video',
            'is_playable': True,
            'next_func':   'get_hosters',
        })
    log.log('[PlutoTV] get_live count=%d (kein contentId: %d)' % (len(items), no_id))
    return items


def search(query='', params=None, url=''):
    if isinstance(params, dict):
        query = query or params.get('query') or params.get('keyword') or ''
    if not query and isinstance(url, str) and url and url.lower() not in ('search', 'suche'):
        query = url
    if not query:
        try:
            r = xbmcgui.Dialog().input('Pluto TV Suche')
            if r:
                query = r.strip()
        except Exception:
            pass
    if not query:
        return []
    log.log('[PlutoTV] Suche: "%s"' % query)
    entries = _search_results(query)
    items   = []
    for e in entries:
        item = _item_from_entry(e)
        if item:
            items.append(item)
    log.log('[PlutoTV] Suche "%s" → %d Treffer' % (query, len(items)))
    return items


def _year_of(entry):
    ad = entry.get('premiereDate') or entry.get('airDate') or entry.get('airDateISO') or ''
    m = re.search(r'(\d{4})', str(ad))
    return m.group(1) if m else ''


def _scout_resolve(title, year, season, episode):
    if not title:
        return ''
    data = _gql(_GQL_HUBS, 'GetVODContent', {'query': title})
    if not data:
        return ''
    raw = ((data.get('data') or {}).get('searchVODContent') or {}).get('data') or []
    hits = [e for e in raw if _title_matches(title, e.get('title') or '')]
    if not hits:
        return ''
    if year:
        by_year = [e for e in hits if _year_of(e) == str(year)]
        if by_year:
            hits = by_year
    movies = [e for e in hits if e.get('contentType') == 'movie']
    if movies and not season and not episode:
        return 'movie:%s' % (movies[0].get('movieId') or movies[0].get('id'))
    shows = [e for e in hits if e.get('contentType') == 'show']
    if not shows:
        return ''
    show_id = shows[0].get('id')
    s_num = str(season or 1)
    _, episodes = _paginated_episodes(show_id, s_num)
    for ep in episodes:
        if str(ep.get('episodeNum') or '') == str(episode):
            cid = ep.get('contentId') or ''
            if cid:
                return 'episode:%s' % cid
    if episodes and not episode:
        cid = episodes[0].get('contentId') or ''
        if cid:
            return 'episode:%s' % cid
    return ''


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    u = str(url or '')
    if not u.startswith(('live:', 'movie:', 'episode:')):
        resolved = _scout_resolve(title, year, season, episode)
        if not resolved:
            log.log('[PlutoTV] Scout: kein Treffer für title=%s year=%s season=%s episode=%s' %
                    (title, year, season, episode), log.LOGWARNING)
            return []
        log.log('[PlutoTV] Scout: title=%s -> %s' % (title, resolved))
        u = resolved
    log.log('[PlutoTV] get_hosters url=%s' % u)

    jwt = _get_session_jwt()

    if u.startswith('live:'):
        ch_id = u[5:]
        if not ch_id:
            return []
        stitch, mtype = _get_stitch_path(ch_id, content_type='channel')
        if not stitch:
            stitch = '/v2/stitch/dash/channel/%s/main.mpd' % ch_id
            mtype  = 'mpd'
        stream   = _build_stream_url(stitch, jwt=jwt)
        if jwt:
            stream += '|Authorization=Bearer %s' % jwt
        drm_info = {'manifest_type': mtype}
        if mtype == 'mpd':
            drm_info['license_type'] = 'com.widevine.alpha'
            drm_info['license_key']  = _license_key(jwt)
        log.log('[PlutoTV] Live stream=%s manifest_type=%s' % (stream[:80], mtype))
        return [['PlutoTV Live', stream, drm_info, 'Live', '', 'plutotv']]

    if u.startswith('movie:') or u.startswith('episode:'):
        prefix = 'movie' if u.startswith('movie:') else 'episode'
        cid = u.split(':', 1)[1]
        if not cid:
            return []
        stitch, mtype = _get_stitch_path(cid, content_type='vod')
        if not stitch:
            stitch = '/v2/stitch/dash/episode/%s/main.mpd' % cid
            mtype  = 'mpd'
            log.log('[PlutoTV] VOD: Standardpfad episode für contentId=%s' % cid)
        stream   = _build_stream_url(stitch, jwt=jwt)
        if jwt:
            stream += '|Authorization=Bearer %s' % jwt
        drm_info = {'manifest_type': mtype}
        if mtype == 'mpd':
            drm_info['license_type'] = 'com.widevine.alpha'
            drm_info['license_key']  = _license_key(jwt)
        log.log('[PlutoTV] VOD stream=%s manifest_type=%s' % (stream[:80], mtype))
        label = 'PlutoTV Film' if prefix == 'movie' else 'PlutoTV Episode'
        return [[label, stream, drm_info, '', '', 'plutotv']]

    log.log('[PlutoTV] get_hosters unbekanntes Schema: %s' % u, log.LOGWARNING)
    return []
