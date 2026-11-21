---
name: clean-comments
description: 清理存量代码注释和 docstring：逐条核实，然后删除、改写成代码、保留为 KEEP:，或修掉注释所辩护的临时方案。在接入 no-comments 之后清理旧代码，或用户要求清理注释时使用。
---

# clean-comments

no-comments hook 拦住新增的注释，这个 skill 清理已有的注释和 docstring。判断标准以 no-comments README 的「规则」一节为准，和 hook 共用 `KEEP:` 约定。

下文的 `references/`、`scripts/` 都相对本 skill 所在目录。

下文所有 `no-comments` 都是指 `uvx --from git+https://github.com/AtticusZeller/no-comments@v0.5.0 no-comments`，版本号和 no-comments 仓库 `pyproject.toml` 的 `version` 一致，skill 和 CLI 随同一个 tag 发布。版本固定后 uvx 只在第一次运行时安装，之后走缓存。

## 0. 前置检查

- `git status --porcelain` 必须为空。不干净就停下，告诉用户。
- `uv` 和 `git` 都可用。然后运行 `no-comments --help`，确认输出里有 `verify-strip`。失败就停下，告诉用户原因：缺 uv、没有网络，或者 tag 不存在。
- 从当前提交新开一个分支，比如 `git switch -c clean-comments/<范围>`。

## 1. 列清单

运行 `no-comments audit <范围>`。业务仓库 `.pre-commit-config.yaml` 里 no-comments hook 配了 `--allow` 的，带上同一组参数。

用户没有指定范围时，用当前分支相对 main 改动过的文件：`git diff --name-only main...HEAD`。结果为空就问用户要范围；无人值守时停下，在报告里说明。

按目录分批，每批大约 50 条。

## 2. 审查

每一批新开一个只读子 agent，prompt 依次拼接：`references/reviewer.md` 全文、`references/investigate.md` 全文、仓库根目录和本 skill 目录的绝对路径（子 agent 要用其中的 `scripts/evidence.sh`）、这一批的 audit 输出。

- Claude Code 用 Agent 工具，类型 `general-purpose`。Codex 用 `spawn_agent`。
- 没有子 agent 能力的环境（比如没装扩展的 Pi）：自己按这份 prompt 重新审一遍，审查时只读不改。
- 写注释的 agent 倾向于为自己的注释辩护，所以判定必须由一个新的视角做出，不要沿用写代码时的判断。

## 3. 核对审查结果

主 agent 逐条核对：

- KEEP 和 ENCODE 必须附上 `references/investigate.md` 规定的证据。没有证据或证据含糊的，改判为 DELETE。
- WORKAROUND 必须写明 hack 在哪几行、它在掩盖什么症状、推断的根因是什么。缺了这些就驳回。
- 越过范围、或要求改业务逻辑的意见，直接驳回。
- 被驳回的条目带上驳回原因，交给子 agent 重审一次。第二次仍被驳回的，记为「待解决」，不再重跑。

## 4. 第一次提交：只动注释

- 删掉所有 DELETE 项。被注释掉的代码整行删掉；行尾注释只删 `#` 及其后面的部分；删掉的 docstring 如果是函数体里唯一的语句，补上 `...`。
- KEEP 项改写成 `# KEEP: <原因>（<证据链接>）`；docstring 改写成 `"""KEEP: <原因>（<证据链接>）"""`。
- WORKAROUND 和 ENCODE 项的注释这一步先留着，后面的提交会处理。
- 运行 `no-comments verify-strip --base HEAD`，必须以 0 退出。它列出删掉的 docstring 时，逐个确认框架（typer、click、FastAPI 等）没有读取这些 `__doc__`；读取的改成显式传入 `help=`、`description=`，这部分放进第二次提交。
- 跑全部测试，通过后提交，比如 `chore: remove stale comments`。

## 5. 第二次提交：改写成代码

- ENCODE 项按 `references/encodings.md` 处理，选成本最低的写法，然后删掉原注释。
- 用户在场时，先列出每一项的方案，用户批准后再改。无人值守时，只有调用方事先授权了才改；否则只删注释，把约束记为「未落地」。
- 跑全部测试，通过后提交。

## 6. 第三次提交：重新设计

WORKAROUND 项按 `references/redesign.md` 处理：

- 先写一个测试，把现有行为，或者 hack 所防止的那个问题，固定下来。测试名本身要说明它锁住了什么。
- 满足「范围内修复」条件的：修根因，去掉 hack 和它的注释，跑全部测试，通过后提交。
- 不满足的：不改代码，按模板写出草图，交给用户；`gh` 可用并且仓库在 GitHub 上时开 issue。然后删掉注释。
- 用户在场时，范围内修复也要先给方案，批准后再动手。无人值守时只写测试和草图，不改代码。

## 7. 验证

- 全部测试通过。
- `no-comments audit <范围>`（带同一组 `--allow`）的结果只剩 KEEP 项。`KEEP:` 注释会被放行，不出现在输出里，所以输出应为空；再用 `rg -n 'KEEP:' <范围>` 核对剩下的 KEEP 和报告里的清单一致。

## 8. 报告

- 每类判定各有多少条；
- KEEP 清单，附证据；
- 已改写成代码的项；
- 已完成的重新设计；
- 待解决的事项：草图或 issue 链接、未落地的约束、第二次仍被驳回的条目。
