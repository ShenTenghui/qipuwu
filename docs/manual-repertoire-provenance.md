# 本人录谱模块的源码来源

本次公开的是棋谱屋实际开发的“手动录谱→自主纳入→冻结发布→按选中边训练”核心。它与原有训练编排精选模块并列，原README、示例、检查和历史均保留。

## 提取方式

- `app/repertoire_training.py`、`app/repertoire_editor.py`、`app/repertoire_graph.py`、`app/training_terminal.py`、`scripts/xq_notation.py`：从本地项目同名源码逐字节复制；本次没有导出它们读取的个人库、棋谱或核验数据。旧固定谱兼容入口仍在代码中，但仓库不附固定谱材料。
- `scripts/opening_classifier.py`：仅提取原文件的 `_PIECE`、`_screens`、`_geometry`、`_in_check`。这些是棋子移动与将帅安全的纯规则函数。函数内容保持原样，新增模块说明；ECCO调用、DLL载入、分类目录、子进程和相关数据均未提取。
- `web/repertoire-training/editor-model.js`：最终冻结的独立编辑状态控制器逐字节复制；只依赖注入的API和存储，不附带整套产品页面。`tests/editor-controller.test.cjs`为该控制器独立编写合成API测试。
- `tests/test_manual_repertoire.py`、`examples/manual_repertoire_demo.py`：为公开模块新写的合成用例和可执行示例。只使用构造的兵步、宫内往返和分支，不复制本地实战、教材主线、真实草稿或个人回答。

每个本地源文件、导出文件的SHA256与提取函数列于[机器可读来源清单](manual-repertoire-provenance.json)。该清单记录的是最终冻结后的真实源码身份，不把文件修改时间当作Git历史或贡献日期。

## 可验证边界

合成测试覆盖草稿默认不纳入、多个本人答案、实际路线应手、分支完整性、显式终点、10回合、版本保护、转序来路隔离、修改版本检查、持久幂等及并发。

本地完整产品另外具有网站、引擎、采集与个人材料。本仓库的命令行示例不宣称重现整套产品；也不因练习成功宣称掌握、棋力迁移或教学有效。
