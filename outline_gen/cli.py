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
from .book_rewriter import BookRewriter
from .usage_tracker import global_usage_tracker


console = Console()


def _generate_outline_for_pdf(
    pdf_path: Path,
    depth: int,
    output: Path,
    fmt: str,
    model: str,
    api_key: str,
) -> None:
    """Core routine to generate outline for a single PDF."""
    # Display configuration
    console.print(Panel.fit(
        f"[bold]PDF文件:[/bold] {pdf_path}\n"
        f"[bold]递归层级:[/bold] {depth}\n"
        f"[bold]输出文件:[/bold] {output}\n"
        f"[bold]输出格式:[/bold] {fmt}\n"
        f"[bold]使用模型:[/bold] {model}",
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
        engine.save_outline(str(output), format=fmt)

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


def _print_usage_summary(config: Config, title: str = "LLM 调用统计") -> None:
    """Print a rich summary of token usage and estimated cost."""
    summary = global_usage_tracker.summary()
    if not summary:
        return

    lines = []
    for model, usage in summary.items():
        pricing = config.get_model_pricing(model)
        input_rate = pricing.get("input_per_1k")
        output_rate = pricing.get("output_per_1k")
        currency = pricing.get("currency", "CNY")

        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)

        cost_str = "价格未配置"
        if input_rate is not None and output_rate is not None:
            total_cost = (prompt_tokens / 1000.0) * float(input_rate) + (
                completion_tokens / 1000.0
            ) * float(output_rate)
            cost_str = f"{total_cost:.4f} {currency}"

        lines.append(
            f"模型: {model}\n"
            f"  输入 tokens: {prompt_tokens}\n"
            f"  输出 tokens: {completion_tokens}\n"
            f"  总 tokens: {total_tokens}\n"
            f"  预估费用: {cost_str}"
        )

    text = "\n\n".join(lines)
    console.print(
        Panel(
            text,
            title=f"[bold blue]{title}[/bold blue]",
            border_style="blue",
        )
    )


@click.group()
def main():
    """outline-gen 命令行工具。"""
    pass


@main.command("init-config")
def init_config_cmd():
    """创建默认配置文件 (~/.outline-gen/config.yaml)。"""
    config = Config()
    config_path = config.create_default_config()
    console.print(f"[green]✓[/green] 已创建配置文件: {config_path}")
    console.print("[yellow]请编辑配置文件并添加您的 API 密钥[/yellow]")


@main.command("outline")
@click.argument('pdf_path', type=click.Path(exists=True))
@click.option(
    '--depth', '-d',
    type=int,
    default=None,
    help='递归层级深度 (默认: 配置中的 default_depth, 默认为2)'
)
@click.option(
    '--output', '-o',
    type=click.Path(),
    default=None,
    help='输出文件路径 (默认: 与PDF同名.outline.txt)'
)
@click.option(
    '--format', '-f',
    type=click.Choice(['txt', 'json', 'md'], case_sensitive=False),
    default=None,
    help='输出格式 (默认: 配置中的 output_format, 默认为 txt)'
)
@click.option(
    '--model', '-m',
    type=str,
    default=None,
    help='使用的模型 (默认: 配置中的 model, 默认为 qwen-turbo)'
)
@click.option(
    '--api-key',
    type=str,
    default=None,
    help='Dashscope API密钥 (可选，优先使用环境变量/配置文件)'
)
def outline_cmd(pdf_path, depth, output, format, model, api_key):
    """为指定 PDF 生成递归大纲。"""
    config = Config()

    # 注意：depth=0 也应被视为有效值，因此仅在 depth 为 None 时使用默认配置
    depth = config.get_default_depth() if depth is None else depth
    fmt = (format or config.get_output_format()).lower()
    api_key = api_key or config.get_api_key()
    model = model or config.get_model()

    if not api_key:
        console.print("[red]错误：[/red] 未找到 Dashscope API 密钥", style="bold red")
        console.print("\n请通过以下方式之一设置 API 密钥：")
        console.print("1. 设置环境变量: export DASHSCOPE_API_KEY=your-key")
        console.print("2. 运行 outline-gen init-config 创建配置文件")
        sys.exit(1)

    pdf_path = Path(pdf_path)

    if output is None:
        # Default: sibling .outline.<fmt> next to the PDF
        output_path = pdf_path.with_suffix(f'.outline.{fmt}')
    else:
        output_path = Path(output)

    _generate_outline_for_pdf(
        pdf_path=pdf_path,
        depth=depth,
        output=output_path,
        fmt=fmt,
        model=model,
        api_key=api_key,
    )

    # Print usage & cost summary for this run
    _print_usage_summary(config, title="LLM 调用统计（大纲生成）")
    global_usage_tracker.reset()


@main.command("book")
@click.argument('book_name', type=str)
@click.option(
    '--data-root',
    type=click.Path(),
    default=None,
    help='数据根目录 (默认: 配置中的 data_root, 默认为 ./data)'
)
@click.option(
    '--depth', '-d',
    type=int,
    default=None,
    help='递归层级深度 (默认: 配置中的 default_depth, 默认为2)'
)
@click.option(
    '--model', '-m',
    type=str,
    default=None,
    help='使用的模型 (默认: 配置中的 model)'
)
@click.option(
    '--api-key',
    type=str,
    default=None,
    help='Dashscope API密钥 (可选，优先使用环境变量/配置文件)'
)
def book_cmd(book_name, data_root, depth, model, api_key):
    """
    以 data/<book_name>/<book_name>.pdf 为输入，自动完成：

    1. 生成 <book_name>.outline.txt
    2. 调用大模型重写为精简版中文正文
    3. 在 data/<book_name>/<book_name>/ 下生成 MkDocs (material 主题) 项目
    """
    config = Config()

    depth = config.get_default_depth() if depth is None else depth
    api_key = api_key or config.get_api_key()
    model = model or config.get_model()

    if not api_key:
        console.print("[red]错误：[/red] 未找到 Dashscope API 密钥", style="bold red")
        console.print("\n请通过以下方式之一设置 API 密钥：")
        console.print("1. 设置环境变量: export DASHSCOPE_API_KEY=your-key")
        console.print("2. 运行 outline-gen init-config 创建配置文件")
        sys.exit(1)

    data_root_path = Path(data_root) if data_root else config.get_data_root()
    book_dir = data_root_path / book_name
    pdf_path = book_dir / f"{book_name}.pdf"
    outline_path = book_dir / f"{book_name}.outline.txt"
    output_root = book_dir / book_name

    if not pdf_path.exists():
        console.print(
            f"[red]错误：[/red] 找不到 PDF 文件: {pdf_path}\n"
            f"请确保路径为 data_root/book_name/book_name.pdf",
            style="bold red",
        )
        sys.exit(1)

    console.print(Panel.fit(
        f"[bold]书名(文件夹):[/bold] {book_name}\n"
        f"[bold]数据根目录:[/bold] {data_root_path}\n"
        f"[bold]PDF路径:[/bold] {pdf_path}\n"
        f"[bold]大纲输出:[/bold] {outline_path}\n"
        f"[bold]重写输出(MkDocs):[/bold] {output_root}\n"
        f"[bold]递归层级:[/bold] {depth}\n"
        f"[bold]书籍类型:[/bold] 自动推断（基于大纲）\n"
        f"[bold]使用模型:[/bold] {model}",
        title="Book 模式配置",
        border_style="magenta",
    ))

    # 1) Generate outline.txt under data/<book_name>/ (with optional overwrite prompt)
    if outline_path.exists():
        console.print(
            f"[yellow]检测到已存在大纲文件:[/yellow] {outline_path}\n"
            "[yellow]是否重新生成并覆盖该文件？[/yellow]"
        )
        if click.confirm("重新生成大纲？", default=False):
            _generate_outline_for_pdf(
                pdf_path=pdf_path,
                depth=depth,
                output=outline_path,
                fmt="txt",
                model=model,
                api_key=api_key,
            )
        else:
            console.print("[green]将跳过大纲生成，直接使用现有大纲文件。[/green]")
    else:
        _generate_outline_for_pdf(
            pdf_path=pdf_path,
            depth=depth,
            output=outline_path,
            fmt="txt",
            model=model,
            api_key=api_key,
        )

    # 2) Rewrite book into MkDocs project using BookRewriter
    console.print("\n[bold green]开始使用大模型重写全书...[/bold green]\n")
    rewriter = BookRewriter(
        pdf_path=str(pdf_path),
        outline_txt_path=str(outline_path),
        output_root=str(output_root),
        api_key=api_key,
        model=model,
    )
    rewriter.rewrite_book()
    console.print(f"\n[bold green]✓ 全书重写完成！[/bold green]")
    console.print(f"[blue]MkDocs 项目路径: {output_root}[/blue]")

    # Print combined usage & cost summary for outline + rewrite
    _print_usage_summary(config, title="LLM 调用统计（大纲生成 + 全书重写）")
    global_usage_tracker.reset()


if __name__ == '__main__':
    main()
