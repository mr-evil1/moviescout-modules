# -*- coding: utf-8 -*-
import re
import json
from urllib.parse import quote
from resources.lib import multiquest, log

SITE_ID       = 'serienstream'
SITE_NAME     = 'SerienStream'
SITE_DOMAIN   = 'serienstream.to'
TYPE          = 'series'
GLOBAL_SEARCH = True

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
_LANG_MAP = {'1': 'DE', '2': 'EN', '3': 'DE+SUB', '4': 'EN+SUB'}

_S_SEASONS  = '__ss_seasons__:'
_S_EPS      = '__ss_eps__:'
_S_GENRES   = '__ss_genres__'
_S_SAMML    = '__ss_samml__'
_S_KALENDER = '__ss_kalender__'
_S_AZ       = '__ss_az__'
_S_NEUESTE  = '__ss_neueste__'
_S_TREND    = '__ss_trend__'
_S_WEEKLY   = '__ss_weekly__'
_S_TOPRATED = '__ss_toprated__'

_HOME_SECTION_URLS = {
    1: ['/gerade-im-trend', '/trending-serien'],
    2: ['/woechentliche-favoriten', '/weekly-favorites'],
    3: ['/meistbewertete-serien', '/top-serien'],
}


def _base():
    return 'https://' + SITE_DOMAIN


def _get(url, referer=None):
    headers = {'User-Agent': _UA}
    if referer:
        headers['Referer'] = referer
    try:
        r = multiquest.get(url, headers=headers, timeout=12)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _follow_redirect(url, referer=''):
    try:
        headers = {'User-Agent': _UA, 'Referer': referer or _base() + '/'}
        r = multiquest.get(url, headers=headers, timeout=10, allow_redirects=True)
        return r.url if r.url != url else url
    except Exception:
        log.error()
        return url


def _extract_hosters_from_page(ep_url):
    html = _get(ep_url, _base())
    result = []
    pattern = (
        r'data-link-id=["\'](\d+)["\'].*?'
        r'data-play-url=["\']([^"\']+)["\'].*?'
        r'data-provider-name=["\']([^"\']+)["\'].*?'
        r'data-language-label=["\']([^"\']+)["\'].*?'
        r'data-language-id=["\'](\d+)["\']'
    )
    for _lid, play_url, provider, lang_label, lang_id in re.findall(pattern, html, re.S):
        redirect_url = _base() + play_url if play_url.startswith('/') else play_url
        resolved = _follow_redirect(redirect_url, ep_url)
        lang = _LANG_MAP.get(lang_id, lang_label)
        label = '%s | %s' % (lang, provider.strip())
        audio = 'de' if lang_id == '1' else ('sub' if lang_id in ('3', '4') else '')
        result.append((label, resolved, False, 'HD', audio))
    return result


def _find_show_url(title):
    clean = _cleantitle(title)
    html = _get(_base() + '/serien')
    best = ('', 0)
    for href, name in re.findall(
        r'<li[^>]*class=["\'][^"\']*series-item[^"\']*["\'][^>]*>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>',
        html, re.S
    ):
        c = _cleantitle(name)
        if c == clean:
            return _base() + href if href.startswith('/') else href
        if clean in c or c in clean:
            score = max(len(clean), len(c))
            if score > best[1]:
                best = (_base() + href if href.startswith('/') else href, score)
    return best[0]


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    season  = int(season  or 0)
    episode = int(episode or 0)
    if url and '/episode-' in url:
        return _extract_hosters_from_page(url)
    if url and '/staffel-' in url:
        ep_url = url.rstrip('/') + '/episode-%d' % episode if episode else url
        return _extract_hosters_from_page(ep_url)
    if url:
        base_url = url
    else:
        base_url = _find_show_url(title)
    if not base_url:
        return []
    if season and episode:
        ep_url = base_url.rstrip('/') + '/staffel-%d/episode-%d' % (season, episode)
    else:
        ep_url = base_url
    return _extract_hosters_from_page(ep_url)


def _get_seasons(show_url):
    html = _get(show_url, _base())
    og_img = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html)
    thumb = og_img.group(1) if og_img else ''
    desc_m = (
        re.search(r'<span[^>]+class=["\']description-text["\'][^>]*>(.*?)</span>', html, re.S | re.I) or
        re.search(r'<p[^>]*itemprop=["\']description["\'][^>]*>(.*?)</p>', html, re.S | re.I) or
        re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    )
    plot = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip() if desc_m else ''
    nav_m = re.search(r'id=["\']season-nav["\'].*?</ul>', html, re.S)
    items = []
    if nav_m:
        for href, s_num, label in re.findall(
            r'href=["\']([^"\']+/staffel-(\d+))["\'][^>]*>\s*([^<]+?)\s*</a>',
            nav_m.group(0), re.S
        ):
            full_url = href if href.startswith('http') else _base() + href
            item = {
                'title':       label.strip() if label.strip() and not label.strip().isdigit() else ('Staffel %s' % s_num),
                'url':         _S_EPS + full_url,
                'poster':      thumb,
                'mediatype':   'season',
                'is_playable': False,
                'next_func':   'load',
            }
            if plot:
                item['plot'] = plot
            items.append(item)
    return items


def _get_episodes(staffel_url):
    html = _get(staffel_url, _base())
    og_img = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html)
    thumb = og_img.group(1) if og_img else ''
    nav_m = re.search(r'id=["\']episode-nav["\'].*?</ul>', html, re.S)
    items = []
    if nav_m:
        for href, ep_num in re.findall(
            r'href=["\']([^"\']+/episode-(\d+))["\']',
            nav_m.group(0)
        ):
            ep_url = href if href.startswith('http') else _base() + href
            items.append({
                'title':       'Episode %s' % ep_num,
                'url':         ep_url,
                'poster':      thumb,
                'mediatype':   'episode',
                'is_playable': True,
                'next_func':   'get_hosters',
            })
    return items


def _parse_show_cards(html):
    try:
        from html import unescape as _unescape
    except ImportError:
        def _unescape(s): return s
    items = []
    for col in re.findall(r'<div class="col-6[^"]*">(.*?)</div>\s*</div>', html, re.S):
        href_m = re.search(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*class=["\'][^"\']*show-card', col, re.S)
        if not href_m:
            continue
        href = href_m.group(1)
        name_m = re.search(r'<h6[^>]+title=["\']([^"\']+)["\']', col)
        if not name_m:
            name_m = re.search(r'<img[^>]+alt=["\']([^"\']+)["\']', col, re.S)
            if not name_m:
                continue
        name = _unescape(name_m.group(1).strip())
        thumb = ''
        img_m = re.search(r'<img([^>]+)>', col, re.S)
        if img_m:
            attrs = img_m.group(1)
            # tile-md in data-src is the lazy-loaded jpg (preferred for Kodi)
            ds = (
                re.search(r'\bdata-src=["\']([^"\']+tile-md[^"\']+format=jpg[^"\']*)["\']', attrs) or
                re.search(r'\bdata-src=["\']([^"\']+format=jpg[^"\']*)["\']', attrs) or
                re.search(r'\bdata-src=["\']([^"\']+)["\']', attrs)
            )
            if ds and not ds.group(1).startswith('data:'):
                thumb = ds.group(1)
            else:
                s = re.search(r'\bsrc=["\']([^"\']+)["\']', attrs)
                if s and not s.group(1).startswith('data:'):
                    thumb = s.group(1)
        show_href = re.sub(r'/staffel-\d+$', '', href.rstrip('/'))
        full_url  = show_href if show_href.startswith('http') else _base() + show_href
        full_thumb = (thumb if thumb.startswith('http') else _base() + thumb) if thumb else ''
        items.append({
            'title':       name,
            'url':         _S_SEASONS + full_url,
            'poster':      full_thumb,
            'mediatype':   'tvshow',
            'is_playable': False,
            'next_func':   'load',
        })
    next_m = re.search(r'href=["\']([^"\']+\?page=\d+)["\'][^>]*>[^<]*Weiter[^<]*</a>', html, re.I)
    if next_m:
        nxt = next_m.group(1)
        full_next = nxt if nxt.startswith('http') else _base() + nxt
        items.append({'title': '[B]>>> Weiter[/B]', 'url': full_next, 'next_func': 'load', 'is_playable': False})
    return items


def _parse_series_list(html):
    items = []
    for href, name in re.findall(
        r'<li[^>]*class=["\'][^"\']*series-item[^"\']*["\'][^>]*>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>',
        html, re.S
    ):
        full_url = href if href.startswith('http') else _base() + href
        items.append({
            'title':       name.strip(),
            'url':         _S_SEASONS + full_url,
            'mediatype':   'tvshow',
            'is_playable': False,
            'next_func':   'load',
        })
    return items


def _get_az_menu():
    items = []
    for letter in list('ABCDEFGHIJKLMNOPQRSTUVWXYZ') + ['0']:
        display = '0-9' if letter == '0' else letter
        items.append({
            'title':       display,
            'url':         _base() + '/katalog/' + letter,
            'is_playable': False,
            'next_func':   'load',
        })
    return items


def _get_genres():
    html = _get(_base() + '/', _base())
    items = []
    for href, name in re.findall(
        r'href=["\']([^"\']*(?:/genre/)[^"\'?#]+)["\'][^>]*>\s*([^<]{2,50})\s*</a>',
        html, re.S
    ):
        name = name.strip()
        if not name:
            continue
        full_url = href if href.startswith('http') else _base() + href
        items.append({'title': name, 'url': full_url, 'next_func': 'load', 'is_playable': False})
    return items


def _get_sammlungen():
    html = _get(_base() + '/sammlungen', _base())
    items = []
    for href, name in re.findall(
        r'href=["\']([^"\']*sammlung[^"\']+)["\'][^>]*title=["\']([^"\']+)["\']',
        html, re.S
    ):
        if 'sammlungen' in href:
            continue
        full_url = href if href.startswith('http') else _base() + href
        items.append({
            'title':       name.strip(),
            'url':         full_url,
            'is_playable': False,
            'next_func':   'load',
        })
    return items


def _get_kalender():
    text = _get(_base() + '/api/calendar', _base())
    try:
        data = json.loads(text)
    except Exception:
        return []
    items = []
    for date_str, eps in sorted(data.items()):
        for ep in eps:
            if not ep.get('released'):
                continue
            ep_url = ep.get('url', '')
            if not ep_url:
                continue
            full_url  = _base() + ep_url
            lang      = _LANG_MAP.get(str(ep.get('language_id', '')), ep.get('language', ''))
            title     = '%s S%02dE%02d [%s]' % (
                ep.get('title', ''), ep.get('season', 0), ep.get('episode', 0), lang
            )
            cover = ep.get('cover_url', '')
            thumb = (_base() + cover) if cover else ''
            items.append({
                'title':       title,
                'url':         full_url,
                'poster':      thumb,
                'mediatype':   'episode',
                'is_playable': True,
                'next_func':   'get_hosters',
            })
    return items


def _get_neueste_episoden():
    try:
        from html import unescape as _unescape
    except ImportError:
        def _unescape(s): return s
    html = _get(_base() + '/', _base())
    items = []
    day_label = ''
    for block in re.split(r'<div class="episodes-day-group">', html)[1:]:
        day_m = re.search(r'<div class="episodes-day-heading">([^<]+)</div>', block)
        day_label = day_m.group(1).strip() if day_m else day_label
        for href, time_str, title, season, episode, flag in re.findall(
            r'<a class="latest-episode-row[^"]*" href="([^"]+)"[^>]*>.*?'
            r'<span class="ep-time">([^<]+)</span>.*?'
            r'<span class="ep-title" title="([^"]+)">.*?'
            r'<span class="ep-season">([^<]+)</span>.*?'
            r'<span class="ep-episode">([^<]+)</span>.*?'
            r'icon-flag-(\w+)',
            block, re.S
        ):
            ep_url = href if href.startswith('http') else _base() + href
            lang = 'DE' if flag == 'german' else ('EN' if flag == 'english' else flag.upper())
            label = '[%s] %s %s %s (%s)' % (lang, _unescape(title), season, episode, time_str)
            items.append({
                'title':       label,
                'url':         ep_url,
                'mediatype':   'episode',
                'is_playable': True,
                'next_func':   'get_hosters',
            })
    return items


def _parse_section_html(html, section_id):
    try:
        from html import unescape as _unescape
    except ImportError:
        def _unescape(s): return s
    pat = 'id="section-%d"' % section_id
    idx = html.find(pat)
    if idx == -1:
        content = html
    else:
        chunk = html[idx:]
        next_m = re.search(r'id="section-\d+"', chunk[len(pat):])
        content = chunk[:next_m.start() + len(pat)] if next_m else chunk

    seen = set()
    items = []
    # Parse each card-mini block as an atomic unit to avoid cross-card mismatches
    card_blocks = re.findall(r'<div[^>]+class="[^"]*card-mini[^"]*"[^>]*>(.*?)</div>\s*</div>', content, re.S)
    if not card_blocks:
        # Fallback: split by col-6 divs
        card_blocks = re.findall(r'<div[^>]+class="col-6[^"]*"[^>]*>(.*?)</div>\s*</div>', content, re.S)
    for card in card_blocks:
        href_m = re.search(r'href=["\'](/serie/[^"\'?#\s>]+)', card)
        if not href_m:
            continue
        href = re.sub(r'/staffel-\d+(/episode-\d+)?$', '', href_m.group(1).rstrip('/'))
        if href in seen:
            continue
        seen.add(href)
        title_m = (
            re.search(r'<h\d[^>]+title=["\']([^"\']{2,80})["\']', card) or
            re.search(r'<img[^>]+alt=["\']([^"\']{2,80})["\']', card) or
            re.search(r'<h\d[^>]*>\s*<span>\s*([^<]{2,80})\s*</span>', card, re.I)
        )
        title = _unescape(title_m.group(1).strip()) if title_m else ''
        if not title or 'backdrop' in title.lower():
            title = href.split('/')[-1].replace('-', ' ').title()
        img_m = (
            re.search(r'data-src=["\']([^"\']+tile-md[^"\']+format=jpg[^"\']*)["\']', card) or
            re.search(r'data-src=["\']([^"\']+format=jpg[^"\']*)["\']', card) or
            re.search(r'data-src=["\']([^"\']+/media/images/[^"\']+)["\']', card) or
            re.search(r'src=["\']([^"\']+tile-md[^"\']+format=jpg[^"\']*)["\']', card) or
            re.search(r'src=["\']([^"\']+/media/images/backdrop/[^"\']+format=jpg[^"\']*)["\']', card)
        )
        thumb = img_m.group(1) if img_m and not img_m.group(1).startswith('data:') else ''
        if thumb and not thumb.startswith('http'):
            thumb = _base() + thumb
        items.append({
            'title':       title,
            'url':         _S_SEASONS + _base() + href,
            'poster':      thumb,
            'mediatype':   'tvshow',
            'is_playable': False,
            'next_func':   'load',
        })
    return items


def _get_home_show_section(section_id):
    # Sections 1-3 are tab-panes on the homepage, loaded server-side
    html = _get(_base() + '/', _base())
    if html:
        items = _parse_section_html(html, section_id)
        if items:
            return items
    # Fallback: try dedicated URLs
    for path in _HOME_SECTION_URLS.get(section_id, []):
        html = _get(_base() + path, _base())
        if html:
            items = _parse_show_cards(html)
            if items:
                return items
            items = _parse_section_html(html, section_id)
            if items:
                return items
    return []


def get_details(url='', params=None):
    real_url = url
    if real_url.startswith(_S_SEASONS):
        real_url = real_url[len(_S_SEASONS):]
    if not real_url or not real_url.startswith('http'):
        return {}
    html = _get(real_url, _base())
    if not html:
        return {}
    result = {}
    og_img = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html)
    if og_img:
        result['poster'] = og_img.group(1)
    desc_m = (
        re.search(r'<span[^>]+class=["\']description-text["\'][^>]*>(.*?)</span>', html, re.S | re.I) or
        re.search(r'<p[^>]*itemprop=["\']description["\'][^>]*>(.*?)</p>', html, re.S | re.I) or
        re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    )
    if desc_m:
        result['plot'] = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip()
    return result


def load(url='', params=None):
    if not url:
        return [
            {'title': 'Neueste Episoden',      'url': _S_NEUESTE,                       'next_func': 'load', 'is_playable': False},
            {'title': 'Gerade im Trend',       'url': _S_TREND,                         'next_func': 'load', 'is_playable': False},
            {'title': 'Wöchentliche Favoriten','url': _S_WEEKLY,                        'next_func': 'load', 'is_playable': False},
            {'title': 'Meistbewertete Serien', 'url': _S_TOPRATED,                      'next_func': 'load', 'is_playable': False},
            {'title': 'Beliebt',               'url': _base() + '/beliebte-serien',     'next_func': 'load', 'is_playable': False},
            {'title': 'Alle Serien',           'url': _base() + '/serien',              'next_func': 'load', 'is_playable': False},
            {'title': 'A-Z',                   'url': _S_AZ,                            'next_func': 'load', 'is_playable': False},
            {'title': 'Genre',                 'url': _S_GENRES,                        'next_func': 'load', 'is_playable': False},
            {'title': 'Sammlungen',            'url': _S_SAMML,                         'next_func': 'load', 'is_playable': False},
            {'title': 'Kalender',              'url': _S_KALENDER,                      'next_func': 'load', 'is_playable': False},
        ]
    if url == _S_NEUESTE:          return _get_neueste_episoden()
    if url == _S_TREND:            return _get_home_show_section(1)
    if url == _S_WEEKLY:           return _get_home_show_section(2)
    if url == _S_TOPRATED:         return _get_home_show_section(3)
    if url == _S_AZ:               return _get_az_menu()
    if url == _S_GENRES:           return _get_genres()
    if url == _S_SAMML:            return _get_sammlungen()
    if url == _S_KALENDER:         return _get_kalender()
    if url.startswith(_S_SEASONS): return _get_seasons(url[len(_S_SEASONS):])
    if url.startswith(_S_EPS):     return _get_episodes(url[len(_S_EPS):])
    html = _get(url, _base())
    if url.split('?')[0].rstrip('/') == _base() + '/serien':
        return _parse_series_list(html)
    return _parse_show_cards(html)


def search(query='', params=None):
    html = _get(_base() + '/serien')
    clean = _cleantitle(query)
    items = []
    for m in re.finditer(
        r'<li[^>]*class=["\'][^"\']*series-item[^"\']*["\'][^>]*data-search=["\']([^"\']+)["\'][^>]*>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>',
        html, re.S
    ):
        search_str, href, name = m.group(1), m.group(2), m.group(3)
        if clean not in _cleantitle(search_str):
            continue
        full_url = href if href.startswith('http') else _base() + href
        items.append({
            'title':       name.strip(),
            'url':         _S_SEASONS + full_url,
            'mediatype':   'tvshow',
            'is_playable': False,
            'next_func':   'load',
        })
    return items
