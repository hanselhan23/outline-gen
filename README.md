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

### 5. 生成叶子节点摘要（调用 LLM）

遍历所有叶子节点，根据节点标题和对应页码文本生成摘要，并写入 Markdown：

```bash
uv run outline-gen summarize <book_id>
```

默认输出目录：`data/<book_id>/summaries/`，文件名为 `leaf_<id>.md`。

### 6. 标签提取（调用 LLM）

遍历所有叶子节点，根据标签模板提取内容，生成 Markdown：

```bash
uv run outline-gen tag <book_id> --template /path/to/tag_template.yaml
```

使用内置模板类型（无需完整路径）：

```bash
uv run outline-gen tag <book_id> --template-type literature
```

默认输出目录：`data/<book_id>/tags/`，文件名为 `leaf_<id>.md`。

生成默认标签模板：

```bash
uv run outline-gen init-tags-template <book_id>
```

### 7. 构建静态站点

基于已生成的 Markdown 目录构建站点：

```bash
uv run outline-gen build-site <book_id> --source tags
```

构建摘要站点：

```bash
uv run outline-gen build-site <book_id> --source summaries
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

## 标签模板格式（YAML）

标签模板是一个 YAML 文件，包含模板名和标签列表。示例：

```yaml
name: 四标签阅读模板
tags:
  - name: 底层设计
    prompt: 提取作者用来搭建论点的核心假设、框架或模型。
  - name: 因果链条
    prompt: 提取作者描述的关键因果机制或推理链条。
  - name: 潜在后果
    prompt: 总结这些观点可能带来的后果、风险或启示。
  - name: 作者金句/改进意见
    prompt: 摘录或改写最具代表性的表述，并给出改进建议。
```

## 内置模板类型

内置模板存放在 `outline_gen/templates/`，可直接通过 `--template-type` 指定：

- `literature`（文学）
- `social_science`（社会科学）
- `philosophy`（哲学）
- `fiction`（小说）
