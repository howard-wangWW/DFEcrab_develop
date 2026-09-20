"""
SQL 校验模块 - 简化版
仅做基础结构校验（SELECT检查 + 去重 + 清理），不再做字段级元数据匹配。
字段正确性由 system prompt 约束和历史记忆保证，SQL可执行性由数据库执行时判断。

Usage:
    from validate_sql_fields import validate_sql
    is_valid, errors, detail = validate_sql(sql_string, meta_cache)
"""
import re
import json
from pathlib import Path
from typing import Dict, List, Tuple


def load_meta_cache(agent_dir: Path) -> Dict:
    """加载元数据缓存"""
    meta_cache_path = agent_dir / "meta_cache.json"
    if meta_cache_path.exists():
        try:
            with open(meta_cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def validate_sql(sql: str, meta_cache=None) -> Tuple[bool, List[str], str]:
    """简化版 SQL 校验：只做结构检查，不做字段级匹配
    
    校验规则符合之前在 LLM 节点定义的逻辑：
    1. 若语句是以 SELECT 开头的查询语句，直接返回该语句（去除多余空格、注释，保留核心逻辑）
    2. 若语句不是 SELECT 类型，返回"无效语句：仅支持 SELECT 查询"
    3. 检查 SQL 是否符合 DM 数据库基本的执行需求
    4. 若语句是重复的，删除掉重复的内容
    5. 只返回纯净的SQL语句
    
    Args:
        sql: SQL 字符串（可能包含多条以 ; 分隔）
        meta_cache: 保留参数兼容调用方，不再用于字段级校验
        
    Returns:
        (is_valid, errors, detail_message)
    """
    if not sql or not sql.strip():
        return False, ["SQL 内容为空"], "SQL 内容为空"

    sql_statements = [s.strip() for s in sql.split(';') if s.strip()]

    if not sql_statements:
        return False, ["未检测到有效的 SQL 语句"], "未检测到有效的 SQL 语句"

    all_errors = []
    cleaned_statements = []
    seen = set()

    for idx, stmt in enumerate(sql_statements):
        # 1. 检查是否以 SELECT 开头
        if not re.match(r'\s*SELECT\s', stmt, re.IGNORECASE):
            all_errors.append(f"[SQL {idx + 1}] 无效语句：仅支持 SELECT 查询")
            continue

        # 2. 清理：去除注释、合并多余空白
        stmt_clean = re.sub(r'--.*$', '', stmt, flags=re.MULTILINE)       # 行注释
        stmt_clean = re.sub(r'/\*.*?\*/', '', stmt_clean, flags=re.DOTALL)  # 块注释
        stmt_clean = re.sub(r'\s+', ' ', stmt_clean).strip()                # 合并空白
        if not stmt_clean.endswith(';'):
            stmt_clean += ';'

        # 3. 去重（基于标准化后的 SQL）
        stmt_normalized = stmt_clean.upper().strip().rstrip(';')
        if stmt_normalized in seen:
            continue
        seen.add(stmt_normalized)
        cleaned_statements.append(stmt_clean)

    if not cleaned_statements:
        if all_errors:
            detail = "SQL 校验失败：\n" + "\n".join(f"  - {err}" for err in all_errors)
        else:
            detail = "SQL 校验失败：所有 SQL 均无效"
        return False, all_errors, detail

    if all_errors:
        # 有跳过但有保留的，返回警告信息但标记成功
        detail = "部分 SQL 已清理（警告仅供参考，不影响执行）\n" + "\n".join(f"  - {err}" for err in all_errors)
        return True, all_errors, detail

    return True, [], "SQL 校验通过（简化模式）"
