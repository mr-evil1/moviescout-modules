# -*- coding: utf-8 -*-
import re
from html import unescape
from urllib.parse import quote, urlparse
import xbmcgui
from resources.lib import multiquest, log

SITE_ID       = 'movie2k'
SITE_NAME     = 'Movie2k'
SITE_DOMAIN   = 'movie2k.cx'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

_S_MOVIES  = '__m2k_movies__'
_S_SERIES  = '__m2k_series__'
_S_NEW     = '__m2k_new__'
_S_SEARCH  = '__m2k_search__'
_S_ENTRIES = '__m2k_entries__:'
_S_UPDATES = '__m2k_updates__:'
_S_TILES   = '__m2k_tiles__:'
_S_GENRES  = '__m2k_genres__:'
_S_SEASONS = '__m2k_seasons__:'
_S_EPS     = '__m2k_eps__:'

_PANE_UPDATES = 'tab-updates'
_PANE_CINEMA  = 'tab-cinema'
_PANE_POPULAR = 'tab-popular'

_RE_ENTRY = (r'<td width="115" valign="top">\s*<img src="([^"]+)"[^>]*>\s*</td>\s*'
             r'<td valign="top">\s*<h2[^>]*>\s*(?:<!--[^>]*-->\s*)?'
             r'<a href="([^"]+)"[^>]*>(.*?)</a>(.*?)</h2>\s*'
             r'<div class="beschreibung"[^>]*>(.*?)</span>')
_RE_GENRE = r'<a href="([^"]+)" class="genre-item">\s*<div class="genre-name">([^<]+)</div>'
_RE_SEASON_BOX = r'<select id="season-select".*?</select>'
_RE_EPISODE_BOX = r'<select id="episode-select".*?</select>'
_RE_SEASON_OPT = r'<option[^>]*>\s*S(\d+)\s*</option>'
_RE_EPISODE_OPT = r'<option value="([^"]+)"[^>]*data-name="([^"]*)"[^>]*data-overview="([^"]*)"[^>]*>\s*E(\d+)'
_RE_MOVIE_HOSTER = r'<option value="(http[^"]+)"[^>]*data-quality="([^"]*)"'
_RE_EPISODE_BLOCK = r'data-episode-id="%s"(.*?)</table>'
_RE_EPISODE_HOSTER = r'''loadMirror\('(http[^']+)'\)"\s*data-host="[^"]+"\s*data-mirror="true"'''
_RE_SERIES_MARK = r'type=(?:tv|series)'
_RE_UPDATE = (r'<td valign="top" height="100%">\s*<a href="([^"]+)">\s*'
              r'<font[^>]*>\s*<strong>(.*?)</strong>\s*</font>\s*'
              r'(?:<font[^>]*>[^<]+</font>\s*)?</a>')
_RE_TILE = (r'<img src="([^"]+)"[^>]*>\s*</a>\s*</div>\s*<div[^>]*>\s*'
            r'<h2[^>]*>\s*<a href="([^"]+)">\s*'
            r'<font[^>]*>\s*<strong>(.*?)</strong>\s*</font>\s*'
            r'(?:<font[^>]*>[^<]+</font>\s*)?</a>')
_RE_OG_IMAGE = r'<meta property="og:image" content="([^"]+)"'
_RE_DESC = r'<div class="beschreibung"[^>]*>(.*?)</div>'
_RE_YEAR = r'\|\s*(\d{4})\s*(?:&nbsp;)?\|'
_RE_RATING = r'Bewertung:\s*([\d.,]+)'

_SEARCH_PROP = 'moviescout.movie2k.lastSearchText'

_QUALITY = {'hd': '720p', 'sd': '480p', 'dvd': 'DVD', 'cam': 'CAM'}


def _base():
    return 'https://' + SITE_DOMAIN


def _get(url, referer=None):
    headers = {'User-Agent': _UA, 'Referer': referer or _base() + '/'}
    try:
        r = multiquest.get(url, headers=headers, timeout=12)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _parse(html, pattern):
    return re.findall(pattern, html or '', re.S)


def _first(html, pattern):
    m = re.search(pattern, html or '', re.S)
    if not m:
        return ''
    return m.group(1) if m.groups() else m.group(0)


def _text(s):
    return unescape(re.sub(r'<[^>]+>', '', s or '')).strip()


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _absolute(url):
    url = unescape(url or '')
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('/'):
        return _base() + url
    return url


def _request_url(url):
    url = re.sub(r'(/stream/)([^?]*)',
                 lambda m: m.group(1) + m.group(2).replace('/', '-').replace('#', '-'), url)
    return quote(url, safe=':/?&=%#+')


def _split(value):
    if '|' in value:
        u, p = value.rsplit('|', 1)
        return u, p
    return value, ''


def _pane_content(html, pane_id):
    m = re.search(r'<div[^>]*id="%s"[^>]*>' % pane_id, html or '')
    if not m:
        return ''
    start = m.end()
    depth = 1
    for tag in re.finditer(r'<div\b|</div>', html[start:]):
        depth += 1 if tag.group(0) == '<div' else -1
        if depth == 0:
            return html[start:start + tag.start()]
    return html[start:]


def _next_page(html, url):
    m = re.search(r'[?&]page=(\d+)', url)
    nxt = (int(m.group(1)) if m else 1) + 1
    link = _first(html, r'href="([^"]*[?&]page=%d)"' % nxt)
    if not link:
        return ''
    link = unescape(link)
    if link.startswith('?'):
        link = url.split('?')[0] + link
    return _absolute(link)


def _make_item(name, link, poster='', year='', rating=0.0, plot=''):
    is_series = bool(re.search(_RE_SERIES_MARK, link))
    url = _absolute(link)
    if poster and 'placehold' in poster:
        poster = ''
    item = {
        'title':  name,
        'poster': _absolute(poster) if poster else '',
        'year':   year,
        'plot':   plot,
        'rating': rating,
    }
    if is_series:
        item.update({
            'url':         _S_SEASONS + url,
            'mediatype':   'tvshow',
            'is_playable': False,
            'next_func':   'load',
        })
    else:
        item.update({
            'url':         url,
            'mediatype':   'movie',
            'is_playable': True,
            'next_func':   'get_hosters',
        })
    return item


def _folder(title, url):
    return {'title': title, 'url': url, 'next_func': 'load', 'is_playable': False}


def _entries(url, pane='', keyword=''):
    html = _get(_request_url(url))
    if pane:
        html = _pane_content(html, pane)
    seen = set()
    items = []
    for thumb, link, title, head_rest, desc in _parse(html, _RE_ENTRY):
        if link in seen:
            continue
        seen.add(link)
        name = _text(title).replace('[SERIE]', '').strip()
        if not name:
            continue
        if keyword and _cleantitle(keyword) not in _cleantitle(name):
            continue
        year = _first(desc, _RE_YEAR)
        try:
            rating = float(_first(desc, _RE_RATING).replace(',', '.'))
        except Exception:
            rating = 0.0
        items.append(_make_item(name, link, thumb, year, rating))
    if items and not keyword:
        nxt = _next_page(html, url)
        if nxt:
            items.append(_folder('[B]>>> Weiter[/B]', _S_ENTRIES + nxt))
    return items


def _updates(url):
    html = _pane_content(_get(_request_url(url)), _PANE_UPDATES)
    seen = set()
    items = []
    for link, title in _parse(html, _RE_UPDATE):
        key = link.split('?')[0]
        if key in seen:
            continue
        seen.add(key)
        name = _text(title)
        if not name:
            continue
        items.append(_make_item(name, link))
    return items


def _tiles(url):
    html = _pane_content(_get(_request_url(url)), _PANE_POPULAR)
    seen = set()
    items = []
    for thumb, link, title in _parse(html, _RE_TILE):
        key = link.split('?')[0]
        if key in seen:
            continue
        seen.add(key)
        name = _text(title)
        if not name:
            continue
        items.append(_make_item(name, link, thumb))
    return items


def _genres(url):
    html = _get(_request_url(url))
    return [_folder(_text(name), _S_ENTRIES + _absolute(link)) for link, name in _parse(html, _RE_GENRE)]


def _poster_of(html):
    poster = _first(html, _RE_OG_IMAGE)
    if not poster or 'placehold' in poster:
        return ''
    return poster


def _seasons(url):
    html = _get(_request_url(url))
    box = _first(html, _RE_SEASON_BOX)
    seasons = _parse(box, _RE_SEASON_OPT)
    if not seasons:
        return []
    poster = _poster_of(html)
    plot = _text(_first(html, _RE_DESC))
    base = url.split('?')[0]
    items = []
    for s in seasons:
        item = {
            'title':       'Staffel %s' % s,
            'url':         _S_EPS + '%s?season=%s' % (base, s),
            'poster':      poster,
            'mediatype':   'season',
            'season':      int(s),
            'is_playable': False,
            'next_func':   'load',
        }
        if plot:
            item['plot'] = plot
        items.append(item)
    return items


def _episodes(url):
    html = _get(_request_url(url))
    box = _first(html, _RE_EPISODE_BOX)
    episodes = _parse(box, _RE_EPISODE_OPT)
    if not episodes:
        return []
    poster = _poster_of(html)
    sm = re.search(r'[?&]season=(\d+)', url)
    season = int(sm.group(1)) if sm else 1
    items = []
    for _id, name, overview, e in episodes:
        label = 'S%02dE%02d' % (season, int(e))
        name = _text(name)
        if name:
            label += ' - ' + name
        item = {
            'title':       label,
            'url':         url,
            'poster':      poster,
            'mediatype':   'episode',
            'is_playable': True,
            'next_func':   'get_hosters',
            'season':      season,
            'episode':     int(e),
        }
        overview = _text(overview)
        if overview:
            item['plot'] = overview
        items.append(item)
    return items


def _movies_menu():
    return [
        _folder('Alle Filme', _S_ENTRIES + _base() + '/movies'),
        _folder('Kinofilme', _S_ENTRIES + _base() + '|' + _PANE_CINEMA),
        _folder('Beliebt', _S_TILES + _base()),
        _folder('Genre', _S_GENRES + _base() + '/genres'),
    ]


def _series_menu():
    return [
        _folder('Alle Serien', _S_ENTRIES + _base() + '/tv/all'),
        _folder('Beliebt', _S_ENTRIES + _base() + '/tv|' + _PANE_CINEMA),
        _folder('Im Trend', _S_TILES + _base() + '/tv'),
        _folder('Genre', _S_GENRES + _base() + '/tv/genres'),
    ]


def _new_menu():
    return [
        _folder('Filme', _S_UPDATES + _base()),
        _folder('Serien', _S_UPDATES + _base() + '/tv'),
    ]


def _search_menu():
    win = xbmcgui.Window(10000)
    text = win.getProperty(_SEARCH_PROP)
    if not text:
        text = xbmcgui.Dialog().input('Suche', type=xbmcgui.INPUT_ALPHANUM)
        if not text:
            return []
        win.setProperty(_SEARCH_PROP, text)
    return search(text)


def load(url='', params=None):
    if not url:
        xbmcgui.Window(10000).clearProperty(_SEARCH_PROP)
        return [
            _folder('Neu auf der Seite', _S_NEW),
            _folder('Filme', _S_MOVIES),
            _folder('Serien', _S_SERIES),
            _folder('Suche', _S_SEARCH),
        ]
    if url == _S_NEW:     return _new_menu()
    if url == _S_MOVIES:  return _movies_menu()
    if url == _S_SERIES:  return _series_menu()
    if url == _S_SEARCH:  return _search_menu()
    if url.startswith(_S_ENTRIES):
        target, pane = _split(url[len(_S_ENTRIES):])
        return _entries(target, pane)
    if url.startswith(_S_UPDATES): return _updates(url[len(_S_UPDATES):])
    if url.startswith(_S_TILES):   return _tiles(url[len(_S_TILES):])
    if url.startswith(_S_GENRES):  return _genres(url[len(_S_GENRES):])
    if url.startswith(_S_SEASONS): return _seasons(url[len(_S_SEASONS):])
    if url.startswith(_S_EPS):     return _episodes(url[len(_S_EPS):])
    return []


def _find_url(title, year, season):
    clean = _cleantitle(title)
    html = _get(_request_url(_base() + '/search?q=' + quote(title)))
    for thumb, link, t, head_rest, desc in _parse(html, _RE_ENTRY):
        name = _text(t).replace('[SERIE]', '').strip()
        if _cleantitle(name) != clean:
            continue
        is_series = bool(re.search(_RE_SERIES_MARK, link))
        if bool(season) != is_series:
            continue
        if not season and year:
            y = _first(desc, _RE_YEAR)
            try:
                if y and abs(int(y) - int(year)) > 1:
                    continue
            except Exception:
                pass
        return _absolute(link)
    return ''


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    season_i  = int(season or 0)
    episode_i = int(episode or 0)

    page = url if (url and not url.startswith('__')) else ''
    if not page and title:
        page = _find_url(title, year, season_i)
    if not page:
        return []
    if season_i:
        base = page.split('?')[0]
        qs = re.sub(r'[?&]season=\d+', '', page[len(base):])
        page = base + qs + ('&' if qs else '?') + 'season=%d' % season_i

    html = _get(_request_url(page))
    if not html:
        return []

    found = []
    if episode_i:
        box = _first(html, _RE_EPISODE_BOX)
        ep_id = ''
        for eid, name, overview, e in _parse(box, _RE_EPISODE_OPT):
            if int(e) == episode_i:
                ep_id = eid
                break
        if not ep_id:
            return []
        block = _first(html, _RE_EPISODE_BLOCK % re.escape(ep_id))
        for link in _parse(block, _RE_EPISODE_HOSTER):
            found.append((link, 'HD'))
    else:
        for link, q in _parse(html, _RE_MOVIE_HOSTER):
            found.append((link, _QUALITY.get(q.lower(), 'HD')))

    result = []
    seen = set()
    for link, quality in found:
        link = re.sub(r'^(https?:)/+', r'\1//', link)
        if 'youtube' in link.lower() or link in seen:
            continue
        seen.add(link)
        hostname = urlparse(link).hostname or ''
        hoster = '.'.join(hostname.split('.')[-2:]) if hostname else SITE_NAME
        result.append((hoster, link, False, quality, 'de'))
    return result


def search(query='', params=None):
    if not query or not query.strip():
        return []
    return _entries(_base() + '/search?q=' + quote(query), keyword=query)


def get_details(url='', params=None):
    if not url or url.startswith('__'):
        return {}
    page = url
    for prefix in (_S_SEASONS, _S_EPS):
        if url.startswith(prefix):
            page = url[len(prefix):]
            break
    html = _get(_request_url(page))
    if not html:
        return {}
    result = {}
    plot = _text(_first(html, _RE_DESC))
    if plot:
        result['plot'] = plot
    poster = _poster_of(html)
    if poster:
        result['poster'] = poster
    return result
