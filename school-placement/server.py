"""Local-only application; all calculations call the original BlocksNet method."""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import argparse
import json
import threading
import webbrowser
from model import Model, HERE, RESULTS, save

MODEL=None
LOCK=threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def respond(self, data, status=200):
        body=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path=='/api/init':
            exp_path=RESULTS/'experiment.json'
            exp=json.loads(exp_path.read_text(encoding='utf-8')) if exp_path.exists() else None
            if exp and exp['source_hashes']!=MODEL.hashes: exp=None
            self.respond({'geo':MODEL.geo,'meta':MODEL.meta,
                'baseline':MODEL.package(MODEL.baseline,[],'Исходное состояние'),'experiment':exp})
            return
        routes={'/':(HERE/'index.html','text/html; charset=utf-8'),
            '/app.js':(HERE/'app.js','application/javascript; charset=utf-8'),
            '/style.css':(HERE/'style.css','text/css; charset=utf-8'),
            '/leaflet.js':(HERE/'vendor/leaflet.js','application/javascript'),
            '/leaflet.css':(HERE/'vendor/leaflet.css','text/css'),
            '/reference.html':(HERE/'reference/dashboard.html','text/html; charset=utf-8')}
        if self.path not in routes: self.send_error(404);return
        path,mime=routes[self.path]
        body=path.read_bytes()
        self.send_response(200);self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

    def do_POST(self):
        streaming=False
        if self.headers.get('Origin') not in (None,f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):
            self.respond({'error':'Недопустимый источник запроса'},403);return
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':
            self.respond({'error':'Ожидается JSON'},415);return
        try:
            length=int(self.headers.get('Content-Length',0))
            if length<1 or length>100000:raise ValueError('Недопустимый размер запроса')
            data=json.loads(self.rfile.read(length))
            if self.path not in ['/api/scenario','/api/search']:self.send_error(404);return
            if not LOCK.acquire(blocking=False):self.respond({'error':'Идёт другой расчёт. Дождитесь завершения.'},409);return
            try:
                if self.path=='/api/scenario':
                    self.respond(MODEL.scenario(data.get('schools',[])))
                else:
                    capacity=data.get('capacity')
                    MODEL.validate([{'block_id':MODEL.ids[0],'capacity':capacity}])
                    cache=RESULTS/f'search_{capacity}.json'
                    cached=json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else None
                    if cached and (not cached['complete'] or cached['source_hashes']!=MODEL.hashes):cached=None
                    self.send_response(200)
                    self.send_header('Content-Type','application/x-ndjson; charset=utf-8')
                    self.send_header('Cache-Control','no-store');self.end_headers()
                    streaming=True
                    def emit(obj):
                        self.wfile.write((json.dumps(obj,ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8'));self.wfile.flush()
                    def progress(k,n,row):emit({'type':'progress','checked':k,'total':n,'last':row})
                    emit({'type':'start','cached':bool(cached and not data.get('force')),'total':len(MODEL.ids)})
                    result=cached if cached and not data.get('force') else MODEL.search(capacity,progress)
                    if result['complete'] and result is not cached:save(cache,result)
                    scenario=MODEL.scenario([{'block_id':result['best_ids'][0],'capacity':capacity}],'Автоматический') if result['best_ids'] else None
                    emit({'type':'done','search':result,'scenario':scenario})
            finally:LOCK.release()
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as exc:
            self.log_error('%s',exc)
            try:
                if streaming:
                    self.wfile.write((json.dumps({'type':'error','error':str(exc)},ensure_ascii=False)+'\n').encode('utf-8'))
                    self.wfile.flush()
                else:self.respond({'error':str(exc)},400)
            except OSError:pass


def main():
    global MODEL
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    print('Загрузка данных и проверка исходного расчёта BlocksNet…',flush=True)
    MODEL=Model()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Приложение готово: http://127.0.0.1:{server.server_port}',flush=True)
    if not args.no_browser:webbrowser.open(f'http://127.0.0.1:{server.server_port}')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
