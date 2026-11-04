# 精选代码的来源与变动

本包为棋谱屋的 **source showcase**。公开范围是训练编排的一个完整代码切面，以及为其新写的合成演示与测试；不是完整产品发行包，也不表示整个私人项目已经开源。

机器可核对的相对来源路径、原文件 SHA-256 与打包文件 SHA-256 见 `source-provenance.json`。记录日期为 2026-11-04。原项目目录、个人路径、账号、实战资料、数据库、缓存及实验材料均未打包。

| 发布文件 | 来源与实际变动 |
| --- | --- |
| `app/training_schedule_v7.py` | 从同名原路径按字节复制；没有改选择策略、权重、默认比例或函数实现 |
| `app/training_schedule_v6.py` | 仅从原文件第 30–89 行摘出 `_separate_games`，函数实现保留；新增说明头和 `lru_cache` 导入。它不是完整历史 v6 实现 |
| `app/__init__.py` | 新增空包说明，便于独立导入；无启动逻辑 |
| `examples/schedule_demo.py` | 新增；构造合成题库，展示 6 新 4 旧、双向补位、来源分散及受控权重比较 |
| `examples/serve_schedule_lab.py`、`examples/schedule_lab.html` | 新增；只提供合成训练编排的本机交互界面，默认随机端口；没有引擎、数据库、采集、文件写入或原项目服务调用 |
| `tests/test_schedule.py` | 原 `scripts/test_training_schedule_v7.py` 的选题性质检查作为参考；移除依赖完整历史 facade 的检查，重写为只依赖本包和合成数据的测试，补充 helper 行为与示例输入验证 |
| `tests/test_lab_http.py` | 新增；使用操作系统分配的独立本机端口，检查页面/API、输入错误和文件路径边界 |

## 实现边界

- `N` 是从未完成过答题的新题，`R` 是已完成过答题的旧题；兼容输入 `F` 在 v7 内归入旧题。本包演示只构造 N/R。
- 输入候选由调用方提供。模块对基本字段做筛选，不验证棋局、答案或引擎证据是否可靠。
- 6 新 4 旧、等待覆盖和近期结果权重是产品策略；不声称它们是已验证的最优学习间隔或比例。
- 权重影响抽样，等待覆盖和配额也参与选择。来源分散是软偏好，不能承诺任何题库都覆盖十个来源。
- 固定种子和同一候选快照支持复现；生产里的持久化、并发提交、测量和用户界面不在本包中。
- 这两份精选模块只依赖 Python 标准库；交互页同样无外部脚本、字体或图片依赖。此处没有打包 Pikafish、NNUE、ECCO、Xiangqiground 或教材材料。

## 本包运行

在仓库根目录执行：

```text
python -B examples/schedule_demo.py --scenario all
python -B examples/schedule_demo.py --scenario balanced --json
python -B -m unittest discover -s tests -v
python -B examples/serve_schedule_lab.py
```

最后一条打印其本机 URL；手动打开即可，按 Ctrl+C 停止。可通过 `--port` 指定独立端口；8642 被显式禁止，避免与完整产品混用。启动与测试只引用此公开副本。

## 使用许可

本仓库尚未指定开源许可证。
