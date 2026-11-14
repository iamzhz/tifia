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
DIST_DIR = os.path.join(BASE_DIR, 'dist')
STYLES_PATH = os.path.join(BASE_DIR, 'styles.css')

# 站点配置
SITE_URL = "https://iamzhz.github.io/zolog"
SITE_TITLE = "iamzhz zolog"
SITE_DESCRIPTION = "iamzhz 的 blog"
FEED_URL = f"{SITE_URL.rstrip('/')}/feed.xml"
SITEMAP_URL = f"{SITE_URL.rstrip('/')}/sitemap.xml"
# 站点在域名下的子路径，例如 "/zolog/"；用于 404 页面这类无法使用相对路径的场景
SITE_BASE_PATH = urlparse(SITE_URL).path.rstrip('/') + '/'
RSS_MAX_ITEMS = 10  # 最多输出的篇数

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
    <title>iamzhz | {title}</title>
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
        <a href="{prefix}index.html" class="nav-brand">iamzhz<span>.</span></a>

        <ul class="nav-links">
            <li><a href="{prefix}index.html" class="{index_cls}">首页</a></li>
            <li><a href="{prefix}tags.html" class="{tags_cls}">标签云</a></li>
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
            <p>Powered by iamzhz</p>
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

    head = html_head.format(
        title=html_escape(title),
        description=html_escape(description, quote=True),
        canonical=html_escape(canonical, quote=True),
        og_type=og_type,
        site_title=html_escape(SITE_TITLE, quote=True),
        feed_url=html_escape(FEED_URL, quote=True),
        prefix=prefix,
        index_cls="active" if active_index else "",
        tags_cls="active" if active_tags else "",
        about_cls="active" if active_about else "",
        katex_head=KATEX_HEAD if needs_katex else "",
    )
    return head + body_html + html_tail


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


def generate_sitemap(posts_data):
    """生成 sitemap.xml。"""
    entries = [
        (f"{SITE_URL.rstrip('/')}/", None),
        (f"{SITE_URL.rstrip('/')}/tags.html", None),
    ]
    entries.extend(
        (f"{SITE_URL.rstrip('/')}/{p['url']}", p['date']) for p in posts_data
    )

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
    generate_sitemap(posts_data)
    generate_404()
    generate_robots()
    shutil.copy2(STYLES_PATH, os.path.join(DIST_DIR, 'styles.css'))

    print(f"\n构建完成! 共生成 {len(posts_data)} 篇文章，并已生成 feed.xml。")


if __name__ == "__main__":
    try:
        build_all()
    except Exception as e:
        print(f"构建失败: {e}", file=sys.stderr)
        sys.exit(1)
