import re
import time
import random
import string
from urllib.parse import urlparse, urljoin
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
    'unpkg.com', 'jsdelivr.net', 'cdnjs.cloudflare.com', 'cdn.jsdelivr.net',
    'fonts.googleapis.com', 'fonts.gstatic.com',
)

_STATIC_EXTS = (
    '.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',
    '.woff', '.woff2', '.ttf', '.eot', '.ico',
)

_AD_DOMAINS = (
    'tagivi.com', 'popads.net', 'propellerads.com', 'adsterra.com',
    'onclickads.net', 'exoclick.com', 'juicyads.com', 'clickadu.com',
    'hilltopads.net', 'adcash.com', 'popcash.net', 'trafficjunky.net',
    'aarems.org', 'directyp.org', 'gzupload.com', 'demper.org',
    'interlinecustomroofingllc.com',
)

_STREAM_PATTERNS = [
    r'(https?://[^\s"\'<>\\]+\.m3u8(?:[^\s"\'<>\\]*)?)',
    r'(https?://[^\s"\'<>\\]+\.(?:mp4|mpd|webm|mkv)(?:[^\s"\'<>\\]*)?)',
    r'(?:file|wurl|hls|source)["\']?\s*[=:]\s*["\'](https?://[^\s"\'<>,\]\\]+)',
    r'<(?:source|video)[^>]*\bsrc=["\'](https?://[^"\']+)',
]


def _is_ad(u):
    u = (u or '').lower()
    return any(d in u for d in _AD_DOMAINS)


def _clean_html(html):
    html = re.sub(r'<!--.*?-->', '', html, flags=re.S)
    html = re.sub(r'<script\b[^>]*\bsrc\s*=[^>]*>\s*</script>', '', html, flags=re.S | re.I)
    return html.replace('\\/', '/')


def _prepare(html):
    html = _clean_html(html)
    if 'eval(function(p,a,c,k' in html:
        html = html + '\n' + _unpack_packer(html)
    return html


def _find_stream(text):
    for pat in _STREAM_PATTERNS:
        for m in re.finditer(pat, text):
            u = m.group(1).strip('"\'')
            if not u or not u.startswith('http'):
                continue
            low = u.lower()
            if _is_ad(low) or any(d in low for d in _SKIP_DOMAINS):
                continue
            u_clean = low.split('?')[0].split('#')[0]
            if any(u_clean.endswith(e) for e in _STATIC_EXTS):
                continue
            return u
    return None


def _origin(url):
    p = urlparse(url)
    return p.scheme + '://' + p.netloc + '/'


def _with_headers(stream, referer, ua=None):
    if '|' in stream:
        return stream
    return stream + '|Referer=' + referer + '&User-Agent=' + (ua or _MOB).replace(' ', '%20')


def _extract_iframes(html, base):
    out = []
    for m in re.finditer(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I):
        link = urljoin(base, m.group(1).strip())
        if link.startswith('http') and not _is_ad(link):
            out.append(link)
    return out


def _scan(url, referer, depth=0):
    html = _get(url, referer, ua=_UA)
    if not html:
        return None
    html = _prepare(html)
    su = _find_stream(html)
    if su:
        return su, url
    if depth < 2:
        for frame in _extract_iframes(html, url):
            found = _scan(frame, url, depth + 1)
            if found:
                return found
    return None


def _resolve_vidara(url):
    try:
        parsed   = urlparse(url)
        filecode = parsed.path.rstrip('/').split('/')[-1]
        domain   = parsed.netloc
        api_base = parsed.scheme + '://' + domain
        mm1      = domain in ('thebesthosterv.com', 'viewdara.com')
        api_url  = api_base + '/api/stream' + ('?mm1=' if mm1 else '')

        embed_url = api_base + '/e/' + filecode

        with multiquest.Session() as sess:
            sess.headers.update({
                'User-Agent':      _UA,
                'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
            })
            html = ''
            try:
                rg = sess.get(embed_url, headers={'Referer': api_base + '/'}, timeout=15)
                html = rg.text
            except Exception:
                log.error()

            try:
                rp = sess.post(
                    api_url,
                    headers={
                        'Content-Type': 'application/json',
                        'Referer':      embed_url,
                        'Origin':       api_base,
                    },
                    json={'filecode': filecode, 'device': 'android'},
                    timeout=10,
                )
                rp.raise_for_status()
                data = rp.json()
                su = (data.get('streaming_url') or data.get('sx') or
                      data.get('url') or data.get('stream') or
                      data.get('hls') or data.get('source') or '')
                if su and su.startswith('http'):
                    return su, True
            except Exception:
                log.error()

            if html:
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
                        return su + '|Referer=' + embed_url + '&User-Agent=' + _UA.replace(' ', '%20'), True

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

        with multiquest.Session() as sess:
            sess.headers.update({'User-Agent': _UA, 'Referer': 'https://%s/' % domain})
            r    = sess.get(url_d, timeout=15)
            html = r.text
            if not html:
                return url, False

            token   = re.search(r'\?token=([a-zA-Z0-9]+)&expiry=(\d+)', html)
            pass_md = re.search(r'(/pass_md5/[^\s"\'&?#]+)', html)
            if not (token and pass_md):
                return url, False

            base = sess.get(
                'https://%s%s' % (domain, pass_md.group(1)),
                headers={'Referer': url_d},
                timeout=15,
            ).text.strip()
            if not base:
                return url, False

            suffix = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            return '%s%s?token=%s&expiry=%s' % (
                base, suffix, token.group(1), token.group(2)), True
    except Exception:
        log.error()
    return url, False


def _resolve_generic(url):
    try:
        found = _scan(url, url)
        if found:
            su, page = found
            return _with_headers(su, _origin(page)), True
    except Exception:
        log.error()
    return url, False


def _aes_decrypt_hex(hex_str):
    raw = bytes.fromhex(hex_str.strip())
    try:
        from Cryptodome.Cipher import AES
    except Exception:
        from Crypto.Cipher import AES
    data = AES.new(b'kiemtienmua911ca', AES.MODE_CBC, b'1234567890oiuytr').decrypt(raw)
    pad = data[-1]
    if 0 < pad <= 16:
        data = data[:-pad]
    return data.decode('utf-8', 'ignore')


def _pick_stream(data):
    if isinstance(data, dict):
        for k in ('source', 'hls', 'cf', 'file', 'url', 'stream', 'streaming_url', 'sx'):
            v = data.get(k)
            if isinstance(v, str) and v.startswith('http') and not _is_ad(v):
                return v
        for v in data.values():
            r = _pick_stream(v)
            if r:
                return r
    elif isinstance(data, list):
        for v in data:
            r = _pick_stream(v)
            if r:
                return r
    return None


_XOR_KEY = 'G7#kP!2qZxV9mRwL'


def _xor_decode(token):
    import base64
    try:
        raw = base64.b64decode(token.split('~', 1)[1])
        out = bytes(c ^ ord(_XOR_KEY[i % len(_XOR_KEY)]) for i, c in enumerate(raw))
        return out.decode('utf-8', 'ignore')
    except Exception:
        return ''


def _resolve_gupload(url):
    import json as _json
    try:
        p = urlparse(url)
        base = p.scheme + '://' + p.netloc
        code = p.path.rstrip('/').split('/')[-1]
        candidates = [base + '/e/' + code, url]
        for page in candidates:
            html = _get(page, 'https://moflix-stream.xyz/', ua=_UA)
            if not html:
                continue
            html = html.replace('\\/', '/')
            for tok in re.findall(r'[0-9a-f]{8}~[A-Za-z0-9+/=]{16,}', html):
                txt = _xor_decode(tok)
                if not txt.startswith('{') or 'videoUrl' not in txt:
                    continue
                try:
                    su = _json.loads(txt).get('videoUrl') or ''
                except Exception:
                    su = ''
                if su.startswith('//'):
                    su = 'https:' + su
                if su.startswith('http') and not _is_ad(su):
                    return _with_headers(su, base + '/'), True
        return _with_headers('%s/data/e/hls/%s/720p.m3u8' % (base, code), base + '/'), True
    except Exception:
        log.error()
    return url, False


_MOFLIX_HOSTS = ('gupload.', 'moflix-stream.', 'moflix.upns.', 'moflix.rpmplay.', 'upns.xyz', 'rpmplay.')


def _resolve_moflix(url):
    import json as _json
    try:
        p = urlparse(url)
        base = p.scheme + '://' + p.netloc
        code = (p.fragment or p.path.rstrip('/').split('/')[-1]).split('&')[0]
        found = _scan(url, 'https://moflix-stream.xyz/')
        if found:
            su, page = found
            return _with_headers(su, base + '/'), True
        if code:
            api = '%s/api/v1/video?id=%s&w=1920&h=1080&r=moflix-stream.xyz' % (base, code)
            txt = (_get(api, url, ua=_UA) or '').strip()
            if txt:
                if not txt.startswith('{') and not txt.startswith('['):
                    txt = _aes_decrypt_hex(txt)
                su = _pick_stream(_json.loads(txt))
                if su:
                    return _with_headers(su, base + '/'), True
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


_DIRECT_EXTS = ('.mp4', '.mkv', '.m3u8', '.ts', '.avi', '.mov', '.mpd')

def _resolve_core(url):
    try:
        u = url.lower()
        p = u.split('?')[0]
        if any(p.endswith(e) for e in _DIRECT_EXTS):
            return url, True
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
        if 'gupload.' in u:
            return _resolve_gupload(url)
        if any(h in u for h in _MOFLIX_HOSTS):
            return _resolve_moflix(url)
        return _resolve_generic(url)
    except Exception:
        log.error()
    return url, False


def resolve(url):
    su, ok = _resolve_core(url)
    if ok and _is_ad(su.split('|')[0]):
        return url, False
    return su, ok


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
