# -*- coding: utf-8 -*-
import re
import json
import os
import time
from resources.lib import multiquest, log

SITE_ID       = 'gezkino'
SITE_NAME     = 'GEZ Kino'
SITE_DOMAIN   = 'mediathekviewweb.de'
TYPE          = 'movie'
GLOBAL_SEARCH = True

_UA          = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
_API_URL     = 'https://mediathekviewweb.de/api/query'
_MIN_DURATION = 4680
_SKIP        = ['audiodeskription', 'audio description', 'hörfilm', 'deskription', 'barrierefrei', 'ad version']
_TERMS       = ['Spielfilm', 'Spielfilme', 'Spielfilm-Highlights', 'Filme', 'Kino - Filme']
_STRIP       = [
    ' - Spielfilm', u' \u2013 Spielfilm', ', Spielfilm',
    u' \xd6sterreich', ', Deutschland', ', Schweiz', ', Belgien',
    ', Frankreich', ', Spanien', ', Niederlande', ', Irland',
    ', Luxemburg', ', Italien', ', USA', ', Kosovo',
    u', Gro\xdfbritannien', ', Norwegen', ', BRD', u', D\xe4nemark',
    ', Australien', ', Schweden', ' Fernsehfilm', ' Heimatfilm',
    ' - Thriller', ' - Drama', u'\xab', u'\xbb',
]
_GENRES = [
    ('Alle Filme',    'Alle'),
    ('Action',        'Action'),
    ('Abenteuer',     'Abenteuer'),
    ('Animation',     'Animation'),
    (u'Kom\xf6die',   u'Kom\xf6die'),
    ('Krimi',         'Krimi'),
    ('Drama',         'Drama'),
    ('Familie',       'Familie'),
    ('Fantasy',       'Fantasy'),
    ('Horror',        'Horror'),
    ('Mystery',       'Mystery'),
    ('Romantik',      'Romanze'),
    ('Science Fiction', 'Sci-Fi'),
    ('Thriller',      'Thriller'),
    ('Western',       'Western'),
]
_GENRES_MAP = {
    28: 'Action', 12: 'Abenteuer', 16: 'Animation', 35: u'Kom\xf6die', 80: 'Krimi',
    18: 'Drama', 10751: 'Familie', 14: 'Fantasy', 27: 'Horror', 9648: 'Mystery',
    10749: 'Romanze', 878: 'Sci-Fi', 53: 'Thriller', 37: 'Western',
}
_TMDB_KEY       = '60b3801a9e76b5706ee2a432f06423e6'
_GENRE_CACHE_TTL = 6 * 3600


def _genre_cache_path():
    try:
        from resources.lib.control import addonProfile
        return os.path.join(addonProfile(), 'gezkino_genre_cache.json')
    except Exception:
        return None


def _load_genre_cache():
    path = _genre_cache_path()
    if not path:
        return {}
    try:
        if not os.path.exists(path):
            return {}
        if time.time() - os.path.getmtime(path) > _GENRE_CACHE_TTL:
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_genre_cache(cache):
    path = _genre_cache_path()
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def _cleantitle(title):
    s = title or ''
    for strip in _STRIP:
        s = re.split(re.escape(strip), s, flags=re.I)[0]
    s = re.sub(r'^(Spielfilm|Spiellfilm):\s*', '', s, flags=re.I)
    s = re.sub(r'\(.*?\)', '', s)
    return re.sub(r'[^a-z0-9]', '', s.lower())


def _is_valid(entry):
    if entry.get('duration', 0) < _MIN_DURATION:
        return False
    title = entry.get('title', '').lower()
    return not any(x in title for x in _SKIP)


def _query(term):
    payload = json.dumps({
        'queries':   [{'fields': ['topic'], 'query': term}],
        'size':      2000,
        'sortBy':    'timestamp',
        'sortOrder': 'desc',
    })
    try:
        r = multiquest.post(_API_URL, data=payload, headers={
            'User-Agent':   _UA,
            'Content-Type': 'application/json',
        }, timeout=20)
        r.raise_for_status()
        return r.json().get('result', {}).get('results', [])
    except Exception:
        log.error()
        return []


def _query_all(terms=None):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = []
    seen    = set()
    with ThreadPoolExecutor(max_workers=len(terms or _TERMS)) as ex:
        futures = {ex.submit(_query, t): t for t in (terms or _TERMS)}
        for f in as_completed(futures):
            for e in f.result():
                url = e.get('url_video', '')
                if url and url not in seen and _is_valid(e):
                    seen.add(url)
                    results.append(e)
    return results


_tmdb_genre_cache = {}


def _get_tmdb_genres(title, year=''):
    key = title.lower().strip()
    if key in _tmdb_genre_cache:
        return _tmdb_genre_cache[key]
    try:
        params = {'api_key': _TMDB_KEY, 'query': title, 'language': 'de-DE'}
        if year:
            params['year'] = year
        r = multiquest.get('https://api.themoviedb.org/3/search/movie', params=params, timeout=8)
        r.raise_for_status()
        results = r.json().get('results', [])
        if results:
            ids = results[0].get('genre_ids', [])
            genres = [_GENRES_MAP[g] for g in ids if g in _GENRES_MAP]
            _tmdb_genre_cache[key] = genres
            return genres
    except Exception:
        pass
    _tmdb_genre_cache[key] = []
    return []


def _build_genre_cache(entries):
    disk = _load_genre_cache()
    _tmdb_genre_cache.update(disk)
    seen_keys = {}
    deduped = []
    for e in entries:
        k = _clean_entry_title(e.get('title', '')).lower().strip()
        if k not in seen_keys:
            seen_keys[k] = True
            deduped.append(e)
    missing = [e for e in deduped
               if _clean_entry_title(e.get('title', '')).lower().strip() not in _tmdb_genre_cache]
    if missing:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=16) as ex:
            futures = [ex.submit(_get_tmdb_genres, _clean_entry_title(e.get('title', ''))) for e in missing]
            for f in as_completed(futures):
                f.result()
        _save_genre_cache(_tmdb_genre_cache)
    return deduped


def _clean_entry_title(title):
    clean = re.sub(r'\s*[-\u2013].*$', '', title).strip()
    for strip in _STRIP:
        clean = re.split(re.escape(strip), clean, flags=re.I)[0]
    clean = re.sub(r'^(Spielfilm|Spiellfilm):\s*', '', clean, flags=re.I).strip()
    return clean or title


def _entry_to_item(e):
    title = e.get('title', '')
    url   = e.get('url_video', '')
    clean = _clean_entry_title(title)
    return {
        'title':       clean,
        'url':         clean + '||' + url,
        'mediatype':   'movie',
        'is_playable': True,
        'next_func':   'get_hosters',
    }


def _browse_term(term):
    return [_entry_to_item(e) for e in _query(term)]


def _browse_genre(genre):
    entries = _query_all()
    if not entries:
        return []
    deduped = _build_genre_cache(entries)
    if genre == 'Alle':
        return [_entry_to_item(e) for e in deduped]
    return [
        _entry_to_item(e)
        for e in deduped
        if genre in _tmdb_genre_cache.get(_clean_entry_title(e.get('title', '')).lower().strip(), [])
    ]


def _browse_az(char):
    items = []
    for e in _query_all():
        title = _clean_entry_title(e.get('title', ''))
        if not title:
            continue
        fc = title[0].upper()
        if char == '#':
            if fc.isalpha():
                continue
        elif fc != char:
            continue
        items.append(_entry_to_item(e))
    items.sort(key=lambda x: x['title'].lower())
    return items


def _browse_year(year):
    items = []
    for e in _query_all():
        _, prod_year = _clean_title_year(e.get('title', ''))
        if prod_year != year:
            continue
        items.append(_entry_to_item(e))
    items.sort(key=lambda x: x['title'].lower())
    return items


def _clean_title_year(title):
    s = title or ''
    for strip in _STRIP:
        s = re.split(re.escape(strip), s, flags=re.I)[0]
    s = re.sub(r'^(Spielfilm|Spiellfilm):\s*', '', s, flags=re.I)
    s = re.sub(r'\(.*?\)', '', s).strip()
    m = re.search(r'(\d{4})', title)
    return s, m.group(1) if m else ''


def load(url='', params=None):
    _plot = '[B]Powered by Zusatzmetall[/B]'
    if not url:
        return [
            {'title': '[ Alle Spielfilme ]',         'url': 'term=Spielfilm',            'plot': _plot, 'is_playable': False, 'next_func': 'load'},
            {'title': '[ Filme A-Z ]',               'url': 'az',                        'plot': _plot, 'is_playable': False, 'next_func': 'load'},
            {'title': '[ Nach Jahren sortiert... ]', 'url': 'years',                     'plot': _plot, 'is_playable': False, 'next_func': 'load'},
            {'title': '[ Nach Genres filtern... ]',  'url': 'genres',                    'plot': _plot, 'is_playable': False, 'next_func': 'load'},
            {'title': '[ Spielfilm-Highlights ]',    'url': 'term=Spielfilm-Highlights', 'plot': _plot, 'is_playable': False, 'next_func': 'load'},
            {'title': '[ Filme ]',                   'url': 'term=Filme',                'plot': _plot, 'is_playable': False, 'next_func': 'load'},
            {'title': '[ Kino - Filme ]',            'url': 'term=Kino - Filme',         'plot': _plot, 'is_playable': False, 'next_func': 'load'},
        ]

    if url == 'az':
        import string
        return [
            {'title': ch, 'url': 'az=%s' % ch, 'is_playable': False, 'next_func': 'load'}
            for ch in ['#'] + list(string.ascii_uppercase)
        ]

    if url.startswith('az='):
        return _browse_az(url[3:])

    if url == 'years':
        seen = set()
        years = []
        for e in _query_all():
            _, y = _clean_title_year(e.get('title', ''))
            if y and y not in seen:
                seen.add(y)
                years.append(y)
        years.sort(reverse=True)
        return [
            {'title': 'Jahr %s' % y, 'url': 'year=%s' % y, 'is_playable': False, 'next_func': 'load'}
            for y in years
        ]

    if url.startswith('year='):
        return _browse_year(url[5:])

    if url == 'genres':
        return [
            {'title': label, 'url': 'genre=%s' % internal, 'is_playable': False, 'next_func': 'load'}
            for label, internal in _GENRES
        ]

    if url.startswith('term='):
        return _browse_term(url[5:])

    if url.startswith('genre='):
        return _browse_genre(url[6:])

    return []


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if season and int(season) > 0:
        return []

    if url and not url.startswith('term=') and not url.startswith('genre='):
        stream = url.split('||')[-1] if '||' in url else url
        return [('Mediathek', stream, True, 'HD', 'de')]

    clean = _cleantitle(title)
    for e in _query_all():
        eurl   = e.get('url_video', '')
        etitle = _cleantitle(e.get('title', ''))
        if clean and eurl and (clean in etitle or etitle in clean):
            return [('Mediathek', eurl, True, 'HD', 'de')]
    log.log('[gezkino] get_hosters: kein Treffer fuer "%s"' % title)
    return []


def search(query='', params=None):
    clean = _cleantitle(query)
    return [_entry_to_item(e) for e in _query_all()
            if clean in _cleantitle(e.get('title', '')) or _cleantitle(e.get('title', '')) in clean]


def get_details(url='', params=None):
    if not url:
        return {}
    title = url.split('||')[0] if '||' in url else url
    try:
        r = multiquest.get('https://api.themoviedb.org/3/search/movie', params={
            'api_key':  _TMDB_KEY,
            'query':    title,
            'language': 'de-DE',
        }, timeout=8)
        r.raise_for_status()
        results = r.json().get('results', [])
        if not results:
            return {}
        mv   = results[0]
        path = mv.get('poster_path', '')
        rd   = mv.get('release_date', '')
        return {
            'plot':   mv.get('overview', ''),
            'rating': mv.get('vote_average', 0),
            'year':   rd[:4] if rd else '',
            'poster': 'https://image.tmdb.org/t/p/w342' + path if path else '',
        }
    except Exception:
        log.error()
        return {}


def _warmup_genre_cache():
    try:
        import threading
        import time
        disk = _load_genre_cache()
        if disk:
            return
        def _build():
            try:
                time.sleep(5)
                entries = _query_all()
                if entries:
                    _build_genre_cache(entries)
                    log.log('[gezkino] Genre-Cache im Hintergrund aufgebaut (%d Einträge)' % len(entries))
            except Exception:
                log.error()
        t = threading.Thread(target=_build, daemon=True)
        t.start()
    except Exception:
        pass

_warmup_genre_cache()
