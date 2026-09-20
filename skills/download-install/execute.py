"""
下载并安装技能工具
"""

import os
import shutil
import zipfile
import urllib.request
from pathlib import Path
from typing import Optional

from src.agentscope_compat import ServiceResponse, ServiceExecStatus


def download_file(url: str, output_path: str) -> ServiceResponse:
    """
    下载网络文件到指定路径

    Args:
        url: 文件 URL
        output_path: 输出文件路径

    Returns:
        下载结果
    """
    try:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        urllib.request.urlretrieve(url, output_path)
        return ServiceResponse(
            status=ServiceExecStatus.SUCCESS,
            content=f"文件已下载到: {output_path}"
        )
    except Exception as e:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"下载失败: {str(e)}"
        )


def unzip_file(zip_path: str, extract_to: str) -> ServiceResponse:
    """
    解压 ZIP 文件

    Args:
        zip_path: ZIP 文件路径
        extract_to: 解压目标目录

    Returns:
        解压结果
    """
    try:
        zip_file = Path(zip_path)
        extract_dir = Path(extract_to)

        if not zip_file.exists():
            return ServiceResponse(
                status=ServiceExecStatus.ERROR,
                content=f"ZIP 文件不存在: {zip_path}"
            )

        extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)

        return ServiceResponse(
            status=ServiceExecStatus.SUCCESS,
            content=f"已解压到: {extract_to}"
        )
    except Exception as e:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"解压失败: {str(e)}"
        )


def set_env_var(key: str, value: str) -> ServiceResponse:
    """
    设置环境变量（仅当前进程）

    Args:
        key: 环境变量名
        value: 环境变量值

    Returns:
        设置结果
    """
    try:
        os.environ[key] = value
        return ServiceResponse(
            status=ServiceExecStatus.SUCCESS,
            content=f"已设置环境变量: {key}"
        )
    except Exception as e:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"设置环境变量失败: {str(e)}"
        )


def install_skill_from_zip(zip_url: str, skill_name: str, env_vars: Optional[dict] = None) -> ServiceResponse:
    """
    一键下载、安装技能（包含设置环境变量）

    Args:
        zip_url: 技能 ZIP 包的 URL
        skill_name: 技能名称（将作为目录名）
        env_vars: 需要设置的环境变量字典，格式为 {"KEY": "value"}

    Returns:
        安装结果
    """
    try:
        project_root = Path(__file__).parent.parent.parent
        skills_dir = project_root / "skills"
        skill_dir = skills_dir / skill_name
        zip_path = skills_dir / f"{skill_name}.zip"

        response = download_file(zip_url, str(zip_path))
        if response.status != ServiceExecStatus.SUCCESS:
            return response

        if skill_dir.exists():
            shutil.rmtree(skill_dir)

        response = unzip_file(str(zip_path), str(skills_dir))
        if response.status != ServiceExecStatus.SUCCESS:
            return response

        extracted_dir = skills_dir / skill_name
        if not extracted_dir.exists():
            for item in skills_dir.iterdir():
                if item.is_dir() and item.name.startswith(skill_name):
                    item.rename(skill_dir)
                    break

        if env_vars:
            for key, value in env_vars.items():
                os.environ[key] = value

        return ServiceResponse(
            status=ServiceExecStatus.SUCCESS,
            content=f"技能 {skill_name} 安装成功！"
        )
    except Exception as e:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"安装失败: {str(e)}"
        )


def execute(action: str, **kwargs) -> ServiceResponse:
    """
    主入口函数

    Args:
        action: 操作类型 (download, unzip, set_env, install_skill)
        **kwargs: 操作参数

    Returns:
        操作结果
    """
    if action == "download":
        return download_file(kwargs.get("url"), kwargs.get("output_path"))
    elif action == "unzip":
        return unzip_file(kwargs.get("zip_path"), kwargs.get("extract_to"))
    elif action == "set_env":
        return set_env_var(kwargs.get("key"), kwargs.get("value"))
    elif action == "install_skill":
        return install_skill_from_zip(
            kwargs.get("zip_url"),
            kwargs.get("skill_name"),
            kwargs.get("env_vars")
        )
    else:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"未知操作: {action}"
        )