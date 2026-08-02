# -*- coding: utf-8 -*-
import re
from urllib.parse import quote, urlparse
from resources.lib import multiquest, log

SITE_ID       = 'topstreamfilm'
SITE_NAME     = 'TopStreamFilm'
SITE_DOMAIN   = 'www.topstreamfilm.live'
TYPE          = 'both'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

_S_BROWSE  = '__tsf_browse__:'
_S_SEASONS = '__tsf_seasons__:'
_S_EPS     = '__tsf_eps__:'


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


def _unescape(s):
    if not s:
        return s
    try:
        from html import unescape
        return unescape(s)
    except Exception:
        return s


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _quality(text):
    t = (text or '').upper()
    if '2160' in t or '4K' in t: return '4K'
    if '1080' in t: return '1080p'
    if '720' in t: return '720p'
    if '480' in t: return '480p'
    return 'HD'


def _abs_url(u):
    if not u: return ''
    if u.startswith('http'): return u
    if u.startswith('//'): return 'https:' + u
    if u.startswith('/'): return _base() + u
    return _base() + '/' + u


def _parse_entries(html):
    items = []
    pattern = (
        r'TPostMv[^\"]*\"[^>]*>.*?'
        r'href=\"([^\"]+).*?'
        r'data-src=\"([^\"]+).*?'
        r'(?:class=\"Title\"|Title\">)([^<]+)(.*?)</li>'
    )
    for sUrl, sThumbnail, sName, sDummy in re.findall(pattern, html, re.S):
        sName = _unescape(sName.strip())
        sName = re.sub(r'\s*[-\u2013\u2014]\s*Der Film.*', '', sName).strip()
        if not sName:
            continue

        thumb = _abs_url(sThumbnail)

        year_m = re.search(r'Year\">([\d]{4})<', sDummy)
        year = year_m.group(1) if year_m else ''

        full_sUrl = _abs_url(sUrl)
        is_series = '/serien/' in full_sUrl or '/serie/' in full_sUrl
        if not is_series:
            dur_m = re.search(r'time\">([\d]+)', sDummy)
            try:
                dur = int(dur_m.group(1)) if dur_m else 999
                is_series = (dur <= 70)
            except Exception:
                is_series = False
        if 'South Park: The End Of Obesity' in sName:
            is_series = False

        plot = ''
        for pat in [
            r'Description\"><p>([^<]+)',
            r'sbox[^\"]*\"[^>]*>([^<]{10,})',
            r'<p[^>]*>([^<]{10,})</p>',
        ]:
            pm = re.search(pat, sDummy, re.I)
            if pm:
                plot = _unescape(pm.group(1).strip())
                break

        items.append({
            'title':       sName,
            'url':         _S_SEASONS + full_sUrl if is_series else full_sUrl,
            'poster':      thumb,
            'year':        year,
            'plot':        plot,
            'mediatype':   'tvshow' if is_series else 'movie',
            'is_playable': not is_series,
            'next_func':   'load' if is_series else 'get_hosters',
        })

    m_next = re.search(r'href=\"([^\"]+)\">Next', html)
    if not m_next:
        m_next = re.search(r'class=\"[^\"]*next[^\"]*\"[^>]*href=\"([^\"]+)\"', html, re.I)
    if m_next:
        items.append({
            'title': '[B]>>> Weiter[/B]',
            'url': _abs_url(m_next.group(1)),
            'next_func': 'load',
            'is_playable': False,
        })
    return items


def _imdb_from_page(url):
    html = _get(url, _base())
    for pat in (
        r'meinecloud\.click/(?:ddl|movie|serial)/(tt\d+)',
        r'imdb\.com/title/(tt\d+)',
        r'id_imdb=(tt\d+)',
        r"var\s+imdb\s*=\s*['\"]+(tt\d+)['\"]",
    ):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1)
    return ''


def _meinecloud_serial_html(imdb):
    imdb_num = re.sub(r'[^0-9]', '', str(imdb))
    url1 = 'https://meinecloud.click/serial/%s' % imdb_num
    url2 = 'https://meinecloud.click/serial/%s' % imdb
    headers = {'User-Agent': _UA}
    try:
        r = multiquest.get(url1, headers=headers, timeout=12)
        r.raise_for_status()
        if r.text:
            return r.text
    except Exception:
        pass
    try:
        r = multiquest.get(url2, headers=headers, timeout=12)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _parse_serial_html(html):
    sid_to_snum = {}
    for sid, label in re.findall(r'data-season=\"(\d+)\"[^>]*>\s*(S\d+)\s*<', html):
        m = re.match(r'S(\d+)', label.strip())
        if m:
            sid_to_snum[sid] = int(m.group(1))
    episodes = {}
    blocks = re.split(r'(?=<div[^>]*class=\"[^\"]*_season-eps[^\"]*\"[^>]*data-season=\")', html)
    for block in blocks:
        sid_m = re.match(r'<div[^>]*data-season=\"(\d+)\">', block)
        if not sid_m:
            continue
        sid = sid_m.group(1)
        snum = sid_to_snum.get(sid)
        if snum is None:
            continue
        links  = re.findall(r'data-link=\"([^\"]+)\"', block)
        labels = re.findall(r'data-label=\"([^\"]+)\"', block)
        ep_nums = re.findall(r'<div[^>]*class=\"[^\"]*_ep-n[^\"]*\">(\d+)</div>', block)
        for i, (link_raw, label) in enumerate(zip(links, labels)):
            ep_num = int(ep_nums[i]) if i < len(ep_nums) else i + 1
            link = link_raw.strip()
            if link.startswith('//'):
                link = 'https:' + link
            episodes.setdefault(snum, []).append((ep_num, label.strip(), link))
    return sid_to_snum, episodes


def _get_seasons(show_url):
    imdb_m = re.search(r'/(tt\d+)', show_url)
    imdb = imdb_m.group(1) if imdb_m else _imdb_from_page(show_url)
    if not imdb:
        return []
    html = _meinecloud_serial_html(imdb)
    if not html:
        return []
    show_html = _get(show_url, _base())

    thumb = ''
    pm = re.search(r'<img[^>]+(?:data-src|src)=\"([^\"]+)\"[^>]*class=\"[^\"]*poster[^\"]*\"', show_html, re.I)
    if not pm:
        pm = re.search(r'<div[^>]*class=\"[^\"]*poster[^\"]*\"[^>]*>.*?<img[^>]+(?:data-src|src)=\"([^\"]+)\"', show_html, re.S | re.I)
    if pm:
        thumb = _abs_url(pm.group(1))

    plot = ''
    dm = re.search(r'<div[^>]*class=\"[^\"]*description[^\"]*\"[^>]*>(.*?)</div>', show_html, re.S | re.I)
    if not dm:
        dm = re.search(r'Description\"><p>([^<]+)', show_html)
    if dm:
        plot = re.sub(r'<[^>]+>', '', dm.group(1)).strip()

    _, episodes = _parse_serial_html(html)
    seasons = sorted(episodes.keys())
    if not seasons:
        return []

    items = []
    for s in seasons:
        item = {
            'title':       'Staffel %d' % s,
            'url':         _S_EPS + show_url + '|' + imdb + '|%d' % s,
            'poster':      thumb,
            'mediatype':   'season',
            'next_func':   'load',
            'is_playable': False,
        }
        if plot:
            item['plot'] = plot
        items.append(item)
    return items


def _get_episodes(encoded):
    show_url, imdb, season_s = encoded.rsplit('|', 2)
    season = int(season_s)
    html = _meinecloud_serial_html(imdb)
    if not html:
        return []
    show_html = _get(show_url, _base())

    thumb = ''
    pm = re.search(r'<img[^>]+(?:data-src|src)=\"([^\"]+)\"[^>]*class=\"[^\"]*poster[^\"]*\"', show_html, re.I)
    if not pm:
        pm = re.search(r'<div[^>]*class=\"[^\"]*poster[^\"]*\"[^>]*>.*?<img[^>]+(?:data-src|src)=\"([^\"]+)\"', show_html, re.S | re.I)
    if pm:
        thumb = _abs_url(pm.group(1))

    plot = ''
    dm = re.search(r'<div[^>]*class=\"[^\"]*description[^\"]*\"[^>]*>(.*?)</div>', show_html, re.S | re.I)
    if not dm:
        dm = re.search(r'Description\"><p>([^<]+)', show_html)
    if dm:
        plot = re.sub(r'<[^>]+>', '', dm.group(1)).strip()

    _, episodes = _parse_serial_html(html)
    items = []
    for ep_num, ep_title, link in sorted(episodes.get(season, []), key=lambda x: x[0]):
        item = {
            'title':       ep_title or 'S%02dE%02d' % (season, ep_num),
            'url':         link,
            'poster':      thumb,
            'mediatype':   'episode',
            'next_func':   'get_hosters',
            'is_playable': True,
            'season':      season,
            'episode':     ep_num,
        }
        if plot:
            item['plot'] = plot
        items.append(item)
    return items


def _extract_hosters_film(page_url):
    html = _get(page_url, _base())
    result = []
    seen = set()

    q_m = re.search(r'(4K|2160p?|1080p?|720p?|480p?|SD|CAM|TS)\b', html, re.I)
    quality = _quality(q_m.group(1)) if q_m else 'HD'

    iframe_m = re.search(r'<iframe[^>]+src=\"([^\"]+)\"', html, re.I)
    if iframe_m:
        iframe_url = _abs_url(iframe_m.group(1))
        iframe_html = _get(iframe_url, page_url)
        for link in re.findall(r'data-link=\"([^\"]+)\"', iframe_html):
            full = _abs_url(link)
            if not full or 'youtube' in full.lower(): continue
            if full in seen: continue
            seen.add(full)
            hostname = urlparse(full).hostname or ''
            hoster = re.sub(r'^www\.', '', hostname).split('.')[0].capitalize()
            result.append((hoster, full, quality))

    if not result:
        for link in re.findall(r'data-link=\"([^\"]+)\"', html):
            full = _abs_url(link)
            if not full or 'youtube' in full.lower(): continue
            if full in seen: continue
            seen.add(full)
            hostname = urlparse(full).hostname or ''
            hoster = re.sub(r'^www\.', '', hostname).split('.')[0].capitalize()
            result.append((hoster, full, quality))

    return result


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if url and not url.startswith('__') and ('dr0pstream.com' in url or 'dropcdn' in url or 'meinecloud' in url):
        hostname = urlparse(url).hostname or ''
        hoster = re.sub(r'^www\.', '', hostname).split('.')[0].capitalize()
        return [(hoster, url, False, 'HD', '')]

    if url and not url.startswith('__'):
        raw = _extract_hosters_film(url)
        return [(name, hurl, False, qual, '') for name, hurl, qual in raw]

    page_url = _find_page_url(title, year)
    if not page_url:
        return []

    season_i  = int(season  or 0)
    episode_i = int(episode or 0)

    if season_i and episode_i:
        imdb_id = _imdb_from_page(page_url)
        if imdb_id:
            html = _meinecloud_serial_html(imdb_id)
            _, eps = _parse_serial_html(html)
            for ep_num, ep_title, link in eps.get(season_i, []):
                if ep_num == episode_i:
                    hostname = urlparse(link).hostname or ''
                    hoster = re.sub(r'^www\.', '', hostname).split('.')[0].capitalize()
                    return [(hoster, link, False, 'HD', '')]
        raw = _extract_hosters_film(page_url)
    else:
        raw = _extract_hosters_film(page_url)

    return [(name, hurl, False, qual, '') for name, hurl, qual in raw]


def _find_page_url(title, year=''):
    clean = _cleantitle(title)
    html = _get(_base() + '/?story=%s&do=search&subaction=search' % quote(title), _base())
    pattern = (
        r'TPostMv[^\"]*\"[^>]*>.*?'
        r'href=\"([^\"]+).*?'
        r'Title\">([^<]+)'
    )
    for href, name in re.findall(pattern, html, re.S):
        if _cleantitle(name) == clean or clean in _cleantitle(name):
            return _abs_url(href)
    return ''


def load(url='', params=None):
    if not url:
        b = _base()
        return [
            {'title': 'Neues',          'url': b + '/filme-online-sehen/', 'next_func': 'load', 'is_playable': False},
            {'title': 'Beliebte Filme', 'url': b + '/beliebte-filme-online/', 'next_func': 'load', 'is_playable': False},
            {'title': 'Kinofilme',      'url': b + '/kinofilme/',          'next_func': 'load', 'is_playable': False},
            {'title': 'Serien',         'url': b + '/serien/',             'next_func': 'load', 'is_playable': False},
            {'title': 'Genre',          'url': _S_BROWSE + 'genres',      'next_func': 'load', 'is_playable': False},
            {'title': 'Jahr',           'url': _S_BROWSE + 'years',       'next_func': 'load', 'is_playable': False},
            {'title': 'Land',           'url': _S_BROWSE + 'countries',   'next_func': 'load', 'is_playable': False},
        ]
    if url.startswith(_S_BROWSE):
        return _get_nav_menu(url[len(_S_BROWSE):])
    if url.startswith(_S_SEASONS):
        return _get_seasons(url[len(_S_SEASONS):])
    if url.startswith(_S_EPS):
        return _get_episodes(url[len(_S_EPS):])
    return _parse_entries(_get(url, _base()))


def _get_nav_menu(key):
    html = _get(_base() + '/', _base())
    value_map = {
        'genres':    'KATEGORIEN',
        'years':     'YAHRE',
        'countries': 'LAND',
    }
    value = value_map.get(key, key.upper())
    block_m = re.search(r'>%s</a>(.*?)</ul>' % re.escape(value), html, re.S)
    if not block_m:
        return []
    block = block_m.group(1)
    items = []
    if key == 'years':
        for href, name in re.findall(r"href='([^']+)'>(\d{4})</a>", block):
            items.append({
                'title': name, 'url': _abs_url(href),
                'next_func': 'load', 'is_playable': False,
            })
    else:
        for href, name in re.findall(r'href=\"([^\"]+)[^>]*>([^<]+)', block):
            name = name.strip()
            if not name: continue
            items.append({
                'title': name, 'url': _abs_url(href),
                'next_func': 'load', 'is_playable': False,
            })
    return items


def search(query='', params=None):
    html = _get(_base() + '/?story=%s&do=search&subaction=search' % quote(query), _base())
    return _parse_entries(html)
