"""节点路径工具。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from .workspace import OutlineNode


def sanitize_path_component(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    value = value.replace("/", "-").replace("\\", "-")
    value = re.sub(r"\s+", "-", value)
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in ("-", "_"))
    return cleaned.strip("-_")


def node_dir_name(node: OutlineNode) -> str:
    safe_title = sanitize_path_component(node.title) or "node"
    return f"{safe_title}__{node.id}"


def leaf_markdown_filename(node: OutlineNode) -> str:
    safe_title = sanitize_path_component(node.title)
    if not safe_title:
        safe_title = f"node-{node.id}"
    return f"{safe_title}.md"


def build_node_dir_map(nodes: List[OutlineNode]) -> Dict[int, List[str]]:
    path_map: Dict[int, List[str]] = {}

    def walk(node: OutlineNode, parent_parts: List[str]) -> None:
        if node.children:
            dir_name = node_dir_name(node)
            parts = parent_parts + [dir_name]
            path_map[node.id] = parts
            for child in node.children:
                walk(child, parts)
        else:
            # 叶子节点直接落在父目录，避免多余嵌套层级
            path_map[node.id] = parent_parts

    for root in nodes:
        walk(root, [])

    return path_map


def resolve_leaf_path(base_dir: Path, path_map: Dict[int, List[str]], leaf: OutlineNode) -> Path:
    parts = path_map.get(leaf.id)
    if parts is None:
        raise ValueError(f"未找到节点路径: {leaf.id}")
    return base_dir.joinpath(*parts, leaf_markdown_filename(leaf))
