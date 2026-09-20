---
name: web-fetch
description: "抓取网页内容，提取标题和正文"
version: 1.0.0
author: DFEcrab
triggers:
  - fetch
  - 抓取
  - 获取网页
  - 爬取
  - scrape
  - crawl
---

# Web Fetch

抓取指定 URL 的网页内容，提取标题和正文信息。

## When to Use

- 需要获取网页内容时
- 需要提取网页标题和正文时
- 需要分析网页结构时

## When NOT to Use

- 需要 JavaScript 渲染的页面（本技能仅抓取静态 HTML）
- 需要登录认证的页面
- 需要执行复杂交互的页面

## Parameters

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| url | string | 是 | 要抓取的网页 URL |
| extract_links | boolean | 否 | 是否提取页面链接（默认 false） |
| max_length | int | 否 | 内容最大长度限制（默认 10000） |

## Dependencies

- requests
- beautifulsoup4

## Example

```
抓取 https://example.com 的内容
获取 https://example.com 的网页标题
```
