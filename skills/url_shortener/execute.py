"""
短链接生成和解析
"""

import requests


def execute(url: str, action: str = "shorten"):
    """短链接工具

    Args:
        url: 需要处理的 URL
        action: "shorten"（缩短）或 "expand"（还原）

    Returns:
        处理结果
    """
    try:
        if action == "shorten":
            api_url = f"https://is.gd/create.php?format=simple&url={url}"
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()

            short_url = response.text.strip()
            return f"✅ 短链接: {short_url}"

        elif action == "expand":
            if not url.startswith(('http://', 'https://')):
                return "❌ 请提供有效的 URL"

            if 'is.gd' in url or 'bit.ly' in url:
                return f"⚠️  检测到短链接: {url}\n   请访问查看实际目标"
            else:
                return f"ℹ️  这是一个完整 URL，无需还原"

        else:
            return "❌ 不支持的操作，使用 'shorten' 或 'expand'"

    except Exception as e:
        return f"❌ 处理失败: {e}"
