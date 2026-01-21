"""MkDocs 站点生成工具。"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .node_paths import build_node_dir_map, resolve_leaf_path
from .workspace import OutlineNode

@dataclass(frozen=True)
class SiteBuildConfig:
    docs_dir: Path
    site_dir: Path
    config_path: Path
    site_name: str
    outline_nodes: List[OutlineNode]
    write_index: bool = True
    run_mkdocs: bool = True


def build_site(config: SiteBuildConfig) -> None:
    """生成 mkdocs 配置并可选构建站点。"""
    docs_dir = config.docs_dir.resolve()
    site_dir = config.site_dir.resolve()
    config_path = config.config_path.resolve()

    if not docs_dir.exists():
        raise FileNotFoundError(f"文档目录不存在: {docs_dir}")

    index_path = docs_dir / "index.md"
    if config.write_index:
        index_path = _write_index(docs_dir, title=config.site_name)

    mkdocs_config = _build_mkdocs_config(
        docs_dir=docs_dir,
        site_dir=site_dir,
        site_name=config.site_name,
        outline_nodes=config.outline_nodes,
        index_path=index_path if index_path.exists() else None,
    )

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(mkdocs_config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    if config.run_mkdocs:
        subprocess.run(
            ["mkdocs", "build", "-f", str(config_path)],
            check=True,
        )


def _write_index(docs_dir: Path, title: str) -> Path:
    """生成站点首页。"""
    lines = [
        f"# {title}",
        "",
        "请通过左侧导航进入章节。",
        "",
    ]
    index_path = docs_dir / "index.md"
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path


def _build_mkdocs_config(
    docs_dir: Path,
    site_dir: Path,
    site_name: str,
    outline_nodes: List[OutlineNode],
    index_path: Optional[Path],
) -> Dict[str, object]:
    nav = _build_nav(docs_dir, outline_nodes, index_path)
    return {
        "site_name": site_name,
        "docs_dir": str(docs_dir),
        "site_dir": str(site_dir),
        "theme": {"name": "material", "features": ["navigation.footer"]},
        "use_directory_urls": False,
        "nav": nav,
    }


def _build_nav(
    docs_dir: Path,
    outline_nodes: List[OutlineNode],
    index_path: Optional[Path],
) -> List[Dict[str, object]]:
    """构建 mkdocs 导航。"""
    nav: List[Dict[str, object]] = []
    if index_path is not None:
        nav.append({"首页": index_path.relative_to(docs_dir).as_posix()})
    if not outline_nodes:
        return nav
    path_map = build_node_dir_map(outline_nodes)
    for entry in _build_nav_from_nodes(outline_nodes, docs_dir, path_map):
        nav.append(entry)
    return nav


def _build_nav_from_nodes(
    nodes: List[OutlineNode],
    docs_dir: Path,
    path_map: Dict[int, List[str]],
) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    for node in _sorted_nodes(nodes):
        if node.children:
            children_entries = _build_nav_from_nodes(node.children, docs_dir, path_map)
            if not children_entries:
                continue
            entries.append({node.title: children_entries})
            continue

        leaf_path = resolve_leaf_path(docs_dir, path_map, node)
        if not leaf_path.exists():
            continue
        title = _read_markdown_title(leaf_path) or node.title or leaf_path.stem
        entries.append({title: leaf_path.relative_to(docs_dir).as_posix()})

    return entries


def _sorted_nodes(nodes: List[OutlineNode]) -> List[OutlineNode]:
    return sorted(nodes, key=lambda node: (node.start_page, node.id))


def _read_markdown_title(path: Path) -> Optional[str]:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        return None
    return None
