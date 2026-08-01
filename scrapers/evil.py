import re
import time
import random
import string
from urllib.parse import urlparse
from resources.lib import multiquest, log

_UA  = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
_MOB = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/30.0 Chrome/143.0.0.0 Mobile Safari/537.36'


def _get(url, referer=None, ua=None):
    h = {'User-Agent': ua or _MOB}
    if referer:
        h['Referer'] = referer
    try:
        r = multiquest.get(url, headers=h, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception:
        log.error()
        return ''


def _unpack_packer(html):
    m = re.search(r"}\('(.+)',(\d+),(\d+),'(.+)'\.split\('\|'\)", html, re.S)
    if not m:
        return html
    p, a, c, k = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4).split('|')
    _ch = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    def _b(n):
        return _ch[n] if n < a else _b(n // a) + _ch[n % a]
    for i in range(c - 1, -1, -1):
        if k[i]:
            p = re.sub(r'\b' + _b(i) + r'\b', k[i], p)
    return p


def _unpack_js(packed):
    m = re.search(
        r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\('(.*?)',\s*(\d+),\s*(\d+),\s*'(.*)'\s*\.split\('\|'\)\)\)",
        packed, re.S)
    if not m:
        return ''
    p_val, a_val, k_str = m.group(1), int(m.group(2)), m.group(4)
    k = k_str.split('|')
    chars = '0123456789abcdefghijklmnopqrstuvwxyz'
    def to_int(s, base):
        r = 0
        for ch in s:
            r = r * base + chars.index(ch)
        return r
    def replace_word(match):
        w = match.group(0)
        try:
            idx = to_int(w, a_val)
            return k[idx] if idx < len(k) and k[idx] else w
        except Exception:
            return w
    return re.sub(r'\b\w+\b', replace_word, p_val)


_SKIP_DOMAINS = (
    'googletagmanager.com', 'google-analytics.com', 'googlesyndication.com',
    'doubleclick.net', 'googleapis.com', 'gstatic.com',
    'facebook.com', 'twitter.com', 'instagram.com',
)

_STREAM_PATTERNS = [
    r'(https?://[^\s"\'<>]+\.m3u8(?:[^\s"\'<>]*)?)',
    r'(?:file|wurl|src|source)\s*[=:]\s*["\']?(https?://[^\s"\'<>,\]]+)',
    r'(https?://[^\s"\'<>]+\.mp4(?:[^\s"\'<>]*)?)',
]


def _find_stream(text):
    for pat in _STREAM_PATTERNS:
        m = re.search(pat, text)
        if m:
            u = (m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)).strip('"\'')
            if u and u.startswith('http') and not any(d in u.lower() for d in _SKIP_DOMAINS):
                return u
    return None


def _resolve_vidara(url):
    try:
        parsed   = urlparse(url)
        filecode = parsed.path.rstrip('/').split('/')[-1]
        domain   = parsed.netloc
        api_base = parsed.scheme + '://' + domain
        mm1      = domain in ('thebesthosterv.com', 'viewdara.com')
        api_url  = api_base + '/api/stream' + ('?mm1=' if mm1 else '')
        r = multiquest.post(
            api_url,
            headers={
                'User-Agent':   _UA,
                'Content-Type': 'application/json',
                'Referer':      url,
                'Origin':       api_base,
            },
            json={'filecode': filecode, 'device': 'android'},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        su = data.get('streaming_url') or data.get('sx') or data.get('url') or data.get('stream') or ''
        if su and su.startswith('http'):
            return su, True
    except Exception:
        log.error()
    return url, False


def _resolve_vidsonic(url):
    try:
        html = _get(url, url)
        if not html:
            return url, False
        m = re.search(r"sources\s*:\s*\[\s*\{[^}]*file\s*:\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]", html, re.I)
        if m:
            return m.group(1), True
        m = re.search(r"file\s*:\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]", html, re.I)
        if m:
            return m.group(1), True
        m = re.search(r'["\']((?:https?:)?//[^"\']+\.m3u8[^"\']*)["\']', html)
        if m:
            su = m.group(1)
            if su.startswith('//'):
                su = 'https:' + su
            return su, True
    except Exception:
        log.error()
    return url, False


def _resolve_dr0pstream(url):
    try:
        html = _get(url, url)
        if not html:
            return url, False
        if 'eval(function(p,a,c,k' in html:
            html = _unpack_packer(html)
        m = re.search(r"file\s*:\s*[\"']((?:https?:)?//[^\"']+\.m3u8[^\"']*)[\"']", html, re.I)
        if m:
            stream = m.group(1)
            if stream.startswith('//'):
                stream = 'https:' + stream
            return stream + '|Referer=https://dr0pstream.com/&User-Agent=' + _MOB.replace(' ', '%20'), True
    except Exception:
        log.error()
    return url, False


def _resolve_supervideo(url):
    try:
        html = _get(url, 'https://supervideo.cc/')
        if not html:
            return url, False
        if 'eval(function(p,a,c,k' in html:
            html = _unpack_packer(html)
        m = re.search(r"file\s*:\s*[\"']((?:https?:)?//[^\"']+\.m3u8[^\"']*)[\"']", html, re.I)
        if m:
            stream = m.group(1)
            if stream.startswith('//'):
                stream = 'https:' + stream
            return stream + '|Referer=https://supervideo.cc/&User-Agent=' + _MOB.replace(' ', '%20'), True
    except Exception:
        log.error()
    return url, False


def _resolve_mixdrop(url):
    try:
        html = _get(url, url)
        if not html:
            return url, False
        if 'eval(function(p,a,c,k' in html:
            html = _unpack_packer(html)
        m = re.search(r'MDCore\.wurl\s*=\s*"([^"]+)"', html)
        if m:
            stream = m.group(1)
            if stream.startswith('//'):
                stream = 'https:' + stream
            return stream + '|Referer=%s&User-Agent=%s' % (url, _MOB.replace(' ', '%20')), True
        m = re.search(r'["\']((?:https?:)?//[^"\']+\.m3u8[^"\']*)["\']', html)
        if m:
            stream = m.group(1)
            if stream.startswith('//'):
                stream = 'https:' + stream
            return stream + '|Referer=%s&User-Agent=%s' % (url, _MOB.replace(' ', '%20')), True
    except Exception:
        log.error()
    return url, False


def _resolve_meinecloud(url):
    try:
        html = _get(url, 'https://meinecloud.click/')
        if not html:
            return url, False
        html = re.sub(r'<!--.*?-->', '', html, flags=re.S)
        for link in re.findall(r'data-link="([^"]+)', html):
            if not link.startswith('http'):
                link = 'https:' + link
            if 'youtube' in link or 'meinecloud' in link:
                continue
            return link, False
        for attr in ('file', 'src', 'source'):
            m = re.search(r'["\']%s["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']' % attr, html, re.I)
            if m:
                stream = m.group(1)
                if stream.startswith('//'):
                    stream = 'https:' + stream
                return stream, True
        iframe = re.search(r'<iframe[^>]*src=["\']([^"\']+)["\']', html, re.I)
        if iframe:
            iframe_url = iframe.group(1)
            if not iframe_url.startswith('http'):
                iframe_url = 'https:' + iframe_url
            if 'meinecloud' not in iframe_url:
                return iframe_url, False
            html2 = _get(iframe_url, url)
            if html2:
                html2 = re.sub(r'<!--.*?-->', '', html2, flags=re.S)
                for link in re.findall(r'data-link="([^"]+)', html2):
                    if not link.startswith('http'):
                        link = 'https:' + link
                    if 'youtube' in link or 'meinecloud' in link:
                        continue
                    return link, False
                for attr in ('file', 'src', 'source'):
                    m = re.search(r'["\']%s["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']' % attr, html2, re.I)
                    if m:
                        stream = m.group(1)
                        if stream.startswith('//'):
                            stream = 'https:' + stream
                        return stream, True
    except Exception:
        log.error()
    return url, False


def _resolve_kinoger_pw(url):
    m = re.search(r'/e/([^/?&#]+)', url)
    if not m:
        return url, False
    filecode = m.group(1)
    try:
        with multiquest.Session(headers={'User-Agent': _MOB}) as sess:
            sess.get(url, headers={'Referer': 'https://kinoger.pw/'}, timeout=10)
            r = sess.post(
                'https://kinoger.pw/api/stream',
                json={'filecode': filecode, 'device': 'android'},
                headers={'Referer': url, 'Origin': 'https://kinoger.pw'},
                timeout=10,
            )
            r.raise_for_status()
            su = r.json().get('streaming_url') or ''
            if su:
                return su, True
    except Exception:
        log.error()
    return url, False


def _resolve_fsst(url):
    incvideo_url = url.replace('fsst.online', 'incvideo1.online')
    try:
        html = _get(incvideo_url, url, ua=_UA)
        if not html:
            return url, False
        m = re.search(r"file\s*:\s*[\"']([^\"']+)[\"']", html)
        if not m:
            return url, False
        raw = m.group(1)
        quality_map = {}
        for part in raw.split(','):
            part = part.strip()
            qm = re.match(r'\[([^\]]+)\](https?://\S+)', part)
            if qm:
                quality_map[qm.group(1).lower()] = qm.group(2)
            elif re.match(r'https?://', part):
                quality_map['default'] = part
        if not quality_map:
            return url, False
        for label in ('1080p', '720p', '480p', '360p', 'default'):
            if label in quality_map:
                return quality_map[label], True
        return next(iter(quality_map.values())), True
    except Exception:
        log.error()
    return url, False


def _resolve_kinoger_be(url):
    try:
        html = _get(url, url, ua=_UA)
        if not html:
            return url, False
        decoded = _unpack_js(html) or html
        urls = re.findall(r'(https?://[^\s"\'\\]+\.m3u8[^\s"\'\\]*)', decoded)
        if urls:
            return urls[0], True
        rel = re.search(r'["\']([/][^\s"\'\\]+\.m3u8[^\s"\'\\]*)["\']', decoded)
        if rel:
            return 'https://kinoger.be' + rel.group(1), True
    except Exception:
        log.error()
    return url, False


def _resolve_playmate(url):
    try:
        parsed   = urlparse(url)
        filecode = parsed.path.rstrip('/').split('/')[-1]
        api_base = parsed.scheme + '://' + parsed.netloc
        r = multiquest.post(
            api_base + '/api/s?1=',
            headers={
                'User-Agent':   _UA,
                'Content-Type': 'application/json',
                'Origin':       api_base,
                'Referer':      url,
            },
            json={'c': filecode, 'd': 'android'},
            timeout=10,
        )
        r.raise_for_status()
        su = r.json().get('sx') or ''
        if su and su.startswith('http'):
            return su, True
    except Exception:
        log.error()
    return url, False


def _resolve_dood(url):
    try:
        m_dom  = re.search(r'https?://([^/]+)', url)
        domain = m_dom.group(1) if m_dom else 'dood.to'
        url_d  = re.sub(r'/(e|f)/', '/d/', url)
        html   = _get(url_d, 'https://%s/' % domain, ua=_UA)
        if not html:
            return url, False
        token   = re.search(r'\?token=([a-zA-Z0-9]+)&expiry=', html)
        pass_md = re.search(r'(/pass_md5/[^\s"\'&?#]+)', html)
        if token and pass_md:
            base = _get('https://%s%s' % (domain, pass_md.group(1)), url_d, ua=_UA).strip()
            if base:
                suffix = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                return '%s%s?token=%s&expiry=%d' % (
                    base, suffix, token.group(1), int(time.time() * 1000)), True
    except Exception:
        log.error()
    return url, False


def _resolve_generic(url):
    try:
        html = _get(url, url)
        if not html:
            return url, False
        html = re.sub(r'<!--.*?-->', '', html, flags=re.S)
        if 'eval(function(p,a,c,k' in html:
            html = _unpack_packer(html)
        su = _find_stream(html)
        if su:
            return su, True
    except Exception:
        log.error()
    return url, False


def _resolve_bsto(url):
    import json as _json
    from resources.lib.captcha.captcha_helper import solve_recaptcha, extract_recaptcha_sitekey

    base = 'https://burningseries.ac'
    try:
        sess = multiquest.Session(headers={
            'User-Agent':      _UA,
            'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
            'Referer':         base,
        })
        r         = sess.get(url, timeout=10)
        html      = r.text
        final_url = r.url or url
    except Exception:
        log.error()
        return url, False

    sitekey = extract_recaptcha_sitekey(html)
    if not sitekey:
        return url, False

    try:
        captcha_token = solve_recaptcha(sitekey, final_url)
    except Exception:
        log.error()
        captcha_token = ''

    lid_m   = re.search(r'data-lid=["\']([^"\']+)["\']', html)
    token_m = re.search(r'security_token["\']?\s+content=["\']([^"\']+)["\']', html, re.I)

    if not lid_m or not token_m:
        sess.close()
        return url, False

    try:
        resp = sess.post(
            base + '/ajax/embed.php',
            data={
                'token':  token_m.group(1),
                'LID':    lid_m.group(1),
                'ticket': captcha_token or '',
            },
            headers={
                'Accept':           'application/json, text/javascript, */*; q=0.01',
                'Content-Type':     'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
                'Origin':           base,
                'Referer':          final_url,
            },
        )
        link = _json.loads(resp.text).get('link', '')
        if link:
            try:
                import resolveurl
                hmf = resolveurl.HostedMediaFile(url=link)
                if hmf.valid_url():
                    stream = hmf.resolve()
                    if stream:
                        return stream, True
            except Exception:
                log.error()
            stream_url, ok = resolve(link)
            if ok and stream_url:
                return stream_url, True
            return link, True
    except Exception:
        log.error()
    finally:
        sess.close()

    return url, False


def _resolve_vidmoly(url):
    try:
        m = re.search(r'vidmoly\.me/(?:w|e)/([a-zA-Z0-9]+)', url)
        if not m:
            return url, False
        code = m.group(1)
        embed = 'https://vidmoly.me/embed-%s.html' % code
        html = _get(embed, 'https://vidmoly.me/')
        if not html:
            return url, False
        if 'eval(function(p,a,c,k' in html:
            html = _unpack_packer(html)
        for pat in (
            r'sources\s*:\s*\[\s*\{[^}]*file\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
            r'["\']file["\']\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
            r'["\']((?:https?:)?//[^"\']+\.m3u8[^"\']*)["\']',
        ):
            mm = re.search(pat, html, re.I)
            if mm:
                su = mm.group(1)
                if su.startswith('//'):
                    su = 'https:' + su
                return su + '|Referer=https://vidmoly.me/&User-Agent=' + _MOB.replace(' ', '%20'), True
    except Exception:
        log.error()
    return url, False


_VIDARA_HOSTS  = ('vidara.', 'vidaraa.', 'vidsonic.', 'vidmatrixa.', 'viewdara.', 'thebesthosterv.')
_DOOD_HOSTS    = ('dood.', 'doodstream.')


def resolve(url):
    try:
        u = url.lower()
        if 'burningseries.ac' in u:
            return _resolve_bsto(url)
        if any(h in u for h in _VIDARA_HOSTS):
            return _resolve_vidara(url)
        if 'vidsonic.' in u:
            return _resolve_vidsonic(url)
        if 'dr0pstream.' in u:
            return _resolve_dr0pstream(url)
        if 'supervideo.' in u:
            return _resolve_supervideo(url)
        if 'mixdrop.' in u:
            return _resolve_mixdrop(url)
        if 'meinecloud.' in u:
            return _resolve_meinecloud(url)
        if 'kinoger.pw' in u:
            return _resolve_kinoger_pw(url)
        if 'fsst.online' in u:
            return _resolve_fsst(url)
        if 'kinoger.be' in u:
            return _resolve_kinoger_be(url)
        if 'playmate.' in u:
            return _resolve_playmate(url)
        if any(h in u for h in _DOOD_HOSTS):
            return _resolve_dood(url)
        if 'vidmoly.' in u:
            return _resolve_vidmoly(url)
        return _resolve_generic(url)
    except Exception:
        log.error()
    return url, False


_TRIGGER = 'meinecloud.click'

_SKIP = re.compile(
    r'/vod/vpn|youtube\.com|embed-\.html|/e/\s*$|/e/\s*"|'
    r'mixdrop\.co/e/\s*$|supervideo\.cc/embed-s\.html$',
    re.I
)


def is_cloud_url(url):
    return _TRIGGER in url


def _normalise_link(link):
    link = link.strip()
    if link.startswith('//'):
        link = 'https:' + link
    return link


def _quality_from_text(text):
    t = text.upper()
    if '2160' in t or '4K' in t:
        return '4K'
    if '1080' in t:
        return '1080p'
    if '720' in t:
        return '720p'
    return 'HD'


def _hosters_from_section(section):
    result = []
    seen   = set()
    for full_li in re.findall(r'<li[^>]*(?:data-link="[^"]*")?[^>]*>.*?</li>', section, re.S | re.I):
        m = re.search(r'data-link="([^"]+)"', full_li)
        if not m:
            continue
        raw = m.group(1)
        if _SKIP.search(raw):
            continue
        if raw in seen:
            continue
        seen.add(raw)
        link  = _normalise_link(raw)
        body  = re.sub(r'<[^>]+>', '', full_li)
        label = re.sub(r'\s+', ' ', body).strip() or 'Hoster'
        qual  = _quality_from_text(label)
        result.append((label, link, qual))
    return result


def _resolve_sirius(hurl):
    html = _get(hurl, ua=_UA)
    if not html:
        return []
    html = re.sub(r'<!--.*?-->', '', html, flags=re.S)
    return _hosters_from_section(html)


def _sid_for_season(html, season):
    for sid, label in re.findall(r'data-season="(\d+)"[^>]*>\s*(S\d+)\s*<', html):
        m = re.match(r'S(\d+)', label.strip())
        if m and int(m.group(1)) == season:
            return sid
    return None


def _episode_hosters_new(html, season, episode):
    sid = _sid_for_season(html, season)
    if not sid:
        return []
    bm = re.search(
        r'class="[^"]*_season-eps[^"]*"[^>]*data-season="%s"[^>]*>(.*?)(?=<div[^>]*class="[^"]*_season-eps|$)' % sid,
        html, re.S
    )
    if not bm:
        return []
    block   = bm.group(1)
    ep_divs = re.split(r'(?=<div[^>]*class="[^"]*\b_ep\b[^"]*"[^>]*data-link=)', block)
    for ep in ep_divs:
        n_m = re.search(r'class="[^"]*_ep-n[^"]*">\s*(\d+)\s*<', ep)
        if not n_m or int(n_m.group(1)) != episode:
            continue
        link_m  = re.search(r'data-link="([^"]+)"', ep)
        if not link_m:
            continue
        label_m = re.search(r'data-label="([^"]+)"', ep)
        raw     = link_m.group(1).strip()
        link    = ('https:' + raw) if raw.startswith('//') else raw
        label   = label_m.group(1) if label_m else ('S%d E%d' % (season, episode))
        return [(label, link, 'HD')]
    return []


def _episode_hosters_legacy(html, season, episode):
    pat = r'id="serie-%d_%d"(.*?)(?=<li\s+id="serie-\d|$)' % (season, episode)
    m   = re.search(pat, html, re.S)
    if not m:
        m = re.search(r'id="serie-1_%d"(.*?)(?=<li\s+id="serie-1_\d|$)' % episode, html, re.S)
    if not m:
        return []
    return _hosters_from_section(m.group(1))


def _episode_hosters_from_html(html, season, episode):
    result = _episode_hosters_new(html, season, episode)
    if not result:
        result = _episode_hosters_legacy(html, season, episode)
    return result


def _cloud_expand(raw_list):
    result = []
    for name, hurl, quality in raw_list:
        if _TRIGGER in hurl:
            for sub_name, sub_url, sub_qual in _resolve_sirius(hurl):
                result.append((sub_name, sub_url, False))
        else:
            result.append((name, hurl, False))
    return result


def get_movie(imdb_id):
    html = _get('https://meinecloud.click/movie/%s' % imdb_id, ua=_UA)
    if not html:
        return []
    return _cloud_expand(_hosters_from_section(html))


def get_episode(imdb_id, season, episode):
    imdb_num = re.sub(r'[^0-9]', '', str(imdb_id))
    html     = _get('https://meinecloud.click/serial/%s' % imdb_num, ua=_UA)
    raw      = _episode_hosters_from_html(html, season, episode)
    if not raw:
        html = _get('https://meinecloud.click/serial/%s' % imdb_id, ua=_UA)
        raw  = _episode_hosters_from_html(html, season, episode)
    return _cloud_expand(raw)


def resolve_page(url, referer=None):
    return _resolve_sirius(url)
