import hashlib
import json
import re
import time
import uuid

from resources.lib import multiquest, log

SITE_ID       = 'joynfree'
SITE_NAME     = 'JoynFree'
SITE_DOMAIN   = 'www.joyn.de'
TYPE          = 'both'
GLOBAL_SEARCH = True

_SUPPORTED = {'DE', 'AT', 'CH'}
_COUNTRY   = None
_TENANT    = None


def _detect_country():
    global _COUNTRY, _TENANT
    if _COUNTRY is not None:
        return
    try:
        r = multiquest.get('http://ip-api.com/json/?fields=status,countryCode', timeout=5)
        data = json.loads(r.text)
        cc = data.get('countryCode', 'DE') if data.get('status') == 'success' else 'DE'
    except Exception:
        cc = 'DE'
    if cc not in _SUPPORTED:
        cc = 'DE'
    _COUNTRY = cc
    _TENANT  = 'JOYN_AT' if cc == 'AT' else 'JOYN_CH' if cc == 'CH' else 'JOYN'
    log.log('[Joyn] detected country=%s tenant=%s' % (_COUNTRY, _TENANT))
_BASE_URL  = 'https://www.joyn.de'
_GQL_URL   = 'https://api.joyn.de/graphql'
_AUTH_URL  = 'https://auth.joyn.de/auth/anonymous'
_AUTH_REF  = 'https://auth.joyn.de/auth/refresh'
_ENT_URL   = 'https://entitlements-service-alb.prd.platform.s.joyn.de/api/user/entitlement-token'
_PBK_URL   = 'https://api.vod-prd.s.joyn.de/v1'
_LIC_URL   = 'https://widevine-proxy.prd.platform.s.joyn.de/proxy'
_API_KEY   = '4f0fd9f18abbe3cf0e87fdb556bc39c8'
_UA        = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/126.0.0.0 Safari/537.36')
_SIG_KEY   = (
    'MzU0MzM3MzgzMzM4MzMzNjM1NDMzNzM4MzYzNDM2MzYzNTQzMz'
    'czODM2MzYzMzM4MzIzNjM1NDMzNzM4MzMzMDM2MzQzNTM5MzU0'
    'MzM3MzgzMzM5MzMzNTMyMzQzNTQzMzczODM2MzUzMzM5MzU0Mz'
    'M3MzgzMzM4MzMzMjMzNDYzNTQzMzczODM2MzYzMzMzMzM0NDMz'
    'NDIzNTQzMzczODMzMzgzNjM2MzMzNQ=='
)

_H = {
    'NAVIGATION'     : '818622ff5afe143664241034ba0c537650ec9a2eeae4d568830b47d8de605b7e',
    'LANDINGPAGE'    : 'b71b3871aebfe266b63a4bf7daaa35645e17be2469b850265ba75146fa60affc',
    'LANDINGBLOCKS'  : '1655591f83b0dc1508ad4d52c5f37f72d410f48ad08c3e5f2de8622f86a21c68',
    'CHANNEL'        : 'f61159391eed95487997fe2a9eab1fe25198e12b35f6206f60eb9f477187fab3',
    'COLLECTION'     : 'bf3a273afa54de5a577de160cc82e55824b0e92c87c8bb0b470087eedaeb7c18',
    'COMPILATION'    : 'f4103ea8a4ebecaf873e439029ea8e8e478031596097808596e7053b5618cae4',
    'MOVIES'         : '9ae6bcd8c45a5e350438d1cc415a022fe053e938c93438509f60ae3abb425fa7',
    'SEASONS'        : 'e867452d17ef36e5c077db5cdcad7563a9aebede497c24ac8fae779723bc462d',
    'EPISODES'       : 'ee2396bb1b7c9f800e5cefd0b341271b7213fceb4ebe18d5a30dab41d703009f',
    'RECENT_EP'      : '165df4f031673746960ae3b36a86d3a6249257b26551dd1407fde75056689305',
    'SEARCH'         : 'bb2bab6cbe17321d7eddd5006e7f40765faedd79790b193a59d83f4640694856',
}

_CATEGORY_LANES = {'StandardLane', 'CollectionLane', 'FeaturedLane', 'LiveLane'}

_Q_LIVE = (
    '{ liveStreams(filterLivestreamsTypes: [EVENT,LINEAR,ON_DEMAND], first: 5000, offset: 0) '
    '{ agofCode, brand { brandCode, id, '
    'livestream { logo { url(profile: "nextgen-web-artlogo-183x75") } } }, '
    'epgEvents { endDate, program { '
    '... on Movie { __typename, title, id, licenseTypes, path, video { id }, '
    'posterImage: image(type: PRIMARY) { url(profile: "nextgen-web-primarycut-1920x1080") } } '
    '... on Episode { __typename, title, id, licenseTypes, number, path, video { id }, '
    'season { number }, series { id, title }, '
    'posterImage: image(type: PRIMARY) { url(profile: "nextgen-web-primarycut-1920x1080") } } '
    '... on EpgEntry { __typename, title, secondaryTitle } '
    '}, startDate }, id, liveStreamGroups, markings, quality, title, type } }'
)

_FREE_LT   = {'AVOD', 'FVOD'}
_PAGE_SIZE = 48
_GQL_FIRST = 1000

_TCACHE    = {}
_DEVICE_ID = None


def _device_id():
    global _DEVICE_ID
    if _DEVICE_ID is None:
        _DEVICE_ID = str(uuid.uuid4())
    return _DEVICE_ID


def _base_hdr():
    return {
        'User-Agent':      _UA,
        'Accept':          'application/json',
        'Origin':          _BASE_URL,
        'Referer':         _BASE_URL + '/',
        'Accept-Language': 'de-DE,de;q=0.9',
    }


def _post_json(url, payload, headers=None, timeout=15):
    hdrs = headers or _base_hdr()
    log.log('[Joyn] POST %s | payload=%s' % (url, str(payload)[:300]))
    safe_hdrs = {k: (v[:40] + '…' if k == 'Authorization' and len(v) > 43 else v)
                 for k, v in hdrs.items()}
    log.log('[Joyn] POST headers=%s' % safe_hdrs)
    try:
        r = multiquest.post(url, json=payload, headers=hdrs, timeout=timeout)
        log.log('[Joyn] POST HTTP %d <- %s | body=%s' % (r.status_code, url, r.text[:500]))
        return r.text, r.status_code
    except Exception as e:
        try:
            import urllib.error
            if isinstance(e, urllib.error.HTTPError):
                body = e.read().decode('utf-8', errors='replace')
                log.log('[Joyn] POST HTTPError %d <- %s | body=%s' % (e.code, url, body[:500]),
                        log.LOGWARNING)
                return body, e.code
        except Exception:
            pass
        log.log('[Joyn] POST exception %s: %s' % (url, e), log.LOGWARNING)
        return '', 0


def _anon_token():
    did = _device_id()
    cid = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'JOYNCLIENTID' + did))
    h   = {**_base_hdr(), 'Joyn-Country': _COUNTRY, 'Joyn-Distribution-Tenant': _TENANT}
    body, st = _post_json(_AUTH_URL,
                          {'anon_device_id': did, 'client_id': cid, 'client_name': 'web'}, h)
    log.log('[Joyn] anon_token HTTP %d' % st)
    if not body or st >= 400:
        return {}
    try:
        return json.loads(body)
    except Exception:
        return {}


def _refresh(refresh_tok, client_id):
    h    = {**_base_hdr(), 'Joyn-Country': _COUNTRY, 'Joyn-Distribution-Tenant': _TENANT}
    body, st = _post_json(_AUTH_REF,
                          {'refresh_token': refresh_tok, 'grant_type': 'Bearer',
                           'client_id': client_id, 'client_name': 'web'}, h)
    if not body or st >= 400:
        return {}
    try:
        return json.loads(body)
    except Exception:
        return {}


def _token():
    _detect_country()
    now = time.time()
    tok = _TCACHE.get('data', {})
    if tok and _TCACHE.get('exp', 0) > now + 300:
        log.log('[Joyn] _token: cache hit (exp in %.0fs)' % (_TCACHE['exp'] - now))
        return tok.get('access_token', '')
    if tok.get('refresh_token') and _TCACHE.get('cid'):
        log.log('[Joyn] _token: refreshing …')
        r = _refresh(tok['refresh_token'], _TCACHE['cid'])
        if r.get('access_token'):
            _TCACHE['data'] = r
            _TCACHE['exp']  = now + r.get('expires_in', 3600) - 300
            log.log('[Joyn] _token: refresh OK, exp_in=%s' % r.get('expires_in'))
            return r['access_token']
        log.log('[Joyn] _token: refresh failed, falling back to anon', log.LOGWARNING)
    log.log('[Joyn] _token: fetching anon token …')
    fresh = _anon_token()
    if fresh.get('access_token'):
        _TCACHE['data'] = fresh
        _TCACHE['exp']  = now + fresh.get('expires_in', 3600) - 300
        _TCACHE['cid']  = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'JOYNCLIENTID' + _device_id()))
        log.log('[Joyn] _token: anon OK, exp_in=%s' % fresh.get('expires_in'))
    else:
        log.log('[Joyn] _token: Kein access_token! response=%s' % str(fresh)[:200],
                log.LOGWARNING)
    return fresh.get('access_token', '')


def _gql_hdr():
    _detect_country()
    return {
        'x-api-key':                _API_KEY,
        'Joyn-Platform':            'web',
        'Joyn-Country':             _COUNTRY,
        'Joyn-Distribution-Tenant': _TENANT,
        'User-Agent':               _UA,
        'Accept':                   'application/json',
        'Content-Type':             'application/json',
        'Origin':                   _BASE_URL,
        'Referer':                  _BASE_URL + '/',
        'Accept-Language':          'de-DE,de;q=0.9',
        'Authorization':            'Bearer ' + _token(),
    }


def _gql(op, variables, hash_key, extra=None):
    params = {
        'operationName': op,
        'variables':     json.dumps(variables, separators=(',', ':')),
        'extensions':    json.dumps({'persistedQuery': {'version': 1,
                                     'sha256Hash': _H[hash_key]}},
                                    separators=(',', ':')),
    }
    if extra:
        params.update(extra)
    log.log('[Joyn] GQL %s %s' % (op, str(variables)[:100]))
    try:
        r    = multiquest.get(_GQL_URL, headers=_gql_hdr(), params=params, timeout=15)
        data = json.loads(r.text)
        log.log('[Joyn] GQL %s HTTP %d' % (op, r.status_code))
        if isinstance(data, dict) and 'data' in data:
            return data['data']
        if isinstance(data, dict) and 'errors' in data:
            log.log('[Joyn] GQL errors: %s' % str(data['errors'])[:200], log.LOGWARNING)
    except Exception as e:
        log.log('[Joyn] GQL exception %s: %s' % (op, e), log.LOGWARNING)
    return None


def _gql_raw(op, query):
    try:
        r    = multiquest.post(_GQL_URL,
                               json={'query': 'query %s %s' % (op, query), 'operationName': op},
                               headers=_gql_hdr(), timeout=15)
        data = json.loads(r.text)
        if isinstance(data, dict) and 'data' in data:
            return data['data']
    except Exception as e:
        log.log('[Joyn] GQL raw exception %s: %s' % (op, e), log.LOGWARNING)
    return None


def _is_free(asset):
    lt = asset.get('licenseTypes') or []
    return any(t in _FREE_LT for t in lt) or not lt


def _img(asset, key='primaryImage', profile='nextgen-web-herolandscape-1920x'):
    img = asset.get(key) or {}
    url = img.get('url') or ''
    if url and 'profile:' in url:
        url = re.sub(r'profile:[^/&"\']+', 'profile:' + profile, url)
    return url


def _folder(title, url, plot='', next_func='showEntries'):
    return {'title': title, 'url': url, 'plot': plot,
            'is_playable': False, 'next_func': next_func}


def _build_movie(m):
    vid  = (m.get('video') or {}).get('id', '')
    path = m.get('path', '')
    url  = ('vod:%s' % vid) if vid else ('movie:%s' % path)
    poster = (_img(m, 'heroPortrait', 'nextgen-webphone-heroportrait-563x')
              or _img(m, 'heroPortraitImage', 'nextgen-webphone-heroportrait-563x')
              or _img(m, 'posterImage', 'nextgen-webphone-heroportrait-563x'))
    icon   = (_img(m, 'primaryImage')
              or _img(m, 'posterImage'))
    fanart = (_img(m, 'heroLandscapeImage', 'nextgen-web-herolandscape-1920x')
              or poster)
    return {
        'title':       m.get('title', ''),
        'url':         url,
        'plot':        m.get('description', ''),
        'year':        str(m.get('productionYear', '') or ''),
        'poster':      poster,
        'icon':        icon,
        'fanart':      fanart,
        'mediatype':   'movie',
        'is_playable': True,
        'next_func':   'get_hosters',
    }


def _build_series(s):
    poster = (_img(s, 'heroPortraitImage', 'nextgen-webphone-heroportrait-563x')
              or _img(s, 'posterImage', 'nextgen-webphone-heroportrait-563x'))
    icon   = (_img(s, 'primaryImage')
              or _img(s, 'posterImage'))
    fanart = (_img(s, 'heroLandscapeImage', 'nextgen-web-herolandscape-1920x')
              or poster)
    return {
        'title':       s.get('title', ''),
        'url':         'series:%s' % s.get('path', ''),
        'plot':        s.get('description', ''),
        'poster':      poster,
        'icon':        icon,
        'fanart':      fanart,
        'mediatype':   'tvshow',
        'is_playable': False,
        'next_func':   'showSeasons',
    }


def _build_episode(ep, series_title=''):
    vid = (ep.get('video') or {}).get('id', '')
    sn  = (ep.get('season') or {}).get('number', 0)
    en  = ep.get('number', 0)
    t   = ep.get('title', '')
    if series_title and sn and en:
        t = '%s – S%02dE%02d – %s' % (series_title, sn, en, t)
    return {
        'title':       t,
        'url':         'vod:%s' % vid,
        'plot':        ep.get('description', ''),
        'season':      sn,
        'episode':     en,
        'poster':      _img(ep, 'primaryImage'),
        'icon':        _img(ep, 'primaryImage'),
        'fanart':      _img(ep, 'heroLandscapeImage', 'nextgen-web-herolandscape-1920x'),
        'mediatype':   'episode',
        'is_playable': bool(vid),
        'next_func':   'get_hosters',
    }


def _build_channel(brand):
    path  = brand.get('path', '')
    title = brand.get('title', '')
    icon  = (_img(brand, 'logo', 'nextgen-web-artlogo-183x75')
             or _img(brand, 'logoImage', 'nextgen-web-artlogo-183x75')
             or _img(brand, 'primaryImage'))
    fanart = _img(brand, 'heroLandscapeImage', 'nextgen-web-herolandscape-1920x') or icon
    return {
        'title':       title,
        'url':         'channel:%s' % path,
        'plot':        'Joyn Sender: %s' % title,
        'poster':      icon,
        'icon':        icon,
        'fanart':      fanart,
        'is_playable': False,
        'next_func':   'showEntries',
    }


def _build_live(ls):
    ch_id     = ls.get('id', '')
    title     = ls.get('title', '')
    epg       = ls.get('epgEvents') or []
    now_prog  = epg[0] if epg else {}
    now_title = (now_prog.get('title', '') if isinstance(now_prog, dict) else '')
    display   = ('[COLOR gold][B]%s[/B][/COLOR] – %s' % (title, now_title)
                 if now_title else '[COLOR gold][B]%s[/B][/COLOR]' % title)
    brand     = ls.get('brand') or {}
    logo      = (brand.get('livestream') or {}).get('logo') or {}
    icon      = logo.get('url', '')
    ls_type   = ls.get('type', 'LINEAR')
    return {
        'title':       display,
        'url':         'live:%s:%s' % (ch_id, ls_type),
        'plot':        now_title,
        'poster':      icon,
        'icon':        icon,
        'fanart':      icon,
        'mediatype':   'video',
        'is_playable': True,
        'next_func':   'get_hosters',
    }


def _build_compilation(c):
    return {
        'title':       c.get('title', ''),
        'url':         'compilation:%s' % c.get('path', ''),
        'plot':        c.get('description', ''),
        'poster':      _img(c, 'heroPortraitImage', 'nextgen-webphone-heroportrait-563x'),
        'icon':        _img(c, 'primaryImage'),
        'fanart':      _img(c, 'heroLandscapeImage', 'nextgen-web-herolandscape-1920x'),
        'mediatype':   'tvshow',
        'is_playable': False,
        'next_func':   'showEpisodes',
    }


def _collect(node, result, seen, depth=0):
    if depth > 10 or not isinstance(node, (dict, list)):
        return
    if isinstance(node, list):
        for item in node:
            _collect(item, result, seen, depth + 1)
        return

    tn = node.get('__typename', '')

    if tn == 'Movie' and _is_free(node):
        vid  = (node.get('video') or {}).get('id', '')
        path = node.get('path', '')
        key  = vid or path
        if key and key not in seen:
            seen.add(key)
            result.append(_build_movie(node))
        return

    if tn == 'Series' and _is_free(node):
        path = node.get('path', '')
        if path and path not in seen:
            seen.add(path)
            result.append(_build_series(node))
        return

    if tn == 'Episode' and _is_free(node):
        vid = (node.get('video') or {}).get('id', '')
        if vid and vid not in seen:
            seen.add(vid)
            series_title = (node.get('series') or {}).get('title', '')
            result.append(_build_episode(node, series_title))
        return

    if tn in ('Brand', 'ChannelPage'):
        path = node.get('path', '')
        if path and path not in seen:
            seen.add(path)
            result.append(_build_channel(node))
        return

    if tn == 'Compilation' and _is_free(node):
        path = node.get('path', '')
        if path and path not in seen:
            seen.add(path)
            result.append(_build_compilation(node))
        return

    if tn == 'Teaser':
        path = node.get('path', '') or node.get('id', '')
        if path and path not in seen:
            seen.add(path)
            result.append({
                'title':       node.get('headline', node.get('title', 'Sammlung')),
                'url':         'collection:%s' % path,
                'plot':        '',
                'is_playable': False,
                'next_func':   'showEntries',
            })
        return

    inner = node.get('asset') or node.get('item')
    if isinstance(inner, dict):
        _collect(inner, result, seen, depth + 1)

    for key in ('items', 'assets', 'lanes', 'blocks', 'lazyBlocks',
                'results', 'nodes', 'edges', 'content',
                'page', 'landingPage', 'tvShows', 'movies',
                'series', 'data', 'compilationItems'):
        child = node.get(key)
        if child:
            _collect(child, result, seen, depth + 1)


def _extract(data):
    items, seen = [], set()
    if isinstance(data, dict):
        _collect(data, items, seen)
    return items


def _page(items, base_url, offset):
    page = items[offset:offset + _PAGE_SIZE]
    if offset + _PAGE_SIZE < len(items):
        page.append(_folder(
            '[B]Nächste Seite »[/B]',
            '%s|%d' % (base_url, offset + _PAGE_SIZE),
        ))
    return page


def load(url='', params=None):
    return [
        _folder('Mediatheken',   'menu:channels'),
        _folder('Live TV',       'menu:live',    'Joyn Live-Sender.',   'get_live'),
        _folder('Live TV Abruf', 'menu:live_vod'),
        _folder('TV-Serien',     'cat:/serien'),
        _folder('Filme',         'cat:/filme'),
        _folder('Sport',         'cat:/sport'),
        _folder('Kategorien',    'cat:/'),
        _folder('Suche',         '',             '',                    'search'),
    ]


def showEntries(url='', params=None):
    offset   = 0
    base_url = url or 'cat:/'
    if '|' in base_url:
        base_url, _, off = base_url.rpartition('|')
        try:
            offset = int(off)
        except ValueError:
            offset = 0

    if base_url == 'menu:channels':
        return _load_channels_vod(offset)

    if base_url == 'menu:live_vod':
        return _load_live_vod(offset)

    if base_url.startswith('cat:'):
        path = base_url[4:]  # z.B. '/serien', '/filme', '/'
        return _load_categories(path, offset)

    if base_url.startswith('block:'):
        block_id = base_url[6:]
        return _load_block(block_id, offset)

    if base_url.startswith('channel:'):
        path = base_url[8:]  # '/senderpath'
        return _load_channel_content(path, offset)

    if base_url.startswith('compilation:'):
        path = base_url[12:]
        return _load_compilation(path, offset)

    if base_url.startswith('collection:'):
        path = base_url[11:]
        return _load_collection(path, offset)

    return _load_categories('/', offset)


def _load_channels_vod(offset=0):
    log.log('[Joyn] _load_channels_vod')
    data = _gql('Navigation', {}, 'NAVIGATION')
    items, seen = [], set()
    mediatheken = (data or {}).get('mediatheken') or {}
    for block in (mediatheken.get('blocks') or []):
        for asset in (block.get('assets') or []):
            if not isinstance(asset, dict):
                continue
            tn   = asset.get('__typename', '')
            path = asset.get('path', '')
            if tn in ('Brand', 'ChannelPage') and path and path not in seen:
                seen.add(path)
                items.append(_build_channel(asset))
    log.log('[Joyn] Sender gefunden: %d' % len(items))
    return _page(items, 'menu:channels', offset)


def _load_live_vod(offset=0):
    log.log('[Joyn] _load_live_vod')
    data        = _gql_raw('PlayerLivestreams', _Q_LIVE)
    live_streams = (data or {}).get('liveStreams') or []
    items, seen  = [], set()
    for ls in live_streams:
        if not isinstance(ls, dict) or ls.get('type') != 'ON_DEMAND':
            continue
        ch_id = ls.get('id', '')
        if ch_id in seen:
            continue
        seen.add(ch_id)
        epg_events = ls.get('epgEvents') or []
        now_prog   = (epg_events[0].get('program', {}) if epg_events else {})
        if isinstance(now_prog, dict) and now_prog.get('video', {}).get('id'):
            vid = now_prog['video']['id']
            items.append({
                'title':       '[COLOR gold][B]%s[/B][/COLOR] – %s' % (
                    ls.get('title', ''), now_prog.get('title', '')),
                'url':         'vod:%s' % vid,
                'plot':        now_prog.get('title', ''),
                'is_playable': True,
                'next_func':   'get_hosters',
            })
        else:
            items.append(_build_live(ls))
    return _page(items, 'menu:live_vod', offset)


def _load_categories(path, offset=0):
    log.log('[Joyn] _load_categories path=%s' % path)
    data  = _gql('LandingPageClient', {'path': path}, 'LANDINGPAGE',
                 {'enable_user_location': 'true'})
    page  = (data or {}).get('page') or {}
    blocks = list(page.get('blocks') or []) + list(page.get('lazyBlocks') or [])

    items, seen = [], set()
    for block in blocks:
        if not isinstance(block, dict):
            continue
        tn = block.get('__typename', '')
        if tn not in _CATEGORY_LANES:
            continue
        headline = block.get('headline', '') or block.get('title', '')
        block_id = block.get('id', '')
        if not headline or not block_id or block_id in seen:
            continue
        seen.add(block_id)
        items.append(_folder(headline, 'block:%s' % block_id, ''))

    log.log('[Joyn] Blöcke: %d für path=%s' % (len(items), path))
    return _page(items, 'cat:%s' % path, offset)


def _load_block(block_id, offset=0):
    log.log('[Joyn] _load_block block_id=%s' % block_id)
    data  = _gql('LandingBlocks', {'ids': [block_id]}, 'LANDINGBLOCKS',
                 {'enable_user_location': 'true'})
    all_items = []
    for block in ((data or {}).get('blocks') or []):
        if isinstance(block, dict) and block.get('id') == block_id:
            all_items = _extract({'assets': block.get('assets') or []})
            break
    if not all_items:
        all_items = _extract(data)
    log.log('[Joyn] Block %s: %d items' % (block_id, len(all_items)))
    return _page(all_items, 'block:%s' % block_id, offset)


def _load_channel_content(path, offset=0):
    log.log('[Joyn] _load_channel_content path=%s offset=%d' % (path, offset))
    gql_offset = offset
    all_items  = []
    first      = 32
    while True:
        data   = _gql('PageDetailMediaLibrary',
                      {'path': path, 'first': first, 'offset': gql_offset},
                      'CHANNEL', {'enable_user_location': 'true'})
        assets = ((data or {}).get('page') or {}).get('assets') or []
        if not assets:
            break
        batch = _extract({'assets': assets})
        all_items.extend(batch)
        if len(assets) < first:
            break
        gql_offset += first
    all_items.sort(key=lambda x: x.get('title', '').upper())
    log.log('[Joyn] Sender %s: %d items' % (path, len(all_items)))
    return _page(all_items, 'channel:%s' % path, 0)


def _load_compilation(path, offset=0):
    log.log('[Joyn] _load_compilation path=%s' % path)
    data      = _gql('CompilationDetailPageStatic', {'path': path}, 'COMPILATION',
                     {'enable_user_location': 'true'})
    comp      = ((data or {}).get('page') or {}).get('compilation') or {}
    all_items = _extract({'compilationItems': comp.get('compilationItems') or []})
    return _page(all_items, 'compilation:%s' % path, offset)


def _load_collection(path, offset=0):
    log.log('[Joyn] _load_collection path=%s' % path)
    data   = _gql('PageCollectionsDetail', {'path': path}, 'COLLECTION',
                  {'enable_user_location': 'true'})
    blocks = ((data or {}).get('page') or {}).get('blocks') or []
    items, seen = [], set()
    for block in blocks:
        if not isinstance(block, dict):
            continue
        tn = block.get('__typename', '')
        bid = block.get('id', '')
        hl  = block.get('headline', '') or block.get('title', '')
        if hl and bid and bid not in seen:
            seen.add(bid)
            if tn in _CATEGORY_LANES:
                items.append(_folder(hl, 'block:%s' % bid))
            elif block.get('assets'):
                items.extend(_extract({'assets': block['assets']}))
    return _page(items, 'collection:%s' % path, offset)


def showSeasons(url='', params=None):
    if not url.startswith('series:'):
        return []
    path = url[7:]
    log.log('[Joyn] showSeasons path=%s' % path)
    data = _gql('SeriesDetailNewPageStatic',
                {'path': path, 'licenseFilter': 'ALL'},
                'SEASONS', {'enable_user_location': 'true'})
    if not isinstance(data, dict):
        return []

    series_node = None
    for v in data.values():
        if isinstance(v, dict):
            if v.get('__typename') == 'Series':
                series_node = v
                break
            for vv in v.values():
                if isinstance(vv, dict) and vv.get('__typename') == 'Series':
                    series_node = vv
                    break
    if not series_node:
        for v in data.values():
            if isinstance(v, dict):
                series_node = v
                break
    if not series_node:
        return []

    all_seasons  = series_node.get('allSeasons') or series_node.get('seasons') or []
    series_title = series_node.get('title', '')
    poster       = _img(series_node, 'heroPortraitImage', 'nextgen-webphone-heroportrait-563x')
    fanart       = _img(series_node, 'heroLandscapeImage', 'nextgen-web-herolandscape-1920x')

    if len(all_seasons) == 1 and all_seasons[0].get('id'):
        return showEpisodes('season:%s|%s' % (all_seasons[0]['id'], series_title))

    items = []
    for s in all_seasons:
        if not isinstance(s, dict):
            continue
        lt = s.get('licenseTypes') or []
        if lt and not any(t in _FREE_LT for t in lt):
            continue
        sid    = s.get('id', '')
        snum   = s.get('number', 0)
        spost  = _img(s, 'primaryImage') or poster
        items.append({
            'title':       'Staffel %d' % snum,
            'url':         'season:%s|%s' % (sid, series_title),
            'poster':      spost,
            'icon':        spost,
            'fanart':      fanart,
            'season':      snum,
            'mediatype':   'season',
            'is_playable': False,
            'next_func':   'showEpisodes',
        })
    log.log('[Joyn] showSeasons "%s": %d Staffeln' % (series_title, len(items)))
    return items


def showEpisodes(url='', params=None):
    if not url.startswith('season:'):
        return []
    rest  = url[7:]
    parts = rest.split('|', 1)
    sid   = parts[0]
    stitle= parts[1] if len(parts) > 1 else ''
    log.log('[Joyn] showEpisodes season_id=%s' % sid)

    items  = []
    offset = 0
    first  = 32
    while True:
        data  = _gql('Season',
                     {'id': sid, 'licenseFilter': 'ALL',
                      'first': first, 'offset': offset},
                     'EPISODES', {'enable_user_location': 'true'})
        eps   = ((data or {}).get('season') or {}).get('episodes') or []
        if not eps:
            break
        for ep in eps:
            if not isinstance(ep, dict):
                continue
            if not _is_free(ep):
                continue
            items.append(_build_episode(ep, stitle))
        if len(eps) < first:
            break
        offset += first

    log.log('[Joyn] showEpisodes: %d Episoden' % len(items))
    return items


def get_live(url='', params=None):
    log.log('[Joyn] get_live')
    data         = _gql_raw('PlayerLivestreams', _Q_LIVE)
    live_streams = (data or {}).get('liveStreams') or []
    items, seen  = [], set()
    for ls in live_streams:
        if not isinstance(ls, dict):
            continue
        ls_type = ls.get('type', '')
        if ls_type == 'ON_DEMAND':
            continue
        ch_id = ls.get('id', '')
        if ch_id in seen:
            continue
        seen.add(ch_id)
        items.append(_build_live(ls))
    log.log('[Joyn] get_live: %d Sender' % len(items))
    return items


def _build_sig(client_data_json, ent_token):
    import base64
    sig_key   = base64.b64decode(_SIG_KEY).decode('utf-8')
    sha_input = '%s,%s%s' % (client_data_json, ent_token, sig_key)
    return hashlib.sha1(sha_input.encode('utf-8')).hexdigest()


def _get_ent(video_id, stream_type):
    log.log('[Joyn] _get_ent video_id=%s type=%s' % (video_id, stream_type))
    tok = _token()
    if not tok:
        log.log('[Joyn] _get_ent: no token!', log.LOGWARNING)
        return ''
    log.log('[Joyn] _get_ent: token ok (len=%d)' % len(tok))
    h = {**_base_hdr(), 'Authorization': 'Bearer ' + tok,
         'Content-Type': 'application/json',
         'Joyn-Platform': 'web',
         'Joyn-Country': _COUNTRY, 'Joyn-Distribution-Tenant': _TENANT}
    body, st = _post_json(_ENT_URL,
                          {'content_id': video_id, 'content_type': stream_type}, h)
    if not body or st >= 400:
        log.log('[Joyn] _get_ent FAILED HTTP %d body=%s' % (st, body[:300]), log.LOGWARNING)
        return ''
    try:
        parsed = json.loads(body)
        et = parsed.get('entitlement_token', '')
        log.log('[Joyn] _get_ent: parsed=%s | ent_token_len=%d' % (
            str({k: v for k, v in parsed.items() if k != 'entitlement_token'})[:200],
            len(et)))
        if not et:
            log.log('[Joyn] _get_ent: entitlement_token leer! full=%s' % body[:400],
                    log.LOGWARNING)
        return et
    except Exception as ex:
        log.log('[Joyn] _get_ent parse error: %s | body=%s' % (ex, body[:300]), log.LOGWARNING)
        return ''


def _get_mpd(video_id, stream_type, ent_tok):
    import base64
    log.log('[Joyn] _get_mpd video_id=%s type=%s' % (video_id, stream_type))
    client_data = json.dumps({
        'manufacturer': 'unknown', 'platform': 'browser',
        'maxSecurityLevel': 1, 'model': 'unknown',
        'protectionSystem': 'widevine', 'streamingFormat': 'dash',
        'enableSubtitles': True, 'maxResolution': 1080, 'version': 'v1',
    }, separators=(',', ':'))
    sig  = _build_sig(client_data, ent_tok)
    seg  = 'channel' if stream_type in ('LIVE', 'LINEAR', 'EVENT') else 'asset'
    url  = '%s/%s/%s/playlist?signature=%s' % (_PBK_URL, seg, video_id, sig)
    log.log('[Joyn] _get_mpd POST url=%s' % url)
    log.log('[Joyn] _get_mpd payload=%s' % client_data)
    log.log('[Joyn] _get_mpd sig=%s' % sig)
    hdrs = {'Authorization': 'Bearer ' + ent_tok,
            'Content-Type': 'application/json',
            'User-Agent': _UA}
    try:
        r = multiquest.post(url, data=client_data, headers=hdrs, timeout=15)
        log.log('[Joyn] _get_mpd HTTP %d | body=%s' % (r.status_code, r.text[:800]))
        parsed = json.loads(r.text)
        mpd     = parsed.get('manifestUrl', '')
        lic_url = parsed.get('licenseUrl', '')
        cert_url= parsed.get('certificateUrl', '')
        if not mpd:
            log.log('[Joyn] _get_mpd: kein manifestUrl! keys=%s' % list(parsed.keys()),
                    log.LOGWARNING)
        else:
            log.log('[Joyn] _get_mpd: manifestUrl=%s licenseUrl=%s' % (mpd, lic_url))
        return mpd, lic_url, cert_url
    except Exception as e:
        log.log('[Joyn] _get_mpd exception: %s' % e, log.LOGWARNING)
        return '', '', ''


def _scout_find_url(title, year, imdb, tmdb_id, season, episode):
    is_episode = int(season) > 0 and int(episode) > 0
    log.log('[Joyn] _scout_find_url title=%s year=%s season=%s episode=%s' % (title, year, season, episode))
    data = _gql('SearchQ',
                {'text': title, 'first': _GQL_FIRST, 'offset': 0},
                'SEARCH', {'enable_user_location': 'true'})
    if not isinstance(data, dict):
        return ''
    search_root = None
    for v in data.values():
        if isinstance(v, dict):
            search_root = v
            break
    if not search_root:
        return ''
    result_list = []
    for v in search_root.values():
        if isinstance(v, list):
            result_list.extend(v)
        elif isinstance(v, dict):
            result_list.extend(v.get('items') or [])
    if not is_episode:
        for it in result_list:
            if not isinstance(it, dict):
                continue
            asset = it.get('asset') or it
            if asset.get('__typename') != 'Movie' or not _is_free(asset):
                continue
            if year and asset.get('productionYear') and str(asset.get('productionYear')) != str(year):
                continue
            vid = (asset.get('video') or {}).get('id', '')
            if vid:
                return 'vod:%s' % vid
            path = asset.get('path', '')
            if path:
                return 'movie:%s' % path
        for it in result_list:
            if not isinstance(it, dict):
                continue
            asset = it.get('asset') or it
            if asset.get('__typename') != 'Movie' or not _is_free(asset):
                continue
            vid = (asset.get('video') or {}).get('id', '')
            if vid:
                return 'vod:%s' % vid
            path = asset.get('path', '')
            if path:
                return 'movie:%s' % path
    else:
        season  = int(season)
        episode = int(episode)
        for it in result_list:
            if not isinstance(it, dict):
                continue
            asset = it.get('asset') or it
            if asset.get('__typename') != 'Series' or not _is_free(asset):
                continue
            path = asset.get('path', '')
            if not path:
                continue
            data2 = _gql('SeriesDetailNewPageStatic',
                         {'path': path, 'licenseFilter': 'ALL'},
                         'SEASONS', {'enable_user_location': 'true'})
            if not isinstance(data2, dict):
                continue
            series_node = None
            for v in data2.values():
                if isinstance(v, dict):
                    if v.get('__typename') == 'Series':
                        series_node = v
                        break
                    for vv in v.values():
                        if isinstance(vv, dict) and vv.get('__typename') == 'Series':
                            series_node = vv
                            break
            if not series_node:
                continue
            all_seasons = series_node.get('allSeasons') or series_node.get('seasons') or []
            target_season = None
            for s in all_seasons:
                if isinstance(s, dict) and s.get('number') == season:
                    target_season = s
                    break
            if not target_season:
                continue
            sid = target_season.get('id', '')
            if not sid:
                continue
            offset2 = 0
            first2  = 32
            while True:
                data3 = _gql('Season',
                             {'id': sid, 'licenseFilter': 'ALL',
                              'first': first2, 'offset': offset2},
                             'EPISODES', {'enable_user_location': 'true'})
                eps = ((data3 or {}).get('season') or {}).get('episodes') or []
                if not eps:
                    break
                for ep in eps:
                    if not isinstance(ep, dict):
                        continue
                    if ep.get('number') == episode and _is_free(ep):
                        vid = (ep.get('video') or {}).get('id', '')
                        if vid:
                            return 'vod:%s' % vid
                if len(eps) < first2:
                    break
                offset2 += first2
    log.log('[Joyn] _scout_find_url: kein Treffer', log.LOGWARNING)
    return ''


def get_hosters(title='', year='', season=0, episode=0,
                imdb='', tmdb='', url='', params=None):
    log.log('[Joyn] get_hosters url=%s title=%s' % (url, title))
    if not url:
        if title:
            url = _scout_find_url(title, year, imdb, tmdb, season, episode)
        if not url:
            log.log('[Joyn] get_hosters: url leer und Scout-Suche erfolglos!', log.LOGWARNING)
            return []

    if url.startswith('movie:'):
        path = url[6:]
        log.log('[Joyn] get_hosters: movie path=%s → GQL für video_id' % path)
        data = _gql('PageMovieDetailStatic', {'path': path}, 'MOVIES',
                    {'enable_user_location': 'true'})
        vid  = ''
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, dict):
                    mov = v.get('movie') or v
                    vid = (mov.get('video') or {}).get('id', '')
                    if vid:
                        break
        if not vid:
            log.log('[Joyn] get_hosters: movie video_id nicht gefunden! data=%s'
                    % str(data)[:300], log.LOGWARNING)
            return []
        log.log('[Joyn] get_hosters: movie video_id=%s' % vid)
        url = 'vod:%s' % vid

    if url.startswith('vod:'):
        vid = url[4:]
        if not vid:
            log.log('[Joyn] get_hosters: vod ohne id!', log.LOGWARNING)
            return []
        log.log('[Joyn] get_hosters: VOD vid=%s → entitlement …' % vid)
        et  = _get_ent(vid, 'VOD')
        if not et:
            log.log('[Joyn] get_hosters: VOD kein ent_token → abbruch', log.LOGWARNING)
            return []
        log.log('[Joyn] get_hosters: VOD ent_token ok → manifest …')
        mpd, lic_url, cert_url = _get_mpd(vid, 'VOD', et)
        if not mpd:
            log.log('[Joyn] get_hosters: VOD kein manifestUrl → abbruch', log.LOGWARNING)
            return []
        log.log('[Joyn] get_hosters: VOD OK mpd=%s lic=%s' % (mpd, lic_url))
        drm_info = {'drm_type': 'widevine', 'drm_license': lic_url}
        if cert_url:
            drm_info['drm_certificate'] = cert_url
        return [['Joyn', mpd, drm_info]]

    if url.startswith('live:'):
        rest  = url[5:]
        parts = rest.split(':', 1)
        ch_id   = parts[0]
        ls_type = parts[1] if len(parts) > 1 else 'LINEAR'
        if not ch_id:
            log.log('[Joyn] get_hosters: live ohne id!', log.LOGWARNING)
            return []
        log.log('[Joyn] get_hosters: LIVE ch_id=%s type=%s → entitlement …' % (ch_id, ls_type))
        et  = _get_ent(ch_id, ls_type)
        if not et:
            log.log('[Joyn] get_hosters: LIVE kein ent_token → abbruch', log.LOGWARNING)
            return []
        log.log('[Joyn] get_hosters: LIVE ent_token ok → manifest …')
        mpd, lic_url, cert_url = _get_mpd(ch_id, ls_type, et)
        if not mpd:
            log.log('[Joyn] get_hosters: LIVE kein manifestUrl → abbruch', log.LOGWARNING)
            return []
        log.log('[Joyn] get_hosters: LIVE OK mpd=%s lic=%s' % (mpd, lic_url))
        drm_info = {'drm_type': 'widevine', 'drm_license': lic_url, 'is_live': True}
        if cert_url:
            drm_info['drm_certificate'] = cert_url
        return [['Joyn Live', mpd, drm_info]]

    log.log('[Joyn] get_hosters: url-Schema unbekannt: %s' % url, log.LOGWARNING)
    return []


def search(query='', params=None, url=''):
    if isinstance(params, dict):
        query = query or params.get('query') or params.get('keyword') or ''
    if not query and isinstance(url, str) and url not in ('', 'search'):
        query = url
    if not query:
        try:
            import xbmcgui
            query = xbmcgui.Dialog().input('Joyn Suche').strip()
        except Exception:
            pass
    if not query:
        return []

    log.log('[Joyn] search "%s"' % query)
    data = _gql('SearchQ',
                {'text': query, 'first': _GQL_FIRST, 'offset': 0},
                'SEARCH', {'enable_user_location': 'true'})
    if not isinstance(data, dict):
        return []

    items, seen = [], set()
    search_root = None
    for v in data.values():
        if isinstance(v, dict):
            search_root = v
            break
    if not search_root:
        return []

    result_list = []
    for v in search_root.values():
        if isinstance(v, list):
            result_list.extend(v)
        elif isinstance(v, dict):
            result_list.extend(v.get('items') or [])

    for it in result_list:
        if not isinstance(it, dict):
            continue
        asset = it.get('asset') or it
        tn    = asset.get('__typename', '')

        if tn == 'Movie' and _is_free(asset):
            vid  = (asset.get('video') or {}).get('id', '')
            path = asset.get('path', '')
            key  = vid or path
            if key and key not in seen:
                seen.add(key)
                if path and (not asset.get('productionYear') or not asset.get('heroPortraitImage')):
                    d2 = _gql('PageMovieDetailStatic', {'path': path}, 'MOVIES',
                              {'enable_user_location': 'true'})
                    if isinstance(d2, dict):
                        for v2 in d2.values():
                            if isinstance(v2, dict):
                                mov = v2.get('movie') or v2
                                if isinstance(mov, dict) and mov.get('__typename') == 'Movie':
                                    asset = mov
                                    break
                items.append(_build_movie(asset))

        elif tn == 'Series' and _is_free(asset):
            path = asset.get('path', '')
            if path and path not in seen:
                seen.add(path)
                items.append(_build_series(asset))

        elif tn == 'Episode' and _is_free(asset):
            vid = (asset.get('video') or {}).get('id', '')
            if vid and vid not in seen:
                seen.add(vid)
                items.append(_build_episode(asset, (asset.get('series') or {}).get('title', '')))

    log.log('[Joyn] search: %d Treffer' % len(items))
    return items