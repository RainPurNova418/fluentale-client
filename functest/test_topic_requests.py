import sys
import time
import requests

URL = "https://p5.toutiaoimg.com/origin/ff5c00033a9f36c704f3"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

print(">>> 开始请求", flush=True)
t0 = time.time()

r = requests.get(URL, timeout=15, headers=HEADERS)

t1 = time.time()
print(f">>> 响应 {r.status_code}，{len(r.content)} bytes，耗时 {t1 - t0:.2f}s",
      flush=True)