import re
import json
import time
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait
from html import unescape
from urllib.parse import quote, urlparse, urlencode, parse_qs, urlunparse
from resources.lib import multiquest, log

SITE_ID       = 'kinoking'
SITE_NAME     = 'KinoKing'
SITE_DOMAIN   = 'kinoking.cc'
TYPE          = 'browse'
GLOBAL_SEARCH = True

UA = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/30.0 Chrome/143.0.0.0 Mobile Safari/537.36'

SKIP_HOSTS = (
    'youtube.com', 'youtu.be', 'google.com', 'gstatic.com', 'googletagmanager.com',
    'google-analytics.com', 'facebook.com', 'twitter.com', 't.me', 'fonts.googleapis.com',
    'schema.org', 'w3.org', 'imdb.com', 'themoviedb.org', 'tmdb.org', 'kinoking.cc',
    'image.tmdb.org', 'tailwindcss.com', 'jsdelivr.net', 'cdnjs.cloudflare.com',
    'cloudflare.com', 'challenges.cloudflare.com', 'rapidadexchange.com', 'intellipopup.com',
)

DIRECT_ONLY_HOSTS = ()

DEVIDEOSRC_HOSTS = ('meinecloud.click', 'vidsync.xyz', 'cinesrc.st')

ASSET_RE = re.compile(r'\.(jpe?g|png|gif|webp|svg|ico|css|js|woff2?|ttf|vtt|srt|json|xml)(\?|$)', re.I)
EMBED_RE = re.compile(r'/(e|embed|embed-[^/]+|v|d|f|watch|player|play|video|videos|stream|file)/|/embed', re.I)
MEDIA_RE = re.compile(r'\.(mp4|m3u8)(\?|$|\|)', re.I)

GENRES = [
    ('current-movies',  'Aktuelle Filme'),
    ('current-series',  'Aktuelle Serien'),
    ('top10-movies',    'Top 10 Filme'),
    ('recently-added',  'Neuerscheinungen'),
    ('anime',           'Anime'),
]

LETTERS = list('ABCDEFGHIJKLMNOPQRSTUVWXYZ') + ['0-9']


def _base():
    return 'https://' + SITE_DOMAIN


def _headers(referer=None):
    h = {'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8', 'User-Agent': UA}
    if referer:
        h['Referer'] = referer
    return h


def _get(url, referer=None):
    try:
        r = multiquest.get(url, headers=_headers(referer), timeout=15, use_cf=True)
        r.raise_for_status()
        return r.text
    except Exception as e:
        if '404' not in str(e):
            log.error()
        return ''


def _get_json(url, referer=None):
    text = _get(url, referer)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _dbg(msg):
    try:
        log.log('[kinoking] ' + str(msg))
    except Exception:
        pass


def _cleantitle(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _quality(text):
    text = re.sub(r'[?#|].*$', '', (text or '')).lower()
    m = re.search(r'(?<![0-9])(2160|1440|1080|720|480)p?(?![0-9])', text)
    if m:
        return {'2160': '4K', '1440': '1440p', '1080': '1080p', '720': '720p', '480': 'SD'}[m.group(1)]
    if re.search(r'(?<![a-z0-9])4k(?![a-z0-9])', text):
        return '4K'
    return 'HD'


def _host(url):
    try:
        return (urlparse(url).hostname or '').replace('www.', '')
    except Exception:
        return ''


def _is_skipped(host):
    return not host or any(host == s or host.endswith('.' + s) for s in SKIP_HOSTS)


def _norm_url(url, base=''):
    url = unescape((url or '').strip()).replace('\\/', '/').replace('\\u0026', '&')
    if not url or url.startswith(('javascript:', 'data:', '#')):
        return ''
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('/') and base:
        return base.rstrip('/') + url
    return url


def _parse_grid(html):
    items = []
    seen = set()

    for card in re.split(r'(?=<div[^>]*class="[^"]*movie-card-shadow[^"]*")', html or ''):
        m_href = re.search(r'onclick="trackHistoryAndGo\(this,\s*[\'\"]((?:movie|series)\.php\?id=(\d+))[\'\"]', card)
        m_poster = re.search(r'<img[^>]+src="(https://image\.tmdb\.org[^"]+)"', card)
        m_title = re.search(r'data-title="([^"]+)"', card)
        m_type = re.search(r'data-type="(\w+)"', card)
        m_year = re.search(r'<span[^>]*text-neutral[^>]*>(\d{4})</span>', card)
        m_rating = re.search(r'fa-star[^<]*</i>\s*([\d.]+)', card)

        if not (m_href and m_title):
            continue
        php_url = m_href.group(1)
        kk_id = m_href.group(2)
        if kk_id in seen:
            continue
        seen.add(kk_id)

        raw_type = (m_type.group(1) if m_type else 'movie').lower()
        is_serie = raw_type == 'series'

        item = {
            'title':       unescape(m_title.group(1).strip()),
            'url':         _base() + '/' + php_url,
            'poster':      m_poster.group(1) if m_poster else '',
            'year':        m_year.group(1) if m_year else '',
            'plot':        ' ',
            'mediatype':   'tvshow' if is_serie else 'movie',
            'next_func':   'get_seasons' if is_serie else 'get_hosters',
            'is_playable': not is_serie,
        }
        if m_rating:
            try:
                item['rating'] = float(m_rating.group(1))
            except ValueError:
                pass
        items.append(item)

    return items


def _next_page(html, current_url):
    if not html or 'load-more-btn' not in html:
        return ''
    cur_match = re.search(r'[?&]page=(\d+)', current_url)
    cur_page = int(cur_match.group(1)) if cur_match else 1
    next_page = cur_page + 1
    if re.search(r'[?&]page=\d+', current_url):
        return re.sub(r'([?&]page=)\d+', lambda m: m.group(1) + str(next_page), current_url)
    sep = '&' if '?' in current_url else '?'
    return current_url + sep + 'page=%d' % next_page


def _browse(url, func='load'):
    html = _get(url, _base())
    items = _parse_grid(html)
    nxt = _next_page(html, url)
    if nxt and items:
        items.append({
            'title':       '[B]Nächste Seite >>[/B]',
            'url':         nxt,
            'next_func':   func,
            'is_playable': False,
        })
    return items


def _genre_url(genre):
    return _base() + '/?genre=' + genre


def _letter_url(letter):
    if letter == '0-9':
        return _base() + '/?letter=num'
    return _base() + '/?letter=' + letter


def _main_menu(func):
    items = [
        {'title': 'Aktuelle Kinofilme',  'url': _genre_url('current-movies'), 'next_func': func, 'is_playable': False},
        {'title': 'Aktuelle Serien',     'url': _genre_url('current-series'),  'next_func': func, 'is_playable': False},
        {'title': 'Top 10 Filme',        'url': _genre_url('top10-movies'),    'next_func': func, 'is_playable': False},
        {'title': 'Neuerscheinungen',    'url': _genre_url('recently-added'),  'next_func': func, 'is_playable': False},
        {'title': 'Anime',               'url': '', 'next_func': 'load_anime', 'is_playable': False},
        {'title': 'Live Sport',          'url': _base() + '/live.php', 'next_func': 'load_live', 'is_playable': False},
        {'title': 'Gaming',              'url': _base() + '/gaming.php?api=home&page=1', 'next_func': 'load_gaming', 'is_playable': False},
        {'title': 'Genres',              'url': '', 'next_func': 'load_genres', 'is_playable': False},
        {'title': 'A–Z',                 'url': '', 'next_func': 'load_letters', 'is_playable': False},
    ]
    return items


def load(url='', params=None):
    if url:
        return _browse(url, 'load')
    return _main_menu('load')


def load_genres(url='', params=None):
    return [
        {'title': name, 'url': _genre_url(slug), 'next_func': 'load', 'is_playable': False}
        for slug, name in GENRES
    ]


def load_letters(url='', params=None):
    return [
        {'title': letter, 'url': _letter_url(letter), 'next_func': 'load', 'is_playable': False}
        for letter in LETTERS
    ]


def load_anime(url='', params=None):
    return [
        {'title': 'Beliebt',          'url': _base() + '/anime.php?category=popular', 'next_func': 'load_anime_cat', 'is_playable': False},
        {'title': 'Neu',              'url': _base() + '/anime.php?category=new',     'next_func': 'load_anime_cat', 'is_playable': False},
        {'title': 'Alle',             'url': _base() + '/anime.php',                  'next_func': 'load_anime_cat', 'is_playable': False},
    ]


def _parse_anime_grid(html):
    items = []
    seen = set()
    for card in re.split(r'(?=<div[^>]*class="[^"]*(?:anime-card|history-card)[^"]*")', html or ''):
        m_href = re.search(r'href="([^"]*(?:anime|series|movie)\.php\?[^"]+)"', card)
        m_poster = re.search(r'<img[^>]+src="(https?://[^"]+(?:tmdb|imageban)[^"]+)"', card)
        m_title = re.search(r'(?:data-title|title)="([^"]{2,})"', card)
        if not (m_href and m_title):
            m_title2 = re.search(r'<h\d[^>]*>\s*([^<]{2,})\s*</h\d>', card)
            if not (m_href and m_title2):
                continue
            m_title = m_title2
        url_path = m_href.group(1) if m_href else ''
        full_url = url_path if url_path.startswith('http') else _base() + '/' + url_path.lstrip('/')
        uid = full_url
        if uid in seen:
            continue
        seen.add(uid)
        is_serie = 'series' in full_url
        items.append({
            'title':       unescape(m_title.group(1).strip()),
            'url':         full_url,
            'poster':      m_poster.group(1) if m_poster else '',
            'mediatype':   'tvshow' if is_serie else 'movie',
            'next_func':   'get_seasons' if is_serie else 'get_hosters',
            'is_playable': not is_serie,
        })
    return items


def load_anime_cat(url='', params=None):
    if not url:
        url = _base() + '/anime.php'
    html = _get(url, _base())
    items = _parse_anime_grid(html)
    if not items:
        items = _parse_grid(html)
    return items


def load_live(url='', params=None):
    api_url = _base() + '/live.php?api=matches&cat=Startseite'
    data = _get_json(api_url, _base() + '/live.php')
    if not data:
        return []
    items = []
    for match in data.get('matches', []):
        title = match.get('title', '')
        match_url = match.get('url', '')
        t = match.get('time', '')
        display = '[B]%s[/B]' % title
        if t:
            display += '  [COLOR gray]%s[/COLOR]' % t
        items.append({
            'title':       display,
            'url':         match_url,
            'next_func':   'load_live_streams',
            'is_playable': False,
        })
    return items


def load_live_streams(url='', params=None):
    if not url:
        return []
    api_url = _base() + '/live.php?api=streams&url=' + quote(url, safe='')
    data = _get_json(api_url, _base() + '/live.php')
    if not data:
        return []
    streams = data.get('streams', [])
    if not streams:
        return [(url, url, True, 'HD', 'de')]
    result = []
    seen = set()
    for s in streams:
        stream_url = s.get('url') or s.get('src') or (s if isinstance(s, str) else '')
        if not stream_url or stream_url in seen:
            continue
        seen.add(stream_url)
        label = s.get('label', '') if isinstance(s, dict) else ''
        quality = _quality(label or stream_url)
        result.append((label or _host(stream_url), stream_url, True, quality, 'de'))
    return result


def load_gaming(url='', params=None):
    if not url:
        url = _base() + '/gaming.php?api=home&page=1'
    data = _get_json(url, _base() + '/gaming.php')
    if not data:
        return []
    items = []
    cur_match = re.search(r'[?&]page=(\d+)', url)
    cur_page = int(cur_match.group(1)) if cur_match else 1

    for game in data.get('games', []):
        title = game.get('title', '')
        game_url = game.get('url', '')
        poster = game.get('image', '')
        date = game.get('date', '')
        display = title
        if date:
            display += '  [COLOR gray](%s)[/COLOR]' % date
        items.append({
            'title':       display,
            'url':         game_url,
            'poster':      poster,
            'is_playable': False,
            'next_func':   'load_gaming_page',
        })

    next_url = re.sub(r'([?&]page=)\d+', lambda m: m.group(1) + str(cur_page + 1), url)
    if next_url == url:
        sep = '&' if '?' in url else '?'
        next_url = url + sep + 'page=%d' % (cur_page + 1)
    if items:
        items.append({
            'title':       '[B]Nächste Seite >>[/B]',
            'url':         next_url,
            'next_func':   'load_gaming',
            'is_playable': False,
        })
    return items


def load_gaming_page(url='', params=None):
    return [{'title': 'FitGirl Repacks öffnen', 'url': url, 'is_playable': False}]


def search(query='', params=None):
    html = _get(_base() + '/index.php?search=' + quote(query), _base())
    items = []
    seen = set()

    for card in re.split(r'(?=<div[^>]*class="[^"]*movie-card-shadow[^"]*")', html or ''):
        m_href = re.search(r'onclick="trackHistoryAndGo\(this,\s*[\'\"]((?:movie|series)\.php\?id=(\d+))[\'\"]', card)
        m_poster = re.search(r'<img[^>]+src="(https://image\.tmdb\.org[^"]+)"', card)
        m_title = re.search(r'data-title="([^"]+)"', card)
        m_type = re.search(r'data-type="(\w+)"', card)
        m_year = re.search(r'<span[^>]*text-neutral[^>]*>(\d{4})</span>', card)

        if not (m_href and m_title):
            continue
        kk_id = m_href.group(2)
        if kk_id in seen:
            continue
        seen.add(kk_id)

        raw_type = (m_type.group(1) if m_type else 'movie').lower()
        is_serie = raw_type == 'series'

        items.append({
            'title':       unescape(m_title.group(1).strip()),
            'url':         _base() + '/' + m_href.group(1),
            'poster':      m_poster.group(1) if m_poster else '',
            'year':        m_year.group(1) if m_year else '',
            'mediatype':   'tvshow' if is_serie else 'movie',
            'next_func':   'get_seasons' if is_serie else 'get_hosters',
            'is_playable': not is_serie,
        })

    return items


def _detail_meta(html):
    result = {}

    m = re.search(r'"description"\s*:\s*"([^"]{40,})"', html)
    if not m:
        m = re.search(r'<meta[^>]+(?:name|property)="(?:description|og:description)"[^>]+content="([^"]{40,})"', html, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content="([^"]{40,})"[^>]+(?:name|property)="(?:description|og:description)"', html, re.I)
    if m:
        result['plot'] = unescape(m.group(1)).replace('\\"', '"').strip()

    m = re.search(r'"image"\s*:\s*"([^"]+t/p/w500[^"]+)"', html)
    if not m:
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, re.I)
    if m:
        result['poster'] = unescape(m.group(1)).replace('\\/', '/')

    m = re.search(r'"dateCreated"\s*:\s*"(\d{4})', html)
    if m:
        result['year'] = m.group(1)

    m = re.search(r'"ratingValue"\s*:\s*"([^"]+)"', html)
    if m:
        try:
            result['rating'] = float(m.group(1))
        except ValueError:
            pass

    return result


def _parse_series_meta(html):
    result = {}
    for var in ('TMDB_SERIES_ID', 'imdbId', 'seriesTitle', 'seriesYear', 'CURRENT_SERIES_ID'):
        m = re.search(r"const\s+%s\s*=\s*['\"]([^'\"]+)['\"]" % var, html)
        if m:
            result[var] = m.group(1)
    m = re.search(r'allEpisodesData\s*=\s*(\[.*?\]);', html, re.S)
    if m:
        try:
            result['episodes'] = json.loads(m.group(1))
        except Exception:
            result['episodes'] = []
    else:
        result['episodes'] = []
    return result


def get_seasons(url='', params=None):
    html = _get(url, _base())
    meta = _parse_series_meta(html)
    episodes = meta.get('episodes', [])

    seasons = sorted(set(ep['season_number'] for ep in episodes if ep.get('season_number')))

    if not seasons:
        for m in re.finditer(r'data-season="(\d+)"', html):
            s = int(m.group(1))
            if s not in seasons:
                seasons.append(s)

    return [
        {
            'title':       'Staffel %d' % s,
            'url':         url,
            'season':      s,
            'next_func':   'get_episodes',
            'is_playable': False,
        }
        for s in seasons
    ]


def get_episodes(url='', params=None):
    season = int((params or {}).get('season', 0))
    if not season:
        return []
    html = _get(url, _base())
    meta = _parse_series_meta(html)
    episodes = [ep for ep in meta.get('episodes', []) if ep.get('season_number') == season]

    if not episodes:
        eps_found = []
        for m in re.finditer(r'data-season="%d"[^>]*data-episode="(\d+)"' % season, html):
            ep = int(m.group(1))
            if ep not in eps_found:
                eps_found.append(ep)
        return [
            {
                'title':       'Episode %d' % ep,
                'url':         url,
                'season':      season,
                'episode':     ep,
                'next_func':   'get_hosters',
                'is_playable': True,
            }
            for ep in sorted(set(eps_found))
        ]

    return [
        {
            'title':       'S%02dE%02d %s' % (ep['season_number'], ep['episode_number'], ep.get('name', '')),
            'url':         url,
            'season':      ep['season_number'],
            'episode':     ep['episode_number'],
            'plot':        ep.get('overview', ''),
            'next_func':   'get_hosters',
            'is_playable': True,
        }
        for ep in sorted(episodes, key=lambda x: x['episode_number'])
    ]


def _resolve_devideosrc(embed_url):
    html = _get(embed_url, embed_url)
    if not html:
        return []

    m = re.search(r'token\s*:\s*["\']([A-Za-z0-9+/=_.-]+\.[0-9a-f]{40,})["\']', html)
    if not m:
        return []
    token = m.group(1)

    parsed = urlparse(embed_url)
    base = parsed.scheme + '://' + parsed.netloc
    path_parts = [p for p in parsed.path.strip('/').split('/') if p]

    content_type = 'movie'
    content_id = ''
    season_n = 0
    episode_n = 0

    if len(path_parts) >= 2 and path_parts[0] in ('embed', 'movie', 'tv'):
        if path_parts[0] == 'embed' and len(path_parts) >= 2:
            content_type = path_parts[1]
            if len(path_parts) >= 3:
                content_id = path_parts[2]
            if content_type == 'tv' and len(path_parts) >= 5:
                try:
                    season_n = int(path_parts[3])
                    episode_n = int(path_parts[4])
                except ValueError:
                    pass
        elif path_parts[0] == 'movie':
            content_type = 'movie'
            content_id = path_parts[1] if len(path_parts) >= 2 else ''
        elif path_parts[0] == 'tv':
            content_type = 'tv'
            content_id = path_parts[1] if len(path_parts) >= 2 else ''
    else:
        for part in path_parts:
            if part in ('movie', 'tv'):
                content_type = part
            elif re.match(r'^(tt\d+|\d+)$', part):
                content_id = part

    if not content_id:
        qs = parse_qs(parsed.query)
        content_id = (qs.get('id') or qs.get('tmdb') or [''])[0]

    if not season_n:
        qs = parse_qs(parsed.query)
        try:
            season_n = int((qs.get('s') or qs.get('season') or [0])[0])
            episode_n = int((qs.get('e') or qs.get('episode') or [0])[0])
        except (ValueError, IndexError):
            pass

    if not content_id:
        return []

    post_body = {'type': content_type, 'id': content_id, 'token': token}
    if season_n:
        post_body['season'] = season_n
        post_body['episode'] = episode_n

    try:
        r = multiquest.post(
            base + '/api/embed-links',
            json=post_body,
            headers=dict(_headers(embed_url), **{'Content-Type': 'application/json', 'Origin': base}),
            timeout=15,
            use_cf=True,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        log.error()
        return []

    if not data.get('ok'):
        return []

    result = []
    for src in data.get('sources', []):
        url = src.get('url', '').strip()
        if not url:
            continue
        name = src.get('name', _host(url))
        is_media = bool(MEDIA_RE.search(url))
        quality = _quality(url) if is_media else 'HD'
        result.append((name, url, is_media, quality, 'de'))

    _dbg('devideosrc %s -> %d sources' % (embed_url, len(result)))
    return result


def _parse_servers(html, season=0, episode=0):
    if season and episode:
        return _collect_ajax_hosters(html, season, episode)

    m = re.search(r'const SERVERS\s*=\s*(\[.*?\]);', html, re.S)
    if not m:
        return []
    try:
        servers = json.loads(m.group(1))
    except Exception:
        return []

    result = []
    seen = set()
    for srv in servers:
        name = srv.get('name', '')
        for mirror in srv.get('mirrors', []):
            mirror = mirror.strip()
            if not mirror or mirror in seen:
                continue
            seen.add(mirror)
            is_media = bool(MEDIA_RE.search(mirror))
            host = _host(mirror)
            if any(host == h or host.endswith('.' + h) for h in DEVIDEOSRC_HOSTS) and not is_media:
                for resolved in _resolve_devideosrc(mirror):
                    rurl = resolved[1]
                    if rurl not in seen:
                        seen.add(rurl)
                        result.append(resolved)
                continue
            quality = _quality(mirror) if is_media else 'HD'
            if srv.get('quality'):
                quality = srv['quality'].upper()
            result.append((name or host, mirror, is_media, quality, 'de'))

    return result


def _collect_ajax_hosters(html, season, episode):
    meta = _parse_series_meta(html)
    tmdb   = meta.get('TMDB_SERIES_ID', '')
    imdb   = meta.get('imdbId', '')
    title  = meta.get('seriesTitle', '')
    year   = meta.get('seriesYear', '')
    series_url = _base() + '/series.php?id=' + meta.get('CURRENT_SERIES_ID', '')

    result = []
    seen   = set()
    pending = []

    def _add(name, url):
        url = url.strip()
        if not url or url in seen:
            return
        seen.add(url)
        is_media = bool(MEDIA_RE.search(url))
        host = _host(url)
        if any(host == h or host.endswith('.' + h) for h in DEVIDEOSRC_HOSTS) and not is_media:
            pending.append(url)
            return
        result.append((name or host, url, is_media, _quality(url) if is_media else 'HD', 'de'))

    ep_data = next(
        (ep for ep in meta.get('episodes', [])
         if ep.get('season_number') == season and ep.get('episode_number') == episode),
        None
    )
    if ep_data and ep_data.get('video_links'):
        for lnk in ep_data['video_links'].split(','):
            lnk = lnk.strip()
            if lnk:
                _add('SERVER', lnk)

    if tmdb:
        _add('VIDSYNC AUTO', 'https://vidsync.xyz/embed/tv/%s/%d/%d?defaultServer=cineflix&autoPlay=true' % (tmdb, season, episode))
        _add('Kinoking UP', 'https://cinesrc.st/embed/tv/%s?s=%d&e=%d&prioritize=true&lastserver=sturm' % (tmdb, season, episode))

    def _fetch_ajax(ajax_url):
        try:
            r = multiquest.get(ajax_url, headers=_headers(series_url), timeout=12, use_cf=True)
            r.raise_for_status()
            return r.json()
        except Exception:
            log.error()
            return []

    ajax_urls = {}
    if tmdb:
        ajax_urls['huhu'] = series_url + '&ajax_huhu_links=1&tmdb=%s&s=%d&e=%d' % (tmdb, season, episode)
    if title and imdb:
        ajax_urls['kk'] = series_url + '&ajax_kk_links=1&title=%s&s=%d&e=%d&imdb=%s' % (quote(title), season, episode, imdb)
    if title and year:
        ajax_urls['fp'] = series_url + '&ajax_fp_links=1&title=%s&y=%s&s=%d&e=%d' % (quote(title), year, season, episode)
    if title:
        ajax_urls['aw'] = series_url + '&ajax_aw_links=1&title=%s&s=%d&e=%d' % (quote(title), season, episode)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {key: pool.submit(_fetch_ajax, u) for key, u in ajax_urls.items()}
        for key, future in futures.items():
            try:
                links = future.result(timeout=15) or []
                for item in links:
                    if item.get('is_group'):
                        for u in (item.get('urls') or []):
                            _add(item.get('host', ''), u)
                    else:
                        _add(item.get('host', ''), item.get('link_url', ''))
            except Exception:
                log.error()

    if pending:
        pool = ThreadPoolExecutor(max_workers=max(1, min(4, len(pending))))
        futures = [pool.submit(_resolve_devideosrc, u) for u in pending]
        done, _ = futures_wait(futures, timeout=8)
        pool.shutdown(wait=False)
        for future in futures:
            if future not in done:
                continue
            try:
                resolved_list = future.result()
            except Exception:
                log.error()
                continue
            for resolved in resolved_list:
                rurl = resolved[1]
                if rurl not in seen:
                    seen.add(rurl)
                    result.append(resolved)

    _dbg('ajax hosters s%d e%d count=%d' % (season, episode, len(result)))
    return result


def _imdb_from_html(html):
    m = re.search(r'(tt\d{5,8})', html or '')
    return m.group(1) if m else ''


def _evil():
    try:
        from resources.lib import cloud
        return cloud
    except Exception:
        return None


def _add_evil(result, seen, items):
    for item in items or []:
        name, hurl, direct = item[0], item[1], item[2]
        if hurl not in seen:
            seen.add(hurl)
            result.append((name, hurl, direct, _quality(hurl), 'de'))


def _evil_items(evil, imdb, season, episode):
    try:
        if season:
            return list(evil.get_episode(imdb, season, episode) or [])
        return list(evil.get_movie(imdb) or [])
    except Exception:
        log.error()
        return []


CACHE = {}
CACHE_TTL = 900
CACHE_TTL_EMPTY = 90


def _cache_key(title, year, season, episode, imdb, url):
    ident = url or imdb or '%s|%s' % (_cleantitle(title), year)
    return '%s|%s|%s' % (ident, season, episode)


def _stream_key(url):
    try:
        p = urlparse(url.strip())
    except Exception:
        return url
    host = (p.hostname or '').lower().replace('www.', '')
    path = p.path.rstrip('/')
    if MEDIA_RE.search(url):
        return (host, path, p.query)
    parts = [x for x in path.split('/') if x]
    labels = host.split('.')
    sld = labels[-2] if len(labels) >= 2 else host
    if parts and len(parts[-1]) >= 8:
        return (sld, parts[-1].lower())
    return (host, path.lower(), p.query)


def _dedupe(items):
    seen = set()
    out = []
    for item in items:
        key = _stream_key(item[1])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None, **kwargs):
    if params:
        season  = int(params.get('season',  season  or 0))
        episode = int(params.get('episode', episode or 0))
    season  = int(season or 0)
    episode = int(episode or 0)
    imdb    = imdb if imdb and str(imdb).startswith('tt') else ''
    key     = _cache_key(title, year, season, episode, imdb, url)
    hit     = CACHE.get(key)
    if hit and time.time() < hit[0]:
        _dbg('cache hit %s count=%d' % (key, len(hit[1])))
        return list(hit[1])
    result = _dedupe(_collect_hosters(title, year, season, episode, imdb, url))
    CACHE[key] = (time.time() + (CACHE_TTL if result else CACHE_TTL_EMPTY), list(result))
    return result


def _collect_hosters(title, year, season, episode, imdb, url):
    _dbg('get_hosters title=%r year=%r season=%s episode=%s imdb=%r url=%r' % (title, year, season, episode, imdb, url))

    evil = _evil()
    pool = ThreadPoolExecutor(max_workers=1)
    evil_future = None
    if imdb and evil:
        evil_future = pool.submit(_evil_items, evil, imdb, season, episode)

    if not url:
        url = _find_url(title, year, bool(season), imdb)
    if not url:
        if imdb and evil:
            if evil_future is None:
                evil_future = pool.submit(_evil_items, evil, imdb, season, episode)
            try:
                result = []
                seen = set()
                _add_evil(result, seen, evil_future.result(timeout=8))
            except Exception:
                log.error()
                result = []
            pool.shutdown(wait=False)
            return result
        pool.shutdown(wait=False)
        return []

    html = _get(url, _base())
    if not html:
        pool.shutdown(wait=False)
        return []

    if not imdb:
        imdb = _imdb_from_html(html)

    if season and episode:
        ep_url = _episode_url(url, season, episode, html)
        if ep_url and ep_url != url:
            html = _get(ep_url, url) or html

    result = _parse_servers(html, season, episode)
    seen = set(r[1] for r in result)

    _dbg('hosters=%d imdb=%r' % (len(result), imdb))

    if imdb and evil:
        if evil_future is None:
            evil_future = pool.submit(_evil_items, evil, imdb, season, episode)
        try:
            _add_evil(result, seen, evil_future.result(timeout=8))
        except Exception:
            log.error()
    pool.shutdown(wait=False)
    return result


def _episode_url(detail_url, season, episode, html):
    m = re.search(
        r'href="([^"]*series\.php\?id=\d+[^"]*s=%d[^"]*e=%d[^"]*)"' % (season, episode),
        html, re.I
    )
    if m:
        url = unescape(m.group(1))
        if url.startswith('/'):
            return _base() + url
        return url

    m = re.search(
        r'data-season="%d"[^>]*data-episode="%d"[^>]*(?:href|data-url)="([^"]+)"' % (season, episode),
        html, re.I
    )
    if m:
        url = unescape(m.group(1))
        if url.startswith('/'):
            return _base() + url
        if url.startswith('http'):
            return url

    if '?' in detail_url:
        return detail_url + '&s=%d&e=%d' % (season, episode)
    return detail_url + '?s=%d&e=%d' % (season, episode)


def _search_queries(title, imdb):
    queries = []
    base = re.sub(r'\s*\(?\b(19|20)\d{2}\b\)?\s*$', '', title or '').strip()
    for q in (title, base, re.split(r'\s*[:\-\u2013]\s*', base)[0].strip(), imdb):
        q = (q or '').strip()
        if q and q not in queries:
            queries.append(q)
    return queries


def _find_url(title, year, expect_series, imdb=''):
    if not title and not imdb:
        return ''
    clean = _cleantitle(title)
    fuzzy = []
    pool = []
    pooled = set()
    for query in _search_queries(title, imdb):
        items = search(query=query)
        _dbg('find_url query=%r results=%d' % (query, len(items)))
        for item in items:
            _dbg('find_url candidate %r year=%r type=%s' % (item.get('title'), item.get('year'), item.get('mediatype')))
            if expect_series != (item.get('mediatype') == 'tvshow'):
                continue
            if item['url'] not in pooled:
                pooled.add(item['url'])
                pool.append(item)
            if year and item.get('year'):
                try:
                    if abs(int(year) - int(item['year'])) > 1:
                        continue
                except ValueError:
                    pass
            ct = _cleantitle(item.get('title', ''))
            if clean and ct == clean:
                return item['url']
            if clean and ct and (ct.startswith(clean) or clean.startswith(ct) or clean in ct):
                fuzzy.append(item)
        if fuzzy:
            break
    if fuzzy:
        fuzzy.sort(key=lambda i: abs(len(_cleantitle(i.get('title', ''))) - len(clean)))
        _dbg('find_url fuzzy match %r' % fuzzy[0].get('title'))
        return fuzzy[0]['url']

    same_year = [i for i in pool if year and i.get('year') == str(year)]
    if len(same_year) == 1:
        _dbg('find_url year match %r' % same_year[0].get('title'))
        return same_year[0]['url']

    if imdb:
        for item in pool[:6]:
            html = _get(item['url'], _base())
            if html and imdb in html:
                _dbg('find_url imdb match %r' % item.get('title'))
                return item['url']
    return ''
