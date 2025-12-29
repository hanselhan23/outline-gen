"""LLM integration module for outline generation using Dashscope via OpenAI framework."""

import os
import json
import re
from typing import List, Dict, Optional
from openai import OpenAI

from .language_utils import is_probably_english
from .usage_tracker import record_chat_completion_usage


class OutlineItem:
    """Represents a single outline item with title and page number."""

    def __init__(self, title: str, page: int, level: int = 1):
        self.title = title
        self.page = page  # 1-indexed for display
        self.level = level
        self.children: List["OutlineItem"] = []

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "page": self.page,
            "level": self.level,
            "children": [child.to_dict() for child in self.children],
        }

    def __repr__(self):
        return f"OutlineItem(title={self.title}, page={self.page}, level={self.level})"


class LLMClient:
    """Client for interacting with Dashscope API via OpenAI framework."""

    # Approximate max characters per chunk to avoid overly long prompts.
    # The whole文本不会被截断，而是按页标记分块后多次调用模型。
    MAX_CHARS_PER_CHUNK = 15000

    def __init__(self, api_key: Optional[str] = None, model: str = "qwen-turbo"):
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise ValueError("DASHSCOPE_API_KEY not found in environment or config")

        self.model = model
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    def generate_outline(self, text_content: str, parent_title: str = "") -> List[OutlineItem]:
        """
        Generate outline from text content using LLM.

        This method will:
        - Split the incoming文本按 [Page N] 页码标记分块
        - 在每个块内部控制长度不超过 MAX_CHARS_PER_CHUNK
        - 对每个块分别调用一次大模型生成局部大纲
        - 合并全部块的大纲条目（按页码排序）

        Args:
            text_content: Text with page markers like [Page N]
            parent_title: Title of parent section for context

        Returns:
            List of OutlineItem objects with titles and page numbers
        """
        chunks = self._split_text_into_chunks(text_content)
        all_items: List[OutlineItem] = []

        for index, chunk in enumerate(chunks, start=1):
            prompt = self._create_prompt(
                chunk,
                parent_title=parent_title,
                chunk_index=index,
                total_chunks=len(chunks),
            )

            # Try multiple times for each chunk: if the first responses are
            # judged to be mostly English, automatically retry a few times.
            for attempt in range(3):
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "你是一个专业的图书大纲生成助手。"
                                    "你的任务是分析图书内容，生成结构化的中文章节大纲，并标注每个章节的起始页码。"
                                    "无论原始文本是中文还是其他语言，你输出的所有标题和说明文字都必须使用简体中文。"
                                    "除少量国际通用缩写（例如 GDP、FDI、PMI 等）外，请不要保留英文单词、短语或章节名"
                                    "（例如 Introduction、Section、Chapter 等），而是改写为自然流畅的中文表达。"
                                ),
                            },
                            {
                                "role": "user",
                                "content": prompt,
                            },
                        ],
                        temperature=0.5,
                    )
                except Exception as e:
                    if attempt == 2:
                        raise RuntimeError(f"Failed to generate outline: {str(e)}")
                    continue

                # Record token usage for this call, if available
                record_chat_completion_usage(self.model, response)

                outline_text = response.choices[0].message.content or ""

                # Validate that the model respected the "Chinese only" requirement.
                # If the outline appears to be mostly English on early attempts,
                # automatically retry. If it remains English after all attempts,
                # still accept the last result instead of raising an error.
                if is_probably_english(outline_text) and attempt < 2:
                    continue

                items = self._parse_outline(outline_text)
                all_items.extend(items)
                break

        # 合并后按页码排序，避免块之间顺序错乱
        all_items.sort(key=lambda item: item.page)
        return all_items

    def _split_text_into_chunks(self, text_content: str) -> List[str]:
        """
        Split long文本 into multiple chunks based on page markers.

        - 优先保证每个块在 [Page N] 边界处分割，避免截断页内容
        - 每个块的长度控制在 MAX_CHARS_PER_CHUNK 左右
        - 保证所有文本都被覆盖，不做硬截断
        """
        if not text_content:
            return [""]

        if len(text_content) <= self.MAX_CHARS_PER_CHUNK:
            return [text_content]

        # 按页标记切分，保留 [Page N] 作为每页的起始
        parts = re.split(r"(?=\[Page \d+\])", text_content)
        parts = [p for p in parts if p.strip()]

        # 如果没有检测到任何页标记，则退化为按字符长度切分
        if not parts:
            chunks: List[str] = []
            text = text_content
            while text:
                chunks.append(text[: self.MAX_CHARS_PER_CHUNK])
                text = text[self.MAX_CHARS_PER_CHUNK :]
            return chunks

        chunks: List[str] = []
        current = ""

        for part in parts:
            # 如果当前块为空，直接放进去，避免单页就超过限制导致死循环
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

    def _create_prompt(
        self,
        chunk_text: str,
        parent_title: str,
        chunk_index: int,
        total_chunks: int,
    ) -> str:
        """Create prompt for outline generation for a single chunk."""
        context = f"\n当前正在分析的上级章节标题：{parent_title}" if parent_title else ""
        chunk_info = ""
        if total_chunks > 1:
            chunk_info = f"\n注意：这是本章节内容的第 {chunk_index}/{total_chunks} 个连续片段，请只基于当前片段生成大纲，条目中的页码要严格根据片段中的 [Page N] 推断。"

        prompt = (
            "你现在拿到的是一段已经按书签拆分好的图书内容片段，文本中包含页码标记 [Page N]。\n"
            "请仔细阅读并理解这段内容，为它生成一个“精炼的中文大纲”，而不是简单抄录原文中的标题。\n\n"
            "请特别注意以下高优先级规则（从高到低）：\n"
            "1. 如果你判断当前文本主要是图书的“目录/Contents”页，或者几乎全部是“标题 + 页码”的结构（缺少完整段落和句子）：\n"
            "   那么请不要生成任何新的大纲条目，直接返回一个空字符串（什么也不要输出）。这一条规则优先级最高。\n"
            "2. 所有大纲条目必须是单层结构，禁止生成子级条目；每一行都是同一层级的条目，行首不能有任何缩进空格。\n"
            "3. 每个条目必须包含起始页码信息。\n\n"
            "在不违反以上规则的前提下，请按照下面的要求工作：\n"
            "4. 从整体理解这段文本的含义，提炼出最重要的 3–5 个子主题或关键问题，而不是逐段机械提取标题。\n"
            "5. 每个子主题的标题要简洁、有概括性，能够帮读者快速理解这一段主要讲什么，可以适当重写、合并或抽象原文的表述。\n"
            "6. 为每个子主题标注起始页码（必须包含），页码需要从文本中的 [Page N] 标记推断得到，使用“第N页”的中文格式。\n"
            "7. 输出格式：每行一个条目，格式为 \"标题 - 第N页\"（注意：行首不能有任何空格，不要使用缩进来表示层级）。\n\n"
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
            "特别注意：无论原文是否为英文，你输出的条目标题和说明必须全部使用中文，"
            "不要保留英文章节标题（如 Introduction、Section I 等），"
            "可以保留极少量必要的英文缩写（如 GDP/FDI/PMI）。\n"
        )

        return prompt

    def _parse_outline(self, outline_text: str) -> List[OutlineItem]:
        """
        Parse LLM generated outline text into structured OutlineItem objects.

        Expected format:
        - "Title - 第N页" or "Title - Page N"
        - Indentation indicates hierarchy
        """
        lines = outline_text.strip().split('\n')
        items = []

        for line in lines:
            line = line.rstrip()
            if not line:
                continue

            # Calculate level based on leading whitespace
            stripped = line.lstrip()
            indent_level = (len(line) - len(stripped)) // 2 + 1

            # Extract title and page number
            title, page = self._extract_title_and_page(stripped)

            if title and page:
                item = OutlineItem(title=title, page=page, level=indent_level)
                items.append(item)

        return items

    def _extract_title_and_page(self, text: str) -> tuple[Optional[str], Optional[int]]:
        """
        Extract title and page number from a line.

        Supports formats:
        - "Title - 第N页"
        - "Title - Page N"
        - "Title (第N页)"
        - "Title (Page N)"
        """
        import re

        # Pattern 1: "Title - 第N页" or "Title - Page N"
        pattern1 = r"^(.+?)\s*[-–—]\s*(?:第|Page\s*)(\d+)(?:页)?"
        match = re.search(pattern1, text, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            page = int(match.group(2))
            return title, page

        # Pattern 2: "Title (第N页)" or "Title (Page N)"
        pattern2 = r"^(.+?)\s*\((?:第|Page\s*)(\d+)(?:页)?\)"
        match = re.search(pattern2, text, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            page = int(match.group(2))
            return title, page

        # Pattern 3: Just numbers at the end "Title N"
        pattern3 = r"^(.+?)\s+(\d+)\s*$"
        match = re.search(pattern3, text)
        if match:
            title = match.group(1).strip()
            page = int(match.group(2))
            return title, page

        return None, None
