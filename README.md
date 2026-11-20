# no-comments

`no-comments` 是一个 pre-commit hook，在提交时拦截新增的代码注释和 docstring，支持 Python 和 Shell。

Claude Code、Codex 等 agent 写的注释，多是变更叙事、对代码的复述，或者已经过时的说明。后来的 agent 会把这些文字当成可信的规格，进而误读代码，并模仿着写出更多注释。代码做什么交给命名、类型和结构表达，改动历史交给 git，必须遵守的约束写成测试或类型。

## 快速开始

在业务仓库的 `.pre-commit-config.yaml` 里加入：

```yaml
repos:
  - repo: https://github.com/AtticusZeller/no-comments
    rev: v0.2.0
    hooks:
      - id: no-comments
```

之后每次 `git commit` 都会检查暂存区里新增的内容。发现违规时，提交被拦下，每条违规输出一行 `path:line:col: NC001 comment not allowed: <前 60 个字符>`，最后附一段写给 agent 的修改提示。退出码：`0` 通过，`1` 有违规，`2` 参数错误或不在 git 仓库里。

## 规则

只报告这次新增的注释和 docstring，分两条规则：

| 编号 | 拦截对象 | 语言 |
| --- | --- | --- |
| `NC001` | 注释（`# ...`），包括行尾注释 | Python、Shell |
| `NC002` | 单独成句的字符串：模块、类、函数的 docstring，以及用三引号字符串充当注释的写法 | Python |

赋值给变量的字符串、f-string 和作为参数传递的字符串，都不算 `NC002`。

### 什么算新增

一条注释要同时满足两个条件才会被报告：它在这次新增或修改的行上；在这次改动涉及的所有文件里，同样的文本改动后比改动前出现得多。比较时忽略开头的 `#` 和空白。所以下面这些情况都不会被报：

- 给文件改名，包括改名时顺带改了别的内容；
- 只改代码、不改注释，比如把 `x = 1  # note` 改成 `x = 2  # note`；
- 把带注释的代码挪到别处，包括挪进类里、改变缩进，以及拆分或合并文件；
- 取消注释一段被注释掉的代码时，其中原有的注释；
- 合并分支、解决冲突时，对方分支带进来的注释。

一行末尾接连写的几段注释分开判断，比如 `x = f()  # noqa  # 说明`：`# noqa` 放行，`# 说明` 照常检查。分段的位置是前面有两个以上空白的 `#`，或者前后都是空白的 `#`。

### 放行

注释去掉开头的 `#` 和空白后，以下表中的前缀开头时放行。除 `KEEP:` 和 `SPDX-License-Identifier:` 外，前缀之后如果还有前面带空白的 `#`（如 `# noqa #说明`），整段不放行：

| 范围 | 前缀 |
| --- | --- |
| 通用 | `KEEP:` |
| 通用 | `SPDX-License-Identifier:` |
| Python | `noqa` |
| Python | `type:` |
| Python | `pyright:` |
| Python | `mypy:` |
| Python | `pragma:` |
| Python | `fmt:` |
| Python | `isort:` |
| Python | `ruff:` |
| Python | `pylint:` |
| Shell | `shellcheck` |

另有以下几条放行：

- 第 1 行的 shebang（`#!`）。Python 第 1、2 行里含 `coding:` 或 `coding=` 的编码声明。
- docstring 的内容去掉开头空白后以 `KEEP:` 开头，比如 `"""KEEP: <原因>"""`。docstring 不适用表里的其他前缀。
- 用 `--allow REGEX` 追加的规则，按去掉注释符号后的文本做 `re.search`，对注释和 docstring 都生效，可以写多次，比如在 hook 配置里写 `args: [--allow, '^TODO\(']`。

### 什么时候写 `KEEP:`

只有代码、类型、测试都表达不了的外部约束，才用 `KEEP:`，比如硬件固件的 bug、第三方服务的调用限制：`# KEEP: 固件 bug，这里的延时不能去掉`。能用命名、类型或测试表达的内容，都不该写成 `KEEP:`。

### 检查哪些文件

扩展名为 `.py`、`.pyi` 的文件按 Python 检查，`.sh`、`.bash` 按 Shell 检查。其他文件看第一行的 shebang，解释器是 `python*` 时按 Python，是 `sh`、`bash`、`dash`、`ksh`、`ash` 时按 Shell。YAML、TOML、Dockerfile、JS/TS 等文件不检查。有语法错误或者不是 UTF-8 编码的文件，会给出警告并跳过，不影响退出码。

## 更多用法

### 在 CI 里检查一段提交范围

在 CI 里检查一段提交时，给 pre-commit 传 `--from-ref` 和 `--to-ref`：

```sh
pre-commit run no-comments --from-ref origin/main --to-ref HEAD
```

不带 ref 运行 `pre-commit run --all-files` 时，只检查暂存区里新增的行，已经提交的文件都会通过。要全量检查，用 `audit`。

### 列出存量注释

`audit` 列出指定路径下所有违规的注释和 docstring，不区分新旧，退出码始终为 `0`：

```sh
uv tool install git+https://github.com/AtticusZeller/no-comments@v0.2.0
no-comments audit                      # 不给路径时检查 git ls-files 的全部文件
no-comments audit --allow '^TODO\(' .  # 和 check 用同一套放行规则
```

### 排除目录

用 pre-commit 自带的 `exclude` 排除目录，工具本身没有配置文件：

```yaml
      - id: no-comments
        exclude: ^(vendor|migrations)/
```

如果是发布给外部用户的库，公共 API 确实需要文档，同样用 `exclude` 排除对应目录。

### 框架的帮助文本

typer、FastAPI 这类框架会读取 docstring 作为帮助文本。改成显式传入 `help=`、`description=`，不要依赖 docstring。

## 已知局限

- 同一次改动里删掉一条注释、同时在任一改动的文件里新加一条文本相同的注释，会被当成移动，不报告。
- Shell 脚本按 bash 语法解析；shebang 是 `zsh` 的脚本不检查。
- 文件用运行 hook 的 Python 版本解析，用了更新版本语法的文件会被跳过。
