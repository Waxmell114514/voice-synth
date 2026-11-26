# atlas/ 数据格式

每个 Cartographer 写自己的领域目录 `atlas/domains/<领域id>/`，互不覆盖；orchestrator 合并到 atlas/ 顶层。

## nodes.jsonl（每行一个结果）
```json
{"id": "N-D2-0007", "domain": "D2", "kind": "theorem | lemma | conjecture | obstruction | method | survey",
 "statement": "从原文逐字抄的陈述，含全部条件；LaTeX 可以",
 "notation": "陈述用到的记号约定（原文逐字）",
 "source": {"authors": "…", "year": 1990, "title": "…", "venue": "…", "volume_pages": "…",
            "theorem_no": "Theorem 2.3", "page": "p. 17（PDF 第 19 页）", "url": "…", "arxiv": "…", "version": "v2"},
 "read_status": "已读原文 | 仅摘要 | 未找到",
 "label": "KNOWN | SKETCH | NUMERICAL | HEURISTIC | SPECULATION",
 "excerpt": "atlas/sources/<文件>，原文摘录所在文件和行号",
 "relates_to": ["N-D1-0003"], "rows": ["停时有限"], "cols": ["Baker 对数线性型及 Rhin 界"],
 "notes": "与 Collatz 的关系，一两句；判断性的内容标 HEURISTIC",
 "added_by": "cartographer-D2", "added_at": "2026-11-26T12:00:00Z"}
```
只有 `read_status = 已读原文` 且 `label = KNOWN` 的条目能当前提。

## edges.jsonl
```json
{"from": "N-D2-0007", "to": "N-D1-0012", "type": "implies | uses | generalizes | special_case | obstructs | analogous",
 "note": "…", "source": "出处或 'orchestrator 推断（HEURISTIC）'"}
```

## obstructions.md
每条：编号、它挡住什么（哪一行 × 哪一列，或哪种论证）、精确原因、出处（已读原文的）、是“全部难点”还是“技术细节”。

## matrix.json
`{"rows": [...], "cols": [...], "cells": {"<行>|<列>": {"status": "未查|文献已做|障碍明确|可试|已试", "evidence": "…", "nodes": [...], "ledger": [...], "by": "…", "at": "…"}}}`
“未查”以外的状态必须有 evidence（出处或账本 id）。

## sources/
原文摘录：`<第一作者><年份>-<短名>.txt`，内容是 pdftotext 的相关页（逐字），文件头写完整出处、URL、版本、页码范围、读取时间。
整篇 PDF 不进 git。

## ERRATA.md
bootstrap 种子文献线索或别人条目里的错误：原写法、实际情况、证据。
