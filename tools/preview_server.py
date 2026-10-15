#!/usr/bin/env python3
"""Real local Roleplay Plus workbench preview, without requiring game binaries.

This only hosts the new add-on UI/backend. It does not simulate original
E-mote/CG visuals or make DeepSeek requests. --data controls demo SQLite path.
"""
from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit,parse_qs

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from studio.roleplay_plus import bridge

class PreviewHandler(BaseHTTPRequestHandler):
    server_version="RoleplayPlusPreview/0.14"
    def reply(self,status,obj,content_type="application/json; charset=utf-8"):
        if not isinstance(obj,bytes):
            obj=json.dumps(obj,ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(obj)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy",
            "default-src 'self'; script-src 'self';style-src 'self';"
            "connect-src 'self';img-src 'self' data:;object-src 'none'")
        self.end_headers();self.wfile.write(obj)
    def do_GET(self):
        request=urlsplit(self.path)
        path=request.path
        try:
            if path=="/":
                self.send_response(302)
                self.send_header("Location","/roleplay/")
                self.send_header("Content-Length","0")
                self.end_headers()
                return
            if not bridge.try_get(self,path,parse_qs(request.query)):
                self.reply(404,{"error":"未知地址"})
        except (ValueError,RuntimeError,OSError) as e:
            self.reply(400,{"error":str(e)[:300]})
    def do_POST(self):
        path=urlsplit(self.path).path
        try:
            origin=self.headers.get("Origin")
            host=f"http://127.0.0.1:{self.server.server_port}"
            if origin and origin!=host:raise ValueError("Origin 不匹配")
            n=int(self.headers.get("Content-Length","0"))
            if not 1<=n<=1024*1024:raise ValueError("请求体不能超过 1MB")
            value=json.loads(self.rfile.read(n))
            if not bridge.try_post(self,path,value):self.reply(404,{"error":"未知 API"})
        except (ValueError,RuntimeError,TypeError,json.JSONDecodeError) as e:
            self.reply(400,{"error":str(e)[:300]})

def make_server(data,port=0):
    path=Path(data)
    path.mkdir(parents=True,exist_ok=True)
    bridge.initialize(path/"preview.sqlite3",{
        "role_name":"千岁","persona":"温柔、自然、善于表达自己的看法。"})
    return ThreadingHTTPServer(("127.0.0.1",port),PreviewHandler)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--port",type=int,default=8765)
    ap.add_argument("--data",help="用于演示的 SQLite 数据目录。默认临时目录，退出自动清理。")
    args=ap.parse_args()
    if args.data:
        server=make_server(args.data,args.port)
        try:run(server)
        finally:server.server_close()
    else:
        with TemporaryDirectory(prefix="rpplus_demo_") as temp:
            server=make_server(temp,args.port)
            try:run(server)
            finally:server.server_close()

def run(server):
    print(f"\nRoleplay Plus 独立预览：http://127.0.0.1:{server.server_port}/roleplay/")
    print("仅验证新模块，不包括原游戏背景/CG/语音或真实 DeepSeek API。Ctrl+C 退出。")
    try:server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:pass
    finally:server.shutdown()

if __name__=="__main__":main()
