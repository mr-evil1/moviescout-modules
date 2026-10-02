# -*- coding: utf-8 -*-
import re
import json as _json
import html as _html
import xbmcgui
from urllib.parse import quote, unquote
from resources.lib import log
from resources.lib import multiquest as _mq

SITE_ID       = 'moflix-stream'
SITE_NAME     = 'Moflix-Stream'
SITE_DOMAIN   = 'moflix-stream.xyz'
TYPE          = 'both'
GLOBAL_SEARCH = True
SCRAPER_TIMEOUT = 10

_BASE = 'https://' + SITE_DOMAIN
_API  = _BASE + '/api/v1/'

_CH_MOVIES = 345
_CH_SERIES = 346
_CH_TOP10  = 10189
_CH_NEU    = 354

_URL_CH       = _API + 'channel/%s?returnContentOnly=true&restriction=&order=%s&perPage=50&query=&page=%d'
_URL_TOP10    = _API + 'channel/%d?top10Days=1&perPage=20&page=1&restriction=&order=popularity:desc&paginate=simple&returnContentOnly=true' % _CH_TOP10
_URL_NEU      = _API + 'channel/%d?restriction=&order=channelables.created_at:desc&page=1&paginate=simple&returnContentOnly=true' % _CH_NEU
_URL_HOMEPAGE = _API + 'channel/homepage'
_URL_TITLE    = _API + 'titles/%s?load=images,genres,productionCountries,keywords,videos,primaryVideo,seasons,compactCredits'
_URL_EPS_LIST = _API + 'titles/%s/seasons/%s/episodes?perPage=100&query=&page=1'
_URL_EPISODE  = _API + 'titles/%s/seasons/%s/episodes/%s?load=videos,compactCredits,primaryVideo'

_S_MOVIES   = '__mfx_movies__'
_S_SERIES   = '__mfx_series__'
_S_COLLS    = '__mfx_colls__'
_S_SEASONS  = '__mfx_seasons__:'
_S_EPISODES = '__mfx_eps__:'

_MENU_CHANNELS = {'now-playing', 'movies', 'top-rated-movies', 'top-10-movies-serien', 'trending-tv', 'series'}

_session_cookies = {}
_xsrf_token      = ''
_session_ok      = False

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'

_BASE_HEADERS = {
    'User-Agent':          _UA,
    'Accept-Language':     'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
    'Origin':              _BASE,
    'Referer':             _BASE + '/',
    'sec-ch-ua':           '"Not A(Brand";v="8", "Chromium";v="143", "Google Chrome";v="143"',
    'sec-ch-ua-mobile':    '?0',
    'sec-ch-ua-platform':  '"Windows"',
    'sec-fetch-site':      'same-origin',
    'sec-fetch-mode':      'cors',
    'sec-fetch-dest':      'empty',
}


def _init_session():
    global _xsrf_token, _session_cookies, _session_ok
    try:
        headers = dict(_BASE_HEADERS)
        headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        headers['sec-fetch-mode'] = 'navigate'
        headers['sec-fetch-dest'] = 'document'
        
        resp = _mq.get(_BASE + '/', headers=headers, timeout=8, use_cf=True)
        if resp:
            if hasattr(resp, 'cookies') and resp.cookies:
                for k, v in resp.cookies.items():
                    _session_cookies[k] = v
                    if k == 'XSRF-TOKEN':
                        _xsrf_token = unquote(v)
            elif hasattr(resp, 'headers'):
                cookie_header = ''
                for k, v in resp.headers.items():
                    if k.lower() == 'set-cookie':
                        cookie_header += str(v) + ', '
                for match in re.finditer(r'([a-zA-Z0-9_\-]+)=([^;,\s]+)', cookie_header):
                    k = match.group(1)
                    v = match.group(2)
                    if k.lower() not in ['path', 'expires', 'domain', 'max-age', 'samesite', 'secure', 'httponly']:
                        _session_cookies[k] = v
                        if k == 'XSRF-TOKEN':
                            _xsrf_token = unquote(v)
    except Exception:
        pass
    _session_ok = True


def _get(url, referer=None, as_html=False, as_inertia=False):
    global _session_ok, _session_cookies
    if not _session_ok:
        _init_session()
        
    headers = dict(_BASE_HEADERS)
    if referer:
        headers['Referer'] = referer
        
    if as_html:
        headers.pop('X-Requested-With', None)
        headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        headers['sec-fetch-mode'] = 'navigate'
        headers['sec-fetch-dest'] = 'document'
        
    if as_inertia:
        headers['X-Inertia'] = 'true'
        headers['Accept'] = 'text/html, application/xhtml+xml, application/json'

    if _session_cookies:
        headers['Cookie'] = '; '.join([f"{k}={v}" for k, v in _session_cookies.items()])

    try:
        resp = _mq.get(url, headers=headers, timeout=10, use_cf=True)
        return getattr(resp, 'text', '') if resp else ''
    except Exception:
        return ''


def _get_json(url, referer=None, as_inertia=False):
    text = _get(url, referer=referer, as_html=False, as_inertia=as_inertia)
    if not text:
        return None
    try:
        return _json.loads(text)
    except Exception:
        if as_inertia or '<html' in text.lower():
            return text
    return None


def _fix_poster(src):
    if not src:
        return ''
    if src.startswith('http'):
        return src
    return _BASE + '/' + src.lstrip('/')


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _quality(s):
    s = (s or '').upper()
    if '2160' in s or '4K' in s:
        return '4K'
    if '1080' in s:
        return '1080p'
    if '720' in s:
        return '720p'
    return 'HD'


def _lang_from_name(name):
    m = re.search(r'-([a-z]{2})(?:\s|$)', (name or '').lower())
    if m:
        return m.group(1)
    return 'de'


def _next_url(url, next_page):
    if re.search(r'[?&]page=', url):
        return re.sub(r'([?&]page=)\d+', r'\g<1>' + str(next_page), url)
    sep = '&' if '?' in url else '?'
    return url + sep + 'page=' + str(next_page)


def _parse_items(data):
    items = []
    for i in data:
        if not isinstance(i, dict):
            continue
            
        sId = str(i.get('id') or i.get('title_id') or '')
        sName = (i.get('name') or i.get('title') or '').strip()
        
        if not sId or not sName:
            continue
            
        m_type = str(i.get('model_type', '')).lower()
        if 'person' in m_type:
            continue
            
        is_series = bool(i.get('is_series')) or m_type in ('series', 'tv', 'tvshow')
        
        poster = _fix_poster(i.get('poster') or i.get('image') or '')
        fanart = _fix_poster(i.get('backdrop') or '')
        year = str((i.get('release_date') or i.get('year') or '')[:4]).strip()
        desc = i.get('description') or ''
        rating = i.get('rating')
        runtime = i.get('runtime')
        
        url_dest = _S_SEASONS + _URL_TITLE % sId if is_series else _URL_TITLE % sId
        
        item = {
            'title':       sName,
            'year':        year,
            'url':         url_dest,
            'poster':      poster,
            'fanart':      fanart,
            'mediatype':   'tvshow' if is_series else 'movie',
            'is_playable': not is_series,
            'next_func':   'load' if is_series else 'get_hosters',
        }
        if desc:
            item['plot'] = desc
        if rating is not None:
            item['rating'] = str(rating)
        if runtime is not None:
            item['duration'] = str(runtime)
        items.append(item)
    return items


def _fetch_channel_page(url):
    r = _get_json(url)
    if not r or not isinstance(r, dict):
        return [{'title': '[B]Fehler: Daten konnten nicht geladen werden[/B]', 'is_playable': False}]
    pag = (r or {}).get('pagination') or {}
    data = pag.get('data') or []
    items = _parse_items(data)
    next_pg = pag.get('next_page')
    if next_pg and items:
        items.append({
            'title':       '[B]>>> Weiter[/B]',
            'url':         _next_url(url, next_pg),
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def _fetch_seasons(title_api_url):
    r = _get_json(title_api_url)
    if not r or not isinstance(r, dict):
        return [], ''
    poster = _fix_poster((r.get('title') or {}).get('poster') or '')
    seasons_data = (r.get('seasons') or {}).get('data') or []
    next_pg = (r.get('seasons') or {}).get('next_page')
    while next_pg:
        r2 = _get_json(title_api_url + '&page=' + str(next_pg))
        if not r2 or not isinstance(r2, dict) or not r2.get('seasons'):
            break
        seasons_data += (r2['seasons'].get('data') or [])
        next_pg = r2['seasons'].get('next_page')
    seasons_data = sorted(seasons_data, key=lambda k: k.get('number', 0))
    return seasons_data, poster


def _get_seasons(title_api_url):
    seasons_data, poster = _fetch_seasons(title_api_url)
    items = []
    for s in seasons_data:
        title_id = str(s.get('title_id') or '')
        season_nr = str(s.get('number') or '')
        if not title_id or not season_nr:
            continue
        items.append({
            'title':       'Staffel ' + season_nr,
            'url':         _S_EPISODES + title_id + '|' + season_nr + '|' + poster,
            'poster':      poster,
            'mediatype':   'season',
            'is_playable': False,
            'next_func':   'load',
        })
    return items


def _get_episodes(encoded):
    parts = encoded.split('|', 2)
    if len(parts) < 2:
        return []
    title_id = parts[0]
    season_nr = parts[1]
    poster = parts[2] if len(parts) > 2 else ''
    r = _get_json(_URL_EPS_LIST % (title_id, season_nr))
    if not r or not isinstance(r, dict):
        return []
    data = (r.get('pagination') or {}).get('data') or []
    items = []
    for i in data:
        if i.get('primary_video') is None:
            continue
        ep_nr = str(i.get('episode_number') or '')
        ep_name = (i.get('name') or '').strip()
        ep_title = 'Folge ' + ep_nr
        if ep_name:
            ep_title += ' - ' + ep_name
        ep_poster = _fix_poster(i.get('poster') or '') or poster
        item = {
            'title':       ep_title,
            'url':         _URL_EPISODE % (title_id, season_nr, ep_nr),
            'poster':      ep_poster,
            'mediatype':   'episode',
            'is_playable': True,
            'next_func':   'get_hosters',
        }
        if i.get('description'):
            item['plot'] = i['description']
        if i.get('runtime') is not None:
            item['duration'] = str(i['runtime'])
        if i.get('rating') is not None:
            item['rating'] = str(i['rating'])
        items.append(item)
    return items


def _get_collections():
    r = _get_json(_URL_HOMEPAGE)
    if not r or not isinstance(r, dict):
        return []
    channels = ((r.get('channel') or {}).get('content', {})).get('data') or []
    items = []
    for ch in channels:
        cfg = ch.get('config') or {}
        if cfg.get('layout') != 'grid' or cfg.get('contentModel') == 'newsArticle':
            continue
        if cfg.get('autoUpdateMethod') in ('moflixTop10', 'upcoming'):
            continue
        if ch.get('slug') in _MENU_CHANNELS:
            continue
        sName = (ch.get('name') or '').strip()
        ch_id = ch.get('id')
        sSlug = ch.get('slug') or ''
        if not sName or not (ch_id or sSlug):
            continue
        ident = str(ch_id) if ch_id else sSlug
        items.append({
            'title':       sName,
            'url':         _URL_CH % (ident, 'popularity:desc', 1),
            'next_func':   'load',
            'is_playable': False,
            'plot':        'Thematische Sammlung von Inhalten: ' + sName,
        })
    return sorted(items, key=lambda x: x['title'].lower())


def _parse_videos(videos):
    hosters = []
    for v in (videos or []):
        src = (v.get('src') or '').strip()
        if not src or 'youtube' in src:
            continue
        name = (v.get('name') or '').strip()
        if 'no ads' in name.lower() or 'premium' in name.lower():
            continue
        quality = _quality(v.get('quality') or '')
        if 'Mirror' in name:
            hoster = re.sub(r'^(?:https?://)?(?:www\.)?([^/]+).*', r'\1', src)
        else:
            hoster = name.split('-')[0].strip()
        lang = _lang_from_name(name)
        hosters.append((hoster, src, False, quality, lang))
    return hosters


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Suche',        'url': '',          'next_func': 'search', 'is_playable': False, 'plot': 'Durchsuche die gesamte Mediathek nach Filmen und Serien.'},
            {'title': 'Neu',          'url': _URL_NEU,    'next_func': 'load', 'is_playable': False, 'plot': 'Die neuesten und kürzlich hinzugefügten Inhalte der Plattform.'},
            {'title': 'Filme',        'url': _S_MOVIES,   'next_func': 'load', 'is_playable': False, 'plot': 'Übersicht aller verfügbaren Spielfilme, sortiert nach Kategorien.'},
            {'title': 'Top 10',       'url': _URL_TOP10,  'next_func': 'load', 'is_playable': False, 'plot': 'Die aktuell beliebtesten Top 10 Filme und Serien.'},
            {'title': 'Serien',       'url': _S_SERIES,   'next_func': 'load', 'is_playable': False, 'plot': 'Übersicht aller verfügbaren Serien und Staffeln.'},
            {'title': 'Kollektionen', 'url': _S_COLLS,    'next_func': 'load', 'is_playable': False, 'plot': 'Thematisch sortierte Sammlungen und Filmreihen.'},
        ]
    if url == _S_MOVIES:
        return [
            {'title': 'Alle Filme',  'url': _URL_CH % (_CH_MOVIES, 'popularity:desc', 1),  'next_func': 'load', 'is_playable': False, 'plot': 'Alle verfügbaren Filme nach Beliebtheit sortiert.'},
            {'title': 'Top Filme',   'url': _URL_CH % (_CH_MOVIES, 'rating:desc', 1),       'next_func': 'load', 'is_playable': False, 'plot': 'Die am besten bewerteten Filme aller Zeiten.'},
            {'title': 'Neue Filme',  'url': _URL_CH % (_CH_MOVIES, 'created_at:desc', 1),   'next_func': 'load', 'is_playable': False, 'plot': 'Die frisch eingetroffenen Film-Neuheiten.'},
            {'title': 'Blockbuster', 'url': _URL_CH % (_CH_MOVIES, 'revenue:desc', 1),      'next_func': 'load', 'is_playable': False, 'plot': 'Die erfolgreichsten Blockbuster nach Einspielergebnis.'},
        ]
    if url == _S_SERIES:
        return [
            {'title': 'Alle Serien', 'url': _URL_CH % (_CH_SERIES, 'popularity:desc', 1),  'next_func': 'load', 'is_playable': False, 'plot': 'Alle verfügbaren Serien nach Beliebtheit sortiert.'},
            {'title': 'Top Serien',  'url': _URL_CH % (_CH_SERIES, 'rating:desc', 1),       'next_func': 'load', 'is_playable': False, 'plot': 'Die am besten bewerteten Serien.'},
            {'title': 'Neue Serien', 'url': _URL_CH % (_CH_SERIES, 'created_at:desc', 1),   'next_func': 'load', 'is_playable': False, 'plot': 'Die frisch eingetroffenen Serien-Neuheiten.'},
        ]
    if url == _S_COLLS:
        return _get_collections()
    if url.startswith(_S_SEASONS):
        return _get_seasons(url[len(_S_SEASONS):])
    if url.startswith(_S_EPISODES):
        return _get_episodes(url[len(_S_EPISODES):])
    return _fetch_channel_page(url)


def _extract_items(data):
    items = []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ['results', 'data', 'titles', 'movies', 'series']:
            if key in data:
                val = data[key]
                if isinstance(val, list):
                    items.extend(val)
                elif isinstance(val, dict) and 'data' in val and isinstance(val['data'], list):
                    items.extend(val['data'])
        if not items:
            for k, v in data.items():
                if isinstance(v, list):
                    items.extend(v)
                elif isinstance(v, dict) and 'data' in v and isinstance(v['data'], list):
                    items.extend(v['data'])
    return items


def _do_search(query):
    results = []
    query_path = quote(query)
    search_page_url = _BASE + '/search/' + query_path
    
    text = _get(search_page_url, as_html=True)
    if text:
        m = re.search(r'window\.bootstrapData\s*=\s*(\{.+?\});\s*</script>', text, re.DOTALL)
        if m:
            try:
                data = _json.loads(m.group(1))
                search_page = data.get('loaders', {}).get('searchPage', {})
                ext = search_page.get('results', [])
                if isinstance(ext, list):
                    results.extend(ext)
            except Exception:
                pass

    if not results and text:
        def _deep_extract(d):
            found = []
            if isinstance(d, dict):
                if 'results' in d and isinstance(d['results'], list):
                    found.extend(d['results'])
                for k, v in d.items():
                    found.extend(_deep_extract(v))
            elif isinstance(d, list):
                for item in d:
                    found.extend(_deep_extract(item))
            return found
            
        try:
            m = re.search(r'window\.bootstrapData\s*=\s*(\{.+?\});\s*</script>', text, re.DOTALL)
            if m:
                data = _json.loads(m.group(1))
                results.extend(_deep_extract(data))
        except Exception:
            pass

    final = []
    seen = set()
    for i in results:
        if not isinstance(i, dict):
            continue
        i_id = str(i.get('id') or i.get('title_id') or '')
        m_type = str(i.get('model_type', '')).lower()
        if not i_id or 'person' in m_type: 
            continue
        if i_id not in seen:
            seen.add(i_id)
            final.append(i)
            
    return final


def _find_match_id(items, ct, years_ok, season):
    for i in items:
        m_type = str(i.get('model_type', '')).lower()
        if 'person' in m_type:
            continue
            
        iname = _cleantitle(i.get('name') or i.get('title') or '')
        if ct not in iname and iname not in ct:
            continue
            
        iyear = str((i.get('release_date') or i.get('year') or '')[:4])
        if years_ok and iyear and iyear not in years_ok:
            continue
            
        is_series = bool(i.get('is_series')) or m_type in ('series', 'tv', 'tvshow')
        if season and not is_series:
            continue
            
        return str(i.get('id') or i.get('title_id'))
    return None


_MATCH_CACHE = {}


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if url and not url.startswith('__'):
        r = _get_json(url)
        if not r or not isinstance(r, dict):
            return []
        if '/seasons/' in url and '/episodes/' in url:
            videos = (r.get('episode') or {}).get('videos') or []
        else:
            videos = (r.get('title') or {}).get('videos') or []
        return _parse_videos(videos)

    if not title:
        return []

    ct = _cleantitle(title)
    years_ok = {str(year), str(int(year or 0) + 1)} if year and not season else set()

    cache_key = (ct, tuple(sorted(years_ok)), bool(season))
    if cache_key in _MATCH_CACHE:
        match_id = _MATCH_CACHE[cache_key]
    else:
        results = _do_search(title)
        match_id = _find_match_id(results, ct, years_ok, season)
        _MATCH_CACHE[cache_key] = match_id

    if not match_id:
        return []

    r_title = _get_json(_URL_TITLE % match_id)
    if not r_title or not isinstance(r_title, dict):
        return []

    if not season:
        videos = (r_title.get('title') or {}).get('videos') or []
        return _parse_videos(videos)

    seasons_data = (r_title.get('seasons') or {}).get('data') or []
    next_pg = (r_title.get('seasons') or {}).get('next_page')
    while next_pg:
        r2 = _get_json(_URL_TITLE % match_id + '&page=' + str(next_pg))
        if not r2 or not isinstance(r2, dict) or not r2.get('seasons'):
            break
        seasons_data += (r2['seasons'].get('data') or [])
        next_pg = r2['seasons'].get('next_page')

    title_id = match_id
    for s in seasons_data:
        if str(s.get('number')) == str(season):
            title_id = str(s.get('title_id') or match_id)
            break

    r_ep = _get_json(_URL_EPISODE % (title_id, season, episode))
    if not r_ep or not isinstance(r_ep, dict):
        return []
    videos = (r_ep.get('episode') or {}).get('videos') or []
    return _parse_videos(videos)


def search(query='', params=None, url=''):
    if not query and url and not url.startswith('__'):
        query = url
    if not query:
        try:
            dialog = xbmcgui.Dialog()
            result = dialog.input(SITE_NAME + ' Suche')
            if result:
                query = result.strip()
        except Exception:
            pass
    if not query:
        return []

    results = _do_search(query)
    results = sorted(results, key=lambda x: (x.get('name') or x.get('title') or '').lower())
    
    parsed = _parse_items(results)
    if not parsed:
        return [{'title': '[B]Keine Ergebnisse für: ' + query + '[/B]', 'is_playable': False}]
        
    return parsed


def get_details(url='', params=None):
    if not url or url.startswith('__'):
        return {}
    real_url = url
    if real_url.startswith(_S_SEASONS):
        real_url = real_url[len(_S_SEASONS):]
    if '/seasons/' in real_url and '/episodes/' in real_url:
        return {}
    r = _get_json(real_url)
    if not r or not isinstance(r, dict):
        return {}
    title_data = r.get('title') or {}
    result = {}
    if title_data.get('description'):
        result['plot'] = title_data['description']
    poster = _fix_poster(title_data.get('poster') or '')
    if poster:
        result['poster'] = poster
    return result
