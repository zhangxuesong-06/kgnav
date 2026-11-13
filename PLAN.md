# 计划

每个任务 2–5 分钟，先写会失败的测试，再写实现。顺序即提交顺序。

- [x] T1 测试：同会话链只连同 sid 的相邻轮（`test_build.py`，RED）
- [x] T2 实现：导出器补 `session` 边 + 证据
- [x] T3 测试：查询日志字段完整、坏行不影响导出（RED）
- [x] T4 实现：CLI 记查询 → `data/queries.jsonl`
- [x] T5 测试：共现边只连"问过两次"的端点、跳过已连的对（RED）
- [x] T6 实现：导出器读日志生成 `cooccur` 边 + 计数证据
- [x] T7 CLI：`--no-session` / `--no-cooccur` / `--no-log`，header 如实显示
- [x] T8 回归：78 组开关组合、`test_nav.py` 不变量、真实图前后对比
- [x] T9 文档：README / NOTES / 验收表写清新边类与开关
- [x] T10 代码审查：派子 Agent 按严重度报问题，6 条 major 全部修完
- [x] T11 测试：手工标签四种键写法、坏键、过大标签（RED）
- [x] T12 实现：`data/tags.json` → tag 边 + 证据 + `--no-tag` + 12 节点上限
- [x] T13 文档与真实数据验证（临时标签，不写用户库）
- [x] T14 `tags.py` 预览（id → 标题）、标签格式统一为「标签 → 节点」
- [x] T15 修：已同标签的一对不再重复生成共现边（测试护栏）
