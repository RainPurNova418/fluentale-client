import re
from dataclasses import dataclass, field
from typing import Optional, List

import requests

from toolmethods import log_warning, log_debug
from plugins._default.login import CredentialStore


DEFAULT_SERVER = "fimtale.com"
TIMEOUT = 15
USER_AGENT = "FluentTaleClient"

_last_raw: dict = {}


# ── 异常 ──

class ApiError(Exception):
    pass


class NotFoundError(ApiError):
    pass


class NotAuthenticatedError(ApiError):
    pass


class RateLimitError(ApiError):
    pass


# ── 数据模型 ──

@dataclass
class Tag:
    type: str = ""
    source: str = ""
    rate: str = ""
    length: str = ""
    status: str = ""
    other: List[str] = field(default_factory=list)


@dataclass
class Chapter:
    id: int
    title: str


@dataclass
class Author:
    id: int
    name: str
    homepage: str = ""
    intro: str = ""
    background: str = ""
    badges: List[str] = field(default_factory=list)


@dataclass
class Topic:
    id: int
    title: str
    author_id: int
    author_name: str
    content: str
    content_format: str

    intro: str = ""
    background: str = ""
    tags: Tag = field(default_factory=Tag)

    views: int = 0
    comments: int = 0
    followers: int = 0
    highpraise: int = 0
    rating: str = ""
    word_count: int = 0
    image_count: int = 0
    chapter_count: int = 0

    is_chapter: bool = False
    is_favorite: bool = False
    my_vote: str = ""

    date_created: int = 0
    date_updated: int = 0

    menu: List[Chapter] = field(default_factory=list)

    parent_id: Optional[int] = None
    parent_title: str = ""

    branches: dict = field(default_factory=dict)
    is_custom_branch: bool = False

    author: Optional[Author] = None

def _load_credentials():
    store = CredentialStore()
    cred = store.load()
    if not cred:
        raise NotAuthenticatedError("未登录，请先登录账号")
    api_key = cred.get("api_key", "")
    api_pass = cred.get("api_pass", "")
    if not api_key or not api_pass:
        raise NotAuthenticatedError("凭据不完整，请重新登录")
    server = cred.get("server", "") or DEFAULT_SERVER
    return api_key, api_pass, server

def _request(topic_id: int, api_key: str, api_pass: str, server: str,
             fmt: Optional[str] = None) -> dict:
    base = server.rstrip("/")
    if not base.startswith("http"):
        base = f"https://{base}"
    url = f"{base}/api/v1/t/{topic_id}"

    params = {"APIKey": api_key, "APIPass": api_pass}
    if fmt:
        params["format"] = fmt

    try:
        r = requests.get(
            url, params=params, timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
    except requests.Timeout:
        raise ApiError(f"请求超时: topic {topic_id}")
    except requests.RequestException as e:
        raise ApiError(f"请求失败: {e}")

    if r.status_code == 404:
        raise NotFoundError(f"Topic {topic_id} 不存在或已删除")
    if r.status_code == 429:
        raise RateLimitError("触发 FimTale 限流，请稍后再试")
    if r.status_code != 200:
        raise ApiError(f"HTTP {r.status_code}: {r.text[:120]}")

    try:
        return r.json()
    except ValueError:
        raise ApiError(f"响应非 JSON: {r.text[:120]}")

_MD_IMG_RE = re.compile(r'!\[[^\]]*\]\([^)]*\)')


def _count_md_images(text: str) -> int:
    return len(_MD_IMG_RE.findall(text))


def _pick_content(md_data: dict, html_fetcher) -> tuple:
    info = md_data.get("TopicInfo", {}) or {}
    md_content = info.get("Content", "") or ""
    expected = info.get("ImageCount", 0) or 0
    md_img = _count_md_images(md_content)
    if expected > md_img:
        log_warning(
            f"[Reader] Topic {info.get('ID')}: "
            f"md 图 {md_img}/{expected}，回退 HTML"
        )
        html_data = html_fetcher()
        return html_data["TopicInfo"].get("Content", "") or "", "html"
    return md_content, "md"

def _parse_tag(tags_data) -> Tag:
    if not isinstance(tags_data, dict):
        return Tag()
    return Tag(
        type=tags_data.get("Type", "") or "",
        source=tags_data.get("Source", "") or "",
        rate=tags_data.get("Rate", "") or "",
        length=tags_data.get("Length", "") or "",
        status=tags_data.get("Status", "") or "",
        other=list(tags_data.get("OtherTags", []) or []),
    )


def _parse_menu(menu_data) -> List[Chapter]:
    if not isinstance(menu_data, list):
        return []
    result = []
    for item in menu_data:
        if not isinstance(item, dict):
            continue
        cid = item.get("ID")
        if cid is None:
            continue
        result.append(Chapter(id=int(cid), title=item.get("Title", "") or ""))
    return result


def _parse_branches(branches_data) -> dict:
    """
    互动文的分支：{分支名: topic_id}

    容错处理非 int 值（比如嵌套 dict 带 ID 字段）。
    普通文的 Branches 通常是 {"下一章": xxx}，空字符串也当作无分支。
    """
    if not isinstance(branches_data, dict):
        return {}
    result = {}
    for name, tid in branches_data.items():
        if isinstance(tid, int):
            result[name] = tid
        elif isinstance(tid, dict) and "ID" in tid:
            try:
                result[name] = int(tid["ID"])
            except (TypeError, ValueError):
                continue
    return result


def _parse_author(author_data) -> Optional[Author]:
    if not isinstance(author_data, dict):
        return None
    return Author(
        id=author_data.get("ID", 0) or 0,
        name=author_data.get("UserName", "") or "",
        homepage=author_data.get("UserHomepage", "") or "",
        intro=author_data.get("UserIntro", "") or "",
        background=author_data.get("Background", "") or "",
        badges=list(author_data.get("Badges", []) or []),
    )


def _parse_topic(data: dict, content: str, fmt: str) -> Topic:
    info = data.get("TopicInfo", {}) or {}
    parent = data.get("ParentInfo") or {}

    parent_id = None
    parent_title = ""
    is_custom_branch = False
    if isinstance(parent, dict) and parent:
        parent_id = parent.get("ID")
        parent_title = parent.get("Title", "") or ""
        is_custom_branch = bool(parent.get("IsCustomBranch", False))

    return Topic(
        id=info.get("ID", 0) or 0,
        title=info.get("Title", "") or "",
        author_id=info.get("UserID", 0) or 0,
        author_name=info.get("UserName", "") or "",
        content=content,
        content_format=fmt,

        intro=info.get("Intro", "") or "",
        background=info.get("Background", "") or "",
        tags=_parse_tag(info.get("Tags", {})),

        views=info.get("Views", 0) or 0,
        comments=info.get("Comments", 0) or 0,
        followers=info.get("Followers", 0) or 0,
        highpraise=info.get("HighPraise", 0) or 0,
        rating=info.get("rating", "") or "",
        word_count=info.get("WordCount", 0) or 0,
        image_count=info.get("ImageCount", 0) or 0,
        chapter_count=info.get("ChapterCount", 0) or 0,

        is_chapter=bool(info.get("IsChapter", False)),
        is_favorite=bool(info.get("IsFavorite", False)),
        my_vote=info.get("MyVote", "") or "",

        date_created=info.get("DateCreated", 0) or 0,
        date_updated=info.get("DateUpdated", 0) or 0,

        menu=_parse_menu(data.get("Menu", [])),

        parent_id=parent_id,
        parent_title=parent_title,

        branches=_parse_branches(info.get("Branches")),
        is_custom_branch=is_custom_branch,

        author=_parse_author(data.get("AuthorInfo")),
    )

def fetch_topic(topic_id: int) -> Topic:
    global _last_raw
    api_key, api_pass, server = _load_credentials()

    log_debug(f"[Reader] fetch_topic id={topic_id}")

    md_data = _request(topic_id, api_key, api_pass, server, fmt="md")
    if md_data.get("Status") != 1:
        raise ApiError(
            f"Topic {topic_id}: Status={md_data.get('Status')} "
            f"Message={md_data.get('Message', '')}"
        )

    def _fetch_html():
        return _request(topic_id, api_key, api_pass, server, fmt=None)

    content, fmt = _pick_content(md_data, _fetch_html)
    md_data["TopicInfo"]["ContentFormat"] = fmt
    _last_raw = md_data
    return _parse_topic(md_data, content, fmt)


def last_raw_response() -> dict:
    return _last_raw or {}


def parse_cached(raw: dict) -> Topic:
    info = raw.get("TopicInfo", {}) or {}
    content = info.get("Content", "") or ""
    fmt = info.get("ContentFormat", "md")
    return _parse_topic(raw, content, fmt)