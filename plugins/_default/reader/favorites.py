# plugins/_default/reader/favorites.py
# coding: utf-8
"""
阅读器收藏。

存储：%APPDATA%/FimtaleClient/favorites.json
结构：{topic_id_str: {title, author, added_at}}
"""
import json
import os
import time
from pathlib import Path
from typing import List, Dict

from toolmethods import log_warning


DATA_DIR = Path(
    os.getenv("APPDATA", os.path.expanduser("~"))
) / "FimtaleClient"

FAV_FILE = DATA_DIR / "favorites.json"


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load() -> Dict[str, dict]:
    _ensure_dir()
    if not FAV_FILE.exists():
        return {}
    try:
        with open(FAV_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: Dict[str, dict]):
    _ensure_dir()
    try:
        with open(FAV_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log_warning(f"[Favorites] 写入失败: {e}")


def is_favorite(topic_id: int) -> bool:
    return str(topic_id) in _load()


def add(topic_id: int, title: str, author: str = ""):
    data = _load()
    data[str(topic_id)] = {
        "title": title or "",
        "author": author or "",
        "added_at": time.time(),
    }
    _save(data)


def remove(topic_id: int):
    data = _load()
    if str(topic_id) in data:
        data.pop(str(topic_id))
        _save(data)


def toggle(topic_id: int, title: str, author: str = "") -> bool:
    """返回 True = 当前已收藏；False = 已取消"""
    if is_favorite(topic_id):
        remove(topic_id)
        return False
    add(topic_id, title, author)
    return True


def list_all() -> List[dict]:
    """按收藏时间降序。每项：{id, title, author, added_at}"""
    data = _load()
    items = []
    for key, entry in data.items():
        try:
            tid = int(key)
        except ValueError:
            continue
        items.append({
            "id": tid,
            "title": entry.get("title", "") or "",
            "author": entry.get("author", "") or "",
            "added_at": entry.get("added_at", 0),
        })
    items.sort(key=lambda x: x["added_at"], reverse=True)
    return items


def count() -> int:
    return len(_load())