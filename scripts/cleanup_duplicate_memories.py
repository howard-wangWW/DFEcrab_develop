#!/usr/bin/env python3
"""
清理重复记忆文件
用于清理 data/shared_memory/DAILY/*.md 文件中的重复行
"""

import hashlib
from pathlib import Path

def cleanup_daily_file(file_path: Path):
    """清理文件中的重复行"""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    seen = set()
    unique_lines = []
    
    for line in lines:
        line_hash = hashlib.md5(line.strip().encode()).hexdigest()
        if line_hash not in seen:
            seen.add(line_hash)
            unique_lines.append(line)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(unique_lines)
    
    return len(lines) - len(unique_lines)

def backup_daily_files():
    """备份每日记忆文件"""
    daily_dir = Path(__file__).parent.parent / "data" / "shared_memory" / "DAILY"
    if daily_dir.exists():
        for file in daily_dir.glob("*.md"):
            backup_file = file.with_suffix(file.suffix + ".bak")
            with open(file, 'r', encoding='utf-8') as src:
                with open(backup_file, 'w', encoding='utf-8') as dst:
                    dst.write(src.read())
            print(f"备份 {file.name} -> {backup_file.name}")

def main():
    """主函数"""
    print("开始清理重复记忆文件...")
    
    # 备份原文件
    print("\n1. 备份原文件...")
    backup_daily_files()
    
    # 清理所有每日记忆文件
    daily_dir = Path(__file__).parent.parent / "data" / "shared_memory" / "DAILY"
    total_removed = 0
    
    print("\n2. 清理重复行...")
    for file in daily_dir.glob("*.md"):
        if file.name.endswith(".bak"):
            continue
        removed = cleanup_daily_file(file)
        total_removed += removed
        print(f"  清理 {file.name}: 移除 {removed} 行重复内容")
    
    print(f"\n清理完成！总共移除 {total_removed} 行重复内容")
    print(f"备份文件保存在 {daily_dir}/*.md.bak")

if __name__ == "__main__":
    main()