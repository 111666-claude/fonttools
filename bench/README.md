# gvar 实例化分配优化 — 可重放基准与验证脚本

所有脚本均通过 `PYTHONPATH=Lib` 运行在仓库本地代码上，并使用 `python3 -I`
隔离模式，避免从脚本目录加载意外模块。

## 脚本

- `bench_gvar.py` — 主基准。构造每个字形含 120 个 variation tuple 的合成
  glyf+gvar 字体，连续完整实例化 50 次，报告：
  - 热路径 `TupleVariation.__new__` / `scaleDeltas` 调用计数（应均为 0）
  - 实例化阶段（不含 deepcopy）的中位/最小/最大/平均墙钟耗时
  - `tracemalloc` 实例化阶段峰值分配
  - 每次运行的逐点坐标快照自检（重复结果必须一致）
- `trace_alloc.py` — 用 monkeypatch 直接计数热路径对象创建与 rescale。
- `scalar_equiv.py` — 5000 组随机 tent/pin，验证 `supportScalar` 直算标量
  与旧的逐轴 rebase 流水线输出等价（gvar 含 IUP、cvar 含 None）。
- `numeric_tolerance.py` — 3000 组、每组最多 30 个重叠 tuple 的严格数值对比，
  快速路径与旧流水线模拟结果的最大绝对浮点误差应为 0.0（位级一致）。
- `correctness.py` — 覆盖分数 delta、稀疏 IUP、复合字形、phantom points、
  长度不匹配错误、cvar None 语义，输出 JSON 快照供新旧实现逐字节 diff。
- `deep_snap.py` — 真实测试字体完整实例化后的坐标 JSON 快照。

## 重放命令

```sh
# 性能与分配（新实现）
PYTHONPATH=Lib python3 -I bench/bench_gvar.py

# 与旧基线对比
git stash
PYTHONPATH=Lib python3 -I bench/bench_gvar.py
git stash pop

# 正确性逐点 diff
PYTHONPATH=Lib python3 -I bench/correctness.py /tmp/new.json
git stash
PYTHONPATH=Lib python3 -I bench/correctness.py /tmp/old.json
git stash pop
diff /tmp/old.json /tmp/new.json   # 应无输出

# 数值等价属性测试
PYTHONPATH=Lib python3 -I bench/scalar_equiv.py
PYTHONPATH=Lib python3 -I bench/numeric_tolerance.py
```

## 实测结果（本机，Python 3.14.4）

| 指标 | 旧基线 | 新快速路径 |
| --- | --- | --- |
| 中位耗时（120 tuple/字形 × 24 字形 × 50 次） | ~21.4 ms | ~12.5 ms（**-42%**） |
| 热路径 `scaleDeltas` 调用/实例 | 1440 | 0 |
| 热路径中间 `TupleVariation`/坐标列表分配 | 每 tuple 每轴一次 | 0 |
| tracemalloc 实例化峰值 | 3045 KiB | 2645 KiB（-13%） |
| 坐标数值差异 | — | 位级一致（误差 0.0） |
