# -*- coding: utf-8 -*-
# IT('s) Possible 
# 2026.10.19
# MovieScout Scraper gezkino.py
import re
import base64
import json
import os
import time
import hashlib
from resources.lib import multiquest, log
from datetime import datetime
import xbmcaddon

SITE_ID       = 'gezkino'
SITE_NAME     = 'GEZ KiNO'
SITE_DOMAIN   = 'mediathekviewweb.de'
TYPE          = 'movie'
GLOBAL_SEARCH = True
STREAMLG      = 'LG0'

_UA          = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
_MIN_DURATION = 4680

_GITHUB_JSON_URL = 'https://raw.githubusercontent.com/Chrisophy/GEZ-KiNO/refs/heads/main/movies.json'

_GENRES_MAP = {
    28: 'Action', 12: 'Abenteuer', 35: u'Kom\xf6die', 80: 'Krimi', 99: 'Doku',
    18: 'Drama', 10751: 'Familie', 14: 'Fantasy', 36: 'Historie', 27: 'Horror', 10402: 'Musik',
    9648: 'Mystery', 10749: 'Romanze', 878: 'Sci-Fi', 10770: 'TV-Film', 53: 'Thriller',
    10752: 'Krieg', 37: 'Western',
}


def _json_path():
    try:
        from resources.lib.control import addonProfile
        path = addonProfile()
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        return os.path.join(path, 'movies.json')
    except Exception:
        return 'movies.json'


def _download_movies_json():
    try:
        r = multiquest.get(_GITHUB_JSON_URL, headers={'User-Agent': _UA}, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                path = _json_path()
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return data
    except Exception:
        log.error()
    return None


def _get_movies():
    path = _json_path()
    if not os.path.exists(path):
        data = _download_movies_json()
        if data is not None:
            return data
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        log.error()
        return []


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


_SYNC_RUNNING = False


def update_database_background():
    global _SYNC_RUNNING
    if _SYNC_RUNNING:
        return
    _SYNC_RUNNING = True

    try:
        log.log('[gezkino] Starte Download der Datenbank...')
        data = _download_movies_json()
        if data:
            log.log(f'[gezkino] Datenbank erfolgreich aktualisiert ({len(data)} Filme).')
        else:
            log.log('[gezkino] Fehler beim Aktualisieren der Datenbank.')
    except Exception:
        log.error()
    finally:
        _SYNC_RUNNING = False


def _get_local_movies(genre=None, letter=None, min_r=None, max_r=None, year_filter=None, search_str=None, is_new=False):
    items = []
    hide_tv = _get_setting('hide_tv_films')
    movies = _get_movies()
    
    for m in movies:
        try:
            title = m.get('title', '')
            url = m.get('video_url', '')
            year = str(m.get('year', ''))
            if year in ['None', 'LIVE']:
                year = ''
            
            genres = m.get('genres_list', ['Sonstige'])
            if not genres:
                genres = ['Sonstige']
            
            rating_str = m.get('rating', '0.0')
            try:
                rating = float(rating_str) if rating_str and rating_str != 'N/A' else 0.0
            except ValueError:
                rating = 0.0
                
            director = m.get('director', '') or ''
            actors = m.get('actors', []) or []
            timestamp = m.get('timestamp', 0)
            plot = m.get('plot', '') or ''
            poster = m.get('thumb', '')
            if poster == 'placeholder.png':
                poster = ''
            is_new_flag = m.get('isNew', False)

            if hide_tv and 'TV-Film' in genres:
                continue

            if search_str:
                sb = search_str.lower()
                actors_combined = " ".join(actors).lower()
                if sb not in title.lower() and sb not in director.lower() and sb not in actors_combined:
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

            meta_plot = ""
            if rating > 0:
                meta_plot += f"[COLOR yellow]★ {rating:.1f}[/COLOR]\n"
            if director:
                meta_plot += f"[B]Regie:[/B] {director}\n"
            if actors:
                meta_plot += f"[B]Cast:[/B] {', '.join(actors)}\n"
            if meta_plot:
                meta_plot += "--------------------------------------------------------\n"
            meta_plot += plot
            
            disp_title = f"{title}" if year else title

            items.append({
                'title':       disp_title,
                'url':         title + '||' + url,
                'mediatype':   'movie',
                'is_playable': True,
                'next_func':   'get_hosters',
                '_rating':     rating,
                '_timestamp':  timestamp,
                '_title':      title.lower(),
                '_is_new':     is_new_flag,
                'plot':        meta_plot,
                'poster':      poster,
                'year':        year
            })
        except Exception:
            continue

    if is_new:
        items.sort(key=lambda x: x['_timestamp'], reverse=True)
        items = items[:100]
    else:
        items.sort(key=lambda x: x['_title'])

    return items


def load(url='', params=None):
    if url == 'toggle_tv':
        current = _get_setting('hide_tv_films')
        _set_setting('hide_tv_films', not current)
        try:
            import xbmcgui
            xbmcgui.Dialog().notification('GEZ KiNO', 'Filter aktualisiert...', xbmcgui.NOTIFICATION_INFO, 3000)
        except Exception:
            pass
        url = ''
        
    if url == 'sync':
        update_database_background()
        try:
            import xbmcgui
            xbmcgui.Dialog().notification('GEZ KiNO', 'Datenbank aktualisiert...', xbmcgui.NOTIFICATION_INFO, 3000)
        except Exception:
            pass
        url = ''

    if not url:
        hide_tv = _get_setting('hide_tv_films')
        switch_label = '[ [B]TV-Filme:[/B] [COLOR red]NEIN[/COLOR] ]' if hide_tv else '[ [B]TV-Filme:[/B] [COLOR green]JA[/COLOR] ]'
        
        return [
            {
                'title': '[ Alle Spielfilme ]',
                'url': 'all',
                'plot': '[B]GEZ KiNO – Alle Spielfilme[/B]\n\nDurchstöbere die vollständige Liste aller verfügbaren Spielfilme und Kinoproduktionen aus den Mediatheken.',
                'is_playable': False,
                'next_func': 'load'
            },
            {
                'title': '[ Filme A - Z ]',
                'url': 'az',
                'plot': '[B]Alphabetische Sortierung[/B]\n\nFinde deine gewünschten Filme schnell und übersichtlich sortiert nach Anfangsbuchstaben (A–Z und Sonderzeichen).',
                'is_playable': False,
                'next_func': 'load'
            },            
            {
                'title': '[ Neu hinzugefügt ]',
                'url': 'new',
                'plot': '[B]Frisch eingetroffen[/B]\n\nEntdecke die neuesten Spielfilm-Uploads aus den Mediatheken, sortiert nach Aktualität (die neuesten zuerst).',
                'is_playable': False,
                'next_func': 'load'
            },
            {
                'title': '[ Nach Bewertung sortiert ]',
                'url': 'ratings',
                'plot': '[B]Top-Filme nach IMDb-Bewertung[/B]\n\nFinde gezielt die am besten bewerteten Filme, unterteilt in verschiedene Qualitäts- und Bewertungsstufen.',
                'is_playable': False,
                'next_func': 'load'
            },
            {
                'title': '[ Nach Jahren sortiert ]',
                'url': 'years',
                'plot': '[B]Chronologische Auswahl[/B]\n\nWähle gezielt ein bestimmtes Produktionsjahr aus, um Film-Highlights aus vergangenen Jahrzehnten oder aktuellen Jahren zu finden.',
                'is_playable': False,
                'next_func': 'load'
            },
            {
                'title': '[ Nach Genres sortiert ]',
                'url': 'genres',
                'plot': '[B]Film-Genres[/B]\n\nFiltere das Angebot nach deinen Lieblings-Kategorien wie Komödie, Drama, Krimi, Thriller, Sci-Fi oder Dokumentarfilm.',
                'is_playable': False,
                'next_func': 'load'
            },
            {
                'title': '[ Suche nach ]',
                'url': 'search',
                'plot': '[B]Gezielte Suche[/B]\n\nStarte eine Direktsuche nach Filmtiteln, Regisseuren oder Schauspielern.',
                'is_playable': False,
                'next_func': 'do_search'
            },                   
            {
                'title': switch_label,
                'url': 'toggle_tv',
                'plot': '[B]Filter: Klassische TV-Filme[/B]\n\nSchalte ein oder aus, ob klassische Fernsehfilme und TV-Produktionen in den Listen angezeigt werden sollen.',
                'is_playable': False,
                'next_func': 'load'
            },    
            {
                'title': '[B][ Datenbank aktualisieren ][/B]',
                'url': 'sync',
                'plot': '[B]Filmliste aktualisieren[/B]\n\nLädt die aktuelle Datenbank herunter, um neue Filme und Metadaten zu laden.',
                'is_playable': False,
                'next_func': 'load'
            },
        ]

    if url == 'all':
        return _get_local_movies()

    if url == 'new':
        return _get_local_movies(is_new=True)
        
    if url == 'az':
        letters = ['#'] + [chr(i) for i in range(65, 91)]
        return [
            {'title': l, 'url': f'letter={l}', 'plot': f'[B]Filme mit Anfangsbuchstabe: {l}[/B]\n\nZeigt alle Spielfilme, deren Titel mit "{l}" beginnen.', 'is_playable': False, 'next_func': 'load'}
            for l in letters
        ]

    if url.startswith('letter='):
        return _get_local_movies(letter=url[7:])

    if url == 'ratings':
        ranges = [(9, 10), (8, 9), (7, 8), (6, 7), (5, 6), (4, 5), (3, 4), (2, 3), (1, 2), (0, 1)]
        return [
            {'title': f'Bewertung {mn}.0 - {mx}.0', 'url': f'rating={mn}-{mx}', 'plot': f'[B]Bewertungskategorie: {mn}.0 bis {mx}.0 Sterne[/B]\n\nFilme mit einer TMDb-Wertung in diesem Bereich.', 'is_playable': False, 'next_func': 'load'}
            for mn, mx in ranges
        ]
        
    if url.startswith('rating='):
        bounds = url.split('=')[1].split('-')
        return _get_local_movies(min_r=float(bounds[0]), max_r=float(bounds[1]))

    if url == 'years':
        try:
            movies = _get_movies()
            years_set = set()
            for m in movies:
                y = str(m.get('year', ''))
                if y and y.isdigit() and int(y) > 1900:
                    years_set.add(y)
            years = sorted(list(years_set), reverse=True)
            return [
                {'title': f'Jahr {y}', 'url': f'year={y}', 'plot': f'[B]Produktionsjahr {y}[/B]\n\nZeigt alle verfügbaren Spielfilme aus dem Jahr {y}.', 'is_playable': False, 'next_func': 'load'}
                for y in years
            ]
        except Exception:
            return []

    if url.startswith('year='):
        return _get_local_movies(year_filter=url[5:])

    if url == 'genres':
        genres = sorted(list(set(_GENRES_MAP.values()))) + ['Sonstige']
        return [
            {'title': g, 'url': f'genre={g}', 'plot': f'[B]Genre: {g}[/B]\n\nZeigt alle Filme aus der Kategorie {g}.', 'is_playable': False, 'next_func': 'load'}
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
    if title:
        import re
        clean_req = re.sub(r'[^a-z0-9]', '', title.lower())
        if clean_req:
            try:
                movies = _get_movies()
                results = []
                for m in movies:
                    db_title = m.get('title', '')
                    video_url = m.get('video_url', '')
                    db_clean = re.sub(r'[^a-z0-9]', '', db_title.lower())
                    if db_clean and (clean_req in db_clean or db_clean in clean_req):
                        results.append(('Mediathek', video_url, True, 'HD', 'de'))
                return results
            except Exception:
                log.error()
    return []


def search(query='', params=None):
    return _get_local_movies(search_str=query)


def do_search(url='', params=None):
    import xbmcgui
    keyboard = xbmcgui.Dialog().input('Suche nach', type=xbmcgui.INPUT_ALPHANUM)
    if keyboard:
        return _get_local_movies(search_str=keyboard)
    return []


def get_details(url='', params=None):
    if not url:
        return {}
    clean_title = url.split('||')[0] if '||' in url else url
    try:
        movies = _get_movies()
        for m in movies:
            if m.get('title', '') == clean_title:
                plot = m.get('plot', '') or m.get('mediathek_desc', '')
                rating_str = m.get('rating', '0.0')
                try:
                    rating = float(rating_str) if rating_str and rating_str != 'N/A' else 0.0
                except ValueError:
                    rating = 0.0
                poster = m.get('thumb', '')
                if poster == 'placeholder.png':
                    poster = ''
                year = str(m.get('year', ''))
                if year in ['None', 'LIVE']:
                    year = ''
                return {
                    'plot':   plot,
                    'rating': rating,
                    'poster': poster,
                    'year':   year
                }
    except Exception:
        log.error()
    return {}


def _warmup_background_sync():
    try:
        import threading
        path = _json_path()
        if os.path.exists(path):
            return
        
        def _run():
            try:
                log.log('[gezkino] Starte initialen Download der Datenbank...')
                update_database_background()
            except Exception:
                log.error()
        t = threading.Thread(target=_run, daemon=True)
        t.start()
    except Exception:
        pass

_warmup_background_sync()
