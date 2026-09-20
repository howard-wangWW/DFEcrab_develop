"""CLI 显示层 - 任务状态可视化"""

import sys
import time
from typing import Optional, List
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.style import Style
from rich.text import Text

from .models import Task, TaskPlan, TaskStatus


class TaskDisplay:
    """
    任务显示组件
    
    提供 CLI 动画和状态更新
    """

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    def show_plan(self, plan: TaskPlan) -> None:
        """显示任务计划概览"""
        self.console.print(
            Panel(
                f"[bold blue]{plan.goal}[/bold blue]",
                title="📋 任务计划",
                border_style="blue",
            )
        )

        table = Table(show_header=True, header_style="bold")
        table.add_column("状态", style="dim", width=4)
        table.add_column("任务", style="bold")
        table.add_column("描述", overflow="ellipsis")

        for task in plan.tasks:
            table.add_row(
                task.status.icon,
                task.name,
                task.description[:50] + "..." if len(task.description) > 50 else task.description,
            )

        self.console.print(table)
        self.console.print()

    def create_execution_view(self, plan: TaskPlan) -> Table:
        """创建执行视图表格"""
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("状态", style="dim", width=4)
        table.add_column("任务", style="bold", width=40)
        table.add_column("进度/结果", overflow="ellipsis")

        for task in plan.tasks:
            status_text = Text(task.status.icon, style=task.status.color)
            
            if task.status == TaskStatus.RUNNING:
                result_text = Text("执行中...", style="blue")
            elif task.status == TaskStatus.COMPLETED:
                result_text = Text("完成", style="green")
            elif task.status == TaskStatus.FAILED:
                result_text = Text(task.error or "失败", style="red")
            else:
                result_text = Text("等待中", style="dim")

            table.add_row(status_text, task.name, result_text)

        return table

    def create_progress_bar(self, plan: TaskPlan) -> str:
        """创建进度条"""
        progress = plan.progress
        bar_width = 30
        filled = int(bar_width * progress)
        bar = "█" * filled + "░" * (bar_width - filled)
        percent = f"{progress * 100:.0f}%"
        return f"[{bar}] {percent}"

    def live_execute(
        self,
        plan: TaskPlan,
        on_start: Optional[callable] = None,
        on_complete: Optional[callable] = None,
    ) -> TaskPlan:
        """
        实时显示执行过程
        
        Args:
            plan: 任务计划
            on_start: 开始执行前的回调
            on_complete: 执行完成后的回调
            
        Returns:
            TaskPlan: 执行后的计划
        """
        def generate_view():
            lines = []
            lines.append(f"[bold]目标:[/bold] {plan.goal}")
            lines.append(f"[bold]进度:[/bold] {self.create_progress_bar(plan)}")
            lines.append("")
            lines.append("[bold]任务状态:[/bold]")
            
            for task in plan.tasks:
                status_icon = task.status.icon
                status_style = task.status.color
                
                if task.status == TaskStatus.RUNNING:
                    status_text = f"[{status_style}]{status_icon} {task.name}[/] [dim](执行中...)[/]"
                elif task.status == TaskStatus.COMPLETED:
                    status_text = f"[{status_style}]{status_icon} {task.name}[/]"
                    if task.result:
                        result = str(task.result)[:50]
                        status_text += f" [dim]→ {result}[/]"
                elif task.status == TaskStatus.FAILED:
                    status_text = f"[{status_style}]{status_icon} {task.name}[/] [red]{task.error or '失败'}[/]"
                else:
                    status_text = f"[{status_style}]{status_icon} {task.name}[/]"
                
                lines.append(f"  {status_text}")
            
            return "\n".join(lines)

        with Live(generate_view(), console=self.console, refresh_per_second=10) as live:
            def task_callback(task: Task):
                live.update(generate_view())

            if on_start:
                on_start(plan)

            # 返回更新后的 plan（由调用者实际执行任务）
            # 这里只是显示框架
            pass

        return plan

    def show_result(self, plan: TaskPlan) -> None:
        """显示最终执行结果"""
        summary = plan.status_summary
        
        self.console.print()
        self.console.print(
            Panel(
                f"[bold]执行完成[/bold]\n\n"
                f"✅ 成功：{summary[TaskStatus.COMPLETED]}\n"
                f"❌ 失败：{summary[TaskStatus.FAILED]}\n"
                f"⏭️ 跳过：{summary[TaskStatus.SKIPPED]}",
                title="📊 执行摘要",
                border_style="green" if summary[TaskStatus.FAILED] == 0 else "yellow",
            )
        )

        # 显示各任务结果
        for task in plan.tasks:
            if task.status == TaskStatus.COMPLETED and task.result:
                self.console.print(
                    Panel(
                        str(task.result),
                        title=f"✅ {task.name}",
                        border_style="green",
                        style="dim",
                    )
                )
            elif task.status == TaskStatus.FAILED:
                self.console.print(
                    Panel(
                        task.error or "未知错误",
                        title=f"❌ {task.name}",
                        border_style="red",
                        style="dim",
                    )
                )

    def show_message(self, message: str, style: str = "dim") -> None:
        """显示临时消息"""
        self.console.print(f"[{style}]{message}[/{style}]")

    def show_error(self, error: str) -> None:
        """显示错误"""
        self.console.print(f"[bold red]错误：[/bold red] {error}")
