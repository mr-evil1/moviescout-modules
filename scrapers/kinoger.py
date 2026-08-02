# -*- coding: utf-8 -*-
import re
import ast
from urllib.parse import quote
from resources.lib import multiquest, log

SITE_ID       = 'kinoger'
SITE_NAME     = 'KinoGer'
SITE_DOMAIN   = 'kinoger.com'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

_SKIP_DOMAINS = (
    'googletagmanager.com', 'google-analytics.com', 'googlesyndication.com',
    'doubleclick.net', 'googleapis.com', 'gstatic.com',
    'facebook.com', 'twitter.com', 'instagram.com',
)

_S_KINO    = '__kg_kino__'
_S_MOVIES  = '__kg_movies__'
_S_SERIES  = '__kg_series__'
_S_GENRE   = '__kg_genre__'
_S_SEASONS = '__kg_seasons__:'
_S_EP      = '__kg_ep__:'


def _base():
    return 'https://' + SITE_DOMAIN


def _get(url, referer=None, post=False, post_data=None, ua=None):
    headers = {'User-Agent': ua or _UA, 'Referer': referer or (_base() + '/')}
    try:
        if post:
            r = multiquest.post(url, data=post_data or {}, headers=headers, timeout=10)
        else:
            r = multiquest.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _quality(label):
    label = (label or '').upper()
    if '2160' in label or '4K' in label: return '4K'
    if '1080' in label or 'HD+' in label: return '1080p'
    if '720' in label or label == 'HD': return '720p'
    if '480' in label: return '480p'
    return 'HD'


def _parse_entries(html, is_series_page=False):
    items = []
    for block in html.split('<div class=\"short\">')[1:]:
        link_m = re.search(
            r'class=[\"\'"]begin[\"\'"][^>]*>.*?<a href=\"(https?://[^\"]+\.html)\"[^>]*>([^<]+)</a>',
            block, re.S)
        if not link_m:
            continue
        href  = link_m.group(1)
        name  = link_m.group(2).strip()
        thumb_m = re.search(r'<!--dle_image_begin:([^|>]+)\|', block)
        if not thumb_m:
            thumb_m = re.search(r'<img[^>]+src=\"((?:https?://|/uploads/)[^\"]+)\"', block)
        thumb = thumb_m.group(1) if thumb_m else ''
        if thumb.startswith('/'):
            thumb = _base() + thumb
        is_series = is_series_page or bool(
            re.search(r'text-align:right[^>]*>(?:<[^>]+>)*\s*S\d{1,2}', block[:1000])
        )
        if is_series:
            items.append({
                'title':       name,
                'url':         _S_SEASONS + href,
                'poster':      thumb,
                'mediatype':   'tvshow',
                'is_playable': False,
                'next_func':   'load',
            })
        else:
            items.append({
                'title':       name,
                'url':         href,
                'poster':      thumb,
                'mediatype':   'movie',
                'is_playable': True,
                'next_func':   'get_hosters',
            })
    m_next = re.search(r'<a href=\"([^\"]+)\"[^>]*>\s*vorw', html, re.I)
    if m_next:
        next_url = m_next.group(1)
        if next_url.startswith('/'):
            next_url = _base() + next_url
        items.append({'title': '[B]>>> Weiter[/B]', 'url': next_url,
                      'next_func': 'load', 'is_playable': False})
    return items


def _parse_search_results(html, is_series_page=False):
    items = []
    for block in html.split('<div class=\"titlecontrol\">')[1:]:
        link_m = re.search(
            r'<a href=\"(https://kinoger\.com/stream/[^\"]+\.html)\"[^>]*>([^<]+)</a>',
            block[:600])
        if not link_m:
            continue
        href = link_m.group(1)
        name = link_m.group(2).strip()
        thumb_m = re.search(r'<!--dle_image_begin:([^|>]+)\|', block)
        if not thumb_m:
            thumb_m = re.search(r'<img[^>]+src=\"((?:https?://|/uploads/)[^\"]+)\"', block)
        thumb = thumb_m.group(1) if thumb_m else ''
        if thumb.startswith('/'):
            thumb = _base() + thumb
        is_series = is_series_page or bool(
            re.search(r'text-align:right[^>]*>(?:<[^>]+>)*\s*S\d{1,2}', block[:1000])
        )
        if is_series:
            items.append({
                'title':       name,
                'url':         _S_SEASONS + href,
                'poster':      thumb,
                'mediatype':   'tvshow',
                'is_playable': False,
                'next_func':   'load',
            })
        else:
            items.append({
                'title':       name,
                'url':         href,
                'poster':      thumb,
                'mediatype':   'movie',
                'is_playable': True,
                'next_func':   'get_hosters',
            })
    return items


def _parse_any_search(html, is_series_page=False):
    items = _parse_search_results(html, is_series_page=is_series_page)
    if items:
        return items
    return _parse_entries(html, is_series_page=is_series_page)


def _get_genre_menu():
    html = _get(_base())
    skip = ('erwachsene', 'erotik')
    items = []
    for m in re.finditer(r'<li class=\"links\"><a href=\"(/main/[^\"]+)\"[^>]*>(.*?)</a>', html, re.S | re.I):
        href  = m.group(1)
        name  = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if not name or any(s in href for s in skip):
            continue
        full_url = _base() + href
        items.append({'title': name, 'url': full_url,
                      'next_func': 'load', 'is_playable': False})
    return items


def _js_array(html):
    links = re.findall(r'\.show\(.+?,(\[\[.+?\]\])', html)
    if not links:
        return None
    try:
        return ast.literal_eval(links[0])
    except Exception:
        return None


def _get_thumb(html):
    m = re.search(r'<!--dle_image_begin:([^|>]+)\|', html)
    if not m:
        m = re.search(r'<img[^>]+src=\"(/uploads/[^\"]+)\"', html, re.I)
    thumb = m.group(1) if m else ''
    if thumb.startswith('/'):
        thumb = _base() + thumb
    return thumb


def _get_seasons(show_url):
    html = _get(show_url)
    arr = _js_array(html)
    if not arr:
        return []
    thumb = _get_thumb(html)
    items = []
    for i in range(len(arr)):
        s = i + 1
        items.append({
            'title':       'Staffel %d' % s,
            'url':         _S_EP + show_url + '|' + str(s),
            'poster':      thumb,
            'mediatype':   'season',
            'is_playable': False,
            'next_func':   'load',
        })
    return items


def _get_episodes(encoded):
    show_url, season = encoded.rsplit('|', 1)
    html = _get(show_url)
    arr = _js_array(html)
    if not arr:
        return []
    thumb = _get_thumb(html)
    s_idx = int(season) - 1
    if s_idx >= len(arr):
        return []
    items = []
    for e_idx in range(len(arr[s_idx])):
        ep_num = e_idx + 1
        items.append({
            'title':       'Folge %d' % ep_num,
            'url':         show_url + '|s%s|e%d' % (season, ep_num),
            'poster':      thumb,
            'mediatype':   'episode',
            'is_playable': True,
            'next_func':   'get_hosters',
        })
    return items


def _is_hoster_url(url):
    u = url.lower()
    if any(d in u for d in _SKIP_DOMAINS):
        return False
    path = u.split('?')[0]
    if path.endswith(('.js', '.css', '.png', '.jpg', '.gif', '.svg', '.ico')):
        return False
    if not u.startswith('http'):
        return False
    return True


def _streams_from_page(html, season=0, episode=0):
    links = re.findall(r'\.show\(.+?,(\[\[.+?\]\])', html)
    if not links:
        return []
    quali_labels = re.findall(r'title=\"Stream\.([^\"]+)\"', html)
    s = max(0, int(season or 1) - 1)
    e = max(0, int(episode or 1) - 1)
    result = []
    for i, link_data in enumerate(links):
        try:
            pw = ast.literal_eval(link_data)
            raw_url = pw[s][e].strip()
        except Exception:
            continue
        if not _is_hoster_url(raw_url):
            continue
        hoster = re.sub(r'^www\.', '', (re.findall(r'//([^/]+)/', raw_url) or [SITE_NAME])[0])
        quality = _quality(quali_labels[i]) if i < len(quali_labels) and quali_labels[i] else 'HD'
        result.append((hoster, raw_url, False, quality, 'de'))
    return result


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Neueste', 'url': _S_KINO,   'next_func': 'load', 'is_playable': False},
            {'title': 'Filme',   'url': _S_MOVIES,  'next_func': 'load', 'is_playable': False},
            {'title': 'Serien',  'url': _S_SERIES,  'next_func': 'load', 'is_playable': False},
            {'title': 'Genre',   'url': _S_GENRE,   'next_func': 'load', 'is_playable': False},
        ]
    if url == _S_KINO:    return _parse_entries(_get(_base() + '/stream/'))
    if url == _S_MOVIES:
        _items = _parse_entries(_get(_base() + '/stream/'))
        return [i for i in _items if i.get('mediatype') != 'tvshow']
    if url == _S_SERIES:  return _parse_entries(_get(_base() + '/stream/serie/'), is_series_page=True)
    if url == _S_GENRE:   return _get_genre_menu()
    if url.startswith(_S_SEASONS): return _get_seasons(url[len(_S_SEASONS):])
    if url.startswith(_S_EP):      return _get_episodes(url[len(_S_EP):])
    is_series = '/stream/serie/' in url
    return _parse_entries(_get(url), is_series_page=is_series)


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if url and '|s' in url and '|e' in url:
        page_url, s_part, e_part = url.split('|')
        html = _get(page_url)
        return _streams_from_page(html, int(s_part[1:]), int(e_part[1:]))

    if url and not url.startswith('__'):
        html = _get(url)
        return _streams_from_page(html, int(season or 1), int(episode or 1))

    if not title:
        return []

    years = [str(year), str(int(year or 0) + 1)] if year and not season else ['']
    ct = _cleantitle(title)

    search_url = _base() + '/index.php?do=search&subaction=search&search_start=1&full_search=0&result_from=1&titleonly=3&story=%s' % quote(title)
    html = _get(search_url)

    if not html or ('<div class=\"titlecontrol\">' not in html and '<div class=\"short\">' not in html):
        html = _get(_base() + '?do=search&subaction=search&titleonly=3&story=%s&x=0&y=0&submit=submit' % quote(title))

    if not html or ('<div class=\"titlecontrol\">' not in html and '<div class=\"short\">' not in html):
        html = _get(_base(), post=True, post_data={
            'do': 'search', 'subaction': 'search',
            'story': title, 'titleonly': '3', 'submit': 'submit'
        })

    if not html:
        return []

    entries = _parse_any_search(html, is_series_page=bool(season))

    match_url = None
    for entry in entries:
        etitle = entry.get('title', '')
        eurl   = entry.get('url', '')
        year_m  = re.search(r'\((\d{4})\)', etitle)
        etitle_clean = re.sub(r'\s+(Film|Stream|Serie|Staffel\s*\d+)\s*$', '', etitle, flags=re.I)
        eclean  = _cleantitle(re.sub(r'\(\d{4}\)', '', etitle_clean))
        if ct not in eclean and eclean not in ct:
            continue
        if year and not season and year_m and year_m.group(1) not in years:
            continue
        if season and entry.get('mediatype') != 'tvshow' and not re.search(r'staffel', eclean):
            continue
        match_url = eurl
        break

    if not match_url:
        return []

    for prefix in (_S_SEASONS, _S_EP):
        if match_url.startswith(prefix):
            match_url = match_url[len(prefix):]
    page_url = match_url.split('|')[0]

    html = _get(page_url)
    return _streams_from_page(html, int(season or 1), int(episode or 1))


def search(query='', params=None):
    search_url = _base() + '/index.php?do=search&subaction=search&search_start=1&full_search=0&result_from=1&titleonly=3&story=%s' % quote(query)
    html = _get(search_url)
    if not html or ('<div class=\"titlecontrol\">' not in html and '<div class=\"short\">' not in html):
        html = _get(_base() + '?do=search&subaction=search&titleonly=3&story=%s&x=0&y=0&submit=submit' % quote(query))
    if not html or ('<div class=\"titlecontrol\">' not in html and '<div class=\"short\">' not in html):
        html = _get(_base(), post=True, post_data={
            'do': 'search', 'subaction': 'search', 'story': query,
            'titleonly': '3', 'submit': 'submit'
        })
    return _parse_any_search(html)


def _extract_plot(html):
    m = re.search(r'<!--dle_image_end-->(.*?)(?=<hr|<center|<div class=\"footercontrol\"|<div class=\"footerbar\")', html, re.S | re.I)
    if not m:
        m = re.search(r'<div[^>]*class=\"[^\"]*content_text[^\"]*\"[^>]*>(.*?)(?=<div class=\"footercontrol\"|<div class=\"footerbar\")', html, re.S | re.I)
        if not m:
            return ''
        raw = m.group(1)
        raw = re.sub(r'<div[^>]*class=\"[^\"]*rating-full[^\"]*\"[^>]*>[\s\S]*?(?:</div>\s*){3}', '', raw, flags=re.I)
    else:
        raw = m.group(1)
    raw = re.sub(r'<!--.*?-->', '', raw, flags=re.S)
    raw = re.sub(r'<[^>]+>', '', raw)
    return re.sub(r'\s+', ' ', raw).strip()


def get_details(url='', params=None):
    if not url:
        return {}
    if url.startswith(_S_SEASONS):
        url = url[len(_S_SEASONS):]
    elif url.startswith('__'):
        return {}
    html = _get(url.split('|')[0])
    plot = _extract_plot(html)
    poster = ''
    pm = re.search(r'<!--dle_image_begin:([^|>]+)\|', html)
    if not pm:
        pm = re.search(r'<img[^>]+src=\"([^\"]+)\"[^>]*class=\"[^\"]*poster[^\"]*\"', html, re.I)
    if not pm:
        pm = re.search(r'<img[^>]+src=\"(/uploads/[^\"]+)\"', html, re.I)
    if pm:
        poster = pm.group(1)
        if poster.startswith('/'):
            poster = _base() + poster
    result = {}
    if plot:   result['plot']   = plot
    if poster: result['poster'] = poster
    return result
