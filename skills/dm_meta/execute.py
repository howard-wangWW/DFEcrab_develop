"""
达梦数据库元数据查询技能 (DM Meta)
"""
import argparse
import json

def execute():
    try:
        try:
            import dmPython
        except ImportError as exc:
            raise RuntimeError("缺少 dmPython 依赖，无法读取达梦元数据") from exc

        conn = dmPython.connect(
            user="xopens",
            password="ytdf000000",
            server="172.20.42.247",
            port=5236,
            autoCommit=True
        )
        cur = conn.cursor()
        
        tables = [
            'AI_ZD_FEEDER', 
            'AI_ANALYSE_PB', 
            'AI_ANALYSE_FEEDER', 
            'AI_PZZD_DETECTION', 
            'IFA_INDEX', 
            'TX6_DEV_ZWBDZ', 
            'TX6_DEV_ZWQY'
        ]
        schema_info = {}
        
        for table_name in tables:
            # 1. 查询列名、注释、数据类型
            sql = """
                SELECT a.column_name,
                       NVL(c.comments, '') AS comments,
                       a.data_type
                FROM   all_tab_columns a
                LEFT   JOIN all_col_comments c
                       ON c.owner       = a.owner
                      AND c.table_name  = a.table_name
                      AND c.column_name = a.column_name
                WHERE  a.owner      = 'XOPENS'
                  AND  a.table_name = ?
                ORDER  BY a.column_id
            """
            cur.execute(sql, (table_name,))
            columns = {}
            column_names = []
            for row in cur.fetchall():
                col_name, comment, data_type = row
                columns[col_name] = {
                    "desc": comment,
                    "type": data_type
                }
                column_names.append(col_name)
            
            # 2. 抽样查询前3条数据，获取示例值
            samples = {}
            try:
                # 构建SELECT语句，限制3条
                cols_str = ", ".join([f'"{c}"' for c in column_names[:10]])  # 最多查10列避免太长
                sample_sql = f'SELECT {cols_str} FROM XOPENS.{table_name} FETCH FIRST 3 ROWS ONLY'
                cur.execute(sample_sql)
                sample_rows = cur.fetchall()
                
                for col_idx, col_name in enumerate(column_names[:10]):
                    col_samples = []
                    for row in sample_rows:
                        if col_idx < len(row) and row[col_idx] is not None:
                            val = str(row[col_idx])
                            if len(val) > 50:
                                val = val[:50] + "..."
                            col_samples.append(val)
                    if col_samples:
                        samples[col_name] = col_samples
            except Exception as se:
                # 抽样查询失败不影响主流程
                pass
            
            # 3. 组装结果
            schema_info[f"XOPENS.{table_name}"] = {
                "table": f"XOPENS.{table_name}",
                "columns": columns,
                "samples": samples
            }
            
        return {
            "status": "success",
            "data": schema_info
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "data": {}
        }
    finally:
        try:
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()
        except:
            pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    args = parser.parse_args()
    result = execute()
    print(json.dumps(result, ensure_ascii=False, default=str))
