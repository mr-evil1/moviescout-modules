import base64
import html
import json
import os
import re
import time
from urllib.parse import quote, urlencode

try:
    from resources.lib import multiquest as _mq
except Exception:
    _mq = None

try:
    import requests as _requests
except Exception:
    _requests = None

BASE_URL = 'https://www.2ix2.com'
POSTS_URL = BASE_URL + '/wp-json/wp/v2/posts'

CACHE_TTL = 6 * 3600

BROWSER_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) '
    'Gecko/20100101 Firefox/128.0'
)

CATEGORIES = (
    {'slug': 'de', 'label': 'Deutschland',  'category_id': 1},
    {'slug': 'at', 'label': 'Österreich',   'category_id': 61},
    {'slug': 'ch', 'label': 'Schweiz',      'category_id': 100},
)

GROUP_ORDER = ['Deutschland', 'Österreich', 'Schweiz']


def get_channels(cache_path, force_refresh=False):
    cached = _read_cache(cache_path)
    if not force_refresh and cached:
        ts = int(cached.get('timestamp') or 0)
        channels = _usable(cached.get('channels') or [])
        if channels and time.time() - ts < CACHE_TTL:
            return channels

    fresh = _load_from_2ix2()
    if fresh:
        _write_cache(cache_path, fresh)
        return fresh

    stale = _usable((cached or {}).get('channels') or [])
    return stale


def get_groups(cache_path, force_refresh=False):
    channels = get_channels(cache_path, force_refresh=force_refresh)
    groups = {}
    for ch in channels:
        g = ch.get('group', 'Other')
        groups[g] = groups.get(g, 0) + 1
    ordered = [g for g in GROUP_ORDER if g in groups]
    for g in sorted(groups):
        if g not in ordered:
            ordered.append(g)
    return [{'name': g, 'count': groups[g]} for g in ordered]


def get_group_channels(cache_path, group):
    channels = get_channels(cache_path)
    return sorted(
        [ch for ch in channels if ch.get('group') == group],
        key=lambda c: c['name'].lower(),
    )


def resolve_stream(channel):
    stream_url = channel.get('stream_url') or ''
    if _is_hls(stream_url):
        return stream_url
    return ''


def probe_stream(stream_url, referer):
    try:
        resp = _get(stream_url, headers=_stream_headers(referer), timeout=8)
        return int(resp.status_code)
    except Exception:
        return 599


def build_kodi_url(stream_url, referer):
    headers = {
        'User-Agent': BROWSER_UA,
        'Referer': referer or BASE_URL + '/',
    }
    sep = '&' if '|' in stream_url else '|'
    return stream_url + sep + urlencode(headers)


def build_plot(ch, epg):
    desc = ch.get('description') or ''
    if desc:
        return desc
    return ''


def build_label(ch, epg):
    return ch['name']


def _load_from_2ix2():
    posts_by_cat = _fetch_all_posts_parallel()
    channels = []
    for cat in CATEGORIES:
        for post in posts_by_cat.get(cat['category_id'], []):
            ch = _channel_from_post(post, cat)
            if ch:
                channels.append(ch)
    return _dedupe(channels)


def _fetch_all_posts_parallel():
    results = {}
    if _mq is not None:
        try:
            import threading
            lock = threading.Lock()

            def _fetch_one(cat):
                try:
                    posts = _get_posts_mq(cat['category_id'])
                    with lock:
                        results[cat['category_id']] = posts
                except Exception:
                    pass

            threads = [threading.Thread(target=_fetch_one, args=(cat,), daemon=True)
                       for cat in CATEGORIES]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=25)
            return results
        except Exception:
            pass

    for cat in CATEGORIES:
        try:
            results[cat['category_id']] = _get_posts_fallback(cat['category_id'])
        except Exception:
            pass
    return results


def _get_posts_mq(category_id):
    resp = _mq.get(
        POSTS_URL,
        params={
            'categories': category_id,
            'per_page': 100,
            '_fields': 'id,slug,link,title,content,excerpt,_links',
            '_embed': 'wp:featuredmedia',
        },
        headers=_api_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    return json.loads(resp.text) or []


def _get_posts_fallback(category_id):
    if _requests is None:
        return []
    resp = _requests.get(
        POSTS_URL,
        headers=_api_headers(),
        params={
            'categories': category_id,
            'per_page': 100,
            '_fields': 'id,slug,link,title,content,excerpt,_links',
            '_embed': 'wp:featuredmedia',
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json() or []


def _get(url, headers=None, timeout=10, stream=False):
    if _mq is not None:
        return _mq.get(url, headers=headers, timeout=timeout)
    if _requests is not None:
        return _requests.get(url, headers=headers, timeout=timeout, stream=stream)
    raise RuntimeError('Kein HTTP-Client verfügbar')


def _extract_logo(post):
    try:
        embedded = post.get('_embedded') or {}
        media_list = embedded.get('wp:featuredmedia') or []
        if media_list:
            src = (media_list[0].get('source_url')
                   or media_list[0].get('media_details', {}).get('source_url')
                   or '')
            if src:
                return src
    except Exception:
        pass
    rendered = post.get('content', {}).get('rendered') or ''
    m = re.search(r'<img[^>]+height="(?:125|160)px"[^>]+src="([^"]+)"', rendered, re.I)
    if not m:
        m = re.search(r'src="([^"]+)"[^>]+height="(?:125|160)px"', rendered, re.I)
    if m:
        return html.unescape(m.group(1))
    return ''


def _extract_description(post):
    excerpt = post.get('excerpt', {}).get('rendered') or ''
    if excerpt:
        text = html.unescape(re.sub(r'<[^>]+>', ' ', excerpt))
        text = ' '.join(text.split()).strip()
        if text and text != 'Weiterlesen':
            return text
    rendered = post.get('content', {}).get('rendered') or ''
    paras = re.findall(r'<p[^>]*>(.*?)</p>', rendered, re.I | re.S)
    for p in paras:
        text = html.unescape(re.sub(r'<[^>]+>', ' ', p))
        text = ' '.join(text.split()).strip()
        if len(text) > 80 and 'jwplayer' not in text and 'setup(' not in text:
            return text[:400]
    return ''


def _channel_from_post(post, cat):
    rendered = post.get('content', {}).get('rendered') or ''
    stream_url = _extract_hls(rendered)
    if not _is_hls(stream_url):
        return None
    post_id = str(post.get('id') or post.get('slug') or stream_url)
    title = post.get('title', {}).get('rendered') or post.get('slug') or ''
    logo = _extract_logo(post)
    description = _extract_description(post)
    return {
        'id': '%s:%s' % (cat['slug'], post_id),
        'name': _clean(title),
        'group': cat['label'],
        'category_slug': cat['slug'],
        'page_url': post.get('link') or BASE_URL,
        'stream_url': stream_url,
        'logo': logo,
        'description': description,
        'source': '2ix2',
    }


def _extract_hls(content):
    text = html.unescape(content or '').replace('\\/', '/')
    patterns = (
        r'\bfile\s*:\s*[\'"]([^\'"]+)[\'"]',
        r'[\'"]file[\'"]\s*:\s*[\'"]([^\'"]+)[\'"]',
        r'<source[^>]+src\s*=\s*[\'"]([^\'"]+)[\'"]',
        r'(https?://[^\s\'"<>]+?\.m3u8(?:\?[^\s\'"<>]+)?)',
    )
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m and _is_hls(m.group(1)):
            return html.unescape(m.group(1)).strip()
    return ''


def _is_hls(value):
    v = html.unescape(value or '').strip()
    if not v.lower().startswith(('http://', 'https://')):
        return False
    return '.m3u8' in v.lower()


def _usable(channels):
    return _dedupe([
        ch for ch in channels or []
        if _is_hls(ch.get('stream_url'))
    ])


def _dedupe(channels):
    seen = set()
    result = []
    for ch in channels:
        key = (ch.get('category_slug'), _norm(ch.get('name')))
        if key in seen:
            continue
        seen.add(key)
        result.append(ch)
    return result


def _b64(value):
    try:
        return base64.b64decode((value or '').encode('ascii')).decode('utf-8', 'replace')
    except Exception:
        return ''


def _clean(value):
    value = html.unescape(value or '')
    value = re.sub(r'<[^>]+>', ' ', value)
    return ' '.join(value.split()).strip()


def _norm(value):
    return re.sub(r'[^a-z0-9]+', '', (value or '').lower())


def _read_cache(path):
    try:
        if not os.path.exists(path):
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _write_cache(path, channels):
    try:
        d = os.path.dirname(path)
        if d and not os.path.exists(d):
            os.makedirs(d)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            json.dump({'timestamp': int(time.time()), 'channels': channels}, f,
                      ensure_ascii=False, separators=(',', ':'))
    except Exception:
        pass


def _api_headers():
    return {
        'User-Agent': BROWSER_UA,
        'Accept': 'application/json,text/html,*/*',
        'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.7,en;q=0.6',
        'Referer': BASE_URL + '/',
        'Connection': 'close',
    }


def _stream_headers(referer):
    return {
        'User-Agent': BROWSER_UA,
        'Accept': '*/*',
        'Accept-Encoding': 'identity',
        'Referer': referer or BASE_URL + '/',
        'Connection': 'close',
    }
