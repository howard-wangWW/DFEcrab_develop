"""
image_service.py - 图片生成服务

能力
----
1. Provider 抽象：当前实现 ``openai_compatible``（POST ``/images/generations``），
   兼容返回 ``b64_json`` 或 ``url`` 两种形式的服务端（vLLM / SD-WebUI OpenAI
   兼容层 / 云端 DALL·E / 各类聚合网关）。
2. 落盘与索引：图片存 ``data/images/YYYY-MM-DD/{image_id}.png``，
   元数据追加写 ``data/images/index.jsonl``（一行一条，便于按天/按用户检索）。
3. 用量埋点：每次生成写一条 ``image_gen`` 事件到 ``data/usage/``，
   自动汇入 ``/api/stats/*`` 统计。

设计取舍
--------
- **独立配置段**：只用 ``config/dfecrab.json`` 的 ``image_providers`` /
  ``image_generation``，不混入 ``model_providers``——后者的"第一个 enabled 即当前
  对话模型"语义与探活逻辑只认 ``/chat/completions``，混入会导致图像模型被误判。
- **零新依赖**：仅用 ``requests`` + 标准库，不需要 Pillow（不做本地图像处理）。
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_FILE = _ROOT / "config" / "dfecrab.json"

_DEFAULT_OUTPUT_DIR = "data/images"
_DEFAULT_SIZES = ["512x512", "768x768", "1024x1024", "1024x1536", "1536x1024"]
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_INDEX_LOCK = threading.Lock()


class ImageProviderError(Exception):
    """图片生成失败（配置缺失 / 网络错误 / 服务端报错）"""


class ImageService:
    """图片生成服务（单例）"""

    _instance: Optional["ImageService"] = None
    _instance_lock = threading.Lock()

    def __init__(self, config_file: Optional[Path] = None):
        self._config_file = config_file or _CONFIG_FILE
        self._providers: Dict[str, Dict[str, Any]] = {}
        self._generation: Dict[str, Any] = {}
        self._load_config()

    # ──────────────────────────────────────────────────────
    # 单例与配置
    # ──────────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> "ImageService":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load_config(self) -> None:
        data: Dict[str, Any] = {}
        try:
            if self._config_file.exists():
                data = json.loads(self._config_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[ImageService] 读取配置失败: {exc}")

        self._providers = data.get("image_providers") or {}
        gen = dict(data.get("image_generation") or {})
        gen.setdefault("output_dir", _DEFAULT_OUTPUT_DIR)
        gen.setdefault("default_n", 1)
        gen.setdefault("max_n", 4)
        gen.setdefault("allowed_sizes", list(_DEFAULT_SIZES))
        gen.setdefault("timeout", 180)
        self._generation = gen

    def reload(self) -> None:
        """热加载配置（配置变更后无需重启）。"""
        self._load_config()
        logger.info("[ImageService] 配置已重新加载")

    # ──────────────────────────────────────────────────────
    # 路径与索引
    # ──────────────────────────────────────────────────────

    def _output_dir(self) -> Path:
        raw = str(self._generation.get("output_dir") or _DEFAULT_OUTPUT_DIR)
        path = Path(raw)
        return path if path.is_absolute() else (_ROOT / path)

    def _index_file(self) -> Path:
        return self._output_dir() / "index.jsonl"

    def _append_index(self, record: Dict[str, Any]) -> None:
        try:
            target = self._index_file()
            with _INDEX_LOCK:
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[ImageService] 写入索引失败: {exc}")

    def _read_index(self) -> List[Dict[str, Any]]:
        path = self._index_file()
        records: List[Dict[str, Any]] = []
        try:
            if not path.exists():
                return records
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        records.append(obj)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[ImageService] 读取索引失败: {exc}")
        return records

    # ──────────────────────────────────────────────────────
    # Provider 选择
    # ──────────────────────────────────────────────────────

    def list_providers(self, redact_secrets: bool = True) -> List[Dict[str, Any]]:
        """列出图像 Provider（默认脱敏，供管理页展示）。"""
        items = []
        for name, cfg in self._providers.items():
            items.append({
                "name": name,
                "provider": cfg.get("provider", "openai_compatible"),
                "model": cfg.get("model", ""),
                "api_base": cfg.get("api_base", ""),
                "enabled": bool(cfg.get("enabled", False)),
                "size": cfg.get("size", ""),
                "has_api_key": bool(cfg.get("api_key")),
                **({} if redact_secrets else {"api_key": cfg.get("api_key", "")}),
            })
        return items

    def _pick_provider(self, provider: Optional[str] = None) -> Dict[str, Any]:
        if not self._providers:
            raise ImageProviderError(
                "未配置图片生成服务：请在 config/dfecrab.json 的 image_providers 段补充配置"
            )

        if provider:
            cfg = self._providers.get(provider)
            if not cfg:
                raise ImageProviderError(
                    f"图片模型不存在: {provider}（可选: {', '.join(self._providers.keys())}）"
                )
            return {**cfg, "name": provider}

        for name, cfg in self._providers.items():
            if cfg.get("enabled", False):
                return {**cfg, "name": name}

        # 全禁用时兜底第一个，报错信息更明确
        name = next(iter(self._providers))
        raise ImageProviderError(
            f"没有已启用的图片生成服务（image_providers.enabled=true 缺失），当前候选: {name}"
        )

    # ──────────────────────────────────────────────────────
    # 生成
    # ──────────────────────────────────────────────────────

    def _normalize_size(self, size: Optional[str], cfg: Dict[str, Any]) -> str:
        allowed = [str(s) for s in (self._generation.get("allowed_sizes") or [])]
        candidate = (size or cfg.get("size") or "").strip()
        if not candidate:
            candidate = allowed[0] if allowed else "1024x1024"
        if allowed and candidate not in allowed:
            fallback = (cfg.get("size") or "").strip() or allowed[0]
            logger.warning(f"[ImageService] size={candidate} 不在白名单，回落 {fallback}")
            candidate = fallback
        return candidate

    def _normalize_n(self, n: Any) -> int:
        try:
            value = int(n or self._generation.get("default_n") or 1)
        except (TypeError, ValueError):
            value = 1
        return max(1, min(value, int(self._generation.get("max_n") or 4)))

    def _endpoint(self, api_base: str) -> str:
        return f"{api_base.rstrip('/')}/images/generations"

    def _decode_item(self, item: Dict[str, Any], timeout: float) -> bytes:
        """把服务端返回的一项转成图片字节（兼容 b64_json / url）。"""
        b64 = item.get("b64_json") or item.get("b64") or item.get("image_base64")
        if b64:
            return base64.b64decode(b64)

        url = item.get("url") or item.get("image_url")
        if url:
            import requests
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.content

        raise ImageProviderError("图片服务返回既无 b64_json 也无 url，无法解析")

    def generate(
        self,
        prompt: str,
        size: Optional[str] = None,
        n: Any = 1,
        provider: Optional[str] = None,
        user_id: str = "",
        session_id: str = "",
    ) -> Dict[str, Any]:
        """生成图片并落盘。

        Args:
            prompt: 图片描述（必填）。
            size: 尺寸，如 ``1024x1024``；不传用 provider 默认。
            n: 生成张数（受 image_generation.max_n 限制）。
            provider: 指定 image_providers 中的 key；不传用第一个 enabled。
            user_id / session_id: 归属信息，写入索引与用量事件。

        Returns:
            {"success": True, "provider", "model", "size", "count", "images": [...], "elapsed_ms"}

        Raises:
            ImageProviderError: 配置缺失、参数非法或服务端失败。
        """
        prompt = (prompt or "").strip()
        if not prompt:
            raise ImageProviderError("prompt 不能为空")

        cfg = self._pick_provider(provider)
        if not cfg.get("enabled", False):
            raise ImageProviderError(f"图片模型 {cfg['name']} 未启用（enabled=false）")

        api_base = str(cfg.get("api_base") or "").strip()
        if not api_base:
            raise ImageProviderError(f"图片模型 {cfg['name']} 未配置 api_base")

        final_size = self._normalize_size(size, cfg)
        final_n = self._normalize_n(n)
        timeout = float(cfg.get("timeout") or self._generation.get("timeout") or 180)

        payload: Dict[str, Any] = {
            "model": cfg.get("model") or "",
            "prompt": prompt,
            "n": final_n,
            "size": final_size,
        }
        # 允许现场透传额外字段（如 response_format / negative_prompt）
        extra = cfg.get("extra_body")
        if isinstance(extra, dict):
            payload.update(extra)

        headers = {"Content-Type": "application/json"}
        api_key = str(cfg.get("api_key") or "").strip()
        if api_key and api_key != "not-needed":
            headers["Authorization"] = f"Bearer {api_key}"

        import requests
        import time as _time

        from src.monitoring.usage_store import record_image_gen

        t0 = _time.time()
        try:
            resp = requests.post(
                self._endpoint(api_base), json=payload, headers=headers, timeout=timeout
            )
            if resp.status_code >= 400:
                raise ImageProviderError(
                    f"图片服务返回 HTTP {resp.status_code}: {resp.text[:300]}"
                )
            body = resp.json()
            items = body.get("data") or body.get("images") or []
            if not items:
                raise ImageProviderError(f"图片服务返回空结果: {str(body)[:300]}")
        except ImageProviderError:
            elapsed_ms = int((_time.time() - t0) * 1000)
            record_image_gen(
                provider=cfg["name"], model=cfg.get("model", ""), size=final_size,
                n=final_n, ok=False, elapsed_ms=elapsed_ms,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = int((_time.time() - t0) * 1000)
            record_image_gen(
                provider=cfg["name"], model=cfg.get("model", ""), size=final_size,
                n=final_n, ok=False, elapsed_ms=elapsed_ms, error=str(exc),
            )
            raise ImageProviderError(f"调用图片服务失败: {exc}") from exc

        now = datetime.now()
        day = now.strftime("%Y-%m-%d")
        day_dir = self._output_dir() / day
        saved: List[Dict[str, Any]] = []

        for item in items:
            if not isinstance(item, dict):
                continue
            image_id = uuid.uuid4().hex[:16]
            try:
                blob = self._decode_item(item, timeout)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[ImageService] 解析图片失败: {exc}")
                continue

            filename = f"{image_id}.png"
            try:
                day_dir.mkdir(parents=True, exist_ok=True)
                (day_dir / filename).write_bytes(blob)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"[ImageService] 写入图片失败: {exc}")
                continue

            record = {
                "image_id": image_id,
                "file": f"{day}/{filename}",
                "url": f"/api/images/{image_id}",
                "prompt": prompt,
                "size": final_size,
                "provider": cfg["name"],
                "model": cfg.get("model", ""),
                "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "date": day,
                "user_id": user_id or "",
                "session_id": session_id or "",
                "bytes": len(blob),
            }
            self._append_index(record)
            saved.append(record)

        elapsed_ms = int((_time.time() - t0) * 1000)
        record_image_gen(
            provider=cfg["name"],
            model=cfg.get("model", ""),
            size=final_size,
            n=len(saved),
            ok=bool(saved),
            elapsed_ms=elapsed_ms,
            image_id=saved[0]["image_id"] if saved else "",
            error=None if saved else "所有图片均解析/落盘失败",
        )

        if not saved:
            raise ImageProviderError("图片服务返回了结果，但所有图片均解析失败")

        return {
            "success": True,
            "provider": cfg["name"],
            "model": cfg.get("model", ""),
            "size": final_size,
            "count": len(saved),
            "elapsed_ms": elapsed_ms,
            "images": saved,
        }

    # ──────────────────────────────────────────────────────
    # 查询 / 读取 / 删除
    # ──────────────────────────────────────────────────────

    def list_images(
        self,
        day: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """按倒序分页列出已生成图片（可按日期、用户过滤）。"""
        records = self._read_index()
        if day:
            records = [r for r in records if r.get("date") == day]
        if user_id:
            records = [r for r in records if str(r.get("user_id") or "") == user_id]

        records.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        total = len(records)
        try:
            limit = max(1, min(int(limit), 200))
            offset = max(0, int(offset))
        except (TypeError, ValueError):
            limit, offset = 50, 0

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": records[offset:offset + limit],
        }

    def get_image(self, image_id: str) -> Optional[Dict[str, Any]]:
        """按 id 取图片元数据（含磁盘绝对路径）；不存在返回 None。"""
        if not image_id or not _ID_RE.match(image_id):
            return None
        for record in self._read_index():
            if record.get("image_id") == image_id:
                path = self._output_dir() / str(record.get("file") or "")
                if not path.exists():
                    return None
                return {**record, "path": str(path)}
        return None

    def delete_image(self, image_id: str) -> Dict[str, Any]:
        """删除图片文件并从索引移除。"""
        if not image_id or not _ID_RE.match(image_id):
            return {"success": False, "error": "image_id 非法"}

        records = self._read_index()
        target = next((r for r in records if r.get("image_id") == image_id), None)
        if not target:
            return {"success": False, "error": f"图片不存在: {image_id}"}

        path = self._output_dir() / str(target.get("file") or "")
        try:
            if path.exists():
                path.unlink()
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": f"删除文件失败: {exc}"}

        kept = [r for r in records if r.get("image_id") != image_id]
        try:
            index_file = self._index_file()
            with _INDEX_LOCK:
                tmp = index_file.with_suffix(".jsonl.tmp")
                tmp.write_text(
                    "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in kept),
                    encoding="utf-8",
                )
                tmp.replace(index_file)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[ImageService] 重建索引失败: {exc}")

        return {"success": True, "image_id": image_id}


def get_image_service() -> ImageService:
    """获取全局 ImageService 单例。"""
    return ImageService.get_instance()