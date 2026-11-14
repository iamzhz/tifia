import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from html import escape as html_escape
from urllib.parse import urljoin, urlparse
from xml.sax.saxutils import escape as xml_escape

import markdown
from dateutil import parser
from markdown.extensions.codehilite import CodeHiliteExtension
from pymdownx.arithmatex import ArithmatexExtension

# 所有路径都基于脚本所在目录，避免依赖当前工作目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSTS_DIR = os.path.join(BASE_DIR, 'posts')
PIECES_DIR = os.path.join(BASE_DIR, 'pieces')
DIST_DIR = os.path.join(BASE_DIR, 'dist')
STYLES_PATH = os.path.join(BASE_DIR, 'styles.css')

# 站点配置：从脚本同目录的 tifia.json 读取
CONFIG_PATH = os.path.join(BASE_DIR, 'tifia.json')
with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

SITE_URL = CONFIG['site_url']
SITE_TITLE = CONFIG['site_title']
SITE_DESCRIPTION = CONFIG['site_description']
FEED_URL = f"{SITE_URL.rstrip('/')}/feed.xml"
SITEMAP_URL = f"{SITE_URL.rstrip('/')}/sitemap.xml"
# 站点在域名下的子路径，例如 "/zolog/"；用于 404 页面这类无法使用相对路径的场景
SITE_BASE_PATH = urlparse(SITE_URL).path.rstrip('/') + '/'
RSS_MAX_ITEMS = CONFIG['rss_max_items']  # 最多输出的篇数

# 小纸条：按内容长度自动分页
PIECES_PAGE_CHAR_BUDGET = CONFIG['pieces_page_char_budget']   # 单页正文的字符预算
PIECES_PAGE_MAX_ITEMS = CONFIG['pieces_page_max_items']       # 单页最多条目数
PIECE_FILE_RE = re.compile(r'^(\d{4})(?:\.(\d{2}))?(?:\.(\d{2}))?$')
PIECE_HEADING_RE = re.compile(
    r'^(20\d{2})-(\d{2})-(\d{2})'
    r'(?:\s*[（(]?\s*(\d{1,2}):(\d{2})\s*[）)]?)?'
)
# 看起来像日期但解析失败的小标题，用于给出明确报错
PIECE_BAD_HEADING_RE = re.compile(r'^20\d{2}[-.]\d')

# 文章日期统一按北京时间处理（无时区的日期视为北京时间）
BEIJING_TZ = timezone(timedelta(hours=8))

# 只有包含公式的页面才需要 KaTeX，避免首页/标签页加载无用资源
KATEX_RE = re.compile(r'\\[\[\(]|\$\$')

KATEX_HEAD = """    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.18.7/dist/katex.min.css" integrity="sha384-JctiRyLzXCrSoOOzFlSoWLdyzQl7OrrRnhyeBmzB6ZWtcjccUyc8lCQJqIbs3uQX" crossorigin="anonymous">
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.18.7/dist/katex.min.js" integrity="sha384-+7Keh381hSkXmXqnjC0JBM/kzsN6TFj+wMKychSLjTvJ8/0ElMde2uKl8i6p6Buj" crossorigin="anonymous"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.18.7/dist/contrib/auto-render.min.js" integrity="sha384-bjyGPfbij8/NDKJhSGZNP/khQVgtHUE5exjm4Ydllo42FwIgYsdLO2lXGmRBf5Mz" crossorigin="anonymous"
        onload="renderMathInElement(document.body);"></script>
"""

# 注意：{prefix} 用于子目录页面回退到站点根目录（例如 "../"）
html_head = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{site_title} | {title}</title>
    <meta name="description" content="{description}">
    <link rel="canonical" href="{canonical}">
    <link rel="alternate" type="application/rss+xml" title="{site_title}" href="{feed_url}">
    <meta property="og:type" content="{og_type}">
    <meta property="og:site_name" content="{site_title}">
    <meta property="og:title" content="{title}">
    <meta property="og:description" content="{description}">
    <meta property="og:url" content="{canonical}">
    <meta name="twitter:card" content="summary">
    <link rel="stylesheet" href="{prefix}styles.css">
{katex_head}</head>
<body>
    <nav class="shiro-nav">
        <a href="{prefix}index.html" class="nav-brand">{site_title}<span>.</span></a>

        <ul class="nav-links">
            <li><a href="{prefix}index.html" class="{index_cls}">首页</a></li>
            <li><a href="{prefix}tags.html" class="{tags_cls}">标签云</a></li>
            <li><a href="{prefix}pieces/index.html" class="{pieces_cls}">小纸条</a></li>
            <li><a href="{prefix}about.html" class="{about_cls}">关于</a></li>
        </ul>
    </nav>

    <main class="main-container">
        <div class="content-area">
"""
html_tail = """
        </div>
    </main>
    <footer class="site-footer">
        <div class="footer-content">
            <p>Powered by {site_title}</p>
        </div>
    </footer>
</body>
</html>
"""


def get_file_content(filename: str) -> str:
    with open(filename, 'r', encoding='utf-8') as f:
        return f.read()


def render_page(title: str, body_html: str, prefix: str = "",
                active_index: bool = False,
                active_tags: bool = False,
                active_pieces: bool = False,
                active_about: bool = False,
                description: str | None = None,
                canonical_path: str = "",
                og_type: str = "website",
                needs_katex: bool = False) -> str:
    """统一拼装页面，prefix 为回到 dist 根目录的相对路径（如 ''、'../'、'../../'）。

    canonical_path 为相对站点根目录的路径（如 '2026/foo.html'），留空表示首页。
    """
    description = description or SITE_DESCRIPTION
    canonical = (f"{SITE_URL.rstrip('/')}/{canonical_path.lstrip('/')}"
                 if canonical_path else f"{SITE_URL.rstrip('/')}/")
    site_title = html_escape(SITE_TITLE, quote=True)

    head = html_head.format(
        title=html_escape(title),
        description=html_escape(description, quote=True),
        canonical=html_escape(canonical, quote=True),
        og_type=og_type,
        site_title=site_title,
        feed_url=html_escape(FEED_URL, quote=True),
        prefix=prefix,
        index_cls="active" if active_index else "",
        tags_cls="active" if active_tags else "",
        pieces_cls="active" if active_pieces else "",
        about_cls="active" if active_about else "",
        katex_head=KATEX_HEAD if needs_katex else "",
    )
    tail = html_tail.format(site_title=site_title)
    return head + body_html + tail


def rel_url_to_fs_path(rel_url: str) -> str:
    """把形如 'tech/python.html' 的相对 URL 转成当前系统下的文件路径。"""
    return os.path.join(DIST_DIR, *rel_url.split('/'))


def normalize_tags(raw_tags) -> list:
    """清洗标签：支持重复 key 与逗号分隔，去空白、去重（忽略大小写）。"""
    tags = []
    seen = set()
    for raw in raw_tags:
        for tag in str(raw).split(','):
            tag = tag.strip()
            if not tag:
                continue
            key = tag.casefold()
            if key in seen:
                continue
            seen.add(key)
            tags.append(tag)
    return tags


def parse_post_date(value: str, source: str) -> datetime:
    """解析文章日期并统一转换为北京时间，保证所有日期可直接比较。"""
    if not value:
        raise ValueError(f"{source}: front matter 缺少 `date` 字段")
    try:
        dt_obj = parser.parse(value)
    except (ValueError, OverflowError) as e:
        raise ValueError(f"{source}: 无法解析日期 {value!r}") from e
    if dt_obj.tzinfo is None:
        return dt_obj.replace(tzinfo=BEIJING_TZ)
    return dt_obj.astimezone(BEIJING_TZ)


def process_single_post(full_path: str):
    md = markdown.Markdown(extensions=[
        'tables', 'meta', 'fenced_code', 'toc',
        CodeHiliteExtension(linenums=True),
        ArithmatexExtension(generic=True),
    ])

    # 1. 读取内容
    content = get_file_content(full_path)
    if not content.strip():
        print(f"跳过空文件: {full_path}")
        return None
    body_html = md.convert(content)

    # 2. 计算输出路径：posts/tech/python.md -> tech/python.html
    rel_path = os.path.relpath(full_path, POSTS_DIR).replace(os.sep, '/')
    rel_dir = os.path.dirname(rel_path)                    # 'tech' 或 ''
    base_name = os.path.basename(rel_path)                 # 'python.md'
    file_slug = os.path.splitext(base_name)[0]             # 'python'

    output_rel = f"{rel_dir}/{file_slug}.html" if rel_dir else f"{file_slug}.html"
    output_path = rel_url_to_fs_path(output_rel)

    # 子目录页面需要 ../ 回退到 dist 根目录
    depth = len([p for p in rel_dir.split('/') if p]) if rel_dir else 0
    prefix = '../' * depth

    # 3. 提取元数据
    meta = getattr(md, 'Meta', {})
    title = meta.get('title', [None])[0]
    if not title:
        title = md.toc_tokens[0]['name'] if md.toc_tokens else file_slug

    dt_obj = parse_post_date(meta.get('date', [None])[0], full_path)

    include_in_feed_meta = meta.get('show-update', ['true'])[0].lower()
    include_in_feed = include_in_feed_meta in ('true', '1', 'yes', 'on')

    is_about = file_slug == 'about'
    needs_katex = bool(KATEX_RE.search(body_html))
    description = meta.get('description', ['暂无描述'])[0]

    # 4. 生成 HTML
    full_html = render_page(
        title, body_html, prefix=prefix,
        active_about=is_about,
        description=description,
        canonical_path=output_rel,
        og_type="article",
        needs_katex=needs_katex,
    )

    # 5. 按原目录结构写入 dist
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(full_html)

    return {
        'title': title,
        'date': dt_obj,
        'description': description,
        'tags': normalize_tags(meta.get('tags', [])),
        'url': output_rel,          # 相对 dist 根目录的 URL，始终用 '/'
        'body_html': body_html,
        'include_in_feed': include_in_feed,
        'is_about': is_about,
    }


def generate_index_and_tags(all_posts):
    """汇总生成 index.html 和 tags.html（均在 dist 根目录，prefix 为空）"""

    # “关于”页面不参与文章列表与标签统计
    listed_posts = [p for p in all_posts if not p['is_about']]
    listed_posts.sort(key=lambda x: (x['date'], x['url']), reverse=True)

    # --- 1. 生成主页 (Index) ---
    index_body = "<h1>最近更新</h1><div class='post-list'>"
    if not listed_posts:
        index_body += "<p>还没有文章。</p>"
    for post in listed_posts:
        tag_spans = "".join(
            f"<span class='tag-mini'>{html_escape(t)}</span>" for t in post['tags']
        )
        meta_line = post['date'].strftime('%Y-%m-%d')
        if tag_spans:
            meta_line += f" | {tag_spans}"
        index_body += f"""
        <article class="post-item">
            <h2><a href="{html_escape(post['url'], quote=True)}">{html_escape(post['title'])}</a></h2>
            <div class="meta-info">{meta_line}</div>
            <p>{html_escape(post['description'])}</p>
        </article>
        """
    index_body += "</div>"

    with open(os.path.join(DIST_DIR, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(render_page("首页", index_body, active_index=True))

    # --- 2. 生成标签页 (Tags) ---
    tag_map = defaultdict(list)
    for post in listed_posts:
        for t in post['tags']:
            tag_map[t].append(post)

    tags_body = "<h1>标签云</h1>"
    if not tag_map:
        tags_body += "<p>还没有标签。</p>"
    for tag, posts in sorted(tag_map.items(), key=lambda item: item[0].casefold()):
        tags_body += f"<section><h2># {html_escape(tag)}</h2><ul>"
        for p in posts:
            tags_body += (
                f'<li><a href="{html_escape(p["url"], quote=True)}">{html_escape(p["title"])}</a>'
                f' ({p["date"].strftime("%m-%d")})</li>'
            )
        tags_body += "</ul></section>"

    with open(os.path.join(DIST_DIR, 'tags.html'), 'w', encoding='utf-8') as f:
        f.write(render_page("标签汇总", tags_body, active_tags=True,
                            canonical_path="tags.html"))


def parse_piece_file_date(filename: str):
    """解析小纸条文件名中的日期（YYYY / YYYY.MM / YYYY.MM.DD）。"""
    stem = os.path.splitext(os.path.basename(filename))[0]
    match = PIECE_FILE_RE.fullmatch(stem)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2) or 1)
    day = int(match.group(3) or 1)
    try:
        return datetime(year, month, day, tzinfo=BEIJING_TZ)
    except ValueError:
        return None


def render_piece_markdown(text: str) -> str:
    md = markdown.Markdown(extensions=[
        'tables', 'fenced_code',
        CodeHiliteExtension(linenums=False),
        ArithmatexExtension(generic=True),
    ])
    return md.convert(text)


def parse_piece_file(full_path: str, file_key: datetime) -> list:
    """按日期小标题拆分单个小纸条文件。"""
    entries = []
    current = None

    for lineno, line in enumerate(get_file_content(full_path).splitlines(), 1):
        heading_match = re.match(r'^#{1,6}\s+(.*?)\s*#*\s*$', line)
        if heading_match:
            heading = heading_match.group(1).strip()
            date_match = PIECE_HEADING_RE.match(heading)
            if date_match:
                year, month, day = (int(date_match.group(i)) for i in (1, 2, 3))
                hour = int(date_match.group(4) or 0)
                minute = int(date_match.group(5) or 0)
                try:
                    date = datetime(year, month, day, hour, minute, tzinfo=BEIJING_TZ)
                except ValueError as e:
                    raise ValueError(
                        f"{full_path}:{lineno}: 无效的小纸条日期 {heading!r}"
                    ) from e
                current = {
                    'date': date,
                    'has_time': date_match.group(4) is not None,
                    'file_key': file_key,
                    'index': len(entries),
                    'lines': [],
                }
                entries.append(current)
                continue
            if PIECE_BAD_HEADING_RE.match(heading):
                raise ValueError(
                    f"{full_path}:{lineno}: 无法解析小纸条日期标题 {heading!r}"
                    "（应为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM）"
                )

        if current is not None:
            current['lines'].append(line)

    for entry in entries:
        body = "\n".join(entry.pop('lines')).strip()
        entry['html'] = render_piece_markdown(body)
        entry['text_length'] = len(body)

    return entries


def load_pieces() -> list:
    """读取 pieces/ 下的所有小纸条，并按时间回溯式排序。"""
    if not os.path.isdir(PIECES_DIR):
        return []

    entries = []
    for name in sorted(os.listdir(PIECES_DIR)):
        if not name.lower().endswith('.md') or name.lower() == 'readme.md':
            continue
        full_path = os.path.join(PIECES_DIR, name)
        if not os.path.isfile(full_path):
            continue
        file_key = parse_piece_file_date(name)
        if file_key is None:
            print(f"警告: 跳过文件名不符合日期格式的小纸条: {name}", file=sys.stderr)
            continue
        entries.extend(parse_piece_file(full_path, file_key))

    # 新的在前；同一时间按文件日期、文件内顺序倒序，保证结果稳定
    entries.sort(
        key=lambda e: (e['date'], e['file_key'], e['index']),
        reverse=True,
    )
    return entries


def paginate_pieces(entries: list) -> list:
    """按字符预算和条目上限把条目动态切成若干页。"""
    pages = []
    current, current_len = [], 0
    for entry in entries:
        size = entry['text_length']
        if current and (
            current_len + size > PIECES_PAGE_CHAR_BUDGET
            or len(current) >= PIECES_PAGE_MAX_ITEMS
        ):
            pages.append(current)
            current, current_len = [], 0
        current.append(entry)
        current_len += size
    if current or not pages:
        pages.append(current)
    return pages


def render_piece(entry: dict) -> str:
    fmt = '%Y-%m-%d %H:%M' if entry['has_time'] else '%Y-%m-%d'
    display = entry['date'].strftime(fmt)
    return f"""
        <article class="piece">
            <h2 class="piece-date"><time datetime="{entry['date'].isoformat()}">{display}</time></h2>
            <div class="piece-body">{entry['html']}</div>
        </article>
        """


def render_piece_pagination(page_no: int, total_pages: int) -> str:
    if total_pages <= 1:
        return ""
    parts = []
    if page_no > 1:
        prev_href = 'index.html' if page_no == 2 else f'{page_no - 1}.html'
        parts.append(f'<a href="{prev_href}" rel="prev">← 上一页</a>')
    parts.append(f'<span class="pagination-info">第 {page_no} / {total_pages} 页</span>')
    if page_no < total_pages:
        parts.append(f'<a href="{page_no + 1}.html" rel="next">下一页 →</a>')
    return '<nav class="pagination" aria-label="小纸条分页">' + ''.join(parts) + '</nav>'


def generate_pieces(entries: list) -> list:
    """生成 dist/pieces/index.html 及后续分页，返回所有页面 URL。"""
    pages = paginate_pieces(entries)
    out_dir = os.path.join(DIST_DIR, 'pieces')
    os.makedirs(out_dir, exist_ok=True)
    page_urls = []

    for page_no, page_entries in enumerate(pages, 1):
        filename = 'index.html' if page_no == 1 else f'{page_no}.html'
        rel_url = f'pieces/{filename}'
        page_urls.append(rel_url)
        title = '小纸条' if page_no == 1 else f'小纸条 · 第 {page_no} 页'

        body = '<h1>小纸条</h1>'
        if not page_entries:
            body += '<p>还没有小纸条。</p>'
        body += '<div class="piece-list">'
        for entry in page_entries:
            body += render_piece(entry)
        body += '</div>'
        body += render_piece_pagination(page_no, len(pages))

        needs_katex = any(KATEX_RE.search(e['html']) for e in page_entries)
        html = render_page(
            title, body, prefix='../',
            active_pieces=True,
            description=f'{SITE_TITLE} 的零散小纸条',
            canonical_path=rel_url,
            needs_katex=needs_katex,
        )
        with open(os.path.join(out_dir, filename), 'w', encoding='utf-8') as f:
            f.write(html)

    print(f"小纸条已生成: {len(entries)} 条，共 {len(pages)} 页")
    return page_urls


def absolutize_html(html_text: str, base_url: str) -> str:
    """把正文里相对的 src/href 转成绝对地址，避免阅读器里图片/链接失效。"""
    def replace(match):
        attr, url = match.group('attr'), match.group('url')
        if url.startswith(('#', 'data:', 'mailto:', 'tel:', 'http://', 'https://', '//')):
            return match.group(0)
        return f'{attr}="{urljoin(base_url, url)}"'

    return re.sub(
        r'(?P<attr>\b(?:src|href))="(?P<url>[^"]+)"',
        replace,
        html_text,
        flags=re.IGNORECASE,
    )


def generate_rss(posts_data, site_url, site_title, site_description):
    """生成 RSS 2.0 格式的 feed.xml，包含全文内容，时间使用 UTC+8"""
    filtered_posts = [p for p in posts_data if p.get('include_in_feed', True)]
    posts_sorted = sorted(
        filtered_posts, key=lambda x: (x['date'], x['url']), reverse=True
    )[:RSS_MAX_ITEMS]
    items_xml = ""

    for post in posts_sorted:
        link = f"{site_url.rstrip('/')}/{post['url']}"

        # 发布时间使用北京时间（+0800）
        pub_date = format_datetime(post['date'])

        # 摘要（description）保留元数据描述
        desc = xml_escape(post['description'])

        # 完整内容（content:encoded）使用正文 HTML：先补全相对链接，再用 CDATA 包裹
        content_html = absolutize_html(
            post['body_html'], link.rsplit('/', 1)[0] + '/'
        )
        content_html = content_html.replace(']]>', ']]]]><![CDATA[>')

        items_xml += f"""
    <item>
        <title>{xml_escape(post['title'])}</title>
        <link>{xml_escape(link)}</link>
        <description>{desc}</description>
        <content:encoded><![CDATA[{content_html}]]></content:encoded>
        <pubDate>{pub_date}</pubDate>
        <guid>{xml_escape(link)}</guid>
    </item>"""

    rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
    <title>{xml_escape(site_title)}</title>
    <link>{xml_escape(site_url)}</link>
    <description>{xml_escape(site_description)}</description>
    <language>zh-cn</language>
    <lastBuildDate>{format_datetime(datetime.now(BEIJING_TZ))}</lastBuildDate>
    <atom:link href="{xml_escape(FEED_URL)}" rel="self" type="application/rss+xml"/>
    {items_xml}
</channel>
</rss>"""

    feed_path = os.path.join(DIST_DIR, 'feed.xml')
    with open(feed_path, 'w', encoding='utf-8') as f:
        f.write(rss_xml)
    print(f"RSS feed 已生成（含全文，时间 UTC+8）：{feed_path}")


def generate_sitemap(posts_data, extra_urls=()):
    """生成 sitemap.xml。"""
    entries = [
        (f"{SITE_URL.rstrip('/')}/", None),
        (f"{SITE_URL.rstrip('/')}/tags.html", None),
    ]
    entries.extend(
        (f"{SITE_URL.rstrip('/')}/{p['url']}", p['date']) for p in posts_data
    )
    entries.extend((f"{SITE_URL.rstrip('/')}/{url}", None) for url in extra_urls)

    urls_xml = ""
    for url, dt_obj in entries:
        lastmod = f"<lastmod>{dt_obj.strftime('%Y-%m-%d')}</lastmod>" if dt_obj else ""
        urls_xml += f"\n    <url><loc>{xml_escape(url)}</loc>{lastmod}</url>"

    sitemap_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls_xml}
</urlset>"""

    sitemap_path = os.path.join(DIST_DIR, 'sitemap.xml')
    with open(sitemap_path, 'w', encoding='utf-8') as f:
        f.write(sitemap_xml)
    print(f"Sitemap 已生成: {sitemap_path}")


def generate_robots():
    robots_path = os.path.join(DIST_DIR, 'robots.txt')
    with open(robots_path, 'w', encoding='utf-8') as f:
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {SITEMAP_URL}\n")
    print(f"robots.txt 已生成: {robots_path}")


def generate_404():
    body = f"""<h1>页面不存在</h1>
<p>你访问的页面走丢了。</p>
<p><a href="{SITE_BASE_PATH}index.html">返回首页</a></p>"""
    html = render_page("404", body, prefix=SITE_BASE_PATH,
                       canonical_path="404.html")
    with open(os.path.join(DIST_DIR, '404.html'), 'w', encoding='utf-8') as f:
        f.write(html)
    print("404.html 已生成")


def build_all():
    # 每次构建都从干净目录开始，避免删除/改名文章后残留旧页面
    if os.path.exists(DIST_DIR):
        shutil.rmtree(DIST_DIR)
    os.makedirs(DIST_DIR, exist_ok=True)

    posts_data = []
    # 递归遍历 posts 文件夹下的所有子文件夹（排序保证构建结果稳定）
    for root, dirs, files in os.walk(POSTS_DIR):
        dirs.sort()
        files.sort()
        for file in files:
            full_path = os.path.join(root, file)
            if file.endswith('.md'):
                data = process_single_post(full_path)
                if data:
                    posts_data.append(data)
                print(f"已处理: {full_path}")
                continue

            # 其余文件视为文章资源（图片、SVG 等），按相同目录结构复制
            rel_path = os.path.relpath(full_path, POSTS_DIR)
            dest_path = os.path.join(DIST_DIR, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(full_path, dest_path)
            print(f"已复制资源: {full_path} -> {dest_path}")

    generate_index_and_tags(posts_data)
    generate_rss(posts_data, SITE_URL, SITE_TITLE, SITE_DESCRIPTION)

    pieces_entries = load_pieces()
    piece_urls = generate_pieces(pieces_entries)

    generate_sitemap(posts_data, piece_urls)
    generate_404()
    generate_robots()
    shutil.copy2(STYLES_PATH, os.path.join(DIST_DIR, 'styles.css'))

    print(f"\n构建完成! 共生成 {len(posts_data)} 篇文章、"
          f"{len(pieces_entries)} 条小纸条，并已生成 feed.xml。")


if __name__ == "__main__":
    try:
        build_all()
    except Exception as e:
        print(f"构建失败: {e}", file=sys.stderr)
        sys.exit(1)
