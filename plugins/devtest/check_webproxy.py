import os
import requests

print("HTTP_PROXY:", os.environ.get("HTTP_PROXY"))
print("HTTPS_PROXY:", os.environ.get("HTTPS_PROXY"))
print("NO_PROXY:", os.environ.get("NO_PROXY"))

print("系统代理:", requests.utils.get_environ_proxies(
    "https://p5.toutiaoimg.com/"
))

s = requests.Session()
print("session proxies:", s.proxies)