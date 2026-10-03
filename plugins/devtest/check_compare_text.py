# tools/sample_topics.py
# -*- coding: utf-8 -*-
"""
随机采样 FimTale 帖子，对比 md 和 html 两种格式的差异。

用法：
    1. 填 API_KEY / API_PASS
    2. python tools/sample_topics.py
    3. 查看控制台汇总 + samples/ 目录下的原始 JSON
"""
import re, sys, time, random, json, os
from pathlib import Path
from plugins._default.login import CredentialStore

import requests


# ══════════════════════════════════════════════════════════════
#  配置区
# ═════════════════════════════════════════════════════════════

_cred = CredentialStore().load()
if not _cred:
    print("未登录，无法使用此脚本")
    sys.exit(1)

API_KEY = _cred.get("api_key", "")
API_PASS = _cred.get("api_pass", "")
BASE = "https://fimtale.com"

# 手动指定的 ID，优先采样
MANUAL_IDS = [
    1431,      # Shortcode 系统说明
    15169,     # 已知 md 丢折叠块
    # 4,       # 用户手册
    # 85171,   # 之前的例子
]

# 按 ID 区间分段采样，覆盖早期 / 中期 / 近期 / 最新
RANGES = [
    (100,   999),      # 早期
    (5000,  20000),    # 中期
    (30000, 60000),    # 近期
    (80000, 99999),    # 最新
]
PER_RANGE = 3          # 每段抽几个
SLEEP = 3.5            # 每次请求间隔（秒），防 429
TIMEOUT = 15           # 单次请求超时

OUT_DIR = (
    Path(os.getenv("APPDATA", os.path.expanduser("~")))
    / "FimtaleClient" / "devtest_samples"
)


# ══════════════════════════════════════════════════════════════
#  请求
# ══════════════════════════════════════════════════════════════

class NotFound(Exception):
    """404：帖子不存在或已删除"""
    pass


def fetch(topic_id: int, fmt: str = None) -> dict:
    """拉一个帖子的 JSON。fmt='md' 走 Markdown，否则默认 HTML。"""
    url = f"{BASE}/api/v1/t/{topic_id}"
    params = {"APIKey": API_KEY, "APIPass": API_PASS}
    if fmt:
        params["format"] = fmt
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code == 404:
        raise NotFound(topic_id)
    r.raise_for_status()
    return r.json()


# ══════════════════════════════════════════════════════════════
#  标记剥离（粗估纯文本长度）
# ══════════════════════════════════════════════════════════════

def strip_md(text: str) -> str:
    text = re.sub(r'!\[([^\]]*)\]\([^)]*\)', '', text)      # 图片整删（对齐 html）
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'(\*\*|__)(.*?)\1', r'\2', text)
    text = re.sub(r'(\*|_)(.*?)\1', r'\2', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[=\-]{3,}\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^>\s?', '', text, flags=re.MULTILINE)   # 新增：剥引用符号
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`([^`]*)`', r'\1', text)
    text = re.sub(r'\s+', '', text)
    return text


def strip_html(text: str) -> str:
    text = re.sub(r'<img[^>]*>', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    text = text.replace('&lt;', '<').replace('&gt;', '>')
    text = re.sub(r'\s+', '', text)
    return text


# ══════════════════════════════════════════════════════════════
#  计数
# ══════════════════════════════════════════════════════════════

def count_md_img(t):    return len(re.findall(r'!\[[^\]]*\]\([^)]*\)', t))
def count_html_img(t):  return len(re.findall(r'<img[^>]*>', t))
def count_md_link(t):   return len(re.findall(r'(?<!!)\[[^\]]*\]\([^)]*\)', t))
def count_html_link(t): return len(re.findall(r'<a\s[^>]*>', t))
def count_md_head(t):   return len(re.findall(r'^#{1,6}\s+', t, flags=re.MULTILINE))
def count_html_head(t): return len(re.findall(r'<h[1-6][^>]*>', t, flags=re.MULTILINE))


# ══════════════════════════════════════════════════════════════
#  单条对比
# ══════════════════════════════════════════════════════════════

def compare(tid: int):
    """
    返回 (result_dict, None) 成功；
    返回 (None, reason) 失败，reason ∈ {'404', 'md_error', 'html_error', 'status'}
    """
    # 拉 md
    try:
        md = fetch(tid, "md")
    except NotFound:
        return None, "404"
    except Exception as e:
        print(f"  [skip] {tid}: md 请求失败 {e}")
        return None, "md_error"
    time.sleep(SLEEP)

    # 拉 html
    try:
        html = fetch(tid)
    except NotFound:
        return None, "404"
    except Exception as e:
        print(f"  [skip] {tid}: html 请求失败 {e}")
        return None, "html_error"
    time.sleep(SLEEP)

    if md.get("Status") != 1 or html.get("Status") != 1:
        return None, "status"

    md_c = md["TopicInfo"]["Content"]
    html_c = html["TopicInfo"]["Content"]

    # 每次写入前确保目录存在（防止 CWD 或权限变化导致目录丢失）
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    (OUT_DIR / f"{tid}.md.json").write_text(
        json.dumps(md, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"{tid}.html.json").write_text(
        json.dumps(html, ensure_ascii=False, indent=2), encoding="utf-8")

    md_len = len(strip_md(md_c))
    html_len = len(strip_html(html_c))
    is_image_post = (md_len < 50 and html_len < 50)
    if is_image_post:
        ratio = 1.0
    else:
        ratio = md_len / html_len if html_len else 0

    return {
        "id": tid,
        "title": md["TopicInfo"]["Title"][:40],
        "md_len": md_len,
        "html_len": html_len,
        "ratio": ratio,
        "md_img": count_md_img(md_c),
        "html_img": count_html_img(html_c),
        "expected_img": md["TopicInfo"].get("ImageCount", 0),
        "md_link": count_md_link(md_c),
        "html_link": count_html_link(html_c),
        "md_head": count_md_head(md_c),
        "html_head": count_html_head(html_c),
    }, None


# ══════════════════════════════════════════════════════════════
#  采样：手动 ID + 每个区间随机抽 N 个，404 自动换
# ══════════════════════════════════════════════════════════════

def sample_ids():
    """返回最终的采样 ID 列表（已排序去重）"""
    picked = set()

    # 1. 手动
    for tid in MANUAL_IDS:
        picked.add(tid)

    # 2. 每个区间随机抽，404 重抽
    for lo, hi in RANGES:
        got = 0
        retry = 0
        while got < PER_RANGE and retry < PER_RANGE * 20:
            retry += 1
            tid = random.randint(lo, hi)
            if tid in picked:
                continue

            # 先探测 md（便宜）
            try:
                fetch(tid, "md")
                picked.add(tid)
                got += 1
            except NotFound:
                continue
            except Exception as e:
                print(f"  [skip] {tid}: 预检失败 {e}")
                continue
            finally:
                time.sleep(SLEEP)

        if got < PER_RANGE:
            print(f"  [warn] 区间 {lo}-{hi} 只采到 {got}/{PER_RANGE} 个")

    return sorted(picked)


# ══════════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════════

def main():
    print(f"输出目录: {OUT_DIR}")
    print("开始采样...")
    ids = sample_ids()
    print(f"共 {len(ids)} 个 ID，预计对比耗时 "
          f"{len(ids) * SLEEP * 2 / 60:.1f} 分钟\n")

    results = []
    not_found = []
    for tid in ids:
        r, reason = compare(tid)
        if reason == "404":
            not_found.append(tid)
            continue
        if not r:
            continue

        results.append(r)

        flag = ""
        if r["ratio"] < 0.85:
            flag = f"  ⚠ md 少 {(1 - r['ratio']) * 100:.0f}%"
        elif r["ratio"] > 1.15:
            flag = f"  ⚠ md 多 {(r['ratio'] - 1) * 100:.0f}%"

        img_flag = ""
        if r["expected_img"] > r["md_img"]:
            img_flag = f"  ⚠ md 图 {r['md_img']}/{r['expected_img']}"

        print(f"  [{r['id']}] md={r['md_len']:>6} html={r['html_len']:>6} "
              f"ratio={r['ratio']:.2f}{flag}{img_flag}")
        print(f"          {r['title']}")

    # ── 汇总 ──
    print("\n" + "=" * 70)
    print(f"有效样本: {len(results)}    404: {len(not_found)}")
    print("=" * 70)

    if not results:
        print("没有有效样本，检查 APIKey / APIPass 或网络")
        return

    md_sum = sum(r["md_len"] for r in results)
    html_sum = sum(r["html_len"] for r in results)
    print(f"总 md 纯文本:   {md_sum}")
    print(f"总 html 纯文本: {html_sum}")
    print(f"总体 ratio:     {md_sum / html_sum:.3f}")

    print(f"\n图片: md={sum(r['md_img'] for r in results)} "
          f"html={sum(r['html_img'] for r in results)} "
          f"expected={sum(r['expected_img'] for r in results)}")
    print(f"链接: md={sum(r['md_link'] for r in results)} "
          f"html={sum(r['html_link'] for r in results)}")
    print(f"标题: md={sum(r['md_head'] for r in results)} "
          f"html={sum(r['html_head'] for r in results)}")

    # ── 异常列表 ──
    bad = [r for r in results if r["ratio"] < 0.85 or r["ratio"] > 1.15]
    img_bad = [r for r in results if r["expected_img"] > r["md_img"]]

    if bad:
        print(f"\n文本异常 {len(bad)} 个：")
        for r in bad:
            print(f"  {r['id']}  ratio={r['ratio']:.2f}  {r['title']}")

    if img_bad:
        print(f"\n图片数不匹配 {len(img_bad)} 个：")
        for r in img_bad:
            print(f"  {r['id']}  md_img={r['md_img']} "
                  f"expected={r['expected_img']}  {r['title']}")

    if not bad and not img_bad:
        print("\n所有样本正常。")

    print(f"\n原始 JSON 保存在 {OUT_DIR}/")


if __name__ == "__main__":
    main()