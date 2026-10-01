# plugins/_default/reader/loader.py
# coding: utf-8
"""
后台加载器：多线程 + 信号回主线程
"""
import os
import re
import socket
import threading
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3.util.connection as urllib3_cn

from PySide6.QtCore import QObject, Signal
from tqdm import tqdm

from toolmethods import log_warning, log_debug

from . import api, cache
from .api import Topic, ApiError, NotFoundError


# ══════════════════════════════════════════════════════════════
#  强制 IPv4（绕过 IPv6 回退的 20 秒超时）
# ══════════════════════════════════════════════════════════════

def _allowed_gai_family_ipv4():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = _allowed_gai_family_ipv4


# ══════════════════════════════════════════════════════════════
#  全局 Session
# ══════════════════════════════════════════════════════════════

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_session = None
_session_lock = threading.Lock()


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                s = requests.Session()
                s.headers.update(BROWSER_HEADERS)
                _session = s
    return _session


# ══════════════════════════════════════════════════════════════
#  图片 URL 提取
# ══════════════════════════════════════════════════════════════

_IMG_URL_RE = re.compile(r'!\[[^\]]*\]\(\s*(\S+?)(?:\s+["\'][^"\']*["\'])?\s*\)')


def _extract_image_urls(content: str):
    return _IMG_URL_RE.findall(content or "")


# ══════════════════════════════════════════════════════════════
#  加载工作线程
# ══════════════════════════════════════════════════════════════

class LoadWorker(QObject):
    started = Signal(int)
    meta_ready = Signal(int, object)
    content_ready = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal(int)
    image_progress = Signal(int, int, int)

    def __init__(self, topic_id: int, force_refresh: bool = False, parent=None):
        super().__init__(parent)
        self.topic_id = topic_id
        self.force_refresh = force_refresh

    def run(self):
        self.started.emit(self.topic_id)
        topic = None
        try:
            topic = self._load()
        except NotFoundError as e:
            cache.delete(self.topic_id)
            self.failed.emit(self.topic_id, f"找不到帖子：{e}")
        except ApiError as e:
            self.failed.emit(self.topic_id, f"加载失败：{e}")
        except Exception as e:
            self.failed.emit(self.topic_id, f"意外错误：{e}")

        if topic is not None:
            self.meta_ready.emit(self.topic_id, topic)
            self._download_images(topic)
            self.content_ready.emit(self.topic_id, topic)

        self.finished.emit(self.topic_id)

    def _load(self) -> Topic:
        if not self.force_refresh:
            cached = cache.get(self.topic_id)
            if cached:
                cache.touch(self.topic_id)
                return api.parse_cached(cached)

        topic = api.fetch_topic(self.topic_id)
        raw = api.last_raw_response()
        if raw:
            cache.put(self.topic_id, raw)
        return topic

    def _download_images(self, topic):
        urls = _extract_image_urls(topic.content or "")
        total = len(urls)
        if not total:
            return

        log_debug(f"[Loader] Topic {topic.id}: 发现 {total} 张图片待下载")

        done = 0
        ok = 0
        failed = 0
        self.image_progress.emit(self.topic_id, 0, total)

        s = _get_session()

        pbar = tqdm(
            urls,
            desc=f"Images[{topic.id}]",
            unit="张",
            leave=False,
            ncols=80,
        )

        for url in pbar:
            data = cache.read_image(url) if cache.has_image(url) else None
            if data and len(data) > 0:
                done += 1
                ok += 1
                self.image_progress.emit(self.topic_id, done, total)
                pbar.set_postfix_str(f"hit {ok}")
                continue

            success = False
            try:
                r = s.get(url, timeout=30)
                if r.status_code == 200 and len(r.content) > 0:
                    cache.save_image(url, r.content)
                    success = True
                else:
                    log_warning(
                        f"[Loader] 图片下载失败 ({r.status_code}, "
                        f"{len(r.content)} bytes): {url}"
                    )
            except Exception as e:
                log_warning(f"[Loader] 图片下载异常 {url}: {e}")

            done += 1
            if success:
                ok += 1
            else:
                failed += 1
            self.image_progress.emit(self.topic_id, done, total)
            pbar.set_postfix_str(f"ok {ok} fail {failed}")

        pbar.close()
        print(flush=True)   # tqdm 结束后换行，避免日志顶残影

        if failed:
            log_warning(
                f"[Loader] Topic {topic.id}: 图片下载 "
                f"{ok}/{total} 成功，{failed} 失败"
            )
        else:
            log_debug(f"[Loader] Topic {topic.id}: 图片下载全部完成 {ok}/{total}")


# ══════════════════════════════════════════════════════════════
#  全局线程池
# ══════════════════════════════════════════════════════════════

class Loader:
    def __init__(self, max_workers: int = None):
        if max_workers is None:
            cpu = os.cpu_count() or 2
            max_workers = min(4, max(1, cpu // 2))
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def submit(self, worker: LoadWorker):
        self.executor.submit(worker.run)

    def shutdown(self):
        self.executor.shutdown(wait=False)


_loader: Loader = None


def get_loader() -> Loader:
    global _loader
    if _loader is None:
        _loader = Loader()
    return _loader