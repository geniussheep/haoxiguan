#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
杨妙绮好习惯魔法存折 - 服务端服务 (SQLite 驱动版)
支持本地与生产环境多设备（手机/电脑/iPad）实时同步与 SQLite 永久存储
支持 HTTP 206 Partial Content (针对 Safari/Chrome 音频流式传输) 与静默异常过滤
"""

import argparse
import http.server
import json
import os
import socket
import socketserver
import subprocess
import sys
import webbrowser

from db import HabitDB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "habit.db")
JSON_FILE = os.path.join(BASE_DIR, "data.json")

# 全局数据库实例
db = None

def get_best_lan_ip():
    """获取本机最佳局域网真实 IP 地址"""
    if sys.platform == 'darwin':
        for iface in ['en0', 'en1', 'en2']:
            try:
                res = subprocess.check_output(['ipconfig', 'getifaddr', iface], stderr=subprocess.DEVNULL).decode('utf-8').strip()
                if res and not res.startswith('127.'):
                    return res
            except Exception:
                pass

    if sys.platform == 'win32':
        candidates = []
        try:
            output = subprocess.check_output('ipconfig', shell=True).decode('gbk', errors='ignore')
            current_adapter = ""
            for line in output.splitlines():
                line_str = line.strip()
                if "adapter" in line or "适配器" in line:
                    current_adapter = line_str
                if "IPv4" in line_str:
                    parts = line_str.split(":")
                    if len(parts) >= 2:
                        ip = parts[1].strip()
                        if not ip.startswith('127.') and not ip.startswith('169.254.'):
                            score = 0
                            if ip.startswith('192.168.'): score = 100
                            elif ip.startswith('10.'): score = 90
                            elif ip.startswith('172.') and 'vEthernet' not in current_adapter: score = 80
                            elif 'Mihomo' in current_adapter or 'Clash' in current_adapter: score = 10
                            else: score = 50
                            candidates.append((score, ip, current_adapter))
        except Exception:
            pass

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('223.5.5.5', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

class RangeFileWrapper:
    """包装分片文件读取，支持 Safari/Chrome 音频流式分段读取 (HTTP 206 Partial Content)"""
    def __init__(self, f, length):
        self.f = f
        self.remaining = length

    def read(self, size=-1):
        if self.remaining <= 0:
            return b''
        if size < 0 or size > self.remaining:
            size = self.remaining
        data = self.f.read(size)
        self.remaining -= len(data)
        return data

    def close(self):
        self.f.close()

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def translate_path(self, path):
        # 兼容 /xiguan 前缀
        if path.startswith('/xiguan/'):
            path = '/' + path[len('/xiguan/'):]
        elif path == '/xiguan':
            path = '/'
        return super().translate_path(path)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Range')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isfile(path) and 'Range' in self.headers:
            range_header = self.headers.get('Range', '').strip()
            if range_header.startswith('bytes='):
                try:
                    file_size = os.path.getsize(path)
                    ranges = range_header[6:].split('-')
                    start = int(ranges[0]) if ranges[0] else 0
                    end = int(ranges[1]) if ranges[1] else file_size - 1
                    if end >= file_size:
                        end = file_size - 1
                    if start > end:
                        self.send_error(416, "Requested Range Not Satisfiable")
                        return None
                    
                    length = end - start + 1
                    f = open(path, 'rb')
                    f.seek(start)
                    
                    self.send_response(206)
                    ctype = self.guess_type(path)
                    self.send_header('Content-Type', ctype)
                    self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                    self.send_header('Content-Length', str(length))
                    self.send_header('Accept-Ranges', 'bytes')
                    self.end_headers()
                    return RangeFileWrapper(f, length)
                except Exception:
                    pass
        return super().send_head()

    def copyfile(self, source, outputfile):
        try:
            super().copyfile(source, outputfile)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def do_GET(self):
        clean_path = self.path.split('?')[0]
        if clean_path.startswith('/xiguan/'):
            clean_path = '/' + clean_path[len('/xiguan/'):]
        elif clean_path == '/xiguan':
            clean_path = '/'

        # API: 从 SQLite 读取存折数据
        if clean_path == '/api/data':
            try:
                data = db.get_state() if db else {}
            except Exception as e:
                print(f"[API] 读取 SQLite 数据异常: {e}")
                data = {}

            content = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            try:
                self.wfile.write(content)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass
            return

        if clean_path == '/favicon.ico' and not os.path.exists(os.path.join(BASE_DIR, 'favicon.ico')):
            self.send_response(204)
            self.end_headers()
            return

        try:
            super().do_GET()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def do_POST(self):
        clean_path = self.path.split('?')[0]
        if clean_path.startswith('/xiguan/'):
            clean_path = '/' + clean_path[len('/xiguan/'):]
        elif clean_path == '/xiguan':
            clean_path = '/'

        # API: 保存存折数据到 SQLite
        if clean_path == '/api/data':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                parsed = json.loads(body)
                
                success = db.save_state(parsed) if db else False
                if not success:
                    raise Exception("SQLite save_state returned False")

                resp = json.dumps({'status': 'ok'}).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass
            except Exception as e:
                print(f"[API] 保存 SQLite 失败: {e}")
                self.send_response(500)
                self.end_headers()
            return

        self.send_response(404)
        self.end_headers()

class QuietThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc_type, _, _ = sys.exc_info()
        if exc_type in (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            return
        super().handle_error(request, client_address)

def main():
    parser = argparse.ArgumentParser(description="好习惯魔法存折服务 (SQLite 驱动)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="监听端口 (默认 8080)")
    parser.add_argument("--db", default=None, help="SQLite 数据库文件路径 (默认 habit.db)")
    parser.add_argument("--json", default=None, help="JSON 备份/迁移文件路径 (默认 data.json)")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    global db, DB_FILE, JSON_FILE
    if args.db:
        DB_FILE = os.path.abspath(args.db)
    if args.json:
        JSON_FILE = os.path.abspath(args.json)

    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    os.chdir(BASE_DIR)

    # 初始化并连接 SQLite
    db = HabitDB(DB_FILE, JSON_FILE)

    lan_ip = get_best_lan_ip()
    url = f"http://{lan_ip}:{args.port}/"
    local_url = f"http://localhost:{args.port}/"

    print("=" * 66)
    print("  杨妙绮“好习惯魔法存折”服务已启动！(SQLite 驱动版)")
    print("=" * 66)
    print(f">> 局域网访问: {url}")
    print(f">> 本机访问:   {local_url}")
    print(f">> 数据库文件: {DB_FILE}")
    print(f">> 备份数据:   {JSON_FILE}")
    print("=" * 66)

    if not args.no_browser:
        try:
            webbrowser.open(local_url)
        except Exception:
            pass

    try:
        with QuietThreadingTCPServer((args.host, args.port), CustomHandler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已安全退出。祝妙绮小公主天天进步！✨")
    except Exception as e:
        print(f"\n启动失败: {e}")

if __name__ == '__main__':
    main()
