import json
import time
import threading

from resources.lib import multiquest

VAVOO_UA = 'TiviMate/5.0.0 (Linux; Google TV)'

BUNDLES = [
    ('vavoo.to',  'https://vavoo.to'),
    ('vavoo.net', 'https://vavoo.net'),
    ('vavoo.top', 'https://vavoo.top'),
    ('kool.to',   'https://kool.to'),
    ('oha.to',    'https://oha.to'),
    ('huhu.to',   'https://huhu.to'),
]

_KNOWN_PORTALS = {
    'oha.to':    {'prefix': '/mediaurl-',   'region': 'DE', 'discovery': '/mediaurl.json'},
    'huhu.to':   {'prefix': '/mediaurl-',   'region': 'DE', 'discovery': '/mediaurl.json'},
    'kool.to':   {'prefix': '/mediahubmx-', 'region': 'AT', 'discovery': '/mediahubmx.json'},
    'vavoo.to':  {'prefix': '/mediahubmx-', 'region': 'XX', 'discovery': '/mediahubmx.json'},
    'vavoo.top': {'prefix': '/mediahubmx-', 'region': 'XX', 'discovery': '/mediahubmx.json'},
    'vavoo.net': {'prefix': '/mediahubmx-', 'region': 'XX', 'discovery': '/mediahubmx.json'},
}

_HEADERS = {
    'User-Agent': VAVOO_UA,
    'Accept': 'application/json',
    'Accept-Charset': 'UTF-8',
    'Content-Type': 'application/json',
}


def _normalise_url(url):
    url = url.strip().rstrip('/')
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def _detect_portal(base_url, timeout):
    for domain, cfg in _KNOWN_PORTALS.items():
        if domain in base_url:
            return cfg['prefix'], cfg['region'], cfg['discovery']
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
                return prefix, region, discovery
        except Exception:
            pass
    return '/mediaurl-', 'DE', '/mediaurl.json'


class VavooClient:
    def __init__(self, portal_url, timeout=20):
        self._base = _normalise_url(portal_url)
        self._timeout = timeout
        self._prefix, self._region, self._discovery = _detect_portal(self._base, timeout)

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

    def test_connection(self):
        data = self._post(self._path('catalog'), self._build_payload())
        return isinstance(data, dict) and 'items' in data

    def get_all_channels(self, adult=True):
        first = self._post(self._path('catalog'), self._build_payload(cursor=None, adult=adult))
        channels = list(first.get('items') or [])
        first_cursor = first.get('nextCursor')
        if not first_cursor:
            return channels

        collected = {0: channels}
        lock = threading.Lock()
        cursors_done = set()

        def fetch_page(cursor, slot):
            try:
                data = self._post(self._path('catalog'), self._build_payload(cursor=cursor, adult=adult))
                items = list(data.get('items') or [])
                next_c = data.get('nextCursor')
            except Exception:
                items = []
                next_c = None
            with lock:
                collected[slot] = items
                if next_c and next_c not in cursors_done:
                    cursors_done.add(next_c)
                    t = threading.Thread(target=fetch_page, args=(next_c, slot + 1))
                    t.daemon = True
                    t.start()

        cursors_done.add(first_cursor)
        t0 = threading.Thread(target=fetch_page, args=(first_cursor, 1))
        t0.daemon = True
        t0.start()
        t0.join(timeout=self._timeout)

        for slot in sorted(collected):
            if slot == 0:
                continue
            channels.extend(collected[slot])
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
