# plugins/_default/reader/markdown.py
# coding: utf-8
"""
FimTale Markdown 子集 → HTML

支持短代码：
- [login]...[/login]     根据登录状态保留或删除
- [collapse]...[/collapse]   去标签，永远展开
- [markdown]...[/markdown]   去标签，内部继续渲染
- [spoiler]...[/spoiler]     黑条 + 点击展开
"""
import html
import re
from typing import Optional, Set


# ── 行内规则 ──

_INLINE_CODE_RE = re.compile(r'`([^`]+)`')
_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(\s*(\S+?)(?:\s+["\'][^"\']*["\'])?\s*\)')
_LINK_RE = re.compile(r'(?<!!)\[([^\]]*)\]\(([^)]+)\)')
_BOLD_RE = re.compile(r'\*\*([^*]+)\*\*')
_ITALIC_RE = re.compile(r'(?<!\*)\*([^*]+)\*(?!\*)')
_ESCAPE_RE = re.compile(r'\\([\\`*_\[\]()#+\-.!])')
_SPOILER_RE = re.compile(r'\[spoiler\](.*?)\[/spoiler\]')


class _SpoilerContext:
    """追踪文档里 spoiler 的序号和展开状态"""
    def __init__(self, revealed: Optional[Set[int]] = None):
        self.n = 0
        self.revealed = revealed if revealed is not None else set()

    def next_id(self) -> int:
        i = self.n
        self.n += 1
        return i


# ── 短代码（块级）──

def _process_block_shortcodes(md: str, logged_in: bool) -> str:
    # [login]：登录了留内容，未登录删整块
    if logged_in:
        md = re.sub(r'\[login\](.*?)\[/login\]', r'\1', md, flags=re.DOTALL)
    else:
        md = re.sub(r'\[login\].*?\[/login\]', '', md, flags=re.DOTALL)

    # [collapse]：去标签留内容
    md = re.sub(r'\[collapse\](.*?)\[/collapse\]', r'\1', md, flags=re.DOTALL)

    # [markdown]：去标签留内容
    md = re.sub(r'\[markdown\](.*?)\[/markdown\]', r'\1', md, flags=re.DOTALL)

    return md


# ── 行内处理 ──

def _inline(text: str, spoiler_ctx: _SpoilerContext) -> str:
    placeholders = []

    def stash(m):
        placeholders.append(m.group(1))
        return f"\x00{len(placeholders) - 1}\x00"

    text = _ESCAPE_RE.sub(stash, text)

    # spoiler 优先（内容按纯文本处理，不再解析内部 markdown）
    def spoiler_repl(m):
        content = html.escape(m.group(1))
        idx = spoiler_ctx.next_id()
        if idx in spoiler_ctx.revealed:
            return f'<span>{content}</span>'
        # 未展开：黑底黑字，点击展开
        return (
            f'<a href="spoiler:{idx}" '
            f'style="background-color:black;color:black;'
            f'text-decoration:none;">{content}</a>'
        )
    text = _SPOILER_RE.sub(spoiler_repl, text)

    # 行内代码
    def code_repl(m):
        return f"<code>{html.escape(m.group(1))}</code>"
    text = _INLINE_CODE_RE.sub(code_repl, text)

    # 图片
    def img_repl(m):
        alt = html.escape(m.group(1))
        url = html.escape(m.group(2), quote=True)
        return f'<img src="{url}" alt="{alt}">'
    text = _IMAGE_RE.sub(img_repl, text)

    # 链接
    def link_repl(m):
        label = html.escape(m.group(1))
        url = html.escape(m.group(2), quote=True)
        return f'<a href="{url}">{label}</a>'
    text = _LINK_RE.sub(link_repl, text)

    # 粗体/斜体
    text = _BOLD_RE.sub(r'<b>\1</b>', text)
    text = _ITALIC_RE.sub(r'<i>\1</i>', text)

    # 转义裸文本
    text = text.replace('&', '&amp;')
    text = text.replace('&amp;lt;', '&lt;').replace('&amp;gt;', '&gt;')
    text = text.replace('&amp;amp;', '&amp;')
    text = text.replace('&amp;quot;', '&quot;')
    text = re.sub(r'&amp;(lt|gt|amp|quot);', r'&\1;', text)
    text = text.replace('&amp;#', '&#')

    for i, ch in enumerate(placeholders):
        text = text.replace(f"\x00{i}\x00", html.escape(ch))

    return text


# ── 块级解析 ──

def md_to_html(md: str,
               revealed_spoilers: Optional[Set[int]] = None,
               logged_in: bool = True) -> str:
    spoiler_ctx = _SpoilerContext(revealed_spoilers)

    md = _process_block_shortcodes(md, logged_in)

    lines = md.split('\n')
    out = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # 代码块
        if stripped.startswith('```'):
            i += 1
            code_lines = []
            while i < n and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1
            out.append(
                '<pre class="code-block">'
                + html.escape('\n'.join(code_lines))
                + '</pre>'
            )
            continue

        # 下划线式标题
        if i + 1 < n:
            underline = lines[i + 1].strip()
            if re.fullmatch(r'={3,}', underline):
                out.append(f'<h1>{_inline(stripped, spoiler_ctx)}</h1>')
                i += 2
                continue
            if re.fullmatch(r'-{3,}', underline):
                out.append(f'<h2>{_inline(stripped, spoiler_ctx)}</h2>')
                i += 2
                continue

        # # 式标题
        m = re.match(r'^(#{1,6})\s+(.*)$', stripped)
        if m:
            level = len(m.group(1))
            out.append(f'<h{level}>{_inline(m.group(2), spoiler_ctx)}</h{level}>')
            i += 1
            continue

        # 有序列表
        if re.match(r'^\d+\.\s+', stripped):
            items = []
            while i < n and re.match(r'^\d+\.\s+', lines[i].strip()):
                items.append(re.sub(r'^\d+\.\s+', '', lines[i].strip()))
                i += 1
            out.append('<ol>' + ''.join(
                f'<li>{_inline(x, spoiler_ctx)}</li>' for x in items
            ) + '</ol>')
            continue

        # 无序列表
        if re.match(r'^[-*]\s+', stripped):
            items = []
            while i < n and re.match(r'^[-*]\s+', lines[i].strip()):
                items.append(re.sub(r'^[-*]\s+', '', lines[i].strip()))
                i += 1
            out.append('<ul>' + ''.join(
                f'<li>{_inline(x, spoiler_ctx)}</li>' for x in items
            ) + '</ul>')
            continue

        # 段落
        para = [stripped]
        i += 1
        while i < n and lines[i].strip():
            nxt = lines[i].strip()
            if (nxt.startswith('#') or nxt.startswith('```')
                    or re.match(r'^\d+\.\s+', nxt)
                    or re.match(r'^[-*]\s+', nxt)):
                break
            para.append(nxt)
            i += 1
        out.append(f'<p>{_inline("<br>".join(para), spoiler_ctx)}</p>')

    return '\n'.join(out)