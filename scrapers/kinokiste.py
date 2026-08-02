# -*- coding: utf-8 -*-
import re
import json as _json
from urllib.parse import quote, urlparse
from resources.lib import multiquest, log

SITE_ID       = 'kinokiste'
SITE_NAME     = 'KinoKiste'
SITE_DOMAIN   = 'kinokiste.club'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA   = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
_TMDB = 'https://image.tmdb.org/t/p/w500'

_BROKEN = {
    'firestream.to',
    'flyfile.app',
}

_QUALITY_MAP = [
    ('4K',    ['4k', 'uhd', '2160']),
    ('1080p', ['1080']),
    ('720p',  ['720']),
    ('HD',    ['hd', 'web', 'webrip', 'bluray', 'bdrip', 'brrip']),
    ('SD',    ['sd', 'dvd', 'dvdrip']),
    ('TS',    ['ts', 'telesync', 'tc']),
    ('CAM',   ['cam']),
]

_S_FILME        = '__kk_filme__'
_S_SERIEN       = '__kk_serien__'
_S_BROWSE       = '__kk_browse__:'
_S_SEASONS      = '__kk_seasons__:'
_S_EPS          = '__kk_eps__:'
_S_GENRE_FILME  = '__kk_gf__'
_S_GENRE_SERIEN = '__kk_gs__'
_S_GENRE_LIST   = '__kk_gl__:'
_S_JAHRE        = '__kk_jahre__'

_GENRES = [
    'Action', 'Abenteuer', 'Animation', 'Biographie', 'Dokumentation',
    'Drama', 'Familie', 'Fantasy', 'Geschichte', 'Horror',
    'Komoedie', 'Krieg', 'Krimi', 'Musik', 'Mystery',
    'Reality-TV', 'Romantik', 'Sci-Fi', 'Sport', 'Thriller', 'Western',
]

_SORT_ORDERS = [
    ('Trending',  'Trending'),
    ('Neu',       'new'),
    ('Aufrufe',   'views'),
    ('Bewertung', 'rating'),
    ('Votes',     'votes'),
    ('Updates',   'updates'),
    ('Name',      'name'),
    ('Featured',  'featured'),
    ('Angefragt', 'requested'),
    ('Releases',  'releases'),
]


def _base():
    return 'https://' + SITE_DOMAIN


def _api(path, referer=None):
    headers = {
        'User-Agent': _UA,
        'Accept': 'application/json, text/plain, */*',
        'Referer': referer or _base() + '/',
        'Origin': _base(),
    }
    try:
        r = multiquest.get(_base() + path, headers=headers, timeout=12)
        r.raise_for_status()
        ct = r.headers.get('content-type', '')
        if 'json' in ct:
            return r.json()
        text = r.text.strip()
        if text.startswith(('{', '[')):
            return _json.loads(text)
        return None
    except Exception:
        log.error()
        return None


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _parse_quality(raw):
    s = (raw or '').lower()
    for label, keys in _QUALITY_MAP:
        if any(k in s for k in keys):
            return label
    return 'SD'


def _poster(path):
    if not path:
        return ''
    if path.startswith('http'):
        return path
    return _TMDB + path


def _item_from_browse(m, is_series):
    _id = str(m.get('_id', ''))
    title = m.get('title', '')
    year = str(m.get('year', ''))
    poster = _poster(m.get('poster_path_season') or m.get('poster_path') or m.get('backdrop_path', ''))
    rating = str(m.get('rating', ''))
    item = {
        'title':     title,
        'year':      year,
        'poster':    poster,
        'mediatype': 'tvshow' if is_series else 'movie',
    }
    if rating:
        try:
            item['rating'] = float(rating)
        except Exception:
            pass
    if is_series:
        item['url']         = _S_SEASONS + _id
        item['next_func']   = 'load'
        item['is_playable'] = False
    else:
        item['url']         = _id
        item['next_func']   = 'get_hosters'
        item['is_playable'] = True
    return item


def _browse_api(encoded, page=1):
    params, pg_str = encoded.rsplit('|page=', 1) if '|page=' in encoded else (encoded, str(page))
    page = int(pg_str)
    data = _api('/data/browse/?' + params + '&page=%d&limit=20' % page)
    if not data:
        return []
    is_series = 'tvseries' in params or 'type=tv' in params
    items = []
    for m in data.get('movies', []):
        items.append(_item_from_browse(m, is_series))
    pager = data.get('pager', {})
    if page < pager.get('totalPages', 1):
        items.append({
            'title':       '[B]>>> Weiter[/B]',
            'url':         _S_BROWSE + encoded.split('|page=')[0] + '|page=%d' % (page + 1),
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def _get_seasons(_id):
    data = _api('/data/watch/?_id=' + _id)
    if not data:
        return []
    poster_show = _poster(data.get('poster_path', ''))
    plot = data.get('storyline') or data.get('overview', '')

    seasons_data = _api('/data/seasons/?lang=2&original_title=' + quote(
        re.sub(r'\s*[-–]\s*Staffel\s*\d+.*$', '', data.get('title', ''), flags=re.I).strip()
    ))
    if not seasons_data:
        seasons_data = [data]

    items = []
    for s in seasons_data:
        s_id     = str(s.get('_id', _id))
        s_num    = s.get('s', 1)
        s_poster = _poster(s.get('poster_path_season') or s.get('poster_path') or poster_show)
        item = {
            'title':       'Staffel %s' % s_num,
            'url':         _S_EPS + s_id,
            'poster':      s_poster,
            'mediatype':   'season',
            'next_func':   'load',
            'is_playable': False,
        }
        if plot:
            item['plot'] = plot
        items.append(item)
    return items


def _get_episodes(_id):
    data = _api('/data/watch/?_id=' + _id)
    if not data:
        return []
    poster = _poster(data.get('poster_path_season') or data.get('poster_path', ''))
    plot   = data.get('storyline') or data.get('overview', '')
    s_num  = data.get('s', 1)

    streams = [s for s in data.get('streams', []) if not s.get('deleted') and s.get('e')]
    ep_nums = sorted(set(int(s['e']) for s in streams))

    items = []
    for ep in ep_nums:
        ep_streams = [s for s in streams if int(s.get('e', -1)) == ep]
        ep_title   = ''
        for s in ep_streams:
            if s.get('e_title'):
                ep_title = s['e_title']
                break
        label = 'S%02dE%02d' % (s_num, ep)
        if ep_title:
            label += ' – ' + ep_title
        item = {
            'title':       label,
            'url':         _id,
            'poster':      poster,
            'mediatype':   'episode',
            'next_func':   'get_hosters',
            'is_playable': True,
            'season':      s_num,
            'episode':     ep,
        }
        if plot:
            item['plot'] = plot
        items.append(item)
    return items


def _filme_menu():
    return [{'title': label, 'url': _S_BROWSE + 'lang=2&type=movies&order_by=' + order,
             'next_func': 'load', 'is_playable': False}
            for label, order in _SORT_ORDERS]


def _serien_menu():
    return [{'title': label, 'url': _S_BROWSE + 'lang=2&type=tvseries&order_by=' + order,
             'next_func': 'load', 'is_playable': False}
            for label, order in _SORT_ORDERS]


def _genre_sort_menu(stype_token):
    return [{'title': 'Genre ' + label, 'url': _S_GENRE_LIST + stype_token + '|' + order,
             'next_func': 'load', 'is_playable': False}
            for label, order in _SORT_ORDERS]


def _genre_list(encoded):
    stype_token, order = encoded.split('|', 1)
    stype = 'movies' if stype_token == 'movies' else 'tvseries'
    return [{'title': g, 'url': _S_BROWSE + 'lang=2&type=%s&genre=%s&order_by=%s' % (stype, quote(g), order),
             'next_func': 'load', 'is_playable': False}
            for g in _GENRES]


def _jahre_menu():
    import datetime
    year = datetime.datetime.now().year
    return [{'title': str(y), 'url': _S_BROWSE + 'lang=2&type=movies&year=%d&order_by=new' % y,
             'next_func': 'load', 'is_playable': False}
            for y in range(year, 1929, -1)]


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Filme',          'url': _S_FILME,        'next_func': 'load', 'is_playable': False},
            {'title': 'Genre (Filme)',   'url': _S_GENRE_FILME,  'next_func': 'load', 'is_playable': False},
            {'title': 'Serien',         'url': _S_SERIEN,       'next_func': 'load', 'is_playable': False},
            {'title': 'Genre (Serien)', 'url': _S_GENRE_SERIEN, 'next_func': 'load', 'is_playable': False},
            {'title': 'Jahre',          'url': _S_JAHRE,        'next_func': 'load', 'is_playable': False},
        ]
    if url == _S_FILME:
        return _filme_menu()
    if url == _S_SERIEN:
        return _serien_menu()
    if url == _S_GENRE_FILME:
        return _genre_sort_menu('movies')
    if url == _S_GENRE_SERIEN:
        return _genre_sort_menu('tvseries')
    if url.startswith(_S_GENRE_LIST):
        return _genre_list(url[len(_S_GENRE_LIST):])
    if url == _S_JAHRE:
        return _jahre_menu()
    if url.startswith(_S_BROWSE):
        return _browse_api(url[len(_S_BROWSE):])
    if url.startswith(_S_SEASONS):
        return _get_seasons(url[len(_S_SEASONS):])
    if url.startswith(_S_EPS):
        return _get_episodes(url[len(_S_EPS):])
    return []


def get_details(url='', params=None):
    if not url:
        return {}
    data = _api('/data/watch/?_id=' + url)
    if not data:
        return {}
    result = {}
    plot = data.get('storyline') or data.get('overview', '')
    if plot:
        result['plot'] = plot
    if data.get('year'):
        result['year'] = str(data['year'])
    poster = _poster(data.get('poster_path') or data.get('poster_path_season', ''))
    if poster:
        result['poster'] = poster
    if data.get('rating'):
        try:
            result['rating'] = float(data['rating'])
        except Exception:
            pass
    return result


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    season  = int(season  or 0)
    episode = int(episode or 0)

    _id = url
    if not _id:
        clean = _cleantitle(title)
        stype = 'movies' if season == 0 else 'tvseries'
        years = [str(year), str(int(year or 0) + 1)] if year and season == 0 else ['']

        def _search(yr, lang):
            lang_param = '&lang=2' if lang else ''
            yr_param   = ('&year=' + yr) if yr else ''
            return _api('/data/browse/?keyword=%s%s&type=%s%s&page=1&limit=20' % (
                quote(title), yr_param, stype, lang_param
            ))

        def _find_id(data):
            if not data:
                return None
            for m in data.get('movies', []):
                mt = re.sub(r'\s*[-–]\s*(Staffel|Season)\s*\d+.*$', '', m.get('title', ''), flags=re.I).strip()
                ec = _cleantitle(mt)
                if clean not in ec and ec not in clean:
                    continue
                if season > 0 and m.get('s') and int(m['s']) != season:
                    continue
                return str(m['_id'])
            return None

        for yr in years:
            _id = _find_id(_search(yr, lang=True))
            if _id:
                break
        if not _id:
            for yr in years:
                _id = _find_id(_search(yr, lang=False))
                if _id:
                    break
        if not _id:
            return []

    watch = _api('/data/watch/?_id=' + _id)
    if not watch:
        return []

    streams = [s for s in watch.get('streams', []) if not s.get('deleted')]

    if season > 0:
        streams = [s for s in streams if int(s.get('e', -1)) == episode]

    result = {}
    for s in streams:
        raw_url = s.get('stream', '')
        if not raw_url:
            continue
        if raw_url.startswith('//'):
            raw_url = 'https:' + raw_url
        if 'youtube' in raw_url.lower():
            continue
        hostname = urlparse(raw_url).hostname or ''
        if any(b in hostname for b in _BROKEN):
            continue
        qual = _parse_quality(s.get('release', ''))
        domain = '.'.join(hostname.split('.')[-2:]) if hostname else SITE_NAME
        if domain in result:
            continue
        result[domain] = (raw_url, qual, False, 'de')

    return [(dom, v[0], v[2], v[1], v[3]) for dom, v in result.items()]


def search(query='', params=None):
    data = _api('/data/browse/?lang=2&keyword=%s&year=&type=&page=1&limit=20' % quote(query))
    if not data:
        return []
    items = []
    for m in data.get('movies', []):
        is_series = bool(re.search(r'\b(Staffel|Season)\s+\d+', m.get('title', ''), re.I))
        items.append(_item_from_browse(m, is_series))
    return items
