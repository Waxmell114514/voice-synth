# 评估器对引擎的要求（阶段 0 定义，随 eval/ 冻结）

## 1. CLI（MISSION.md 固定接口）
```
python -m engine.synth --text "你好" --seed 0 --params params/x.json --out a.wav
python -m engine.synth --pinyin "ni3 hao3" --seed 0 --params params/x.json --out a.wav
```
- `engine/synth.py` 必须提供 `main(argv: list[str] | None = None) -> int`，`python -m engine.synth`
  只是 `sys.exit(main())`。评估器为了速度在常驻 worker 进程里调用 `main(argv)`，
  语义必须与命令行调用完全相同；评估器每次运行都会抽一条用真正的子进程重跑并逐样本比对，
  不一致则整次评估作废（报 `nondeterministic`）。
- `main` 不得依赖跨调用的全局可变状态（JIT 缓存除外）。
- 拼音输入格式：空格分隔，数字调号 1–5（5 为轻声），ü 写作 `v`。评估器给的是**本调**，
  变调由引擎负责。
- `--params` 指向的文件视为显式输入，可以位于任何目录（T0 和优化器会传临时文件）；
  除此之外引擎只能读 engine/ 和 params/（CONSTRAINTS 第 6 条）。

## 2. T0 钩子：`engine/t0_api.py`
```python
FS: int                     # 引擎内部采样率
def tube_impulse_response(area_cm2, length_cm, n_samples) -> np.ndarray
    # 用引擎实际的声道代码（同一个 Kelly-Lochbaum 散射与延迟实现），但两端取**理想终端**：
    # 声门端闭合（全反射），唇端为理想开口（压力反射 −1），关闭辐射阻抗、末端修正和可屈服声壁；
    # 均匀分布的常数壁损耗可保留。在声门端注入单位冲激，返回唇端输出（采样率 FS）。
    # 本测试只检验散射与延迟的实现是否正确；辐射和声壁模型是否有益由 T1–T4 判断。
    # （2026-11-24 经人批准修改，见 proposals/001-t0-uniform-tube-vs-radiation.md，方案 C）
    # area_cm2 为从声门到唇的各段面积，均匀分段，总长 length_cm。
def zero_input_energy(params_path, n_samples, seed) -> np.ndarray
    # 用 params 的声道配置，把声道内部状态初始化为由 seed 决定的随机值，
    # 之后输入恒为 0，返回每个采样点的声道总存储能量（行波能量按面积加权之和）。
```
Critic 须确认钩子走的是与 synth 相同的代码路径，不是另写的理想模型。

## 3. params/schema.json
```json
{"params": [
  {"name": "lf_rd", "meaning": "LF 模型 Rd 形状参数", "unit": "1",
   "min": 0.3, "max": 2.7, "shape": []}
]}
```
`shape` 为 `[]` 表示标量，`[n]` 或 `[n, m]` 为数组；参数总数 = 各条目元素数之和，
不超过 config.param_cap。参数文件格式：`{"values": {"lf_rd": 1.0, ...}}`。
T0 会生成"全部取 min""全部取 max"和若干固定随机角点的参数文件测试稳定性。
