import dmPython
import sys
import traceback

try:
    print("正在尝试连接达梦数据库...")
    conn = dmPython.connect(
        user='xopens',      # 例如 SYSDBA
        password='ytdf000000',    # 替换成真实密码
        server='172.20.42.72', # 你的服务器IP
        port=5236,
        autoCommit=True
    )
    print("✅ 连接成功！")
    conn.close()
except dmPython.Error as e:
    # 如果能捕获到达梦原生的错误，这里会打印具体信息
    print(f"❌ 达梦原生错误: {e}")
    traceback.print_exc()
except Exception as e:
    # 如果还是之前的通用异常，我们也打印出来
    print(f"❌ 连接失败: {e}")
    traceback.print_exc()