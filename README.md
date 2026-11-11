# Branchback

Branchback 是供开发 Agent 使用的通用探索工具。它以问题树保存上层目标、局部实验、证据和适用范围，并在返回时恢复父层背景。它适用于单人本地研究，支持多个开发会话、Agent 和 Git worktree 并行。

工具由 [Skill](SKILL.md) 与 Python 标准库 CLI 组成，不依赖被开发的应用、模型 API、数据库或 hs-delivery。研究可以包含原型实现，交付过程中也可以重新进入研究；工具不强制划分阶段。

## 使用

环境：Python 3.10+，Linux／WSL／macOS。Git 项目需要 Git；原生 Windows 尚未提供文件锁实现。

将仓库链接到个人技能目录：

```bash
mkdir -p ~/.agents/skills
ln -s ~/proj/branchback ~/.agents/skills/branchback
```

目标已存在时应先核对，不覆盖其他技能。Codex 支持用户技能目录及符号链接，见[官方文档](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)。可显式调用 `$branchback`，也可由宿主按技能描述发现。

```bash
python3 ~/.agents/skills/branchback/scripts/branchback.py --repo /path/to/project read
python3 ~/.agents/skills/branchback/scripts/branchback.py --help
```

完整命令、JSON 输入和并行流程见 [CLI 参考](references/cli.md)。实验事实优先引用现有产物，节点内部无需逐轮更新记录。

可用 `plan` 提前把问题挂到指定父节点，当前位置保持不变；选中后以 `enter` 开始。节点区分 `planned`、`open`、`paused`、`closed` 和 `abandoned`。`abandon` 保存放弃原因，`restore` 恢复待续问题；`handoff` 只暂停自己的 session，让其他执行者继续。

关闭父节点时，子树只能保留计划、已关闭或已放弃的节点，计划范围须在 `uncovered` 中说明。`open` 或 `paused` 后代必须先处置。旧树可读取，成功写入时升级为 schema 2，旧状态与历史不会被自动重新分类；后续使用更新后的 CLI。

状态位于 `~/.branchback/`；`projects.json` 维护仓库公共 Git 目录与 `projects/<项目名>-<短ID>/` 的关联。各 worktree 共用状态，各会话保留自己的位置。测试用 `--home` 或 `BRANCHBACK_HOME` 隔离状态。

## 本地可视化

```bash
python3 scripts/bb_web.py
```

打开 http://127.0.0.1:8765。左侧按项目展开探索树，支持搜索和隐藏已结束 / 已放弃的树。右上以带箭头的树图展示父子问题，默认使用 100% 大小；超过 20 个节点的树初始收起深层分支。可以折叠分支、聚焦节点、展开全树、适应全图、缩放、拖动空白处平移，或扩大图区。未选择节点时，界面优先为图区分配空间。

点击节点后，右下展示最新结论、会话位置、问题范围、结果和评估；详情可独立扩大。搜索、折叠或聚焦隐藏当前节点时会显示提示，可一键定位回图中。历史以时间排序，每次展示 20 条，原始 JSON 可单独展开。

地址栏保存项目、树、节点和聚焦分支位置，可复制节点链接，或在浏览器刷新、前进和后退时恢复。定位、聚焦和搜索会恢复 100% 阅读比例；扩大模式中的跨区域操作会自动恢复分区，显露目标内容。HTTP(S) 来源可打开，本地文档和证据引用可复制；页面不直接读取引用文件。点击“刷新数据”读取 CLI 的最新变更。

服务只监听本机地址，所有接口只读，不创建或迁移状态。默认读取 `BRANCHBACK_HOME` 或 `~/.branchback`，无需额外依赖。可用 `--home /path/to/state --port 8766` 指定数据目录和端口；终端按 Ctrl+C 停止。

## 开发与验证

```bash
python3 -m unittest discover -s tests -v
```

使用说明与命令契约见 [Skill](SKILL.md) 和 [CLI 参考](references/cli.md)。原始输入、讨论、决定及开发验证资料保存在本地 `.dev_docs/`，不随公开仓库发布。

工具校验自身操作并恢复背景，不能证明模型理解正确或强制约束其他工具。对研究偏移的长期改善仍需实际使用观察。
