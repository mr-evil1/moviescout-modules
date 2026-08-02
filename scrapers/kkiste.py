# -*- coding: utf-8 -*-
import re
import json
from urllib.parse import quote
from resources.lib import multiquest, log

SITE_ID       = 'kkiste'
SITE_NAME     = 'KKiste'
SITE_DOMAIN   = 'kkiste.eu'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA         = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
_THUMB_BASE = 'https://image.tmdb.org/t/p/w300%s'

_S_MOVIES_NEW   = '__kkiste_movies_new__'
_S_MOVIES_TREND = '__kkiste_movies_trend__'
_S_MOVIES_TOP   = '__kkiste_movies_top__'
_S_SERIES_NEW   = '__kkiste_series_new__'
_S_SERIES_TREND = '__kkiste_series_trend__'
_S_GENRE_MOVIES = '__kkiste_genre_movies__'
_S_GENRE_SERIES = '__kkiste_genre_series__'
_S_API_PFX      = '__kkiste_api__:'
_S_API_SEASONS  = '__kkiste_api_seasons__:'
_S_API_EPS      = '__kkiste_api_eps__:'
_S_SEASONS      = '__kkiste_seasons__:'
_S_EP           = '__kkiste_ep__:'

_HOSTER_PRIO = {
    'voe': 10, 'streamruby': 10, 'mixdrop': 9, 'streamwish': 8,
    'vidoza': 7, 'vidguard': 6, 'doodstream': 5, 'streamtape': 5,
    'filemoon': 5, 'upstream': 5,
}
_MIN_PRIO  = 6
_MAX_PER_H = 1

_GENRES = [
    ('Abenteuer',    'Adventure'),
    ('Action',       'Action'),
    ('Animation',    'Animation'),
    ('Dokumentation','Documentary'),
    ('Drama',        'Drama'),
    ('Familie',      'Family'),
    ('Fantasy',      'Fantasy'),
    ('Horror',       'Horror'),
    ('Komödie',      'Comedy'),
    ('Krieg',        'War'),
    ('Krimi',        'Crime'),
    ('Mystery',      'Mystery'),
    ('Romantik',     'Romance'),
    ('Sci-Fi',       'Science Fiction'),
    ('Thriller',     'Thriller'),
]


def _base():
    return 'https://' + SITE_DOMAIN


def _request(url, is_json=False):
    try:
        h = {'User-Agent': _UA, 'Referer': _base() + '/'}
        if is_json:
            h.update({'Accept': 'application/json, text/plain, */*', 'Origin': _base(), 'X-Requested-With': 'XMLHttpRequest'})
        r = multiquest.get(url, headers=h, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _get_html(url):
    return _request(url, is_json=False)


def _get_json(url):
    raw = _request(url, is_json=True)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        log.error()
        return None


def _strip_comments(html):
    return re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)


def _hoster_prio(name):
    return _HOSTER_PRIO.get(name.lower().split('.')[0], 0)


def _api_url(stype, order, page, genre=''):
    u = _base() + '/data/browse/?lang=2&type=%s&order_by=%s&page=%s' % (stype, order, page)
    if genre:
        u += '&genres=' + quote(genre)
    return u


def _parse_api(data, base_api_url=''):
    items = []
    if not data or 'movies' not in data:
        return items

    for movie in data['movies']:
        if '_id' not in movie:
            continue
        sTitle   = str(movie.get('title', ''))
        movie_id = str(movie['_id'])
        watch_url = _base() + '/data/watch/?_id=' + movie_id

        sThumbnail = ''
        for key in ('poster_path_season', 'poster_path', 'backdrop_path'):
            if movie.get(key):
                sThumbnail = _THUMB_BASE % movie[key]
                break

        sYear   = str(movie.get('year', ''))
        sPlot   = str(movie.get('storyline') or movie.get('overview') or movie.get('description') or movie.get('plot') or '')
        sRating = str(movie.get('rating', ''))

        isTvshow = bool(re.search(r'\b(Staffel|Season)\s+\d+', sTitle, re.I))

        if isTvshow:
            show_title = re.sub(r'\s*[-:]\s*(Staffel|Season)\s*\d+.*', '', sTitle, flags=re.I).strip()
            m_sn = re.search(r'(?:Staffel|Season)\s+(\d+)', sTitle, re.I)
            sn = int(m_sn.group(1)) if m_sn else 1
            items.append({
                'title':       '%s - Staffel %d' % (show_title, sn),
                'url':         _S_API_EPS + watch_url + '|%d' % sn,
                'poster':      sThumbnail,
                'year':        sYear,
                'plot':        sPlot,
                'rating':      sRating,
                'mediatype':   'season',
                'is_playable': False,
                'next_func':   'load',
            })
        else:
            items.append({
                'title':       sTitle,
                'url':         watch_url,
                'poster':      sThumbnail,
                'year':        sYear,
                'plot':        sPlot,
                'rating':      sRating,
                'mediatype':   'movie',
                'is_playable': False,
                'next_func':   'get_hosters',
            })

    pager = data.get('pager', {})
    if pager and base_api_url:
        try:
            cur   = int(pager.get('currentPage', 0))
            total = int(pager.get('totalPages', cur))
            if cur and cur < total:
                next_url = re.sub(r'page=\d+', 'page=%d' % (cur + 1), base_api_url)
                items.append({
                    'title':       '[B]>>> Nächste Seite[/B]',
                    'url':         _S_API_PFX + next_url,
                    'next_func':   'load',
                    'is_playable': False,
                })
        except Exception:
            pass

    return items


def _load_api(api_url):
    data = _get_json(api_url)
    if (not data or not data.get('movies')) and 'genres=' in api_url:
        alt_url = api_url.replace('genres=', 'genre=')
        data2 = _get_json(alt_url)
        if data2 and data2.get('movies'):
            data = data2
            api_url = alt_url
    return _parse_api(data, api_url)


def _genre_menu(stype):
    items = []
    for label, api_name in _GENRES:
        api_url = _api_url(stype, 'new', 1, api_name)
        items.append({
            'title':       label,
            'url':         _S_API_PFX + api_url,
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def _parse_articles(html):
    html = _strip_comments(html)
    items = []
    seen_shows = set()

    for article in re.findall(r'<article[^>]*class=\"short\"[^>]*>(.*?)</article>', html, re.S | re.I):
        m = re.search(r'<h2>\s*<a\s+href=\"([^\"]+)\"[^>]*>([^<]+)</a>', article)
        if not m:
            continue
        detail_url = m.group(1)
        sName = m.group(2).strip()

        m_thumb = re.search(r'<img\s+src=\"([^\"]+)\"[^>]*alt=\"([^\"]*)\"', article)
        sThumbnail = ''
        sAltText   = ''
        if m_thumb:
            sThumbnail = m_thumb.group(1)
            if sThumbnail.startswith('/'):
                sThumbnail = _base() + sThumbnail
            sAltText = m_thumb.group(2)

        sYear = ''
        m_year = re.search(r'<span>Jahr:</span>\s*(\d{4})', article)
        if m_year:
            sYear = m_year.group(1)
        elif sAltText:
            m_ya = re.search(r'\((\d{4})\)', sAltText)
            if m_ya:
                sYear = m_ya.group(1)

        sPlot = ''
        m_desc = re.search(r'<div class=\"st-line st-desc\">([^<]+)</div>', article)
        if m_desc:
            sPlot = m_desc.group(1).strip()

        isTvshow = 'taffel' in sName or (sAltText and 'taffel' in sAltText)

        if isTvshow:
            key = re.sub(r'[^a-z0-9]', '', sName.lower())
            if key in seen_shows:
                continue
            seen_shows.add(key)
            items.append({
                'title':       sName,
                'url':         _S_SEASONS + detail_url,
                'poster':      sThumbnail,
                'year':        sYear,
                'plot':        sPlot,
                'mediatype':   'tvshow',
                'is_playable': False,
                'next_func':   'load',
            })
        else:
            items.append({
                'title':       sName,
                'url':         detail_url,
                'poster':      sThumbnail,
                'year':        sYear,
                'plot':        sPlot,
                'mediatype':   'movie',
                'is_playable': False,
                'next_func':   'get_hosters',
            })

    m_next = re.search(r'class=\"pnext\"><a\s+href=\"([^\"]+)\"', html)
    if m_next:
        nxt = m_next.group(1)
        if nxt.startswith('/'):
            nxt = _base() + nxt
        items.append({'title': '[B]>>> Weiter[/B]', 'url': nxt, 'next_func': 'load', 'is_playable': False})

    return items


def _get_seasons(show_url):
    html = _strip_comments(_get_html(show_url))

    m_thumb = re.search(r'<img[^>]+src=\"([^\"]+)\"', html)
    sThumbnail = ''
    if m_thumb:
        sThumbnail = m_thumb.group(1)
        if sThumbnail.startswith('/'):
            sThumbnail = _base() + sThumbnail

    sPlot = ''
    m_desc = re.search(r'<div[^>]*class=\"[^\"]*full-story[^\"]*\"[^>]*>(.*?)</div>', html, re.S | re.I)
    if m_desc:
        sPlot = re.sub(r'<[^>]+>', '', m_desc.group(1)).strip()

    items = []
    for s in re.findall(r'data-sid=\"(\d+)\"', html):
        items.append({
            'title':       'Staffel ' + s,
            'url':         _S_EP + show_url + '|' + s,
            'poster':      sThumbnail,
            'plot':        sPlot,
            'mediatype':   'season',
            'is_playable': False,
            'next_func':   'load',
        })
    return items


def _get_episodes(encoded):
    show_url, season = encoded.rsplit('|', 1)
    html = _strip_comments(_get_html(show_url))

    m_thumb = re.search(r'<img[^>]+src=\"([^\"]+)\"', html)
    sThumbnail = ''
    if m_thumb:
        sThumbnail = m_thumb.group(1)
        if sThumbnail.startswith('/'):
            sThumbnail = _base() + sThumbnail

    sPlot = ''
    m_desc = re.search(r'<div[^>]*class=\"[^\"]*full-story[^\"]*\"[^>]*>(.*?)</div>', html, re.S | re.I)
    if m_desc:
        sPlot = re.sub(r'<[^>]+>', '', m_desc.group(1)).strip()

    m_start = re.search(r'<div[^>]*data-sid=\"%s\"[^>]*>' % re.escape(season), html, re.I)
    if not m_start:
        return []
    section = html[m_start.end():]
    m_nb = re.search(r'<div[^>]*class=\"staffelWrapperLoop', section, re.I)
    if m_nb:
        section = section[:m_nb.start()]

    items = []
    for anchor in re.finditer(r'(<a[^>]*class=\"getStaffelStream[^\"]*\"[^>]*>)(.*?)</a>', section, re.S | re.I):
        href_m = re.search(r'href=\"([^\"]+)\"', anchor.group(1))
        if not href_m:
            continue
        ep_url = href_m.group(1).strip()
        if ep_url.startswith('//'):
            ep_url = 'https:' + ep_url
        elif ep_url.startswith('/'):
            ep_url = _base() + ep_url
        raw = re.sub(r'<[^>]+>', '', anchor.group(2)).replace('&nbsp;', ' ')
        ep_title = ' '.join(raw.split()) or ep_url.split('/')[-1]
        items.append({
            'title':       ep_title,
            'url':         ep_url,
            'poster':      sThumbnail,
            'plot':        sPlot,
            'mediatype':   'episode',
            'is_playable': False,
            'next_func':   'get_hosters',
        })
    return items


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _api_seasons(show_title, poster='', plot='', year=''):
    clean = _cleantitle(show_title)
    seen = set()
    items = []

    for type_filter in ('tvseries', ''):
        base = _base() + '/data/browse/?lang=2&order_by=new&keyword=' + quote(show_title)
        if type_filter:
            base += '&type=' + type_filter
        page = 1
        total = 1
        while page <= total and page <= 20:
            url = base + '&page=%d' % page
            data = _get_json(url)
            if not data or 'movies' not in data:
                break
            pager = data.get('pager', {})
            try:
                total = int(pager.get('totalPages', page))
            except Exception:
                total = page
            for movie in data['movies']:
                sTitle = str(movie.get('title', ''))
                m = re.search(r'(Staffel|Season)\s+(\d+)', sTitle, re.I)
                if not m:
                    continue
                base_title = re.sub(r'\s*[-:]?\s*(Staffel|Season)\s*\d+.*', '', sTitle, flags=re.I).strip()
                if _cleantitle(base_title) != clean:
                    continue
                sn = int(m.group(2))
                if sn in seen:
                    continue
                seen.add(sn)
                movie_id = str(movie['_id'])
                watch_url = _base() + '/data/watch/?_id=' + movie_id
                sThumbnail = poster
                for key in ('poster_path_season', 'poster_path', 'backdrop_path'):
                    if movie.get(key):
                        sThumbnail = _THUMB_BASE % movie[key]
                        break
                items.append({
                    'title':       'Staffel %d' % sn,
                    'url':         _S_API_EPS + watch_url + '|%d' % sn,
                    'poster':      sThumbnail,
                    'plot':        plot,
                    'year':        year,
                    'mediatype':   'season',
                    'is_playable': False,
                    'next_func':   'load',
                })
            page += 1
        if seen:
            break

    return sorted(items, key=lambda x: x['title'])


def _api_episodes(watch_url, season):
    data = _get_json(watch_url)
    if not data or 'streams' not in data:
        return []
    season_i = int(season)
    episodes = sorted(set(
        int(s['e']) for s in data['streams']
        if 'e' in s
    ))
    plot = str(data.get('storyline') or data.get('overview') or '')
    items = []
    for ep in episodes:
        items.append({
            'title':       'Episode %d' % ep,
            'url':         watch_url,
            'plot':        plot,
            'mediatype':   'episode',
            'is_playable': False,
            'next_func':   'get_hosters',
            'season':      season_i,
            'episode':     ep,
        })
    return items


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Neue Filme',         'url': _S_MOVIES_NEW,   'next_func': 'load', 'is_playable': False},
            {'title': 'Trending Filme',      'url': _S_MOVIES_TREND, 'next_func': 'load', 'is_playable': False},
            {'title': 'Top bewertete Filme', 'url': _S_MOVIES_TOP,   'next_func': 'load', 'is_playable': False},
            {'title': 'Neue Serien',         'url': _S_SERIES_NEW,   'next_func': 'load', 'is_playable': False},
            {'title': 'Trending Serien',     'url': _S_SERIES_TREND, 'next_func': 'load', 'is_playable': False},
            {'title': 'Genre (Filme)',       'url': _S_GENRE_MOVIES, 'next_func': 'load', 'is_playable': False},
            {'title': 'Genre (Serien)',      'url': _S_GENRE_SERIES, 'next_func': 'load', 'is_playable': False},
        ]
    if url == _S_MOVIES_NEW:
        return _load_api(_api_url('movies',   'new',      1))
    if url == _S_MOVIES_TREND:
        return _load_api(_api_url('movies',   'Trending', 1))
    if url == _S_MOVIES_TOP:
        return _load_api(_api_url('movies',   'rating',   1))
    if url == _S_SERIES_NEW:
        return _load_api(_api_url('tvseries', 'new',      1))
    if url == _S_SERIES_TREND:
        return _load_api(_api_url('tvseries', 'Trending', 1))
    if url == _S_GENRE_MOVIES:
        return _genre_menu('movies')
    if url == _S_GENRE_SERIES:
        return _genre_menu('tvseries')
    if url.startswith(_S_API_SEASONS):
        return _api_seasons(url[len(_S_API_SEASONS):])
    if url.startswith(_S_API_EPS):
        watch_url, season = url[len(_S_API_EPS):].rsplit('|', 1)
        return _api_episodes(watch_url, season)
    if url.startswith(_S_API_PFX):
        return _load_api(url[len(_S_API_PFX):])
    if url.startswith(_S_SEASONS):
        return _get_seasons(url[len(_S_SEASONS):])
    if url.startswith(_S_EP):
        return _get_episodes(url[len(_S_EP):])
    return _parse_articles(_get_html(url))


def _match_title(movie, clean_title, year, season):
    sTitle = str(movie.get('title', ''))
    if not sTitle:
        return False
    if season == 0:
        if re.search(r'\b(Staffel|Season)\s+\d+', sTitle, re.I):
            return False
        base = re.sub(r'\s*\(\d{4}\)\s*$', '', sTitle).strip()
        ec = _cleantitle(base)
        if clean_title not in ec and ec not in clean_title:
            return False
        try:
            if year and int(movie.get('year', 0)) and abs(int(movie.get('year')) - int(year)) > 1:
                return False
        except Exception:
            pass
        return True
    m = re.search(r'(?:Staffel|Season)\s+(\d+)', sTitle, re.I)
    if not m or int(m.group(1)) != int(season):
        return False
    base = re.sub(r'\s*[-:]?\s*(?:Staffel|Season)\s*\d+.*', '', sTitle, flags=re.I).strip()
    ec = _cleantitle(base)
    return clean_title in ec or ec in clean_title


def _streams_from_watch(data, season_i, episode_i):
    result = []
    hoster_count = {}
    for stream in data.get('streams', []):
        if season_i > 0 and episode_i > 0:
            try:
                if int(stream.get('e', -1)) != episode_i:
                    continue
            except Exception:
                continue
        s_url = str(stream.get('stream', ''))
        if not s_url or 'youtube' in s_url.lower():
            continue
        if s_url.startswith('//'):
            s_url = 'https:' + s_url
        m = re.search(r'//([^/]+)', s_url)
        if not m:
            continue
        parts = m.group(1).split('.')
        hname = parts[-2] if len(parts) >= 2 else parts[0]
        prio = _hoster_prio(hname)
        if prio < _MIN_PRIO:
            continue
        key = hname.lower()
        if hoster_count.get(key, 0) >= _MAX_PER_H:
            continue
        hoster_count[key] = hoster_count.get(key, 0) + 1
        quality = 'HD'
        if stream.get('release'):
            rel = str(stream['release']).upper()
            if 'CAM' in rel or 'TS' in rel:
                quality = 'CAM'
            elif 'SD' in rel:
                quality = 'SD'
        result.append((hname.upper(), s_url, False, quality, 'de'))
    return result


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    season_i  = int(season  or 0)
    episode_i = int(episode or 0)

    if url and not url.startswith('__') and '/data/watch/' in url:
        data = _get_json(url)
        if data and 'streams' in data:
            result = _streams_from_watch(data, season_i, episode_i)
            return sorted(result, key=lambda x: _hoster_prio(x[0]), reverse=True)

    if title:
        clean = _cleantitle(title)
        media_type = 'tvseries' if season_i > 0 else 'movies'
        found_ids = set()
        result = []
        lang_filters = [('2', True), ('3', True), ('2', False), ('', False)]
        for lang, with_type in lang_filters:
            params = 'order_by=new&page=1&keyword=%s' % quote(title)
            if lang:
                params += '&lang=' + lang
            if with_type:
                params += '&type=' + media_type
            search_url = _base() + '/data/browse/?' + params
            data = _get_json(search_url)
            if not data or 'movies' not in data:
                continue
            for movie in data['movies']:
                if '_id' not in movie:
                    continue
                if not _match_title(movie, clean, year, season_i):
                    continue
                mid = str(movie['_id'])
                if mid in found_ids:
                    continue
                found_ids.add(mid)
                watch_url = _base() + '/data/watch/?_id=' + mid
                wdata = _get_json(watch_url)
                if not wdata:
                    continue
                result.extend(_streams_from_watch(wdata, season_i, episode_i))
            if result:
                break
        return sorted(result, key=lambda x: _hoster_prio(x[0]), reverse=True)

    return []


def search(query='', params=None):
    data = _get_json(_base() + '/data/browse/?lang=2&order_by=new&page=1&search=' + quote(query))
    return _parse_api(data)


def get_details(url='', params=None):
    if not url:
        return {}
    if url.startswith(_S_API_EPS):
        url = url[len(_S_API_EPS):].rsplit('|', 1)[0]
    if '/data/watch/' not in url:
        return {}
    data = _get_json(url)
    if not data:
        return {}
    plot = str(data.get('storyline') or data.get('overview') or data.get('description') or '')
    result = {}
    if plot:
        result['plot'] = plot
    if data.get('year'):
        result['year'] = str(data['year'])
    if data.get('rating'):
        result['rating'] = str(data['rating'])
    return result
