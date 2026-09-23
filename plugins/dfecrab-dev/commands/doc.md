# /doc - 文档生成

为代码生成或更新文档。

## 执行步骤

1. **分析代码**
   - 解析函数签名
   - 提取类型注解
   - 分析代码逻辑

2. **生成文档**
   - 函数文档字符串
   - 模块文档
   - API 文档

3. **更新现有文档**
   - 检查过期内容
   - 同步最新变更

## 文档模板

### 函数文档
```python
def function_name(param1: Type1, param2: Type2) -> ReturnType:
    """
    函数简要描述

    详细描述...

    Args:
        param1: 参数1描述
        param2: 参数2描述

    Returns:
        返回值描述

    Raises:
        ExceptionType: 异常描述

    Examples:
        >>> function_name(arg1, arg2)
        expected_result
    """
```

### 模块文档
```python
"""
模块名称

模块简要描述

详细描述...

Usage:
    from module import Class
    obj = Class()
"""
```

## 参数

- `type`: 文档类型 (`api`, `readme`, `changelog`)
- `output`: 输出目录
- `format`: 输出格式 (`markdown`, `rst`, `html`)

## 示例

```bash
/doc                           # 为所有代码生成文档
/doc src/core/memory/          # 为指定模块生成文档
/doc --type api --format html  # 生成 HTML 格式的 API 文档
```
