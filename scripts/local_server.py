#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import argparse,json
p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--port',type=int,default=8791);p.add_argument('--token',required=True);a=p.parse_args()
root=Path(a.directory).resolve()
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kw):super().__init__(*args,directory=str(root),**kw)
    def do_GET(self):
        if self.path=='/__health':
            b=json.dumps({'service':'tidestone-local','token':a.token,'directory':str(root)}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b);return
        super().do_GET()
    def end_headers(self):
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');super().end_headers()
    def list_directory(self,path):self.send_error(404,'No directory listing');return None
ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
