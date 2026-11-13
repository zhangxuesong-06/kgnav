# 计划 v2

先写会失败的测试，再实现；每个任务 2–5 分钟。

- [x] T1 测试：`neighbors()` 四组分类、引用方向、`review=False` 排除回顾边、缺节点（RED）
- [x] T2 实现：`nav.neighbors()` + `Neighbor` 数据类
- [x] T3 测试：CLI `--about` 的输出分组与截断（可只测纯函数 `render_about`）
- [x] T4 实现：`cli.py --about <节点>`，概念组优先、截断带"还有 M 条"
- [x] T5 真实数据跑 5 个种子（记录 / 方法枢纽 / 文件 / 项目文档 / 无轮次归属记录），逐条看
- [x] T6 文档：README 主入口改写、NOTES Day 15、验收表新增"展开"一节
- [x] T7 复查：旧测试全过、开关矩阵 111 次 0 失败、代码审查（子 Agent）修了 1 critical + 6 major
