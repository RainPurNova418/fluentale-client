import os
import requests

# 看环境变量里有没有代理
print("HTTP_PROXY:", os.environ.get("HTTP_PROXY"))
print("HTTPS_PROXY:", os.environ.get("HTTPS_PROXY"))
print("NO_PROXY:", os.environ.get("NO_PROXY"))

# 看 requests 实际用了什么代理
print("系统代理:", requests.utils.get_environ_proxies(
    "https://p5.toutiaoimg.com/"
))

# 打印 requests 最终使用的代理
s = requests.Session()
print("session proxies:", s.proxies)