在你的独立分支上实现假设 {id}，父版本为 {parent}。
可写：engine/ 下 {touched_modules} 列出的目录，以及 params/schema.json 的新增条目。
禁止：CONSTRAINTS.md 列出的一切。先读它。
流程：读 specs/ 相关规格，实现，本地跑 T0，通过后提交。
T0 不通过不要提交。实现不了就写明原因后停止，不要换一个假设硬做。
输出：diff 摘要，新增参数清单，你认为可能出问题的地方。
