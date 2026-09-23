"""
计算数学表达式
"""


def execute(expr: str):
    """计算数学表达式

    Args:
        expr: 数学表达式，如 "2 + 3 * 4"

    Returns:
        计算结果
    """
    try:
        result = eval(expr)
        return str(result)
    except Exception as e:
        return f"计算出错: {e}"
