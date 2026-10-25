# jacko-skills

Agent skill 集合，供 Claude Code 及兼容客户端使用。仓库只包含普通文件和真实目录，不使用符号链接或子模块，Windows、macOS 和 Linux 可直接克隆。

## Skills

| Skill | 用途 |
| --- | --- |
| `code-craft` | 让每次改动都让代码库更整洁。 |
| `grasp-the-principal-contradiction` | 在复杂任务中找出主要矛盾，决定先做什么。 |
| `humanizer` | 消除 AI 写作痕迹，保留原意。 |
| `meet-the-learner` | 从学习者的已知出发，选择贴合当前起点的讲解方式。 |
| `workspace-cleaner` | 任务收尾时清理临时文件和产物。 |
| `neverssh` | 通过 NeverSSH MCP 操作远程 SSH 主机。 |

## neverssh 的同步

`neverssh/` 来自 [NeverSSH](https://github.com/Jacko-John/NeverSSH/tree/main/skills/neverssh)，请勿在本仓库编辑；修改应在 NeverSSH 仓库完成。

`.github/workflows/sync-neverssh.yml` 默认每天 03:17 UTC 从 NeverSSH 的 `main` 拉取 `skills/neverssh`，复制到本仓库并在有变化时提交。也可以在 Actions 页面手动触发。workflow 只读取该目录，克隆本仓库不会带入 NeverSSH 的源码。

## 使用

把需要的 skill 目录复制到客户端的 skills 目录，然后重启客户端。

```sh
# macOS / Linux
cp -R neverssh ~/.claude/skills/
```

```powershell
# Windows PowerShell
Copy-Item -Recurse neverssh "$HOME\.claude\skills\"
```
