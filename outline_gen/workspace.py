"""Workspace data model and tree utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .pdf_processor import Bookmark


@dataclass
class OutlineNode:
    """Node in the editable outline tree."""

    id: int
    title: str
    start_page: int
    end_page: int
    children: List["OutlineNode"] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, payload: Dict) -> "OutlineNode":
        return cls(
            id=int(payload["id"]),
            title=str(payload.get("title", "")),
            start_page=int(payload.get("start_page", 1)),
            end_page=int(payload.get("end_page", 1)),
            children=[cls.from_dict(child) for child in payload.get("children", [])],
        )


@dataclass
class Workspace:
    book_id: str
    root_dir: Path
    pdf_path: Path
    nodes: List[OutlineNode]
    next_id: int

    @property
    def outline_path(self) -> Path:
        return self.root_dir / "outline.json"

    @property
    def outline_txt_path(self) -> Path:
        return self.root_dir / "outline.txt"


def _collect_nodes(nodes: List[OutlineNode]) -> List[OutlineNode]:
    collected: List[OutlineNode] = []

    def walk(node: OutlineNode) -> None:
        collected.append(node)
        for child in node.children:
            walk(child)

    for root in nodes:
        walk(root)

    return collected


def _infer_next_id(nodes: List[OutlineNode]) -> int:
    ids = [node.id for node in _collect_nodes(nodes)]
    return max(ids, default=0) + 1


def load_workspace(book_id: str, data_root: Path) -> Workspace:
    root_dir = data_root / book_id
    outline_path = root_dir / "outline.json"
    if not outline_path.exists():
        raise FileNotFoundError(f"Workspace outline not found: {outline_path}")

    with outline_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    pdf_rel = payload.get("pdf", "book.pdf")
    pdf_path = root_dir / pdf_rel
    nodes = [OutlineNode.from_dict(n) for n in payload.get("nodes", [])]
    next_id = int(payload.get("next_id") or _infer_next_id(nodes))

    return Workspace(
        book_id=book_id,
        root_dir=root_dir,
        pdf_path=pdf_path,
        nodes=nodes,
        next_id=next_id,
    )


def save_workspace(workspace: Workspace, force: bool) -> None:
    if workspace.outline_path.exists() and not force:
        raise FileExistsError(f"Outline already exists: {workspace.outline_path}")
    workspace.outline_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "book_id": workspace.book_id,
        "pdf": workspace.pdf_path.name,
        "nodes": [node.to_dict() for node in workspace.nodes],
        "next_id": workspace.next_id,
    }

    with workspace.outline_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    lines = build_outline_txt_lines(workspace.nodes)
    workspace.outline_txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def find_node(nodes: List[OutlineNode], node_id: int) -> Optional[OutlineNode]:
    for node in nodes:
        if node.id == node_id:
            return node
        child = find_node(node.children, node_id)
        if child:
            return child
    return None


def find_parent_and_index(
    nodes: List[OutlineNode],
    node_id: int,
    parent: Optional[OutlineNode] = None,
) -> Optional[Tuple[Optional[OutlineNode], int, OutlineNode]]:
    for idx, node in enumerate(nodes):
        if node.id == node_id:
            return parent, idx, node
        result = find_parent_and_index(node.children, node_id, node)
        if result:
            return result
    return None


def recompute_ranges(nodes: List[OutlineNode]) -> None:
    for node in nodes:
        if node.children:
            recompute_ranges(node.children)
            node.start_page = min(child.start_page for child in node.children)
            node.end_page = max(child.end_page for child in node.children)


def compute_subtree_stats(nodes: List[OutlineNode]) -> Dict[int, Dict[str, int]]:
    stats: Dict[int, Dict[str, int]] = {}

    def walk(node: OutlineNode) -> Dict[str, int]:
        if not node.children:
            page_count = max(node.end_page - node.start_page + 1, 0)
            stats[node.id] = {
                "node_count": 1,
                "leaf_count": 1,
                "page_count": page_count,
            }
            return stats[node.id]

        node_count = 1
        leaf_count = 0
        page_count = 0
        for child in node.children:
            child_stats = walk(child)
            node_count += child_stats["node_count"]
            leaf_count += child_stats["leaf_count"]
            page_count += child_stats["page_count"]

        stats[node.id] = {
            "node_count": node_count,
            "leaf_count": leaf_count,
            "page_count": page_count,
        }
        return stats[node.id]

    for root in nodes:
        walk(root)

    return stats


def build_nodes_from_bookmarks(
    bookmarks: List[Bookmark],
    total_pages: int,
    next_id_start: int = 1,
) -> Tuple[List[OutlineNode], int]:
    if not bookmarks:
        return [], next_id_start

    nodes: List[OutlineNode] = []
    stack: List[Tuple[int, OutlineNode]] = []
    next_id = next_id_start

    for bm in bookmarks:
        node = OutlineNode(
            id=next_id,
            title=bm.title,
            start_page=bm.page + 1,
            end_page=bm.page + 1,
            children=[],
        )
        next_id += 1

        while stack and stack[-1][0] >= bm.level:
            stack.pop()

        if stack:
            stack[-1][1].children.append(node)
        else:
            nodes.append(node)

        stack.append((bm.level, node))

    _assign_leaf_ranges_by_order(nodes, total_pages)
    recompute_ranges(nodes)
    return nodes, next_id


def _assign_leaf_ranges_by_order(nodes: List[OutlineNode], total_pages: int) -> None:
    flat: List[OutlineNode] = []

    def walk(node: OutlineNode) -> None:
        flat.append(node)
        for child in node.children:
            walk(child)

    for root in nodes:
        walk(root)

    flat.sort(key=lambda n: n.start_page)
    for idx, node in enumerate(flat):
        if idx < len(flat) - 1:
            node.end_page = max(node.start_page, flat[idx + 1].start_page - 1)
        else:
            node.end_page = max(node.start_page, total_pages)


def build_outline_txt_lines(nodes: List[OutlineNode]) -> List[str]:
    lines: List[str] = []

    def walk(node: OutlineNode, level: int) -> None:
        indent = "\t" * max(level, 0)
        title_lines = node.title.splitlines() or [node.title]
        first = title_lines[0]
        lines.append(f"{indent}{first} {node.start_page}")
        for extra in title_lines[1:]:
            lines.append(f"{indent}{extra}")
        for child in node.children:
            walk(child, level + 1)

    for root in nodes:
        walk(root, 0)

    return lines
