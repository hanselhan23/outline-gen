"""Command-line interface for outline-gen."""

import click
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree

from .config import Config
from .recursive_engine import RecursiveEngine, OutlineNode
from .pdf_processor import PDFProcessor


console = Console()


@click.command()
@click.argument('pdf_path', type=click.Path(exists=True))
@click.option(
    '--depth', '-d',
    type=int,
    default=None,
    help='递归层级深度 (默认: 2)'
)
@click.option(
    '--output', '-o',
    type=click.Path(),
    default=None,
    help='输出文件路径 (默认: 与PDF同名.txt)'
)
@click.option(
    '--format', '-f',
    type=click.Choice(['txt', 'json', 'md'], case_sensitive=False),
    default=None,
    help='输出格式 (默认: txt)'
)
@click.option(
    '--model', '-m',
    type=str,
    default=None,
    help='使用的模型 (默认: qwen-turbo)'
)
@click.option(
    '--api-key',
    type=str,
    default=None,
    help='Dashscope API密钥 (可选，优先使用环境变量)'
)
@click.option(
    '--init-config',
    is_flag=True,
    help='创建默认配置文件'
)
def main(pdf_path, depth, output, format, model, api_key, init_config):
    """
    为PDF书籍递归生成详细大纲。

    PDF_PATH: PDF文件路径
    """
    # Handle config initialization
    config = Config()

    if init_config:
        config_path = config.create_default_config()
        console.print(f"[green]✓[/green] 已创建配置文件: {config_path}")
        console.print("[yellow]请编辑配置文件并添加您的 API 密钥[/yellow]")
        return

    # Load configuration
    depth = depth or config.get_default_depth()
    format = format or config.get_output_format()
    api_key = api_key or config.get_api_key()

    if not api_key:
        console.print("[red]错误：[/red] 未找到 Dashscope API 密钥", style="bold red")
        console.print("\n请通过以下方式之一设置 API 密钥：")
        console.print("1. 设置环境变量: export DASHSCOPE_API_KEY=your-key")
        console.print("2. 运行 outline-gen --init-config 创建配置文件")
        sys.exit(1)

    pdf_path = Path(pdf_path)

    # Determine output path
    if output is None:
        output = pdf_path.with_suffix(f'.outline.{format}')
    else:
        output = Path(output)

    # Display configuration
    console.print(Panel.fit(
        f"[bold]PDF文件:[/bold] {pdf_path}\n"
        f"[bold]递归层级:[/bold] {depth}\n"
        f"[bold]输出文件:[/bold] {output}\n"
        f"[bold]输出格式:[/bold] {format}\n"
        f"[bold]使用模型:[/bold] {model or config.get_model()}",
        title="配置信息",
        border_style="blue"
    ))

    # Verify PDF has bookmarks
    try:
        with PDFProcessor(pdf_path) as processor:
            bookmarks = processor.extract_bookmarks()
            page_count = processor.get_page_count()
            is_scanned = processor.is_scanned_pdf()

            console.print(f"\n[blue]ℹ[/blue] PDF信息:")
            console.print(f"  页数: {page_count}")
            console.print(f"  书签数: {len(bookmarks)}")
            console.print(f"  PDF类型: {'扫描版 (需要OCR)' if is_scanned else '文本版'}")

            if bookmarks:
                console.print(f"  最小层级: {min(b.level for b in bookmarks)}")
                console.print(f"  最大层级: {max(b.level for b in bookmarks)}")

            # Check if tesseract is available for scanned PDFs
            if is_scanned:
                try:
                    import pytesseract
                    pytesseract.get_tesseract_version()
                    console.print("[green]  ✓ Tesseract OCR 已安装[/green]")
                except Exception:
                    console.print("[yellow]  ⚠ 警告: Tesseract OCR 未安装，无法处理扫描版 PDF[/yellow]")
                    console.print("[yellow]    请安装: sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim[/yellow]")
                    sys.exit(1)

    except Exception as e:
        console.print(f"[red]错误：[/red] 无法读取PDF文件: {e}", style="bold red")
        sys.exit(1)

    # Initialize engine
    console.print("\n[bold green]开始生成大纲...[/bold green]\n")

    try:
        engine = RecursiveEngine(
            pdf_path=str(pdf_path),
            max_depth=depth,
            api_key=api_key
        )

        # Hierarchical real-time progress logging (no Live, pure scroll output)
        def progress_callback(action: str, node: OutlineNode):
            """Handle progress updates with hierarchical, readable logging."""
            level = max(node.level, 0)
            indent = "  " * level
            level_tag = f"[cyan]层级 {level}[/cyan]"
            # Page range used for this level's outline generation
            if getattr(node, "start_page", None) and getattr(node, "end_page", None):
                if node.start_page == node.end_page:
                    range_info = f"第{node.start_page}页"
                else:
                    range_info = f"第{node.start_page}–{node.end_page}页"
            else:
                range_info = f"第{node.page}页"

            if action == "generating":
                # Extra spacing between顶层章节 for更清晰
                if level == 0:
                    console.print()
                console.print(
                    f"{level_tag} [yellow]⏳ 正在生成[/yellow] "
                    f"{indent}[bold]{node.title}[/bold] "
                    f"[dim](基于 {range_info})[/dim]"
                )
            elif action == "generated":
                console.print(
                    f"{level_tag} [green]✓ 已完成[/green] "
                    f"{indent}[bold]{node.title}[/bold] "
                    f"[dim](基于 {range_info})[/dim]"
                )
                if node.children:
                    child_indent = "  " * (level + 1)
                    total = len(node.children)
                    for idx, child in enumerate(node.children):
                        branch = "└─" if idx == total - 1 else "├─"
                        console.print(
                            f"{child_indent}{branch} [bold]{child.title}[/bold] "
                            f"[dim](第{child.page}页, 层级 {child.level})[/dim]"
                        )

                # After each节点完成, 输出当前树状大纲快照，方便实时查看整体结构
                if engine.outline_tree:
                    snapshot_tree = Tree("📚 当前大纲进度")

                    def add_nodes_to_snapshot(parent_tree, nodes):
                        for n in nodes:
                            label = f"{n.title} [dim](第{n.page}页)[/dim]"
                            branch = parent_tree.add(label)
                            if n.children:
                                add_nodes_to_snapshot(branch, n.children)

                    add_nodes_to_snapshot(snapshot_tree, engine.outline_tree)
                    console.print("\n[dim]当前树状大纲（部分进度）：[/dim]")
                    console.print(snapshot_tree)

            elif action.startswith("error:"):
                error_msg = action.split(":", 1)[1]
                console.print(
                    f"{level_tag} [red]✗ 出错[/red] "
                    f"{indent}[bold]{node.title}[/bold] "
                    f"[dim](基于 {range_info})[/dim]: {error_msg}"
                )

        # Generate outline with real-time progress logs
        outline_tree = engine.generate_outline(progress_callback=progress_callback)

        if not outline_tree:
            console.print("[yellow]警告：[/yellow] 未能生成大纲", style="bold yellow")
            sys.exit(1)

        # Save outline
        engine.save_outline(str(output), format=format)

        # Display result
        console.print(f"\n[bold green]✓ 大纲生成完成！[/bold green]")
        console.print(f"输出文件: [blue]{output}[/blue]")

        # Display outline preview
        console.print("\n[bold]大纲预览:[/bold]")
        tree = Tree("📚 " + pdf_path.name)

        def add_nodes_to_tree(parent_tree, nodes):
            for node in nodes:
                branch = parent_tree.add(f"{node.title} [dim](第{node.page}页)[/dim]")
                if node.children:
                    add_nodes_to_tree(branch, node.children)

        add_nodes_to_tree(tree, outline_tree)
        console.print(tree)

        # Cleanup
        engine.cleanup()
        console.print(f"\n[dim]已清理 {len(engine.temp_files)} 个临时文件[/dim]")

    except KeyboardInterrupt:
        console.print("\n[yellow]已取消操作[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[bold red]错误：[/bold red] {str(e)}")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)


if __name__ == '__main__':
    main()
