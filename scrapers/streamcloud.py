import re
import json
from html import unescape
from urllib.parse import quote, urlparse
from resources.lib import multiquest, log

SITE_ID       = 'streamcloud'
SITE_NAME     = 'Streamcloud'
SITE_DOMAIN   = 'streamcloud.date'
TYPE          = 'both'
GLOBAL_SEARCH = True

UA = 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36'

GENRES = [
    ('abenteuer', 'Abenteuer'), ('action', 'Action'), ('action-adventure', 'Action & Adventure'),
    ('animation', 'Animation'), ('dokumentarfilm', 'Dokumentarfilm'), ('drama', 'Drama'),
    ('familie', 'Familie'), ('fantasy', 'Fantasy'), ('historie', 'Historie'), ('horror', 'Horror'),
    ('kids', 'Kids'), ('komoedie', 'Komödie'), ('kriegsfilm', 'Kriegsfilm'), ('krimi', 'Krimi'),
    ('liebesfilm', 'Liebesfilm'), ('musik', 'Musik'), ('mystery', 'Mystery'), ('reality', 'Reality'),
    ('sci-fi-fantasy', 'Sci-Fi & Fantasy'), ('science-fiction', 'Science Fiction'), ('soap', 'Soap'),
    ('talk', 'Talk'), ('thriller', 'Thriller'), ('tv-film', 'TV-Film'),
    ('war-politics', 'War & Politics'), ('western', 'Western'),
]

SORTS = [
    ('beliebt', 'Beliebteste'),
    ('zuletzt', 'Zuletzt hinzugefügt'),
    ('neu', 'Neueste Veröffentlichungen'),
    ('bewertung', 'Beste Bewertung'),
    ('jahr', 'Jahr, neueste zuerst'),
    ('titel', 'Titel A–Z'),
]

TYPES = [
    ('', 'Filme & Serien'),
    ('movie', 'Nur Filme'),
    ('tv', 'Nur Serien'),
]

SKIP_HOSTS = (
    'youtube.com', 'youtu.be', 'google.com', 'gstatic.com', 'googletagmanager.com',
    'google-analytics.com', 'facebook.com', 'twitter.com', 't.me', 'fonts.googleapis.com',
    'schema.org', 'w3.org', 'imdb.com', 'themoviedb.org', 'tmdb.org', 'streamcloud.date', 'img.streamcloud.date',
    'yadro.ru', 'histats.com', 'aliexpress.com', 'cloudflare.com', 'jsdelivr.net', 'cdnjs.cloudflare.com',
)

ASSET_RE = re.compile(r'\.(jpe?g|png|gif|webp|svg|ico|css|js|woff2?|ttf|vtt|srt|json|xml)(\?|$)', re.I)
EMBED_RE = re.compile(r'/(e|embed|embed-[^/]+|v|d|f|watch|player|play|video|videos|stream|file)/|/embed', re.I)

DIRECT_ONLY_HOSTS = ('meinecloud.click', 'dl.tmdb.club', 'devideosrc.co')

MEDIA_RE = re.compile(r'\.(mp4|m3u8)(\?|$|\|)', re.I)


def _base():
    return 'https://' + SITE_DOMAIN


def _headers(referer=None):
    headers = {'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8', 'User-Agent': UA}
    if referer:
        headers['Referer'] = referer
    return headers


LAST_UA = [UA]


def _get(url, referer=None):
    try:
        r = multiquest.get(url, headers=_headers(referer), timeout=15, use_cf=True)
        r.raise_for_status()
        try:
            LAST_UA[0] = r.request.headers.get('User-Agent') or UA
        except Exception:
            LAST_UA[0] = UA
        return r.text
    except Exception:
        log.error()
        return ''


def _get_json(url, referer=None):
    try:
        r = multiquest.get(url, headers=_headers(referer or _base()), timeout=15, use_cf=True)
        r.raise_for_status()
        return r.json()
    except Exception:
        log.error()
        return {}


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _quality(text):
    text = re.sub(r'[?#|].*$', '', (text or '')).lower()
    m = re.search(r'(?<![0-9])(2160|1440|1080|720|480)p?(?![0-9])', text)
    if m:
        return {'2160': '4K', '1440': '1440p', '1080': '1080p', '720': '720p', '480': 'SD'}[m.group(1)]
    if re.search(r'(?<![a-z0-9])4k(?![a-z0-9])', text): return '4K'
    if re.search(r'(?<![a-z0-9])dvd', text): return 'SD'
    return 'HD'


def _host(url):
    try:
        return (urlparse(url).hostname or '').replace('www.', '')
    except Exception:
        return ''


def _norm_url(url, base=''):
    url = unescape((url or '').strip()).replace('\\/', '/').replace('\\u0026', '&')
    if not url or url.startswith(('javascript:', 'data:', '#')):
        return ''
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('/') and base:
        return base.rstrip('/') + url
    return url


def _is_skipped(host):
    return not host or any(host == s or host.endswith('.' + s) for s in SKIP_HOSTS)


def get_details(url='', params=None):
    if not url:
        return {}
    html   = _get(url, _base())
    result = {}

    m = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:description"', html, re.I)
    if m:
        plot = unescape(m.group(1)).strip()
        if len(plot) > 40:
            result['plot'] = plot

    m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"', html, re.I)
    if m:
        result['poster'] = unescape(m.group(1))

    m = re.search(r'<div class="cv-m">(\d{4})', html, re.I)
    if m:
        result['year'] = m.group(1)

    return result


def _parse_grid(html):
    items = []
    seen  = set()
    for card in re.split(r'(?=<a class="cv"[\s>])', html or ''):
        m_href  = re.search(r'<a class="cv"\s+href="(/(filme|serie)/[^"]+)"', card)
        m_thumb = re.search(r'<img src="(https://img\.streamcloud\.date[^"]+)"', card)
        m_title = re.search(r'<div class="cv-t">([^<]+)</div>', card)
        m_year  = re.search(r'<div class="cv-m">(\d{4})', card)
        if not (m_href and m_title):
            continue
        href = m_href.group(1)
        if href in seen:
            continue
        seen.add(href)
        is_serie = m_href.group(2) == 'serie'
        items.append({
            'title':       unescape(m_title.group(1).strip()),
            'url':         _base() + href,
            'poster':      m_thumb.group(1) if m_thumb else '',
            'year':        m_year.group(1) if m_year else '',
            'mediatype':   'tvshow' if is_serie else 'movie',
            'next_func':   'get_seasons' if is_serie else 'get_hosters',
            'is_playable': not is_serie,
        })
    return items


def _next_page(html, current_url):
    m = re.search(r'<div class="carica">.*?<a href="([^"]+)"', html or '', re.S)
    if not m:
        return ''
    href = unescape(m.group(1)).strip()
    if href.startswith('http'):
        return href
    if href.startswith('/'):
        return _base() + href
    return ''


def _browse(url, func='load', no_details=False):
    html  = _get(url, _base())
    items = _parse_grid(html)
    if no_details:
        for item in items:
            item['plot'] = ' '
    nxt = _next_page(html, url)
    if nxt and items:
        items.append({
            'title':       '[B]Nächste Seite >>[/B]',
            'url':         nxt,
            'next_func':   func,
            'is_playable': False,
        })
    return items


def _discover_url(g='', t='', sort=''):
    parts = []
    if g:
        parts.append('g=' + quote(g))
    if t:
        parts.append('t=' + quote(t))
    if sort:
        parts.append('sort=' + quote(sort))
    return _base() + '/discover' + ('?' + '&'.join(parts) if parts else '')


def _main_menu(func):
    b = _base()
    return [
        {'title': 'Trending',       'url': b + '/trends',    'next_func': func, 'is_playable': False},
        {'title': 'Kinofilme',      'url': b + '/kinofilme', 'next_func': func, 'is_playable': False},
        {'title': 'Serien',         'url': b + '/serien',    'next_func': func, 'is_playable': False},
        {'title': 'Alle Filme',     'url': b + '/filme',     'next_func': func, 'is_playable': False},
        {'title': 'Entdecken',      'url': b + '/discover',  'next_func': func, 'is_playable': False},
        {'title': 'Genres',         'url': '', 'next_func': 'load_genres' if func == 'load' else 'load_genres_fast', 'is_playable': False},
        {'title': 'Sortierung',     'url': '', 'next_func': 'load_sorts' if func == 'load' else 'load_sorts_fast',   'is_playable': False},
    ]


def load(url='', params=None):
    if url:
        return _browse(url, 'load')
    items = [{'title': '[B]── Schnell (ohne Beschreibung) ──[/B]', 'url': '', 'next_func': 'load_fast', 'is_playable': False}]
    return items + _main_menu('load')


def load_fast(url='', params=None):
    if url:
        return _browse(url, 'load_fast', no_details=True)
    return _main_menu('load_fast')


def _genre_menu(func, typ=''):
    return [
        {'title': name, 'url': _discover_url(g=slug, t=typ), 'next_func': func, 'is_playable': False}
        for slug, name in GENRES
    ]


def load_genres(url='', params=None):
    params = params or {}
    if 'typ' not in params:
        return [
            {'title': label, 'url': '', 'next_func': 'load_genres', 'is_playable': False, 'typ': t}
            for t, label in TYPES
        ]
    return _genre_menu('load', params.get('typ', ''))


def load_genres_fast(url='', params=None):
    params = params or {}
    if 'typ' not in params:
        return [
            {'title': label, 'url': '', 'next_func': 'load_genres_fast', 'is_playable': False, 'typ': t}
            for t, label in TYPES
        ]
    return _genre_menu('load_fast', params.get('typ', ''))


def load_sorts(url='', params=None):
    return [
        {'title': label, 'url': _discover_url(sort=key), 'next_func': 'load', 'is_playable': False}
        for key, label in SORTS
    ]


def load_sorts_fast(url='', params=None):
    return [
        {'title': label, 'url': _discover_url(sort=key), 'next_func': 'load_fast', 'is_playable': False}
        for key, label in SORTS
    ]


def _api_search(query):
    data = _get_json(_base() + '/api/suche?q=%s&g=1' % quote(query), _base())
    results = []
    for row in (data.get('righe') or []):
        url = row.get('url', '')
        if not url.startswith('http'):
            url = _base() + url
        results.append({
            'title':  row.get('titolo', ''),
            'url':    url,
            'year':   str(row.get('anno', '')),
            'tipo':   row.get('tipo', 'movie'),
            'poster': row.get('poster', ''),
        })
    return results


def search(query='', params=None):
    items = []
    for item in _api_search(query):
        is_serie = item['tipo'] == 'tv'
        items.append({
            'title':       item['title'],
            'url':         item['url'],
            'year':        item['year'],
            'poster':      item['poster'],
            'mediatype':   'tvshow' if is_serie else 'movie',
            'is_playable': not is_serie,
            'next_func':   'get_seasons' if is_serie else 'get_hosters',
        })
    return items


def _title_matches(title, clean_titles):
    current = _cleantitle(title)
    if current in clean_titles: return True
    return any(current and c and (current.startswith(c) or c.startswith(current)) for c in clean_titles)


def _find_detail_urls(title, year, expect_series, imdb_id=''):
    seen    = set()
    results = []
    query   = imdb_id if imdb_id else title
    for item in _api_search(query):
        is_serie = item['tipo'] == 'tv'
        if expect_series != is_serie:
            continue
        if not imdb_id:
            if year and item['year'] and str(year) != str(item['year']):
                continue
            if not _title_matches(item['title'], {_cleantitle(title)}):
                continue
        if item['url'] not in seen:
            seen.add(item['url'])
            results.append(item['url'])
    return results


def _imdb_from_html(html):
    text = (html or '').replace('\\/', '/')
    m = re.search(r'devideosrc\.co/custom/(?:serial|movie|tv)/(tt\d+)', text, re.I)
    if m:
        return m.group(1)
    m = re.search(r'imdb\.com/title/(tt\d+)', text, re.I)
    return m.group(1) if m else ''


def get_seasons(url='', params=None):
    html = _get(url, _base())
    seasons = []
    for s_str, ep_str in re.findall(
        r'<button[^>]*>Staffel\s+(\d+)<b>(\d+)</b></button>', html, re.I
    ):
        seasons.append((int(s_str), int(ep_str)))
    return [
        {
            'title':       'Staffel %d  (%d Folgen)' % (s, ep),
            'url':         url,
            'season':      s,
            'next_func':   'get_episodes',
            'is_playable': False,
        }
        for s, ep in sorted(set(seasons))
    ]


def get_episodes(url='', params=None):
    season = int((params or {}).get('season', 0))
    if not season:
        return []
    html = _get(url, _base())
    m = re.search(r'<button[^>]*>Staffel\s+%d<b>(\d+)</b></button>' % season, html, re.I)
    count = int(m.group(1)) if m else 0
    if not count:
        m2 = re.search(r'"season_number":%d[^}]+"disponibili":(\d+)' % season, html)
        count = int(m2.group(1)) if m2 else 0
    return [
        {
            'title':       'Episode %d' % e,
            'url':         url,
            'season':      season,
            'episode':     e,
            'next_func':   'get_hosters',
            'is_playable': True,
        }
        for e in range(1, count + 1)
    ]


def _extract_urls(html, base):
    text = (html or '').replace('\\/', '/').replace('\\u0026', '&').replace('&amp;', '&')
    found = []
    patterns = (
        r'<iframe[^>]+?(?:src|data-src)=["\']([^"\']+)',
        r'data-(?:link|src|url|embed|iframe)=["\']([^"\']+)',
        r'(?:file|src|source|url|link|embed)["\']?\s*[:=]\s*["\'](https?:?//[^"\']+)',
        r'["\'](https?://[^"\'\s<>\\]+\.(?:m3u8|mp4)[^"\'\s<>\\]*)',
        r'["\'](https?://devideosrc\.co/custom/[^"\'\s<>\\]+)',
        r'["\'](https?://dr0pstream\.com/e/[a-z0-9]+)',
    )
    for pat in patterns:
        for u in re.findall(pat, text, re.I):
            u = _norm_url(u, base)
            if u and u not in found:
                found.append(u)
    return found


def _origin(url):
    p = urlparse(url)
    return '%s://%s' % (p.scheme or 'https', p.netloc)


def _wrap_direct(url, referer, ua=None):
    if '|' in url or not MEDIA_RE.search(url):
        return url
    ref = referer if referer.endswith('/') else referer + '/'
    return '%s|Referer=%s&Origin=%s&User-Agent=%s' % (
        url, quote(ref, safe=':/'), quote(_origin(ref), safe=':/'), quote(ua or UA, safe='')
    )


def _accept(url, seen, result, referer):
    host = _host(url)
    if not url.startswith('http') or (_is_skipped(host) and not MEDIA_RE.search(url)):
        return False
    is_media = MEDIA_RE.search(url) is not None
    if host in DIRECT_ONLY_HOSTS and not is_media:
        return False
    if not is_media and (ASSET_RE.search(url) or not EMBED_RE.search(urlparse(url).path or '')):
        return False
    if url in seen:
        return False
    seen.add(url)
    final = _wrap_direct(url, referer) if is_media else url
    result.append((host or SITE_NAME, final, is_media, _quality(url), 'de'))
    return True


def _b62(n, base):
    chars = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    out = ''
    while True:
        out = chars[n % base] + out
        n //= base
        if n == 0:
            return out


def _unpack(html):
    out = ''
    for m in re.finditer(r"\}\('(.*?)',(\d+),(\d+),'([^']*)'\.split\('\|'\)", html or '', re.S):
        payload = m.group(1).replace("\\'", "'").replace('\\\\', '\\')
        base, count, words = int(m.group(2)), int(m.group(3)), m.group(4).split('|')
        table = {}
        for n in range(count):
            key = _b62(n, base)
            table[key] = words[n] if n < len(words) and words[n] else key
        out += re.sub(r'\b\w+\b', lambda x: table.get(x.group(0), x.group(0)), payload)
    return out


def _post_json(url, payload, referer):
    headers = _headers(referer)
    headers['Content-Type'] = 'application/json'
    headers['Origin'] = _origin(referer)
    headers['Accept'] = 'application/json, text/plain, */*'
    for kwargs in ({'json': payload}, {'data': json.dumps(payload)}):
        try:
            r = multiquest.post(url, headers=headers, timeout=15, use_cf=True, **kwargs)
            r.raise_for_status()
            return r.json()
        except TypeError:
            continue
        except Exception:
            log.error()
            return {}
    return {}


def _dropload_embed(url):
    m = re.search(r'/(?:e|embed|d)/([0-9a-z]+)', url, re.I)
    if m and re.search(r'dr0pstream|dropload|dropcdn', _host(url)):
        return 'https://dropload.io/e/' + m.group(1)
    return ''


def _resolve_embed(url, referer):
    host = _host(url)
    if not re.search(r'dr0pstream|dropload|dropcdn', host):
        return []
    result = []
    mirror = _dropload_embed(url)
    if mirror:
        result.append(('dropload.io', mirror, False, 'HD', 'de'))
    html = _get(url, referer)
    ua   = LAST_UA[0]
    text = ((html or '') + _unpack(html)).replace('\\/', '/')
    links = re.findall(r'file\s*:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)', text, re.I)
    if not links:
        links = re.findall(r'["\'](https?://[^"\'\s]+\.(?:m3u8|mp4)[^"\'\s]*)', text, re.I)
    label = re.search(r'qualityLabels["\']?\s*:\s*\{[^}]*?["\']?(\d{3,4})p', text)
    for link in links[:1]:
        quality = _quality(label.group(1) + 'p') if label else _quality(link)
        result.append((
            host + ' (direkt)',
            _wrap_direct(unescape(link), _origin(url) + '/', ua),
            True, quality, 'de',
        ))
    return result


def _dvs_links(dvs_url, seen):
    html   = _get(dvs_url, _base())
    result = []
    origin = _origin(dvs_url)
    tag    = re.search(r'<[^>]+data-resolve-token="[^"]*"[^>]*>', html or '')
    if tag:
        attrs = dict(re.findall(r'data-([a-z-]+)="([^"]*)"', tag.group(0)))
        payload = {
            'type':    attrs.get('type', ''),
            'id':      attrs.get('id', ''),
            'season':  attrs.get('season', ''),
            'episode': attrs.get('episode', ''),
            'mode':    attrs.get('mode', 'custom'),
            'token':   attrs.get('resolve-token', ''),
        }
        endpoint = origin + (attrs.get('resolve-endpoint') or '/api/resolve')
        data = _post_json(endpoint, payload, dvs_url)
        for src in sorted(data.get('sources') or [], key=lambda x: x.get('rank', 99)):
            link = _norm_url(src.get('url', ''), origin)
            if not link or link in seen:
                continue
            seen.add(link)
            direct = _resolve_embed(link, origin + '/')
            if direct:
                result += direct
                continue
            is_media = MEDIA_RE.search(link) is not None
            result.append((
                src.get('name') or _host(link),
                _wrap_direct(link, origin + '/') if is_media else link,
                is_media, _quality(link), 'de',
            ))
    if not result:
        for u in _extract_urls(html, origin):
            if _host(u) == 'devideosrc.co' and not MEDIA_RE.search(u):
                continue
            _accept(u, seen, result, origin)
    return result


def _detail_links(detail_url, seen, serial=None):
    html   = _get(detail_url, _base())
    result = []
    for u in _extract_urls(html, _base()):
        host = _host(u)
        if host == 'devideosrc.co' and not MEDIA_RE.search(u):
            if '/custom/serial/' in u or '/custom/tv/' in u:
                if serial:
                    u = re.sub(r'(/custom/(?:serial|tv)/tt\d+).*$', r'\1/%d/%d' % serial, u)
                else:
                    continue
            result += _dvs_links(u, seen)
        elif MEDIA_RE.search(u):
            _accept(u, seen, result, _base())
    return result, html


def _evil():
    try:
        from resources.lib import cloud
        return cloud
    except Exception:
        return None


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if params:
        season  = int(params.get('season',  season  or 0))
        episode = int(params.get('episode', episode or 0))
    season  = int(season or 0)
    episode = int(episode or 0)
    result  = []
    seen    = set()
    evil    = _evil()

    if season == 0:
        detail_urls = [url] if url else _find_detail_urls(title, year, False, imdb_id=imdb)[:3]
        for detail_url in detail_urls:
            links, html = _detail_links(detail_url, seen)
            result += links
            if not imdb:
                imdb = _imdb_from_html(html)
        if not result and imdb:
            result += _dvs_links('https://devideosrc.co/custom/movie/%s' % imdb, seen)
        if imdb and evil:
            try:
                for item in evil.get_movie(imdb):
                    name, hurl, direct = item[0], item[1], item[2]
                    if hurl not in seen:
                        seen.add(hurl)
                        result.append((name, hurl, direct, _quality(hurl), 'de'))
            except Exception:
                log.error()
    else:
        detail_urls = [url] if url else _find_detail_urls(title, '', True, imdb_id=imdb)[:3]
        imdb_id = imdb
        for detail_url in detail_urls:
            links, html = _detail_links(detail_url, seen, serial=(season, episode))
            result += links
            imdb_id = imdb_id or _imdb_from_html(html)
        if not result and imdb_id:
            result += _dvs_links(
                'https://devideosrc.co/custom/serial/%s/%d/%d' % (imdb_id, season, episode), seen
            )
        if imdb_id and evil:
            try:
                for item in evil.get_episode(imdb_id, season, episode):
                    name, hurl, direct = item[0], item[1], item[2]
                    if hurl not in seen:
                        seen.add(hurl)
                        result.append((name, hurl, direct, _quality(hurl), 'de'))
            except Exception:
                log.error()
    return result
