# code_executor Python代码沙箱执行工具

## 能力
你可以编写Python代码，调用`code_executor`工具运行代码。
工具会在隔离子进程运行代码，限制CPU、内存、文件输出大小，超时自动杀死进程。

## 使用方式
参数 `code` 传入你的完整Python代码，支持直接写markdown ```python 代码块，工具会自动提取代码内容。
可选参数 `timeout` 设置超时，默认5秒。

## 返回结果字段
- success(bool): 是否执行成功
- stdout: 标准输出
- stderr: 标准错误输出，报错堆栈在这里
- returncode: 进程返回码，0代表正常
- timed_out: 是否执行超时

## 约束
- ❌ 禁止 import os / subprocess / socket / sys / importlib 等高危模块
- ❌ 不要做网络请求、读写系统文件
- ✅ 适合数值计算、pandas数据处理、数学运算、文本处理

## 工作流建议
1. 分析问题，编写Python代码
2. 调用code_executor执行代码
3. 根据stdout/stderr结果修正代码，循环迭代直到得到正确答案
