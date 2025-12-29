# Outline Generator

为 PDF 书籍递归生成详细大纲的命令行工具。

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置 API 密钥

```bash
export DASHSCOPE_API_KEY="your-api-key-here"
```

### 3. 使用

```bash
# 基本用法
uv run outline-gen book.pdf

# 指定深度和格式
uv run outline-gen book.pdf --depth 2 -f md -o outline.md
```

## 命令选项

```
Usage: outline-gen [OPTIONS] PDF_PATH

Options:
  -d, --depth INTEGER         递归层级深度 (默认: 2)
  -o, --output PATH           输出文件路径
  -f, --format [txt|json|md]  输出格式 (默认: txt)
  -m, --model TEXT            使用的模型 (默认: qwen-turbo)
  --api-key TEXT              API密钥
  --init-config               创建配置文件
  --help                      显示帮助
```

## 示例

```bash
# 生成1层详细大纲
uv run outline-gen book.pdf --depth 1

# 生成2层递归大纲，输出为Markdown
uv run outline-gen book.pdf --depth 2 -f md -o outline.md

# 使用不同模型
uv run outline-gen book.pdf -m qwen-plus
```
