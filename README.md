# Outline Generator

为 PDF 书籍递归生成详细大纲，并基于大纲用大模型重写整本书（MkDocs + mkdocs-material 排版）的命令行工具。

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置 API 密钥

```bash
export DASHSCOPE_API_KEY="your-api-key-here"
```

### 3. 初始化配置（可选）

```bash
uv run outline-gen init-config
```

这会在 `~/.outline-gen/config.yaml` 下创建默认配置，包含：

- `dashscope_api_key`
- `model`（默认 `qwen-turbo`）
- `default_depth`（默认 2）
- `output_format`（默认 `txt`）
- `data_root`（默认 `data`）

也可以直接通过环境变量提供 `DASHSCOPE_API_KEY`。

### 4. 使用

推荐使用 “data 目录 + 书名子目录” 的工作流。

#### 4.1 目录准备

假设书名为 `uc`，建议目录结构：

```bash
data/
  uc/
    uc.pdf
```

#### 4.2 一条命令完成：生成大纲 + 重写整本书

```bash
# 在 data/uc/ 里查找 uc.pdf
# 1) 生成 data/uc/uc.outline.txt
# 2) 在 data/uc/uc/ 下生成 MkDocs 项目（material 主题）
uv run outline-gen book uc
```

命令执行后，将得到：

- `data/uc/uc.outline.txt`：递归大纲（txt）
- `data/uc/uc/mkdocs.yml`
- `data/uc/uc/docs/index.md`
- `data/uc/uc/docs/...`（按原书标签层级拆分的精简版中文正文）

然后可以进入该目录，使用 MkDocs 构建 / 预览：

```bash
cd data/uc/uc
mkdocs serve   # 或 mkdocs build
```

#### 4.3 仅生成大纲（不重写）

```bash
# 为任意 PDF 生成递归大纲
uv run outline-gen outline path/to/book.pdf

# 指定深度和输出格式
uv run outline-gen outline path/to/book.pdf --depth 2 -f md -o outline.md
```

## 命令概览

```bash
Usage: outline-gen [COMMAND] [OPTIONS] ...

Commands:
  init-config  创建默认配置文件 (~/.outline-gen/config.yaml)
  outline      为指定 PDF 生成递归大纲
  book         以 data/<book_name>/<book_name>.pdf 为输入，一键生成大纲并重写全书
```

### `outline-gen book` 主要参数

- `book_name`：书名/文件夹名，例如 `uc` → 使用 `data/uc/uc.pdf`
- `--data-root`：数据根目录（默认 `config.data_root` 或 `./data`）
- `--depth`：递归大纲层级（默认 `config.default_depth`，通常为 2）
- `-m, --model`：使用的模型（默认 `config.model`）

### `outline-gen outline` 主要参数

- `pdf_path`：PDF 文件路径
- `--depth`：递归层级深度
- `-o, --output`：输出路径（默认 `<pdf>.outline.txt`）
- `-f, --format`：输出格式 (`txt` / `json` / `md`)
