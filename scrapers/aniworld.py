# -*- coding: utf-8 -*-
import re
import datetime
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from resources.lib import multiquest, log

SITE_ID       = 'aniworld'
SITE_NAME     = 'AniWorld'
SITE_DOMAIN   = 'aniworld.to'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

_LANG_LABELS = {'1': 'DE', '3': 'SUB'}


def _base():
    return 'https://' + SITE_DOMAIN


def _get(url, referer=None):
    headers = {'User-Agent': _UA, 'Accept-Language': 'de-DE,de;q=0.9'}
    if referer:
        headers['Referer'] = referer
    try:
        r = multiquest.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _cleantitle(s):
    s = (s or '').lower()
    return re.sub(r'[^a-z0-9]', '', s)


_BYSE_DOMAINS = ('bysezejataos.com',)


def _byse_rewrite(url):
    for domain in _BYSE_DOMAINS:
        if domain in url:
            return re.sub(r'(https?://[^/]+)/d/', r'\1/e/', url)
    return url


def _follow_redirect(full_url):
    try:
        r = multiquest.get(
            full_url,
            headers={'User-Agent': _UA, 'Referer': _base(),
                     'Upgrade-Insecure-Requests': '1'},
            timeout=10, allow_redirects=True
        )
        resolved = r.url if r.url != full_url else full_url
        return _byse_rewrite(resolved)
    except Exception:
        log.error()
        return full_url


def _extract_hosters_from_page(episode_url):
    html    = _get(episode_url, _base())
    raw     = []
    pattern = r'data-lang-key=\"(\d+)\"(.*?)(?=data-lang-key=\"|</ul>)'
    for lang_id, block in re.findall(pattern, html, re.S):
        lang_label = _LANG_LABELS.get(lang_id)
        if not lang_label:
            continue
        for redirect_path, provider in re.findall(
            r'href=\"(/redirect/[^\"]+)\".*?<h4>([^<]+)<', block, re.S
        ):
            label = lang_label + ' | ' + provider.strip()
            raw.append((label, _base() + redirect_path, lang_id))
    if not raw:
        for redirect_path, provider in re.findall(
            r'href=\"(/redirect/[^\"]+)\".*?<h4>([^<]+)<', html, re.S
        ):
            raw.append((provider.strip(), _base() + redirect_path, ''))

    def _resolve_entry(entry):
        label, redirect_url, lang_id = entry
        final_url = _follow_redirect(redirect_url)
        return label, final_url, lang_id

    result = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_resolve_entry, e): e for e in raw}
        for f in as_completed(futures):
            try:
                label, resolved_url, lang_id = f.result(timeout=15)
                result.append((label, resolved_url, lang_id))
            except Exception:
                orig = futures[f]
                result.append((orig[0], orig[1], orig[2]))
    return result


def _find_page_url(title, season=0, episode=0):
    clean = _cleantitle(title)
    html  = _get(_base() + '/animes?search=%s' % quote(title))
    for s_url, s_name in re.findall(r'href=\"(/anime/[^\"]+)\"[^>]*>([^<]+)', html):
        if _cleantitle(s_name) == clean or clean in _cleantitle(s_name):
            series_url = _base() + s_url
            if season and episode:
                return series_url.rstrip('/') + '/staffel-%s/episode-%s' % (season, episode)
            return series_url
    return ''


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    scout_mode = bool(title or imdb or tmdb) and not url

    if url and '/episode-' in url:
        raw = _extract_hosters_from_page(url)
    elif url and '/staffel-' in url:
        ep_url = url.rstrip('/') + '/episode-%s' % episode
        raw = _extract_hosters_from_page(ep_url)
    else:
        series_url = url or _find_page_url(title, season, episode)
        if not series_url:
            return []
        if season and episode and '/episode-' not in series_url:
            series_url = series_url.rstrip('/') + '/staffel-%s/episode-%s' % (season, episode)
        raw = _extract_hosters_from_page(series_url)

    if not scout_mode:
        return [(r[0], r[1], False, 'HD', '') for r in raw]

    result = []
    for label, play_url, lang_id in raw:
        lang = 'de' if lang_id == '1' else 'sub'
        result.append((label, play_url, False, 'HD', lang))
    return result


def _browse_series_page(url):
    html  = _get(url)
    items = []

    season_container = re.search(
        r'class=\"hosterSiteDirectNav\"[^>]*>.*?<ul>(.*?)</ul>', html, re.S
    )
    if season_container:
        for s_href, s_title in re.findall(
            r'<a[^>]*href=\"([^\"]+)\"[^>]*title=\"([^\"]+)\"', season_container.group(1), re.S
        ):
            full_url = _base() + s_href if s_href.startswith('/') else s_href
            items.append({
                'title':       s_title.strip(),
                'url':         full_url,
                'next_func':   'load',
                'mediatype':   'season',
                'is_playable': False,
            })
        if items:
            return items

    for s_num in sorted(set(re.findall(r'href=\"[^\"]+/staffel-(\d+)\"', html)), key=int):
        items.append({
            'title':       'Staffel %s' % s_num,
            'url':         url.rstrip('/') + '/staffel-' + s_num,
            'next_func':   'load',
            'mediatype':   'season',
            'is_playable': False,
        })
    return items


def _browse_season_page(url):
    html  = _get(url)
    items = []
    table = re.search(r'<table[^>]*class=\"seasonEpisodesList\"[^>]*>(.*?)</table>', html, re.S)
    if table:
        for ep_id, ep_href, name_ger, name_eng in re.findall(
            r'<tr[^>]*data-episode-season-id=\"(\d+).*?<a href=\"([^\"]+).*?(?:<strong>(.*?)</strong>.*?)?(?:<span>(.*?)</span>.*?)?<',
            table.group(1), re.S
        ):
            ep_name = (name_ger or name_eng or '').strip(' -') or ('Episode ' + ep_id)
            label   = '%s - %s' % (ep_id, ep_name)
            ep_url  = _base() + ep_href if ep_href.startswith('/') else ep_href
            items.append({
                'title':       label,
                'url':         ep_url,
                'next_func':   'get_hosters',
                'mediatype':   'episode',
                'is_playable': True,
            })
    if not items:
        for ep_num in sorted(set(re.findall(r'/episode-(\d+)', html)), key=int):
            items.append({
                'title':       'Episode %s' % ep_num,
                'url':         url.rstrip('/') + '/episode-' + ep_num,
                'next_func':   'get_hosters',
                'mediatype':   'episode',
                'is_playable': True,
            })
    return items


def _browse_list_page(url):
    html  = _get(url)
    items = []

    pattern = (
        r'<div[^>]*class=\"col-md-[^\"]*\"[^>]*>.*?'
        r'<a[^>]*href=\"(/anime/[^\"]+)\"[^>]*>.*?'
        r'<img[^>]*(?:data-src|src)=\"([^\"]+)\"[^>]*>.*?'
        r'<h3>(.*?)<span[^>]*class=\"paragraph-end'
    )
    for s_url, thumb, s_name in re.findall(pattern, html, re.S):
        s_name   = re.sub(r'<[^>]+>', '', s_name).strip()
        full_url = _base() + s_url
        if thumb.startswith('/'):
            thumb = _base() + thumb
        items.append({
            'title':       s_name,
            'url':         full_url,
            'poster':      thumb,
            'mediatype':   'tvshow',
            'next_func':   'load',
            'is_playable': False,
        })

    next_m = re.search(r'pagination\">.*?<a href=\"([^\"]+)\">>%s</a>' % '', html, re.S)
    if not next_m:
        next_m = re.search(r'<a href=\"([^\"]+)\">></a>', html, re.S)
    if next_m:
        next_url = next_m.group(1)
        if next_url.startswith('/'):
            next_url = _base() + next_url
        items.append({
            'title':       '[B]>>> Weiter[/B]',
            'url':         next_url,
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def _browse_new_animes():
    html  = _get(_base())
    items = []
    m = re.search(
        r'Neue Animes</h2>.*?<div class=\"previews\">(.*?)</div>\s*</div>\s*<div class=\"cf\">',
        html, re.S
    )
    if not m:
        return items
    pattern = (
        r'<div class=\"coverListItem\"><a href=\"(/anime/stream/[^\"]+)\"[^>]*>'
        r'.*?(?:data-src|src)=\"([^\"]+)\"[^>]*>'
        r'.*?<h3>([^<]+)<span'
        r'.*?<small>([^<]*)</small>'
    )
    for s_url, thumb, s_name, genre in re.findall(pattern, m.group(1), re.S):
        s_name = s_name.strip()
        if not s_name:
            continue
        if thumb.startswith('/'):
            thumb = _base() + thumb
        label = s_name
        if genre.strip():
            label += '  [COLOR gray][%s][/COLOR]' % genre.strip()
        items.append({
            'title':       label,
            'url':         _base() + s_url,
            'poster':      thumb,
            'mediatype':   'tvshow',
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def _browse_genres():
    html  = _get(_base())
    items = []
    m = re.search(r'<ul[^>]*class=\"homeContentGenresList\"[^>]*>(.*?)</ul>', html, re.S)
    if not m:
        return items
    for href, name in re.findall(r'<li>\s*<a[^>]*href=\"([^\"]*)\"[^>]*>(.*?)</a>\s*</li>', m.group(1), re.S):
        full_url = href if href.startswith('http') else _base() + href
        items.append({
            'title':       name.strip(),
            'url':         full_url,
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def _browse_az():
    html  = _get(_base())
    items = []
    m = re.search(r'<ul[^>]*class=\"catalogNav\"[^>]*>(.*?)</ul>', html, re.S)
    if not m:
        return items
    for href, name in re.findall(r'<li>\s*<a[^>]*href=\"([^\"]*)\"[^>]*>(.*?)</a>\s*</li>', m.group(1), re.S):
        full_url = href if href.startswith('http') else _base() + href
        items.append({
            'title':       name.strip(),
            'url':         full_url,
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def _browse_year_submenu():
    current_year = datetime.datetime.now().year
    return [
        {
            'title':       str(y),
            'url':         _base() + '/animes/jahr/%d' % y,
            'next_func':   'load',
            'is_playable': False,
        }
        for y in range(current_year, 1989, -1)
    ]


def _browse_year_entries(url):
    html  = _get(url)
    items = []
    pattern = (
        r'href=\"(/anime/stream/[^\"]+)\"[^>]*>'
        r'.*?(?:data-src|src)=\"([^\"]+)\"'
        r'.*?<h3>([^<]+)<span[^>]*></span></h3>'
        r'\s*<small>([^<]*)</small>'
    )
    for s_url, thumb, s_name, genre in re.findall(pattern, html, re.S):
        s_name = s_name.strip()
        if thumb.startswith('/'):
            thumb = _base() + thumb
        items.append({
            'title':       s_name,
            'url':         _base() + s_url,
            'poster':      thumb,
            'mediatype':   'tvshow',
            'next_func':   'load',
            'is_playable': False,
        })
    next_m = re.search(r'pagination\">.*?<a href=\"([^\"]+)\">>%s</a>' % '', html, re.S)
    if not next_m:
        next_m = re.search(r'<a href=\"([^\"]+)\">></a>', html, re.S)
    if next_m:
        next_url = next_m.group(1)
        if next_url.startswith('/'):
            next_url = _base() + next_url
        items.append({
            'title':       '[B]>>> Weiter[/B]',
            'url':         next_url,
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def _browse_entries(url):
    if '/staffel-' in url:
        return _browse_season_page(url)
    if '/anime/stream/' in url or '/anime/' in url:
        return _browse_series_page(url)
    if '/animes/jahr/' in url:
        return _browse_year_entries(url)
    return _browse_list_page(url)


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Neue Animes', 'url': '__new_animes__',           'next_func': 'load', 'is_playable': False},
            {'title': 'Neue Folgen', 'url': _base() + '/neue-episoden', 'next_func': 'load', 'is_playable': False},
            {'title': 'Beliebt',     'url': _base() + '/beliebte-animes','next_func': 'load', 'is_playable': False},
            {'title': 'Genres',      'url': '__genres__',                'next_func': 'load', 'is_playable': False},
            {'title': 'Jahr',        'url': '__year__',                  'next_func': 'load', 'is_playable': False},
            {'title': 'A-Z',         'url': '__az__',                    'next_func': 'load', 'is_playable': False},
            {'title': 'Alle Animes', 'url': _base() + '/animes',        'next_func': 'load', 'is_playable': False},
        ]

    if url == '__new_animes__':
        return _browse_new_animes()
    if url == '__genres__':
        return _browse_genres()
    if url == '__az__':
        return _browse_az()
    if url == '__year__':
        return _browse_year_submenu()

    return _browse_entries(url)


def search(query='', params=None):
    html  = _get(_base() + '/animes', referer=_base())
    clean = _cleantitle(query)
    items = []
    for s_href, s_name in re.findall(r'<li><a[^>]+href=\"([^\"]+)\"[^>]*>([^<]+)</a>', html):
        if clean not in _cleantitle(s_name):
            continue
        full_url = _base() + s_href if s_href.startswith('/') else s_href
        items.append({
            'title':       s_name.strip(),
            'url':         full_url,
            'mediatype':   'tvshow',
            'next_func':   'load',
            'is_playable': False,
        })
    return items


def get_details(url='', params=None):
    if not url or url.startswith('__'):
        return {}
    if '/staffel-' in url or '/episode-' in url:
        return {}
    try:
        html = _get(url)
        if not html:
            return {}

        result = {}

        desc_m = re.search(r'data-full-description=\"([^\"]+)\"', html)
        if desc_m:
            import html as _html_mod
            result['plot'] = _html_mod.unescape(desc_m.group(1))

        thumb_m = re.search(
            r'<div[^>]*class=\"seriesCoverBox\"[^>]*>.*?<img[^>]*src=\"([^\"]+)\"', html, re.S
        )
        if thumb_m:
            thumb = thumb_m.group(1)
            if thumb.startswith('/'):
                thumb = _base() + thumb
            result['poster'] = thumb

        year_m = re.search(r'itemprop=\"startDate\"[^>]*>\s*<a[^>]*>(\d{4})</a>', html)
        if year_m:
            result['year'] = year_m.group(1)

        return result
    except Exception:
        log.error()
        return {}
