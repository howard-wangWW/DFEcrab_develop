# 工具系统设计文档

## 1. 概述

工具系统是 DFEcrab 的核心执行层，为 AI Agent 提供与文件系统、Shell 环境交互的能力。通过统一的工具接口设计和权限集成，确保所有操作安全可控。

### 1.1 设计目标

- **统一接口**：所有工具遵循相同的调用和执行协议
- **权限集成**：工具执行自动进行权限检查和过滤
- **流式执行**：支持长时间运行任务的实时输出流
- **可观测性**：完整的工具调用日志和性能指标
- **可扩展性**：支持自定义工具插件

### 1.2 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                         LLM (Agent Core)                         │
│                    生成工具调用 (Tool Call)                       │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Tool Router (工具路由器)                       │
│  • 解析工具调用请求                                               │
│  • 路由到对应工具处理器                                           │
│  • 权限预检查                                                     │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  File Tools  │  │  Search Tools│  │  Bash Tool   │
│              │  │              │  │              │
│ • list_dir   │  │ • glob_search│  │ • bash       │
│ • read_file  │  │ • grep_search│  │   (streaming)│
│ • write_file │  │              │  │              │
│ • edit_file  │  │              │  │              │
└──────────────┘  └──────────────┘  └──────────────┘
              │              │              │
              └──────────────┼──────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Tool Executor (执行器)                          │
│  • 参数验证                                                       │
│  • 路径安全验证                                                   │
│  • 权限检查                                                       │
│  • 执行并收集结果                                                 │
│  • 流式输出（如适用）                                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 统一工具接口设计

### 2.1 AgentTool 接口定义

```typescript
/**
 * 统一工具接口
 * 所有工具必须实现此接口
 */
export interface AgentTool {
  /** 工具唯一名称 */
  readonly name: string;
  
  /** 工具描述（用于 LLM 理解） */
  readonly description: string;
  
  /** 工具参数 JSON Schema */
  readonly parameters: JSONSchema7;
  
  /** 工具所需的最低权限级别 */
  readonly requiredPermission: PermissionLevel;
  
  /**
   * 执行工具
   * @param args 工具参数
   * @param context 执行上下文
   * @returns 工具执行结果或异步结果流
   */
  execute(
    args: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<ToolResult | AsyncIterable<ToolChunk>>;
  
  /**
   * 验证参数
   * @param args 待验证参数
   * @returns 验证结果
   */
  validateArgs?(args: Record<string, unknown>): ValidationResult;
}

/**
 * 工具执行上下文
 */
export interface ToolExecutionContext {
  /** 当前工作目录 */
  cwd: string;
  
  /** 权限检查器 */
  permissionChecker: PermissionChecker;
  
  /** 路径验证器 */
  pathValidator: PathValidator;
  
  /** 取消信号 */
  abortSignal?: AbortSignal;
  
  /** 自定义元数据 */
  metadata?: Record<string, unknown>;
}

/**
 * 工具执行结果
 */
export interface ToolResult {
  /** 是否成功 */
  success: boolean;
  
  /** 输出内容 */
  output: string;
  
  /** 错误信息（如果失败） */
  error?: string;
  
  /** 执行耗时（毫秒） */
  duration: number;
  
  /** 额外元数据 */
  metadata?: Record<string, unknown>;
}

/**
 * 流式工具输出块
 */
export interface ToolChunk {
  /** 块类型 */
  type: 'stdout' | 'stderr' | 'exit';
  
  /** 块内容 */
  content: string;
  
  /** 退出码（仅 type 为 exit 时） */
  exitCode?: number;
  
  /** 时间戳 */
  timestamp: number;
}

/**
 * 参数验证结果
 */
export interface ValidationResult {
  valid: boolean;
  errors?: string[];
}
```

### 2.2 工具基类

```typescript
/**
 * 工具抽象基类
 * 提供通用功能实现
 */
export abstract class BaseTool implements AgentTool {
  abstract readonly name: string;
  abstract readonly description: string;
  abstract readonly parameters: JSONSchema7;
  abstract readonly requiredPermission: PermissionLevel;
  
  /**
   * 执行前验证
   */
  protected async preExecute(
    args: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<void> {
    // 1. 参数验证
    const validation = this.validateArgs(args);
    if (!validation.valid) {
      throw new ToolError(
        `参数验证失败: ${validation.errors?.join(', ')}`
      );
    }
    
    // 2. 权限检查
    const permResult = context.permissionChecker.checkPermission(
      this.name, 
      args
    );
    if (!permResult.allowed) {
      throw new ToolError(`权限拒绝: ${permResult.reason}`);
    }
  }
  
  /**
   * 默认参数验证实现
   */
  validateArgs(args: Record<string, unknown>): ValidationResult {
    // 子类可覆盖此方法
    return { valid: true };
  }
  
  abstract execute(
    args: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<ToolResult | AsyncIterable<ToolChunk>>;
}

/**
 * 工具错误类
 */
export class ToolError extends Error {
  constructor(
    message: string,
    public readonly toolName?: string,
    public readonly recoverable: boolean = true
  ) {
    super(message);
    this.name = 'ToolError';
  }
}
```

---

## 3. 核心工具详细说明

### 3.1 工具概览

| 工具名称 | 类型 | 权限要求 | 描述 |
|---------|------|---------|------|
| `list_dir` | 文件 | READ_ONLY | 列出目录内容 |
| `read_file` | 文件 | READ_ONLY | 读取文件内容 |
| `write_file` | 文件 | WRITE | 写入文件内容 |
| `edit_file` | 文件 | WRITE | 编辑文件（精确替换） |
| `glob_search` | 搜索 | READ_ONLY | Glob 模式文件搜索 |
| `grep_search` | 搜索 | READ_ONLY | 正则内容搜索 |
| `bash` | 命令 | SHELL | 执行 Shell 命令 |

### 3.2 list_dir - 目录列表工具

```typescript
/**
 * 目录列表工具
 * 列出指定目录下的文件和子目录
 */
export class ListDirTool extends BaseTool {
  readonly name = 'list_dir';
  readonly description = '列出指定目录的内容，包括文件和子目录信息';
  readonly requiredPermission = PermissionLevel.READ_ONLY;
  
  readonly parameters: JSONSchema7 = {
    type: 'object',
    properties: {
      path: {
        type: 'string',
        description: '要列出的目录路径（绝对路径或相对于 cwd 的路径）'
      },
      recursive: {
        type: 'boolean',
        description: '是否递归列出子目录内容',
        default: false
      },
      maxDepth: {
        type: 'number',
        description: '递归最大深度',
        default: 1,
        minimum: 1,
        maximum: 5
      },
      includeHidden: {
        type: 'boolean',
        description: '是否包含隐藏文件（以 . 开头的文件）',
        default: false
      }
    },
    required: ['path']
  };
  
  async execute(
    args: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<ToolResult> {
    const startTime = Date.now();
    const { path, recursive = false, maxDepth = 1, includeHidden = false } = args;
    
    // 路径验证
    const pathValidation = context.pathValidator.validatePath(path as string);
    if (!pathValidation.valid) {
      return {
        success: false,
        output: '',
        error: `路径验证失败: ${pathValidation.reason}`,
        duration: Date.now() - startTime
      };
    }
    
    try {
      const entries = await this.listDirectory(
        pathValidation.resolvedPath!,
        { recursive, maxDepth, includeHidden }
      );
      
      return {
        success: true,
        output: this.formatOutput(entries),
        duration: Date.now() - startTime,
        metadata: { entryCount: entries.length }
      };
    } catch (error) {
      return {
        success: false,
        output: '',
        error: error instanceof Error ? error.message : String(error),
        duration: Date.now() - startTime
      };
    }
  }
  
  private async listDirectory(
    dirPath: string,
    options: { recursive: boolean; maxDepth: number; includeHidden: boolean }
  ): Promise<DirEntry[]> {
    const entries: DirEntry[] = [];
    
    async function scan(dir: string, depth: number): Promise<void> {
      if (depth > options.maxDepth) return;
      
      const items = await fs.readdir(dir, { withFileTypes: true });
      
      for (const item of items) {
        if (!options.includeHidden && item.name.startsWith('.')) continue;
        
        const fullPath = path.join(dir, item.name);
        const entry: DirEntry = {
          name: item.name,
          path: fullPath,
          type: item.isDirectory() ? 'directory' : 'file',
          size: item.isFile() ? (await fs.stat(fullPath)).size : 0
        };
        
        entries.push(entry);
        
        if (options.recursive && item.isDirectory()) {
          await scan(fullPath, depth + 1);
        }
      }
    }
    
    await scan(dirPath, 1);
    return entries;
  }
  
  private formatOutput(entries: DirEntry[]): string {
    const lines = entries.map(entry => {
      const type = entry.type === 'directory' ? '📁' : '📄';
      const size = entry.type === 'file' 
        ? ` (${this.formatSize(entry.size)})` 
        : '';
      return `${type} ${entry.name}${size}`;
    });
    
    return lines.join('\n');
  }
  
  private formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
}

interface DirEntry {
  name: string;
  path: string;
  type: 'file' | 'directory';
  size: number;
}
```

### 3.3 read_file - 文件读取工具

```typescript
/**
 * 文件读取工具
 * 读取文件内容，支持文本文件和二进制文件
 */
export class ReadFileTool extends BaseTool {
  readonly name = 'read_file';
  readonly description = '读取文件内容。支持指定行范围读取。';
  readonly requiredPermission = PermissionLevel.READ_ONLY;
  
  readonly parameters: JSONSchema7 = {
    type: 'object',
    properties: {
      path: {
        type: 'string',
        description: '要读取的文件路径'
      },
      offset: {
        type: 'number',
        description: '起始行号（0-based），用于大文件分页读取',
        default: 0,
        minimum: 0
      },
      limit: {
        type: 'number',
        description: '最大读取行数',
        default: 2000,
        minimum: 1,
        maximum: 10000
      }
    },
    required: ['path']
  };
  
  async execute(
    args: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<ToolResult> {
    const startTime = Date.now();
    const { path, offset = 0, limit = 2000 } = args;
    
    // 路径验证
    const pathValidation = context.pathValidator.validatePath(path as string);
    if (!pathValidation.valid) {
      return {
        success: false,
        output: '',
        error: `路径验证失败: ${pathValidation.reason}`,
        duration: Date.now() - startTime
      };
    }
    
    try {
      const content = await this.readFile(
        pathValidation.resolvedPath!,
        { offset: offset as number, limit: limit as number }
      );
      
      return {
        success: true,
        output: content.text,
        duration: Date.now() - startTime,
        metadata: {
          totalLines: content.totalLines,
          encoding: content.encoding,
          truncated: content.truncated
        }
      };
    } catch (error) {
      return {
        success: false,
        output: '',
        error: error instanceof Error ? error.message : String(error),
        duration: Date.now() - startTime
      };
    }
  }
  
  private async readFile(
    filePath: string,
    options: { offset: number; limit: number }
  ): Promise<FileContent> {
    // 检查文件大小
    const stat = await fs.stat(filePath);
    
    // 对于大文件，使用流式读取
    if (stat.size > 10 * 1024 * 1024) { // 10MB
      return this.readLargeFile(filePath, options);
    }
    
    // 小文件直接读取
    const buffer = await fs.readFile(filePath);
    const encoding = this.detectEncoding(buffer);
    const text = buffer.toString(encoding as BufferEncoding);
    const lines = text.split('\n');
    
    const slicedLines = lines.slice(options.offset, options.offset + options.limit);
    
    return {
      text: slicedLines.join('\n'),
      totalLines: lines.length,
      encoding,
      truncated: lines.length > options.offset + options.limit
    };
  }
  
  private async readLargeFile(
    filePath: string,
    options: { offset: number; limit: number }
  ): Promise<FileContent> {
    const lines: string[] = [];
    let currentLine = 0;
    let totalLines = 0;
    
    const stream = fs.createReadStream(filePath, { encoding: 'utf-8' });
    const rl = readline.createInterface({ input: stream });
    
    for await (const line of rl) {
      totalLines++;
      
      if (currentLine >= options.offset && lines.length < options.limit) {
        lines.push(line);
        currentLine++;
      } else if (currentLine >= options.offset) {
        break;
      } else {
        currentLine++;
      }
    }
    
    return {
      text: lines.join('\n'),
      totalLines,
      encoding: 'utf-8',
      truncated: totalLines > options.offset + options.limit
    };
  }
  
  private detectEncoding(buffer: Buffer): string {
    // 简单的 UTF-8 检测
    try {
      buffer.toString('utf-8');
      return 'utf-8';
    } catch {
      return 'binary';
    }
  }
}

interface FileContent {
  text: string;
  totalLines: number;
  encoding: string;
  truncated: boolean;
}
```

### 3.4 write_file - 文件写入工具

```typescript
/**
 * 文件写入工具
 * 创建新文件或覆盖现有文件
 */
export class WriteFileTool extends BaseTool {
  readonly name = 'write_file';
  readonly description = '写入内容到文件。如果文件不存在则创建，存在则覆盖。';
  readonly requiredPermission = PermissionLevel.WRITE;
  
  readonly parameters: JSONSchema7 = {
    type: 'object',
    properties: {
      path: {
        type: 'string',
        description: '目标文件路径'
      },
      content: {
        type: 'string',
        description: '要写入的内容'
      },
      createDirectories: {
        type: 'boolean',
        description: '是否自动创建不存在的父目录',
        default: true
      }
    },
    required: ['path', 'content']
  };
  
  validateArgs(args: Record<string, unknown>): ValidationResult {
    const errors: string[] = [];
    
    if (!args.path || typeof args.path !== 'string') {
      errors.push('path 参数必须是非空字符串');
    }
    
    if (args.content === undefined || args.content === null) {
      errors.push('content 参数不能为空');
    }
    
    // 检查文件大小限制
    if (typeof args.content === 'string' && args.content.length > 100000) {
      errors.push('内容超过最大限制 (100,000 字符)');
    }
    
    return {
      valid: errors.length === 0,
      errors: errors.length > 0 ? errors : undefined
    };
  }
  
  async execute(
    args: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<ToolResult> {
    const startTime = Date.now();
    const { path, content, createDirectories = true } = args;
    
    // 路径验证
    const pathValidation = context.pathValidator.validatePath(path as string);
    if (!pathValidation.valid) {
      return {
        success: false,
        output: '',
        error: `路径验证失败: ${pathValidation.reason}`,
        duration: Date.now() - startTime
      };
    }
    
    try {
      const filePath = pathValidation.resolvedPath!;
      
      // 创建父目录
      if (createDirectories) {
        await fs.mkdir(path.dirname(filePath), { recursive: true });
      }
      
      // 写入文件
      await fs.writeFile(filePath, content as string, 'utf-8');
      
      return {
        success: true,
        output: `成功写入文件: ${filePath}`,
        duration: Date.now() - startTime,
        metadata: {
          bytesWritten: Buffer.byteLength(content as string, 'utf-8'),
          charactersWritten: (content as string).length
        }
      };
    } catch (error) {
      return {
        success: false,
        output: '',
        error: error instanceof Error ? error.message : String(error),
        duration: Date.now() - startTime
      };
    }
  }
}
```

### 3.5 edit_file - 文件编辑工具

```typescript
/**
 * 文件编辑工具
 * 精确替换文件中的特定内容
 */
export class EditFileTool extends BaseTool {
  readonly name = 'edit_file';
  readonly description = '编辑文件内容。通过精确匹配和替换实现安全的文件编辑。';
  readonly requiredPermission = PermissionLevel.WRITE;
  
  readonly parameters: JSONSchema7 = {
    type: 'object',
    properties: {
      path: {
        type: 'string',
        description: '要编辑的文件路径'
      },
      old_string: {
        type: 'string',
        description: '要替换的原始文本（必须精确匹配，包括空白和缩进）'
      },
      new_string: {
        type: 'string',
        description: '替换后的新文本'
      },
      expected_replacements: {
        type: 'number',
        description: '预期替换次数（用于防止意外多次替换）',
        default: 1,
        minimum: 1
      }
    },
    required: ['path', 'old_string', 'new_string']
  };
  
  validateArgs(args: Record<string, unknown>): ValidationResult {
    const errors: string[] = [];
    
    if (!args.old_string || typeof args.old_string !== 'string') {
      errors.push('old_string 必须是非空字符串');
    }
    
    if (args.old_string === args.new_string) {
      errors.push('old_string 和 new_string 不能相同');
    }
    
    return {
      valid: errors.length === 0,
      errors: errors.length > 0 ? errors : undefined
    };
  }
  
  async execute(
    args: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<ToolResult> {
    const startTime = Date.now();
    const { path, old_string, new_string, expected_replacements = 1 } = args;
    
    // 路径验证
    const pathValidation = context.pathValidator.validatePath(path as string);
    if (!pathValidation.valid) {
      return {
        success: false,
        output: '',
        error: `路径验证失败: ${pathValidation.reason}`,
        duration: Date.now() - startTime
      };
    }
    
    try {
      const filePath = pathValidation.resolvedPath!;
      
      // 读取原文件
      const originalContent = await fs.readFile(filePath, 'utf-8');
      
      // 计算匹配次数
      const matchCount = this.countOccurrences(originalContent, old_string as string);
      
      if (matchCount === 0) {
        return {
          success: false,
          output: '',
          error: `未找到匹配的原始文本。请确保 old_string 精确匹配文件内容。`,
          duration: Date.now() - startTime,
          metadata: { matchCount: 0 }
        };
      }
      
      if (matchCount !== expected_replacements) {
        return {
          success: false,
          output: '',
          error: `找到 ${matchCount} 处匹配，但预期为 ${expected_replacements} 处。` +
                 `请提供更多上下文以确保唯一匹配。`,
          duration: Date.now() - startTime,
          metadata: { matchCount, expectedReplacements: expected_replacements }
        };
      }
      
      // 执行替换
      const newContent = originalContent.replace(
        this.escapeRegex(old_string as string),
        new_string as string
      );
      
      // 写回文件
      await fs.writeFile(filePath, newContent, 'utf-8');
      
      // 计算变更统计
      const changes = this.computeDiff(originalContent, newContent);
      
      return {
        success: true,
        output: `成功编辑文件: ${filePath}\n` +
                `替换了 ${matchCount} 处匹配`,
        duration: Date.now() - startTime,
        metadata: {
          matchCount,
          changes
        }
      };
    } catch (error) {
      return {
        success: false,
        output: '',
        error: error instanceof Error ? error.message : String(error),
        duration: Date.now() - startTime
      };
    }
  }
  
  private countOccurrences(text: string, search: string): number {
    let count = 0;
    let pos = 0;
    while ((pos = text.indexOf(search, pos)) !== -1) {
      count++;
      pos += search.length;
    }
    return count;
  }
  
  private escapeRegex(text: string): RegExp {
    return new RegExp(
      text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
      'g'
    );
  }
  
  private computeDiff(original: string, modified: string): ChangeStats {
    const originalLines = original.split('\n');
    const modifiedLines = modified.split('\n');
    
    let added = 0;
    let removed = 0;
    
    // 简化的差异计算
    const originalSet = new Set(originalLines);
    const modifiedSet = new Set(modifiedLines);
    
    for (const line of modifiedLines) {
      if (!originalSet.has(line)) added++;
    }
    for (const line of originalLines) {
      if (!modifiedSet.has(line)) removed++;
    }
    
    return { added, removed };
  }
}

interface ChangeStats {
  added: number;
  removed: number;
}
```

### 3.6 glob_search - Glob 模式搜索工具

```typescript
/**
 * Glob 模式文件搜索工具
 * 使用 glob 模式匹配查找文件
 */
export class GlobSearchTool extends BaseTool {
  readonly name = 'glob_search';
  readonly description = '使用 glob 模式搜索文件。支持 ** 递归匹配。';
  readonly requiredPermission = PermissionLevel.READ_ONLY;
  
  readonly parameters: JSONSchema7 = {
    type: 'object',
    properties: {
      pattern: {
        type: 'string',
        description: 'Glob 模式（例如: **/*.ts, src/**/*.js）'
      },
      path: {
        type: 'string',
        description: '搜索起始目录（默认为 cwd）'
      },
      caseSensitive: {
        type: 'boolean',
        description: '是否区分大小写',
        default: false
      },
      maxResults: {
        type: 'number',
        description: '最大返回结果数',
        default: 100,
        minimum: 1,
        maximum: 1000
      }
    },
    required: ['pattern']
  };
  
  async execute(
    args: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<ToolResult> {
    const startTime = Date.now();
    const { pattern, path, caseSensitive = false, maxResults = 100 } = args;
    
    const searchPath = path 
      ? context.pathValidator.validatePath(path as string).resolvedPath 
      : context.cwd;
    
    try {
      const results = await glob(pattern as string, {
        cwd: searchPath,
        nocase: !caseSensitive,
        maxResults: maxResults as number
      });
      
      return {
        success: true,
        output: results.join('\n'),
        duration: Date.now() - startTime,
        metadata: { matchCount: results.length }
      };
    } catch (error) {
      return {
        success: false,
        output: '',
        error: error instanceof Error ? error.message : String(error),
        duration: Date.now() - startTime
      };
    }
  }
}
```

### 3.7 grep_search - 正则内容搜索工具

```typescript
/**
 * Grep 正则内容搜索工具
 * 在文件中搜索匹配正则表达式的内容
 */
export class GrepSearchTool extends BaseTool {
  readonly name = 'grep_search';
  readonly description = '使用正则表达式搜索文件内容。返回匹配的行号和内容。';
  readonly requiredPermission = PermissionLevel.READ_ONLY;
  
  readonly parameters: JSONSchema7 = {
    type: 'object',
    properties: {
      pattern: {
        type: 'string',
        description: '正则表达式模式（使用 ripgrep 语法）'
      },
      path: {
        type: 'string',
        description: '搜索路径（文件或目录）'
      },
      glob: {
        type: 'string',
        description: '文件过滤 glob 模式（例如: *.ts）'
      },
      caseSensitive: {
        type: 'boolean',
        description: '是否区分大小写',
        default: false
      },
      maxResults: {
        type: 'number',
        description: '最大匹配结果数',
        default: 100,
        minimum: 1,
        maximum: 500
      },
      contextLines: {
        type: 'number',
        description: '上下文行数（前后各显示几行）',
        default: 0,
        minimum: 0,
        maximum: 5
      }
    },
    required: ['pattern']
  };
  
  async execute(
    args: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<ToolResult> {
    const startTime = Date.now();
    const { 
      pattern, 
      path, 
      glob, 
      caseSensitive = false, 
      maxResults = 100,
      contextLines = 0 
    } = args;
    
    const searchPath = path 
      ? context.pathValidator.validatePath(path as string).resolvedPath 
      : context.cwd;
    
    try {
      // 使用 ripgrep (rg) 进行搜索
      const rgArgs = [
        '--json',
        '--max-count', String(maxResults),
        '--line-number',
        caseSensitive ? '' : '--ignore-case',
        ...(contextLines > 0 ? ['-C', String(contextLines)] : []),
        ...(glob ? ['--glob', glob] : []),
        pattern as string,
        searchPath!
      ].filter(Boolean);
      
      const { stdout } = await execFile('rg', rgArgs);
      
      // 解析 JSON 输出
      const results = this.parseRipgrepOutput(stdout);
      
      return {
        success: true,
        output: this.formatGrepOutput(results),
        duration: Date.now() - startTime,
        metadata: { matchCount: results.length }
      };
    } catch (error) {
      // ripgrep 在没有匹配时返回非零退出码
      if (error instanceof Error && 'code' in error && (error as any).code === 1) {
        return {
          success: true,
          output: '未找到匹配结果',
          duration: Date.now() - startTime,
          metadata: { matchCount: 0 }
        };
      }
      
      return {
        success: false,
        output: '',
        error: error instanceof Error ? error.message : String(error),
        duration: Date.now() - startTime
      };
    }
  }
  
  private parseRipgrepOutput(jsonOutput: string): GrepMatch[] {
    const results: GrepMatch[] = [];
    const lines = jsonOutput.trim().split('\n');
    
    for (const line of lines) {
      try {
        const parsed = JSON.parse(line);
        if (parsed.type === 'match') {
          results.push({
            file: parsed.data.path.text,
            lineNumber: parsed.data.line_number,
            content: parsed.data.lines.text.trim()
          });
        }
      } catch {
        // 忽略解析错误
      }
    }
    
    return results;
  }
  
  private formatGrepOutput(matches: GrepMatch[]): string {
    return matches.map(match => 
      `${match.file}:${match.lineNumber}: ${match.content}`
    ).join('\n');
  }
}

interface GrepMatch {
  file: string;
  lineNumber: number;
  content: string;
}
```

### 3.8 bash - Shell 命令执行工具

```typescript
/**
 * Shell 命令执行工具
 * 支持同步和流式执行
 */
export class BashTool extends BaseTool {
  readonly name = 'bash';
  readonly description = '执行 Shell 命令。支持流式输出。';
  readonly requiredPermission = PermissionLevel.SHELL;
  
  readonly parameters: JSONSchema7 = {
    type: 'object',
    properties: {
      command: {
        type: 'string',
        description: '要执行的 Shell 命令'
      },
      timeout: {
        type: 'number',
        description: '命令执行超时时间（毫秒）',
        default: 120000, // 2 分钟
        minimum: 1000,
        maximum: 600000 // 10 分钟
      },
      stream: {
        type: 'boolean',
        description: '是否使用流式输出（适用于长时间运行的命令）',
        default: false
      }
    },
    required: ['command']
  };
  
  validateArgs(args: Record<string, unknown>): ValidationResult {
    const errors: string[] = [];
    
    if (!args.command || typeof args.command !== 'string') {
      errors.push('command 参数必须是非空字符串');
    }
    
    // 检查命令长度
    if (typeof args.command === 'string' && args.command.length > 10000) {
      errors.push('命令长度超过限制 (10,000 字符)');
    }
    
    return {
      valid: errors.length === 0,
      errors: errors.length > 0 ? errors : undefined
    };
  }
  
  async execute(
    args: Record<string, unknown>,
    context: ToolExecutionContext
  ): Promise<ToolResult | AsyncIterable<ToolChunk>> {
    const { command, timeout = 120000, stream = false } = args;
    
    if (stream) {
      return this.executeStream(
        command as string,
        { timeout: timeout as number, cwd: context.cwd, abortSignal: context.abortSignal }
      );
    }
    
    return this.executeSync(
      command as string,
      { timeout: timeout as number, cwd: context.cwd }
    );
  }
  
  /**
   * 同步执行命令
   */
  private async executeSync(
    command: string,
    options: { timeout: number; cwd: string }
  ): Promise<ToolResult> {
    const startTime = Date.now();
    
    try {
      const { stdout, stderr } = await exec(command, {
        timeout: options.timeout,
        cwd: options.cwd,
        maxBuffer: 10 * 1024 * 1024 // 10MB
      });
      
      return {
        success: true,
        output: stdout,
        duration: Date.now() - startTime,
        metadata: { stderr: stderr || undefined }
      };
    } catch (error) {
      return {
        success: false,
        output: (error as any).stdout || '',
        error: error instanceof Error ? error.message : String(error),
        duration: Date.now() - startTime,
        metadata: { stderr: (error as any).stderr }
      };
    }
  }
  
  /**
   * 流式执行命令
   */
  private async *executeStream(
    command: string,
    options: { timeout: number; cwd: string; abortSignal?: AbortSignal }
  ): AsyncIterable<ToolChunk> {
    const startTime = Date.now();
    
    // 设置超时
    const timeoutId = setTimeout(() => {
      options.abortSignal?.abort();
    }, options.timeout);
    
    try {
      const child = spawn(command, {
        shell: true,
        cwd: options.cwd,
        stdio: ['pipe', 'pipe', 'pipe']
      });
      
      // 监听 stdout
      child.stdout.on('data', (data: Buffer) => {
        yield {
          type: 'stdout',
          content: data.toString('utf-8'),
          timestamp: Date.now()
        };
      });
      
      // 监听 stderr
      child.stderr.on('data', (data: Buffer) => {
        yield {
          type: 'stderr',
          content: data.toString('utf-8'),
          timestamp: Date.now()
        };
      });
      
      // 等待进程结束
      const exitCode = await new Promise<number>((resolve, reject) => {
        child.on('close', resolve);
        child.on('error', reject);
        
        options.abortSignal?.addEventListener('abort', () => {
          child.kill('SIGTERM');
          reject(new Error('命令执行被取消'));
        });
      });
      
      yield {
        type: 'exit',
        content: '',
        exitCode,
        timestamp: Date.now()
      };
    } finally {
      clearTimeout(timeoutId);
    }
  }
}
```

---

## 4. 流式工具执行机制

### 4.1 流式执行架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Bash Tool (stream=true)                  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   Child Process Spawn                         │
│              spawn(command, { shell: true })                  │
└────────────────────────┬────────────────────────────────────┘
                         │
              ┌──────────┼──────────┐
              │          │          │
              ▼          ▼          ▼
         ┌────────┐ ┌────────┐ ┌────────┐
         │ stdin  │ │ stdout │ │ stderr │
         └────────┘ └───┬────┘ └───┬────┘
                        │          │
                        ▼          ▼
                   ┌─────────────────┐
                   │  AsyncIterator  │
                   │   Generator     │
                   └────────┬────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │        Tool Chunks          │
              │  ┌───────────────────────┐  │
              │  │ { type: 'stdout',     │  │
              │  │   content: '...',     │  │
              │  │   timestamp: 123 }    │  │
              │  └───────────────────────┘  │
              │  ┌───────────────────────┐  │
              │  │ { type: 'stderr',     │  │
              │  │   content: '...',     │  │
              │  │   timestamp: 124 }    │  │
              │  └───────────────────────┘  │
              │  ┌───────────────────────┐  │
              │  │ { type: 'exit',       │  │
              │  │   exitCode: 0,        │  │
              │  │   timestamp: 125 }    │  │
              │  └───────────────────────┘  │
              └─────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    LLM Response Handler                       │
│  • 实时收集输出                                               │
│  • 累积到 token 限制                                          │
│  • 发送回 LLM 进行下一轮推理                                  │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 流式输出收集器

```typescript
/**
 * 流式输出收集器
 * 收集流式输出并在达到阈值时返回
 */
export class StreamOutputCollector {
  private chunks: ToolChunk[] = [];
  private totalOutputLength = 0;
  private readonly maxOutputLength: number;
  private readonly maxChunks: number;
  
  constructor(options: { maxOutputLength?: number; maxChunks?: number } = {}) {
    this.maxOutputLength = options.maxOutputLength ?? 50000; // 50KB
    this.maxChunks = options.maxChunks ?? 1000;
  }
  
  /**
   * 添加输出块
   * @returns 是否应该停止收集
   */
  addChunk(chunk: ToolChunk): boolean {
    this.chunks.push(chunk);
    
    if (chunk.type === 'stdout' || chunk.type === 'stderr') {
      this.totalOutputLength += chunk.content.length;
    }
    
    // 检查是否达到限制
    if (this.totalOutputLength >= this.maxOutputLength) {
      return true; // 应该停止
    }
    
    if (this.chunks.length >= this.maxChunks) {
      return true; // 应该停止
    }
    
    // 检查是否是退出块
    if (chunk.type === 'exit') {
      return true; // 命令已结束
    }
    
    return false; // 继续收集
  }
  
  /**
   * 获取收集的输出
   */
  getOutput(): string {
    return this.chunks
      .filter(c => c.type === 'stdout' || c.type === 'stderr')
      .map(c => c.content)
      .join('');
  }
  
  /**
   * 获取完整结果
   */
  getResult(): StreamCollectionResult {
    const exitChunk = this.chunks.find(c => c.type === 'exit');
    
    return {
      output: this.getOutput(),
      exitCode: exitChunk?.exitCode ?? -1,
      truncated: this.totalOutputLength >= this.maxOutputLength,
      chunkCount: this.chunks.length,
      totalOutputLength: this.totalOutputLength
    };
  }
}

export interface StreamCollectionResult {
  output: string;
  exitCode: number;
  truncated: boolean;
  chunkCount: number;
  totalOutputLength: number;
}
```

### 4.3 流式执行循环

```typescript
/**
 * 流式执行循环
 * 处理长时间运行的命令
 */
export async function* executeWithStreaming(
  command: string,
  options: StreamExecuteOptions
): AsyncIterable<ToolChunk> {
  const { timeout, cwd, abortSignal, onChunk } = options;
  
  const child = spawn(command, {
    shell: true,
    cwd,
    stdio: ['pipe', 'pipe', 'pipe']
  });
  
  // 超时处理
  const timeoutId = setTimeout(() => {
    child.kill('SIGTERM');
    setTimeout(() => child.kill('SIGKILL'), 5000); // 5秒后强制杀死
  }, timeout);
  
  // 取消信号处理
  abortSignal?.addEventListener('abort', () => {
    child.kill('SIGTERM');
  });
  
  try {
    // 收集 stdout
    for await (const chunk of iterateStream(child.stdout)) {
      const toolChunk: ToolChunk = {
        type: 'stdout',
        content: chunk.toString('utf-8'),
        timestamp: Date.now()
      };
      
      onChunk?.(toolChunk);
      yield toolChunk;
    }
    
    // 收集 stderr
    for await (const chunk of iterateStream(child.stderr)) {
      const toolChunk: ToolChunk = {
        type: 'stderr',
        content: chunk.toString('utf-8'),
        timestamp: Date.now()
      };
      
      onChunk?.(toolChunk);
      yield toolChunk;
    }
    
    // 等待退出
    const exitCode = await waitForExit(child);
    
    yield {
      type: 'exit',
      content: '',
      exitCode,
      timestamp: Date.now()
    };
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * 将 ReadableStream 转换为 AsyncIterable
 */
async function* iterateStream(stream: Readable): AsyncIterable<Buffer> {
  for await (const chunk of stream) {
    yield chunk as Buffer;
  }
}

/**
 * 等待子进程退出
 */
function waitForExit(child: ChildProcess): Promise<number> {
  return new Promise((resolve, reject) => {
    child.on('close', (code) => resolve(code ?? -1));
    child.on('error', reject);
  });
}

export interface StreamExecuteOptions {
  timeout: number;
  cwd: string;
  abortSignal?: AbortSignal;
  onChunk?: (chunk: ToolChunk) => void;
}
```

---

## 5. 工具权限过滤

### 5.1 权限过滤流程

```
┌─────────────────────────────────────────────────────────────┐
│                   所有可用工具列表                             │
│              (All Available Tools)                            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              权限过滤器 (Permission Filter)                   │
│                                                              │
│  for each tool in allTools:                                  │
│    if tool.requiredPermission <= sessionPermission:          │
│      add to allowedTools                                     │
│    else:                                                     │
│      add to deniedTools (with reason)                        │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                    ┌────┴────┐
                    │         │
                    ▼         ▼
         ┌──────────────┐ ┌──────────────┐
         │ Allowed Tools│ │ Denied Tools │
         │ (传递给 LLM)  │ │ (记录日志)    │
         └──────────────┘ └──────────────┘
```

### 5.2 权限过滤实现

```typescript
/**
 * 工具权限过滤器
 */
export class ToolPermissionFilter {
  /**
   * 根据权限过滤工具
   */
  public filter(
    tools: AgentTool[],
    sessionPermission: PermissionLevel
  ): FilterResult {
    const allowed: AgentTool[] = [];
    const denied: DeniedToolInfo[] = [];
    
    for (const tool of tools) {
      if (tool.requiredPermission <= sessionPermission) {
        allowed.push(tool);
      } else {
        denied.push({
          tool,
          reason: `需要 ${PermissionLevel[tool.requiredPermission]} 权限，` +
                  `当前会话权限为 ${PermissionLevel[sessionPermission]}`
        });
      }
    }
    
    return { allowed, denied };
  }
  
  /**
   * 生成工具描述（包含权限信息）
   */
  public generateToolDescriptions(
    tools: AgentTool[],
    sessionPermission: PermissionLevel
  ): string {
    const lines: string[] = [];
    
    lines.push('## Available Tools');
    lines.push('');
    
    for (const tool of tools) {
      const isAllowed = tool.requiredPermission <= sessionPermission;
      const status = isAllowed ? '✅ Available' : '❌ Denied';
      
      lines.push(`### ${tool.name} (${status})`);
      lines.push('');
      lines.push(tool.description);
      lines.push('');
      
      if (!isAllowed) {
        lines.push(`**Required Permission:** ${PermissionLevel[tool.requiredPermission]}`);
        lines.push('');
      }
    }
    
    return lines.join('\n');
  }
}

export interface FilterResult {
  allowed: AgentTool[];
  denied: DeniedToolInfo[];
}

export interface DeniedToolInfo {
  tool: AgentTool;
  reason: string;
}
```

---

## 6. OpenAI Function Calling 格式转换

### 6.1 转换流程

```
┌─────────────────────────────────────────────────────────────┐
│                    AgentTool 定义                            │
│                                                              │
│  {                                                           │
│    name: "read_file",                                        │
│    description: "读取文件内容",                               │
│    parameters: { JSON Schema }                               │
│  }                                                           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              OpenAI Format Converter                          │
│                                                              │
│  {                                                           │
│    type: "function",                                         │
│    function: {                                               │
│      name: "read_file",                                      │
│      description: "读取文件内容",                             │
│      parameters: { JSON Schema }                             │
│    }                                                         │
│  }                                                           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│               Chat Completion API Request                    │
│                                                              │
│  {                                                           │
│    model: "gpt-4",                                           │
│    messages: [...],                                          │
│    tools: [ /* converted tools */ ],                         │
│    tool_choice: "auto"                                       │
│  }                                                           │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 转换器实现

```typescript
import type { ChatCompletionTool } from 'openai/resources';

/**
 * OpenAI Function Calling 格式转换器
 */
export class OpenAIToolConverter {
  /**
   * 将 AgentTool 转换为 OpenAI 格式
   */
  public static toOpenAIFunction(tool: AgentTool): ChatCompletionTool {
    return {
      type: 'function',
      function: {
        name: tool.name,
        description: tool.description,
        parameters: tool.parameters
      }
    };
  }
  
  /**
   * 批量转换
   */
  public static toOpenAIFunctions(tools: AgentTool[]): ChatCompletionTool[] {
    return tools.map(tool => this.toOpenAIFunction(tool));
  }
  
  /**
   * 从 OpenAI 响应解析工具调用
   */
  public static parseToolCall(
    toolCall: ChatCompletionMessageToolCall
  ): ParsedToolCall {
    const { function: func } = toolCall;
    
    return {
      id: toolCall.id,
      name: func.name,
      args: JSON.parse(func.arguments)
    };
  }
  
  /**
   * 批量解析工具调用
   */
  public static parseToolCalls(
    toolCalls: ChatCompletionMessageToolCall[]
  ): ParsedToolCall[] {
    return toolCalls.map(call => this.parseToolCall(call));
  }
}

/**
 * 解析后的工具调用
 */
export interface ParsedToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}
```

---

## 7. 路径安全验证

### 7.1 路径验证流程

```
┌─────────────────────────────────────────────────────────────┐
│                    输入文件路径                               │
│                  (Input File Path)                            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Step 1: 路径规范化                               │
│  • 解析为绝对路径                                              │
│  • 解析符号链接                                                │
│  • 清理多余的斜杠                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Step 2: 路径遍历攻击检测                          │
│  • 检查 ../ 模式                                               │
│  • 检查 Unicode 编码绕过                                       │
│  • 检查符号链接绕过                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                    ┌────┴────┐
                    │ 安全?   │
                    └────┬────┘
                    No   │   Yes
                    │    │    │
                    ▼    │    ▼
         ┌─────────────┐ │ ┌──────────────────────────────┐
         │ 拒绝并报错   │ │ │ Step 3: 目录白名单检查         │
         └─────────────┘ │ └──────────────┬───────────────┘
                         │                │
                         │         ┌──────┴──────┐
                         │         │ 在白名单内?  │
                         │         └──────┬──────┘
                         │          No    │   Yes
                         │          │     │    │
                         │          ▼     │    ▼
                         │  ┌──────────┐  │ ┌─────────────┐
                         │  │ 拒绝并报错 │  │ │ Step 4: 黑名单检查│
                         │  └──────────┘  │ └──────┬──────┘
                         │                │        │
                         │                │  ┌─────┴─────┐
                         │                │  │ 在黑名单?  │
                         │                │  └─────┬─────┘
                         │                │  No   │  Yes
                         │                │   │   │   │
                         │                │   ▼   │   ▼
                         │                │  通过  │  拒绝
                         │                │       │
                         ▼                ▼       ▼
┌─────────────────────────────────────────────────────────────┐
│                    验证通过，允许操作                           │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 路径验证器完整实现

```typescript
import * as path from 'path';
import * as fs from 'fs/promises';

/**
 * 路径验证器
 */
export class PathValidator {
  private allowedDirs: string[];
  private blockedDirs: string[];
  private blockedFiles: Set<string>;
  
  constructor(config: PathValidationConfig) {
    this.allowedDirs = config.allowedDirectories.map(p => path.resolve(p));
    this.blockedDirs = config.blockedDirectories?.map(p => path.resolve(p)) || [];
    this.blockedFiles = new Set(config.blockedFiles?.map(p => path.resolve(p)) || []);
  }
  
  /**
   * 验证路径
   */
  public async validatePath(filePath: string): Promise<ValidationResult> {
    // 1. 路径规范化
    const resolvedPath = await this.resolvePath(filePath);
    if (!resolvedPath) {
      return {
        valid: false,
        reason: '无法解析路径'
      };
    }
    
    // 2. 路径遍历攻击检测
    if (this.containsPathTraversal(filePath)) {
      return {
        valid: false,
        reason: '检测到路径遍历攻击尝试'
      };
    }
    
    // 3. 检查文件黑名单
    if (this.blockedFiles.has(resolvedPath)) {
      return {
        valid: false,
        reason: `文件在禁止列表中: ${resolvedPath}`
      };
    }
    
    // 4. 检查目录黑名单
    for (const blocked of this.blockedDirs) {
      if (this.isPathWithin(resolvedPath, blocked)) {
        return {
          valid: false,
          reason: `路径在禁止目录中: ${blocked}`
        };
      }
    }
    
    // 5. 检查目录白名单
    let isInAllowedDir = false;
    for (const allowed of this.allowedDirs) {
      if (this.isPathWithin(resolvedPath, allowed)) {
        isInAllowedDir = true;
        break;
      }
    }
    
    if (!isInAllowedDir) {
      return {
        valid: false,
        reason: '路径不在允许的目录范围内'
      };
    }
    
    return {
      valid: true,
      resolvedPath
    };
  }
  
  /**
   * 解析路径（包括符号链接解析）
   */
  private async resolvePath(filePath: string): Promise<string | null> {
    try {
      const resolved = path.resolve(filePath);
      const realPath = await fs.realpath(resolved);
      return realPath;
    } catch {
      // 文件可能不存在，返回解析后的路径
      return path.resolve(filePath);
    }
  }
  
  /**
   * 检测路径遍历攻击
   */
  private containsPathTraversal(filePath: string): boolean {
    // 检查常见的路径遍历模式
    const traversalPatterns = [
      /\.\./,           // 标准 ..
      /%2e%2e/i,        // URL 编码 ..
      /%252e%252e/i,    // 双重 URL 编码
      /\.\.%2f/i,       // 混合编码
      /\.\.\\/,         // Windows 风格
    ];
    
    for (const pattern of traversalPatterns) {
      if (pattern.test(filePath)) {
        return true;
      }
    }
    
    return false;
  }
  
  /**
   * 检查 target 是否在 base 目录内
   */
  private isPathWithin(target: string, base: string): boolean {
    const relative = path.relative(base, target);
    return (
      !relative.startsWith('..') && 
      !path.isAbsolute(relative) &&
      relative !== ''
    );
  }
}

export interface PathValidationConfig {
  allowedDirectories: string[];
  blockedDirectories?: string[];
  blockedFiles?: string[];
}

export interface ValidationResult {
  valid: boolean;
  reason?: string;
  resolvedPath?: string;
}
```

### 7.3 路径安全测试用例

```typescript
// 测试用例
const testCases = [
  // 应该通过验证
  { path: '/Users/zhanghanzhi/projects/my-app/src/index.ts', valid: true },
  { path: './src/utils.ts', valid: true },
  
  // 应该被拒绝
  { path: '../../../etc/passwd', valid: false, reason: '路径遍历' },
  { path: '/Users/zhanghanzhi/.ssh/id_rsa', valid: false, reason: '不在允许目录' },
  { path: '/Users/zhanghanzhi/projects/my-app/.env', valid: false, reason: '文件黑名单' },
  { path: '/Users/zhanghanzhi/projects/my-app/node_modules/pkg/index.js', valid: false, reason: '目录黑名单' },
];
```

---

## 8. 工具注册与发现

### 8.1 工具注册表

```typescript
/**
 * 工具注册表
 * 管理所有可用工具
 */
export class ToolRegistry {
  private tools: Map<string, AgentTool> = new Map();
  
  /**
   * 注册工具
   */
  public register(tool: AgentTool): void {
    if (this.tools.has(tool.name)) {
      throw new Error(`工具已注册: ${tool.name}`);
    }
    this.tools.set(tool.name, tool);
  }
  
  /**
   * 注销工具
   */
  public unregister(name: string): boolean {
    return this.tools.delete(name);
  }
  
  /**
   * 获取工具
   */
  public get(name: string): AgentTool | undefined {
    return this.tools.get(name);
  }
  
  /**
   * 获取所有工具
   */
  public getAll(): AgentTool[] {
    return Array.from(this.tools.values());
  }
  
  /**
   * 注册默认工具集
   */
  public registerDefaults(): void {
    this.register(new ListDirTool());
    this.register(new ReadFileTool());
    this.register(new WriteFileTool());
    this.register(new EditFileTool());
    this.register(new GlobSearchTool());
    this.register(new GrepSearchTool());
    this.register(new BashTool());
  }
}
```

---

## 附录

### A. 工具参数限制

| 工具 | 参数 | 限制 |
|------|------|------|
| read_file | limit | 最大 10,000 行 |
| write_file | content | 最大 100,000 字符 |
| bash | command | 最大 10,000 字符 |
| bash | timeout | 最大 600,000ms (10分钟) |
| glob_search | maxResults | 最大 1,000 条 |
| grep_search | maxResults | 最大 500 条 |

### B. 相关文档

- [权限系统设计文档](./PERMISSION_SYSTEM.md)
- [上下文引擎设计文档](./CONTEXT_ENGINE.md)
- [工具扩展开发指南](../03-开发指南/TOOL_DEVELOPMENT.md)
