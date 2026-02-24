"""标签模板读取与默认模板管理。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml


@dataclass
class TagPrompt:
    """标签提示词定义。"""

    name: str
    prompt: str


@dataclass
class TagTemplate:
    """标签模板结构。"""

    name: str
    tags: List[TagPrompt]


DEFAULT_TAG_TEMPLATE = """name: 四标签阅读模板
tags:
  - name: 底层设计
    prompt: 提取作者用来搭建论点的核心假设、框架或模型。
  - name: 因果链条
    prompt: 提取作者描述的关键因果机制或推理链条。
  - name: 潜在后果
    prompt: 总结这些观点可能带来的后果、风险或启示。
  - name: 作者金句/改进意见
    prompt: 摘录或改写最具代表性的表述，并给出改进建议。
"""


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

TEMPLATE_ALIASES: Dict[str, str] = {
    "literature": "literature.yaml",
    "wenxue": "literature.yaml",
    "social_science": "social_science.yaml",
    "sociology": "social_science.yaml",
    "philosophy": "philosophy.yaml",
    "zhexue": "philosophy.yaml",
    "fiction": "fiction.yaml",
    "novel": "fiction.yaml",
    "xiaoshuo": "fiction.yaml",
    "general": "general.yaml"
}


def load_tag_template(path: Path) -> TagTemplate:
    """读取并校验标签模板 YAML。"""
    if not path.exists():
        raise FileNotFoundError(f"标签模板不存在: {path}")

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    name = str(payload.get("name") or path.stem).strip()
    tags_payload = payload.get("tags")

    if not isinstance(tags_payload, list) or not tags_payload:
        raise ValueError("标签模板需要包含非空的 tags 列表")

    tags: List[TagPrompt] = []
    for idx, item in enumerate(tags_payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"标签模板第 {idx} 项必须是字典")
        tag_name = str(item.get("name") or "").strip()
        tag_prompt = str(item.get("prompt") or "").strip()
        if not tag_name or not tag_prompt:
            raise ValueError(f"标签模板第 {idx} 项缺少 name 或 prompt")
        tags.append(TagPrompt(name=tag_name, prompt=tag_prompt))

    return TagTemplate(name=name, tags=tags)


def resolve_tag_template_path(template_type: str) -> Path:
    """根据作品类型解析模板路径。"""
    key = (template_type or "").strip().lower()
    filename = TEMPLATE_ALIASES.get(key)
    if not filename:
        raise ValueError(f"未知模板类型: {template_type}")
    return TEMPLATE_DIR / filename


def list_template_types() -> List[str]:
    """列出支持的模板类型键名。"""
    return sorted(set(TEMPLATE_ALIASES.keys()))


def write_default_tag_template(path: Path, force: bool) -> Path:
    """写入默认标签模板。"""
    if path.exists() and not force:
        raise FileExistsError(f"标签模板已存在: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_TAG_TEMPLATE, encoding="utf-8")
    return path
