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

状态位于 `~/.branchback/`；`projects.json` 维护仓库公共 Git 目录与 `projects/<项目名>-<短ID>/` 的关联。各 worktree 共用状态，各会话保留自己的位置。测试用 `--home` 或 `BRANCHBACK_HOME` 隔离状态。

## 开发与验证

```bash
python3 -m unittest discover -s tests -v
```

使用说明与命令契约见 [Skill](SKILL.md) 和 [CLI 参考](references/cli.md)。原始输入、讨论、决定及开发验证资料保存在本地 `.dev_docs/`，不随公开仓库发布。

工具校验自身操作并恢复背景，不能证明模型理解正确或强制约束其他工具。对研究偏移的长期改善仍需实际使用观察。
