#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
review_scope_audit.py —— 送审范围判定（只读）

用途
    判定仓库中每个文件在「送审第三方代码审核」时该怎么处置。
    判定遵循「**脱敏优先**」：能脱敏的必须交付，只有无法脱敏的才排除。

        [ALLOW]  直接交付   —— 平台通用能力，不含任何敏感信息
        [MASK]   脱敏后交付 —— 含凭据 / 内网地址 / 现场名 / 甲方表名，
                              替换为占位符后**必须交付**
        [BLOCK]  排除       —— 甲方数据与资产本体（内容即数据，脱敏无意义）
        [SKIP]   排除       —— 生成物 / 部署环境 / 与审核无关（非源码）

    为什么业务代码必须交（这是本脚本的核心原则）：
        1. 静态代码审计要求 100% 代码覆盖，覆盖不足的报告无法律与验收效力；
        2. 扫描工具最大的盲区正是「业务逻辑缺陷」——不交业务实现，等于让审计作废，
           同时把真实的 SQL 注入、越权、参数校验缺失等问题继续藏起来；
        3. 防复刻应靠 NDA / 审核范围书面约定 / 只读环境 / 水印，
           而不是删代码——删代码既防不住，还挡住了审计。

约束（重要）
    - 只读：不修改、不移动、不删除、不脱敏任何文件
    - 不联网：不做任何 HTTP / gRPC / 数据库调用
    - 纯标准库：不依赖任何第三方包，现场 venv 缺失也能跑
    - 规则外置：--rules 可传入 JSON 覆盖内置默认规则，避免"什么算敏感"写死在代码里

用法
    python3 scripts/review_scope_audit.py                     # 扫描并生成报告
    python3 scripts/review_scope_audit.py --handover          # 额外生成交付说明与清单
    python3 scripts/review_scope_audit.py --out-dir /tmp/audit
    python3 scripts/review_scope_audit.py --dump-rules rules.json   # 导出默认规则供修改
    python3 scripts/review_scope_audit.py --json-only

    本脚本只做判定。按判定结果生成送审压缩包用：
        python3 scripts/build_review_package.py --report <out-dir>/review_scope_report.json

输出
    <out-dir>/review_scope_report.json   —— 机器可读，是打包脚本的输入
    <out-dir>/review_scope_report.md     —— 人读清单
    --handover 时额外生成：
    <out-dir>/送审范围说明.md              —— 目录判定 + 逐文件清单
    <out-dir>/01_直接交付清单.txt          —— 可直接用于打包
    <out-dir>/02_脱敏后交付清单.txt
    <out-dir>/03_排除_甲方数据.txt
    <out-dir>/04_排除_非源码.txt
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ============================================================================
# 级别定义（数值越大越严格，同一文件命中多级时取最高）
# ============================================================================

# 同一文件命中多级时取"最高"。
# ⚠️ SKIP 必须高于 MASK：否则 `skills/xxx/__pycache__/*.pyc` 这类生成物会被
#    父目录的 MASK 规则"提级"成需要脱敏的文件，进而混进送审包
#    （.pyc 可反编译 = 泄露源码，且二进制无法脱敏）。生成物一律优先排除。
LEVEL_ORDER = {"ALLOW": 0, "MASK": 1, "SKIP": 2, "BLOCK": 3}
LEVEL_LABEL = {
    "ALLOW": "直接交付",
    "SKIP": "排除·非源码",
    "MASK": "脱敏后交付",
    "BLOCK": "排除·甲方数据",
}

# 内容扫描范围与上限（避免读大文件 / 二进制）
TEXT_EXTS = {
    ".py", ".pyi", ".json", ".yaml", ".yml", ".md", ".txt", ".sh", ".ps1",
    ".cfg", ".ini", ".toml", ".sql", ".proto", ".html", ".htm",
    ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".env", ".conf", ".properties",
}
MAX_SCAN_BYTES = 1_500_000


# ============================================================================
# 默认规则
#   说明：路径规则（dir / glob）用于整块判定；内容规则用于逐文件扫描。
#   全部可被 --rules 传入的文件覆盖，不写死在逻辑里。
# ============================================================================

DEFAULT_RULES = {
    "version": "2.0",
    "_note": (
        "level: ALLOW=直接交付 / MASK=脱敏后交付 / BLOCK=排除(甲方数据) / SKIP=排除(非源码)。"
        "kind: dir=整个子树（命中即不再深入）/ glob=单个路径 / dotdir=任一路径段以点开头。"
        "原则：业务代码一律 MASK（脱敏后必须交），BLOCK 只留给甲方数据本体。"
    ),

    # ---- 路径规则：整块判定 ------------------------------------------------
    "path_rules": [
        # == 必须排除：部署环境与生成物（与敏感无关，纯粹不该外发） ==
        {"level": "SKIP", "kind": "dir", "value": "venv", "reason": "Python 虚拟环境（部署环境，非源码）"},
        {"level": "SKIP", "kind": "dir", "value": "wheels", "reason": "pip 离线包（部署环境）"},
        {"level": "SKIP", "kind": "dir", "value": "runtime", "reason": "Node.js 运行时（部署环境）"},
        {"level": "SKIP", "kind": "dir", "value": "__pycache__", "reason": "字节码缓存（可反编译，进包等同泄露源码）"},
        # 嵌套的 __pycache__（如 skills/kunming_api/__pycache__）——dir 规则只匹配根级，故补 glob
        {"level": "SKIP", "kind": "glob", "value": "*/__pycache__", "reason": "字节码缓存（可反编译，进包等同泄露源码）"},
        {"level": "SKIP", "kind": "glob", "value": "*.pyc", "reason": "字节码文件（可反编译，外发会泄露源码）"},
        {"level": "SKIP", "kind": "glob", "value": "*.whl", "reason": "wheel 包（部署环境）"},
        {"level": "SKIP", "kind": "glob", "value": "*.tar.gz", "reason": "打包产物"},
        {"level": "SKIP", "kind": "dir", "value": ".git", "reason": "版本历史（含全量代码与全部历史提交）"},
        {"level": "SKIP", "kind": "dotdir", "value": ".", "reason": "以点开头的目录（版本控制 / IDE / 工具缓存，非交付源码）"},
        {"level": "SKIP", "kind": "glob", "value": ".DS_Store", "reason": "macOS 系统垃圾文件"},
        {"level": "SKIP", "kind": "glob", "value": "*/.DS_Store", "reason": "macOS 系统垃圾文件（子目录内）"},
        {"level": "SKIP", "kind": "glob", "value": "Thumbs.db", "reason": "Windows 缩略图缓存"},
        {"level": "SKIP", "kind": "glob", "value": "*/Thumbs.db", "reason": "Windows 缩略图缓存（子目录内）"},
        # 归档包与本地数据库：二进制不可脱敏，且常含运行时数据，一律排除
        {"level": "SKIP", "kind": "glob", "value": "*.zip", "reason": "压缩包（二进制不可脱敏；展开后内容不在审核范围）"},
        {"level": "SKIP", "kind": "glob", "value": "*.db", "reason": "本地数据库文件（二进制，常含运行时数据）"},
        {"level": "SKIP", "kind": "glob", "value": "*.sqlite", "reason": "本地数据库文件"},
        {"level": "SKIP", "kind": "glob", "value": "*.sqlite3", "reason": "本地数据库文件"},
        {"level": "SKIP", "kind": "dir", "value": "src/logs", "reason": "src 下的运行日志与 trace 数据库（运行时产物）"},
        # 送审工具自身的产物：报告里含敏感信息的位置索引，绝不能进包
        {"level": "SKIP", "kind": "dir", "value": "review_scope_out", "reason": "送审判定报告输出目录（含敏感位置索引，不可进包）"},
        {"level": "SKIP", "kind": "glob", "value": "review_scope_report.*", "reason": "送审判定报告（含敏感位置索引，不可进包）"},
        {"level": "SKIP", "kind": "glob", "value": "audit_report_*.json", "reason": "审计报告（含敏感位置索引，不可进包）"},
        {"level": "SKIP", "kind": "dir", "value": "dist", "reason": "打包产物目录"},
        {"level": "SKIP", "kind": "glob", "value": "SOP_*.md", "reason": "内部作业指引（描述送审流程，不随包送审）"},
        # 现场自检产物：文件名即含现场标识（如「昆明xxx验证_日期.txt」）。
        # 路径名不做脱敏（改名会破坏引用），故只能整体排除，否则现场名会从文件名泄露。
        {"level": "SKIP", "kind": "dir", "value": "docs/verify_results", "reason": "现场自检产物（文件名含现场标识；如需作为测试证据提交，请先重命名再单独说明）"},
        {"level": "SKIP", "kind": "glob", "value": ".env*", "reason": "本地环境变量文件（可能含凭据）"},
        {"level": "SKIP", "kind": "glob", "value": "*.code-workspace", "reason": "IDE 工作区配置"},
        # 手工备份/临时文件：命名不规范、内容陈旧，常残留真实地址与凭据，一律排除。
        # 现场实测教训：`config.json.bak-20260917` 这类「.bak-日期」后缀不匹配 `*.bak[0-9]*`
        # （点后是连字符不是数字），会被判成 MASK 混进送审包。故用 `*.bak*` 覆盖全部变体。
        {"level": "SKIP", "kind": "glob", "value": "*.bak*", "reason": "手工备份文件（内容陈旧，常残留真实地址/凭据）"},
        {"level": "SKIP", "kind": "glob", "value": "*.pybak*", "reason": "手工备份文件（内容陈旧，常残留真实地址/凭据）"},
        {"level": "SKIP", "kind": "glob", "value": "*.orig", "reason": "合并冲突残留文件"},
        {"level": "SKIP", "kind": "glob", "value": "*.old", "reason": "旧版本残留文件"},
        {"level": "SKIP", "kind": "glob", "value": "*.save", "reason": "编辑器临时保存文件"},
        {"level": "SKIP", "kind": "glob", "value": "*~", "reason": "编辑器备份文件"},
        # ⚠️ 送审工具链自指：这些文件内置了检测关键词（甲方表名、现场名称），
        #    不排除会出现"工具把自己判成敏感文件"的假命中。它们都是内部工具，本就不送审。
        {"level": "SKIP", "kind": "glob", "value": "scripts/review_*.py", "reason": "送审判定工具（内置检测关键词，工具自指，不随包送审）"},
        {"level": "SKIP", "kind": "glob", "value": "scripts/review_*.json", "reason": "脱敏规则（含检测关键词，内部工具配置，不随包送审）"},
        {"level": "SKIP", "kind": "glob", "value": "scripts/build_review_package.py", "reason": "送审打包工具（内部工具，不随包送审）"},
        {"level": "SKIP", "kind": "dir", "value": "LibreChat-intranet-offline-amd64", "reason": "第三方离线包（与本次审核无关）"},
        {"level": "SKIP", "kind": "dir", "value": "tui", "reason": "前端子项目（独立 npm 依赖，与本次审核无关）"},
        # 以下两项由「与审核无关的冗余」主动排除（减小交付面，避免审计方被两套结构干扰）
        {"level": "SKIP", "kind": "dir", "value": "plugins", "reason": "未启用的插件目录（与 skills/ 大量重复，加载器不扫描该目录）"},
        {"level": "SKIP", "kind": "dir", "value": "task_engine", "reason": "早期任务引擎原型（全仓无外部引用，已被 src/task/ 取代）"},

        # == 排除：甲方数据与资产本体 ==
        {"level": "BLOCK", "kind": "dir", "value": "data", "reason": "运行时业务数据（会话/任务/记忆）"},
        {"level": "BLOCK", "kind": "dir", "value": "knowledge_base", "reason": "知识库语料与向量索引（甲方资料）"},
        {"level": "BLOCK", "kind": "dir", "value": "models", "reason": "本地模型权重与配置"},
        {"level": "BLOCK", "kind": "dir", "value": "reflections", "reason": "反思记录（真实对话内容）"},
        {"level": "BLOCK", "kind": "dir", "value": "logs", "reason": "运行日志（含真实业务数据）"},
        {"level": "BLOCK", "kind": "dir", "value": "decks", "reason": "生成的汇报材料（业务产出物）"},
        {"level": "BLOCK", "kind": "dir", "value": "dfecrab-kb-full-20260911-r4", "reason": "知识库分发包（内含源码副本 + 知识库）"},
        {"level": "BLOCK", "kind": "glob", "value": "dfecrab-kb-full-*", "reason": "知识库分发包（内含源码副本 + 知识库）"},

        # == 排除：甲方数据与资产本体（内容即数据，脱敏无意义） ==
        {"level": "BLOCK", "kind": "dir", "value": "mcp_servers/blackxml-topology-mcp", "reason": "电网拓扑资产（甲方 XML 与站点数据本体）"},
        # 说明：services/*/validate_sql_fields.py 只是通用 SQL 结构校验（不做字段级匹配），
        # 真正的库表元数据在 agents/<agent>/meta_cache.json，故规则只挂在后者上。
        {"level": "BLOCK", "kind": "glob", "value": "agents/*/meta_cache.json", "reason": "库表元数据缓存（甲方 schema 本体）"},
        {"level": "BLOCK", "kind": "glob", "value": "config/mcporter.json", "reason": "MCP 工具缓存（含甲方站点名，属运行时生成物，审计价值低而泄露面大）"},

        # == 脱敏后交付：现场业务实现 ==
        # ⚠️ 这些**不要**改成排除。静态代码审计要求 100% 覆盖，而扫描工具的最大盲区
        #    正是业务逻辑缺陷——把业务实现排除在外，等于让审计报告作废，
        #    同时把真实的 SQL 注入 / 越权 / 参数校验缺失继续藏在系统里。
        #    正确做法：脱敏（表名 / 凭据 / 内网地址 / 现场名 → 占位符）后交付。
        {"level": "MASK", "kind": "glob", "value": "DM-*.py", "reason": "现场数据 API 后端（脱敏后交付）"},
        {"level": "MASK", "kind": "glob", "value": "mcp_servers/blackxml*.py", "reason": "电网拓扑 MCP 服务（脱敏后交付；XML 数据本体另见 BLOCK）"},
        {"level": "MASK", "kind": "glob", "value": "mcp_servers/mcp_alert_judge.py", "reason": "告警研判 MCP 服务（脱敏后交付）"},
        {"level": "MASK", "kind": "dir", "value": "src/alert_judge", "reason": "告警研判业务实现（脱敏后交付）"},
        {"level": "MASK", "kind": "glob", "value": "src/skill/extractors/*.py", "reason": "现场参数提取器（脱敏后交付）"},

        # == 脱敏后交付：绑定现场的业务技能 ==
        {"level": "MASK", "kind": "dir", "value": "skills/kunming_api", "reason": "现场数据接口契约（脱敏后交付）"},
        {"level": "MASK", "kind": "dir", "value": "skills/kunming_classifier", "reason": "现场业务分类器（脱敏后交付）"},
        {"level": "MASK", "kind": "dir", "value": "skills/dm_query", "reason": "现场数据库查询技能（脱敏后交付）"},
        {"level": "MASK", "kind": "dir", "value": "skills/dm_meta", "reason": "现场数据库元数据技能（脱敏后交付）"},
        {"level": "MASK", "kind": "dir", "value": "skills/dm_test", "reason": "现场数据库测试技能（脱敏后交付）"},
        {"level": "MASK", "kind": "dir", "value": "skills/load_analysis", "reason": "现场负荷分析技能（脱敏后交付）"},
        {"level": "MASK", "kind": "dir", "value": "skills/power_transfer_strategy", "reason": "现场转供策略技能（脱敏后交付）"},

        # == 脱敏后交付：现场 Agent 角色定义 ==
        {"level": "MASK", "kind": "dir", "value": "agents/kunming", "reason": "现场 Agent 角色与提示词（脱敏后交付）"},
        {"level": "MASK", "kind": "dir", "value": "agents/alert_judge", "reason": "现场 Agent 角色与提示词（脱敏后交付）"},

        # == 脱敏后交付：现场验证脚本（反映真实测试覆盖，审计方会看） ==
        {"level": "MASK", "kind": "glob", "value": "scripts/verify_kunming*.py", "reason": "现场验证脚本（脱敏后交付）"},
        {"level": "MASK", "kind": "glob", "value": "scripts/probe_kunming*.py", "reason": "现场探测脚本（脱敏后交付）"},

        # == 脱敏后交付：含部署信息，但主体是通用代码 / 文档 ==
        {"level": "MASK", "kind": "dir", "value": "config", "reason": "运行配置（含内网地址、现场标识）"},
        {"level": "MASK", "kind": "dir", "value": "docs", "reason": "项目文档（含内网地址与现场描述）"},
        {"level": "MASK", "kind": "dir", "value": "前端对接文档", "reason": "对接文档（需核对是否含现场系统信息）"},
        {"level": "MASK", "kind": "glob", "value": "README.md", "reason": "项目说明（含部署示例地址）"},
        {"level": "MASK", "kind": "glob", "value": "dfecrab", "reason": "启动器（shebang 为现场绝对路径）"},
        {"level": "MASK", "kind": "glob", "value": "requirements.txt", "reason": "依赖清单（含现场路径与部署说明）"},
        {"level": "MASK", "kind": "glob", "value": "agents/dfecrab/*", "reason": "通用 Agent 角色定义（提示词属核心资产，需评估）"},
        {"level": "MASK", "kind": "glob", "value": "agents/code_writer/*", "reason": "通用 Agent 角色定义（提示词属核心资产，需评估）"},
        {"level": "MASK", "kind": "glob", "value": "agents/knowledge_agent/*", "reason": "通用 Agent 角色定义（提示词属核心资产，需评估）"},
        {"level": "MASK", "kind": "glob", "value": "agents/manager_agent/*", "reason": "通用 Agent 角色定义（提示词属核心资产，需评估）"},
        {"level": "MASK", "kind": "glob", "value": "HANDOFF_*.md", "reason": "交接文档（需核对现场信息）"},
        {"level": "BLOCK", "kind": "glob", "value": "1", "reason": "无扩展名的残留文件，内容是甲方告警接口响应转储（含真实变电站名等甲方数据）"},
    ],

    # ---- 内容规则：逐文件扫描 ----------------------------------------------
    # mask: secret=掩码替换 / ip=保留网段 / none=原样展示（关键词本身不涉密）
    #
    # ⚠️ 这里全部是 MASK 级别，不是 BLOCK。原因：
    #    S1–S6 命中的都是「源码里写死的敏感值」——它们**可以被替换掉**，
    #    替换后代码本身仍然可审、且必须审（凭据管理、参数校验、SQL 拼接方式
    #    正是审计要看的点）。判成 BLOCK 会导致整文件被排除，
    #    结果是审计覆盖率不足 + 真实问题继续隐藏在系统里。
    #    打包脚本 build_review_package.py 会对 MASK 文件执行脱敏替换并复扫验证。
    "content_rules": [
        {
            # ⚠️ 只匹配「引号包裹的字面量」：`api_key = cfg.get("api_key", "")` 这类
            #    读取配置的写法端点分隔符很多（. 和 (），不能算明文凭据。
            #    早期版本用 [A-Za-z0-9_.-]{12,} 匹配无引号值，把 `model_config.get`
            #    这类点号标识符误判成密钥，导致 grpc_server.py 等文件被假命中。
            "id": "S1-credential", "level": "MASK", "mask": "secret",
            "reason": "明文凭据字面量（密码 / 密钥 / 令牌）",
            # 用前后断言而非 \b：\b 在中文旁边失效（中文算 \w），会静默漏报
            "pattern": r"(?i)(?<![A-Za-z0-9_])(?:password|passwd|pwd|secret|client[_-]?secret|api[_-]?key|apikey|access[_-]?token|auth[_-]?token|private[_-]?key)\s*[=:]\s*[\"']([^\"'\n]{4,})[\"']",
            "ignore_values": [
                # 配置占位符
                "not-needed", "not_needed", "notneeded", "none", "null", "nil",
                "changeme", "change-me", "change_me", "placeholder", "todo",
                "your-api-key", "your_api_key", "yourapikey", "your-password",
                "your_password", "yourpassword", "xxx",
                # 文档示例值（README / 设计说明书里贴的示例代码，非真实凭据）
                "1234", "123456", "password", "passwd", "example", "demo",
                "dummy", "sample", "fake", "redacted",
            ],
        },
        {
            "id": "S1b-credential-bare", "level": "MASK", "mask": "secret",
            "reason": "疑似明文密钥 / 令牌字面量（无引号）",
            "pattern": r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?token|auth[_-]?token)\b\s*[=:]\s*[A-Za-z0-9+/]{20,}={0,2}\b",
        },
        {
            "id": "S2-env-fallback-secret", "level": "MASK", "mask": "secret",
            "reason": "环境变量兜底值为明文凭据（缺失时应报错，不应回退）",
            "pattern": r"(?i)os\.(?:getenv|environ\.get)\(\s*[\"'][A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|KEY)[A-Z0-9_]*[\"']\s*,\s*[\"'][^\"'\n]+[\"']",
        },
        {
            "id": "S3-bearer", "level": "MASK", "mask": "secret",
            "reason": "硬编码 Bearer 令牌",
            "pattern": r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}",
        },
        {
            "id": "S4-jwt", "level": "MASK", "mask": "secret",
            "reason": "硬编码 JWT",
            # 现场实测教训：JWT 常被拆成多个字符串字面量拼接（跨行、带引号和点），
            # 要求「连续三段点分」的正则会整体漏过，故段间允许引号/空白/换行。
            "pattern": r"eyJ[A-Za-z0-9_\-]{6,}[\"'\s]*\.?[\"'\s]*[A-Za-z0-9_\-]{6,}[\"'\s]*\.?[\"'\s]*[A-Za-z0-9_\-]{6,}",
        },
        {
            "id": "S5-private-key", "level": "MASK", "mask": "none",
            "reason": "内嵌私钥",
            "pattern": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        },
        {
            "id": "S6-party-schema", "level": "MASK", "mask": "none",
            "reason": "甲方库表 / 系统标识（等价于泄露数据模型）",
            # 用前后断言而非 \b：`跳闸表IFA_INDEX：` 这类「中文紧贴表名」的写法 \b 不成立，会漏报
            "pattern": r"(?i)(?<![A-Za-z0-9_])(?:XOPENS|IFA_INDEX|TX6_[A-Z0-9_]+|AI_ANALYSE_[A-Z0-9_]+|AI_ZZD_[A-Z0-9_]+|AI_PZZD_[A-Z0-9_]+|QUALIFIED_COMMAND_PERSONNEL|BLACKXML)(?![A-Za-z0-9_])",
        },
        {
            "id": "S7-internal-ip", "level": "MASK", "mask": "ip",
            "reason": "内网地址（需替换为占位符）",
            "pattern": r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b",
        },
        {
            "id": "S8-site-term", "level": "MASK", "mask": "none",
            "reason": "现场 / 甲方名称（需脱敏）",
            "pattern": None,  # 由 site_terms 组装
        },
        {
            "id": "S9-deploy-path", "level": "MASK", "mask": "none",
            "reason": "部署绝对路径（含现场部署账号，需替换为占位符）",
            # 不只匹配 /home/<user>/DFEcrab：现场还有 /home/<user>/apache-zookeeper-*、
            # /home/<user>/skills/... 等路径，同样暴露部署账号，故整体匹配 /home/<user>
            "pattern": r"/home/[A-Za-z0-9_]+",
        },
    ],

    # ---- 现场名称词表（用于 S8；按需增删，不写死在逻辑里）------------------
    "site_terms": [
        "昆明", "烟台", "深圳", "云南电网", "供电局",
        "kunming", "yantai", "shenzhen",
    ],
}


# ============================================================================
# 规则加载
# ============================================================================

def load_rules(path: str | None) -> dict:
    """加载规则：未指定则用内置默认；指定则整份替换（便于现场调整）。"""
    if not path:
        rules = json.loads(json.dumps(DEFAULT_RULES))  # 深拷贝，避免污染
    else:
        with open(path, encoding="utf-8") as f:
            rules = json.load(f)

    # 校验结构，缺项直接报错（不做兜底）
    for key in ("path_rules", "content_rules", "site_terms"):
        if key not in rules:
            raise SystemExit(f"[FATAL] 规则文件缺少必需字段: {key}")

    # 组装 S8 现场名称正则
    terms = [t for t in rules.get("site_terms") or [] if t]
    if terms:
        alternation = "|".join(re.escape(t) for t in terms)
        pattern = rf"(?i)({alternation})"
    else:
        pattern = r"(?!)"  # 永不匹配

    compiled = []
    for rule in rules["content_rules"]:
        raw = rule.get("pattern")
        if rule["id"] == "S8-site-term" or raw is None:
            raw = pattern
        try:
            rule["_re"] = re.compile(raw)
        except re.error as e:
            raise SystemExit(f"[FATAL] 规则 {rule['id']} 正则非法: {e}")
        compiled.append(rule)
    rules["content_rules"] = compiled
    return rules


# ============================================================================
# 匹配
# ============================================================================

def _norm(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def match_path_rules(rel_path: str, rules: dict, *, is_dir: bool = False) -> tuple[str, list[str]] | None:
    """按路径规则判定，返回 (level, reasons)；无命中返回 None。

    is_dir 用于区分同一条规则该作用于目录还是文件（dotdir 只作用于目录）。
    """
    rel = _norm(rel_path)
    level = None
    reasons: list[str] = []

    for rule in rules["path_rules"]:
        value = _norm(rule["value"])
        hit = False
        if rule["kind"] == "dir":
            hit = rel == value or rel.startswith(value + "/")
        elif rule["kind"] == "glob":
            hit = fnmatch.fnmatch(rel, value) or fnmatch.fnmatch(rel, value + "/*")
        elif rule["kind"] == "dotdir":
            # 任一路径段以 "." 开头（.git / .codebuddy / .trae / .pytest_cache …）；仅目录
            hit = is_dir and any(
                seg.startswith(".") for seg in rel.split("/") if seg not in ("", ".", "..")
            )
        if not hit:
            continue

        r_level = rule["level"]
        if level is None or LEVEL_ORDER[r_level] > LEVEL_ORDER[level]:
            level = r_level
        reasons.append(f"{rule['reason']} [{r_level}]")

    return (level, reasons) if level else None


def _mask(kind: str, matched: str) -> str:
    """命中值掩码：报告里不出现明文凭据。"""
    if kind == "secret":
        return "***"
    if kind == "ip":
        parts = matched.split(".")
        return f"{parts[0]}.{parts[1]}.x.x" if len(parts) == 4 else "***"
    return matched


def scan_content(abs_path: Path, rules: dict) -> list[dict]:
    """扫描单个文本文件，返回命中列表。"""
    try:
        if abs_path.stat().st_size > MAX_SCAN_BYTES:
            return []
        raw = abs_path.read_bytes()
    except OSError:
        return []

    if b"\x00" in raw[:2048]:
        return []  # 二进制

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            return []

    hits: list[dict] = []
    for rule in rules["content_rules"]:
        found = []
        ignore = {v.lower() for v in (rule.get("ignore_values") or [])}
        for m in rule["_re"].finditer(text):
            # 值被判为占位符（not-needed / xxx / test …）时不算明文凭据
            if ignore and m.lastindex and (m.group(1) or "").strip().lower() in ignore:
                continue
            line_no = text.count("\n", 0, m.start()) + 1
            found.append({"line": line_no, "value": _mask(rule["mask"], m.group(0))})
            if len(found) >= 5:  # 单规则单文件最多记 5 处，避免刷屏
                break
        if found:
            hits.append({
                "id": rule["id"],
                "level": rule["level"],
                "reason": rule["reason"],
                "count": len(found),
                "samples": found,
            })
    return hits


# ============================================================================
# 仓库扫描
# ============================================================================

def audit(root: Path, rules: dict, exclude_rels: set[str] | None = None) -> dict:
    root = root.resolve()
    exclude_rels = exclude_rels or set()
    files: list[dict] = []
    dir_hits: list[dict] = []
    scanned = 0

    for cur, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        cur_path = Path(cur)
        try:
            rel_dir = cur_path.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel_dir == ".":
            rel_dir = ""

        # --- 目录剪枝：整块命中 BLOCK/SKIP 的目录（含本脚本自身的输出目录）不再深入 ---
        keep = []
        for d in sorted(dirnames):
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if rel in exclude_rels:
                continue
            hit = match_path_rules(rel, rules, is_dir=True)
            if hit and hit[0] in ("BLOCK", "SKIP"):
                dir_hits.append({"path": rel, "level": hit[0], "reasons": hit[1]})
            else:
                keep.append(d)
        dirnames[:] = keep

        # --- 逐文件判定 ---
        for fn in sorted(filenames):
            rel = f"{rel_dir}/{fn}" if rel_dir else fn
            entry: dict = {"path": rel, "level": "ALLOW", "reasons": [], "hits": []}

            path_hit = match_path_rules(rel, rules)
            if path_hit:
                entry["level"], entry["reasons"] = path_hit
                entry["reasons"] = [
                    r for r in entry["reasons"]
                    if r.endswith(f"[{entry['level']}]")
                ] or entry["reasons"]

            # 内容扫描：SKIP 的文件不必再读（反正要排除）
            if entry["level"] != "SKIP" and Path(fn).suffix.lower() in TEXT_EXTS:
                scanned += 1
                content_hits = scan_content(cur_path / fn, rules)
                if content_hits:
                    entry["hits"] = content_hits
                    entry["reasons"].extend(
                        f"{h['reason']} [{h['level']}]" for h in content_hits
                    )
                    top = max(
                        [entry["level"]] + [h["level"] for h in content_hits],
                        key=lambda lv: LEVEL_ORDER[lv],
                    )
                    entry["level"] = top

            files.append(entry)

    return {
        "root": str(root),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scanned_text_files": scanned,
        "files": files,
        "dir_hits": dir_hits,
    }


# ============================================================================
# 汇总
# ============================================================================

def summarize(result: dict) -> dict:
    by_level: dict[str, int] = defaultdict(int)
    by_dir: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    by_rule: dict[str, dict] = defaultdict(lambda: {"level": "", "reason": "", "files": 0})
    site_terms: dict[str, int] = defaultdict(int)

    for entry in result["files"]:
        lv = entry["level"]
        by_level[lv] += 1
        top = entry["path"].split("/")[0] if "/" in entry["path"] else "(根目录)"
        by_dir[top][lv] += 1
        for h in entry["hits"]:
            agg = by_rule[h["id"]]
            agg["level"] = h["level"]
            agg["reason"] = h["reason"]
            agg["files"] += 1
            if h["id"] == "S8-site-term":
                for sample in h["samples"]:
                    site_terms[sample["value"]] += 1

    for d in result["dir_hits"]:
        by_level[d["level"]] += 1
        top = d["path"].split("/")[0]
        by_dir[top][d["level"]] += 1

    return {
        "by_level": dict(by_level),
        "by_dir": {k: dict(v) for k, v in by_dir.items()},
        "by_rule": dict(by_rule),
        "site_terms": dict(site_terms),
    }


def verdict_of(counts: dict) -> str:
    if counts.get("BLOCK"):
        return f"含排除项（{counts['BLOCK']}）"
    if counts.get("MASK"):
        return f"需脱敏交付（{counts['MASK']}）"
    if counts.get("ALLOW"):
        return "直接交付"
    if counts.get("SKIP"):
        return "排除（非源码）"
    return "-"


# ============================================================================
# 报告输出
# ============================================================================

def print_console(result: dict, summary: dict, max_detail: int) -> None:
    files = result["files"]
    lv = summary["by_level"]
    sep = "=" * 78

    print(sep)
    print("DFEcrab 送审范围判定报告（只读）")
    print(f"仓库根    : {result['root']}")
    print(f"生成时间  : {result['generated_at']}")
    print(f"文件总数  : {len(files)}（其中内容扫描 {result['scanned_text_files']}）")
    print(sep)

    print("\n【总体结论】")
    for key in ("ALLOW", "MASK", "BLOCK", "SKIP"):
        print(f"  {LEVEL_LABEL[key]:<8}({key:<5}) : {lv.get(key, 0)}")

    terms = summary.get("site_terms") or {}
    print("\n【现场特征】（确认扫描的是目标现场的仓库）")
    if terms:
        ranked = sorted(terms.items(), key=lambda kv: -kv[1])
        print("  命中现场 / 甲方名称: " + "、".join(f"{t}（{n} 个文件）" for t, n in ranked))
    else:
        print("  未命中任何现场名称（site_terms 为空或本仓库无现场标识）")
    print(f"  整目录排除(甲方数据): {len([d for d in result['dir_hits'] if d['level'] == 'BLOCK'])} 个")
    print(f"  整目录排除(非源码)  : {len([d for d in result['dir_hits'] if d['level'] == 'SKIP'])} 个")

    print("\n【按顶层目录汇总】")
    print(f"  {'目录':<32}{'判定':<22}{'排除(数据)':>10}{'脱敏后交':>9}{'直接交':>8}{'排除(非源码)':>12}")
    for name in sorted(summary["by_dir"], key=lambda n: (-summary["by_dir"][n].get("BLOCK", 0), n)):
        c = summary["by_dir"][name]
        print(
            f"  {name[:30]:<32}{verdict_of(c):<22}"
            f"{c.get('BLOCK', 0):>10}{c.get('MASK', 0):>9}{c.get('ALLOW', 0):>8}{c.get('SKIP', 0):>12}"
        )

    print("\n【规则命中统计】")
    for rid in sorted(summary["by_rule"]):
        agg = summary["by_rule"][rid]
        print(f"  [{agg['level']:<5}] {rid:<26} {agg['files']:>4} 个文件   {agg['reason']}")

    blocked = [f for f in files if f["level"] == "BLOCK"]
    print(f"\n【排除明细·甲方数据本体】（共 {len(blocked)}，最多显示 {max_detail}）")
    for f in blocked[:max_detail]:
        print(f"  - {f['path']}")
        for r in f["reasons"][:3]:
            print(f"      · {r}")
        for h in f["hits"]:
            loc = ", ".join(f"L{s['line']}" for s in h["samples"][:3])
            print(f"      · {h['id']} 命中 {h['count']} 处（{loc}）")
    if len(blocked) > max_detail:
        print(f"  ... 其余 {len(blocked) - max_detail} 个见报告文件")

    dir_hits = [d for d in result["dir_hits"] if d["level"] == "BLOCK"]
    if dir_hits:
        print(f"\n【整目录排除·甲方数据本体】（共 {len(dir_hits)}）")
        for d in dir_hits[:max_detail]:
            print(f"  - {d['path']}/   {d['reasons'][0] if d['reasons'] else ''}")

    print("\n" + sep)
    print("结论：交付 = 【直接交付】+【脱敏后交付】(必须先脱敏)。【排除】一律不带出。")
    print("      注意：业务代码属【脱敏后交付】，不得因'怕复刻'而排除——")
    print("      审计要求 100% 代码覆盖，排除业务实现等于让审计报告作废。")
    print("警告：本报告列出了敏感信息的位置索引，本身不可送审；请只回传结论，或自行裁剪。")
    print(sep)


def build_markdown(result: dict, summary: dict) -> str:
    lv = summary["by_level"]
    lines = [
        "# DFEcrab 送审范围判定报告",
        "",
        f"- 仓库根：`{result['root']}`",
        f"- 生成时间：{result['generated_at']}",
        f"- 文件总数：{len(result['files'])}（内容扫描 {result['scanned_text_files']}）",
        "",
        "## 一、总体结论",
        "",
        "| 级别 | 含义 | 文件数 |",
        "|---|---|---|",
    ]
    for key in ("ALLOW", "MASK", "BLOCK", "SKIP"):
        meaning = {
            "ALLOW": "直接交付（平台通用能力）",
            "MASK": "脱敏后交付（含敏感值，替换后必须交）",
            "BLOCK": "排除（甲方数据本体，无法脱敏）",
            "SKIP": "排除（生成物/部署环境/与审核无关）",
        }[key]
        lines.append(f"| `{key}` | {meaning} | {lv.get(key, 0)} |")

    terms = summary.get("site_terms") or {}
    lines += ["", "### 现场特征（确认扫描的是目标现场的仓库）", ""]
    if terms:
        ranked = sorted(terms.items(), key=lambda kv: -kv[1])
        lines.append("命中现场 / 甲方名称：")
        lines.append("")
        for t, n in ranked:
            lines.append(f"- `{t}` — {n} 个文件")
    else:
        lines.append("未命中任何现场名称（`site_terms` 为空，或本仓库无现场标识）。")
    lines += [
        "",
        f"- 整目录排除（甲方数据）：{len([d for d in result['dir_hits'] if d['level'] == 'BLOCK'])} 个",
        f"- 整目录排除（非源码）：{len([d for d in result['dir_hits'] if d['level'] == 'SKIP'])} 个",
    ]

    lines += ["", "## 二、按顶层目录汇总", "",
              "| 目录 | 判定 | 排除(数据) | 脱敏后交 | 直接交 | 排除(非源码) |",
              "|---|---|---:|---:|---:|---:|"]
    for name in sorted(summary["by_dir"], key=lambda n: (-summary["by_dir"][n].get("BLOCK", 0), n)):
        c = summary["by_dir"][name]
        lines.append(
            f"| `{name}` | {verdict_of(c)} | {c.get('BLOCK', 0)} | "
            f"{c.get('MASK', 0)} | {c.get('ALLOW', 0)} | {c.get('SKIP', 0)} |"
        )

    lines += ["", "## 三、规则命中统计", "", "| 级别 | 规则 | 文件数 | 说明 |", "|---|---|---:|---|"]
    for rid in sorted(summary["by_rule"]):
        agg = summary["by_rule"][rid]
        lines.append(f"| `{agg['level']}` | `{rid}` | {agg['files']} | {agg['reason']} |")

    lines += ["", "## 四、排除明细（甲方数据本体）", ""]
    blocked = [f for f in result["files"] if f["level"] == "BLOCK"]
    if not blocked:
        lines.append("（无）")
    for f in blocked:
        lines.append(f"- `{f['path']}`")
        for r in f["reasons"][:5]:
            lines.append(f"  - {r}")
        for h in f["hits"]:
            loc = ", ".join(f"L{s['line']}" for s in h["samples"])
            lines.append(f"  - 命中 `{h['id']}` {h['count']} 处：{loc}")

    dir_hits = [d for d in result["dir_hits"] if d["level"] == "BLOCK"]
    if dir_hits:
        lines += ["", "## 五、整目录排除（甲方数据本体）", ""]
        for d in dir_hits:
            lines.append(f"- `{d['path']}/` — {d['reasons'][0] if d['reasons'] else ''}")

    lines += ["", "## 六、脱敏后交付明细", ""]
    masked = [f for f in result["files"] if f["level"] == "MASK"]
    if not masked:
        lines.append("（无）")
    for f in masked:
        lines.append(f"- `{f['path']}`")
        for r in f["reasons"][:3]:
            lines.append(f"  - {r}")

    allow = [f["path"] for f in result["files"] if f["level"] == "ALLOW"]
    lines += ["", f"## 七、直接交付白名单（{len(allow)} 个，可直接用于打包）", "", "```"]
    lines.extend(allow)
    lines.append("```")

    lines += [
        "",
        "---",
        "",
        "> 本报告由 `scripts/review_scope_audit.py` 只读扫描生成，未修改任何文件。",
        "> `MASK` 级别的条目仍需人工确认；内容命中为候选清单，占位符文本可能被误判。",
        "> ⚠️ 本报告列出了敏感信息的位置索引，**本身不可外发**；请只回传结论或自行裁剪。",
        "",
    ]
    return "\n".join(lines)


# ============================================================================
# 入口
# ============================================================================

LEVEL_MEANING = {
    "ALLOW": "直接交付（平台通用能力，无敏感信息）",
    "MASK": "脱敏后交付（含凭据/内网地址/现场名/甲方表名，替换占位符后必须交）",
    "BLOCK": "排除（甲方数据与资产本体，无法脱敏）",
    "SKIP": "排除（生成物 / 部署环境 / 与审核无关）",
}


def _clean_reasons(reasons: list[str]) -> list[str]:
    """去掉级别后缀并去重，供文档展示（同一原因不重复列）。"""
    out: list[str] = []
    for r in reasons:
        text = re.sub(r"\s*\[(?:BLOCK|MASK|SKIP|ALLOW)\]\s*$", "", r).strip()
        if text and text not in out:
            out.append(text)
    return out


def _group_by_top(paths: list[str]) -> dict[str, list[str]]:
    """按顶层目录分组，便于文档分节阅读。"""
    grouped: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        top = p.split("/")[0] if "/" in p else "(根目录)"
        grouped[top].append(p)
    return grouped


def build_handover_doc(result: dict, summary: dict) -> str:
    """生成《送审范围说明》—— 目录级判定 + 逐文件清单。"""
    files = result["files"]
    lv = summary["by_level"]
    by_dir = summary["by_dir"]

    def pick(level: str) -> list[dict]:
        return [f for f in files if f["level"] == level]

    blocked, masked, allowed, skipped = pick("BLOCK"), pick("MASK"), pick("ALLOW"), pick("SKIP")
    blocked_dirs = [d for d in result["dir_hits"] if d["level"] == "BLOCK"]
    skipped_dirs = [d for d in result["dir_hits"] if d["level"] == "SKIP"]

    lines: list[str] = [
        "# DFEcrab 第三方代码审核 · 送审范围说明",
        "",
        f"- 仓库根：`{result['root']}`",
        f"- 扫描时间：{result['generated_at']}",
        f"- 扫描工具：`scripts/review_scope_audit.py`（只读，未修改任何文件）",
        f"- 文件总数：{len(files)}（内容扫描 {result['scanned_text_files']}）",
        "",
        "> ⚠️ 本文档列出了敏感信息的位置索引，**属内部资料，不可随代码送审**。",
        "",
        "---",
        "",
        "## 一、交付结论",
        "",
        "| 级别 | 含义 | 文件数 |",
        "|---|---|---:|",
    ]
    for key in ("ALLOW", "MASK", "BLOCK", "SKIP"):
        lines.append(f"| `{key}` | {LEVEL_MEANING[key]} | {lv.get(key, 0)} |")
    lines += [
        "",
        f"- 整目录排除（甲方数据）：**{len(blocked_dirs)} 个**",
        f"- 整目录排除（非源码）：**{len(skipped_dirs)} 个**",
        "",
        "**交付公式：**",
        "",
        "```",
        "交付 = 直接交付(ALLOW) + 脱敏后交付(MASK，必须先脱敏)",
        "排除 = 排除·甲方数据(BLOCK) + 排除·非源码(SKIP)",
        "```",
        "",
        "**为什么业务代码必须交**：静态代码审计要求 100% 代码覆盖，而扫描工具最大的盲区",
        "正是「业务逻辑缺陷」。把业务实现排除在外，会让审计报告失去效力，同时把真实的",
        "SQL 注入 / 越权 / 参数校验缺失继续留在系统里。防复刻应靠 NDA、审核范围书面约定、",
        "只读环境与水印，而不是删代码。",
        "",
        "---",
        "",
        "## 二、目录级判定",
        "",
        "| 目录 | 判定 | 直接交 | 脱敏后交 | 排除(数据) | 排除(非源码) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for name in sorted(by_dir, key=lambda n: (-by_dir[n].get("BLOCK", 0), -by_dir[n].get("ALLOW", 0), n)):
        c = by_dir[name]
        lines.append(
            f"| `{name}` | {verdict_of(c)} | {c.get('ALLOW', 0)} | "
            f"{c.get('MASK', 0)} | {c.get('BLOCK', 0)} | {c.get('SKIP', 0)} |"
        )

    lines += [
        "",
        "---",
        "",
        f"## 三、直接交付（{len(allowed)} 个，原样进包）",
        "",
        "以下文件不含任何敏感值，可**原样**纳入送审包。",
        "",
    ]
    if not allowed:
        lines.append("（无）")
    for top, paths in sorted(_group_by_top([f["path"] for f in allowed]).items()):
        lines += [f"### `{top}/`（{len(paths)} 个）", "", "```"]
        lines.extend(paths)
        lines += ["```", ""]

    lines += [
        "---",
        "",
        f"## 四、排除·甲方数据本体（{len(blocked)} 个文件 + {len(blocked_dirs)} 个整目录）",
        "",
        "内容是数据本身（语料、拓扑、schema、运行时记录），**脱敏无意义，一律不带出**。",
        "",
        "### 4.1 整目录（整个目录树都不带出）",
        "",
    ]
    if not blocked_dirs:
        lines.append("（无）")
    for d in blocked_dirs:
        why = _clean_reasons(d["reasons"])
        lines.append(f"- `{d['path']}/` — {why[0] if why else ''}")
    lines += ["", "### 4.2 单文件", ""]
    if not blocked:
        lines.append("（无）")
    for f in blocked:
        lines.append(f"- `{f['path']}`")
        for r in _clean_reasons(f["reasons"]):
            lines.append(f"  - 原因：{r}")
        for h in f["hits"]:
            loc = ", ".join(f"L{s['line']}" for s in h["samples"][:5])
            lines.append(f"  - 命中 `{h['id']}` {h['count']} 处：{loc}")

    lines += [
        "",
        "---",
        "",
        f"## 五、脱敏后交付（{len(masked)} 个，必须先脱敏）",
        "",
        "含凭据 / 内网地址 / 现场名 / 甲方表名，**替换为占位符后必须交付**——",
        "这批是业务实现的主体，排除它们会导致审计覆盖率不足、报告失效。",
        "",
        "```",
        "内网地址      →  <INTERNAL_IP>",
        "密码/密钥/令牌 →  <CREDENTIAL>",
        "现场/甲方名称   →  <SITE>",
        "甲方库表名      →  <TABLE> / <SCHEMA>",
        "```",
        "",
        "> 脱敏由 `scripts/build_review_package.py` 按 `scripts/review_sanitize_rules.json`",
        "> 自动执行，并在打包后复扫验证：仍有泄露命中则拒绝出包。",
        "",
    ]
    if not masked:
        lines.append("（无）")
    for top, paths in sorted(_group_by_top([f["path"] for f in masked]).items()):
        lines += [f"### `{top}/`（{len(paths)} 个）", ""]
        for p in paths:
            entry = next(f for f in masked if f["path"] == p)
            why = _clean_reasons(entry["reasons"])
            lines.append(f"- `{p}` — {'；'.join(why[:2])}")
        lines.append("")

    lines += [
        "---",
        "",
        f"## 六、排除·非源码（{len(skipped)} 个文件 + {len(skipped_dirs)} 个整目录）",
        "",
        "生成物、部署环境、与审核无关的冗余，不是源码或不应进包。",
        "",
        "### 6.1 整目录",
        "",
    ]
    if not skipped_dirs:
        lines.append("（无）")
    for d in skipped_dirs:
        why = _clean_reasons(d["reasons"])
        lines.append(f"- `{d['path']}/` — {why[0] if why else ''}")
    lines += ["", "### 6.2 单文件（按原因归类）", ""]
    by_reason: dict[str, list[str]] = defaultdict(list)
    for f in skipped:
        why = _clean_reasons(f["reasons"])
        by_reason[why[0] if why else "未分类"].append(f["path"])
    for reason, paths in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"- **{reason}**（{len(paths)} 个）")
        lines.append(f"  - `{'`、`'.join(paths[:8])}`" + ("……" if len(paths) > 8 else ""))

    lines += [
        "",
        "---",
        "",
        "## 七、打包与送审操作建议",
        "",
        "1. 直接用打包脚本生成送审包（自动完成脱敏 + 复扫验证 + 清单 + 压缩）：",
        "   ```",
        "   python3 scripts/build_review_package.py --report <out-dir>/review_scope_report.json",
        "   ```",
        "2. 打包脚本会把「直接交付」原样复制、「脱敏后交付」脱敏后复制、「排除」全部跳过；",
        "   打包完成后自动复扫，**只要还有一条泄露规则命中就拒绝出包**。",
        "3. 出包后人工抽查（压缩包内不得出现任何真实 IP / 口令 / 甲方表名 / 现场名）。",
        "4. 送审前补齐审计方要求的其余材料（见第五节之外的文档、测试、合规项）。",
        "",
        "> 本文档由 `scripts/review_scope_audit.py --handover` 自动生成，未修改任何文件。",
        "",
    ]
    return "\n".join(lines)


def write_handover(result: dict, summary: dict, out_dir: Path) -> list[Path]:
    """写出送审范围说明 + 4 份纯文本清单（打包脚本与人工核对共用）。"""
    written: list[Path] = []

    doc = out_dir / "送审范围说明.md"
    doc.write_text(build_handover_doc(result, summary), encoding="utf-8")
    written.append(doc)

    lists = [
        ("01_直接交付清单.txt", "ALLOW"),
        ("02_脱敏后交付清单.txt", "MASK"),
        ("03_排除_甲方数据.txt", "BLOCK"),
        ("04_排除_非源码.txt", "SKIP"),
    ]
    for filename, level in lists:
        path = out_dir / filename
        entries = [f for f in result["files"] if f["level"] == level]
        dirs = [d for d in result["dir_hits"] if d["level"] == level]
        rows = [
            f"# {filename[:-4]}  文件 {len(entries)} 个 / 整目录 {len(dirs)} 个"
            f"（生成于 {result['generated_at']}）",
            "# 格式: 路径<TAB>原因",
        ]
        for d in sorted(dirs, key=lambda x: x["path"]):
            rows.append(f"{d['path']}/\t[整目录] {'；'.join(_clean_reasons(d['reasons']))}")
        for e in sorted(entries, key=lambda x: x["path"]):
            rows.append(f"{e['path']}\t{'；'.join(_clean_reasons(e['reasons']))}")
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        written.append(path)

    return written


def print_diff(mine: dict, other: dict, max_items: int) -> None:
    """对比两份报告，列出文件级差异——用于核对多现场之间是否同一版本。

    典型用法：本地跑一份、现场跑一份，两边 diff 为空即代表代码一致。
    """
    mf = {f["path"]: f["level"] for f in mine["files"]}
    of = {f["path"]: f["level"] for f in other["files"]}
    md = {d["path"]: d["level"] for d in (mine.get("dir_hits") or [])}
    od = {d["path"]: d["level"] for d in (other.get("dir_hits") or [])}

    only_mine = sorted(set(mf) - set(of))
    only_other = sorted(set(of) - set(mf))
    level_diff = sorted(
        p for p in (set(mf) & set(of)) if mf[p] != of[p]
    )
    dir_only_mine = sorted(set(md) - set(od))
    dir_only_other = sorted(set(od) - set(md))

    sep = "=" * 78
    print("\n" + sep)
    print("报告对比（核对是否同一版本）")
    print(f"  A = {mine['root']}　（{len(mf)} 文件 / {len(md)} 目录）")
    print(f"  B = {other['root']}　（{len(of)} 文件 / {len(od)} 目录）")
    print(sep)

    def dump(title: str, items: list[str], mark) -> None:
        print(f"\n【{title}】（{len(items)}）")
        if not items:
            print("  （无）")
            return
        for p in items[:max_items]:
            print(f"  {mark} {p}")
        if len(items) > max_items:
            print(f"  ... 其余 {len(items) - max_items} 项")

    dump("只在 A 有", only_mine, "-")
    dump("只在 B 有", only_other, "+")
    dump("A 独有的目录", dir_only_mine, "-")
    dump("B 独有的目录", dir_only_other, "+")

    print(f"\n【判定级别不同】（{len(level_diff)}）")
    if not level_diff:
        print("  （无）")
    for p in level_diff[:max_items]:
        print(f"  ~ {p}: A={mf[p]}  B={of[p]}")

    print("\n" + sep)
    if not (only_mine or only_other or level_diff or dir_only_mine or dir_only_other):
        print("结论：两份报告完全一致 —— 两边是同一份代码。")
    else:
        print("结论：两边代码不一致。在定送审基线前，必须先把差异处理干净——")
        print("      否则审计报告会对应到一个既不是 A 也不是 B 的混合版本。")
    print(sep)


def _ensure_utf8_stdout() -> None:
    """让中文报告在 GBK 终端（Windows 默认）不乱码。

    只影响输出编码，不改变任何判定结果。切换失败时明确告警，
    而不是静默吞掉——否则现场会看到乱码却查不到原因。
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError) as e:
        print(
            f"[WARN] 无法将输出编码切换为 UTF-8（{e}）；中文可能乱码，"
            f"可先执行 set PYTHONIOENCODING=utf-8",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(
        description="判定仓库中各文件的送审处置方式（直接交付/脱敏后交付/排除），只读，不做任何修改",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", default=None, help="仓库根目录（默认脚本上一级）")
    parser.add_argument("--out-dir", default="review_scope_out", help="报告输出目录")
    parser.add_argument("--rules", default=None, help="自定义规则 JSON（整份替换内置默认）")
    parser.add_argument("--dump-rules", default=None, help="导出内置默认规则到指定路径后退出")
    parser.add_argument("--json-only", action="store_true", help="只输出 JSON，不写 Markdown")
    parser.add_argument("--max-detail", type=int, default=40, help="控制台明细显示上限")
    parser.add_argument(
        "--handover", action="store_true",
        help="额外生成《送审范围说明.md》与 4 份纯文本清单（直接交付/脱敏后交付/排除甲方数据/排除非源码）",
    )
    parser.add_argument(
        "--diff", default=None, metavar="OTHER_REPORT.json",
        help="与另一份报告对比（如：本地跑一份、现场跑一份），核对是否为同一版本",
    )
    args = parser.parse_args(argv)

    if args.dump_rules:
        out = Path(args.dump_rules)
        out.write_text(
            json.dumps(DEFAULT_RULES, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[OK] 默认规则已导出: {out}")
        return 0

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    if not root.is_dir():
        print(f"[FATAL] 仓库根不存在: {root}", file=sys.stderr)
        return 2

    rules = load_rules(args.rules)

    # 把本脚本自身的输出目录排除在扫描范围外，避免"报告把自己扫进去"的自引用
    out_dir = Path(args.out_dir)
    exclude_rels: set[str] = set()
    try:
        exclude_rels.add(out_dir.resolve().relative_to(root).as_posix())
    except ValueError:
        pass  # 输出目录在仓库之外，无需排除

    result = audit(root, rules, exclude_rels=exclude_rels)
    summary = summarize(result)

    print_console(result, summary, args.max_detail)

    if args.diff:
        other_path = Path(args.diff)
        if not other_path.is_file():
            raise SystemExit(f"[FATAL] --diff 指定的报告不存在: {other_path}")
        with open(other_path, encoding="utf-8") as f:
            other = json.load(f)
        if "files" not in other or "root" not in other:
            raise SystemExit(f"[FATAL] --diff 报告结构不合法（缺 files/root）: {other_path}")
        print_diff(result, other, args.max_detail)

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, **result}

    json_path = out_dir / "review_scope_report.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] JSON 报告: {json_path}")

    if not args.json_only:
        md_path = out_dir / "review_scope_report.md"
        md_path.write_text(build_markdown(result, summary), encoding="utf-8")
        print(f"[OK] Markdown 报告: {md_path}")

    if args.handover:
        for path in write_handover(result, summary, out_dir):
            print(f"[OK] 交付清单: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
