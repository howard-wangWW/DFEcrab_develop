---
name: download-install
description: 下载网络文件、解压ZIP包、安装技能、设置环境变量
version: 1.0.0
author: DFEcrab
triggers:
  - 下载
  - 安装技能
  - 设置环境变量
  - unzip
  - download
---

# download-install

下载网络文件、解压ZIP包、安装技能、设置环境变量的工具集。

## 功能

1. **download** - 下载网络文件到本地
2. **unzip** - 解压 ZIP 文件
3. **set_env** - 设置环境变量（仅当前进程）
4. **install_skill** - 一键下载并安装技能

## 使用示例

```
下载文件：
action=download, url="https://example.com/file.zip", output_path="/tmp/file.zip"

解压文件：
action=unzip, zip_path="/tmp/file.zip", extract_to="/tmp/"

设置环境变量：
action=set_env, key="MY_TOKEN", value="secret123"

一键安装技能：
action=install_skill, zip_url="https://example.com/skill.zip", skill_name="my-skill", env_vars={"TOKEN": "xxx"}
```