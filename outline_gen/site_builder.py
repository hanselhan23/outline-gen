"""MkDocs 站点生成工具。"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml


@dataclass(frozen=True)
class SiteBuildConfig:
    docs_dir: Path
    site_dir: Path
    config_path: Path
    site_name: str


def build_site(config: SiteBuildConfig) -> None:
    """为指定的 Markdown 目录生成静态站点。"""
    docs_dir = config.docs_dir.resolve()
    site_dir = config.site_dir.resolve()
    config_path = config.config_path.resolve()

    if not docs_dir.exists():
        raise FileNotFoundError(f"文档目录不存在: {docs_dir}")

    index_path = _write_index(docs_dir, title=config.site_name)
    nav = _build_nav(docs_dir, index_path)
    mkdocs_config = {
        "site_name": config.site_name,
        "docs_dir": str(docs_dir),
        "site_dir": str(site_dir),
        "theme": {"name": "material", "features": ["navigation.footer"]},
        "nav": nav,
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(mkdocs_config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

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


def _build_nav(docs_dir: Path, index_path: Path) -> List[Dict[str, object]]:
    """构建 mkdocs 导航。"""
    nav: List[Dict[str, object]] = [{"首页": index_path.relative_to(docs_dir).as_posix()}]
    for entry in _build_nav_entries(docs_dir, docs_dir):
        nav.append(entry)
    return nav


def _build_nav_entries(current_dir: Path, docs_dir: Path) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    for subdir in _sorted_subdirs(current_dir):
        sub_entries = _build_nav_entries(subdir, docs_dir)
        index_path = subdir / "index.md"
        if sub_entries:
            title = _display_name_from_dir(subdir.name)
            entries.append({title: sub_entries})
        elif index_path.exists():
            title = _read_markdown_title(index_path) or _display_name_from_dir(subdir.name)
            rel_path = index_path.relative_to(docs_dir).as_posix()
            entries.append({title: rel_path})
    return entries


def _iter_leaf_indexes(current_dir: Path, docs_dir: Path) -> List[Path]:
    subdirs = _sorted_subdirs(current_dir)
    if not subdirs:
        if current_dir == docs_dir:
            return []
        index_path = current_dir / "index.md"
        return [index_path] if index_path.exists() else []
    leaf_indexes: List[Path] = []
    for subdir in subdirs:
        leaf_indexes.extend(_iter_leaf_indexes(subdir, docs_dir))
    return leaf_indexes


def _sorted_subdirs(current_dir: Path) -> List[Path]:
    subdirs = [path for path in current_dir.iterdir() if path.is_dir()]
    return sorted(subdirs, key=_dir_sort_key)


def _dir_sort_key(path: Path) -> Tuple[int, str]:
    order = _parse_dir_order(path.name)
    if order is None:
        return (10**9, path.name)
    return (order, path.name)


def _parse_dir_order(name: str) -> Optional[int]:
    if "__" not in name:
        return None
    suffix = name.rsplit("__", 1)[-1]
    if suffix.isdigit():
        return int(suffix)
    return None


def _read_markdown_title(path: Path) -> Optional[str]:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        return None
    return None


def _display_name_from_dir(name: str) -> str:
    base = name.split("__", 1)[0]
    base = base.replace("-", " ").strip()
    return base or name


def _has_subdirs(path: Path) -> bool:
    return any(child.is_dir() for child in path.iterdir())
