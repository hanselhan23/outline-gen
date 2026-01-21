"""Workspace-based CLI for outline-gen."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List, Optional

import click
from rich.console import Console
from rich.panel import Panel

from .config import Config
from .llm_client import LLMClient
from .pdf_processor import PDFProcessor
from .site_builder import SiteBuildConfig, build_site
from .tag_template import (
    list_template_types,
    load_tag_template,
    resolve_tag_template_path,
    write_default_tag_template,
)
from .workspace import (
    OutlineNode,
    Workspace,
    build_nodes_from_bookmarks,
    collect_leaf_nodes,
    compute_subtree_stats,
    find_node,
    find_parent_and_index,
    load_workspace,
    recompute_ranges,
    save_workspace,
)
from .node_paths import build_node_dir_map, resolve_leaf_path


console = Console()


def _resolve_data_root(data_root: Optional[str]) -> Path:
    if data_root:
        return Path(data_root)
    return Config().get_data_root()


def _copy_pdf_to_workspace(src: Path, dest: Path, force: bool) -> None:
    if dest.exists():
        if not force:
            raise FileExistsError(f"PDF already exists: {dest}")
        dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _load_workspace_or_exit(book_id: str, data_root: Path) -> Workspace:
    try:
        return load_workspace(book_id, data_root)
    except FileNotFoundError as exc:
        console.print(f"[red]错误：[/red] {exc}")
        raise SystemExit(1)


def _build_llm_client(cfg: Config, api_key: Optional[str], model: Optional[str]) -> LLMClient:
    api_key = api_key or cfg.get_api_key()
    if not api_key:
        console.print("[red]错误：[/red] 未找到 Dashscope API 密钥")
        raise SystemExit(1)
    return LLMClient(api_key=api_key, model=model or cfg.get_model())


def _render_tree(nodes: List[OutlineNode]) -> List[str]:
    stats = compute_subtree_stats(nodes)
    lines: List[str] = []

    def fmt_node(node: OutlineNode) -> str:
        info = f"pp {node.start_page}-{node.end_page}"
        if node.children:
            info += f", subtree {stats[node.id]['node_count']} nodes, leaves {stats[node.id]['leaf_count']}"
        else:
            info += f", pages {stats[node.id]['page_count']}"
        return f"[{node.id}] {node.title} ({info})"

    def walk(node: OutlineNode, prefix: str, is_last: bool) -> None:
        branch = "└─ " if is_last else "├─ "
        lines.append(f"{prefix}{branch}{fmt_node(node)}")
        child_prefix = f"{prefix}{'   ' if is_last else '│  '}"
        for idx, child in enumerate(node.children):
            walk(child, child_prefix, idx == len(node.children) - 1)

    for idx, root in enumerate(nodes):
        walk(root, "", idx == len(nodes) - 1)

    return lines


def _render_summary_markdown(node: OutlineNode, summary: str) -> str:
    return "\n".join(
        [
            f"# {node.title}",
            "",
            f"页码范围: {node.start_page}-{node.end_page}",
            "",
            "## 总结",
            summary.strip(),
            "",
        ]
    )


def _render_tag_markdown(node: OutlineNode, template_name: str, tag_notes: str) -> str:
    return "\n".join(
        [
            f"# {node.title}",
            "",
            f"页码范围: {node.start_page}-{node.end_page}",
            f"标签模板: {template_name}",
            "",
            tag_notes.strip(),
            "",
        ]
    )


def _prepare_output_dir(path_value: Optional[str], fallback: Path) -> Path:
    output_dir = Path(path_value) if path_value else fallback
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _resolve_leaf_output_path(output_dir: Path, path_map: Dict[int, List[str]], leaf: OutlineNode) -> Path:
    target_path = resolve_leaf_path(output_dir, path_map, leaf)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    return target_path


def _write_markdown(path: Path, content: str, overwrite: bool) -> bool:
    if path.exists() and not overwrite:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def _resolve_template_source(template_path: Optional[str], template_type: Optional[str]) -> Path:
    if template_path and template_type:
        console.print("[red]错误：[/red] --template 与 --template-type 只能选一个。")
        raise SystemExit(1)
    if template_path:
        return Path(template_path)
    if template_type:
        try:
            return resolve_tag_template_path(template_type)
        except ValueError as exc:
            types = ", ".join(list_template_types())
            console.print(f"[red]错误：[/red] {exc}，可选类型: {types}")
            raise SystemExit(1)
    console.print("[red]错误：[/red] 请提供 --template 或 --template-type。")
    raise SystemExit(1)


@click.group()
def main() -> None:
    """outline-gen workspace CLI."""


@main.command("init-config")
def init_config_cmd() -> None:
    """Create default config file (~/.outline-gen/config.yaml)."""
    config = Config()
    path = config.create_default_config()
    console.print(f"[green]✓[/green] 已创建配置文件: {path}")
    console.print("[yellow]请编辑配置文件并添加您的 API 密钥[/yellow]")


@main.command("init")
@click.argument("book_id", type=str)
@click.option("--pdf", "pdf_path", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--title", type=str, default=None, help="Root node title (default: book_id).")
@click.option("--data-root", type=click.Path(), default=None)
@click.option("--force", is_flag=True, help="Overwrite existing workspace PDF/outline.")
def init_cmd(book_id: str, pdf_path: str, title: Optional[str], data_root: Optional[str], force: bool) -> None:
    """Initialize a workspace under data/<book_id> with a single root node."""
    data_root_path = _resolve_data_root(data_root)
    book_dir = data_root_path / book_id
    pdf_dest = book_dir / "book.pdf"
    outline_path = book_dir / "outline.json"

    try:
        _copy_pdf_to_workspace(Path(pdf_path), pdf_dest, force=force)
    except FileExistsError as exc:
        console.print(f"[red]错误：[/red] {exc}")
        console.print("使用 --force 进行覆盖。")
        raise SystemExit(1)

    with PDFProcessor(str(pdf_dest)) as processor:
        total_pages = processor.get_page_count()
        bookmarks = processor.extract_bookmarks()

    if bookmarks:
        nodes, next_id = build_nodes_from_bookmarks(bookmarks, total_pages, next_id_start=1)
    else:
        root = OutlineNode(
            id=1,
            title=title or book_id,
            start_page=1,
            end_page=max(total_pages, 1),
            children=[],
        )
        nodes = [root]
        next_id = 2

    workspace = Workspace(
        book_id=book_id,
        root_dir=book_dir,
        pdf_path=pdf_dest,
        nodes=nodes,
        next_id=next_id,
    )
    save_workspace(workspace, force=force)

    console.print(
        Panel.fit(
            f"[bold]Book ID:[/bold] {book_id}\n"
            f"[bold]PDF:[/bold] {pdf_dest}\n"
            f"[bold]Outline:[/bold] {outline_path}\n"
            f"[bold]Outline TXT:[/bold] {book_dir / 'outline.txt'}\n"
            f"[bold]总页数:[/bold] {total_pages}",
            title="Workspace 初始化完成",
            border_style="green",
        )
    )


@main.command("ls")
@click.argument("book_id", type=str)
@click.option("--data-root", type=click.Path(), default=None)
def ls_cmd(book_id: str, data_root: Optional[str]) -> None:
    """List outline tree with node ids and tuning info."""
    data_root_path = _resolve_data_root(data_root)
    workspace = _load_workspace_or_exit(book_id, data_root_path)

    lines = _render_tree(workspace.nodes)
    console.print(Panel.fit("\n".join(lines) or "[空大纲]", title=f"{book_id} Outline", border_style="blue"))


@main.command("merge")
@click.argument("book_id", type=str)
@click.argument("node_ids", nargs=-1, type=int)
@click.option("--title", type=str, default=None, help="Title for merged node (default: join titles).")
@click.option("--data-root", type=click.Path(), default=None)
def merge_cmd(book_id: str, node_ids: List[int], title: Optional[str], data_root: Optional[str]) -> None:
    """Merge sibling nodes into a single node."""
    if len(node_ids) < 2:
        console.print("[red]错误：[/red] merge 至少需要两个节点 ID。")
        raise SystemExit(1)

    data_root_path = _resolve_data_root(data_root)
    workspace = _load_workspace_or_exit(book_id, data_root_path)

    parent_ref = None
    indices: List[int] = []
    nodes: List[OutlineNode] = []

    for node_id in node_ids:
        result = find_parent_and_index(workspace.nodes, node_id)
        if result is None:
            console.print(f"[red]错误：[/red] 找不到节点 ID {node_id}")
            raise SystemExit(1)
        parent, idx, node = result
        if parent_ref is None:
            parent_ref = parent
        elif parent_ref is not parent:
            console.print("[red]错误：[/red] 需要合并的节点必须是同一父节点下的兄弟节点。")
            raise SystemExit(1)
        indices.append(idx)
        nodes.append(node)

    indices_sorted = sorted(indices)
    if indices_sorted != list(range(indices_sorted[0], indices_sorted[-1] + 1)):
        console.print("[red]错误：[/red] 只能合并连续的兄弟节点。")
        raise SystemExit(1)

    container = parent_ref.children if parent_ref else workspace.nodes
    ordered_nodes = [container[i] for i in indices_sorted]

    merged_title = title or " + ".join(n.title for n in ordered_nodes)
    merged_children: List[OutlineNode] = []
    for node in ordered_nodes:
        merged_children.extend(node.children)

    merged_node = OutlineNode(
        id=workspace.next_id,
        title=merged_title,
        start_page=min(n.start_page for n in ordered_nodes),
        end_page=max(n.end_page for n in ordered_nodes),
        children=merged_children,
    )
    workspace.next_id += 1

    for idx in reversed(indices_sorted):
        container.pop(idx)
    container.insert(indices_sorted[0], merged_node)

    recompute_ranges(workspace.nodes)
    save_workspace(workspace, force=True)

    console.print(f"[green]✓[/green] 已合并节点 -> 新节点 ID {merged_node.id}")


@main.command("split")
@click.argument("book_id", type=str)
@click.argument("node_id", type=int, required=False)
@click.option("--all-leaves", is_flag=True, help="Split all current leaf nodes.")
@click.option("--model", type=str, default=None)
@click.option("--api-key", type=str, default=None)
@click.option("--data-root", type=click.Path(), default=None)
def split_cmd(
    book_id: str,
    node_id: Optional[int],
    all_leaves: bool,
    model: Optional[str],
    api_key: Optional[str],
    data_root: Optional[str],
) -> None:
    """Split leaf node(s) using LLM-generated outline."""
    cfg = Config()
    data_root_path = _resolve_data_root(data_root)
    workspace = _load_workspace_or_exit(book_id, data_root_path)

    if all_leaves and node_id is not None:
        console.print("[red]错误：[/red] 使用 --all-leaves 时不要传 node_id。")
        raise SystemExit(1)
    if not all_leaves and node_id is None:
        console.print("[red]错误：[/red] 请提供 node_id 或使用 --all-leaves。")
        raise SystemExit(1)

    llm = _build_llm_client(cfg, api_key=api_key, model=model)

    targets = collect_leaf_nodes(workspace.nodes) if all_leaves else [find_node(workspace.nodes, node_id)]
    targets = [t for t in targets if t is not None]
    if not targets:
        console.print("[red]错误：[/red] 未找到可拆分的叶子节点。")
        raise SystemExit(1)

    failed: List[int] = []

    with PDFProcessor(str(workspace.pdf_path)) as processor:
        for target in targets:
            if target.children:
                continue
            console.print(f"[yellow]正在使用模型 {llm.model} 拆分节点 {target.id}...[/yellow]")
            text = processor.extract_text_with_pages_range(target.start_page, target.end_page)
            items = llm.generate_outline(text, parent_title=target.title)
            items = [item for item in items if target.start_page <= item.page <= target.end_page]

            if len(items) < 2:
                failed.append(target.id)
                continue

            items.sort(key=lambda i: i.page)
            new_children: List[OutlineNode] = []
            for idx, item in enumerate(items):
                start_page = max(item.page, target.start_page)
                if idx < len(items) - 1:
                    next_page = max(items[idx + 1].page, start_page)
                    end_page = max(start_page, next_page - 1)
                else:
                    end_page = target.end_page

                child = OutlineNode(
                    id=workspace.next_id,
                    title=item.title,
                    start_page=start_page,
                    end_page=end_page,
                    children=[],
                )
                workspace.next_id += 1
                new_children.append(child)

            target.children = new_children

    recompute_ranges(workspace.nodes)
    save_workspace(workspace, force=True)

    if failed:
        console.print(f"[yellow]部分节点未能拆分：{', '.join(str(i) for i in failed)}[/yellow]")
    console.print("[green]✓[/green] 拆分完成。")


@main.command("summarize")
@click.argument("book_id", type=str)
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--overwrite", is_flag=True, help="Overwrite existing summary files.")
@click.option("--model", type=str, default=None)
@click.option("--api-key", type=str, default=None)
@click.option("--data-root", type=click.Path(), default=None)
def summarize_cmd(
    book_id: str,
    output_dir: Optional[str],
    overwrite: bool,
    model: Optional[str],
    api_key: Optional[str],
    data_root: Optional[str],
) -> None:
    """Summarize all leaf nodes and save markdown files."""
    cfg = Config()
    data_root_path = _resolve_data_root(data_root)
    workspace = _load_workspace_or_exit(book_id, data_root_path)
    llm = _build_llm_client(cfg, api_key=api_key, model=model)

    leaves = collect_leaf_nodes(workspace.nodes)
    if not leaves:
        console.print("[red]错误：[/red] 当前大纲没有叶子节点。")
        raise SystemExit(1)

    output_dir_path = _prepare_output_dir(output_dir, workspace.root_dir / "summaries")
    path_map = build_node_dir_map(workspace.nodes)
    skipped: List[int] = []

    with PDFProcessor(str(workspace.pdf_path)) as processor:
        for leaf in leaves:
            text = processor.extract_text_for_page_range(leaf.start_page, leaf.end_page)
            if not text.strip():
                console.print(f"[yellow]跳过节点 {leaf.id}：未提取到文本[/yellow]")
                skipped.append(leaf.id)
                continue

            console.print(f"[yellow]正在生成摘要：节点 {leaf.id}...[/yellow]")
            summary = llm.generate_leaf_summary(text, title=leaf.title)
            content = _render_summary_markdown(leaf, summary)
            output_path = _resolve_leaf_output_path(output_dir_path, path_map, leaf)
            if not _write_markdown(output_path, content, overwrite=overwrite):
                skipped.append(leaf.id)

    console.print(f"[green]✓[/green] 摘要生成完成，输出目录: {output_dir_path}")
    if skipped:
        console.print(f"[yellow]未写入的节点：{', '.join(str(i) for i in skipped)}[/yellow]")


@main.command("tag")
@click.argument("book_id", type=str)
@click.option("--template", "template_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--template-type", type=str)
@click.option("--output-dir", type=click.Path(), default=None)
@click.option("--overwrite", is_flag=True, help="Overwrite existing tag files.")
@click.option("--model", type=str, default=None)
@click.option("--api-key", type=str, default=None)
@click.option("--data-root", type=click.Path(), default=None)
def tag_cmd(
    book_id: str,
    template_path: Optional[str],
    template_type: Optional[str],
    output_dir: Optional[str],
    overwrite: bool,
    model: Optional[str],
    api_key: Optional[str],
    data_root: Optional[str],
) -> None:
    """Extract tag notes for all leaf nodes."""
    cfg = Config()
    data_root_path = _resolve_data_root(data_root)
    workspace = _load_workspace_or_exit(book_id, data_root_path)
    llm = _build_llm_client(cfg, api_key=api_key, model=model)

    template_source = _resolve_template_source(template_path, template_type)
    tag_template = load_tag_template(template_source)

    leaves = collect_leaf_nodes(workspace.nodes)
    if not leaves:
        console.print("[red]错误：[/red] 当前大纲没有叶子节点。")
        raise SystemExit(1)

    output_dir_path = _prepare_output_dir(output_dir, workspace.root_dir / "tags")
    path_map = build_node_dir_map(workspace.nodes)
    skipped: List[int] = []

    with PDFProcessor(str(workspace.pdf_path)) as processor:
        for leaf in leaves:
            text = processor.extract_text_for_page_range(leaf.start_page, leaf.end_page)
            if not text.strip():
                console.print(f"[yellow]跳过节点 {leaf.id}：未提取到文本[/yellow]")
                skipped.append(leaf.id)
                continue

            console.print(f"[yellow]正在提取标签：节点 {leaf.id}...[/yellow]")
            tag_notes = llm.generate_tag_notes(text, title=leaf.title, tag_template=tag_template)
            content = _render_tag_markdown(leaf, tag_template.name, tag_notes)
            output_path = _resolve_leaf_output_path(output_dir_path, path_map, leaf)
            if not _write_markdown(output_path, content, overwrite=overwrite):
                skipped.append(leaf.id)

    console.print(f"[green]✓[/green] 标签提取完成，输出目录: {output_dir_path}")
    if skipped:
        console.print(f"[yellow]未写入的节点：{', '.join(str(i) for i in skipped)}[/yellow]")


@main.command("build-site")
@click.argument("book_id", type=str)
@click.option(
    "--source",
    type=click.Choice(["tags", "summaries"], case_sensitive=False),
    default="tags",
    show_default=True,
)
@click.option("--docs-dir", type=click.Path(), default=None)
@click.option("--site-dir", type=click.Path(), default=None)
@click.option("--site-name", type=str, default=None)
@click.option("--only-config", is_flag=True, help="仅生成 mkdocs 配置文件，不执行构建。")
@click.option("--skip-index", is_flag=True, help="不生成站点首页 index.md。")
@click.option("--data-root", type=click.Path(), default=None)
def build_site_cmd(
    book_id: str,
    source: str,
    docs_dir: Optional[str],
    site_dir: Optional[str],
    site_name: Optional[str],
    only_config: bool,
    skip_index: bool,
    data_root: Optional[str],
) -> None:
    """Build mkdocs static site from existing markdown files."""
    data_root_path = _resolve_data_root(data_root)
    workspace = _load_workspace_or_exit(book_id, data_root_path)
    source_key = source.lower()

    if docs_dir:
        docs_dir_path = Path(docs_dir)
        if not docs_dir_path.is_absolute():
            docs_dir_path = workspace.root_dir / docs_dir_path
    else:
        docs_dir_path = workspace.root_dir / source_key

    site_suffix = f"{source_key}_site"
    site_dir_path = Path(site_dir) if site_dir else workspace.root_dir / site_suffix
    config_path = workspace.root_dir / f"{site_suffix}.mkdocs.yml"
    default_site_name = f"{book_id} 标签" if source_key == "tags" else f"{book_id} 摘要"
    site_name_value = site_name or default_site_name

    build_site(
        SiteBuildConfig(
            docs_dir=docs_dir_path,
            site_dir=site_dir_path,
            config_path=config_path,
            site_name=site_name_value,
            outline_nodes=workspace.nodes,
            write_index=not skip_index and not only_config,
            run_mkdocs=not only_config,
        )
    )
    if only_config:
        console.print(f"[green]✓[/green] 配置已生成: {config_path}")
    else:
        console.print(f"[green]✓[/green] 站点已生成: {site_dir_path}")


@main.command("init-tags-template")
@click.argument("book_id", type=str)
@click.option("--path", "path_value", type=click.Path(), default=None)
@click.option("--data-root", type=click.Path(), default=None)
@click.option("--force", is_flag=True, help="Overwrite existing template file.")
def init_tags_template_cmd(
    book_id: str,
    path_value: Optional[str],
    data_root: Optional[str],
    force: bool,
) -> None:
    """Create a default tag template YAML for a book."""
    data_root_path = _resolve_data_root(data_root)
    book_dir = data_root_path / book_id
    target_path = Path(path_value) if path_value else book_dir / "tag_template.yaml"

    try:
        path = write_default_tag_template(target_path, force=force)
    except FileExistsError as exc:
        console.print(f"[red]错误：[/red] {exc}")
        console.print("使用 --force 进行覆盖。")
        raise SystemExit(1)

    console.print(f"[green]✓[/green] 已创建标签模板: {path}")


if __name__ == "__main__":
    main()
