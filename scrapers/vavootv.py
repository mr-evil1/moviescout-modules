import json
import time
import threading

from resources.lib import multiquest

VAVOO_UA = 'TiviMate/5.0.0 (Linux; Google TV)'
GEIL_UA = 'Mozilla/5.0 (Linux; Android 14; SM-G998B Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/156.0.8078.47 Mobile Safari/537.36'

BUNDLES = [
    ('geil.to',   'https://geil.to'),
    ('vavoo.net', 'https://vavoo.net'),
    ('vavoo.top', 'https://vavoo.top'),
    ('kool.to',   'https://kool.to'),
    ('oha.to',    'https://oha.to'),
    ('huhu.to',   'https://huhu.to'),
]

_KNOWN_PORTALS = {
    'oha.to':    {'prefix': '/mediaurl-',   'region': 'DE', 'discovery': '/mediaurl.json',   'api': 'vavoo'},
    'huhu.to':   {'prefix': '/mediaurl-',   'region': 'DE', 'discovery': '/mediaurl.json',   'api': 'vavoo'},
    'kool.to':   {'prefix': '/mediahubmx-', 'region': 'AT', 'discovery': '/mediahubmx.json', 'api': 'vavoo'},
    'vavoo.top': {'prefix': '/mediahubmx-', 'region': 'XX', 'discovery': '/mediahubmx.json', 'api': 'vavoo'},
    'vavoo.net': {'prefix': '/mediahubmx-', 'region': 'XX', 'discovery': '/mediahubmx.json', 'api': 'vavoo'},
    'geil.to':   {'region': 'AT', 'api': 'geil'},
}

_HEADERS = {
    'User-Agent':   VAVOO_UA,
    'Accept':       'application/json',
    'Accept-Charset': 'UTF-8',
    'Content-Type': 'application/json',
}

_GEIL_HEADERS = {
    'User-Agent':      GEIL_UA,
    'Accept':          'application/json',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'de-AT,de;q=0.9,en-US;q=0.8,en;q=0.7',
    'X-Requested-With': 'net.vypn.app',
    'Connection':      'keep-alive',
}


def _normalise_url(url):
    url = url.strip().rstrip('/')
    if 'vavoo.to' in url:
        url = 'http://geil.to'
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def _detect_portal(base_url, timeout):
    for domain, cfg in _KNOWN_PORTALS.items():
        if domain in base_url:
            return cfg
    for discovery, prefix, region in [
        ('/mediaurl.json',   '/mediaurl-',   'DE'),
        ('/mediahubmx.json', '/mediahubmx-', 'DE'),
    ]:
        try:
            r = multiquest.post(
                base_url + discovery,
                data='{}',
                headers=_HEADERS,
                timeout=timeout,
            )
            if r.status_code == 200 and 'catalogs' in r.text:
                return {'prefix': prefix, 'region': region, 'discovery': discovery, 'api': 'vavoo'}
        except Exception:
            pass
    return {'prefix': '/mediaurl-', 'region': 'DE', 'discovery': '/mediaurl.json', 'api': 'vavoo'}


class VavooClient:
    def __init__(self, portal_url, timeout=20):
        self._base = _normalise_url(portal_url)
        self._timeout = timeout
        cfg = _detect_portal(self._base, timeout)
        self._api = cfg.get('api', 'vavoo')
        self._region = cfg.get('region', 'DE')
        if self._api == 'vavoo':
            self._prefix = cfg.get('prefix', '/mediaurl-')
            self._discovery = cfg.get('discovery', '/mediaurl.json')

    def _path(self, name):
        return self._base + self._prefix + name + '.json'

    def _post(self, url, payload):
        url_t = url + '?_t=%d' % int(time.time() * 1000)
        r = multiquest.post(
            url_t,
            data=json.dumps(payload, separators=(',', ':')),
            headers=_HEADERS,
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.json()

    def _build_payload(self, cursor=None, adult=True):
        return {
            'language': 'de', 'region': self._region,
            'catalogId': 'iptv', 'id': '',
            'adult': adult, 'search': '',
            'sort': 'trending-region',
            'filter': {}, 'cursor': cursor,
            'clientVersion': '3.1.0',
        }

    def _geil_catalog_url(self, cursor=None):
        url = '%s/live/catalog/live/channels.json?region=%s&language=de&sort=trending' % (
            self._base, self._region
        )
        if cursor is not None:
            url += '&cursor=%s' % cursor
        return url

    def _geil_get(self, url):
        r = multiquest.get(url, headers=_GEIL_HEADERS, timeout=self._timeout)
        r.raise_for_status()
        return r.json()

    def test_connection(self):
        if self._api == 'geil':
            try:
                data = self._geil_get(self._geil_catalog_url())
                return isinstance(data, dict) and 'items' in data
            except Exception:
                return False
        data = self._post(self._path('catalog'), self._build_payload())
        return isinstance(data, dict) and 'items' in data

    def get_all_channels(self, adult=True, progress_callback=None):
        if self._api == 'geil':
            return self._geil_get_all_channels(progress_callback)
        return self._vavoo_get_all_channels(adult, progress_callback)

    def _geil_get_all_channels(self, progress_callback=None):
        pages = {}
        lock = threading.Lock()
        threads = []
        total_count = [0]

        def fetch_page(cursor, slot):
            try:
                data = self._geil_get(self._geil_catalog_url(cursor))
                raw = list(data.get('items') or [])
                for item in raw:
                    if 'group' not in item:
                        tags = item.get('tags') or []
                        item['group'] = tags[0] if tags else ''
                items = raw
                next_c = data.get('nextCursor')
            except Exception:
                items = []
                next_c = None
            with lock:
                pages[slot] = items
                total_count[0] += len(items)
                if next_c is not None:
                    t = threading.Thread(target=fetch_page, args=(next_c, slot + 1))
                    t.daemon = True
                    threads.append(t)
                    t.start()

        t0 = threading.Thread(target=fetch_page, args=(None, 0))
        t0.daemon = True
        threads.append(t0)
        t0.start()

        deadline = time.time() + self._timeout
        while True:
            with lock:
                alive = [t for t in threads if t.is_alive()]
                current_total = total_count[0]
            if progress_callback:
                try:
                    progress_callback(current_total, bool(alive))
                except Exception:
                    pass
            if not alive:
                break
            if time.time() > deadline:
                break
            time.sleep(0.3)

        if progress_callback:
            try:
                progress_callback(total_count[0], False)
            except Exception:
                pass

        channels = []
        for slot in sorted(pages):
            channels.extend(pages[slot])
        return channels

    def _vavoo_get_all_channels(self, adult=True, progress_callback=None):
        pages = {}
        lock = threading.Lock()
        threads = []
        total_count = [0]

        def fetch_page(cursor, slot):
            try:
                data = self._post(self._path('catalog'), self._build_payload(cursor=cursor, adult=adult))
                items = list(data.get('items') or [])
                next_c = data.get('nextCursor')
            except Exception:
                items = []
                next_c = None
            with lock:
                pages[slot] = items
                total_count[0] += len(items)
                if next_c:
                    t = threading.Thread(target=fetch_page, args=(next_c, slot + 1))
                    t.daemon = True
                    threads.append(t)
                    t.start()

        t0 = threading.Thread(target=fetch_page, args=(None, 0))
        t0.daemon = True
        threads.append(t0)
        t0.start()

        deadline = time.time() + self._timeout
        while True:
            with lock:
                alive = [t for t in threads if t.is_alive()]
                current_total = total_count[0]
            if progress_callback:
                try:
                    progress_callback(current_total, bool(alive))
                except Exception:
                    pass
            if not alive:
                break
            if time.time() > deadline:
                break
            time.sleep(0.3)

        if progress_callback:
            try:
                progress_callback(total_count[0], False)
            except Exception:
                pass

        channels = []
        for slot in sorted(pages):
            channels.extend(pages[slot])
        return channels

    def _resolve_task_request(self, task_id, task_data):
        fetch_url = task_data.get('url', '')
        params = task_data.get('params', {})
        method = params.get('method', 'GET').upper()
        headers = params.get('headers', {})
        try:
            if method == 'POST':
                r = multiquest.post(fetch_url, headers=headers, timeout=self._timeout)
            else:
                r = multiquest.get(fetch_url, headers=headers, timeout=self._timeout)
            response_payload = {
                'kind': 'taskResponse',
                'id': task_id,
                'data': {'text': r.text, 'status': r.status_code},
            }
        except Exception as e:
            response_payload = {
                'kind': 'taskResponse',
                'id': task_id,
                'data': {'error': str(e)},
            }
        return self._post(self._path('resolve'), response_payload)

    def resolve_stream_url(self, play_url):
        if self._api == 'geil':
            return self._geil_resolve(play_url)
        return self._vavoo_resolve(play_url)

    def _geil_resolve(self, play_url):
        try:
            import urllib.parse
            resolve_url = '%s/live/resolve?region=%s&language=de&url=%s' % (
                self._base, self._region, urllib.parse.quote(play_url, safe='')
            )
            data = self._geil_get(resolve_url)
            if isinstance(data, dict) and data.get('url'):
                return data['url']
        except Exception:
            pass
        return play_url

    def _vavoo_resolve(self, play_url):
        payload = {
            'language': 'de',
            'region': self._region,
            'url': play_url,
            'clientVersion': '3.1.0',
        }
        data = self._post(self._path('resolve'), payload)
        for _ in range(5):
            if isinstance(data, list) and data:
                return data[0].get('url', '')
            if isinstance(data, dict) and data.get('url'):
                return data['url']
            if isinstance(data, dict) and data.get('kind') == 'taskRequest':
                task_id = data.get('id', '')
                task_data = data.get('data', {})
                data = self._resolve_task_request(task_id, task_data)
                continue
            break
        raise ValueError('Vavoo resolve fehlgeschlagen für %s' % play_url)
