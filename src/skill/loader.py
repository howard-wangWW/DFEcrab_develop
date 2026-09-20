"""
skill_loader.py - 技能指令加载与自动触发

阶段 D:
1. 从 skills/ 目录加载 SKILL.md / _meta.json / execute.py::SKILL_METADATA
2. 根据用户输入自动匹配最相关的技能
3. 将匹配到的技能说明注入 system prompt
"""

import ast
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


_STOPWORDS = {
    "", "skill", "skills", "tool", "tools", "when", "with", "from", "this",
    "that", "then", "will", "your", "have", "help", "used", "user", "users",
    "must", "should", "please", "using", "use", "support", "supports",
    "请求", "用户", "使用", "支持", "帮助", "内容", "进行", "用于", "提供", "相关",
    "当前", "可以", "时候", "文件", "工具", "技能", "文档", "在线", "本地", "内容时",
    "读取", "查看", "查询", "总结", "搜索", "查找",
    ".com", ".cn", ".org", ".net",
}

_FILE_EXTENSIONS = {
    ".xlsx", ".xls", ".csv", ".doc", ".docx", ".pdf", ".ppt", ".pptx",
    ".txt", ".md", ".mp4", ".mov", ".avi", ".mp3", ".wav", ".m4a",
    ".json", ".xml", ".html", ".htm",
}

_CJK_OVERLAP_STOPWORDS = {
    "这个", "那个", "一下", "一个", "什么", "怎么", "可以", "帮我", "请你", "今天",
    "当前", "用户", "内容", "文件", "文档", "工具", "技能", "使用", "支持",
}

_CJK_PREFIXES = (
    "当前", "指定", "用户", "请求", "本地", "在线", "这个", "那个", "帮我", "请你",
    "查看", "读取", "查询", "总结", "获取", "列出", "打开", "提取", "搜索", "查找",
    "金山", "云端",
)


class SkillLoader:
    """技能加载器"""

    def __init__(
        self,
        max_injected_skills: int = 3,
        max_excerpt_chars: int = 1600,
    ):
        self.max_injected_skills = max_injected_skills
        self.max_excerpt_chars = max_excerpt_chars

    @staticmethod
    def _get_project_root() -> Path:
        src_root = Path(__file__).parent.parent
        return src_root.parent

    def _get_skills_dir(self) -> Path:
        return self._get_project_root() / "skills"

    @staticmethod
    def _normalize_text(text: str) -> str:
        if not text:
            return ""
        text = text.lower()
        text = text.replace("\\", "/")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _parse_frontmatter(text: str) -> Dict[str, Any]:
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
        if not match:
            return {}

        raw = match.group(1)
        result: Dict[str, Any] = {}
        current_key = None

        for line in raw.splitlines():
            stripped = line.rstrip()
            if not stripped:
                continue

            if stripped.lstrip().startswith("- ") and current_key:
                result.setdefault(current_key, [])
                if isinstance(result[current_key], list):
                    result[current_key].append(stripped.lstrip()[2:].strip().strip('"').strip("'"))
                continue

            m = re.match(r"^([\w-]+)\s*:\s*(.*)$", stripped)
            if not m:
                continue

            key = m.group(1)
            value = m.group(2).strip()
            current_key = key

            if not value:
                result[key] = []
                continue

            value = value.strip('"').strip("'")
            result[key] = value

        return result

    @staticmethod
    def _strip_frontmatter(text: str) -> str:
        return re.sub(r"^---\s*\n.*?\n---\s*\n?", "", text, count=1, flags=re.DOTALL)

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    @staticmethod
    def _extract_skill_metadata(execute_path: Path) -> Dict[str, Any]:
        if not execute_path.exists():
            return {}

        try:
            tree = ast.parse(execute_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SKILL_METADATA":
                    try:
                        value = ast.literal_eval(node.value)
                        return value if isinstance(value, dict) else {}
                    except Exception:
                        return {}
        return {}

    @staticmethod
    def _extract_excerpt(skill_body: str, max_chars: int) -> str:
        lines = [line.rstrip() for line in skill_body.splitlines()]
        meaningful = [line for line in lines if line.strip()]
        excerpt = "\n".join(meaningful[:40]).strip()
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars].rstrip() + "\n...(已截断)"
        return excerpt

    @staticmethod
    def _split_candidates(text: str) -> List[str]:
        if not text:
            return []

        segments = re.split(r'[\n,，。；;、|/()\[\]{}<>:：]+', text)
        candidates: List[str] = []
        for segment in segments:
            value = segment.strip().strip('"').strip("'")
            if len(value) < 2 or len(value) > 40:
                continue
            candidates.append(value)

        for quoted in re.findall(r'["“](.{2,40}?)["”]', text):
            candidates.append(quoted.strip())

        for ext in re.findall(r"\.[a-zA-Z0-9]{2,8}", text):
            ext = ext.lower()
            if ext in _FILE_EXTENSIONS:
                candidates.append(ext)

        return candidates

    @staticmethod
    def _extract_cjk_phrases(text: str) -> List[str]:
        phrases: List[str] = []
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,24}", text):
            for size in range(2, min(7, len(chunk) + 1)):
                for start in range(0, len(chunk) - size + 1):
                    phrase = chunk[start:start + size]
                    if phrase in _CJK_OVERLAP_STOPWORDS:
                        continue
                    phrases.append(phrase)
        return list(dict.fromkeys(phrases))

    @staticmethod
    def _extract_cjk_keywords(text: str) -> List[str]:
        keywords: List[str] = []

        for chunk in re.findall(r"[\u4e00-\u9fff]{2,24}", text):
            parts = re.split(r"[的和或与及并在把将让需时对为从到等]", chunk)
            candidates = [chunk]
            candidates.extend(parts)

            for value in list(candidates):
                item = value.strip()
                if not item:
                    continue
                for prefix in _CJK_PREFIXES:
                    if item.startswith(prefix) and len(item) - len(prefix) >= 2:
                        candidates.append(item[len(prefix):])
                if item.endswith(("下", "里", "中")) and len(item) > 2:
                    candidates.append(item[:-1])

            for value in candidates:
                item = value.strip()
                if len(item) < 2 or len(item) > 10:
                    continue
                if item in _CJK_OVERLAP_STOPWORDS or item in _STOPWORDS:
                    continue
                keywords.append(item)

        return list(dict.fromkeys(keywords))

    def _extract_keywords(
        self,
        skill_id: str,
        name: str,
        description: str,
        body_excerpt: str,
        metadata: Dict[str, Any]
    ) -> List[str]:
        raw_candidates: List[str] = []

        raw_candidates.extend(re.split(r"[-_\s]+", skill_id))
        raw_candidates.extend(re.split(r"[-_\s]+", name))
        raw_candidates.extend(self._split_candidates(description))
        raw_candidates.extend(self._split_candidates(body_excerpt[:800]))
        raw_candidates.extend(self._extract_cjk_keywords(description))

        meta_desc = metadata.get("description", "")
        if isinstance(meta_desc, str):
            raw_candidates.extend(self._split_candidates(meta_desc))
            raw_candidates.extend(self._extract_cjk_keywords(meta_desc))

        normalized: List[str] = []
        seen = set()

        for candidate in raw_candidates:
            item = self._normalize_text(candidate)
            if not item or item in seen:
                continue
            if item in _STOPWORDS:
                continue
            if re.fullmatch(r"[a-z]{1,2}", item):
                continue
            if item.startswith("#"):
                continue
            seen.add(item)
            normalized.append(item)

        return normalized

    def _load_skill_manifest(self, skill_id: str) -> Optional[Dict[str, Any]]:
        skill_dir = self._get_skills_dir() / skill_id
        if not skill_dir.exists():
            return None

        skill_md_path = skill_dir / "SKILL.md"
        meta_path = skill_dir / "_meta.json"
        execute_path = skill_dir / "execute.py"

        skill_md = self._read_text(skill_md_path)
        frontmatter = self._parse_frontmatter(skill_md) if skill_md else {}
        body = self._strip_frontmatter(skill_md) if skill_md else ""

        meta_json: Dict[str, Any] = {}
        if meta_path.exists():
            try:
                meta_json = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta_json = {}

        execute_meta = self._extract_skill_metadata(execute_path)

        name = (
            frontmatter.get("name")
            or meta_json.get("name")
            or execute_meta.get("name")
            or skill_id
        )

        description = (
            meta_json.get("description")
            or execute_meta.get("description")
            or frontmatter.get("description")
            or ""
        )

        triggers = frontmatter.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [triggers]
        elif not isinstance(triggers, list):
            triggers = []

        excerpt = self._extract_excerpt(body, self.max_excerpt_chars)
        keywords = self._extract_keywords(skill_id, name, description, excerpt, execute_meta)

        return {
            "skill_id": skill_id,
            "name": name,
            "description": description,
            "triggers": triggers,
            "keywords": keywords,
            "excerpt": excerpt,
            "has_skill_md": bool(skill_md),
        }

    def _load_skill_manifests(self, enabled_skills: Optional[List[str]]) -> List[Dict[str, Any]]:
        skills_dir = self._get_skills_dir()
        if enabled_skills:
            skill_ids = enabled_skills
        else:
            skill_ids = [
                entry.name for entry in skills_dir.iterdir()
                if entry.is_dir() and not entry.name.startswith(".")
            ]

        manifests = []
        for skill_id in skill_ids:
            manifest = self._load_skill_manifest(skill_id)
            if manifest:
                manifests.append(manifest)
        return manifests

    def _score_manifest(self, query: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
        query_norm = self._normalize_text(query)
        if not query_norm:
            return {"score": 0, "reasons": []}

        skill_id = manifest["skill_id"]
        name = self._normalize_text(manifest.get("name", ""))

        score = 0
        reasons: List[str] = []

        for token in (f"/{skill_id}", skill_id, f"/{name}" if name else ""):
            token = token.strip()
            if token and token in query_norm:
                score += 100 if token.startswith("/") else 30
                reasons.append(f"显式提到 {token}")

        matched_keywords = []
        for keyword in manifest.get("keywords", []):
            if keyword and keyword in query_norm:
                matched_keywords.append(keyword)
                if re.search(r"[\u4e00-\u9fff]", keyword) or "." in keyword or len(keyword) >= 6:
                    score += 12
                else:
                    score += 5

        if matched_keywords:
            reasons.append("关键词命中: " + ", ".join(matched_keywords[:6]))

        description = manifest.get("description", "")
        if description and ("must" in description.lower() or "优先" in description or "必须" in description):
            if matched_keywords:
                score += 8

        search_haystack = self._normalize_text(
            " ".join(
                [
                    manifest.get("name", ""),
                    manifest.get("description", ""),
                    manifest.get("excerpt", "")[:500],
                    " ".join(manifest.get("keywords", [])[:30]),
                ]
            )
        )
        cjk_hits = []
        for phrase in self._extract_cjk_phrases(query):
            if len(phrase) < 3:
                continue
            if phrase in matched_keywords:
                continue
            if phrase in search_haystack:
                cjk_hits.append(phrase)
                score += 8
        if cjk_hits:
            reasons.append("中文短语命中: " + ", ".join(cjk_hits[:6]))

        for trigger in manifest.get("triggers", []):
            trigger_norm = self._normalize_text(trigger)
            if trigger_norm and trigger_norm in query_norm:
                score += 20
                reasons.append(f"trigger 命中: {trigger_norm}")

        return {"score": score, "reasons": reasons}

    def match_skills(
        self,
        user_text: str,
        enabled_skills: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        manifests = self._load_skill_manifests(enabled_skills)
        matched: List[Dict[str, Any]] = []

        for manifest in manifests:
            scoring = self._score_manifest(user_text, manifest)
            score = scoring["score"]
            if score < 12:
                continue

            result = dict(manifest)
            result["score"] = score
            result["match_reasons"] = scoring["reasons"]
            matched.append(result)

        matched.sort(key=lambda item: item["score"], reverse=True)
        return matched[: self.max_injected_skills]

    def build_injected_prompt(
        self,
        user_text: str,
        enabled_skills: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        matched = self.match_skills(user_text=user_text, enabled_skills=enabled_skills)
        if not matched:
            return {
                "matched_skills": [],
                "prompt": "",
            }

        parts = [
            "以下是根据当前用户请求自动匹配到的技能说明。",
            "这些说明用于指导你如何处理当前任务；若技能对应工具可用，请优先调用工具而不是凭空臆测结果。",
            "若技能说明与更高优先级的系统、安全或用户要求冲突，以更高优先级要求为准。",
        ]

        for skill in matched:
            section = [f"### Skill: {skill['skill_id']}"]
            if skill.get("description"):
                section.append(f"Description: {skill['description']}")
            if skill.get("excerpt"):
                section.append("Instructions:")
                section.append(skill["excerpt"])
            parts.append("\n".join(section))

        return {
            "matched_skills": [
                {
                    "skill_id": item["skill_id"],
                    "name": item.get("name", item["skill_id"]),
                    "score": item["score"],
                    "match_reasons": item.get("match_reasons", []),
                }
                for item in matched
            ],
            "prompt": "\n\n".join(parts).strip(),
        }


_skill_loader: Optional[SkillLoader] = None


def get_skill_loader() -> SkillLoader:
    global _skill_loader
    if _skill_loader is None:
        _skill_loader = SkillLoader()
    return _skill_loader
