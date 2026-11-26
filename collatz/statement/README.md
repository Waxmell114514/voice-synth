# statement/：冻结的命题与裁判

- `Statement.lean`：`CollatzConjecture.collatzStep` 与 `CollatzConjecture.CollatzConjecture`。
  定义逐字取自 google-deepmind/formal-conjectures 的 `FormalConjectures/Wikipedia/CollatzConjecture.lean`
  （main 分支，2026-11-26 拉取，Apache-2.0，Copyright 2025 The Formal Conjectures Authors），
  原文件整份保存在 `upstream/`。上游把猜想写成 `theorem collatz_conjecture (n : ℕ) (hn : n > 0) : ∃ m, … := by sorry`，
  这里把同一个类型命名为 `Prop`；`statement_eq_upstream` 用 `rfl` 证明二者是同一个命题。
  上游用 `import FormalConjecturesUtil`（它导入整个 Mathlib），这里直接 `import Mathlib`，
  mathlib 版本与上游 lake-manifest 相同（v4.33.1，0df444a3…）。
- `verify.sh <定理全名>`：唯一的裁判，实现在 `verify.py`。首行 PASS 或 FAIL。
- `Inspect.lean.in`：verify.py 用来查询定理信息的 Lean 模板。
- `Final.lean`：终局检查模板。verify.py 把 `CLAIMED_PROOF` 换成 `@<定理>` 后编译；
  能编译就说明该定理的类型就是冻结的 `CollatzConjecture`。

## 对 bootstrap“验证接口”的具体落实
1. `eval.lock` 记录本目录全部文件和 `lakefile.toml`、`lean-toolchain`、`lake-manifest.json` 的 SHA-256。
   多出、缺少、改动任何一个都 FAIL。
2. 构建：`lake build`（Statement 与 Lib 两个库），非零退出或日志里出现 “declaration uses sorry” 都 FAIL。
3. 公理：`collectAxioms` 的结果必须是 {propext, Classical.choice, Quot.sound} 加上 `routes/gaps.tsv`
   登记过的缺口的子集。Lib 里声明的每个 `axiom` 都必须登记，不论是否被这个定理用到。
4. 命题：定理必须是 Lib 模块里声明的 `theorem`；其类型里出现的 Lib 常量不能是 axiom 或 opaque；
   Lib 里任何常量的末段名不得是 `collatzStep`、`CollatzConjecture`、`statement_eq_upstream`（防局部重定义）。
   输出 `claim: CollatzConjecture` 当且仅当 Final.lean 模板能编译；
   `final: PASS` 当且仅当 claim 成立且不依赖任何缺口。只有 `final: PASS` 才算 T5。
   一个关于别的命题的定理可以 PASS，但 claim 是 `lemma`，它证明的只是它的类型所说的东西。
5. 源码扫描（去掉注释和字符串后）：`sorry`、`admit`、`native_decide`、`native`、`unsafe`、`implemented_by`、
   `extern`、`debug.` 选项、`skipKernelTC`、`ofReduceBool`/`reduceBool`/`trustCompiler`、
   `addDecl`/`addAndCompile`/`modifyEnv`/`setEnv`/`Kernel.`；import 只许 Mathlib、Batteries、Aesop、Qq、
   Plausible、Lean、Std、Init、Statement、Lib；`lib/` 下 Lib 库以外的 .lean 文件一律 FAIL。
6. `leanchecker` 把 Statement 和全部 Lib 模块的声明在内核里重放一遍（不带 `--fresh`，Mathlib 本身不重放）。

## 缺口登记 routes/gaps.tsv
每行：`公理全名<TAB>L 或 O<TAB>路线 id<TAB>一句话陈述`，`#` 开头为注释。
L 类是 KNOWN 定理（附出处），O 类是开放命题。
