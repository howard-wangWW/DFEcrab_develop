# 上下文引擎设计文档

## 1. 概述

上下文引擎是 DFEcrab 的智能组件，负责管理 AI Agent 与 LLM 之间的上下文信息流。通过自动发现项目配置、集成 Git 状态、智能 Token 估算和动态提示词管理，确保 LLM 获得最优的上下文信息。

### 1.1 设计目标

- **自动发现**：自动查找并加载项目配置文件（CLAUDE.md 等）
- **智能裁剪**：根据 Token 限制动态调整上下文内容
- **状态感知**：集成 Git 状态，提供项目变更上下文
- **用量透明**：实时报告上下文使用情况
- **边界控制**：精确控制提示词大小，防止超出模型限制

### 1.2 架构位置

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Request                             │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Context Engine (上下文引擎)                    │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ CLAUDE.md    │  │ Git Status   │  │  System Prompt       │  │
│  │ Auto-Discover│  │ Cache        │  │  Builder             │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│         └─────────────────┼──────────────────────┘              │
│                           │                                     │
│                  ┌────────┴────────┐                            │
│                  │  Token Estimator│                            │
│                  └────────┬────────┘                            │
│                           │                                     │
│                  ┌────────┴────────┐                            │
│                  │ Context Trimmer │                            │
│                  └────────┬────────┘                            │
│                           │                                     │
└───────────────────────────┼─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Final System Prompt                           │
│                                                                  │
│  [Project Context] + [Git Status] + [Instructions] + [Tools]    │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         LLM API Call                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. CLAUDE.md 自动发现机制

### 2.1 发现流程

```
┌─────────────────────────────────────────────────────────────┐
│                    用户指定工作目录                            │
│                  (Working Directory)                          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Step 1: 查找 Git 根目录                          │
│  • 从 cwd 向上遍历，查找 .git 目录                            │
│  • 确定项目根目录                                             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Step 2: 搜索 CLAUDE.md 文件                      │
│                                                              │
│  搜索优先级（从高到低）:                                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 1. {cwd}/CLAUDE.md          (当前目录)               │    │
│  │ 2. {gitRoot}/CLAUDE.md      (Git 根目录)             │    │
│  │ 3. {gitRoot}/.github/CLAUDE.md                       │    │
│  │ 4. {gitRoot}/docs/CLAUDE.md                          │    │
│  │ 5. {home}/CLAUDE.md         (用户主目录)              │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Step 3: 解析并验证                              │
│  • 验证 Markdown 格式                                         │
│  • 提取关键章节                                               │
│  • 检查文件大小限制                                           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Step 4: 注入到系统提示                            │
│  • 作为 Project Context 部分                                  │
│  • 在工具描述之前                                              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 自动发现实现

```typescript
import * as path from 'path';
import * as fs from 'fs/promises';

/**
 * CLAUDE.md 发现器
 */
export class ClaudeMdDiscoverer {
  /**
   * CLAUDE.md 搜索路径（按优先级排序）
   */
  private static readonly SEARCH_PATHS = [
    'CLAUDE.md',
    '.github/CLAUDE.md',
    'docs/CLAUDE.md',
    '.cursor/rules/CLAUDE.md',
  ];
  
  /**
   * 最大文件大小 (100KB)
   */
  private static readonly MAX_FILE_SIZE = 100 * 1024;
  
  /**
   * 发现并加载 CLAUDE.md
   */
  public async discover(cwd: string): Promise<ClaudeMdResult> {
    // 1. 查找 Git 根目录
    const gitRoot = await this.findGitRoot(cwd);
    
    // 2. 搜索 CLAUDE.md
    const searchPaths = this.getSearchPaths(cwd, gitRoot);
    const found = await this.searchClaudeMd(searchPaths);
    
    if (!found) {
      return {
        found: false,
        content: null,
        path: null,
        warning: '未找到 CLAUDE.md 文件'
      };
    }
    
    // 3. 验证并加载内容
    const content = await this.loadAndValidate(found);
    
    return {
      found: true,
      content,
      path: found,
      warning: null
    };
  }
  
  /**
   * 查找 Git 根目录
   */
  private async findGitRoot(cwd: string): Promise<string | null> {
    let current = path.resolve(cwd);
    const root = path.parse(current).root;
    
    while (current !== root) {
      try {
        const gitDir = path.join(current, '.git');
        const stat = await fs.stat(gitDir);
        if (stat.isDirectory() || stat.isSymbolicLink()) {
          return current;
        }
      } catch {
        // .git 不存在，继续向上
      }
      
      current = path.dirname(current);
    }
    
    return null;
  }
  
  /**
   * 获取搜索路径列表
   */
  private getSearchPaths(cwd: string, gitRoot: string | null): string[] {
    const paths: string[] = [];
    
    // 当前目录优先
    for (const searchPath of ClaudeMdDiscoverer.SEARCH_PATHS) {
      paths.push(path.join(cwd, searchPath));
    }
    
    // Git 根目录
    if (gitRoot) {
      for (const searchPath of ClaudeMdDiscoverer.SEARCH_PATHS) {
        const fullPath = path.join(gitRoot, searchPath);
        if (!paths.includes(fullPath)) {
          paths.push(fullPath);
        }
      }
    }
    
    // 用户主目录
    paths.push(path.join(process.env.HOME || '', 'CLAUDE.md'));
    
    return paths;
  }
  
  /**
   * 搜索 CLAUDE.md 文件
   */
  private async searchClaudeMd(paths: string[]): Promise<string | null> {
    for (const filePath of paths) {
      try {
        const stat = await fs.stat(filePath);
        if (stat.isFile()) {
          return filePath;
        }
      } catch {
        // 文件不存在，继续
      }
    }
    
    return null;
  }
  
  /**
   * 加载并验证 CLAUDE.md
   */
  private async loadAndValidate(filePath: string): Promise<string> {
    const stat = await fs.stat(filePath);
    
    // 检查文件大小
    if (stat.size > ClaudeMdDiscoverer.MAX_FILE_SIZE) {
      throw new Error(
        `CLAUDE.md 文件过大 (${stat.size} bytes)，` +
        `超过限制 (${ClaudeMdDiscoverer.MAX_FILE_SIZE} bytes)`
      );
    }
    
    const content = await fs.readFile(filePath, 'utf-8');
    
    // 基本验证：检查是否为 Markdown 格式
    if (!this.isValidMarkdown(content)) {
      throw new Error('CLAUDE.md 文件格式无效');
    }
    
    return content;
  }
  
  /**
   * 验证 Markdown 格式
   */
  private isValidMarkdown(content: string): boolean {
    // 至少包含一些文本内容
    return content.trim().length > 0;
  }
}

/**
 * CLAUDE.md 发现结果
 */
export interface ClaudeMdResult {
  /** 是否找到 */
  found: boolean;
  
  /** 文件内容 */
  content: string | null;
  
  /** 文件路径 */
  path: string | null;
  
  /** 警告信息 */
  warning: string | null;
}
```

### 2.3 CLAUDE.md 内容解析

```typescript
/**
 * CLAUDE.md 内容解析器
 */
export class ClaudeMdParser {
  /**
   * 解析 CLAUDE.md 内容，提取结构化信息
   */
  public parse(content: string): ParsedClaudeMd {
    const sections = this.extractSections(content);
    
    return {
      rawContent: content,
      sections,
      projectInfo: this.extractProjectInfo(sections),
      instructions: this.extractInstructions(sections),
      codeStyle: this.extractCodeStyle(sections),
      tokenEstimate: this.estimateTokens(content)
    };
  }
  
  /**
   * 提取 Markdown 章节
   */
  private extractSections(content: string): Section[] {
    const sections: Section[] = [];
    const lines = content.split('\n');
    
    let currentSection: Section | null = null;
    
    for (const line of lines) {
      const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
      
      if (headingMatch) {
        // 保存前一个章节
        if (currentSection) {
          sections.push(currentSection);
        }
        
        // 开始新章节
        currentSection = {
          level: headingMatch[1].length,
          title: headingMatch[2].trim(),
          content: []
        };
      } else if (currentSection) {
        currentSection.content.push(line);
      }
    }
    
    // 保存最后一个章节
    if (currentSection) {
      sections.push(currentSection);
    }
    
    return sections;
  }
  
  /**
   * 提取项目信息
   */
  private extractProjectInfo(sections: Section[]): ProjectInfo {
    const info: ProjectInfo = {};
    
    for (const section of sections) {
      const title = section.title.toLowerCase();
      const content = section.content.join('\n');
      
      if (title.includes('project') || title.includes('项目')) {
        info.description = content.trim();
      }
      
      if (title.includes('tech') || title.includes('stack') || title.includes('技术')) {
        info.techStack = this.parseTechStack(content);
      }
      
      if (title.includes('structure') || title.includes('目录') || title.includes('架构')) {
        info.structure = content.trim();
      }
    }
    
    return info;
  }
  
  /**
   * 提取指令
   */
  private extractInstructions(sections: Section[]): string[] {
    const instructions: string[] = [];
    
    for (const section of sections) {
      const title = section.title.toLowerCase();
      
      if (
        title.includes('instruction') ||
        title.includes('guideline') ||
        title.includes('规则') ||
        title.includes('指南') ||
        title.includes('note') ||
        title.includes('注意')
      ) {
        instructions.push(section.content.join('\n').trim());
      }
    }
    
    return instructions;
  }
  
  /**
   * 提取代码风格
   */
  private extractCodeStyle(sections: Section[]): string[] {
    const styles: string[] = [];
    
    for (const section of sections) {
      const title = section.title.toLowerCase();
      
      if (
        title.includes('style') ||
        title.includes('convention') ||
        title.includes('风格') ||
        title.includes('规范') ||
        title.includes('format') ||
        title.includes('格式')
      ) {
        styles.push(section.content.join('\n').trim());
      }
    }
    
    return styles;
  }
  
  /**
   * 解析技术栈
   */
  private parseTechStack(content: string): string[] {
    // 提取列表项
    const lines = content.split('\n');
    const techs: string[] = [];
    
    for (const line of lines) {
      const match = line.match(/^\s*[-*]\s+(.+)$/);
      if (match) {
        techs.push(match[1].trim());
      }
    }
    
    return techs;
  }
  
  /**
   * 估算 Token 数量
   */
  private estimateTokens(content: string): number {
    // 使用简化的 Token 估算算法
    // 1 个英文单词 ≈ 1.3 tokens
    // 1 个中文字符 ≈ 1.5 tokens
    const englishWords = content.match(/[a-zA-Z]+/g)?.length || 0;
    const chineseChars = (content.match(/[\u4e00-\u9fa5]/g) || []).length;
    const otherChars = content.length - englishWords - chineseChars;
    
    return Math.ceil(
      englishWords * 1.3 +
      chineseChars * 1.5 +
      otherChars * 0.5
    );
  }
}

export interface Section {
  level: number;
  title: string;
  content: string[];
}

export interface ProjectInfo {
  description?: string;
  techStack?: string[];
  structure?: string;
}

export interface ParsedClaudeMd {
  rawContent: string;
  sections: Section[];
  projectInfo: ProjectInfo;
  instructions: string[];
  codeStyle: string[];
  tokenEstimate: number;
}
```

---

## 3. Git 状态缓存集成

### 3.1 Git 状态缓存架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Git Status Cache                           │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ File Status  │  │ Branch Info  │  │  Commit History  │  │
│  │ Cache        │  │ Cache        │  │  Cache           │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                    │             │
│         └─────────────────┼────────────────────┘             │
│                           │                                  │
│                  ┌────────┴────────┐                         │
│                  │  Cache Manager  │                         │
│                  │                 │                         │
│                  │  • TTL 管理      │                         │
│                  │  • 失效策略      │                         │
│                  │  • 懒加载        │                         │
│                  └─────────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Git 状态缓存实现

```typescript
import { execFile } from 'child_process';
import { promisify } from 'util';

const execFileAsync = promisify(execFile);

/**
 * Git 状态缓存
 */
export class GitStatusCache {
  private cache: Map<string, CacheEntry> = new Map();
  private readonly ttl: number;
  private readonly cwd: string;
  
  constructor(options: GitCacheOptions) {
    this.ttl = options.ttl ?? 30000; // 默认 30 秒
    this.cwd = options.cwd;
  }
  
  /**
   * 获取 Git 状态
   */
  public async getStatus(): Promise<GitStatus> {
    return this.getOrFetch('status', async () => {
      return this.fetchGitStatus();
    });
  }
  
  /**
   * 获取当前分支
   */
  public async getCurrentBranch(): Promise<string> {
    return this.getOrFetch('branch', async () => {
      return this.fetchCurrentBranch();
    });
  }
  
  /**
   * 获取最近提交
   */
  public async getRecentCommits(count: number = 5): Promise<GitCommit[]> {
    return this.getOrFetch(`commits:${count}`, async () => {
      return this.fetchRecentCommits(count);
    });
  }
  
  /**
   * 获取 Git 差异
   */
  public async getDiff(staged: boolean = false): Promise<string> {
    const key = staged ? 'diff:staged' : 'diff:unstaged';
    return this.getOrFetch(key, async () => {
      return this.fetchDiff(staged);
    });
  }
  
  /**
   * 清除缓存
   */
  public invalidate(): void {
    this.cache.clear();
  }
  
  /**
   * 获取或刷新缓存
   */
  private async getOrFetch<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
    const entry = this.cache.get(key);
    
    // 检查缓存是否有效
    if (entry && Date.now() - entry.timestamp < this.ttl) {
      return entry.data as T;
    }
    
    // 获取新数据
    const data = await fetcher();
    
    this.cache.set(key, {
      data,
      timestamp: Date.now()
    });
    
    return data;
  }
  
  /**
   * 获取 Git 状态
   */
  private async fetchGitStatus(): Promise<GitStatus> {
    const { stdout } = await execFileAsync('git', ['status', '--porcelain'], {
      cwd: this.cwd
    });
    
    const files: GitFileStatus[] = [];
    
    for (const line of stdout.trim().split('\n').filter(Boolean)) {
      const indexStatus = line[0];
      const worktreeStatus = line[1];
      const filePath = line.slice(3).trim();
      
      files.push({
        path: filePath,
        indexStatus: this.parseStatus(indexStatus),
        worktreeStatus: this.parseStatus(worktreeStatus)
      });
    }
    
    return { files };
  }
  
  /**
   * 获取当前分支
   */
  private async fetchCurrentBranch(): Promise<string> {
    const { stdout } = await execFileAsync('git', ['branch', '--show-current'], {
      cwd: this.cwd
    });
    
    return stdout.trim();
  }
  
  /**
   * 获取最近提交
   */
  private async fetchRecentCommits(count: number): Promise<GitCommit[]> {
    const { stdout } = await execFileAsync('git', [
      'log',
      `--max-count=${count}`,
      '--format=%H|%h|%s|%an|%ai'
    ], { cwd: this.cwd });
    
    return stdout.trim().split('\n').filter(Boolean).map(line => {
      const [hash, shortHash, subject, author, date] = line.split('|');
      return { hash, shortHash, subject, author, date };
    });
  }
  
  /**
   * 获取差异
   */
  private async fetchDiff(staged: boolean): Promise<string> {
    const args = staged
      ? ['diff', '--cached', '--', ':!*.lock']
      : ['diff', '--', ':!*.lock'];
    
    try {
      const { stdout } = await execFileAsync('git', args, {
        cwd: this.cwd,
        maxBuffer: 5 * 1024 * 1024 // 5MB
      });
      
      return stdout;
    } catch {
      return '';
    }
  }
  
  /**
   * 解析状态字符
   */
  private parseStatus(char: string): FileChangeType {
    const statusMap: Record<string, FileChangeType> = {
      'M': 'modified',
      'A': 'added',
      'D': 'deleted',
      'R': 'renamed',
      'C': 'copied',
      'U': 'unmerged',
      '?': 'untracked',
      ' ': 'unchanged'
    };
    
    return statusMap[char] || 'unchanged';
  }
}

export interface GitCacheOptions {
  cwd: string;
  ttl?: number;
}

export interface GitStatus {
  files: GitFileStatus[];
}

export interface GitFileStatus {
  path: string;
  indexStatus: FileChangeType;
  worktreeStatus: FileChangeType;
}

export type FileChangeType = 
  | 'modified'
  | 'added'
  | 'deleted'
  | 'renamed'
  | 'copied'
  | 'unmerged'
  | 'untracked'
  | 'unchanged';

export interface GitCommit {
  hash: string;
  shortHash: string;
  subject: string;
  author: string;
  date: string;
}

interface CacheEntry {
  data: unknown;
  timestamp: number;
}
```

### 3.3 Git 状态格式化输出

```typescript
/**
 * Git 状态格式化器
 */
export class GitStatusFormatter {
  /**
   * 格式化为系统提示文本
   */
  public formatForSystemPrompt(status: GitStatus, branch: string, commits: GitCommit[]): string {
    const lines: string[] = [];
    
    lines.push('## Git Repository Status');
    lines.push('');
    lines.push(`**Branch:** ${branch}`);
    lines.push('');
    
    // 变更文件
    const changedFiles = status.files.filter(f => 
      f.indexStatus !== 'unchanged' || f.worktreeStatus !== 'unchanged'
    );
    
    if (changedFiles.length > 0) {
      lines.push('### Changed Files');
      lines.push('');
      
      for (const file of changedFiles) {
        const icon = this.getStatusIcon(file);
        lines.push(`${icon} ${file.path}`);
      }
      
      lines.push('');
    }
    
    // 最近提交
    if (commits.length > 0) {
      lines.push('### Recent Commits');
      lines.push('');
      
      for (const commit of commits) {
        lines.push(`- \`${commit.shortHash}\` ${commit.subject}`);
      }
      
      lines.push('');
    }
    
    return lines.join('\n');
  }
  
  /**
   * 获取状态图标
   */
  private getStatusIcon(file: GitFileStatus): string {
    if (file.indexStatus === 'added' || file.worktreeStatus === 'added') return '🆕';
    if (file.indexStatus === 'deleted' || file.worktreeStatus === 'deleted') return '🗑️';
    if (file.indexStatus === 'modified' || file.worktreeStatus === 'modified') return '✏️';
    if (file.indexStatus === 'renamed' || file.worktreeStatus === 'renamed') return '📝';
    if (file.indexStatus === 'untracked' || file.worktreeStatus === 'untracked') return '❓';
    return '📄';
  }
}
```

---

## 4. Token 估算算法

### 4.1 Token 估算策略

```
┌─────────────────────────────────────────────────────────────┐
│                    Token Estimator                            │
│                                                              │
│  估算方法:                                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                                                      │    │
│  │  1. 精确估算 (使用 tiktoken 库)                      │    │
│  │     • 适用于 OpenAI 模型                              │    │
│  │     • 准确度: ~99%                                   │    │
│  │     • 性能: 中等                                      │    │
│  │                                                      │    │
│  │  2. 启发式估算 (字符/单词统计)                        │    │
│  │     • 适用于所有模型                                  │    │
│  │     • 准确度: ~85-95%                                │    │
│  │     • 性能: 高                                        │    │
│  │                                                      │    │
│  │  3. 保守估算 (最坏情况)                               │    │
│  │     • 用于边界检查                                     │    │
│  │     • 准确度: 偏低                                     │    │
│  │     • 性能: 高                                        │    │
│  │                                                      │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  默认使用启发式估算，可选切换到精确估算                        │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Token 估算器实现

```typescript
/**
 * Token 估算器
 */
export class TokenEstimator {
  /**
   * 估算系数
   */
  private static readonly COEFFICIENTS = {
    // 英文单词到 Token
    englishWordToToken: 1.3,
    
    // 中文字符到 Token
    chineseCharToToken: 1.5,
    
    // 代码字符到 Token
    codeCharToToken: 0.8,
    
    // 标点符号到 Token
    punctuationToToken: 0.5,
    
    // 换行符到 Token
    newlineToToken: 1.2,
    
    // 空白字符到 Token
    whitespaceToToken: 0.3
  };
  
  /**
   * 估算文本 Token 数量（启发式方法）
   */
  public estimateTokensHeuristic(text: string): number {
    // 分类统计
    const englishWords = (text.match(/[a-zA-Z]+/g) || []).length;
    const chineseChars = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
    const codeChars = (text.match(/[a-zA-Z0-9_{}()[\];,.<>\/\\|~`!@#$%^&*+=-]/g) || []).length;
    const punctuations = (text.match(/[.,;:!?'"()]/g) || []).length;
    const newlines = (text.match(/\n/g) || []).length;
    const whitespaces = (text.match(/\s/g) || []).length;
    
    // 计算重叠
    const totalChars = text.length;
    const countedChars = englishWords + chineseChars + codeChars + punctuations + newlines;
    const otherChars = Math.max(0, totalChars - countedChars);
    
    // 加权计算
    const tokens = 
      englishWords * TokenEstimator.COEFFICIENTS.englishWordToToken +
      chineseChars * TokenEstimator.COEFFICIENTS.chineseCharToToken +
      punctuations * TokenEstimator.COEFFICIENTS.punctuationToToken +
      newlines * TokenEstimator.COEFFICIENTS.newlineToToken +
      otherChars * TokenEstimator.COEFFICIENTS.whitespaceToToken;
    
    return Math.ceil(tokens);
  }
  
  /**
   * 估算消息列表的 Token 数量
   */
  public estimateMessagesTokens(messages: ChatMessage[]): number {
    let totalTokens = 0;
    
    for (const message of messages) {
      // 基础开销：每条消息 4 tokens
      totalTokens += 4;
      
      // 角色开销
      totalTokens += this.estimateTokensHeuristic(message.role);
      
      // 内容开销
      if (typeof message.content === 'string') {
        totalTokens += this.estimateTokensHeuristic(message.content);
      } else if (Array.isArray(message.content)) {
        for (const part of message.content) {
          if (part.type === 'text') {
            totalTokens += this.estimateTokensHeuristic(part.text);
          } else if (part.type === 'image_url') {
            // 图像 Token 估算（简化）
            totalTokens += 85; // 低分辨率图像基础开销
          }
        }
      }
      
      // 工具调用开销
      if (message.tool_calls) {
        totalTokens += message.tool_calls.length * 10;
        for (const toolCall of message.tool_calls) {
          totalTokens += this.estimateTokensHeuristic(toolCall.function.name);
          totalTokens += this.estimateTokensHeuristic(toolCall.function.arguments);
        }
      }
    }
    
    // 响应格式开销
    totalTokens += 2;
    
    return totalTokens;
  }
  
  /**
   * 估算工具定义的 Token 数量
   */
  public estimateToolsTokens(tools: AgentTool[]): number {
    let totalTokens = 0;
    
    for (const tool of tools) {
      totalTokens += this.estimateTokensHeuristic(tool.name);
      totalTokens += this.estimateTokensHeuristic(tool.description);
      totalTokens += this.estimateTokensHeuristic(JSON.stringify(tool.parameters));
    }
    
    return totalTokens;
  }
  
  /**
   * 计算可用 Token 预算
   */
  public calculateAvailableBudget(
    modelLimit: number,
    systemPrompt: string,
    messages: ChatMessage[],
    tools: AgentTool[],
    reservedTokens: number = 1000
  ): TokenBudget {
    const systemTokens = this.estimateTokensHeuristic(systemPrompt);
    const messageTokens = this.estimateMessagesTokens(messages);
    const toolTokens = this.estimateToolsTokens(tools);
    
    const usedTokens = systemTokens + messageTokens + toolTokens;
    const availableTokens = modelLimit - usedTokens - reservedTokens;
    
    return {
      modelLimit,
      used: {
        system: systemTokens,
        messages: messageTokens,
        tools: toolTokens,
        total: usedTokens
      },
      reserved: reservedTokens,
      available: Math.max(0, availableTokens),
      utilization: (usedTokens / modelLimit) * 100
    };
  }
}

export interface TokenBudget {
  modelLimit: number;
  used: {
    system: number;
    messages: number;
    tools: number;
    total: number;
  };
  reserved: number;
  available: number;
  utilization: number;
}

export interface ChatMessage {
  role: string;
  content: string | Array<{ type: string; text?: string }>;
  tool_calls?: Array<{
    id: string;
    function: { name: string; arguments: string };
  }>;
}
```

---

## 5. 上下文用量报告

### 5.1 用量报告生成

```typescript
/**
 * 上下文用量报告生成器
 */
export class ContextUsageReporter {
  /**
   * 生成用量报告
   */
  public generateReport(budget: TokenBudget, details: ContextDetails): ContextUsageReport {
    return {
      summary: this.generateSummary(budget),
      breakdown: this.generateBreakdown(budget, details),
      recommendations: this.generateRecommendations(budget),
      visualization: this.generateVisualization(budget)
    };
  }
  
  /**
   * 生成摘要
   */
  private generateSummary(budget: TokenBudget): string {
    const utilizationPercent = budget.utilization.toFixed(1);
    const availableK = (budget.available / 1000).toFixed(1);
    const usedK = (budget.used.total / 1000).toFixed(1);
    const limitK = (budget.modelLimit / 1000).toFixed(1);
    
    return `Token Usage: ${usedK}K / ${limitK}K (${utilizationPercent}%) | Available: ${availableK}K`;
  }
  
  /**
   * 生成分解
   */
  private generateBreakdown(budget: TokenBudget, details: ContextDetails): string {
    const lines: string[] = [];
    
    lines.push('### Token Usage Breakdown');
    lines.push('');
    lines.push(`| Component | Tokens | Percentage |`);
    lines.push(`|-----------|--------|------------|`);
    
    const total = budget.used.total;
    
    lines.push(
      `| System Prompt | ${budget.used.system} | ` +
      `${((budget.used.system / total) * 100).toFixed(1)}% |`
    );
    lines.push(
      `| Messages | ${budget.used.messages} | ` +
      `${((budget.used.messages / total) * 100).toFixed(1)}% |`
    );
    lines.push(
      `| Tools | ${budget.used.tools} | ` +
      `${((budget.used.tools / total) * 100).toFixed(1)}% |`
    );
    lines.push(
      `| Reserved | ${budget.reserved} | ` +
      `${((budget.reserved / budget.modelLimit) * 100).toFixed(1)}% |`
    );
    lines.push(
      `| **Available** | **${budget.available}** | ` +
      `${((budget.available / budget.modelLimit) * 100).toFixed(1)}% |`
    );
    
    lines.push('');
    
    // 详细信息
    if (details.claudeMd) {
      lines.push(`**CLAUDE.md:** ${details.claudeMd.tokens} tokens`);
    }
    
    if (details.gitStatus) {
      lines.push(`**Git Status:** ${details.gitStatus.tokens} tokens`);
    }
    
    if (details.fileContents) {
      lines.push(`**File Contents:** ${details.fileContents.tokens} tokens`);
    }
    
    return lines.join('\n');
  }
  
  /**
   * 生成建议
   */
  private generateRecommendations(budget: TokenBudget): string[] {
    const recommendations: string[] = [];
    
    if (budget.utilization > 90) {
      recommendations.push(
        '⚠️ Token 使用率超过 90%，建议减少上下文或切换到更大上下文窗口的模型'
      );
    }
    
    if (budget.utilization > 75) {
      recommendations.push(
        '💡 Token 使用率较高，注意后续请求可能会被截断'
      );
    }
    
    if (budget.available < 5000) {
      recommendations.push(
        '📉 可用 Token 较少，长输出可能会被截断'
      );
    }
    
    if (budget.used.tools > budget.modelLimit * 0.3) {
      recommendations.push(
        '🔧 工具定义占用较多 Token，考虑减少工具数量或简化描述'
      );
    }
    
    return recommendations;
  }
  
  /**
   * 生成可视化（ASCII 条形图）
   */
  private generateVisualization(budget: TokenBudget): string {
    const barWidth = 40;
    const filledWidth = Math.round((budget.utilization / 100) * barWidth);
    const emptyWidth = barWidth - filledWidth;
    
    const filled = '█'.repeat(filledWidth);
    const empty = '░'.repeat(emptyWidth);
    
    return `[${filled}${empty}] ${budget.utilization.toFixed(1)}%`;
  }
}

export interface ContextDetails {
  claudeMd?: { tokens: number; found: boolean };
  gitStatus?: { tokens: number; fileCount: number };
  fileContents?: { tokens: number; fileCount: number };
}

export interface ContextUsageReport {
  summary: string;
  breakdown: string;
  recommendations: string[];
  visualization: string;
}
```

### 5.2 用量报告示例

```
Token Usage: 45.2K / 128K (35.3%) | Available: 81.8K

[██████████████░░░░░░░░░░░░░░░░░░░░░░░░░░] 35.3%

### Token Usage Breakdown

| Component | Tokens | Percentage |
|-----------|--------|------------|
| System Prompt | 12500 | 27.7% |
| Messages | 18200 | 40.3% |
| Tools | 14500 | 32.1% |
| Reserved | 1000 | 0.8% |
| **Available** | **81800** | **63.9%** |

**CLAUDE.md:** 2340 tokens (found: true)
**Git Status:** 856 tokens (7 changed files)
**File Contents:** 15200 tokens (12 files)
```

---

## 6. 动态提示词边界

### 6.1 提示词构建流程

```
┌─────────────────────────────────────────────────────────────┐
│                    System Prompt Builder                      │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                                                       │   │
│  │  [1] Identity & Role                                  │   │
│  │  "You are DFEcrab, an AI coding assistant..."         │   │
│  │                                                       │   │
│  │  [2] Project Context (CLAUDE.md)                      │   │
│  │  "Project: MyApp - A web application..."              │   │
│  │                                                       │   │
│  │  [3] Git Status                                       │   │
│  │  "Branch: main, 7 files changed..."                   │   │
│  │                                                       │   │
│  │  [4] Core Instructions                                │   │
│  │  "Always read files before editing..."                │   │
│  │                                                       │   │
│  │  [5] Tool Definitions                                 │   │
│  │  "Available tools: list_dir, read_file..."            │   │
│  │                                                       │   │
│  │  [6] Output Format                                    │   │
│  │  "Respond with tool calls when needed..."             │   │
│  │                                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  总大小必须 <= modelContextLimit - reservedTokens             │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 动态边界控制器

```typescript
/**
 * 动态提示词边界控制器
 */
export class PromptBoundaryController {
  private readonly modelLimit: number;
  private readonly reservedTokens: number;
  private readonly estimator: TokenEstimator;
  
  constructor(options: PromptBoundaryOptions) {
    this.modelLimit = options.modelLimit;
    this.reservedTokens = options.reservedTokens ?? 1000;
    this.estimator = new TokenEstimator();
  }
  
  /**
   * 构建系统提示词，自动裁剪以适应 Token 限制
   */
  public async buildSystemPrompt(
    components: PromptComponents
  ): Promise<BuiltPrompt> {
    // 按优先级排序
    const priorities = [
      { key: 'identity' as const, priority: 1, required: true },
      { key: 'instructions' as const, priority: 2, required: true },
      { key: 'tools' as const, priority: 3, required: true },
      { key: 'projectContext' as const, priority: 4, required: false },
      { key: 'gitStatus' as const, priority: 5, required: false },
      { key: 'outputFormat' as const, priority: 6, required: false },
    ];
    
    let result = '';
    let usedTokens = 0;
    const maxTokens = this.modelLimit - this.reservedTokens;
    const truncated: string[] = [];
    
    // 首先添加必需组件
    for (const { key, required } of priorities) {
      const content = components[key];
      if (!content) continue;
      
      const tokens = this.estimator.estimateTokensHeuristic(content);
      
      if (usedTokens + tokens <= maxTokens) {
        result += content + '\n\n';
        usedTokens += tokens;
      } else if (required) {
        // 必需组件，尝试裁剪
        const remainingTokens = maxTokens - usedTokens;
        if (remainingTokens > 100) {
          const truncatedContent = this.truncateContent(content, remainingTokens);
          result += truncatedContent + '\n\n';
          usedTokens += this.estimator.estimateTokensHeuristic(truncatedContent);
          truncated.push(key);
        } else {
          throw new Error(`无法容纳必需组件: ${key}`);
        }
      } else {
        // 可选组件，跳过
        truncated.push(key);
      }
    }
    
    return {
      content: result.trim(),
      tokens: usedTokens,
      truncated,
      availableTokens: maxTokens - usedTokens
    };
  }
  
  /**
   * 裁剪内容以适应 Token 限制
   */
  private truncateContent(content: string, maxTokens: number): string {
    const tokens = this.estimator.estimateTokensHeuristic(content);
    
    if (tokens <= maxTokens) {
      return content;
    }
    
    // 按比例裁剪
    const ratio = maxTokens / tokens;
    const charLimit = Math.floor(content.length * ratio);
    
    // 尝试在句子边界裁剪
    let truncated = content.substring(0, charLimit);
    const lastSentenceEnd = Math.max(
      truncated.lastIndexOf('.\n'),
      truncated.lastIndexOf('。\n'),
      truncated.lastIndexOf('!\n'),
      truncated.lastIndexOf('?\n')
    );
    
    if (lastSentenceEnd > charLimit * 0.5) {
      truncated = truncated.substring(0, lastSentenceEnd + 1);
    }
    
    return truncated + '\n\n[...内容已裁剪以适应 Token 限制...]';
  }
  
  /**
   * 检查提示词是否在限制内
   */
  public isWithinLimit(prompt: string): boolean {
    const tokens = this.estimator.estimateTokensHeuristic(prompt);
    return tokens <= this.modelLimit - this.reservedTokens;
  }
  
  /**
   * 获取剩余可用 Token
   */
  public getRemainingTokens(prompt: string): number {
    const tokens = this.estimator.estimateTokensHeuristic(prompt);
    return this.modelLimit - this.reservedTokens - tokens;
  }
}

export interface PromptBoundaryOptions {
  modelLimit: number;
  reservedTokens?: number;
}

export interface PromptComponents {
  identity?: string;
  projectContext?: string;
  gitStatus?: string;
  instructions?: string;
  tools?: string;
  outputFormat?: string;
}

export interface BuiltPrompt {
  content: string;
  tokens: number;
  truncated: string[];
  availableTokens: number;
}
```

### 6.3 模型上下文限制配置

```typescript
/**
 * 模型上下文限制配置
 */
export const MODEL_CONTEXT_LIMITS: Record<string, number> = {
  // OpenAI
  'gpt-4o': 128000,
  'gpt-4o-mini': 128000,
  'gpt-4-turbo': 128000,
  'gpt-4': 8192,
  'gpt-3.5-turbo': 16385,
  
  // Anthropic
  'claude-3-opus': 200000,
  'claude-3-sonnet': 200000,
  'claude-3-haiku': 200000,
  
  // Google
  'gemini-pro': 32768,
  'gemini-1.5-pro': 1000000,
  
  // 本地模型
  'qwen-2.5-72b': 131072,
  'qwen-2.5-32b': 32768,
  'llama-3-70b': 8192,
};

/**
 * 获取模型上下文限制
 */
export function getModelContextLimit(modelName: string): number {
  // 精确匹配
  if (MODEL_CONTEXT_LIMITS[modelName]) {
    return MODEL_CONTEXT_LIMITS[modelName];
  }
  
  // 前缀匹配
  for (const [prefix, limit] of Object.entries(MODEL_CONTEXT_LIMITS)) {
    if (modelName.startsWith(prefix)) {
      return limit;
    }
  }
  
  // 默认值
  return 128000;
}
```

---

## 7. 上下文引擎主类

### 7.1 引擎整合

```typescript
/**
 * 上下文引擎主类
 * 整合所有组件
 */
export class ContextEngine {
  private readonly claudeMdDiscoverer: ClaudeMdDiscoverer;
  private readonly gitCache: GitStatusCache;
  private readonly tokenEstimator: TokenEstimator;
  private readonly promptBoundary: PromptBoundaryController;
  private readonly usageReporter: ContextUsageReporter;
  
  constructor(options: ContextEngineOptions) {
    this.claudeMdDiscoverer = new ClaudeMdDiscoverer();
    this.gitCache = new GitStatusCache({
      cwd: options.cwd,
      ttl: options.gitCacheTtl ?? 30000
    });
    this.tokenEstimator = new TokenEstimator();
    
    const modelLimit = options.modelName 
      ? getModelContextLimit(options.modelName)
      : options.modelLimit ?? 128000;
    
    this.promptBoundary = new PromptBoundaryController({
      modelLimit: modelLimit,
      reservedTokens: options.reservedTokens ?? 1000
    });
    this.usageReporter = new ContextUsageReporter();
  }
  
  /**
   * 构建完整的系统提示词
   */
  public async buildSystemPrompt(
    options: BuildSystemPromptOptions
  ): Promise<SystemPromptResult> {
    // 1. 发现 CLAUDE.md
    const claudeMd = await this.claudeMdDiscoverer.discover(options.cwd);
    
    // 2. 获取 Git 状态
    const gitStatus = await this.gitCache.getStatus();
    const gitBranch = await this.gitCache.getCurrentBranch();
    const gitCommits = await this.gitCache.getRecentCommits(5);
    
    // 3. 格式化 Git 状态
    const gitFormatter = new GitStatusFormatter();
    const gitStatusText = gitFormatter.formatForSystemPrompt(
      gitStatus, gitBranch, gitCommits
    );
    
    // 4. 构建提示词组件
    const components: PromptComponents = {
      identity: options.identity,
      projectContext: claudeMd.found ? claudeMd.content! : undefined,
      gitStatus: options.includeGitStatus ? gitStatusText : undefined,
      instructions: options.instructions,
      tools: options.toolsDescription,
      outputFormat: options.outputFormat
    };
    
    // 5. 构建并裁剪提示词
    const builtPrompt = await this.promptBoundary.buildSystemPrompt(components);
    
    // 6. 生成用量报告
    const budget = this.tokenEstimator.calculateAvailableBudget(
      this.promptBoundary['modelLimit'],
      builtPrompt.content,
      options.messages ?? [],
      options.tools ?? []
    );
    
    const report = this.usageReporter.generateReport(budget, {
      claudeMd: {
        tokens: claudeMd.found ? this.tokenEstimator.estimateTokensHeuristic(claudeMd.content!) : 0,
        found: claudeMd.found
      },
      gitStatus: {
        tokens: this.tokenEstimator.estimateTokensHeuristic(gitStatusText),
        fileCount: gitStatus.files.length
      }
    });
    
    return {
      systemPrompt: builtPrompt.content,
      tokens: builtPrompt.tokens,
      truncated: builtPrompt.truncated,
      budget,
      report
    };
  }
  
  /**
   * 刷新 Git 缓存
   */
  public refreshGitCache(): void {
    this.gitCache.invalidate();
  }
  
  /**
   * 获取当前 Token 预算
   */
  public getTokenBudget(messages: ChatMessage[], tools: AgentTool[]): TokenBudget {
    return this.tokenEstimator.calculateAvailableBudget(
      this.promptBoundary['modelLimit'],
      '',
      messages,
      tools
    );
  }
}

export interface ContextEngineOptions {
  cwd: string;
  modelName?: string;
  modelLimit?: number;
  gitCacheTtl?: number;
  reservedTokens?: number;
}

export interface BuildSystemPromptOptions {
  cwd: string;
  identity?: string;
  instructions?: string;
  toolsDescription?: string;
  outputFormat?: string;
  includeGitStatus?: boolean;
  messages?: ChatMessage[];
  tools?: AgentTool[];
}

export interface SystemPromptResult {
  systemPrompt: string;
  tokens: number;
  truncated: string[];
  budget: TokenBudget;
  report: ContextUsageReport;
}
```

---

## 8. 使用示例

### 8.1 基本使用

```typescript
// 初始化上下文引擎
const engine = new ContextEngine({
  cwd: '/Users/zhanghanzhi/projects/my-app',
  modelName: 'gpt-4o',
  gitCacheTtl: 30000
});

// 构建系统提示词
const result = await engine.buildSystemPrompt({
  cwd: '/Users/zhanghanzhi/projects/my-app',
  identity: 'You are DFEcrab, an expert AI coding assistant.',
  instructions: 'Always read files before editing. Use precise edits.',
  toolsDescription: toolRegistry.getAll().map(t => t.description).join('\n'),
  includeGitStatus: true,
  messages: conversationHistory,
  tools: toolRegistry.getAll()
});

console.log(result.report.summary);
console.log(result.report.visualization);

// 使用系统提示词调用 LLM
const response = await openai.chat.completions.create({
  model: 'gpt-4o',
  messages: [
    { role: 'system', content: result.systemPrompt },
    ...conversationHistory
  ],
  tools: convertToolsForLLM(toolRegistry.getAll(), permissionLevel)
});
```

### 8.2 上下文监控

```typescript
// 监控上下文使用情况
function monitorContextUsage(engine: ContextEngine, messages: ChatMessage[]) {
  const budget = engine.getTokenBudget(
    messages,
    toolRegistry.getAll()
  );
  
  if (budget.utilization > 90) {
    console.warn('⚠️ Context window nearly full!');
    console.warn(`Available: ${budget.available} tokens`);
    
    // 建议裁剪策略
    console.warn('Consider:');
    console.warn('1. Truncating older messages');
    console.warn('2. Reducing tool descriptions');
    console.warn('3. Switching to a model with larger context window');
  }
  
  return budget;
}
```

---

## 附录

### A. Token 估算系数参考

| 内容类型 | 系数 | 说明 |
|---------|------|------|
| 英文单词 | 1.3 tokens/word | 平均英文单词长度 |
| 中文字符 | 1.5 tokens/char | 中文分词特性 |
| 代码字符 | 0.8 tokens/char | 代码压缩效应 |
| 标点符号 | 0.5 tokens/char | 常见标点合并 |
| 换行符 | 1.2 tokens/newline | 结构标记 |
| 空白字符 | 0.3 tokens/char | 空白压缩 |

### B. 模型上下文限制

| 模型 | 上下文限制 | 可用输出 |
|------|-----------|---------|
| GPT-4o | 128,000 | ~4,096 |
| GPT-4 Turbo | 128,000 | ~4,096 |
| Claude 3 | 200,000 | ~4,096 |
| Gemini 1.5 Pro | 1,000,000 | ~8,192 |
| Qwen 2.5 72B | 131,072 | ~8,192 |

### C. 相关文档

- [权限系统设计文档](./PERMISSION_SYSTEM.md)
- [工具系统设计文档](./TOOL_SYSTEM.md)
- [CLAUDE.md 编写指南](../03-开发指南/CLAUDE_MD_GUIDE.md)
