# src/knowledge/paths.py
"""
知识库路径统一入口 — 基于 __file__ 锚定项目根，消除 CWD 依赖。

背景：knowledge_api 若从非项目根目录启动（systemd / 手动指定工作目录），
原相对路径 "knowledge_base/index"、"config/dfecrab.json" 都会加载失败，
且因日志缺失表现为"检索为空/降级本地拼接"等静默故障。
"""
from pathlib import Path


# src/knowledge/paths.py → parents[0]=knowledge, [1]=src, [2]=项目根
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 知识库版本（单一事实源：/knowledge/health、启动日志、对接文档统一引用，避免版本号漂移）
# 阶段 5 功能收口后再递增。
KNOWLEDGE_VERSION = "1.5.0"

# 支持的文档扩展名（单一事实源：DocumentLoader 与 DocumentRepository 共用，避免两处白名单漂移）
# 说明：.xlsx/.csv 走纯标准库解析；.xls 需 xlrd；.doc 需 antiword（详见 document_loader / xlsx_loader）
SUPPORTED_EXTENSIONS = {'.txt', '.md', '.pdf', '.docx', '.doc', '.xlsx', '.xls', '.csv'}

# 知识库数据目录（仓库/索引/切片）
KNOWLEDGE_BASE = PROJECT_ROOT / "knowledge_base"

# 向量索引目录（知识库技能加载与重建共用的唯一事实源）
INDEX_DIR = KNOWLEDGE_BASE / "index"

# 文档内嵌图片落盘目录（knowledge_base/media/{doc_id}/NNN.ext）
# 切片正文里只放占位块【图片：NNN.ext】，原图存这里，由 /knowledge/media/{doc_id}/{name} 提供
MEDIA_DIR = KNOWLEDGE_BASE / "media"

# LLM 配置（知识库 chat 综合回答用）
LLM_CONFIG_FILE = PROJECT_ROOT / "config" / "dfecrab.json"


def require_runtime_deps() -> None:
    """校验知识库关键第三方依赖是否可用；缺失时给出"请用项目 venv"的明确提示并退出。

    背景：scripts/ 下的运维脚本依赖 venv 内的 jieba / faiss / numpy 等，
    若误用系统 Python（如 conda base）会抛出难以定位的 ModuleNotFoundError。
    这些脚本在导入重依赖前调用本函数，即可得到可执行的修复指引。
    """
    import importlib
    import sys

    missing = []
    for mod, pkg in (("jieba", "jieba"), ("faiss", "faiss-cpu"), ("numpy", "numpy")):
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(pkg)
    if not missing:
        return

    venv_py = PROJECT_ROOT / "venv" / "bin" / "python3"
    raise SystemExit(
        "❌ 知识库脚本缺少依赖: " + ", ".join(missing) + "\n"
        f"   当前解释器: {sys.executable}\n"
        "   请改用项目虚拟环境运行，例如:\n"
        f"       {venv_py} scripts/<脚本名> [参数]\n"
        f"   或先激活虚拟环境: source {PROJECT_ROOT}/venv/bin/activate"
    )
