# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个 Python 命令行工具，用于为 PDF 书籍递归生成详细大纲。工作流程：
1. 接收一个已有简单书签的 PDF 文件
2. 按最小层级书签切分 PDF
3. 从每个分区提取文本并标记页码
4. 使用 OpenAI 框架调用 Dashscope 百炼大模型生成包含页码的大纲
5. 根据生成的大纲递归切分和处理
6. 用户可指定递归层级

## 包管理

本项目使用 **uv** 管理 Python 环境和依赖。

### 常用命令

```bash
# 安装依赖
uv sync

# 运行主程序
uv run outline-gen <pdf文件路径> --depth <递归层级>

# 运行测试
uv run pytest

# 运行单个测试文件
uv run pytest tests/test_specific.py

# 运行单个测试函数
uv run pytest tests/test_specific.py::test_function_name

# 添加依赖
uv add <包名>

# 添加开发依赖
uv add --dev <包名>
```

## 架构设计

### 核心模块

1. **PDF 处理模块**
   - 书签提取和解析
   - 按书签层级切分 PDF
   - 文本提取并保留页码标记

2. **大模型集成模块**
   - 使用 OpenAI 框架对接 Dashscope 百炼
   - 提示词设计（要求返回页码）
   - 解析大模型响应，提取结构化大纲数据

3. **递归引擎**
   - 管理基于生成大纲的递归切分
   - 跟踪递归深度
   - 协调 PDF 处理和大模型调用

4. **命令行接口**
   - 参数解析（PDF 文件路径、递归层级）
   - 进度显示
   - 输出格式化

### 关键设计要点

- **递归处理**：大纲生成是递归过程 - 每个分区可根据生成的大纲进一步细分，直到达到指定层级

- **页码保持**：在所有处理阶段都要保持准确的页码映射，确保最终大纲引用正确的页码

- **提示词设计**：大模型提示词必须明确要求返回页码，确保生成的大纲包含位置信息

## 依赖项

预期核心依赖：
- PyMuPDF 或 pypdf：PDF 操作
- openai：Python 客户端（配置 Dashscope 端点）
- click 或 argparse：CLI 框架
- pytest：测试框架

## 配置

Dashscope API 凭证配置方式：
- 环境变量（DASHSCOPE_API_KEY）
- 用户目录配置文件（~/.outline-gen/config.yaml）
- 禁止将 API 密钥提交到代码仓库
