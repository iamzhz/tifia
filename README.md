# tifia

静态博客生成器，使用 Python + Markdown。

## 本地构建

```bash
python -m pip install -r requirements.txt
python g.py
```

构建结果输出到 `dist/`（已在 `.gitignore` 中忽略）。本地可直接用浏览器打开 `dist/index.html`，或起一个静态服务器：

```bash
python -m http.server 8000 --directory dist
```

## 目录结构

```
posts/            文章源文件（Markdown），支持任意层子目录
  about.md        关于页，不进入首页文章列表与 RSS
  <year>/
    <slug>.md
    <slug>/       文章附属资源（图片、SVG 等，会原样复制到 dist）
pieces/           小纸条源文件，按日期命名（YYYY / YYYY.MM / YYYY.MM.DD）
g.py              构建脚本
tifia.json        站点配置
styles.css        站点样式
dist/             构建产物（自动生成）
```

文章所在目录结构会原样映射到 `dist/`，例如 `posts/2026/foo.md` 会生成 `dist/2026/foo.html`。

## 站点配置

站点级配置放在脚本同目录的 `tifia.json`，`g.py` 启动时读取：

```json
{
  "site_url": "https://example.com",
  "site_title": "我的博客",
  "site_description": "我的站点描述",
  "rss_max_items": 10,
  "pieces_page_char_budget": 6000,
  "pieces_page_max_items": 20
}
```

| 字段 | 说明 |
| --- | --- |
| `site_url` | 站点根地址，用于 canonical、RSS、sitemap、robots 及 404 页面的子路径推导 |
| `site_title` | 站点名，用于 `<title>`、导航品牌、页脚与 OG 信息 |
| `site_description` | 默认页面描述（文章未写 `description` 时使用） |
| `rss_max_items` | `feed.xml` 最多输出的篇数 |
| `pieces_page_char_budget` | 小纸条单页正文的字符预算 |
| `pieces_page_max_items` | 小纸条单页最多条目数 |

`feed.xml`、`sitemap.xml` 的地址以及站点的子路径均由 `site_url` 推导，无需单独配置。

## Front matter

```markdown
---
date: 2026-01-02 12:00
description: 出现在首页和 RSS 里的摘要
tags: math
tags: code
show-update: true
---
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `date` | 是 | 文章日期，不带时区时视为北京时间（UTC+8） |
| `description` | 否 | 摘要，默认「暂无描述」 |
| `tags` | 否 | 标签，可重复写多行，也可用逗号分隔 |
| `title` | 否 | 页面标题，缺省时取正文第一个一级标题 |
| `show-update` | 否 | 设为 `false` 时不输出到 RSS，默认 `true` |

`posts/about.md` 会被识别为「关于」页：不参与首页列表和标签统计，也不进入 RSS（需配合 `show-update: false`）。

## 小纸条

`pieces/` 目录用于存放零散记录，详见 [`pieces-README.md`](pieces-README.md)。简要规则：

- 文件名：`2026.md`、`2026.08.md` 或 `2026.08.29.md`。
- 文件内每条记录以日期小标题开头：`## 2026-08-29 (21:30)`，时间可省略。
- 所有条目按时间倒序合并，并按内容长度自动分页输出到 `dist/pieces/`。

## 构建产物

`g.py` 每次构建会先清空 `dist/`，然后生成：

- 各篇文章 HTML、`index.html`、`tags.html`、`404.html`
- `pieces/index.html` 及分页文件（小纸条）
- `feed.xml`（RSS 2.0 全文输出）
- `sitemap.xml`、`robots.txt`
- 文章附属资源与 `styles.css`

