"""
api_base 规范化工具单元测试

覆盖深圳现场场景（完整接口地址 → 根地址），保证回归不破坏昆明 vLLM /v1 配置。
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.utils.api_base import normalize_api_base  # noqa: E402


class TestNormalizeApiBase(unittest.TestCase):

    def test_shenzhen_full_endpoint_stripped(self):
        """深圳网关：误填完整 /chat/completions → 剥成根地址（本次故障回归用例）"""
        self.assertEqual(
            normalize_api_base("http://10.176.174.28:8080/apis/ais-v2/chat/completions"),
            "http://10.176.174.28:8080/apis/ais-v2",
        )

    def test_kunming_v1_kept(self):
        """昆明 vLLM：/v1 结尾属合法根地址，保持不变"""
        self.assertEqual(
            normalize_api_base("http://172.20.41.86:8089/v1"),
            "http://172.20.41.86:8089/v1",
        )

    def test_trailing_slash_stripped(self):
        self.assertEqual(
            normalize_api_base("http://172.20.41.86:8089/v1/"),
            "http://172.20.41.86:8089/v1",
        )

    def test_duplicate_v1_collapsed(self):
        """/v1/v1 重复版本段 → 只保留一个 /v1"""
        self.assertEqual(
            normalize_api_base("http://172.20.41.86:8089/v1/v1"),
            "http://172.20.41.86:8089/v1",
        )

    def test_models_suffix_stripped(self):
        """误填 /models → 剥掉"""
        self.assertEqual(
            normalize_api_base("http://host:8080/apis/ais-v2/models"),
            "http://host:8080/apis/ais-v2",
        )

    def test_double_suffix_fully_stripped(self):
        """双重拼接 /chat/completions/chat/completions → 剥干净"""
        self.assertEqual(
            normalize_api_base("http://host/apis/ais-v2/chat/completions/chat/completions"),
            "http://host/apis/ais-v2",
        )

    def test_case_insensitive(self):
        """大小写不敏感（/CHAT/COMPLETIONS 同样剥掉）"""
        self.assertEqual(
            normalize_api_base("http://host/apis/ais-v2/CHAT/COMPLETIONS"),
            "http://host/apis/ais-v2",
        )

    def test_whitespace_and_none(self):
        self.assertEqual(normalize_api_base(""), "")
        self.assertEqual(normalize_api_base(None), "")
        self.assertEqual(normalize_api_base("  http://host/v1  "), "http://host/v1")

    def test_idempotent(self):
        """幂等：对已是根地址的输入重复调用结果不变"""
        base = normalize_api_base("http://10.176.174.28:8080/apis/ais-v2/chat/completions")
        self.assertEqual(normalize_api_base(base), base)


if __name__ == "__main__":
    unittest.main(verbosity=2)
