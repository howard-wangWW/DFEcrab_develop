# -*- coding: utf-8 -*-
"""远端代码执行客户端（路线 C：复用 LibreChat 的本地代码沙箱服务）。

**只读复用** LibreChat 的 `local-code-api`（容器 `librechat-code-api`，默认 :8008）：
DFEcrab 侧不新增任何服务，LibreChat 侧不做任何修改。

契约真源 = `LibreChat/local-code-api/server.py`（逐字对齐的部分）：

    GET  /health                         → {"ok": true}
    POST /exec    {lang, code, args[], session_id, files[{id,name}]}
                  → 200 {stdout, stderr, session_id, files[{id,name,session_id,storage_session_id}]}
                    429 {"error": "sandbox is busy; try again shortly"}
                    413 {"error": "request body too large"}（> LOCAL_CODE_API_MAX_BODY，实际 2MB）
    POST /upload  multipart/form-data（kind=user|agent|skill, id, [version], file）
                  → 200 {message, storage_session_id, files[{status,fileId,filename}]}
    GET  /download/<session>/<file_id>   → 二进制（`do_GET` 只取 parts[2] 作为 file_id）
    GET  /sessions/<sid>/objects/<fid>   → {"lastModified": "..."}
    DELETE /sessions/<sid>/objects/<fid> → 204

与本地模式（backend=local）的语义差异（刻意的，逐条如下）：

  1. `/mnt/data` 是**容器的真实挂载点**（compose 的 `code_sandbox` 卷）→ **不做**
     realize/virtualize 双向映射（那是无容器形态的适配）。
  2. 执行环境（依赖库、中文字体、matplotlibrc/sitecustomize、资源上限、并发闸门、语言支持）
     与 LibreChat **完全同一套实现** → 这部分不会再随 LibreChat 升级而漂移。
  3. 结果加工（截断、`Process exited with code N.`、`Execution timed out after N s.`）
     已由服务端的 `_bounded_text` + `do_POST` 完成 → 本地**不再二次加工**，
     避免出现两个 `Process exited` 行。
  4. 会话附件要先 `POST /upload`，执行时按 `files[{id,name}]` 引用交给服务端 staging；
     服务端会把它复制进 workspace（以及 `/mnt/data` 根），执行后还原根副本。
  5. 产物由服务端在 **rc==0** 时扫描并返回；本地据此下载到本地工作区，
     再由既有的 `detect_outputs` / `register_outputs` 发现并登记
     （产物登记链路 `artifacts.py` 无需改动）。

已知契约局限：
  - `/exec` 响应**不含 returncode**，只能从加工后的 stderr 尾部反推
    （rc≠0 且 stderr 非空时，服务端会追加 `Process exited with code N.`）。
    "rc≠0 且 stderr 为空"的情形无法区分，但此时服务端返回的 `files` 必为空
    （服务端只在 rc==0 时才 `_scan_files`）→ 本地不会下载任何东西 →
    不可能出现"失败却登记了产物"。
  - 并发超限返回 429（服务端 `MAX_CONCURRENT=2`），本客户端按 `busy_retry` 退避重试。
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 默认配置（可被 dfecrab.json 的 sandbox.remote 覆盖）──────────────────────
_REMOTE_DEFAULTS: Dict[str, Any] = {
    # 候选地址按序探测（GET {base}/health，期望 200 + {"ok":true}），命中即用并缓存。
    # 默认只放回环；容器 IP 由 discover_container_id 自动补进候选项。
    "base_urls": ["http://127.0.0.1:8008"],
    # 自动发现：docker inspect <container> 取容器在自定义 bridge 网络里的 IP。
    # 宿主机到容器 IP 是通的（internal:true 只影响容器的出站 NAT，不影响宿主机访问）。
    "discover_container": True,
    "container": "librechat-code-api",
    # HTTP 读超时 = 远端执行超时 + 余量（远端 900s，读超时必须更大）
    "http_timeout_pad_sec": 60,
    # 健康探测缓存秒数
    "probe_cache_sec": 60,
    # 服务繁忙（429）的退避重试
    "busy_retry": 4,
    "busy_retry_wait_sec": 2.0,
}

_PROBE_CACHE: Dict[str, Any] = {}
_MULTIPART_BOUNDARY_PREFIX = "----DFEcrabRemoteBoundary"


class RemoteUnavailable(RuntimeError):
    """远端沙箱不可达或返回异常（携带与本地模式风格一致的错误前缀）。"""


# ── 配置 ────────────────────────────────────────────────────────────────────

def _remote_cfg() -> Dict[str, Any]:
    raw: Dict[str, Any] = {}
    try:
        from .config import sandbox_cfg
        sec = sandbox_cfg().get("remote")
        if isinstance(sec, dict):
            raw = sec
    except Exception:
        raw = {}
    merged = dict(_REMOTE_DEFAULTS)
    merged.update({k: v for k, v in raw.items() if not str(k).startswith("_")})
    return merged


def _candidates() -> List[str]:
    out: List[str] = []
    cfg = _remote_cfg()

    def _add(u: Any) -> None:
        s = str(u or "").strip().rstrip("/")
        if s and s not in out:
            out.append(s)

    for u in (cfg.get("base_urls") or []):
        _add(u)
    if cfg.get("discover_container", True):
        ip = _discover_container_ip(str(cfg.get("container") or ""))
        if ip:
            _add(f"http://{ip}:8008")
    return out


def _discover_container_ip(container: str) -> str:
    """docker inspect 取容器 IP（失败返回空串，不抛异常）。

    宿主机访问容器 IP 是通的：`internal: true` 只阻止容器**出站**到外网（不配 NAT），
    宿主机本身在 bridge 上有接口，可直接访问容器 IP。
    """
    if not container:
        return ""
    docker = shutil.which("docker")
    if not docker:
        return ""
    try:
        out = subprocess.run(
            [docker, "inspect", "-f",
             "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", container],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return ""
        for token in (out.stdout or "").split():
            if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", token) and token != "0.0.0.0":
                return token
    except Exception as e:
        logger.debug(f"[Remote] 容器 IP 探测失败（忽略）: {e}")
    return ""


# ── HTTP ────────────────────────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """固定内部目标，不跟随重定向（与 ocr.py 同一取向）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _http(url: str, *, data: Optional[bytes] = None, timeout: float = 30.0,
          method: str = "GET", content_type: str = "application/json",
          raw: bool = False) -> Tuple[int, Any]:
    """发一次请求。返回 (状态码, bytes|解析后的 dict)。网络层异常抛 RemoteUnavailable。"""
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("content-type", content_type)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            body = resp.read()
            code = int(getattr(resp, "status", 200) or 200)
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        code = int(e.code or 0)
    except Exception as e:
        raise RemoteUnavailable(f"REMOTE_SERVICE: 无法连接远端沙箱 {url}（{e}）") from e

    if raw:
        return code, body
    try:
        payload = json.loads(body.decode("utf-8", errors="replace")) if body else {}
    except Exception:
        payload = {}
    return code, payload


def probe(force: bool = False) -> Dict[str, Any]:
    """探测远端沙箱可达性：返回 {ok, base, tried, error}。结果按 probe_cache_sec 缓存。"""
    cfg = _remote_cfg()
    ttl = float(cfg.get("probe_cache_sec") or 60)
    if not force and _PROBE_CACHE and (time.time() - float(_PROBE_CACHE.get("ts") or 0) < ttl):
        return dict(_PROBE_CACHE.get("result") or {})

    tried: List[str] = []
    last_err = ""
    for base in _candidates():
        url = f"{base}/health"
        tried.append(url)
        try:
            code, payload = _http(url, timeout=6.0)
            if code != 200:
                last_err = f"{url} → HTTP {code}"
                continue
            if not (isinstance(payload, dict) and payload.get("ok") is True):
                last_err = f"{url} → 响应不是 {{\"ok\": true}}（{payload!r}）"
                continue
            result = {"ok": True, "base": base, "tried": tried, "error": ""}
            _PROBE_CACHE.update({"ts": time.time(), "result": result})
            return result
        except RemoteUnavailable as e:
            last_err = str(e)
        except Exception as e:
            last_err = f"{url} → {e}"

    result = {
        "ok": False, "base": "", "tried": tried,
        "error": last_err or (
            "远端沙箱不可达（候选地址均已尝试）。请确认 librechat-code-api 容器在运行，"
            "并考虑给它加 ports: [\"127.0.0.1:8008:8008\"]（LibreChat 侧改动，需确认）"
            "或在 sandbox.remote.base_urls 里显式写可达地址。"
        ),
    }
    _PROBE_CACHE.update({"ts": time.time(), "result": result})
    return result


def reset_probe_cache() -> None:
    _PROBE_CACHE.clear()


# ── 本地状态（远端 file_id 缓存，避免每次执行都重新上传附件）──────────────

def _state_path() -> Path:
    from .paths import workspace_root
    return workspace_root() / "remote_state.json"


def _state_load() -> Dict[str, Any]:
    p = _state_path()
    if not p.is_file():
        return {"version": 1, "sessions": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("sessions"), dict):
            return data
    except Exception as e:
        logger.warning(f"[Remote] 状态文件损坏，将重建: {e}")
    return {"version": 1, "sessions": {}}


def _state_save(state: Dict[str, Any]) -> None:
    p = _state_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:
        logger.warning(f"[Remote] 状态写入失败（忽略，仅影响上传去重）: {e}")


# ── multipart（stdlib 没有 client 侧实现，手写）──────────────────────────────

def _multipart_body(filename: str, data: bytes) -> Tuple[bytes, str]:
    boundary = f"{_MULTIPART_BOUNDARY_PREFIX}{uuid.uuid4().hex}"
    safe = str(filename).replace("\\", "_").replace('"', "_") or "file"
    parts: List[bytes] = []

    def _field(name: str, value: str) -> None:
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode("utf-8")
        )

    # 服务端 _validate_upload_identity 要求 kind ∈ {user, agent, skill} 且 id 非空
    _field("kind", "user")
    _field("id", "dfecrab")
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{safe}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8")
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# ── 附件上传（带本地指纹缓存）───────────────────────────────────────────────

def _session_attachments(session_id: str) -> List[Tuple[Path, str]]:
    """本会话可见的 active 文件（上传附件 + 既往产物），返回 [(本地路径, 原名)]。

    语义与 LibreChat 的"会话文件在 /mnt/data 可见"等价：上一轮产出的文件在后续调用里
    依然可被读取/修改。只收录注册表里 status=active 且实体存在的记录。
    """
    out: List[Tuple[Path, str]] = []
    seen: set = set()
    try:
        from src.files.registry import list_by_session
        recs = list_by_session(session_id)
    except Exception as e:
        logger.debug(f"[Remote] 读取会话文件记录失败: {e}")
        return out
    for rec in recs or []:
        if not isinstance(rec, dict):
            continue
        if str(rec.get("status") or "active") != "active":
            continue
        p = Path(str(rec.get("storage") or ""))
        if not p.is_file():
            continue
        name = Path(str(rec.get("filename") or p.name)).name
        if not name or name in seen:
            continue
        seen.add(name)
        out.append((p, name))
    return out


def _fingerprint(p: Path) -> Optional[Tuple[int, int]]:
    try:
        st = p.stat()
        return int(st.st_size), int(st.st_mtime)
    except OSError:
        return None


def _upload_one(base: str, path: Path, name: str, timeout: float) -> str:
    """上传单个文件，返回远端 fileId（服务端 state 里的指纹 id）。"""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise RemoteUnavailable(f"REMOTE_INPUT: 无法读取待上传附件 {name}（{e}）")
    body, ctype = _multipart_body(name, data)
    code, payload = _http(f"{base}/upload", data=body, timeout=timeout,
                          method="POST", content_type=ctype)
    if code != 200 or not isinstance(payload, dict):
        raise RemoteUnavailable(f"REMOTE_UPLOAD: 上传 {name} 失败（HTTP {code}）")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise RemoteUnavailable(f"REMOTE_UPLOAD: 上传 {name} 的响应缺少 files")
    first = files[0]
    if str(first.get("status")) != "success" or not first.get("fileId"):
        raise RemoteUnavailable(
            f"REMOTE_UPLOAD: 上传 {name} 未成功（{first.get('error') or first.get('status')}）"
        )
    return str(first["fileId"])


def ensure_uploads(base: str, session_id: str, timeout: float) -> List[Dict[str, str]]:
    """把本会话文件同步到远端沙箱，返回 /exec 用的 files 引用 [{id, name}]。

    去重依据：(文件名, 大小, mtime) 三元组。命中缓存则直接复用远端 fileId。
    单个文件失败只记日志并跳过（不阻塞执行本身），与"附件是可选项"的取向一致。
    """
    atts = _session_attachments(session_id)
    if not atts:
        return []

    state = _state_load()
    sessions = state.setdefault("sessions", {})
    entry = sessions.setdefault(session_id, {})
    cache = entry.setdefault("files", {})

    refs: List[Dict[str, str]] = []
    dirty = False
    for path, name in atts:
        fp = _fingerprint(path)
        if fp is None:
            continue
        cached = cache.get(name)
        if isinstance(cached, dict) and cached.get("id") \
                and int(cached.get("size") or -1) == fp[0] \
                and int(cached.get("mtime") or -1) == fp[1]:
            refs.append({"id": str(cached["id"]), "name": name})
            continue
        try:
            fid = _upload_one(base, path, name, timeout)
        except RemoteUnavailable as e:
            logger.warning(f"[Remote] 附件 {name} 上传失败，跳过: {e}")
            continue
        cache[name] = {"id": fid, "size": fp[0], "mtime": fp[1]}
        dirty = True
        refs.append({"id": fid, "name": name})

    if dirty:
        _state_save(state)
    return refs


# ── 产物下载 ────────────────────────────────────────────────────────────────

def _safe_relative(name: str) -> Optional[Path]:
    """远端返回的产物名 → 工作区相对路径（拒绝绝对路径与 .. 逃逸）。"""
    s = str(name or "").replace("\\", "/").strip()
    if not s or s.startswith("/"):
        return None
    parts = [p for p in s.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return Path(*parts)


def _download_outputs(base: str, session_id: str, files: Any, workspace: Path,
                      timeout: float) -> List[str]:
    """把远端产物取回本地工作区，返回落地的绝对路径列表。

    落在工作区而非产物目录，是为了让既有的 `artifacts.detect_outputs`（快照 diff）
    自动发现它们——产物登记链路因此完全复用，`artifacts.py` 无需改动。
    """
    saved: List[str] = []
    if not isinstance(files, list):
        return saved
    for item in files:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("id") or "")
        rel = _safe_relative(item.get("name") or "")
        if not fid or rel is None:
            continue
        try:
            code, blob = _http(f"{base}/download/{session_id}/{fid}",
                               timeout=timeout, raw=True)
        except RemoteUnavailable as e:
            logger.warning(f"[Remote] 产物 {rel} 下载失败: {e}")
            continue
        if code != 200 or not blob:
            logger.warning(f"[Remote] 产物 {rel} 下载失败（HTTP {code}）")
            continue
        dest = workspace / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(blob)
            saved.append(str(dest))
        except OSError as e:
            logger.warning(f"[Remote] 产物 {rel} 落盘失败: {e}")
    return saved


# ── 执行 ────────────────────────────────────────────────────────────────────

_RC_RE = re.compile(r"Process exited with code (-?\d+)\.\s*$")
_TIMEOUT_RE = re.compile(r"Execution timed out after \d+s\.")


def _infer_returncode(stderr: str) -> Tuple[int, bool]:
    """从服务端加工过的 stderr 反推 (returncode, timed_out)。

    服务端在 rc≠0 且 stderr 非空时追加 `Process exited with code N.`；
    超时路径还会先写入 `Execution timed out after N s.`（rc=124）。
    """
    text = stderr or ""
    timed_out = bool(_TIMEOUT_RE.search(text))
    m = _RC_RE.search(text)
    if m:
        try:
            return int(m.group(1)), timed_out
        except ValueError:
            pass
    return (124 if timed_out else 0), timed_out


def execute(
    lang: str,
    code: str,
    *,
    workspace: Path,
    args: Optional[List[str]] = None,
    timeout_sec: int = 900,
    max_output_bytes: int = 8388608,
    session_id: str = "",
) -> Dict[str, Any]:
    """在远端沙箱执行一段代码，返回与 `runner.execute_code` 同构的结果。

    返回值：{stdout, stderr, returncode, timed_out, lang, cwd, remote, remote_files}
      - stdout/stderr 是**服务端加工后的最终文本**，本地不再二次加工
      - remote_files 是本次取回的产物落地路径（供调用方/自检观察）
    """
    workspace = Path(workspace)
    lang_norm = str(lang or "").strip().lower()
    base_result = {
        "stdout": "", "stderr": "", "returncode": -1, "timed_out": False,
        "lang": lang_norm, "cwd": "/mnt/data", "remote": True, "remote_files": [],
    }

    p = probe()
    if not p.get("ok"):
        base_result["returncode"] = -1
        base_result["stderr"] = (
            f"REMOTE_SERVICE: 远端沙箱不可达，无法执行。{p.get('error') or ''}\n"
            f"已尝试的地址：{', '.join(p.get('tried') or []) or '（无候选）'}\n"
            "可把 sandbox.backend 改回 \"local\" 使用主机执行。"
        )
        return base_result

    base = str(p["base"])
    cfg = _remote_cfg()
    http_timeout = float(timeout_sec or 900) + float(cfg.get("http_timeout_pad_sec") or 60)
    workspace.mkdir(parents=True, exist_ok=True)

    # 附件引用（失败只记日志，不阻塞执行）
    try:
        file_refs = ensure_uploads(base, session_id, min(http_timeout, 300.0)) if session_id else []
    except Exception as e:
        logger.warning(f"[Remote] 附件同步异常（忽略继续）: {e}")
        file_refs = []

    payload = {
        "lang": lang_norm if lang_norm in ("py", "python", "python3", "bash", "sh") else "bash",
        "code": code,
        "args": [str(a) for a in (args or [])],
        "files": file_refs,
    }
    if session_id:
        payload["session_id"] = session_id

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    retries = int(cfg.get("busy_retry") or 0)
    wait = float(cfg.get("busy_retry_wait_sec") or 2.0)

    attempt = 0
    while True:
        try:
            code_status, resp = _http(f"{base}/exec", data=body, timeout=http_timeout,
                                      method="POST")
        except RemoteUnavailable as e:
            base_result["stderr"] = f"{e}\n可把 sandbox.backend 改回 \"local\" 使用主机执行。"
            return base_result

        if code_status == 429 and attempt < retries:
            attempt += 1
            logger.warning(f"[Remote] 沙箱繁忙（429），第 {attempt} 次退避重试")
            time.sleep(wait * attempt)
            continue
        break

    if code_status != 200 or not isinstance(resp, dict):
        msg = resp.get("error") if isinstance(resp, dict) else ""
        base_result["stderr"] = (
            f"REMOTE_SERVICE: 远端沙箱执行请求失败（HTTP {code_status}）"
            f"{'：' + str(msg) if msg else ''}。"
        )
        return base_result

    # 服务端已做完结果加工（截断 + 退出码行 + 超时行），此处原样透传
    stdout = str(resp.get("stdout") or "")
    stderr = str(resp.get("stderr") or "")
    rc, timed_out = _infer_returncode(stderr)

    remote_files = _download_outputs(
        base, str(resp.get("session_id") or session_id or ""),
        resp.get("files"), workspace, min(http_timeout, 600.0),
    )

    return {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": rc,
        "timed_out": timed_out,
        "lang": lang_norm,
        "cwd": "/mnt/data",
        "remote": True,
        "remote_files": remote_files,
    }
