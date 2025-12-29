"""Recursive engine for managing outline generation with depth control."""

import os
import re
from typing import List, Dict, Optional, Callable
from pathlib import Path
from dataclasses import dataclass

from .pdf_processor import PDFProcessor, Bookmark
from .llm_client import LLMClient, OutlineItem


@dataclass
class OutlineNode:
    """Represents a node in the recursive outline tree."""
    title: str
    page: int
    level: int
    children: List['OutlineNode']
    source_bookmark: Optional[Bookmark] = None
    # Optional page range (in original PDF) used to generate this node's outline
    start_page: Optional[int] = None
    end_page: Optional[int] = None

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "page": self.page,
            "level": self.level,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "children": [child.to_dict() for child in self.children]
        }

    def flatten(self, prefix: str = "") -> List[str]:
        """Flatten outline to list of formatted strings."""
        # 使用制表符代表层级缩进，而不是空格
        indent_level = max(self.level - 1, 0)
        indent = "\t" * indent_level
        lines = [f"{indent}{self.title} {self.page}"]

        for child in self.children:
            lines.extend(child.flatten(prefix))

        return lines


class RecursiveEngine:
    """Manages recursive outline generation process."""

    def __init__(self, pdf_path: str, max_depth: int = 2, api_key: Optional[str] = None):
        self.pdf_path = Path(pdf_path)
        self.max_depth = max_depth
        self.llm_client = LLMClient(api_key=api_key)
        self.outline_tree: List[OutlineNode] = []
        self.temp_files: List[Path] = []
        # Minimum token-like unit count for enabling recursive refinement.
        # We approximate tokens by counting non-whitespace characters.
        self.min_tokens_for_recursion: int = 400

    def _estimate_token_count(self, text: str) -> int:
        """Rough token count estimation based on non-whitespace characters."""
        cleaned = re.sub(r"\s+", "", text)
        return len(cleaned)

    def _build_bookmark_tree(self, bookmarks: List[Bookmark]) -> List[Bookmark]:
        """
        Build hierarchical bookmark tree from flat bookmark list.

        The incoming bookmarks are expected to be in reading order with
        valid level information (as returned by PyMuPDF).
        """
        roots: List[Bookmark] = []
        stack: List[Bookmark] = []

        for bm in bookmarks:
            # Pop until we find a parent with smaller level
            while stack and stack[-1].level >= bm.level:
                stack.pop()

            if stack:
                # Current bookmark is a child of the stack top
                stack[-1].children.append(bm)
            else:
                # No parent on stack, this is a root-level bookmark
                roots.append(bm)

            stack.append(bm)

        return roots

    def _collect_leaf_bookmarks(self, roots: List[Bookmark]) -> List[Bookmark]:
        """Collect all leaf bookmarks (bookmarks without children) in reading order."""
        leaves: List[Bookmark] = []

        def dfs(node: Bookmark):
            if not node.children:
                leaves.append(node)
            else:
                for child in node.children:
                    dfs(child)

        for root in roots:
            dfs(root)

        # Leaves are discovered in document order because the input roots
        # preserve the original reading order.
        return leaves

    def _build_outline_tree_from_bookmarks(self, roots: List[Bookmark], base_level: int) -> List[OutlineNode]:
        """Create an OutlineNode tree mirroring the original bookmark hierarchy."""

        def build_node(bm: Bookmark) -> OutlineNode:
            node_level = max(bm.level - base_level, 0)
            node = OutlineNode(
                title=bm.title,
                page=bm.page + 1,  # Convert to 1-indexed global page
                level=node_level,
                children=[],
                source_bookmark=bm
            )
            for child_bm in bm.children:
                node.children.append(build_node(child_bm))
            return node

        return [build_node(root) for root in roots]

    def _build_bookmark_to_node_map(self, roots: List[OutlineNode]) -> Dict[Bookmark, OutlineNode]:
        """Build a mapping from Bookmark objects to their corresponding OutlineNode."""
        mapping: Dict[Bookmark, OutlineNode] = {}

        def dfs(node: OutlineNode):
            if node.source_bookmark is not None:
                mapping[node.source_bookmark] = node
            for child in node.children:
                dfs(child)

        for root in roots:
            dfs(root)

        return mapping

    def _attach_outline_items_to_node(
        self,
        parent_node: OutlineNode,
        outline_items: List[OutlineItem]
    ) -> Dict[OutlineItem, OutlineNode]:
        """
        Attach LLM-generated outline items as children of a node,
        respecting the relative levels in OutlineItem.

        Returns a mapping from OutlineItem to the created OutlineNode.
        """
        item_to_node: Dict[OutlineItem, OutlineNode] = {}
        base_level = parent_node.level
        stack: List[tuple[int, OutlineNode]] = []  # (relative_level, node)

        for item in outline_items:
            # OutlineItem.level is relative indentation (1 = direct child)
            rel_level = max(item.level, 1)

            # Find parent according to relative levels
            while stack and stack[-1][0] >= rel_level:
                stack.pop()

            if stack:
                parent = stack[-1][1]
            else:
                parent = parent_node

            global_level = base_level + rel_level
            node = OutlineNode(
                title=item.title,
                page=item.page,
                level=global_level,
                children=[]
            )
            parent.children.append(node)
            item_to_node[item] = node
            stack.append((rel_level, node))

        return item_to_node

    def _enrich_node_with_llm(
        self,
        node: OutlineNode,
        section_path: Path,
        page_offset: int,
        current_depth: int,
        progress_callback: Optional[Callable[[str, Optional[OutlineNode]], None]] = None
    ) -> None:
        """
        Use LLM to recursively enrich a given node with additional outline levels.

        - node: the OutlineNode representing the current section
        - section_path: path to the PDF segment for this node
        - page_offset: starting page in the original PDF (0-indexed)
        - current_depth: current AI recursion depth beneath the leaf
        """
        # Stop if reached max depth (depth=0 means no AI generation)
        if current_depth >= self.max_depth:
            return

        with PDFProcessor(section_path) as processor:
            # Determine page range in original PDF for this section
            section_page_count = processor.get_page_count()
            node.start_page = page_offset + 1
            node.end_page = page_offset + section_page_count

            # Extract text with page offset to maintain original page numbers
            text = processor.extract_text_with_pages(page_offset=page_offset)
            token_count = self._estimate_token_count(text)

            # Notify that we're starting to generate outline
            if progress_callback:
                progress_callback("generating", node)

            try:
                outline_items = self.llm_client.generate_outline(text, node.title)
            except Exception as e:
                if progress_callback:
                    progress_callback(f"error:{str(e)}", node)
                return

            if not outline_items:
                # Nothing to attach
                if progress_callback:
                    progress_callback("generated", node)
                return

            # Attach first-level (and nested) items under this node
            item_to_node = self._attach_outline_items_to_node(parent_node=node, outline_items=outline_items)

            if progress_callback:
                progress_callback("generated", node)

            # Decide whether this section is "large enough" to justify
            # another round of recursive refinement.
            can_recurse = (
                current_depth + 1 < self.max_depth
                and len(outline_items) > 1
                and token_count >= self.min_tokens_for_recursion
                # If the local section has less than 2 pages, do not split further.
                and section_page_count >= 2
            )

            if not can_recurse:
                return

            # Prepare sub-bookmarks for further splitting based on LLM items.
            sub_bookmarks: List[Bookmark] = []
            sorted_items = sorted(outline_items, key=lambda i: i.page)
            for item in sorted_items:
                # item.page is global (1-indexed, includes offset already)
                # Convert to 0-indexed global, then to local page index
                global_page_zero = max(item.page - 1, 0)
                local_page = global_page_zero - page_offset

                # Clamp to valid local range [0, section_page_count - 1]
                if section_page_count > 0:
                    if local_page < 0:
                        local_page = 0
                    elif local_page >= section_page_count:
                        local_page = section_page_count - 1

                bookmark_obj = Bookmark(
                    title=item.title,
                    page=local_page,  # Local page index within this section PDF
                    level=item.level
                )
                # Link bookmark back to its corresponding OutlineNode
                setattr(bookmark_obj, "_outline_node", item_to_node[item])
                sub_bookmarks.append(bookmark_obj)

            # Split section by generated outline and recurse into each subsection
            sections = processor.split_by_bookmarks(sub_bookmarks)

            for sub_bookmark, sub_section_path, sub_page_offset in sections:
                self.temp_files.append(sub_section_path)
                child_node = getattr(sub_bookmark, "_outline_node", None)
                if child_node is None:
                    continue

                # sub_page_offset is local to this section; convert to global
                self._enrich_node_with_llm(
                    node=child_node,
                    section_path=sub_section_path,
                    page_offset=sub_page_offset + page_offset,
                    current_depth=current_depth + 1,
                    progress_callback=progress_callback
                )

    def generate_outline(self, progress_callback: Optional[Callable[[str, Optional[OutlineNode]], None]] = None) -> List[OutlineNode]:
        """
        Generate recursive outline for the entire PDF.

        Args:
            progress_callback: Optional callback function(action: str, node: Optional[OutlineNode]) for progress updates

        Returns:
            List of top-level OutlineNode objects
        """
        with PDFProcessor(self.pdf_path) as processor:
            # Extract existing bookmarks
            bookmarks = processor.extract_bookmarks()

            if not bookmarks:
                # Process entire PDF as one section
                text = processor.extract_text_with_pages()
                outline_items = self.llm_client.generate_outline(text, "")
                self.outline_tree = self._convert_items_to_nodes(outline_items, 1)
            else:
                # Build full bookmark tree and use it as the base outline.
                # Then, only for leaf bookmarks, use LLM to generate additional
                # levels of outline beneath them.
                roots = self._build_bookmark_tree(bookmarks)

                # Normalize levels so that the smallest bookmark level becomes 0
                base_level = min(b.level for b in bookmarks)
                self.outline_tree = self._build_outline_tree_from_bookmarks(roots, base_level)

                # Build a map from Bookmark -> OutlineNode
                bookmark_node_map = self._build_bookmark_to_node_map(self.outline_tree)

                # Collect leaf bookmarks and split PDF by these leaves
                leaf_bookmarks = self._collect_leaf_bookmarks(roots)
                leaf_bookmarks_sorted = sorted(leaf_bookmarks, key=lambda b: b.page)

                sections = processor.split_by_bookmarks(leaf_bookmarks_sorted)

                # Map each leaf bookmark to its corresponding section
                leaf_section_map: Dict[Bookmark, tuple[Path, int]] = {}
                for bm, section_path, page_offset in sections:
                    leaf_section_map[bm] = (section_path, page_offset)

                # For each leaf bookmark, enrich its corresponding OutlineNode
                # with recursively generated outline using LLM.
                for leaf_bm in leaf_bookmarks_sorted:
                    section = leaf_section_map.get(leaf_bm)
                    target_node = bookmark_node_map.get(leaf_bm)
                    if not section or target_node is None:
                        continue

                    section_path, page_offset = section
                    self.temp_files.append(section_path)

                    self._enrich_node_with_llm(
                        node=target_node,
                        section_path=section_path,
                        page_offset=page_offset,
                        current_depth=0,
                        progress_callback=progress_callback
                    )

        return self.outline_tree


    def _convert_items_to_nodes(self, items: List[OutlineItem], level: int) -> List[OutlineNode]:
        """Convert OutlineItem objects to OutlineNode objects."""
        nodes = []
        for item in items:
            node = OutlineNode(
                title=item.title,
                page=item.page,
                level=level,
                children=[]
            )
            nodes.append(node)
        return nodes

    def cleanup(self):
        """Clean up temporary files."""
        for temp_file in self.temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception:
                pass

    def save_outline(self, output_path: str, format: str = "txt"):
        """
        Save generated outline to file.

        Args:
            output_path: Output file path
            format: Output format ('txt', 'json', 'md')
        """
        output_path = Path(output_path)

        if format == "json":
            import json
            data = [node.to_dict() for node in self.outline_tree]
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        elif format == "md":
            lines = ["# 图书大纲\n"]
            for node in self.outline_tree:
                lines.extend(self._format_node_markdown(node))
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines))

        else:  # txt format
            lines = []
            for node in self.outline_tree:
                lines.extend(node.flatten())
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines))

    def _format_node_markdown(self, node: OutlineNode, prefix: str = "") -> List[str]:
        """Format node as markdown with hierarchy."""
        lines = []
        indent = "#" * (node.level + 1)
        lines.append(f"{indent} {node.title} {node.page}")
        lines.append("")

        for child in node.children:
            lines.extend(self._format_node_markdown(child, prefix))

        return lines
