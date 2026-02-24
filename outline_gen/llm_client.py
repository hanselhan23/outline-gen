"""LLM 集成模块：大纲、摘要与标签提取。"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from openai import OpenAI

from .language_utils import is_probably_english
from .tag_template import TagTemplate
from .usage_tracker import record_chat_completion_usage


class OutlineItem:
    """大纲条目。"""

    def __init__(self, title: str, page: int, level: int = 1) -> None:
        self.title = title
        self.page = page
        self.level = level
        self.children: List["OutlineItem"] = []

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "page": self.page,
            "level": self.level,
            "children": [child.to_dict() for child in self.children],
        }

    def __repr__(self) -> str:
        return f"OutlineItem(title={self.title}, page={self.page}, level={self.level})"


class LLMClient:
    """Dashscope (OpenAI 兼容) 客户端。"""

    MAX_CHARS_PER_CHUNK = 15000

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
    ) -> None:
        self.api_key = api_key
        if not self.api_key:
            for env_var in ["DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY"]:
                self.api_key = os.getenv(env_var)
                if self.api_key:
                    # 发现 Key，但为了调试，如果是从环境变量来的，打印它的来源（遮蔽大部分）
                    print(f"DEBUG: Using API key from environment variable {env_var}: {self.api_key[:5]}...")
                    break

        if not self.api_key:
            # 这里的打印是为了让用户在终端能直接看到为什么报错，而不是只看 trace
            print("\n[red]CRITICAL ERROR: No API key found![/red]")
            print("Please set one of the following environment variables:")
            print("  - DEEPSEEK_API_KEY")
            print("  - DASHSCOPE_API_KEY")
            print("  - OPENAI_API_KEY")
            print("Or update your config.yaml file separately.\n")
            raise ValueError("No LLM API key found in environment or config")

        self.model = model
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=base_url,
        )

    def generate_outline(self, text_content: str, parent_title: str = "") -> List[OutlineItem]:
        """根据文本生成单层大纲条目。"""
        chunks = self._split_text_into_chunks(text_content)
        all_items: List[OutlineItem] = []

        for index, chunk in enumerate(chunks, start=1):
            prompt = self._create_outline_prompt(
                chunk,
                parent_title=parent_title,
                chunk_index=index,
                total_chunks=len(chunks),
            )
            outline_text = self._chat_with_retry(
                prompt,
                system_prompt=self._outline_system_prompt(),
                fallback="（本次生成失败，已跳过）",
            )
            items = self._parse_outline(outline_text)
            all_items.extend(items)

        all_items.sort(key=lambda item: item.page)
        return all_items

    def generate_leaf_summary(self, text_content: str, title: str) -> str:
        """生成单个叶子节点的摘要（Markdown）。"""
        chunks = self._split_text_into_chunks(text_content)
        if len(chunks) == 1:
            prompt = self._create_summary_prompt(chunks[0], title=title, chunk_index=1, total_chunks=1)
            return self._chat_with_retry(
                prompt,
                system_prompt=self._summary_system_prompt(),
                fallback=self._summary_fallback(title),
            )

        chunk_summaries: List[str] = []
        for index, chunk in enumerate(chunks, start=1):
            prompt = self._create_summary_prompt(chunk, title=title, chunk_index=index, total_chunks=len(chunks))
            chunk_summary = self._chat_with_retry(
                prompt,
                system_prompt=self._summary_system_prompt(),
                fallback=self._summary_fallback(title),
            )
            chunk_summaries.append(chunk_summary.strip())

        merge_prompt = self._create_summary_merge_prompt(title=title, summaries=chunk_summaries)
        return self._chat_with_retry(
            merge_prompt,
            system_prompt=self._summary_system_prompt(),
            fallback=self._summary_fallback(title),
        )

    def generate_tag_notes(self, text_content: str, title: str, tag_template: TagTemplate) -> str:
        """根据标签模板提取要点（Markdown）。"""
        prompt = self._create_tag_prompt(text_content, title=title, tag_template=tag_template)
        return self._chat_with_retry(
            prompt,
            system_prompt=self._tag_system_prompt(),
            fallback=self._tag_fallback(tag_template),
        )

    def _chat_with_retry(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float = 0.5,
        fallback: str = "",
    ) -> str:
        """调用模型，报错时重试两次，最终返回可理解的默认结果。"""
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                )
                record_chat_completion_usage(self.model, response)
                content = response.choices[0].message.content or ""
                if is_probably_english(content) and attempt < max_attempts:
                    continue
                return content
            except Exception as e:
                # 如果是认证错误，直接抛出，不再重试，因为重试也没用
                if "401" in str(e) or "auth" in str(e).lower():
                    raise RuntimeError(f"LLM 认证失败 (401): 请检查您的 API Key 是否正确，并且适用于当前接口 ({self.client.base_url})。报错详情: {e}")
                
                if attempt < max_attempts:
                    continue
                return fallback
        return fallback

    def _summary_fallback(self, title: str) -> str:
        return f"- 《{title}》摘要生成失败，已跳过。\n- 可稍后重试获取完整内容。"

    def _tag_fallback(self, tag_template: TagTemplate) -> str:
        parts = []
        for tag in tag_template.tags:
            parts.append(f"## {tag.name}\n- 本次标签提取失败，已跳过。")
        return "\n\n".join(parts)

    def _split_text_into_chunks(self, text_content: str) -> List[str]:
        """按页标记切分文本，避免过长。"""
        if not text_content:
            return [""]

        if len(text_content) <= self.MAX_CHARS_PER_CHUNK:
            return [text_content]

        parts = re.split(r"(?=\[Page \d+\])", text_content)
        parts = [p for p in parts if p.strip()]

        # 如果没有找到页面标记，或者由于某种原因 re.split 后还是只有一个超大块，则强制按字符切分
        if len(parts) <= 1:
            chunk_source = parts[0] if parts else text_content
            if len(chunk_source) > self.MAX_CHARS_PER_CHUNK:
                chunks: List[str] = []
                text = chunk_source
                while text:
                    chunks.append(text[: self.MAX_CHARS_PER_CHUNK])
                    text = text[self.MAX_CHARS_PER_CHUNK :]
                return chunks

        chunks: List[str] = []
        current = ""

        for part in parts:
            if not current:
                current = part
                continue

            if len(current) + len(part) <= self.MAX_CHARS_PER_CHUNK:
                current += part
            else:
                chunks.append(current)
                current = part

        if current:
            chunks.append(current)

        return chunks

    def _outline_system_prompt(self) -> str:
        return (
            "你是一个专业的图书大纲生成助手。"
            "你的任务是分析图书内容，生成结构化的中文章节大纲，并标注每个章节的起始页码。"
            "无论原始文本是中文还是其他语言，你输出的所有标题和说明文字都必须使用简体中文。"
            "除少量国际通用缩写（例如 GDP、FDI、PMI 等）外，请不要保留英文单词、短语或章节名。"
        )

    def _summary_system_prompt(self) -> str:
        return (
            "你是一个专业的中文阅读总结助手。"
            "请用简体中文输出结果，避免出现英文标题或段落。"
        )

    def _tag_system_prompt(self) -> str:
        return (
            "你是一个阅读笔记整理助手。"
            "请用简体中文输出结果，避免出现英文标题或段落。"
        )

    def _create_outline_prompt(
        self,
        chunk_text: str,
        parent_title: str,
        chunk_index: int,
        total_chunks: int,
    ) -> str:
        context = f"\n当前正在分析的上级章节标题：{parent_title}" if parent_title else ""
        chunk_info = ""
        if total_chunks > 1:
            chunk_info = (
                f"\n注意：这是本章节内容的第 {chunk_index}/{total_chunks} 个连续片段，"
                "请只基于当前片段生成大纲，条目中的页码要严格根据片段中的 [Page N] 推断。"
            )

        return (
            "你现在拿到的是一段已经按书签拆分好的图书内容片段，文本中包含页码标记 [Page N]。\n"
            "请仔细阅读并理解这段内容，为它生成一个“精炼的中文大纲”，而不是简单抄录原文中的标题。\n\n"
            "请特别注意以下高优先级规则（从高到低）：\n"
            "1. 如果你判断当前文本主要是图书的“目录/Contents”页，或者几乎全部是“标题 + 页码”的结构：\n"
            "   那么请不要生成任何新的大纲条目，直接返回一个空字符串（什么也不要输出）。\n"
            "2. 所有大纲条目必须是单层结构，禁止生成子级条目；每一行都是同一层级的条目。\n"
            "3. 每个条目必须包含起始页码信息。\n\n"
            "在不违反以上规则的前提下，请按照下面的要求工作：\n"
            "4. 从整体理解这段文本的含义，提炼出最重要的 3–5 个子主题或关键问题。\n"
            "5. 每个子主题的标题要简洁、有概括性，能够帮读者快速理解。\n"
            "6. 为每个子主题标注起始页码，使用“第N页”的中文格式。\n"
            "7. 输出格式：每行一个条目，格式为 \"标题 - 第N页\"。\n\n"
            "示例输出格式（仅示例结构与格式，不要照抄示例标题）：\n"
            "本节的三个关键观点 - 第38页\n"
            "方法与数据概览 - 第45页\n"
            "局限性与后续讨论方向 - 第50页\n"
            f"{context}"
            f"{chunk_info}\n\n"
            "待分析的文本内容如下：\n"
            f"{chunk_text}\n\n"
            "如果你判断这是目录/Contents 页，请直接返回一个空字符串；\n"
            "否则，请按照上述要求，输出 3–5 个条目的大纲。\n"
            "特别注意：无论原文是否为英文，你输出的条目标题和说明必须全部使用中文。"
        )

    def _create_summary_prompt(
        self,
        chunk_text: str,
        title: str,
        chunk_index: int,
        total_chunks: int,
    ) -> str:
        chunk_info = ""
        if total_chunks > 1:
            chunk_info = f"\n这是第 {chunk_index}/{total_chunks} 个连续片段，请仅基于该片段提炼要点。"

        return (
            f"请为章节《{title}》生成简洁摘要，输出 Markdown 要点列表。\n"
            "要求：\n"
            "1. 输出 5-8 条要点，使用短句或短段落。\n"
            "2. 不要复述原文标题，不要出现英文标题。\n"
            "3. 若信息不足，可以减少要点数量，但不要空输出。\n"
            f"{chunk_info}\n\n"
            "待分析文本如下：\n"
            f"{chunk_text}\n"
        )

    def _create_summary_merge_prompt(self, title: str, summaries: List[str]) -> str:
        joined = "\n".join(f"片段{idx + 1}:\n{summary}" for idx, summary in enumerate(summaries))
        return (
            f"请合并以下分段摘要，输出章节《{title}》的统一摘要。\n"
            "输出要求：\n"
            "1. 使用 Markdown 要点列表。\n"
            "2. 只保留最重要的 6-10 条要点，避免重复。\n"
            "3. 不要出现英文标题。\n\n"
            f"{joined}\n"
        )

    def _create_tag_prompt(self, text_content: str, title: str, tag_template: TagTemplate) -> str:
        tag_lines = "\n".join(
            f"{idx + 1}. {tag.name}：{tag.prompt}" for idx, tag in enumerate(tag_template.tags)
        )
        return (
            f"请阅读章节《{title}》的内容，并按以下标签分类提取书中原始文段。\n"
            "输出要求：\n"
            "1. 使用 Markdown 格式。\n"
            "2. 按标签顺序输出，每个标签用二级标题：## 标签名。\n"
            "3. 每个标签下用要点列表，若没有信息请写“无”。\n"
            "4. 不要输出与标签无关的内容。\n\n"
            "5. 通过摘录原文的方式提取，不要进行改写或总结。\n\n"
            "6. 使用双引号包裹，代表是原文摘录。\n\n"
            "标签定义：\n"
            f"{tag_lines}\n\n"
            "待分析文本如下：\n"
            f"{text_content}\n"
        )

    def _parse_outline(self, outline_text: str) -> List[OutlineItem]:
        lines = outline_text.strip().split("\n")
        items: List[OutlineItem] = []

        for line in lines:
            line = line.rstrip()
            if not line:
                continue

            stripped = line.lstrip()
            indent_level = (len(line) - len(stripped)) // 2 + 1
            title, page = self._extract_title_and_page(stripped)
            if title and page:
                items.append(OutlineItem(title=title, page=page, level=indent_level))

        return items

    def _extract_title_and_page(self, text: str) -> tuple[Optional[str], Optional[int]]:
        pattern1 = r"^(.+?)\s*[-–—]\s*(?:第|Page\s*)(\d+)(?:页)?"
        match = re.search(pattern1, text, re.IGNORECASE)
        if match:
            return match.group(1).strip(), int(match.group(2))

        pattern2 = r"^(.+?)\s*\((?:第|Page\s*)(\d+)(?:页)?\)"
        match = re.search(pattern2, text, re.IGNORECASE)
        if match:
            return match.group(1).strip(), int(match.group(2))

        pattern3 = r"^(.+?)\s+(\d+)\s*$"
        match = re.search(pattern3, text)
        if match:
            return match.group(1).strip(), int(match.group(2))

        return None, None
