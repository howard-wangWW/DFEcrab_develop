# -*- coding: utf-8 -*-
import dmPython
from config import DMConfig

class DMQuery:
    def __init__(self):
        self.config = DMConfig()
        self.conn = None
        
    def connect(self):
        try:
            self.conn = dmPython.connect(
                user=self.config.USER,
                password=self.config.PASSWORD,
                server=self.config.HOST,
                port=self.config.PORT,
                schema=self.config.SCHEMA
            )
            print(f"连接成功 -> {self.config.HOST}:{self.config.PORT}/{self.config.SCHEMA}")
        except Exception as e:
            print(f"连接失败: {e}")
            raise
    
    def close(self):
        if self.conn:
            self.conn.close()
    
    def query_table(self, table_name, limit=10, columns="*", where_clause=""):
        if not self.conn:
            self.connect()
        
        sql = f"SELECT {columns} FROM {self.config.SCHEMA}.{table_name}"
        if where_clause:
            sql += f" WHERE {where_clause}"
        sql += f" LIMIT {limit}"
        
        print(f"执行 SQL: {sql}")
        cursor = self.conn.cursor()
        cursor.execute(sql)
        col_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        cursor.close()
        
        # 打印结果表格
        print("\n" + " | ".join(col_names))
        print("-" * 80)
        for row in rows:
            print(" | ".join(str(v) for v in row))
        print(f"共返回 {len(rows)} 行\n")
        return rows
    
    def get_table_preview(self, table_name, limit=5):
        print(f"\n===== 表 {table_name} 前 {limit} 行 =====")
        rows = self.query_table(table_name, limit=limit)
        return rows

if __name__ == "__main__":
    dq = DMQuery()
    try:
        for tbl in ["AI_ANALYSE_PB", "AI_ANALYSE_FEEDER", "IFA_INDEX"]:
            dq.get_table_preview(tbl, limit=5)
    finally:
        dq.close()