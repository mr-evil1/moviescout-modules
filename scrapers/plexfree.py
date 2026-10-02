# -*- coding: utf-8 -*-
# MovieScout - Plex Free Movies & Series
# 2026.10.01
# IT('s) Possible
import html, json, time, uuid, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from resources.lib import multiquest, log

SITE_ID       = 'plexfree'
SITE_NAME     = 'Plex Free'
SITE_DOMAIN   = 'watch.plex.tv'
TYPE          = 'both'
GLOBAL_SEARCH = True
STREAMLG      = 'LG0'

PAGE_SIZE = 20

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36'
_CLIENT_ID = str(uuid.uuid4())
_PLEX_MIN_INTERVAL, _PLEX_429_WAIT = 0.2, 5.0
_PLEX_TIMEOUT = 10
_WEB_MIN_INTERVAL, _WEB_TIMEOUT, _WEB_WORKERS = 0.08, 4, 15

def _dbg(msg):
    try:
        fn = getattr(log, 'log', None) or log
        fn(f'[PlexFree] {msg}')
    except Exception:
        pass


def _mask(token):
    t = str(token or '')
    return f'{t[:4]}...({len(t)})' if t else 'LEER'


def _is_german_only():
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon('plugin.video.moviescout')
        val = addon.getSetting('general.german_only')
        if val == '' or val is None:
            val = addon.getSetting('filter_german')
        return str(val).lower() == 'true'
    except Exception:
        return False


_PLEX_RATE_LOCK, _PLEX_LAST_REQUEST = threading.Lock(), 0.0
_GUEST_TOKEN_LOCK, _GUEST_TOKEN = threading.Lock(), None
_WEB_RATE_LOCK, _WEB_LAST_REQUEST = threading.Lock(), 0.0
_WEB_META_LOCK, _WEB_META_CACHE = threading.Lock(), {}
_AUDIO_CACHE_LOCK, _AUDIO_CACHE = threading.Lock(), {}


def _fetch_missing_metadata(item):
    if not item or not isinstance(item, dict):
        return item
    rating_key = str(item.get('ratingKey') or (item.get('key', '').split('/')[-1] if item.get('key') else ''))
    if not rating_key:
        return item
    full_data = plex_api_get(f"/library/metadata/{rating_key}")
    if full_data:
        metas = metadata_objects(full_data)
        if metas and isinstance(metas[0], dict):
            item['Media'] = metas[0].get('Media') or []
    return item


def _prefetch_audio_metadata(items):
    if not _is_german_only() or not items:
        return
    items_to_fetch = []
    for item in items:
        if isinstance(item, dict):
            rk = str(item.get('ratingKey') or (item.get('key', '').split('/')[-1] if item.get('key') else ''))
            if rk:
                with _AUDIO_CACHE_LOCK:
                    if rk in _AUDIO_CACHE:
                        continue
            items_to_fetch.append(item)
            
    if items_to_fetch:
        with ThreadPoolExecutor(max_workers=_WEB_WORKERS) as executor:
            list(executor.map(_fetch_missing_metadata, items_to_fetch))


def _has_german_audio(item):
    if not _is_german_only():
        return True
    if not item or not isinstance(item, dict):
        return False

    if 'MediaContainer' in item:
        metas = metadata_objects(item)
        if metas:
            item = metas[0]
        else:
            return False

    rating_key = str(item.get('ratingKey') or (item.get('key', '').split('/')[-1] if item.get('key') else ''))
    if rating_key:
        with _AUDIO_CACHE_LOCK:
            if rating_key in _AUDIO_CACHE:
                return _AUDIO_CACHE[rating_key]

    media_list = item.get('Media') or []
    if not media_list and rating_key:
        full_data = plex_api_get(f"/library/metadata/{rating_key}")
        if full_data:
            metas = metadata_objects(full_data)
            if metas and isinstance(metas[0], dict):
                item = metas[0]
                media_list = item.get('Media') or []

    if isinstance(media_list, dict):
        media_list = [media_list]

    found_audio = False
    has_german = False

    for media in media_list:
        if not isinstance(media, dict):
            continue
        parts = media.get('Part') or []
        if isinstance(parts, dict):
            parts = [parts]
        for part in parts:
            if not isinstance(part, dict):
                continue
            streams = part.get('Stream') or []
            if isinstance(streams, dict):
                streams = [streams]
            for stream in streams:
                if not isinstance(stream, dict):
                    continue
                if str(stream.get('streamType')) == '2':
                    found_audio = True
                    lang_code = str(stream.get('languageCode') or '').lower()
                    lang = str(stream.get('language') or '').lower()
                    display = str(stream.get('displayTitle') or '').lower()

                    if lang_code in ('ger', 'deu', 'de') or 'deutsch' in lang or 'german' in lang or 'deutsch' in display:
                        has_german = True

    res = has_german if found_audio else False

    if rating_key:
        with _AUDIO_CACHE_LOCK:
            _AUDIO_CACHE[rating_key] = res
    return res


def _plex_wait():
    global _PLEX_LAST_REQUEST
    with _PLEX_RATE_LOCK:
        wait = _PLEX_MIN_INTERVAL - (time.monotonic() - _PLEX_LAST_REQUEST)
        if wait > 0:
            time.sleep(wait)
        _PLEX_LAST_REQUEST = time.monotonic()


def _web_wait():
    global _WEB_LAST_REQUEST
    with _WEB_RATE_LOCK:
        wait = _WEB_MIN_INTERVAL - (time.monotonic() - _WEB_LAST_REQUEST)
        if wait > 0:
            time.sleep(wait)
        _WEB_LAST_REQUEST = time.monotonic()


def _safe_get(url, headers=None, params=None, timeout=15, retries=3):
    req_headers = dict(headers or {})
    req_headers.setdefault('User-Agent', _UA)
    req_headers.setdefault('Accept-Language', 'de-DE,de;q=0.9')
    shown = {k: (_mask(v) if 'token' in str(k).lower() else v) for k, v in (params or {}).items()}
    is_web = 'watch.plex.tv' in url
    for attempt in range(retries):
        if is_web:
            _web_wait()
        else:
            _plex_wait()
        t0 = time.monotonic()
        try:
            r = multiquest.get(url, headers=req_headers, params=params, timeout=timeout)
            code = getattr(r, 'status_code', None)
            _dbg(f'GET {url} params={shown} try={attempt + 1}/{retries} -> HTTP {code} in {time.monotonic() - t0:.2f}s')
            if code == 429:
                _dbg(f'429 Rate-Limit, warte {_PLEX_429_WAIT * (attempt + 1):.0f}s')
                time.sleep(_PLEX_429_WAIT * (attempt + 1))
                continue
            return r
        except Exception as e:
            _dbg(f'GET {url} try={attempt + 1}/{retries} EXCEPTION {type(e).__name__}: {e}')
            if '404' in str(e) or '401' in str(e) or '403' in str(e):
                break
            if attempt < retries - 1:
                time.sleep(1.0)
    _dbg(f'GET {url} endgueltig fehlgeschlagen')
    return None


def _get_plex_guest_token():
    global _GUEST_TOKEN
    if _GUEST_TOKEN:
        return _GUEST_TOKEN
    with _GUEST_TOKEN_LOCK:
        if _GUEST_TOKEN:
            return _GUEST_TOKEN
        headers = {
            'User-Agent': _UA,
            'X-Plex-Product': 'Plex Web',
            'X-Plex-Version': '4.120.1',
            'X-Plex-Client-Identifier': _CLIENT_ID,
            'X-Plex-Language': 'de',
            'Accept': 'application/json'
        }
        try:
            r = multiquest.post('https://plex.tv/api/v2/users/anonymous', headers=headers, timeout=15)
            code = getattr(r, 'status_code', None)
            _dbg(f'POST plex.tv/api/v2/users/anonymous client_id={_CLIENT_ID} -> HTTP {code}')
            if r and code in (200, 201):
                _GUEST_TOKEN = r.json().get('authToken')
                _dbg(f'Gast-Token erhalten: {_mask(_GUEST_TOKEN)}')
                return _GUEST_TOKEN
            body = ''
            try:
                body = str(r.text)[:300]
            except Exception:
                pass
            _dbg(f'Gast-Token fehlgeschlagen, Antwort: {body}')
        except Exception as e:
            _dbg(f'Gast-Token EXCEPTION {type(e).__name__}: {e}')
    return None


def _refresh_guest_token():
    global _GUEST_TOKEN
    with _GUEST_TOKEN_LOCK:
        _GUEST_TOKEN = None
    return _get_plex_guest_token()


def plex_api_get(endpoint, params=None, _retry=True):
    token = _get_plex_guest_token()
    if not token:
        _dbg(f'plex_api_get {endpoint}: kein Gast-Token, Abbruch')
        return None
    url = endpoint if endpoint.startswith('http') else f"https://vod.provider.plex.tv{endpoint}"
    headers = {
        'User-Agent': _UA,
        'X-Plex-Token': token,
        'X-Plex-Client-Identifier': _CLIENT_ID,
        'X-Plex-Language': 'de',
        'Accept': 'application/json'
    }
    q = dict(params or {})
    q['X-Plex-Token'] = token
    q['X-Plex-Client-Identifier'] = _CLIENT_ID
    r = _safe_get(url, headers=headers, params=q, timeout=_PLEX_TIMEOUT)
    if r is None:
        _dbg(f'plex_api_get {endpoint}: keine Antwort')
        return None
    code = getattr(r, 'status_code', None)
    if code == 401 and _retry:
        _dbg(f'plex_api_get {endpoint}: 401, erneuere Token')
        _refresh_guest_token()
        return plex_api_get(endpoint, params, _retry=False)
    if code != 200:
        body = ''
        try:
            body = str(r.text)[:300]
        except Exception:
            pass
        _dbg(f'plex_api_get {endpoint}: HTTP {code} Body: {body}')
        return None
    try:
        data = r.json()
    except Exception as e:
        _dbg(f'plex_api_get {endpoint}: JSON-Fehler {type(e).__name__}: {e}')
        return None
    mc = data.get('MediaContainer') if isinstance(data, dict) else None
    if isinstance(mc, dict):
        _dbg(f'plex_api_get {endpoint}: OK size={mc.get("size")} keys={sorted(mc.keys())}')
    else:
        _dbg(f'plex_api_get {endpoint}: OK ohne MediaContainer, keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}')
    return data


def metadata_objects(data):
    if not data or not isinstance(data, dict):
        return []
    mc = data.get('MediaContainer') or {}
    items = mc.get('Metadata') or []
    return [items] if isinstance(items, dict) else (items if isinstance(items, list) else [])


def hub_objects(data):
    if not data or not isinstance(data, dict):
        return []
    mc = data.get('MediaContainer') or {}
    hubs = mc.get('Hub') or []
    return [hubs] if isinstance(hubs, dict) else (hubs if isinstance(hubs, list) else [])


def _extract_all_metadata(data):
    if not data or not isinstance(data, dict):
        return []
    mc = data.get('MediaContainer') or {}
    results = []

    items = mc.get('Metadata') or []
    if isinstance(items, dict):
        items = [items]
    if isinstance(items, list):
        results.extend(items)

    hubs = mc.get('Hub') or []
    if isinstance(hubs, dict):
        hubs = [hubs]
    if isinstance(hubs, list):
        for h in hubs:
            if isinstance(h, dict):
                m_list = h.get('Metadata') or []
                if isinstance(m_list, dict):
                    m_list = [m_list]
                if isinstance(m_list, list):
                    results.extend(m_list)

    def _collect_sr(sr_list):
        if isinstance(sr_list, dict):
            sr_list = [sr_list]
        if not isinstance(sr_list, list):
            return
        for sr in sr_list:
            if not isinstance(sr, dict):
                continue
            m = sr.get('Metadata')
            if isinstance(m, dict):
                results.append(m)
            elif isinstance(m, list):
                results.extend(x for x in m if isinstance(x, dict))
            inner = sr.get('SearchResult')
            if inner:
                _collect_sr(inner)

    _collect_sr(mc.get('SearchResult') or [])
    _collect_sr(mc.get('SearchResults') or [])

    return results


def _get_item_slug(item):
    if not item or not isinstance(item, dict):
        return ''
    slug = item.get('slug') or item.get('Slug') or ''
    if slug:
        return str(slug)
    for k in ('key', 'guid'):
        val = str(item.get(k, ''))
        if '/movie/' in val:
            return val.split('/movie/', 1)[1].split('/', 1)[0]
        if '/show/' in val:
            return val.split('/show/', 1)[1].split('/', 1)[0]
    return ''


def _get_german_summary(slug, item_type):
    if not slug or item_type not in ('movie', 'show', 'series', 'tvshow'):
        return ''
    page_type = 'movie' if item_type == 'movie' else 'show'
    cache_key = f"{page_type}:{slug}"
    with _WEB_META_LOCK:
        cached = _WEB_META_CACHE.get(cache_key)
    if cached is not None:
        return cached
    url = f"https://watch.plex.tv/de/{page_type}/{slug}"
    try:
        r = _safe_get(url, headers={'Accept-Language': 'de-DE,de;q=0.9'}, timeout=_WEB_TIMEOUT, retries=2)
        if not r or getattr(r, 'status_code', None) != 200:
            return ''
        page = getattr(r, 'text', '') or ''
        summary = ''
        for marker in ('Worum geht es in ', 'Worum geht es bei '):
            pos = page.find(marker)
            if pos >= 0:
                fragment = html.unescape(page[pos:pos + 8000])
                for sep in ('</h3>', '</h2>', '<p>', '>'):
                    if sep in fragment:
                        cand = fragment.split(sep, 1)[1].split('<', 1)[0].strip()
                        if len(cand) > 30 and not cand.startswith('Worum'):
                            summary = cand
                            break
                if summary:
                    break
        if not summary:
            for marker in ('"summary":"', '"description":"', '"overview":"'):
                pos = page.find(marker)
                if pos >= 0:
                    start = pos + len(marker)
                    end = page.find('"', start)
                    if end > start:
                        cand = html.unescape(page[start:end].replace('\\"', '"').replace('\\n', '\n')).strip()
                        if len(cand) > 30:
                            summary = cand
                            break
        with _WEB_META_LOCK:
            _WEB_META_CACHE[cache_key] = summary
        return summary
    except Exception as e:
        _dbg(f'German summary {url} EXCEPTION {type(e).__name__}: {e}')
        return ''


def _prefetch_german_summaries(items):
    unique = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get('type', 'movie')).lower()
        if item_type not in ('movie', 'show', 'series', 'tvshow'):
            continue
        slug = _get_item_slug(item)
        if slug:
            unique[f"{'movie' if item_type == 'movie' else 'show'}:{slug}"] = (slug, item_type)
    if not unique:
        return
    with ThreadPoolExecutor(max_workers=_WEB_WORKERS) as executor:
        futures = [executor.submit(_get_german_summary, sl, ty) for sl, ty in unique.values()]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass


def _format_plex_item(item, token):
    if not item or not isinstance(item, dict):
        return None
    
    if not _has_german_audio(item):
        return None
    
    rating_key = item.get('ratingKey') or (item.get('key', '').split('/')[-1] if item.get('key') else None)
    if not rating_key:
        return None
        
    item_type = item.get('type', 'movie').lower()
    
    raw_title = item.get('title') or 'Unbekannt'
    title = html.unescape(raw_title) if isinstance(raw_title, str) else str(raw_title)
    
    year = str(item.get('year') or item.get('parentYear') or '')
    
    raw_summary = item.get('summary') or item.get('tagline') or item.get('overview') or ''
    summary = html.unescape(raw_summary) if isinstance(raw_summary, str) else str(raw_summary)

    de_summary = _get_german_summary(_get_item_slug(item), item_type)
    if de_summary:
        summary = de_summary
    
    try:
        rating = float(item.get('rating') or item.get('audienceRating') or 0.0)
    except (ValueError, TypeError):
        rating = 0.0
    
    thumb = item.get('thumb') or item.get('art') or item.get('grandparentThumb')
    poster = f"https://vod.provider.plex.tv{thumb}?X-Plex-Token={token}" if thumb and not str(thumb).startswith('http') else (thumb or '')
        
    directors_data = item.get('Director') or []
    if isinstance(directors_data, dict):
        directors_data = [directors_data]
    directors = [d.get('tag') for d in directors_data if isinstance(d, dict) and d.get('tag')]

    genres_data = item.get('Genre') or []
    if isinstance(genres_data, dict):
        genres_data = [genres_data]
    genres = [g.get('tag') for g in genres_data if isinstance(g, dict) and g.get('tag')]
    
    meta_plot = f"[COLOR yellow]★ {rating:.1f}[/COLOR]\n" if rating > 0 else ""
    if directors:
        meta_plot += f"[B]Regie:[/B] {', '.join(directors)}\n"
    if genres:
        meta_plot += f"[B]Genre:[/B] {', '.join(genres)}\n"
    if meta_plot and summary:
        meta_plot += "--------------------------------------------------------\n"
    meta_plot += summary

    if item_type == 'movie':
        return {
            'title': title,
            'url': f"{title}||metadata:{rating_key}",
            'mediatype': 'movie',
            'is_playable': True,
            'next_func': 'get_hosters',
            'plot': meta_plot,
            'poster': poster,
            'year': year
        }
    elif item_type in ('show', 'series', 'tvshow'):
        return {
            'title': f"[Serie] {title}",
            'url': f"show_seasons||{rating_key}",
            'mediatype': 'tvshow',
            'is_playable': False,
            'next_func': 'load',
            'plot': meta_plot,
            'poster': poster,
            'year': year
        }
    elif item_type == 'season':
        s_num = item.get('index', 1)
        s_title = item.get('title') or f"Staffel {s_num}"
        return {
            'title': s_title,
            'url': f"season_episodes||{rating_key}",
            'mediatype': 'season',
            'is_playable': False,
            'next_func': 'load',
            'plot': meta_plot,
            'poster': poster,
            'year': year
        }
    elif item_type == 'episode':
        ep_num = item.get('index', 1)
        s_num = item.get('parentIndex', 1)
        ep_display = f"S{int(s_num):02d}E{int(ep_num):02d} - {title}"
        return {
            'title': ep_display,
            'url': f"{ep_display}||metadata:{rating_key}",
            'mediatype': 'episode',
            'is_playable': True,
            'next_func': 'get_hosters',
            'plot': meta_plot,
            'poster': poster,
            'year': year
        }
    return None


_LIVE_HOST = 'https://epg.provider.plex.tv'
_LIVE_PROVIDER_VERSION = '7.0.0'
_LIVE_PRODUCT, _LIVE_PLATFORM = 'Plex Web', 'Chrome'

_DE_WORDS = {
    'der', 'das', 'den', 'dem', 'des', 'und', 'oder', 'für', 'fuer', 'mit', 'von',
    'eine', 'einer', 'einem', 'einen', 'eines', 'auf', 'aus', 'zur', 'zum', 'über',
    'ueber', 'deutsch', 'deutsche', 'deutschen', 'filme', 'serien', 'sendungen',
    'zeigt', 'erlebt', 'gegen', 'nach', 'seine', 'seiner', 'ihre', 'ihrer', 'wird',
    'werden', 'sich', 'nicht', 'auch', 'beim', 'durch', 'zwischen', 'menschen',
    'welt', 'jagd', 'geschichten', 'folgen'
}
_DE_TITLES = ('deutsch', 'spiegel tv', 'netzkino', 'myspass', 'stromberg', 'pastewka',
              'täterjagd', 'taeterjagd')


def _live_headers(token):
    return {
        'User-Agent': _UA,
        'Accept': 'application/json',
        'Accept-Language': 'de-DE,de;q=0.9',
        'X-Plex-Token': token,
        'X-Plex-Product': _LIVE_PRODUCT,
        'X-Plex-Version': '4.120.1',
        'X-Plex-Client-Identifier': _CLIENT_ID,
        'X-Plex-Platform': _LIVE_PLATFORM,
        'X-Plex-Provider-Version': _LIVE_PROVIDER_VERSION,
        'X-Plex-Language': 'de',
    }


def _is_german_channel(title, plot):
    import re
    text = f"{title} {plot}".lower()
    if any(x in text for x in _DE_TITLES) or any(c in text for c in 'äöüß'):
        return True
    words = re.findall(r'[a-zäöüß]+', text)
    return sum(1 for w in words if w in _DE_WORDS) >= 3


def _live_channels():
    token = _get_plex_guest_token()
    if not token:
        return []
    r = _safe_get(f"{_LIVE_HOST}/lineups/plex/channels", headers=_live_headers(token), timeout=20)
    if r is not None and getattr(r, 'status_code', None) in (401, 403):
        token = _refresh_guest_token()
        if not token:
            return []
        r = _safe_get(f"{_LIVE_HOST}/lineups/plex/channels", headers=_live_headers(token), timeout=20)
    if r is None or getattr(r, 'status_code', None) != 200:
        try:
            log(f"[PlexFree Live] Senderliste HTTP {getattr(r, 'status_code', None)}")
        except Exception:
            pass
        return []
    try:
        data = r.json()
    except Exception:
        return []
    container = data.get('MediaContainer', data) if isinstance(data, dict) else {}
    items = (container.get('Channel') or container.get('Metadata') or []) if isinstance(container, dict) else []
    if isinstance(items, dict):
        items = [items]
    out = []
    for ch in items if isinstance(items, list) else []:
        if not isinstance(ch, dict):
            continue
        cid = str(ch.get('id') or '').strip()
        title = html.unescape(str(ch.get('title') or ch.get('name') or ch.get('callSign') or '')).strip()
        if not cid or not title:
            continue
        logo = ch.get('thumb') or ch.get('logo') or ''
        if logo and not str(logo).startswith('http'):
            logo = ''
        out.append({
            'id': cid,
            'title': title,
            'plot': html.unescape(str(ch.get('summary') or ch.get('description') or '')),
            'logo': logo,
        })
    return out


def _live_items(german_only):
    results = []
    for ch in _live_channels():
        if german_only and not _is_german_channel(ch['title'], ch['plot']):
            continue
        results.append({
            'title': ch['title'],
            'url': f"{ch['title']}||live:{ch['id']}",
            'mediatype': 'movie',
            'is_playable': True,
            'next_func': 'get_hosters',
            'plot': ch['plot'],
            'poster': ch['logo'],
            'year': ''
        })
    results.sort(key=lambda x: x['title'].lower())
    return results


def _resolve_live(channel_id):
    from urllib.parse import urlencode
    part_url = f"{_LIVE_HOST}/library/parts/{channel_id}.m3u8"
    play_headers = {'User-Agent': _UA, 'Referer': 'https://watch.plex.tv/', 'Origin': 'https://watch.plex.tv'}
    token = _get_plex_guest_token()
    for attempt in range(2):
        if not token:
            return None
        params = {
            'includeAllStreams': '1',
            'X-Plex-Product': _LIVE_PRODUCT,
            'X-Plex-Client-Identifier': _CLIENT_ID,
            'X-Plex-Client-Platform': _LIVE_PLATFORM,
            'X-Plex-Platform': _LIVE_PLATFORM,
            'X-Plex-Device': 'Windows',
            'X-Plex-Session-Id': str(uuid.uuid4()),
            'X-Plex-Token': token,
        }
        probe_url = part_url + '?' + urlencode(params)
        r = _safe_get(probe_url, headers=dict(play_headers), timeout=15, retries=1)
        status = getattr(r, 'status_code', None)
        try:
            log(f"[PlexFree Live] Manifest-Test {channel_id[-8:]}: HTTP {status}")
        except Exception:
            pass
        if r is None:
            break
        if status == 200:
            break
        if status in (401, 403) and attempt == 0:
            token = _refresh_guest_token()
            continue
        return None
    if not token:
        return None
    params['X-Plex-Product'] = _LIVE_PRODUCT.replace(' ', '%20').replace('%', '%25')
    resolved = part_url + '?' + urlencode(params, safe='%')
    return resolved + '|' + urlencode(play_headers)


def load(url='', params=None):
    token = _get_plex_guest_token()
    
    if not url:
        return [
            {'title': '[ Live TV - Deutsch ]', 'url': 'live_de', 'plot': 'Plex Live TV (ohne Anmeldung), deutschsprachige Sender', 'is_playable': False, 'next_func': 'load'},
            {'title': '[ Live TV - Alle Sender ]', 'url': 'live_all', 'plot': 'Plex Live TV (ohne Anmeldung), alle Sender', 'is_playable': False, 'next_func': 'load'},
            {'title': '[ Suche ]', 'url': 'search_input', 'plot': 'Plex VOD durchsuchen', 'is_playable': False, 'next_func': 'load'},
            {'title': '[ Entdecken & Kategorien ]', 'url': 'hubs', 'plot': 'Plex On-Demand Hubs durchstöbern', 'is_playable': False, 'next_func': 'load'}
        ]

    if url in ('live_de', 'live_all'):
        return _live_items(german_only=(url == 'live_de'))

    if url == 'search_input':
        try:
            import xbmcgui
            dialog = xbmcgui.Dialog()
            query = dialog.input('Plex Free - Suche', type=xbmcgui.INPUT_ALPHANUM)
            _dbg(f'search_input: Eingabe={query!r}')
            if query and query.strip():
                return search(query.strip())
            _dbg('search_input: leere Eingabe oder abgebrochen')
        except Exception as e:
            _dbg(f'search_input EXCEPTION {type(e).__name__}: {e}')
        return []

    if url == 'hubs':
        data = plex_api_get('/hubs')
        promoted = plex_api_get('/hubs/promoted')
        items = []
        seen_keys = set()
        for hub in hub_objects(data) + hub_objects(promoted):
            hub_title = hub.get('title')
            hub_key = hub.get('key')
            if hub_title and hub_key and hub_key not in seen_keys:
                seen_keys.add(hub_key)
                items.append({
                    'title': f"[ {hub_title} ]",
                    'url': f"hub_key||{hub_key}",
                    'plot': f"Inhalte aus {hub_title}",
                    'is_playable': False,
                    'next_func': 'load'
                })
        return items

    if url.startswith('hub_key||'):
        parts = url.split('||')
        key = parts[1]
        offset = int(parts[2]) if len(parts) > 2 else 0
        data = plex_api_get(key, params={
            'X-Plex-Container-Start': offset,
            'X-Plex-Container-Size': PAGE_SIZE
        })
        results = []
        seen_keys = set()
        meta_list = _extract_all_metadata(data)
        _prefetch_audio_metadata(meta_list)
        _prefetch_german_summaries(meta_list)
        for meta in meta_list:
            rk = meta.get('ratingKey') or (meta.get('key', '').split('/')[-1] if meta.get('key') else None)
            if rk and rk not in seen_keys:
                seen_keys.add(rk)
                parsed = _format_plex_item(meta, token)
                if parsed:
                    results.append(parsed)
        
        mc = (data or {}).get('MediaContainer', {}) if isinstance(data, dict) else {}
        total = int(mc.get('totalSize') or mc.get('size') or 0)

        has_more_from_plex = total > offset + PAGE_SIZE
        if _is_german_only():
            has_more_from_plex = len(meta_list) == PAGE_SIZE and total > offset + len(meta_list)

        if has_more_from_plex:
            next_offset = offset + PAGE_SIZE
            results.append({
                'title': f'[ Weiter \u2192 (ab Eintrag {next_offset + 1}) ]',
                'url': f'hub_key||{key}||{next_offset}',
                'plot': f'N\u00e4chste Einträge laden',
                'is_playable': False,
                'next_func': 'load'
            })
        return results

    if url.startswith('show_seasons||'):
        rating_key = url.split('||', 1)[1]
        data = plex_api_get(f"/library/metadata/{rating_key}/children")
        results = []
        meta_list = metadata_objects(data)
        if not meta_list:
            data_leaves = plex_api_get(f"/library/metadata/{rating_key}/allLeaves")
            meta_list = metadata_objects(data_leaves)
        _prefetch_audio_metadata(meta_list)
        for meta in meta_list:
            parsed = _format_plex_item(meta, token)
            if parsed:
                results.append(parsed)
        return results

    if url.startswith('season_episodes||'):
        rating_key = url.split('||', 1)[1]
        data = plex_api_get(f"/library/metadata/{rating_key}/children")
        results = []
        meta_list = metadata_objects(data)
        _prefetch_audio_metadata(meta_list)
        for meta in meta_list:
            parsed = _format_plex_item(meta, token)
            if parsed:
                results.append(parsed)
        return results

    return []


def _search_params(query, endpoint=''):
    p = {'query': query, 'limit': 40}
    if 'discover.provider' in endpoint:
        p.update({'searchTypes': 'movies,tv', 'searchProviders': 'discover', 'includeMetadata': 1})
    return p


def search(query='', params=None):
    _dbg(f'search() query={query!r}')
    if not query:
        return []
    token = _get_plex_guest_token()
    if not token:
        _dbg('search(): kein Gast-Token')
        return []

    endpoints = [
        'https://discover.provider.plex.tv/library/search'
    ]

    results = []
    seen_keys = set()

    for ep in endpoints:
        data = plex_api_get(ep, params=_search_params(query, ep))
        if not data:
            _dbg(f'search(): {ep} ohne Daten')
            continue
        metas = _extract_all_metadata(data)
        _prefetch_audio_metadata(metas)
        _prefetch_german_summaries(metas)
        if not metas:
            try:
                _dbg(f'search(): {ep} Rohdaten: {json.dumps(data, ensure_ascii=False)[:1500]}')
            except Exception:
                pass
        added = 0
        skipped = 0
        for meta in metas:
            rk = meta.get('ratingKey') or (meta.get('key', '').split('/')[-1] if meta.get('key') else None)
            if rk and rk not in seen_keys:
                seen_keys.add(rk)
                parsed = _format_plex_item(meta, token)
                if parsed:
                    results.append(parsed)
                    added += 1
                else:
                    skipped += 1
        _dbg(f'search(): {ep} metadata={len(metas)} neu={added} verworfen={skipped}')
    _dbg(f'search(): gesamt={len(results)} Treffer fuer {query!r}')
    return results


def _plex_search_raw(query):
    results = []
    seen_keys = set()
    for ep in ():
        data = plex_api_get(ep, params=_search_params(query, ep))
        if not data:
            continue
        for meta in _extract_all_metadata(data):
            rk = meta.get('ratingKey') or (meta.get('key', '').split('/')[-1] if meta.get('key') else None)
            if rk and rk not in seen_keys:
                seen_keys.add(rk)
                results.append(meta)
    disc = plex_api_get('https://discover.provider.plex.tv/library/search', params=_search_params(query, 'https://discover.provider.plex.tv/library/search'))
    if disc:
        for meta in _extract_all_metadata(disc):
            rk = meta.get('ratingKey') or (meta.get('key', '').split('/')[-1] if meta.get('key') else None)
            if rk and rk not in seen_keys:
                seen_keys.add(rk)
                results.append(meta)
    return results


def _norm_title(text):
    import re
    text = html.unescape(str(text or '')).lower()
    text = text.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
    text = re.sub(r'\(\d{4}\)', '', text)
    return re.sub(r'[^a-z0-9]+', '', text)


def _meta_guids(meta):
    guids = set()
    raw = meta.get('Guid') or []
    if isinstance(raw, dict):
        raw = [raw]
    for g in raw:
        if isinstance(g, dict) and g.get('id'):
            guids.add(str(g['id']).lower())
    if meta.get('guid'):
        guids.add(str(meta['guid']).lower())
    return guids


def _pick_match(candidates, want_type, title, year, imdb, tmdb):
    want_title = _norm_title(title)
    imdb = str(imdb or '').strip().lower()
    tmdb = str(tmdb or '').strip()
    try:
        want_year = int(year) if year else 0
    except (ValueError, TypeError):
        want_year = 0
    best, best_score = None, 0
    for meta in candidates:
        mtype = str(meta.get('type', '')).lower()
        if want_type == 'show' and mtype not in ('show', 'series', 'tvshow'):
            continue
        if want_type == 'movie' and mtype != 'movie':
            continue
        score = 0
        guids = _meta_guids(meta)
        if imdb and any(imdb in g for g in guids):
            score += 100
        if tmdb and any(g.endswith('tmdb://' + tmdb) or g.endswith('/' + tmdb) for g in guids):
            score += 100
        if want_title and _norm_title(meta.get('title')) == want_title:
            score += 50
        elif want_title and want_title in _norm_title(meta.get('title')):
            score += 10
        try:
            have_year = int(meta.get('year') or meta.get('parentYear') or 0)
        except (ValueError, TypeError):
            have_year = 0
        if want_year and have_year:
            if have_year == want_year:
                score += 20
            elif abs(have_year - want_year) == 1:
                score += 8
            elif want_type == 'movie':
                score -= 40
        if score > best_score:
            best, best_score = meta, score
    return best if best_score >= 50 else None


def _movie_manifests(metadata_id):
    token = _get_plex_guest_token()
    if not token:
        return []
    data = plex_api_get(f"/library/metadata/{metadata_id}")
    if not data:
        return []
    if _is_german_only() and not _has_german_audio(data):
        _dbg(f'_movie_manifests {metadata_id}: kein deutsches Audio, gefiltert (_is_german_only=True)')
        return []
    manifests = []
    for item in metadata_objects(data):
        for media in (item.get('Media') or []):
            if isinstance(media, dict):
                for part in (media.get('Part') or []):
                    if isinstance(part, dict):
                        key = part.get('key')
                        if key:
                            manifests.append(key if key.startswith('http') else f"https://vod.provider.plex.tv{key}?X-Plex-Token={token}")
    return manifests


def _find_episode_id(show_key, season, episode):
    data = plex_api_get(f"/library/metadata/{show_key}/children")
    season_key = None
    for meta in metadata_objects(data):
        if str(meta.get('type', '')).lower() == 'season' and str(meta.get('index', '')) == str(season):
            season_key = meta.get('ratingKey')
            break
    if season_key:
        eps = plex_api_get(f"/library/metadata/{season_key}/children")
        for meta in metadata_objects(eps):
            if str(meta.get('index', '')) == str(episode):
                return meta.get('ratingKey')
    leaves = plex_api_get(f"/library/metadata/{show_key}/allLeaves")
    for meta in metadata_objects(leaves):
        if str(meta.get('parentIndex', '')) == str(season) and str(meta.get('index', '')) == str(episode):
            return meta.get('ratingKey')
    return None


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    metadata_id = None
    if url and '||' in url:
        for part in url.split('||'):
            if part.startswith('live:'):
                live_url = _resolve_live(part.split('live:', 1)[1].strip())
                return [('Plex Live', live_url, True, 'HD', 'de')] if live_url else []
            if part.startswith('metadata:'):
                metadata_id = part.split('metadata:', 1)[1].strip()
                break
    elif url:
        metadata_id = url.strip()

    if not metadata_id and title:
        try:
            season = int(season or 0)
            episode = int(episode or 0)
        except (ValueError, TypeError):
            season, episode = 0, 0
        is_episode = season > 0 and episode > 0
        match = _pick_match(_plex_search_raw(title), 'show' if is_episode else 'movie', title, year, imdb, tmdb)
        if not match:
            return []
        rk = match.get('ratingKey') or (match.get('key', '').split('/')[-1] if match.get('key') else None)
        if not rk:
            return []
        metadata_id = _find_episode_id(rk, season, episode) if is_episode else rk

    if metadata_id:
        manifests = _movie_manifests(metadata_id)
        if manifests:
            return [('Plex VOD', manifests[0], True, 'HD', 'de')]
        if title:
            try:
                season = int(season or 0)
                episode = int(episode or 0)
            except (ValueError, TypeError):
                season, episode = 0, 0
            is_episode = season > 0 and episode > 0
            vod_candidates = []
            vod_seen = set()
            for ep in ('https://discover.provider.plex.tv/library/search',):
                data = plex_api_get(ep, params=_search_params(title, ep))
                if not data:
                    continue
                for meta in _extract_all_metadata(data):
                    rk = meta.get('ratingKey') or (meta.get('key', '').split('/')[-1] if meta.get('key') else None)
                    if rk and rk not in vod_seen:
                        vod_seen.add(rk)
                        vod_candidates.append(meta)
            vod_match = _pick_match(vod_candidates, 'show' if is_episode else 'movie', title, year, imdb, tmdb)
            if vod_match:
                vod_rk = vod_match.get('ratingKey') or (vod_match.get('key', '').split('/')[-1] if vod_match.get('key') else None)
                if vod_rk:
                    fallback_id = _find_episode_id(vod_rk, season, episode) if is_episode else vod_rk
                    if fallback_id:
                        manifests = _movie_manifests(fallback_id)
                        if manifests:
                            return [('Plex VOD', manifests[0], True, 'HD', 'de')]
    return []
