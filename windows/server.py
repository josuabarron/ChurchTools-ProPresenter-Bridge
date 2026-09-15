"""Lokaler HTTP-Server für die Live-Ansichten.

Er lauscht ausschließlich auf 127.0.0.1. Das ist Netzwerkisolation, aber KEINE
Zugriffskontrolle: jeder lokale Prozess und jede Seite im gleichen Browser kann
diesen Port erreichen. Deshalb wird hier geprüft, wer fragt:

* Host muss auf 127.0.0.1/localhost lauten. Das schließt DNS-Rebinding aus:
  Dabei verbindet sich der Browser zwar auf 127.0.0.1, schickt aber den Host
  der Angreifer-Domain mit.
* Origin/Referer und Sec-Fetch-Site müssen zur eigenen Seite passen oder
  fehlen. Eine fremde Webseite darf die Daten nicht abfragen.
* Ein Timeout begrenzt die Lebensdauer eines Handler-Threads. Ohne das sammeln
  sich Threads an, wenn ChurchTools hängt und der Browser abbricht.

Was hier NICHT gelöst werden kann: /live gibt die ChurchTools-Weiterleitung mit
dem Login-Token zurück (siehe core.Client.live_url). Ein lokaler Prozess, der
als derselbe Benutzer läuft, könnte den Token auch direkt aus token.dpapi
holen. Der Token darf deshalb nur zu einem eng eingeschränkten
ChurchTools-Funktionsbenutzer gehören.
"""
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from core import BridgeError

# Wo der Server lauschen darf.
LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1'}

# Sec-Fetch-Site: was ein Browser bei einer eigenen Anfrage sendet. Fehlt der
# Kopf (ältere Browser, ProPresenter-Browser-Source, curl), wird er nicht
# verlangt – sonst bräche die Ansicht in ProPresenter.
EIGENE_HERKUNFT = {'none', 'same-origin', 'same-site'}

PAGE = '''<!doctype html><html lang="de"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Live Agenda</title>
<style>body{margin:0;background:#050607;color:white;font-family:Segoe UI,sans-serif}
main{display:flex;align-items:center;gap:4vw;min-height:100vh;padding:0 4vw;box-sizing:border-box}
section{flex:1;min-width:0}label{color:#9299a2;font-size:2vw;text-transform:uppercase}
h1{font-size:clamp(20px,7vw,100px);overflow-wrap:anywhere;margin:12px 0;line-height:1.08}
#notes{white-space:pre-wrap;overflow-wrap:anywhere;font-weight:700}</style>
<main id="strip"><section><label>Jetzt</label><h1 id="current">Noch nicht gestartet</h1></section>
<section><label>Dann</label><h1 id="next"></h1></section></main>
<main id="noteview" hidden><div id="notes">Keine Notizen</div></main>
<script>const isNotes=location.pathname==='/live/notes';
document.getElementById('strip').style.display=isNotes?'none':'flex';
document.getElementById('noteview').style.display=isNotes?'flex':'none';
async function refresh(){try{const response=await fetch('/live/data.json',{cache:'no-store'});
if(response.ok){const d=await response.json();
for(const key of ['current','next','notes'])document.getElementById(key).textContent=d[key]||(key==='current'?'Noch nicht gestartet':key==='notes'?'Keine Notizen':'');
document.getElementById('notes').style.fontSize=d.notesFontSize+'px';}}
catch(e){}finally{setTimeout(refresh,2500)}}refresh();</script></html>'''


def _host_erlaubt(kopf):
    """Prüft den Host-Kopf gegen die Loopback-Namen.

    Ohne diese Prüfung könnte eine fremde Seite per DNS-Rebinding als
    gleichursprünglich auf die Ansichten zugreifen.
    """
    if not kopf:
        return False
    try:
        name = urlsplit('//' + kopf.split('@')[-1]).hostname
    except ValueError:
        return False
    return (name or '').lower() in LOOPBACK_HOSTS


def _herkunft_erlaubt(origin):
    """True, wenn der Origin fehlt oder selbst lokal ist."""
    if not origin:
        return True
    if origin == 'null':                # Sandbox/Datei-Herkunft: ablehnen
        return False
    try:
        name = urlsplit(origin).hostname
    except ValueError:
        return False
    return (name or '').lower() in LOOPBACK_HOSTS


class Server:
    def __init__(self, port, state):
        # Die Hilfe einmal lesen. Je Anfrage gelesen wäre sie ein Fehlerpfad:
        # fehlt die Datei, bricht do_GET ab und der Client wartet vergeblich.
        try:
            help_text = Path(__file__).with_name('help.html').read_text(encoding='utf-8')
        except OSError:
            help_text = ('<!doctype html><meta charset="utf-8">'
                         '<p>Die Hilfe lässt sich nicht laden.</p>')
        # Auch als Attribut bereitstellen, damit Tests und Diagnose den Inhalt
        # prüfen können.
        self.help_text = help_text

        class Handler(BaseHTTPRequestHandler):
            # Begrenzt die Lebensdauer des Threads, wenn der Client abbricht
            # oder ChurchTools nicht antwortet.
            timeout = 15
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass

            def _antwort(self, status, body='', kind='text/html; charset=utf-8', location=None):
                encoded = body.encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', kind)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                # Die Ansichten sollen nicht in fremde Seiten eingebettet werden.
                self.send_header('X-Frame-Options', 'DENY')
                if location:
                    self.send_header('Location', location)
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _abweisen(self, grund):
                self._antwort(403, f'Zugriff abgelehnt: {grund}')

            def do_GET(self):
                try:
                    self._weiterleiten()
                except Exception:
                    # Kein Traceback nach draußen: die fensterlose EXE hat gar
                    # kein stderr, und der Client wartete sonst ohne Antwort.
                    try:
                        self._antwort(500, 'Interner Fehler')
                    except Exception:
                        pass

            def _weiterleiten(self):
                if not _host_erlaubt(self.headers.get('Host')):
                    self._abweisen('unbekannter Host')
                    return
                if not _herkunft_erlaubt(self.headers.get('Origin')):
                    self._abweisen('fremde Herkunft')
                    return
                herkunft = self.headers.get('Sec-Fetch-Site')
                if herkunft and herkunft.lower() not in EIGENE_HERKUNFT:
                    self._abweisen('seitenübergreifende Anfrage')
                    return

                route = urlsplit(self.path).path
                client, event_id, font = state()
                status, body, kind, location = 200, '', 'text/html; charset=utf-8', None
                if route in ('/help', '/live/help'):
                    body = help_text            # Closure, nicht self: self ist der Handler
                elif route in ('/live/strip', '/live/notes'):
                    body = PAGE
                elif route == '/live':
                    if client and event_id:
                        status, location = 302, client.live_url(event_id)
                        body = 'Weiterleitung zur Live-Agenda'
                    else:
                        status, body = 503, 'Kein Event ausgewählt.'
                elif route in ('/live/data.json', '/live/strip.json', '/live/notes.json', '/live/settings.json'):
                    kind = 'application/json; charset=utf-8'
                    try:
                        if route == '/live/settings.json':
                            data = {}
                        else:
                            if not client or not event_id:
                                raise BridgeError('Kein Event ausgewählt.')
                            data = client.snapshot(event_id)
                        body = json.dumps(dict(data, notesFontSize=font))
                    except BridgeError:
                        status, body = 503, '{"error":"Agenda derzeit nicht verfügbar"}'
                else:
                    status, body = 404, 'Nicht gefunden'
                self._antwort(status, body, kind, location)

            def _nur_lesen(self):
                # Bisher beantwortete der Standardhandler das mit 501. Ein
                # klarer 405 ist ehrlicher und einheitlich.
                self._antwort(405, 'Nur GET')

            do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _nur_lesen

        self.http = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        # Handler-Threads nicht am Serverende aufhalten und benennen, damit
        # sie im Diagnosefall zuzuordnen sind.
        self.http.daemon_threads = True
        self.http.block_on_close = False
        # poll_interval klein halten: BaseServer.shutdown() wartet auf das Ende
        # der aktuellen Warteschleife. Mit dem Standardwert 0.5 s fror die
        # Oberfläche bei jedem Neustart gemessene 502 ms ein.
        self.thread = threading.Thread(
            target=lambda: self.http.serve_forever(poll_interval=0.05), daemon=True)
        self.thread.start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()