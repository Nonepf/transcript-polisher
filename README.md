# 🎙 录音稿自动润色脚本

基于 **SiliconFlow** 的录音稿智能润色工具，支持批量处理，自动分段并保持上下文连贯性。

本脚本由 AI 编写，支持 `txt`，`md` 输入，输出为 `md` 格式。

---

## 📦 安装依赖

```bash
pip install requests
```

---

## ⚙️ 配置 API Key

**方法一：环境变量（推荐）**
```bash
export SILICONFLOW_API_KEY=sk-xxxxxxxxxxxxxxxx   # Linux/macOS
setx SILICONFLOW_API_KEY "sk-xxxxxxxxxxxxxxxx"        # Windows
```

**方法二：命令行参数**
```bash
python run.py --api-key sk-xxxxxxxxxxxxxxxx
```

**方法三：直接修改脚本**  
打开 `transcript_polisher\config.py`，找到 `CONFIG` 字典，将 `"api_key"` 改为你的 Key。

---

## 📁 使用方法

### 1. 准备录音稿

把 `.txt` / `.md` 录音稿文件放入 `recording_raw/` 文件夹：

```
recording_raw/
├── 会议记录_20250301.txt
└── 访谈录音稿.md
```

### 2. 运行脚本

```bash
# 基本用法（使用默认文件夹）
python run.py

# 自定义输入/输出文件夹
python run.py -i my_transcripts -o my_output

# 完整参数
python run.py \
  --api-key sk-xxx \
  --input recording_raw \
  --output recording_polished \
  --chunk-size 1000 \
  --model Pro/deepseek-ai/DeepSeek-V3.2
```

### 3. 查看输出

结果保存在 `recording_polished/` 文件夹，每个文件生成一个 `_polished.md` 文件：

```
recording_polished/
├── 会议记录_20250301_polished.md
├── 访谈录音稿_polished.md
└── 讲座转录_polished.md
```

---

## 📄 输出文档结构

每个润色后的 `.md` 文件包含三个部分：

| 章节 | 内容 |
|------|------|
| **📋 关键信息提取** | 核心主题、关键信息点、行动项、人物/组织、数据时间节点 |
| **✏️ 润色后正文** | 语法纠正、重新排版、书面化处理后的完整文本 |
| **📝 原始文稿（存档）** | 折叠保存原文，方便对比 |

---

## 🔧 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--input` / `-i` | `recording_raw` | 输入文件夹 |
| `--output` / `-o` | `recording_polished` | 输出文件夹 |
| `--api-key` | 环境变量 | SiliconFlow API Key |
| `--model` | `moonshotai/Kimi-K2-Instruct` | 模型名称 |
| `--chunk-size` | `800` | 每段处理字数 |
| `--api-base` | `https://api.siliconflow.cn/v1` | API 地址 |

---

## 🔄 分段与上下文机制

```
原文 (3000字)
    │
    ▼ 按句子边界切割
┌─────────┐  ┌─────────┐  ┌─────────┐
│  段1    │  │  段2    │  │  段3    │
│ 800字   │  │ 800字   │  │ 800字   │
│         │  │ ←150字  │  │ ←150字  │
│         │  │  重叠   │  │  重叠   │
└─────────┘  └─────────┘  └─────────┘
    │              │              │
    ▼              ▼              ▼
 润色+摘要  →  润色+摘要  →  润色+摘要
  (摘要传入下一段作为上下文)
```

- **重叠(overlap)**：相邻段共享 150 字，避免句子被截断
- **摘要传递**：每段 LLM 输出摘要，作为下一段的上下文提示
- **最终合并**：所有段拼接成完整文档
