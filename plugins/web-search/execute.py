"""
网络搜索
"""

import requests
from bs4 import BeautifulSoup


def execute(query: str, max_results: int = 5):
    """搜索网络并返回结果

    Args:
        query: 搜索关键词
        max_results: 最多返回的结果数量

    Returns:
        搜索结果列表
    """
    try:
        url = f"https://duckduckgo.com/html/?q={query}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        results = []

        # DuckDuckGo 搜索结果的选择器
        result_divs = soup.find_all('div', class_='result', limit=max_results)
        
        for result_div in result_divs:
            title_elem = result_div.find('a', class_='result__a')
            if title_elem:
                title = title_elem.get_text(strip=True)
                link = title_elem.get('href', '')
                if title and link:
                    results.append({
                        'title': title,
                        'url': link
                    })

        if not results:
            return f"未找到关于 '{query}' 的搜索结果"

        output = f"🔍 关于 '{query}' 的搜索结果:\n\n"
        for i, r in enumerate(results, 1):
            output += f"{i}. {r['title']}\n   {r['url']}\n\n"

        return output.strip()

    except Exception as e:
        return f"搜索失败: {str(e)}"
