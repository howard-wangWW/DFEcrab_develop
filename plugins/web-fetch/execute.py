"""
Web Fetch - 网页内容抓取

抓取指定 URL 的网页内容，提取标题和正文。
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from typing import Optional, Dict, List


def _fetch_web(url: str, extract_links: bool = False, max_length: int = 10000) -> str:
    """
    抓取网页内容并提取信息（内部实现）

    Args:
        url: 要抓取的网页 URL
        extract_links: 是否提取页面链接（默认 False）
        max_length: 内容最大长度限制（默认 10000）

    Returns:
        str: 提取的网页内容或错误信息
    """
    try:
        # 验证 URL
        if not url:
            return "错误：URL 不能为空"

        if not url.startswith(('http://', 'https://')):
            return "错误：URL 必须以 http:// 或 https:// 开头"

        # 设置请求头
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        # 发送请求
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        # 解析 HTML
        soup = BeautifulSoup(response.content, 'html.parser')

        # 提取标题
        title = soup.find('title')
        title_text = title.get_text().strip() if title else "无标题"

        # 提取正文内容
        # 尝试找到主要内容区域
        content_selectors = [
            'article',
            '[class*="content"]',
            '[class*="article"]',
            '[class*="post"]',
            'main',
            '.main',
            '#content',
            '#main'
        ]

        content_text = ""
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content:
                # 移除脚本和样式
                for script in content(["script", "style", "nav", "footer", "header"]):
                    script.decompose()
                content_text = content.get_text(separator='\n', strip=True)
                if len(content_text) > 200:  # 找到足够长的内容就停止
                    break

        # 如果没找到主要内容，提取整个 body
        if not content_text or len(content_text) < 200:
            body = soup.find('body')
            if body:
                for script in body(["script", "style", "nav", "footer", "header"]):
                    script.decompose()
                content_text = body.get_text(separator='\n', strip=True)

        # 限制内容长度
        if len(content_text) > max_length:
            content_text = content_text[:max_length] + "\n\n... (内容过长已截断)"

        # 构建结果
        result = f"## 标题\n{title_text}\n\n"
        result += f"## URL\n{url}\n\n"
        result += f"## 内容\n{content_text}\n"

        # 提取链接（可选）
        if extract_links:
            links = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                text = link.get_text().strip()
                if text and href and not href.startswith(('#', 'javascript:')):
                    full_url = urljoin(url, href)
                    links.append(f"- [{text}]({full_url})")

            if links:
                result += f"\n## 链接 ({len(links)} 个)\n"
                result += "\n".join(links[:20])  # 最多显示 20 个链接
                if len(links) > 20:
                    result += f"\n\n... 还有 {len(links) - 20} 个链接"

        return result

    except requests.exceptions.Timeout:
        return "错误：请求超时"
    except requests.exceptions.ConnectionError:
        return "错误：无法连接到服务器"
    except requests.exceptions.HTTPError as e:
        return f"错误：HTTP {e.response.status_code}"
    except Exception as e:
        return f"错误：{str(e)}"


def execute(
    url: str,
    extract_links: bool = False,
    max_length: int = 10000
):
    """
    抓取网页内容（DFEcrab 技能接口）

    Args:
        url: 要抓取的网页 URL
        extract_links: 是否提取页面链接（默认 False）
        max_length: 内容最大长度限制（默认 10000）

    Returns:
        ServiceResponse: 包含抓取结果的响应对象
    """
    from agentscope.service import ServiceResponse, ServiceExecStatus

    try:
        result = _fetch_web(url, extract_links, max_length)
        if result.startswith("错误："):
            return ServiceResponse(status=ServiceExecStatus.ERROR, content=result)
        return ServiceResponse(status=ServiceExecStatus.SUCCESS, content=result)
    except Exception as e:
        return ServiceResponse(status=ServiceExecStatus.ERROR, content=f"抓取网页失败: {str(e)}")


if __name__ == "__main__":
    # 测试
    import sys
    if len(sys.argv) > 1:
        url = sys.argv[1]
        print(_fetch_web(url))
    else:
        print("用法: python execute.py <URL>")
