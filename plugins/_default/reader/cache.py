"""
阅读器本地缓存。

目录：%APPDATA%/FimtaleClient/reader_cache/
文件：{topic_id}.json  —— 原始 API 响应
      meta.json        —— LRU 索引
      images/          —— 图片缓存
"""
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

from toolmethods import log_warning, log_debug


CACHE_DIR = Path(
    os.getenv("APPDATA", os.path.expanduser("~"))
) / "FimtaleClient" / "reader_cache"

META_FILE = CACHE_DIR / "meta.json"
IMAGE_CACHE_DIR = CACHE_DIR / "images"

MAX_CACHE_ENTRIES = 200
MAX_CACHE_AGE_DAYS = 30

def _ensure_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_meta() -> dict:
    _ensure_dir()
    if not META_FILE.exists():
        return {}
    try:
        with open(META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_meta(meta: dict):
    _ensure_dir()
    try:
        with open(META_FILE, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log_warning(f"[Cache] meta 写入失败: {e}")


def _topic_path(topic_id: int) -> Path:
    return CACHE_DIR / f"{topic_id}.json"

def get(topic_id: int, max_age_days: int = MAX_CACHE_AGE_DAYS) -> Optional[dict]:
    """读取缓存。过期返回 None。"""
    path = _topic_path(topic_id)
    if not path.exists():
        return None

    meta = _load_meta()
    entry = meta.get(str(topic_id))
    if entry:
        age_days = (time.time() - entry.get("saved_at", 0)) / 86400
        if age_days > max_age_days:
            log_debug(f"[Cache] topic {topic_id} 过期（{age_days:.1f} 天）")
            return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def put(topic_id: int, data: dict):
    """写入缓存，并执行 LRU 淘汰。"""
    _ensure_dir()
    path = _topic_path(topic_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError as e:
        log_warning(f"[Cache] topic {topic_id} 写入失败: {e}")
        return

    meta = _load_meta()
    meta[str(topic_id)] = {
        "saved_at": time.time(),
        "accessed_at": time.time(),
    }
    _evict(meta)
    _save_meta(meta)


def touch(topic_id: int):
    """更新访问时间，用于 LRU。"""
    meta = _load_meta()
    key = str(topic_id)
    if key in meta:
        meta[key]["accessed_at"] = time.time()
        _save_meta(meta)


def delete(topic_id: int):
    """删除单个 topic 的缓存（帖子已被删除时调用）"""
    path = _topic_path(topic_id)
    try:
        path.unlink()
    except OSError:
        pass
    meta = _load_meta()
    if str(topic_id) in meta:
        meta.pop(str(topic_id), None)
        _save_meta(meta)

def get_recent_topics(limit: int = 30):
    """
    返回最近访问的 topic 列表：
        [{id, title, parent_title, accessed_at}, ...]
    按 accessed_at 降序。
    """
    meta = _load_meta()
    items = []
    for key, entry in meta.items():
        try:
            tid = int(key)
        except ValueError:
            continue

        title = f"Topic {tid}"
        parent_title = ""

        try:
            path = _topic_path(tid)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                info = data.get("TopicInfo") or {}
                t = info.get("Title", "")
                if t:
                    title = t

                parent = data.get("ParentInfo") or {}
                if isinstance(parent, dict) and parent:
                    pid = parent.get("ID")
                    pt = parent.get("Title", "")
                    if pt and pid != tid:
                        parent_title = pt
        except Exception:
            pass

        items.append({
            "id": tid,
            "title": title,
            "parent_title": parent_title,
            "accessed_at": entry.get("accessed_at", 0),
        })

    items.sort(key=lambda x: x["accessed_at"], reverse=True)
    return items[:limit]


def _evict(meta: dict):
    if len(meta) <= MAX_CACHE_ENTRIES:
        return
    items = sorted(meta.items(), key=lambda kv: kv[1].get("accessed_at", 0))
    to_remove = items[: len(meta) - MAX_CACHE_ENTRIES]
    for key, _ in to_remove:
        p = _topic_path(int(key))
        try:
            p.unlink()
        except OSError:
            pass
        meta.pop(key, None)
    log_debug(f"[Cache] 淘汰 {len(to_remove)} 个旧条目")


def clear():
    """清空全部缓存（包括图片）。"""
    if not CACHE_DIR.exists():
        return
    for f in CACHE_DIR.glob("*.json"):
        try:
            f.unlink()
        except OSError:
            pass
    if IMAGE_CACHE_DIR.exists():
        for f in IMAGE_CACHE_DIR.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass

def image_cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return IMAGE_CACHE_DIR / f"{h}.img"


def has_image(url: str) -> bool:
    return image_cache_path(url).exists()


def read_image(url: str) -> Optional[bytes]:
    path = image_cache_path(url)
    if not path.exists():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def save_image(url: str, data: bytes) -> bool:
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = image_cache_path(url)
    try:
        path.write_bytes(data)
        return True
    except OSError as e:
        log_warning(f"[Cache] 图片写入失败 {url}: {e}")
        return False