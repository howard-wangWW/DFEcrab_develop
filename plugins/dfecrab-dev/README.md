# dfecrab-dev

DFEcrab 开发辅助插件，提供代码审查、测试和文档生成功能。

## 安装

```bash
dfecrab plugin install dfecrab-dev
```

## 命令

### /review
代码审查命令，检查代码质量和规范。

```bash
/review                    # 审查当前目录
/review src/core/         # 审查指定目录
/review --fix             # 审查并自动修复
```

别名: `/cr`

### /test
运行测试并生成报告。

```bash
/test                    # 运行所有测试
/test --coverage        # 显示覆盖率
/test --failed          # 只运行失败的测试
```

别名: `/t`

### /doc
生成或更新文档。

```bash
/doc                     # 为所有代码生成文档
/doc src/core/          # 为指定模块生成文档
/doc --type api         # 生成 API 文档
```

## 代理

### code-reviewer
代码审查专家代理，提供：
- 代码质量分析
- 安全问题检查
- 性能问题识别

### test-generator
测试生成专家代理，提供：
- 自动生成测试用例
- 覆盖率分析
- 测试建议

## 技能

### python-development
Python 开发最佳实践：
- PEP 8 规范
- 类型注解
- 文档字符串

## 钩子

- `pre_commit`: 提交前检查测试是否通过
- `session_start`: 会话开始时加载项目上下文

---
作者: DFEcrab Team
版本: 1.0.0
