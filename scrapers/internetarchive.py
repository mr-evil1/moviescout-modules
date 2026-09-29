# -*- coding: utf-8 -*-
import re
import json
import datetime
from urllib.parse import quote_plus
import xbmcgui
from resources.lib import multiquest, log

SITE_ID       = 'internetarchive'
SITE_NAME     = 'Internet Archive'
SITE_DOMAIN   = 'archive.org'
TYPE          = 'both'
GLOBAL_SEARCH = True
ACTIVE        = True
STREAMLG      = 'LG0'

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

_COLLECTIONS = {
    'Cinemocracy':        'cinemocracy',
    'Feature Films':      'feature_films',
    'Film Noir':          'Film_Noir',
    'Movie Trailers':     'movie_trailers',
    'SciFi / Horror':     'SciFi_Horror',
    'Short Format Films': 'short_films',
}

_GENRES = [
    'Action', 'Adventure', 'Animation', 'Comedy', 'Crime',
    'Documentary', 'Drama', 'Family', 'Fantasy', 'Film Noir',
    'Horror', 'Musical', 'Mystery', 'Romance', 'Science Fiction',
    'Short', 'Thriller', 'War', 'Western',
]

_LANG_MAP = {
    'ger': 'de', 'german': 'de',
    'eng': 'en', 'english': 'en',
}

_S_COLLECTIONS = '__ia_collections__'
_S_COLL        = '__ia_coll__:'
_S_GENRES      = '__ia_genres__'
_S_GENRE       = '__ia_genre__:'
_S_JAHRE       = '__ia_jahre__'
_S_JAHR        = '__ia_jahr__:'
_S_NEU         = '__ia_neu__:'

_ROWS     = 500
_PAGE_NEU = 50


def _base():
    return 'https://' + SITE_DOMAIN


def _get_json(url):
    try:
        r = multiquest.get(url, headers={'User-Agent': _UA, 'Accept': 'application/json'}, timeout=20)
        r.raise_for_status()
        return json.loads(r.text)
    except Exception:
        log.error()
        return {}


def _thumb(identifier):
    return 'https://archive.org/services/img/' + identifier


def _adv_url(q, sort='', rows=_ROWS, page=1):
    url = (
        _base() + '/advancedsearch.php?q=' + q +
        '+AND+mediatype%3Amovies'
        '&fl[]=description&fl[]=identifier&fl[]=language&fl[]=title&fl[]=year'
        '&rows=' + str(rows) + '&page=' + str(page) + '&output=json'
    )
    if sort:
        url += '&sort[]=' + sort
    return url


def _parse_docs(docs):
    items = []
    for doc in docs:
        identifier = doc.get('identifier', '')
        title      = doc.get('title', '')
        if not identifier or not title:
            continue
        item = {
            'title':       title,
            'url':         identifier,
            'poster':      _thumb(identifier),
            'mediatype':   'movie',
            'next_func':   'get_hosters',
            'is_playable': True,
        }
        year = str(doc.get('year') or '')
        if len(year) == 4:
            item['year'] = year
        desc = doc.get('description') or ''
        if desc:
            item['plot'] = str(desc)[:600]
        lang_out = _LANG_MAP.get((doc.get('language') or '').lower().strip(), '')
        if lang_out:
            item['lang'] = lang_out
        items.append(item)
    return items


def _docs_from(data):
    return (data.get('response') or {}).get('docs') or []


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Kollektionen', 'url': _S_COLLECTIONS, 'next_func': 'load',   'is_playable': False},
            {'title': 'Genre',        'url': _S_GENRES,       'next_func': 'load',   'is_playable': False},
            {'title': 'Jahre',        'url': _S_JAHRE,        'next_func': 'load',   'is_playable': False},
            {'title': 'Neu',          'url': _S_NEU + '1',    'next_func': 'load',   'is_playable': False},
            {'title': 'Suche',        'url': '',              'next_func': 'search', 'is_playable': False},
        ]

    if url == _S_COLLECTIONS:
        return [
            {'title': name, 'url': _S_COLL + coll_id, 'next_func': 'load', 'is_playable': False}
            for name, coll_id in _COLLECTIONS.items()
        ]

    if url.startswith(_S_COLL):
        coll_id = url[len(_S_COLL):]
        data = _get_json(_adv_url('collection%3A' + quote_plus(coll_id)))
        return _parse_docs(_docs_from(data))

    if url == _S_GENRES:
        return [
            {'title': g, 'url': _S_GENRE + g, 'next_func': 'load', 'is_playable': False}
            for g in _GENRES
        ]

    if url.startswith(_S_GENRE):
        genre = url[len(_S_GENRE):]
        data = _get_json(_adv_url(quote_plus(genre)))
        return _parse_docs(_docs_from(data))

    if url == _S_JAHRE:
        year = datetime.datetime.now().year
        return [
            {'title': str(y), 'url': _S_JAHR + str(y), 'next_func': 'load', 'is_playable': False}
            for y in range(year, 1919, -1)
        ]

    if url.startswith(_S_JAHR):
        year = url[len(_S_JAHR):]
        data = _get_json(_adv_url('year%3A' + quote_plus(year)))
        return _parse_docs(_docs_from(data))

    if url.startswith(_S_NEU):
        try:
            page = int(url[len(_S_NEU):] or 1)
        except ValueError:
            page = 1
        data  = _get_json(_adv_url('mediatype%3Amovies', sort='addeddate+desc', rows=_PAGE_NEU, page=page))
        items = _parse_docs(_docs_from(data))
        if len(items) == _PAGE_NEU:
            items.append({
                'title':       '[B]>>> Weiter[/B]',
                'url':         _S_NEU + str(page + 1),
                'next_func':   'load',
                'is_playable': False,
            })
        return items

    return []


def get_hosters(url='', title='', year='', season=0, episode=0, imdb='', tmdb='', params=None):
    if url:
        identifier = url.rstrip('/').split('/')[-1]
        embed = 'https://archive.org/embed/' + identifier
        return [('Archive.org', embed, False, '', '')]

    if not title:
        return []

    clean = _cleantitle(title)
    years = [str(year), str(int(year or 0) + 1)] if year else ['']

    def _search(yr):
        q = quote_plus(title)
        if yr:
            q += '+AND+year%3A' + yr
        data = _get_json(_adv_url(q, rows=20))
        return _docs_from(data)

    for yr in years:
        for doc in _search(yr):
            identifier = doc.get('identifier', '')
            doc_title  = doc.get('title', '')
            if not identifier or not doc_title:
                continue
            if clean in _cleantitle(doc_title) or _cleantitle(doc_title) in clean:
                embed = 'https://archive.org/embed/' + identifier
                return [('Archive.org', embed, False, '', '')]

    return []


def search(query='', params=None, url=''):
    if not query and isinstance(params, dict):
        query = params.get('query') or params.get('keyword') or ''
    if not query and isinstance(url, str) and url:
        query = url
    if not query:
        try:
            r = xbmcgui.Dialog().input('Internet Archive – Suche')
            if r:
                query = r.strip()
        except Exception:
            log.error()
    if not query:
        return []
    data = _get_json(_adv_url(quote_plus(query)))
    return _parse_docs(_docs_from(data))


def get_details(url='', params=None):
    if not url:
        return {}
    identifier = url.rstrip('/').split('/')[-1]
    try:
        data = _get_json(_base() + '/metadata/' + identifier)
        if not data:
            return {}
        result = {'poster': _thumb(identifier)}
        meta = data.get('metadata') or {}
        desc = meta.get('description')
        if desc:
            if isinstance(desc, list):
                desc = desc[0]
            result['plot'] = str(desc)[:600]
        date = meta.get('date') or meta.get('year', '')
        if date:
            m = re.search(r'(\d{4})', str(date))
            if m:
                result['year'] = m.group(1)
        return result
    except Exception:
        log.error()
        return {}
