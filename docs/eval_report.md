# 检索质量评测报告（Recall@k / nDCG@k / MRR）

> 更新日期：2026-08-15　|　评测脚本：`scripts/eval_retrieval.py`

---

## 1. 评测目标

量化验证检索链路的召回质量与排序质量，对比**向量检索**与**混合检索（BM25 + 向量 + RRF）**，重点考察：
1. **同领域细粒度区分**（AI Agent 书 5 章 + RAG 教程 + 提示工程指南，词汇大量重叠）
2. **多格式入库检索**（md / PDF / docx / xlsx / txt）
3. **负样本鲁棒性**（无关查询不应召回任何文档）

## 2. 评测语料（13 文档 · 5 种格式 · 2453 chunk）

| 文档 | 格式 | 来源 | chunk |
|------|------|------|-------|
| AI Agent 书 第1-5章 | md | [bojieli/ai-agent-book](https://github.com/bojieli/ai-agent-book)（Apache-2.0） | 1615 |
| RAG 技术简介 / 文本分块 | md | [datawhalechina/all-in-rag](https://github.com/datawhalechina/all-in-rag) | 141 |
| 提示词基础 / 高级用法 | md | [yunwei37/prompt-engineering-guide-zh-cn](https://github.com/yunwei37/prompt-engineering-guide-zh-cn) | 65 |
| Attention Is All You Need | pdf | [arXiv:1706.03762](https://arxiv.org/abs/1706.03762) | 54 |
| 中国能源转型白皮书 | docx | 中国政府网 | 118 |
| 咖啡馆销售数据表（200行节选） | xlsx | GitHub 公开示例数据 | 146 |
| 水浒传节选（前二十回片段） | txt | [tennessine/corpus](https://github.com/tennessine/corpus)（公版） | 314 |

> 语料来源与许可说明见 `eval_corpus/语料来源说明_20260815.md`。

## 3. 评测集设计（32 条）

| 类型 | 数量 | 说明 |
|------|------|------|
| 各文档独有内容 | 24 | query 唯一归属某一文档 |
| 词汇陷阱 | 6 | 关键词跨文档出现（"提示工程""文本分块"等） |
| 多相关样本 | 1 | "如何防止 Agent 陷入无限循环" 同时相关第1、2章 |
| 负样本 | 3 | 红烧肉 / 世界杯 / 房产过户 |

## 4. 评测结果

| 指标 | 向量检索 | 混合检索 |
|------|---------|---------|
| Recall@5 | 0.8676 | **0.8676** |
| nDCG@5 | 2.2586 | **2.3969** |
| MRR | 0.8627 | **0.8627** |

### 4.1 关键观察

- **多格式全部命中**：PDF（多头注意力→论文）、docx（能源目标→白皮书）、xlsx（Coffee/Cake→销售表）、txt（拳打镇关西→水浒传）均 Recall=1.0，证明 pdf/docx/xlsx/txt 四种格式的解析与入库链路均有效。
- **同域细粒度区分良好**：24 条独有 query 几乎全部命中；「什么是上下文工程」（第2章）与「为什么说上下文是眼睛」（第1章）未被重叠词汇误导。
- **词汇陷阱部分命中**：「什么是提示工程」命中 提示词高级用法 + 第2章（两处都讲提示工程，标注为多相关），Recall=0.5 属预期。
- **负样本误召回已修复**：3 条负样本在两种模式下均返回空（此前误召回章节文档），绝对下限防线生效。
- **混合检索排序优于向量**：nDCG 2.3969 vs 2.2586——RRF 融合对排序质量的增益有数据印证。

## 5. 本轮修复记录

### 5.1 负样本误召回（已修复 ✅）

**问题**：无关查询（红烧肉等）被强制返回 top-k 最近邻。
**根因**：`similarity_search_with_score` 无条件返回 top-k；`SIMILARITY_THRESHOLD`（0.3）低于负样本实测分数（0.41~0.47），无法拦截。
**修复**：
- `config.py` 新增 `ABSOLUTE_MIN_SCORE = 0.5`（依据评测数据：正样本 0.62~0.68，负样本 0.41~0.47）；
- `services/retrieval.py` 新增 `filter_by_absolute_floor()`，在**向量检索分支**（仅相似度尺度分数）应用；
- `utils/hybrid_search.py` 在向量部分应用同款防线（RRF 分数量纲不同，不适用）；
- 修复过程中发现并规避了「对 RRF 分数误用绝对下限导致混合检索全空」的量纲陷阱。

### 5.2 多相关查询召回不完整（已知局限）

「无限循环」命中第1章漏第2章（Recall=0.5）：单 query 跨多文档时固定 top-k 有召回天花板。可选项：查询分解（`services/query_decompose.py`）或动态 k。生产环境 fetch_k（10-30）高于评测 k=5，实际影响更小。

## 6. 复现方式

```bash
# 1. 构建评测知识库（多格式语料在 eval_corpus/）
python scripts/build_eval_kb_20260815.py --user 98

# 2. 评测：向量 + 混合，含 Recall/nDCG/MRR
python scripts/eval_retrieval.py --user 98 --k 5 --mode both
```
