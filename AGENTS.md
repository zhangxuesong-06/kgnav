# kgnav · harness 协作入口

适用于在本仓库接手工作的 Codex、OpenCode、DSH、WorkBuddy、ZCode 等 harness。

## 开工与收工

- 开工先读 `kgnav-handoff.md` 的“最新工作报告”、`README.md` 和 `NOTES.md`，
  再核对实际目录、分支与 Git 状态。旧报告里的“当前”“Day 1”和测试数字是历史记录。
- 两个有效项目目录为 `D:\DSH WorkSpace\tool\kgnav` 与
  `C:\Users\HUAWEI\Desktop\work\记忆`。旧临时工作树已作废，不再写入代码或报告；
  原始目录无权限时停下并记录阻塞，不用旧工作树代替。
- 完成代码、配置、测试或接口改动后，必须更新 `kgnav-handoff.md`：
  日期、改动、实际执行的命令及结果、未验证项、待办和是否提交或部署。
- `kgnav-handoff.md` 是各 harness 共用的本地工作报告，已列入 `.gitignore`，
  仍被跟踪时须先用 `git rm --cached -- kgnav-handoff.md` 取消跟踪并保留本地文件。
  持续维护但不提交报告正文，不要用 `git add -f` 强行加入。`AGENTS.md` 继续纳入版本管理。
- 涉及记忆插件接口时，同时更新对方仓库的 `HANDOFF.md`；无法写入时记下待同步项，
  不声称已同步或已通知正在运行的其他会话。
- 源码、导出快照与已安装副本分别核对。不要把 Git 提交、源码更新或报告提醒当作已部署。

## 方法词表接口边界

- 方法名及别名仅由记忆侧显式维护，kgnav 消费既有 `--methods` JSON；
  本仓库示例不是第二份维护源。
- 普通同义词不自动升级为方法，共现不当作语义关系，词面命中只表示“提到”；
  不自动替使用者断言标签。
- 本接口只用仓库合成数据验证；端到端入口在记忆侧 `agent-memory/test-kgnav.mjs`。
  未经另行授权，不读取或提交私人记忆、已有私人图、真实标签或查询日志，
  不为更新报告运行真实库维护命令。
