import time
import socket
import ssl
import requests

HOST = "p5.toutiaoimg.com"
URL = "https://p5.toutiaoimg.com"

# ── 1. DNS ──
t = time.time()
try:
    ip = socket.gethostbyname(HOST)
    print(f"[1] DNS: {ip}  {time.time() - t:.2f}s", flush=True)
except Exception as e:
    print(f"[1] DNS 失败: {e}", flush=True)
    raise

# ── 2. TCP 连接 ──
t = time.time()
try:
    sock = socket.create_connection((HOST, 443), timeout=10)
    print(f"[2] TCP: {time.time() - t:.2f}s", flush=True)
except Exception as e:
    print(f"[2] TCP 失败: {e}", flush=True)
    raise

# ── 3. SSL 握手 ──
t = time.time()
ctx = ssl.create_default_context()
ssock = ctx.wrap_socket(sock, server_hostname=HOST)
print(f"[3] SSL: {time.time() - t:.2f}s", flush=True)
ssock.close()

# ── 4. 完整 requests ──
t = time.time()
r = requests.get(URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
print(f"[4] requests: {r.status_code}  {len(r.content)} bytes  "
      f"{time.time() - t:.2f}s", flush=True)

# ── 5. 第二次 requests（复用连接池）──
t = time.time()
r = requests.get(URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
print(f"[5] requests 第二次: {r.status_code}  {time.time() - t:.2f}s", flush=True)

# ── 6. Session 复用 ──
t = time.time()
with requests.Session() as s:
    s.headers["User-Agent"] = "Mozilla/5.0"
    s.get(URL, timeout=30)   # 预热
    t2 = time.time()
    s.get(URL, timeout=30)   # 复用连接
    print(f"[6] Session 第二次: {time.time() - t2:.2f}s", flush=True)