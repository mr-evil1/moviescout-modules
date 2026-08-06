# -*- coding: utf-8 -*-
import re
import json
import os
import time
import sqlite3
import hashlib
from resources.lib import multiquest, log
import xbmcaddon

SITE_ID       = 'gezkino'
SITE_NAME     = 'GEZ Kino'
SITE_DOMAIN   = 'mediathekviewweb.de'
TYPE          = 'movie'
GLOBAL_SEARCH = True

_UA          = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
_API_URL     = 'https://mediathekviewweb.de/api/query'
_MIN_DURATION = 4680

_TERMS = ['Spielfilm', 'Spielfilme', 'Spielfilm-Highlights', 'Filme', 'Kino - Filme', 'Filme in der ARD']

_SKIP = [
    'audiodeskription', 'audio description', 'hörfilm', 'deskription', 'barrierefrei', 'ad version',
    '(englisch)', '(zho)', '(originalversion mit untertitel)', '(mit untertitel)', '(originalversion)'
]
_SKIP_CHANNELS = ['kika', 'zdf-tivi']
_SKIP_REGEX = [
    r'\b(folge|staffel|episode|ep\.|teil)\b',
    r'\(\d+(\s*[\/\-]\s*\d+)?\)',
    r'\b\d{1,2}/\d{1,2}\b'
]

_STRIP = [
    ' - Spielfilm', u' \u2013 Spielfilm', ' - Spiellfilm', u' \u2013 Spiellfilm', ', Spielfilm',
    u' \xd6sterreich', ', Deutschland', ', Schweiz', ', Belgien', ', Frankreich', ', Spanien', 
    ', Niederlande', ', Irland', ', Luxemburg', ', Italien', ', USA', ', Kosovo',
    u', Gro\xdfbritannien', ', Tschechische Republik', ', Norwegen', ', BRD', u', D\xe4nemark',
    ', Australien', ', Schweden', ', Video:', ', Präsentiert:', ', Kurzfilm', ' Fernsehfilm', 
    ' Heimatfilm', ' - Thriller', ' - Drama', u'\xab', u'\xbb',
]

_GENRES_MAP = {
    28: 'Action', 12: 'Abenteuer', 16: 'Animation', 35: u'Kom\xf6die', 80: 'Krimi', 99: 'Doku',
    18: 'Drama', 10751: 'Familie', 14: 'Fantasy', 36: 'Historie', 27: 'Horror', 10402: 'Musik',
    9648: 'Mystery', 10749: 'Romanze', 878: 'Sci-Fi', 10770: 'TV-Film', 53: 'Thriller',
    10752: 'Krieg', 37: 'Western',
}

_TMDB_KEY = '60b3801a9e76b5706ee2a432f06423e6'


def _db_path():
    try:
        from resources.lib.control import addonProfile
        path = addonProfile()
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        return os.path.join(path, 'gezkino_movies.db')
    except Exception:
        return 'gezkino_movies.db'


def init_db():
    try:
        with sqlite3.connect(_db_path()) as conn:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS movie_cache
                         (search_title TEXT PRIMARY KEY, plot TEXT, rating REAL,
                          poster_url TEXT, genres_json TEXT, year TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS film_list
                         (hash_id TEXT PRIMARY KEY, title TEXT, video_url TEXT,
                          search_name TEXT, year TEXT, genres_json TEXT, timestamp INTEGER)''')
            conn.commit()
    except Exception:
        log.error()


init_db()


def _get_setting(setting_id):
    try:
        return xbmcaddon.Addon().getSetting(setting_id) == 'true'
    except Exception:
        return False


def _set_setting(setting_id, value):
    try:
        xbmcaddon.Addon().setSetting(setting_id, 'true' if value else 'false')
    except Exception:
        pass


def _cleantitle(title):
    s = title or ''
    for strip in _STRIP:
        s = re.split(re.escape(strip), s, flags=re.I)[0]
    s = re.sub(r'^(Spielfilm|Spiellfilm):\s*', '', s, flags=re.I)
    s = re.sub(r'\(.*?\)', '', s)
    return re.sub(r'[^a-z0-9]', '', s.lower())


def _clean_entry_title(title):
    clean = re.sub(r'\s+[-\u2013]\s+.*$', '', title).strip()
    for strip in _STRIP:
        clean = re.split(re.escape(strip), clean, flags=re.I)[0]
    clean = re.sub(r'^(Spielfilm|Spiellfilm):\s*', '', clean, flags=re.I).strip()
    return clean or title


def _clean_title_year(title):
    s = title or ''
    for strip in _STRIP:
        s = re.split(re.escape(strip), s, flags=re.I)[0]
    s = re.sub(r'^(Spielfilm|Spiellfilm):\s*', '', s, flags=re.I)
    s = re.sub(r'\(.*?\)', '', s).strip()
    m = re.search(r'(\d{4})', title)
    return s, m.group(1) if m else ''


def _is_valid(entry):
    if entry.get('duration', 0) < _MIN_DURATION:
        return False
    channel = entry.get('channel', '').lower()
    if any(c in channel for c in _SKIP_CHANNELS):
        return False
    title = entry.get('title', '').lower()
    if 'zdf-tivi' in title or 'tivi' in title or title == 'nö':
        return False
    if any(x in title for x in _SKIP):
        return False
    for rx in _SKIP_REGEX:
        if re.search(rx, title, re.I):
            return False
    return True


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


def _get_tmdb_data(title, year=''):
    data = {'g': ['Sonstige'], 'r': 0.0, 'y': year, 'plot': '', 'poster': ''}
    try:
        params = {'api_key': _TMDB_KEY, 'query': title, 'language': 'de-DE', 'include_adult': 'false'}
        if year:
            params['year'] = year
            
        r = multiquest.get('https://api.themoviedb.org/3/search/movie', params=params, timeout=8)
        results = r.json().get('results', [])
        
        if not results and year:
            del params['year']
            r = multiquest.get('https://api.themoviedb.org/3/search/movie', params=params, timeout=8)
            results = r.json().get('results', [])
            
        if not results:
            r = multiquest.get('https://api.themoviedb.org/3/search/tv', params=params, timeout=8)
            results = r.json().get('results', [])
            
        if results:
            best = results[0]
            ids = best.get('genre_ids', [])
            genres = [_GENRES_MAP[g] for g in ids if g in _GENRES_MAP]
            
            if 16 in ids:
                desc_lower = (best.get('overview', '') + ' ' + title).lower()
                realfilm_kw = ['tatort', 'polizeiruf', 'in aller freundschaft', 'rosenheim-cops', 'krimi', 'fernsehfilm', 'kommissar', 'drama', 'spielfilm']
                if any(kw in desc_lower for kw in realfilm_kw):
                    genres = [g for g in genres if g != 'Animation']
                    
            data['g'] = genres if genres else ['Sonstige']
            data['r'] = best.get('vote_average', 0.0)
            data['plot'] = best.get('overview', '')
            
            path = best.get('poster_path', '')
            data['poster'] = 'https://image.tmdb.org/t/p/w342' + path if path else ''
            
            rd = best.get('release_date', best.get('first_air_date', ''))
            data['y'] = rd[:4] if rd else year
    except Exception:
        pass
    return data


def _notify(msg, title='GEZ Kino', ms=4000):
    try:
        import xbmc
        xbmc.executebuiltin(f'Notification({title},{msg},{ms})')
    except Exception:
        pass


def update_database_background():
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        _notify('Mediathek wird aktualisiert...')
        raw_results = []
        seen = set()
        seen_t = set()

        with ThreadPoolExecutor(max_workers=len(_TERMS)) as ex:
            futures = {ex.submit(_query, t): t for t in _TERMS}
            for f in as_completed(futures):
                for e in f.result():
                    url = e.get('url_video', '')
                    clean_name = _clean_entry_title(e.get('title', '')).lower().strip()
                    if url and url not in seen and clean_name not in seen_t and _is_valid(e):
                        seen.add(url)
                        seen_t.add(clean_name)
                        raw_results.append(e)

        prepared = []
        for e in raw_results:
            title = e.get('title', '')
            url = e.get('url_video', '')
            clean_name, prod_year = _clean_title_year(title)
            clean_name = _clean_entry_title(title)
            if not clean_name:
                continue
            cache_key = clean_name.lower()
            prepared.append((e, clean_name, prod_year, cache_key, url))

        cached_keys = set()
        with sqlite3.connect(_db_path()) as conn:
            rows = conn.execute("SELECT search_title FROM movie_cache").fetchall()
            cached_keys = {r[0] for r in rows}

        to_fetch = [item for item in prepared if item[3] not in cached_keys]

        tmdb_map = {}
        total_fetch = len(to_fetch)

        if total_fetch > 0:
            completed_count = 0
            with ThreadPoolExecutor(max_workers=16) as ex:
                futures = {ex.submit(_get_tmdb_data, item[1], item[2]): item for item in to_fetch}
                for f in as_completed(futures):
                    item = futures[f]
                    tmdb_map[item[3]] = f.result()
                    completed_count += 1

        with sqlite3.connect(_db_path()) as conn:
            conn.execute("DELETE FROM film_list")
            for e, clean_name, prod_year, cache_key, url in prepared:
                if cache_key in tmdb_map:
                    tmdb = tmdb_map[cache_key]
                    conn.execute(
                        "INSERT OR REPLACE INTO movie_cache VALUES (?,?,?,?,?,?)",
                        (cache_key, tmdb['plot'], tmdb['r'], tmdb['poster'],
                         json.dumps(tmdb['g']), tmdb['y'])
                    )
                    final_year = tmdb['y'] or prod_year
                    genres = tmdb['g']
                else:
                    row = conn.execute("SELECT genres_json, year FROM movie_cache WHERE search_title = ?", (cache_key,)).fetchone()
                    if row:
                        genres = json.loads(row[0]) if row[0] else ['Sonstige']
                        final_year = row[1] if row[1] else prod_year
                    else:
                        genres = ['Sonstige']
                        final_year = prod_year

                conn.execute(
                    "INSERT OR REPLACE INTO film_list VALUES (?,?,?,?,?,?,?)",
                    (hashlib.md5(url.encode()).hexdigest(), clean_name, url,
                     clean_name.lower(), final_year if final_year else '', json.dumps(genres), e.get('timestamp', 0))
                )
            conn.commit()

        _notify(f'Aktualisierung abgeschlossen! ({len(prepared)} Filme)')
        log.log(f'[gezkino] Datenbank erfolgreich aktualisiert ({len(prepared)} Filme).')
    except Exception:
        log.error()
        _notify('Fehler beim Aktualisieren der Datenbank.')


def _get_local_movies(genre=None, letter=None, min_r=None, max_r=None, year_filter=None, search_str=None, is_new=False):
    items = []
    hide_tv = _get_setting('hide_tv_films')
    try:
        with sqlite3.connect(_db_path()) as conn:
            query = """
                SELECT f.title, f.video_url, f.year, f.genres_json, c.poster_url, c.plot, c.rating, f.timestamp
                FROM film_list f
                LEFT JOIN movie_cache c ON f.search_name = c.search_title
            """
            rows = conn.execute(query).fetchall()
            
            for r in rows:
                title, url, year, genres_json, poster, plot, rating, timestamp = r
                genres = json.loads(genres_json) if genres_json else ['Sonstige']
                rating = float(rating) if rating is not None else 0.0
                year = str(year) if year else ''

                if hide_tv and 'TV-Film' in genres:
                    continue

                if search_str:
                    if search_str.lower() not in title.lower():
                        continue
                if letter:
                    if not title:
                        continue
                    fc = title[0].upper()
                    if letter == '#' and fc.isalpha():
                        continue
                    elif letter != '#' and fc != letter:
                        continue
                if min_r is not None and max_r is not None:
                    if not (min_r <= rating <= max_r):
                        continue
                if year_filter:
                    if year != str(year_filter):
                        continue
                if genre:
                    if genre == 'Sonstige':
                        if genres and 'Sonstige' not in genres:
                            continue
                    elif genre not in genres:
                        continue

                disp_title = title
                if rating > 0:
                    disp_title = f"{title} [COLOR yellow](★ {rating})[/COLOR]"

                items.append({
                    'title':       disp_title,
                    'url':         title + '||' + url,
                    'mediatype':   'movie',
                    'is_playable': True,
                    'next_func':   'get_hosters',
                    '_rating':     rating,
                    '_timestamp':  timestamp,
                    '_title':      title.lower(),
                    'plot':        plot or '',
                    'poster':      poster or '',
                    'year':        year
                })

            if is_new:
                items.sort(key=lambda x: x['_timestamp'], reverse=True)
                items = items[:100]
            else:
                items.sort(key=lambda x: x['_title'])
    except Exception:
        log.error()
    return items


def load(url='', params=None):
    _plot = '[B]Powered by Zusatzmetall[/B]'
    
    if url == 'toggle_tv':
        current = _get_setting('hide_tv_films')
        _set_setting('hide_tv_films', not current)
        import xbmc
        xbmc.executebuiltin('Container.Refresh')
        return []

    if not url:
        hide_tv = _get_setting('hide_tv_films')
        switch_label = '[B]TV-Filme ausblenden:[/B] [COLOR red]AN[/COLOR]' if hide_tv else '[B]TV-Filme ausblenden:[/B] [COLOR green]AUS[/COLOR]'
        
        return [
            {'title': '[ Alle Spielfilme ]',                 'url': 'all',          'plot': _plot, 'is_playable': False, 'next_func': 'load'},
            {'title': '[ Filme A - Z ]',                     'url': 'az',           'plot': _plot, 'is_playable': False, 'next_func': 'load'},            
            {'title': '[ Neu hinzugefügt ]',                 'url': 'new',          'plot': _plot, 'is_playable': False, 'next_func': 'load'},
            {'title': '[ Nach Bewertung filtern ]',       'url': 'ratings',      'plot': _plot, 'is_playable': False, 'next_func': 'load'},
            {'title': '[ Nach Jahren filtern ]',          'url': 'years',        'plot': _plot, 'is_playable': False, 'next_func': 'load'},
            {'title': '[ Nach Genres filtern ]',          'url': 'genres',       'plot': _plot, 'is_playable': False, 'next_func': 'load'},
            {'title': switch_label,                          'url': 'toggle_tv',    'plot': _plot, 'is_playable': False, 'next_func': 'load'},            
            {'title': '[B][ Datenbank aktualisieren ][/B]',   'url': 'sync',         'plot': _plot, 'is_playable': False, 'next_func': 'load'},
        ]

    if url == 'sync':
        update_database_background()
        return []

    if url == 'all':
        return _get_local_movies()

    if url == 'new':
        return _get_local_movies(is_new=True)
        
    if url == 'az':
        letters = ['#'] + [chr(i) for i in range(65, 91)]
        return [
            {'title': l, 'url': f'letter={l}', 'is_playable': False, 'next_func': 'load'}
            for l in letters
        ]

    if url.startswith('letter='):
        return _get_local_movies(letter=url[7:])

    if url == 'ratings':
        ranges = [(9, 10), (8, 9), (7, 8), (6, 7), (5, 6), (4, 5), (3, 4), (2, 3), (1, 2), (0, 1)]
        return [
            {'title': f'Bewertung {mn}.0 - {mx}.0', 'url': f'rating={mn}-{mx}', 'is_playable': False, 'next_func': 'load'}
            for mn, mx in ranges
        ]
        
    if url.startswith('rating='):
        bounds = url.split('=')[1].split('-')
        return _get_local_movies(min_r=float(bounds[0]), max_r=float(bounds[1]))

    if url == 'years':
        try:
            with sqlite3.connect(_db_path()) as conn:
                rows = conn.execute("SELECT DISTINCT year FROM film_list WHERE year != '' ORDER BY year DESC").fetchall()
                years = [r[0] for r in rows if r[0] and str(r[0]).isdigit() and int(r[0]) > 1900]
            return [
                {'title': f'Jahr {y}', 'url': f'year={y}', 'is_playable': False, 'next_func': 'load'}
                for y in years
            ]
        except Exception:
            return []

    if url.startswith('year='):
        return _get_local_movies(year_filter=url[5:])

    if url == 'genres':
        genres = sorted(list(set(_GENRES_MAP.values()))) + ['Sonstige']
        return [
            {'title': g, 'url': f'genre={g}', 'is_playable': False, 'next_func': 'load'}
            for g in genres
        ]

    if url.startswith('genre='):
        return _get_local_movies(genre=url[6:])

    return []


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if season and int(season) > 0:
        return []

    if url and '||' in url:
        stream = url.split('||')[-1]
        return [('Mediathek', stream, True, 'HD', 'de')]
    return []


def search(query='', params=None):
    return _get_local_movies(search_str=query)


def get_details(url='', params=None):
    if not url:
        return {}
    clean_title = url.split('||')[0] if '||' in url else url
    try:
        with sqlite3.connect(_db_path()) as conn:
            row = conn.execute("""
                SELECT c.plot, c.rating, c.poster_url, c.year 
                FROM movie_cache c 
                JOIN film_list f ON f.search_name = c.search_title 
                WHERE f.title = ?
            """, (clean_title,)).fetchone()
            if row:
                return {
                    'plot':   row[0] or '',
                    'rating': row[1] or 0.0,
                    'poster': row[2] or '',
                    'year':   row[3] or ''
                }
    except Exception:
        log.error()
    return {}


def _warmup_background_sync():
    try:
        import threading
        with sqlite3.connect(_db_path()) as conn:
            count = conn.execute("SELECT COUNT(*) FROM film_list").fetchone()[0]
            if count > 0:
                return
        
        def _run():
            try:
                log.log('[gezkino] Starte initialen Hintergrund-Sync...')
                update_database_background()
            except Exception:
                log.error()
        t = threading.Thread(target=_run, daemon=True)
        t.start()
    except Exception:
        pass

_warmup_background_sync()
