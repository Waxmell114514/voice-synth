# 阶段 0.1 预检报告（2026-11-26，UTC 09:47 记录）

仓库位置：`bootstrap.md` 放在 voice-synth 仓库的 `collatz/` 子目录里，不是空仓库。
本舰队把 `collatz/` 当作仓库根目录，所有路径（statement/、atlas/、eval.lock……）都相对 `collatz/`。
voice-synth 原有文件一律不动。开发分支 `claude/bootstrap-phase-0-svf0qf`。

| 项目 | 结果（均来自命令输出） |
|---|---|
| git | 2.43.0 |
| CPU / 内存 | 4 核 / 15 GB，无 swap |
| 磁盘 | 装完 mathlib 缓存后可用 50 GB（`.lake/` 占 7.6 GB） |
| elan | 4.4.0（GitHub release 直链下载成功；github.com 的 HTML 页面返回 403，下载直链可用） |
| Lean | 4.33.1（commit 819816b），从 releases.lean-lang.org 安装 |
| mathlib | tag v4.33.1 = 0df444a360eaa60ab8c11dca51a86af692955474，与 formal-conjectures 主分支 lake-manifest 的 mathlib rev 相同；依赖包 rev 也全部相同 |
| mathlib 缓存 | `lake exe cache get` 从 lakecache.blob.core.windows.net 下载 8690 个文件，用时 1 分 26 秒 |
| 构建冒烟测试 | `import Mathlib` + `decide` + `#print axioms` 用时 5.5 秒，正常 |
| 独立检查器 | 工具链自带 `leanchecker`，可用于 verify.sh 第 6 步 |
| 子 agent 并行 | 可用。实测子 agent 获得独立 git 工作树（`.claude/worktrees/agent-…`）和独立分支 |

## 文献访问（HTTP 状态码，带浏览器 UA）
| 来源 | 结果 |
|---|---|
| arXiv 摘要页、PDF、export API | 200，PDF 可下载 |
| zbMATH、Numdam、Project Euclid、JSTOR 落地页、Springer 落地页 | 200（JSTOR 和 Springer 全文多半需订阅，逐篇再试） |
| Crossref API | 200，可用来核对书目信息 |
| OEIS、Wikipedia、erdosproblems.com、bbchallenge.org 及其 wiki | 200 |
| raw.githubusercontent.com、github.com 上的 git 克隆 | 可用（formal-conjectures 原文件已取到） |
| Taylor & Francis（Amer. Math. Monthly）、ScienceDirect、Zenodo、phys.org、Lagarias 的密歇根主页 | 403 |
| web.archive.org、eudml.org、ericr.nl | 连接失败 |
| Semantic Scholar API | 429（限流） |

影响：
- Amer. Math. Monthly 上的 Lagarias 1985 等期刊论文多半拿不到出版社全文。arXiv 上有的（Lagarias 两卷注释书目、
  Tao 1909.03562 等）可以读。拿不到的条目在图谱里标“仅摘要”或“未找到”，不能当前提。
- `config.atlas.min_nodes_read_in_full: 300` 很可能达不到。0.5 按实际能读到的全文量改一次这个数（bootstrap 允许），
  并把原因写在这里。
- 盗版站点（sci-hub 等）不使用。预检时对它们的探测被权限系统拦下，这样处理是对的。
- 文献线索里的“事实注记”（phys.org/AFP）本容器打不开 phys.org，未能重新核对。它不是任何定理的前提。

## 并行与资源
- `max_parallel_workers: 4`，正好 4 核。Lean 构建是 CPU 和内存密集型，4 个 Prover 同时 `lake build` 时
  内存（15 GB）可能吃紧，实测后再调。
- 子 agent 的工作树是整个 voice-synth 仓库的副本，不含 `.lake/`（未跟踪）。每个 Prover 工作树要么再拉一次
  mathlib 缓存（约 7.6 GB、1.5 分钟），要么把 `.lake/packages` 软链接到主检出。磁盘 50 GB，
  4 个工作树各拉一次也放得下；默认用软链接，只读共享。

## 结论
Lean、mathlib、并行子 agent 都可用，arXiv 可用。阶段 0 继续，不需要人提供文件。
需要人知道的偏差：期刊全文访问有限，图谱的“全文已读”下限会在 0.5 按实际情况下调一次。
