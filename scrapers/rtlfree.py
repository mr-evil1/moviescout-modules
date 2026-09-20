import hashlib
import hmac as _hmac
import json
import os
import re
import time
import urllib.parse
import uuid
import xbmc
import xbmcaddon
import xbmcgui
from resources.lib import multiquest

SITE_ID       = 'rtlfree'
SITE_NAME     = 'RTL+ Free'
SITE_DOMAIN   = 'plus.rtl.de'
TYPE          = 'both'
GLOBAL_SEARCH = True

try:
    _ICON = xbmcaddon.Addon().getAddonInfo('icon')
except Exception:
    _ICON = ''

_UA             = ('Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) SamsungBrowser/29.0 Chrome/136.0.0.0 Mobile Safari/537.36')
_CLIENT_RELEASE = '6.50.3'
_RTL_WEB        = 'https://plus.rtl.de'
_LAYOUT_BASE    = 'https://layout.rtlde.bedrock.tech/front/v1/rtlde/m6group_web/main/token-web-31'
_FRONT_AUTH_URL = 'https://front-auth.rtlde.bedrock.tech/v2/rtlde/platforms/m6group_web/token'
_ANON_OIDC_URL  = 'https://auth.rtl.de/auth/realms/rtlplus/protocol/openid-connect/token'
_ANON_CLIENT_ID     = 'anonymous-user'
_ANON_CLIENT_SECRET = '4bfeb73f-1c4a-4e9f-a7fa-96aa1ad3d94c'
_IMAGE_BASE     = 'https://images-fio.rtlde.bedrock.tech'
_IMAGE_KEY      = 'x9vGg4RNeNBqV2nBfhqLV6cN4n'
_AUTH_TOKEN_STATIC = 'c0b0575f16b596d7d24b05987bbca51453f6afb0'
_FREE_FOLDER_ID = '193'
_PLUGIN_RTL     = 'plugin://plugin.video.rtlplus/'
_PAGE_SIZE      = 50
_LAYOUT_PAGES   = 2
_BLOCK_PAGES    = 3
_FALLBACK_PAGES = (3, 2, 1)
_LIVE_TYPES     = ('live', 'livetv', 'channel', 'event', 'live_event', 'event_stream')


def log_error(msg=''):
    import traceback
    xbmc.log('[RTL+Free] ERROR: %s\n%s' % (msg, traceback.format_exc()), xbmc.LOGERROR)


def _log_http(tag, status, body):
    snippet = str(body or '')[:300].replace('\n', ' ')
    xbmc.log('[RTL+Free] %s HTTP %d: %s' % (tag, status, snippet), xbmc.LOGWARNING)


def _clean_html(raw):
    if not raw:
        return ''
    return re.sub(r'<[^>]+>', '', str(raw)).strip()


def _exc_result(exc):
    code = getattr(exc, 'code', 0) or 0
    body = ''
    try:
        body = exc.read().decode('utf-8', 'ignore')
    except Exception:
        pass
    if not code:
        xbmc.log('[RTL+Free] %s: %s' % (type(exc).__name__, exc), xbmc.LOGWARNING)
    return body, code


def _http_get(url, headers, params=None, timeout=15):
    try:
        r = multiquest.get(url, params=params, headers=headers, timeout=timeout)
        return r.text, r.status_code
    except Exception as e:
        return _exc_result(e)


def _http_post(url, form_data, headers, timeout=15):
    try:
        r = multiquest.post(url, data=form_data, headers=headers, timeout=timeout)
        return r.text, r.status_code
    except Exception as e:
        return _exc_result(e)


_TOKEN_CACHE = {}


def _anon_oidc():
    body, status = _http_post(
        _ANON_OIDC_URL,
        {
            'client_id':     _ANON_CLIENT_ID,
            'client_secret': _ANON_CLIENT_SECRET,
            'grant_type':    'client_credentials',
        },
        {
            'User-Agent': _UA,
            'Origin':     _RTL_WEB,
            'Referer':    _RTL_WEB + '/',
            'Accept':     '*/*',
        }
    )
    if not body or status >= 400:
        _log_http('oidc', status, body)
        return ''
    try:
        token = json.loads(body).get('access_token', '')
    except Exception as e:
        log_error(str(e))
        return ''
    if not token:
        _log_http('oidc ohne access_token', status, body)
    return token


def _get_device_id():
    try:
        import xbmcvfs
        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
        path = os.path.join(profile, 'rtlfree_device.json')
        if os.path.isfile(path):
            with open(path, 'r') as f:
                did = json.load(f).get('device_id', '')
            if did:
                return did
        did = '_luid_' + str(uuid.uuid4())
        os.makedirs(profile, exist_ok=True)
        with open(path, 'w') as f:
            json.dump({'device_id': did}, f)
        return did
    except Exception:
        return '_luid_' + str(uuid.uuid4())


def _guest_headers(oidc, ts, auth_tok):
    return {
        'Authorization':                    'Bearer %s' % oidc,
        'x-auth-device-name':               'Android - Samsung Internet',
        'x-auth-token-timestamp':           str(ts),
        'x-auth-token':                     auth_tok,
        'x-auth-device-id':                 _get_device_id(),
        'x-auth-device-player-size-width':  '384',
        'x-auth-device-player-size-height': '682',
        'x-client-release':                 _CLIENT_RELEASE,
        'x-customer-name':                  'rtlde',
        'request-timeout':                  '10000',
        'User-Agent':                       _UA,
        'Origin':                           _RTL_WEB,
        'Referer':                          _RTL_WEB + '/',
        'Accept':                           '*/*',
        'Accept-Language':                  'de-DE,de;q=0.9',
    }


def _bedrock_guest_token(oidc):
    if not oidc:
        return ''
    ts       = int(time.time())
    computed = _hmac.new(b'', str(ts).encode(), hashlib.sha1).hexdigest()
    body, status = '', 0
    for auth_tok in (_AUTH_TOKEN_STATIC, computed):
        body, status = _http_get(_FRONT_AUTH_URL, _guest_headers(oidc, ts, auth_tok))
        if body and status < 400:
            break
        _log_http('guest-token', status, body)
    if not body or status >= 400:
        return ''
    try:
        token = json.loads(body).get('token', '')
    except Exception as e:
        log_error(str(e))
        return ''
    if not token:
        _log_http('guest-token ohne token', status, body)
    return token


def _get_tokens():
    now = time.time()
    oidc = _TOKEN_CACHE.get('oidc', '')
    if not oidc or _TOKEN_CACHE.get('oidc_exp', 0) < now + 300:
        oidc = _anon_oidc()
        if oidc:
            _TOKEN_CACHE['oidc'] = oidc
            _TOKEN_CACHE['oidc_exp'] = now + 3600
    bedrock = _TOKEN_CACHE.get('bedrock', '')
    if not bedrock or _TOKEN_CACHE.get('bedrock_exp', 0) < now + 300:
        bedrock = _bedrock_guest_token(oidc)
        if bedrock:
            _TOKEN_CACHE['bedrock'] = bedrock
            _TOKEN_CACHE['bedrock_exp'] = now + 86000
    return oidc, bedrock


def _api_headers(oidc, bedrock, x_location=None):
    h = {
        'User-Agent':       _UA,
        'Accept':           '*/*',
        'Origin':           _RTL_WEB,
        'Referer':          _RTL_WEB + '/',
        'x-client-release': _CLIENT_RELEASE,
        'x-customer-name':  'rtlde',
        'request-timeout':  '10000',
        'Accept-Language':  'de-DE,de;q=0.9',
    }
    if oidc:
        h['Authorization'] = 'Bearer %s' % oidc
    if bedrock:
        h['x-bedrock-token'] = bedrock
    if x_location:
        h['x-location'] = x_location
    return h


def _page_steps(params):
    try:
        nb = int(params.get('nbPages') or 0)
    except (TypeError, ValueError):
        nb = 0
    if not nb:
        return [None]
    return [nb] + [n for n in _FALLBACK_PAGES if n < nb]


def _api_get(path, params=None, x_location=None):
    oidc, bedrock = _get_tokens()
    if not bedrock:
        xbmc.log('[RTL+Free] kein Bedrock-Token erhalten', xbmc.LOGWARNING)
    url = _LAYOUT_BASE + path
    query = dict(params or {})
    attempts = [(nb, x_location) for nb in _page_steps(query)]
    if x_location:
        attempts.append((attempts[0][0], None))
    body, status = '', 0
    for i, (nb, xloc) in enumerate(attempts):
        if nb is not None:
            query['nbPages'] = nb
        body, status = _http_get(url, _api_headers(oidc, bedrock, xloc), query)
        if status != 400 or not bedrock or i == len(attempts) - 1:
            break
        _log_http('%s nbPages=%s xloc=%s' % (path, nb, bool(xloc)), status, body)
    if not body or status >= 400:
        _log_http(path, status, body)
        return None
    try:
        return json.loads(body)
    except Exception as e:
        log_error(str(e))
    return None


def _block_title(block):
    bc     = block.get('content') or {}
    bt_obj = bc.get('title') or {}
    if isinstance(bt_obj, dict):
        return bt_obj.get('short') or bt_obj.get('long') or ''
    return str(bt_obj)


def _expand_blocks(entity_path, data, x_location=None, select=None, max_rounds=8):
    if not isinstance(data, dict):
        return data
    for block in data.get('blocks', []):
        if select is not None and not select(block):
            continue
        bc       = block.get('content') or {}
        block_id = block.get('id')
        page     = (bc.get('pagination') or {}).get('nextPage')
        rounds   = 0
        while page and block_id and rounds < max_rounds:
            more = _api_get('%s/block/%s' % (entity_path, block_id),
                            {'nbPages': _BLOCK_PAGES, 'page': page},
                            x_location=x_location)
            if not isinstance(more, dict):
                break
            mc = more.get('content') or {}
            bc.setdefault('items', []).extend(mc.get('items') or [])
            page = (mc.get('pagination') or {}).get('nextPage')
            rounds += 1
    return data


def _layout_all(path, x_location=None, max_block_pages=5):
    data = _api_get(path, {'blockPage': 1, 'nbPages': _LAYOUT_PAGES}, x_location=x_location)
    if not isinstance(data, dict):
        return None
    page  = (data.get('pagination') or {}).get('nextPage')
    count = 1
    while page and count < max_block_pages:
        more = _api_get(path, {'blockPage': page, 'nbPages': _LAYOUT_PAGES}, x_location=x_location)
        if not isinstance(more, dict):
            break
        data.setdefault('blocks', []).extend(more.get('blocks') or [])
        page   = (more.get('pagination') or {}).get('nextPage')
        count += 1
    return _expand_blocks(path[:-len('/layout')], data, x_location)


def _image_url(img, w=320, h=180, ratio='16:9'):
    if not img or not isinstance(img, dict):
        return _ICON
    ids = img.get('idsByRatio') or {}
    img_id = (ids.get(ratio) or ids.get('16:9') or ids.get('2:3')
              or next(iter(ids.values()), ''))
    if not img_id:
        return _ICON
    pq = '/v2/images/%s/raw?auto=webp&blur=0&fit=max&width=%d&height=%d&interlace=1&quality=65' % (img_id, w, h)
    sig = hashlib.sha1((pq + _IMAGE_KEY).encode()).hexdigest()
    return '%s%s&hash=%s' % (_IMAGE_BASE, pq, sig)


def _resolve_target(target):
    if not isinstance(target, dict):
        return {}
    depth = 0
    while target.get('type') == 'lock' and depth < 5:
        inner = (target.get('value_lock') or {}).get('originalTarget') or {}
        if not inner or inner is target:
            break
        target = inner
        depth += 1
    return target


def _build_title(ic):
    t = str(ic.get('title') or '')
    e = str(ic.get('extraTitle') or '')
    if t and e:
        return '%s - %s' % (t, e)
    h = str(ic.get('highlight') or '')
    return t or e or h.split('•')[0].strip() or 'Unbekannt'


def _is_movie_item(ic):
    return (ic.get('extraDetails') or '').lower().startswith('film')


def _year_from_ic(ic):
    for key in ('highlight', 'description', 'subTitle'):
        m = re.search(r'\b(19|20)\d{2}\b', str(ic.get(key) or ''))
        if m:
            return m.group(0)
    return ''


_RE_DATE   = re.compile(r'^(?:[^\d,]{1,4},\s*)?(\d{1,2}\.\d{1,2}\.\d{4})$')
_RE_MONTH  = re.compile(r'^\d{4}-\d{2}$')
_RE_SEASON = re.compile(r'^Staffel\s+(\d+)$', re.I)
_RE_FOLGE  = re.compile(r'^Folge\s+(\d+)$', re.I)


def _episode_info(ic):
    text = str(ic.get('highlight') or ic.get('description') or '')
    info = {'date': '', 'season': 0, 'episode': 0, 'name': ''}
    for part in [p.strip() for p in text.split('\u2022')]:
        if not part or _RE_MONTH.match(part):
            continue
        m = _RE_DATE.match(part)
        if m:
            info['date'] = m.group(1)
            continue
        m = _RE_SEASON.match(part)
        if m:
            info['season'] = int(m.group(1))
            continue
        m = _RE_FOLGE.match(part)
        if m:
            info['episode'] = int(m.group(1))
            continue
        if not info['name']:
            info['name'] = part
    if info['date'] or info['season'] or info['episode']:
        return info
    return None


def _episode_title(series, info):
    parts = [series] if series else []
    if info['season'] and info['episode']:
        parts.append('S%02dE%02d' % (info['season'], info['episode']))
    elif info['episode']:
        parts.append('Folge %d' % info['episode'])
    if info['name']:
        parts.append(info['name'])
    title = ' - '.join(parts)
    if info['date']:
        title = '%s (%s)' % (title, info['date'])
    return title


def _apply_episode(item, ic):
    info = _episode_info(ic)
    if not info:
        return item
    item['title']     = _episode_title(str(ic.get('title') or ''), info)
    item['mediatype'] = 'episode'
    item['season']    = info['season']
    item['episode']   = info['episode']
    item['year']      = ''
    return item


def _dedupe(items):
    result, index = [], {}
    for item in items:
        uid = item.get('url', '')
        if not uid:
            result.append(item)
            continue
        if uid in index:
            pos = index[uid]
            if len(item.get('title', '')) > len(result[pos].get('title', '')):
                result[pos] = item
            continue
        index[uid] = len(result)
        result.append(item)
    return result


def _live_item(title, raw_id, ic, thumb):
    slug = str(raw_id).replace('rtlde_', '')
    return {
        'title': '[COLOR gold][B]Letzte Folge - %s[/B][/COLOR]' % title,
        'url': 'live:%s' % slug,
        'poster': thumb, 'icon': thumb, 'fanart': thumb,
        'plot': _clean_html(ic.get('description') or ic.get('highlight') or ''),
        'mediatype': 'video', 'is_playable': True, 'next_func': 'get_hosters',
    }


def _item_from_entry(it, group_series=False):
    if not isinstance(it, dict):
        return None
    ic = it.get('itemContent') or {}
    if not isinstance(ic, dict):
        return None
    title  = _build_title(ic)
    action = ic.get('action') or {}
    target = _resolve_target(action.get('target') or {})
    t_type = target.get('type', '')
    vl     = target.get('value_layout') or {}
    vp     = target.get('value_player') or {}
    vl_type = vl.get('type', '')
    vl_id   = str(vl.get('id', ''))
    vl_seo  = str(vl.get('seo', ''))
    vp_id   = str(vp.get('id', ''))
    vp_type = str(vp.get('type', ''))
    thumb  = _image_url(ic.get('image'))
    poster = _image_url(ic.get('image'), w=213, h=320, ratio='2:3')
    fanart = _image_url(ic.get('secondaryImage') or ic.get('image'), w=640, h=360)
    plot   = _clean_html(ic.get('description') or ic.get('highlight') or '')
    year   = _year_from_ic(ic)

    if vl_type == 'live' and vl_id:
        return _live_item(title, vl_id, ic, thumb)
    if t_type == 'live' or vl_type == 'live':
        return None
    if vp_type in _LIVE_TYPES:
        return _live_item(title, vp_id, ic, thumb) if vp_id else None

    if t_type == 'player' and vp_id:
        vl_alt   = target.get('value_layout') or {}
        clip_alt = vl_alt.get('id', '') if vl_alt.get('type') == 'video' else ''
        play_id  = clip_alt or vp_id
        return _apply_episode({
            'title': title, 'url': 'video:%s' % play_id,
            'poster': poster, 'icon': thumb, 'fanart': fanart,
            'plot': plot, 'year': year,
            'mediatype': 'movie', 'is_playable': True, 'next_func': 'get_hosters',
        }, ic)

    if not vl_id:
        return None

    if vl_type == 'video':
        parent = vl.get('parent') or {}
        if group_series and parent.get('type') == 'program' and parent.get('id'):
            return {
                'title': str(ic.get('title') or title),
                'url': 'program:%s:%s' % (parent['id'], parent.get('seo') or ''),
                'poster': poster, 'icon': thumb, 'fanart': fanart,
                'plot': _clean_html(ic.get('extraDetails') or ''),
                'mediatype': 'tvshow', 'is_playable': False, 'next_func': 'showSeasons',
            }
        return _apply_episode({
            'title': title, 'url': 'video:%s' % vl_id,
            'poster': poster, 'icon': thumb, 'fanart': fanart,
            'plot': plot, 'year': year,
            'mediatype': 'movie', 'is_playable': True, 'next_func': 'get_hosters',
        }, ic)

    if vl_type == 'program':
        if _is_movie_item(ic):
            return {
                'title': title, 'url': 'program:%s:%s' % (vl_id, vl_seo),
                'poster': poster, 'icon': thumb, 'fanart': fanart,
                'plot': plot, 'year': year,
                'mediatype': 'movie', 'is_playable': True, 'next_func': 'get_hosters',
            }
        return {
            'title': title, 'url': 'program:%s:%s' % (vl_id, vl_seo),
            'poster': poster, 'icon': thumb, 'fanart': fanart,
            'plot': plot, 'year': year,
            'mediatype': 'tvshow', 'is_playable': False, 'next_func': 'showSeasons',
        }

    if vl_type == 'folder':
        return {
            'title': title, 'url': 'folder:%s:%s' % (vl_id, vl_seo),
            'poster': thumb, 'icon': thumb, 'fanart': fanart,
            'plot': plot,
            'is_playable': False, 'next_func': 'showEntries',
        }

    return None


def _items_from_layout(data, group_series=False):
    if not isinstance(data, dict):
        return []
    items = []
    for block in data.get('blocks', []):
        bc = block.get('content') or {}
        for it in bc.get('items') or []:
            item = _item_from_entry(it, group_series)
            if item:
                items.append(item)
    items = _dedupe(items)
    live  = [i for i in items if i.get('url', '').startswith('live:')]
    other = [i for i in items if not i.get('url', '').startswith('live:')]
    return live + other


def _program_xloc(program_id, seo=''):
    return ('%s/%s-p_%s' % (_RTL_WEB, seo, program_id)
            if seo else '%s/program/%s' % (_RTL_WEB, program_id))


def _get_program_data(program_id, seo=''):
    return _api_get('/program/%s/layout' % program_id,
                    {'blockPage': 1, 'nbPages': _LAYOUT_PAGES},
                    x_location=_program_xloc(program_id, seo))


def _clip_from_program(program_id, seo=''):
    data = _get_program_data(program_id, seo)
    if not isinstance(data, dict):
        return ''
    for block in data.get('blocks', []):
        bc     = block.get('content') or {}
        bt_obj = bc.get('title') or {}
        bt     = (bt_obj.get('short') or bt_obj.get('long') or '') if isinstance(bt_obj, dict) else str(bt_obj)
        if 'empfehlung' in bt.lower() or 'recommendation' in bt.lower():
            continue
        for it in bc.get('items') or []:
            ic     = it.get('itemContent') or {}
            action = ic.get('action') or {}
            target = _resolve_target(action.get('target') or {})
            vl     = target.get('value_layout') or {}
            if target.get('type') == 'layout' and vl.get('type') == 'video':
                clip_id = str(vl.get('id', ''))
                if clip_id:
                    return clip_id
            if vl.get('type') == 'video' and vl.get('id'):
                return str(vl['id'])
    return ''


def _is_season_block(title):
    tl = title.lower().strip()
    if any(tl.startswith(p) for p in ('staffel', 'season', 'serie ', 'teil ', 'volume', 'buch ')):
        return True
    if tl.startswith('s') and len(tl) <= 4 and tl[1:].isdigit():
        return True
    if re.match(r'^[a-zäöü\s]+ \d+$', tl):
        return True
    return False


def _season_num_from_title(title):
    m = re.search(r'\d+', title)
    return int(m.group(0)) if m else 1


def _parse_url_offset(url):
    url = str(url or '')
    if '|' in url:
        base, _, off = url.rpartition('|')
        try:
            return base, int(off)
        except ValueError:
            pass
    return url, 0


def load(url='', params=None):
    return [
        {
            'title': 'Filme',
            'url': 'folder:%s:movies' % _FREE_FOLDER_ID,
            'plot': 'Kostenlose Filme von RTL+ (Gastbereich).',
            'is_playable': False,
            'next_func': 'showEntries',
            'poster': _ICON,
            'icon': _ICON,
        },
        {
            'title': 'Serien',
            'url': 'folder:%s:series' % _FREE_FOLDER_ID,
            'plot': 'Kostenlose Serien von RTL+ (Gastbereich).',
            'is_playable': False,
            'next_func': 'showEntries',
            'poster': _ICON,
            'icon': _ICON,
        },
        {
            'title': 'Live TV',
            'url': '',
            'plot': 'RTL+ Live-Sender.',
            'is_playable': False,
            'next_func': 'get_live',
            'poster': _ICON,
            'icon': _ICON,
        },
        {
            'title': 'Suche',
            'url': '',
            'plot': 'Durchsuche die freien RTL+ Inhalte.',
            'is_playable': False,
            'next_func': 'search',
            'poster': _ICON,
            'icon': _ICON,
        },
    ]


def showEntries(url='', params=None):
    base_url, offset = _parse_url_offset(url)
    if not base_url:
        base_url = 'folder:%s' % _FREE_FOLDER_ID

    content_filter = None
    folder_id = None
    if base_url.startswith('folder:'):
        parts = base_url[7:].split(':')
        folder_id = parts[0]
        if len(parts) > 1 and parts[1] in ('movies', 'series'):
            content_filter = parts[1]

    all_items = []
    if base_url.startswith('folder:'):
        xloc = '%s/rtlplus-root/kostenlose-inhalte-main-root-service-f_%s' % (_RTL_WEB, folder_id)
        data = _layout_all('/folder/%s/layout' % folder_id, x_location=xloc)
        all_items = _items_from_layout(data, group_series=True)
        if content_filter == 'movies':
            all_items = [i for i in all_items if i.get('mediatype') == 'movie' and not i.get('url', '').startswith('live:')]
        elif content_filter == 'series':
            all_items = [i for i in all_items if i.get('mediatype') in ('tvshow', 'episode', 'season')]

    total = len(all_items)
    page  = all_items[offset:offset + _PAGE_SIZE]

    if offset + _PAGE_SIZE < total:
        remaining = total - offset - _PAGE_SIZE
        page.append({
            'title': 'Weiter  (%d weitere)' % remaining,
            'url': '%s|%d' % (base_url, offset + _PAGE_SIZE),
            'plot': 'Nächste Seite laden.',
            'is_playable': False,
            'next_func': 'showEntries',
            'poster': _ICON,
            'icon': _ICON,
        })
    return page


def showSeasons(url='', params=None):
    base_url, _ = _parse_url_offset(url)
    if not base_url.startswith('program:'):
        return []
    rest       = base_url[8:]
    program_id = rest.split(':')[0]
    seo        = rest.split(':')[1] if ':' in rest else ''
    data       = _get_program_data(program_id, seo)
    if not isinstance(data, dict):
        return []

    season_blocks     = []
    fallback_episodes = []
    for block in data.get('blocks', []):
        bc     = block.get('content') or {}
        bt_obj = bc.get('title') or {}
        bt     = (bt_obj.get('short') or bt_obj.get('long') or '') if isinstance(bt_obj, dict) else str(bt_obj)
        if bt and _is_season_block(bt):
            season_blocks.append((bt, block))
        else:
            for it in bc.get('items') or []:
                ep = _item_from_entry(it)
                if ep and ep.get('is_playable') and ep.get('url', '').startswith('video:'):
                    fallback_episodes.append(ep)

    fallback_episodes = _dedupe(fallback_episodes)
    if not season_blocks:
        return showEpisodes(base_url) or fallback_episodes

    items = []
    for bt, block in season_blocks:
        s_num = _season_num_from_title(bt)
        bc    = block.get('content') or {}
        first = (bc.get('items') or [{}])[0]
        f_ic  = first.get('itemContent') or {}
        thumb = _image_url(f_ic.get('image'))
        items.append({
            'title': bt,
            'url': 'program:%s:%s:%d' % (program_id, seo, s_num),
            'poster': thumb,
            'icon': thumb,
            'mediatype': 'season',
            'season': s_num,
            'is_playable': False,
            'next_func': 'showEpisodes',
        })
    return items


def showEpisodes(url='', params=None):
    base_url, _ = _parse_url_offset(url)
    if not base_url.startswith('program:'):
        return []
    rest   = base_url[8:]
    parts  = rest.split(':')
    program_id    = parts[0]
    seo           = parts[1] if len(parts) > 1 else ''
    target_season = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    data = _get_program_data(program_id, seo)
    if not isinstance(data, dict):
        return []

    def _wanted(block):
        bt = _block_title(block)
        if bt and _is_season_block(bt):
            return target_season is None or _season_num_from_title(bt) == target_season
        if bt:
            return False
        first = ((block.get('content') or {}).get('items') or [None])[0]
        return (_item_from_entry(first) or {}).get('url', '').startswith('video:')

    _expand_blocks('/program/%s' % program_id, data, _program_xloc(program_id, seo), select=_wanted)

    episodes = []
    for block in data.get('blocks', []):
        bt = _block_title(block)
        if target_season is not None and bt and _is_season_block(bt):
            if _season_num_from_title(bt) != target_season:
                continue
        for it in (block.get('content') or {}).get('items') or []:
            ep = _item_from_entry(it)
            if ep and ep.get('is_playable') and ep.get('url', '').startswith('video:'):
                episodes.append(ep)

    items = _dedupe(episodes)
    for n, ep in enumerate(items, 1):
        ep['mediatype'] = 'episode'
        if not ep.get('season'):
            ep['season'] = target_season or 1
        if not ep.get('episode'):
            ep['episode'] = n
    return items


def get_live(url='', params=None):
    data = _api_get('/epg_grid', {'nbPages': 5})
    if not isinstance(data, dict):
        return []
    items_raw = (data.get('content') or {}).get('items') or []
    if not items_raw:
        for block in data.get('blocks', []):
            items_raw += (block.get('content') or {}).get('items') or []
    channels = []
    seen = set()
    for it in items_raw:
        ic     = it.get('itemContent') or {}
        action = ic.get('action') or {}
        target = _resolve_target(action.get('target') or {})
        t_type = target.get('type', '')
        channel_slug = ''
        if t_type == 'layout':
            channel_slug = (target.get('value_layout') or {}).get('id', '').replace('rtlde_', '')
        elif t_type == 'player':
            channel_slug = (target.get('value_player') or {}).get('id', '').replace('rtlde_', '')
        if not channel_slug or channel_slug in seen:
            continue
        seen.add(channel_slug)
        ch_data = ic.get('channel') or {}
        title = ch_data.get('title') or channel_slug.upper()
        img   = _image_url(ch_data.get('image') or ic.get('image'), w=200, h=200, ratio='1:1')
        channels.append({
            'title': title,
            'url': 'live:%s' % channel_slug,
            'poster': img, 'icon': img, 'fanart': img,
            'plot': title,
            'mediatype': 'video',
            'is_playable': True,
            'next_func': 'get_hosters',
        })
    return channels


def get_hosters(title='', year='', season=0, episode=0, imdb='', tmdb='', url='', params=None):
    if url:
        u = str(url)
        if u.startswith('live:'):
            channel_id = u[5:]
            if channel_id:
                purl = _PLUGIN_RTL + '?mode=play_live&channel_id=' + urllib.parse.quote_plus(channel_id)
                return [('RTL+ Live', purl, True, 'HD', 'de')]
        elif u.startswith('video:'):
            clip_id = u[6:]
            if clip_id:
                purl = _PLUGIN_RTL + '?mode=play_vod&video_id=' + urllib.parse.quote_plus(clip_id)
                return [('RTL+ Free', purl, True, 'HD', 'de')]
        elif u.startswith('program:'):
            rest       = u[8:]
            program_id = rest.split(':')[0]
            seo_part   = rest.split(':')[1] if ':' in rest else ''
            if ':' in seo_part:
                seo_part = seo_part.split(':')[0]
            clip_id = _clip_from_program(program_id, seo_part)
            if clip_id:
                purl = _PLUGIN_RTL + '?mode=play_vod&video_id=' + urllib.parse.quote_plus(clip_id)
                return [('RTL+ Free', purl, True, 'HD', 'de')]
        elif u.startswith('player:'):
            vp_id = u[7:]
            if vp_id:
                purl = _PLUGIN_RTL + '?mode=play_vod&video_id=' + urllib.parse.quote_plus(vp_id)
                return [('RTL+ Free', purl, True, 'HD', 'de')]
        return []

    query = re.sub(r'\s*[\(\[\{].*', '', str(title or '')).strip()
    if not query:
        return []
    year_s = str(year or '')
    xloc   = '%s/suche?query=%s' % (_RTL_WEB, urllib.parse.quote(query))
    data   = _api_get('/frontspace/search/layout', {'blockPage': 1, 'nbPages': 3, 'query': query}, x_location=xloc)
    if not isinstance(data, dict):
        return []
    for r in _items_from_layout(data):
        if not r.get('is_playable'):
            continue
        if year_s and r.get('year') and r['year'] != year_s:
            continue
        r_url = r.get('url', '')
        if r_url.startswith('video:'):
            clip_id = r_url[6:]
            purl = _PLUGIN_RTL + '?mode=play_vod&video_id=' + urllib.parse.quote_plus(clip_id)
            return [('RTL+ Free', purl, True, 'HD', 'de')]
        elif r_url.startswith('program:'):
            rest       = r_url[8:]
            program_id = rest.split(':')[0]
            seo_part   = rest.split(':')[1] if ':' in rest else ''
            clip_id    = _clip_from_program(program_id, seo_part)
            if clip_id:
                purl = _PLUGIN_RTL + '?mode=play_vod&video_id=' + urllib.parse.quote_plus(clip_id)
                return [('RTL+ Free', purl, True, 'HD', 'de')]
    return []


def search(query='', params=None, url=''):
    if isinstance(params, dict):
        query = query or params.get('query') or params.get('keyword') or ''
    if not query:
        if isinstance(url, str) and url and url.lower() not in ('search', 'suche', 'search_form'):
            query = url
    if not query:
        try:
            r = xbmcgui.Dialog().input('RTL+ Free Suche')
            if r:
                query = r.strip()
        except Exception as e:
            log_error(str(e))
    if not query:
        return []
    xloc = '%s/suche?query=%s' % (_RTL_WEB, urllib.parse.quote(query))
    data = _api_get('/frontspace/search/layout', {'blockPage': 1, 'nbPages': 3, 'query': query}, x_location=xloc)
    if not isinstance(data, dict):
        return []
    items = _items_from_layout(data, group_series=True)
    if not items:
        xbmcgui.Dialog().notification('RTL+ Free', 'Keine Treffer gefunden.', xbmcgui.NOTIFICATION_INFO, 3000, False)
    return items
