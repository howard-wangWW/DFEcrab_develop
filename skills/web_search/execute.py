"""
网络搜索
"""

import requests
from html.parser import HTMLParser


class _DuckDuckGoParser(HTMLParser):
    """DuckDuckGo HTML 结果的轻量解析器。"""

    def __init__(self, max_results: int):
        super().__init__()
        self.max_results = max_results
        self.results = []
        self._in_result_link = False
        self._current_href = ""
        self._current_text = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        classes = attrs_dict.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._in_result_link = True
            self._current_href = attrs_dict.get("href", "")
            self._current_text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._in_result_link:
            title = "".join(self._current_text).strip()
            if title and self._current_href and len(self.results) < self.max_results:
                self.results.append({"title": title, "url": self._current_href})
            self._in_result_link = False
            self._current_href = ""
            self._current_text = []

    def handle_data(self, data):
        if self._in_result_link:
            self._current_text.append(data)


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

        results = []
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(response.text, 'html.parser')
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
        except ImportError:
            parser = _DuckDuckGoParser(max_results=max_results)
            parser.feed(response.text)
            results = parser.results

        if not results:
            return f"未找到关于 '{query}' 的搜索结果"

        output = f"🔍 关于 '{query}' 的搜索结果:\n\n"
        for i, r in enumerate(results, 1):
            output += f"{i}. {r['title']}\n   {r['url']}\n\n"

        return output.strip()

    except Exception as e:
        return f"搜索失败: {str(e)}"
