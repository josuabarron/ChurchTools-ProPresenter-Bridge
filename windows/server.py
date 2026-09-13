import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from core import BridgeError

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


class Server:
    def __init__(self, port, state):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                route = urlsplit(self.path).path
                client, event_id, font = state()
                status, body, kind, location = 200, '', 'text/html; charset=utf-8', None
                if route in ('/help', '/live/help'):
                    body = Path(__file__).with_name('help.html').read_text(encoding='utf-8')
                elif route in ('/live/strip', '/live/notes'):
                    body = PAGE
                elif route == '/live':
                    if client and event_id:
                        status, location = 302, client.live_url(event_id)
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
                encoded = body.encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', kind)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                if location:
                    self.send_header('Location', location)
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
        self.http = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
