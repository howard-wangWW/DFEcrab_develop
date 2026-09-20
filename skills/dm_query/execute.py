"""
达梦数据库查询技能 (DM Query)
"""
import argparse
import json
import time
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import date, datetime

SKILL_METADATA = {
    "name": "dm_query",
    "description": "执行达梦数据库查询并返回结果。仅用于查询达梦业务表或电网实时数据；不要用于知识库文档、规程规范、操作手册的检索。",
    "parameters": {
        "type": "object",
        "properties": {
            "sql_query": {
                "type": "string",
                "description": "需要执行的完整 SQL 查询语句，例如：SELECT * FROM XOPENS.AI_ANALYSE_FEEDER",
                "default": ""
            }
        },
        "required": ["sql_query"]
    }
}

def get_conn():
    """建立达梦数据库连接"""
    try:
        import dmPython
    except ImportError as exc:
        raise RuntimeError("缺少 dmPython 依赖，无法连接达梦数据库") from exc

    return dmPython.connect(
        user="xopens",
        password="ytdf000000",
        server="172.20.42.247",
        port=5236,
        autoCommit=True
    )

def _safe_close(obj):
    if obj:
        try:
            obj.close()
        except:
            pass

def _db_value_jsonable(v):
    if v is None:
        return None
    if hasattr(v, "read"):
        try:
            v = v.read()
        except Exception:
            return None
    if isinstance(v, memoryview):
        v = v.tobytes()
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", "ignore")
        except Exception:
            return None
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, (date, datetime)):
        return str(v)
    return v

def execute(sql_query: str = "") -> Dict[str, Any]:
    """
    执行数据库查询 (原汁原味的 DM-python247excel.py 逻辑)
    """
    if not sql_query:
        return {
            "status": "error",
            "message": "请提供 SQL 查询语句！",
            "data": []
        }

    sql = sql_query.strip()
    if not sql.upper().startswith("SELECT"):
        return {
            "status": "error",
            "message": "仅支持 SELECT 语句",
            "data": []
        }

    conn = None
    cur = None
    start_perf = time.perf_counter()
    
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(sql)
        
        if not cur.description:
            elapsed_ms = (time.perf_counter() - start_perf) * 1000
            return {
                "status": "success",
                "columns": [],
                "data": [],
                "row_count": 0,
                "elapsed_ms": round(elapsed_ms, 3)
            }
            
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        
        if not rows:
            elapsed_ms = (time.perf_counter() - start_perf) * 1000
            return {
                "status": "success",
                "columns": cols,
                "data": [],
                "row_count": 0,
                "elapsed_ms": round(elapsed_ms, 3)
            }
             
        data = [
            {cols[i]: _db_value_jsonable(row[i]) for i in range(len(cols))}
            for row in rows
        ]
        elapsed_ms = (time.perf_counter() - start_perf) * 1000
        
        return {
            "status": "success",
            "columns": cols,
            "data": data,
            "row_count": len(data),
            "elapsed_ms": round(elapsed_ms, 3)
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "data": []
        }
    finally:
        _safe_close(cur)
        _safe_close(conn)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sql-query", default="")
    parser.add_argument("--query-mode", default="normal")
    parser.add_argument("--time-info", default="{}")
    args = parser.parse_args()
    result = execute(sql_query=args.sql_query)
    print(json.dumps(result, ensure_ascii=False, default=str))
