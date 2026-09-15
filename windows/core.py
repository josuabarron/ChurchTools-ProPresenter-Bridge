"""ChurchTools protocol and agenda semantics shared by the Windows UI and tests."""
import datetime as dt
import http.cookiejar
import json
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid


class BridgeError(Exception):
    pass


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.strip().casefold())
                   if not unicodedata.combining(c))


def note_on(packed, channel=1):
    status, note, velocity = packed & 255, (packed >> 8) & 255, (packed >> 16) & 255
    if status == 0x90 + channel - 1 and note < 128 and 0 < velocity < 128:
        return note
    return None


def title(item):
    song = item.get('song') or {}
    return next((v for v in [item.get('title'), item.get('name'), song.get('title'), song.get('name')]
                 if isinstance(v, str)), '')


def notes(item):
    return next((item[k].strip() for k in ('note', 'notes', 'comment', 'comments', 'description')
                 if isinstance(item.get(k), str) and item[k].strip()), '')


def resolve_position(target, position, items):
    value = normalized(target)
    if value in ('vor', 'weiter', 'next', 'forward'):
        candidate = min(position + 1, len(items) + 1)
        while candidate <= len(items):
            item = items[candidate - 1]
            if item.get('duration', 0) != 0 or item.get('song') is None:
                break
            candidate += 1
        return candidate
    if value in ('zuruck', 'zurueck', 'previous', 'back'):
        return max(0, position - 1)
    try:
        result = int(target.strip())
    except ValueError:
        result = next((i + 1 for i, item in enumerate(items) if normalized(title(item)) == value), None)
        if result is None:
            raise BridgeError('Kein Agenda-Eintrag mit diesem Titel gefunden.')
    if not 0 <= result <= len(items) + 1:
        raise BridgeError(f'Agenda-Position muss zwischen 0 und {len(items) + 1} liegen.')
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the login header to a redirect destination.
        return None


class Client:
    def __init__(self, config, token):
        self.config = config
        self.base = config['api'].rstrip('/')
        self.root = self.base[:-4] if self.base.endswith('/api') else self.base
        self.token = token
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = None
        self.tab = str(uuid.uuid4())
        self.agendas = {}
        self.backoff_until = 0
        self.cancelled = False
        # Nach einem Fehler kurz nicht erneut fragen. Sonst feuern die drei
        # Ansichten alle 2,5 s nach, obwohl ChurchTools nicht antwortet
        # (gemessen: Antwortdauer Median 6,5 s / Spitze 9,2 s).
        self.recent_failures = {}
        self.failure_pause = 5.0
        # self.lock schuetzt ChurchTools-Zustand (CSRF, Drosselung, Agenda,
        # Positionsablauf). Es wird waehrend des Netzaufrufs gehalten - das ist
        # gewollt, sonst laufen Abfragen ungebremst in ChurchTools' Drosselung.
        self.lock = threading.RLock()
        # Nur der Cache hat einen eigenen, kurz gehaltenen Schuetzen. Sonst
        # muessten die Ansichten warten, bis ein MIDI-Klick seinen Netzaufruf
        # beendet hat (gemessen: +750 ms).
        self.cache_lock = threading.Lock()
        self.cache = {}
        # Je Event ein eigener Schuetze: so holt nur ein Thread wirklich nach,
        # wenn drei Ansichten gleichzeitig dieselbe Agenda brauchen.
        self.event_locks = {}
        self.event_locks_lock = threading.Lock()

    def request(self, path, form=None):
        with self.lock:
            if self.cancelled:
                raise BridgeError('Bridge wurde gestoppt.')
            if time.monotonic() < self.backoff_until:
                raise BridgeError('Gedrosselt · Cache aktiv. Bitte später erneut versuchen.')
            headers = {'Authorization': 'Login ' + self.token, 'Accept': 'application/json'}
            data = None
            if form is not None:
                if self.csrf is None:
                    self.csrf = self.request('/csrftoken')['data']
                headers['CSRF-Token'] = self.csrf
                headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
                data = urllib.parse.urlencode(dict(form, browsertabId=self.tab)).encode()
            url = self.root + '/index.php?q=churchservice/ajax' if form is not None else self.base + path
            try:
                with self.opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=10) as response:
                    result = json.load(response)
            except urllib.error.HTTPError as error:
                if error.code == 429:
                    try:
                        delay = max(60, int(error.headers.get('Retry-After', '60')))
                    except ValueError:
                        delay = 60
                    self.backoff_until = time.monotonic() + delay
                if error.code == 403:
                    self.csrf = None
                # Response bodies and URLs may contain secrets: do not expose them.
                raise BridgeError(f'ChurchTools HTTP {error.code}') from None
            except (OSError, ValueError) as error:
                raise BridgeError('ChurchTools nicht erreichbar oder Antwort ungültig.') from None
            if form is not None and result.get('status') != 'success':
                raise BridgeError('ChurchTools hat den Live-Agenda-Befehl abgelehnt.')
            return result

    def agenda(self, event_id):
        if event_id not in self.agendas:
            self.agendas[event_id] = self.request(f'/events/{event_id}/agenda')['data']
        return self.agendas[event_id]

    def events(self):
        self.request('/whoami')
        today = dt.date.today()
        query = urllib.parse.urlencode(dict(
            **{'from': today.isoformat()}, to=(today + dt.timedelta(days=self.config['days'])).isoformat(),
            direction='forward', limit=25, canceled='false'))
        events = self.request('/events?' + query)['data']
        events.sort(key=lambda e: e.get('startDate') or '9999')
        selected, selected_day = [], None
        for event in events:
            if event.get('isCanceled') or normalized(self.config['filter']) not in normalized(event['name']):
                continue
            start = event.get('startDate')
            day = dt.datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone().date() if start else None
            if selected_day and day and day != selected_day:
                break
            try:
                agenda = self.agenda(event['id'])
            except BridgeError:
                if time.monotonic() < self.backoff_until:
                    raise
                continue
            if not self.config['locked'] or agenda.get('isLocked'):
                selected.append(event)
                selected_day = selected_day or day
        return selected

    def position(self, event_id, agenda):
        data = self.request('', dict(func='loadAgendaLivePosition', event_id=event_id, agenda_id=agenda['id'])).get('data')
        return int((data or {}).get('pos_id') or 0)

    def execute(self, event_id, target):
        with self.lock:
            agenda = self.agenda(event_id)
            items = [i for i in agenda['items'] if i.get('type') != 'header']
            current = self.position(event_id, agenda)
            new = resolve_position(target, current, items)
            if new != current:
                self.request('', dict(func='saveAgendaLivePosition', event_id=event_id, pos_id=new, addseconds=0))
                with self.cache_lock:
                    self.cache.pop(event_id, None)

    def event_lock(self, event_id):
        with self.event_locks_lock:
            lock = self.event_locks.get(event_id)
            if lock is None:
                lock = self.event_locks[event_id] = threading.Lock()
            return lock

    def snapshot(self, event_id):
        # Frischer Cache-Treffer zuerst und OHNE die globale Sperre: die Ansichten
        # duerfen nicht darauf warten, dass ein MIDI-Klick sein Netz-IO beendet.
        with self.cache_lock:
            cached = self.cache.get(event_id)
        if cached and time.monotonic() - cached[0] < 3:
            return cached[1]
        # Nur ein Thread je Event holt wirklich nach. Die anderen warten hier
        # und finden danach den frischen Cache vor.
        with self.event_lock(event_id):
            with self.cache_lock:
                cached = self.cache.get(event_id)
            if cached and time.monotonic() - cached[0] < 3:
                return cached[1]
            return self._refresh(event_id)

    def _refresh(self, event_id):
        # Frische Fehlermeldung? Dann die letzte bekannte Agenda liefern,
        # ohne ChurchTools erneut zu belasten.
        with self.cache_lock:
            zuletzt_gescheitert = self.recent_failures.get(event_id, 0)
        if time.monotonic() - zuletzt_gescheitert < self.failure_pause:
            with self.cache_lock:
                veraltet = self.cache.get(event_id)
            if veraltet:
                return veraltet[1]
        try:
            agenda = self.agenda(event_id)
            items = [i for i in agenda['items'] if i.get('type') != 'header']
            pos = self.position(event_id, agenda)
            current = items[pos - 1] if 1 <= pos <= len(items) else {}
            following = items[pos] if 0 <= pos < len(items) else {}
            result = dict(current=title(current), next=title(following), notes=notes(current))
            with self.cache_lock:
                self.cache[event_id] = time.monotonic(), result
                self.recent_failures.pop(event_id, None)
            return result
        except BridgeError:
            with self.cache_lock:
                self.recent_failures[event_id] = time.monotonic()
                veraltet = self.cache.get(event_id)
            # Bei einem Fehler die letzte bekannte Agenda zeigen, sofern vorhanden.
            if veraltet:
                return veraltet[1]
            raise

    def live_url(self, event_id):
        query = dict(q='churchservice/liveview', event_id=event_id, login_token=self.token)
        if self.config['user']:
            query['user_id'] = self.config['user']
        return self.root + '/?' + urllib.parse.urlencode(query) + '#LiveView'
