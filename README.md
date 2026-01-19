# Outline Generator

基于工作区的 PDF 书籍大纲微调工具。所有书籍统一放在 `data/<book_id>/` 目录下，提供树状浏览与节点合并/拆分操作。

## 安装依赖

```bash
uv sync
```

## 基本用法

### 1. 初始化工作区

```bash
uv run outline-gen init <book_id> --pdf /path/to/book.pdf
```

初始化后目录结构示例：

```
data/
  <book_id>/
    book.pdf
    outline.json
```

如果 PDF 自带书签，会用书签层级作为初始结构；否则创建单一根节点（覆盖全书页码范围）。后续可用 split/merge 进行微调。

### 2. 查看树状结构（含节点 ID）

```bash
uv run outline-gen ls <book_id>
```

输出示例：

```
└─ [1] 书名 (pp 1-240, subtree 1 nodes, leaves 1)
```

叶子节点会显示页数，非叶节点显示子树节点数与叶子数量。

### 3. 合并节点

```bash
uv run outline-gen merge <book_id> <node_id_1> <node_id_2> [<node_id_3>...]
```

要求：节点必须是同一父节点下连续的兄弟节点。

### 4. 拆分节点（调用 LLM）

```bash
uv run outline-gen split <book_id> <node_id>
```

拆分仅支持叶子节点。默认使用配置中的模型和 API Key。

批量拆分所有叶子节点：

```bash
uv run outline-gen split <book_id> --all-leaves
```

## 配置

可选创建配置文件：

```bash
uv run outline-gen init-config
```

配置路径：`~/.outline-gen/config.yaml`。支持字段：

- `dashscope_api_key`
- `model`
- `data_root`（默认 `data`）

也可以通过环境变量提供 API Key：

```bash
export DASHSCOPE_API_KEY="your-key"
```

## 输出文件

- `outline.json`：结构化大纲（节点 ID、页码范围、子树结构）。
- `outline.txt`：缩进文本格式，适合复制到其他工具中生成目录。
