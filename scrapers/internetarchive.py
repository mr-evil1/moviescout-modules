# -*- coding: utf-8 -*-
import re
import json
from urllib.parse import quote_plus
from resources.lib import multiquest, log

SITE_ID       = 'internetarchive'
SITE_NAME     = 'Internet Archive'
SITE_DOMAIN   = 'archive.org'
TYPE          = 'movie'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

_COLLECTIONS = {
    'Cinemocracy':       'cinemocracy',
    'Feature Films':     'feature_films',
    'Film Noir':         'Film_Noir',
    'Movie Trailers':    'movie_trailers',
    'SciFi / Horror':    'SciFi_Horror',
    'Short Format Films':'short_films',
}

_LANG_MAP = {
    'ger': 'de', 'german': 'de',
    'eng': 'en', 'english': 'en',
}


def _base():
    return 'https://' + SITE_DOMAIN


def _get(url):
    try:
        r = multiquest.get(url, headers={'User-Agent': _UA}, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _get_json(url):
    try:
        r = multiquest.get(url, headers={'User-Agent': _UA, 'Accept': 'application/json'}, timeout=20)
        r.raise_for_status()
        return json.loads(r.text)
    except Exception:
        log.error()
        return {}


def _coll_url(coll_id):
    return (
        _base() + '/advancedsearch.php?q=collection%3A%22' + coll_id +
        '%22&fl%5B%5D=description&fl%5B%5D=identifier&fl%5B%5D=language'
        '&fl%5B%5D=title&fl%5B%5D=year&rows=80000&page=1&output=json'
    )


def _search_url(query):
    return (
        _base() + '/advancedsearch.php?q=' + quote_plus(query) +
        '%20AND%20mediatype%3Amovies&fl%5B%5D=description&fl%5B%5D=identifier'
        '&fl%5B%5D=language&fl%5B%5D=title&fl%5B%5D=year&rows=500&output=json'
    )


def _thumb(identifier):
    return 'https://archive.org/services/img/' + identifier


def _parse_docs(docs):
    items = []
    for doc in docs:
        identifier = doc.get('identifier', '')
        title      = doc.get('title', '')
        if not identifier or not title:
            continue
        lang_raw = (doc.get('language') or '').lower().strip()
        item = {
            'title':       title,
            'url':         _base() + '/details/' + identifier,
            'poster':      _thumb(identifier),
            'mediatype':   'movie',
            'next_func':   'get_hosters',
            'is_playable': True,
        }
        if doc.get('year') and len(str(doc['year'])) == 4:
            item['year'] = str(doc['year'])
        if doc.get('description'):
            item['plot'] = str(doc['description'])[:600]
        lang_out = _LANG_MAP.get(lang_raw, '')
        if lang_out:
            item['lang'] = lang_out
        items.append(item)
    return items


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Kollektionen', 'url': '__collections__',
             'next_func': 'load', 'is_playable': False},
        ]

    if url == '__collections__':
        return [
            {'title': name, 'url': _coll_url(coll_id),
             'next_func': 'load', 'is_playable': False}
            for name, coll_id in _COLLECTIONS.items()
        ]

    data = _get_json(url)
    docs = (data.get('response') or {}).get('docs') or []
    return _parse_docs(docs)


def get_hosters(url='', params=None):
    html = _get(url)
    m    = re.search(r'itemprop="embedUrl".*?href="([^"]+)"', html, re.S)
    if not m:
        return []
    embed = m.group(1)
    if embed.startswith('//'):
        embed = 'https:' + embed
    name = 'YouTube' if 'youtube' in embed else 'Archive.org'
    return [(name, embed, False, '', '')]


def search(query='', params=None):
    data = _get_json(_search_url(query))
    docs = (data.get('response') or {}).get('docs') or []
    return _parse_docs(docs)


def get_details(url='', params=None):
    if not url or '/details/' not in url:
        return {}
    identifier = url.rstrip('/').split('/')[-1]
    try:
        data = _get_json(_base() + '/metadata/' + identifier)
        if not data:
            return {}
        result = {'poster': _thumb(identifier)}
        meta   = data.get('metadata') or {}
        desc   = meta.get('description')
        if desc:
            if isinstance(desc, list):
                desc = desc[0]
            result['plot'] = str(desc)[:600]
        date = meta.get('date') or meta.get('year', '')
        if date:
            m_year = re.search(r'(\d{4})', str(date))
            if m_year:
                result['year'] = m_year.group(1)
        return result
    except Exception:
        log.error()
        return {}
