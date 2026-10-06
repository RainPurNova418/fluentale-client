"""
测试 IPv6 回退导致的 TCP 连接慢问题。
跑法：python test_ipv4.py
"""
import socket
import time

URL = "https://p5.toutiaoimg.com"
HOST = "p5.toutiaoimg.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}

print("=== DNS 解析结果 ===", flush=True)
try:
    infos = socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
    for info in infos:
        print(f"  family={info[0].name}  addr={info[4][0]}", flush=True)
except Exception as e:
    print(f"  DNS 失败: {e}", flush=True)

print("\n=== 测试 1: 默认 requests ===", flush=True)
import requests
t = time.time()
try:
    r = requests.get(URL, timeout=30, headers=HEADERS)
    print(f"  结果: {r.status_code}, {len(r.content)} bytes, "
          f"耗时 {time.time() - t:.2f}s", flush=True)
except Exception as e:
    print(f"  失败: {e}, 耗时 {time.time() - t:.2f}s", flush=True)

print("\n=== 测试 2: 强制 IPv4（urllib3 hook）===", flush=True)
import urllib3.util.connection as urllib3_cn

def _allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = _allowed_gai_family

t = time.time()
try:
    r = requests.get(URL, timeout=30, headers=HEADERS)
    print(f"  结果: {r.status_code}, {len(r.content)} bytes, "
          f"耗时 {time.time() - t:.2f}s", flush=True)
except Exception as e:
    print(f"  失败: {e}, 耗时 {time.time() - t:.2f}s", flush=True)

print("\n=== 测试 3: Session 复用（第 2 次请求）===", flush=True)
s = requests.Session()
s.headers.update(HEADERS)

t = time.time()
r = s.get(URL, timeout=30)
print(f"  第一次: {r.status_code}, {len(r.content)} bytes, "
      f"耗时 {time.time() - t:.2f}s", flush=True)

t = time.time()
r = s.get(URL, timeout=30)
print(f"  第二次: {r.status_code}, {len(r.content)} bytes, "
      f"耗时 {time.time() - t:.2f}s", flush=True)