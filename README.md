# no-comments

`no-comments` 是一个 pre-commit hook，在提交时拦截新增的代码注释和 docstring，支持 Python、Shell、TypeScript 和 TSX。

Claude Code、Codex 等 agent 写的注释，多是变更叙事、对代码的复述，或者已经过时的说明。后来的 agent 会把这些文字当成可信的规格，进而误读代码，并模仿着写出更多注释。代码做什么交给命名、类型和结构表达，改动历史交给 git，必须遵守的约束写成测试或类型。

## 快速开始

在业务仓库的 `.pre-commit-config.yaml` 里加入：

```yaml
repos:
  - repo: https://github.com/AtticusZeller/no-comments
    rev: v0.7.0
    hooks:
      - id: no-comments
```

之后每次 `git commit` 都会检查暂存区里新增的内容。发现违规时，提交被拦下，每条违规输出一行 `path:line:col: NC001 comment not allowed: <前 60 个字符>`，最后附一段写给 agent 的修改提示。退出码：`0` 通过，`1` 有违规，`2` 无法完成检查（如参数错误、不在 git 仓库或无法解析 TypeScript）。

## 规则

只报告这次新增的注释和 docstring，分两条规则：

| 编号 | 拦截对象 | 语言 |
| --- | --- | --- |
| `NC001` | 行注释、块注释、JSDoc 和 JSX 注释 | Python、Shell、TypeScript、TSX |
| `NC002` | 单独成句的字符串：模块、类、函数的 docstring，以及用三引号字符串充当注释的写法 | Python |

赋值给变量的字符串、f-string 和作为参数传递的字符串，都不算 `NC002`。

### 什么算新增

一条注释要同时满足两个条件才会被报告：它在这次新增或修改的行上；在这次改动涉及的所有文件里，同样的文本改动后比改动前出现得多。同一文件的 diff 替换块内，先按文本配对保留的注释，再分配新增次数；插入或删除代码行导致注释移位不影响配对。比较时忽略注释标记和首尾空白，TypeScript 块注释还忽略续行缩进和行首的装饰性 `*`。所以下面这些情况都不会被报：

- 给文件改名，包括改名时顺带改了别的内容；
- 只改代码、不改注释，比如把 `x = 1  # note` 改成 `x = 2  # note`；
- 把带注释的代码挪到别处，包括挪进类里、改变缩进，以及拆分或合并文件；
- 取消注释一段被注释掉的代码时，其中原有的注释；
- 合并分支、解决冲突时，对方分支带进来的注释。

一行末尾接连写的几段注释分开判断，比如 `x = f()  # noqa  # 说明`：`# noqa` 放行，`# 说明` 照常检查。分段的位置是前面有两个以上空白的 `#`，或者前后都是空白的 `#`。

### 放行

注释去掉开头的注释标记和空白后，以下表中的前缀开头时放行。在 Python 和 Shell 中，除 `KEEP:` 和 `SPDX-License-Identifier:` 外，前缀之后如果还有前面带空白的 `#`（如 `# noqa #说明`），整段不放行：

| 范围 | 前缀 |
| --- | --- |
| 通用 | `KEEP:` |
| 通用 | `SPDX-License-Identifier:` |
| Python | `noqa` |
| Python | `type:` |
| Python | `pyright:` |
| Python | `ty:` |
| Python | `mypy:` |
| Python | `pragma:` |
| Python | `fmt:` |
| Python | `isort:` |
| Python | `ruff:` |
| Python | `pylint:` |
| Shell | `shellcheck` |
| TypeScript、TSX | `biome-ignore` |
| TypeScript、TSX | `<reference` |

TypeScript 和 TSX 中，`biome-ignore` 须写明一个或多个以空白分隔的 Biome 规则类别（包括 `format`）和冒号后的理由，例如 `// biome-ignore lint/suspicious/noExplicitAny: 外部接口没有类型`。`<reference` 只放行文件开头、代码之前的三斜线指令，例如 `/// <reference types="vite/client" />`。指令后用空白和 `//` 另写的注释，或另起的块注释，照常检查。

另有以下几条放行：

- 第 1 行的 shebang（`#!`）。Python 第 1、2 行里含 `coding:` 或 `coding=` 的编码声明。
- docstring 的内容去掉开头空白后以 `KEEP:` 开头，比如 `"""KEEP: <原因>"""`。docstring 不适用表里的其他前缀。
- 用 `--allow REGEX` 追加的规则，按去掉注释符号后的文本做 `re.search`，对注释和 docstring 都生效，可以写多次，比如在 hook 配置里写 `args: [--allow, '^TODO\(']`。

### 什么时候写 `KEEP:`

只有代码、类型、测试都表达不了的外部约束，才用 `KEEP:`，比如硬件固件的 bug、第三方服务的调用限制：`# KEEP: 固件 bug，这里的延时不能去掉`。TypeScript 用 `// KEEP: ...` 或 `/* KEEP: ... */`。能用命名、类型或测试表达的内容，都不该写成 `KEEP:`。

### 检查哪些文件

扩展名为 `.py`、`.pyi` 的文件按 Python 检查，`.sh`、`.bash` 按 Shell 检查。`.ts`（包括 `.d.ts`）按 TypeScript 检查，`.tsx` 按 TSX 检查。其他文件看第一行的 shebang，解释器是 `python*` 时按 Python，是 `sh`、`bash`、`dash`、`ksh`、`ash` 时按 Shell。独立 JavaScript、HTML、CSS、YAML、TOML 和 Dockerfile 不检查。Python 解析失败或文件不是 UTF-8 编码时，会给出警告并跳过。TypeScript 或 TSX 文件无法解析时，`check` 和 `audit` 报错退出，不会静默跳过。

## 纯前端仓库接入

本机需要安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，并保证 Git hook 的 `PATH` 上有 `uvx`。以下两种配置任选其一，都会把暂存的 TypeScript 和 TSX 文件传给固定版本的 `no-comments check`。检查使用暂存区的文件内容，未暂存的修改不会影响结果。

使用 Lefthook 时，把以下内容加入 `lefthook.yml`，然后运行 `lefthook install`。在 `exclude` 中填写仓库根目录下的生成目录，例如 `src/generated/`：

```yaml
# lefthook.yml
glob_matcher: doublestar
pre-commit:
  jobs:
    - name: no-comments
      glob: "**/*.{ts,tsx}"
      exclude:
        - "src/generated/**"
      run: uvx --from git+https://github.com/AtticusZeller/no-comments@v0.7.0 no-comments check -- {staged_files}
```

使用 Husky 时，安装 Husky 并运行 `npx husky init`，然后在 `.husky/pre-commit` 中加入以下命令。生成目录写在 Git 的排除路径规格里；可追加多条 `':(exclude,glob)目录/**'`。没有待检查的文件时不会启动 `uvx`：

```sh
# .husky/pre-commit
git diff --cached --name-only --diff-filter=ACMR -z -- \
  ':(glob)**/*.ts' ':(glob)**/*.tsx' ':(exclude,glob)src/generated/**' | \
  xargs -0 sh -c '
    [ "$#" -gt 0 ] || exit 0
    exec uvx --from git+https://github.com/AtticusZeller/no-comments@v0.7.0 no-comments check -- "$@"
  ' no-comments
```

## 更多用法

### 在 CI 里检查一段提交范围

在 CI 里检查一段提交时，给 pre-commit 传 `--from-ref` 和 `--to-ref`：

```sh
pre-commit run no-comments --from-ref origin/main --to-ref HEAD
```

不带 ref 运行 `pre-commit run --all-files` 时，只检查暂存区里新增的行，已经提交的文件都会通过。要全量检查，用 `audit`。

### 列出存量注释

`audit` 列出指定路径下所有违规的注释和 docstring，不区分新旧，跳过符号链接及通过符号链接访问的文件。Python 文件的生效编码不是 UTF-8（可带 BOM）时，`audit` 警告并跳过，`strip` 和 `verify-strip` 报错退出：

```sh
uv tool install git+https://github.com/AtticusZeller/no-comments@v0.7.0
no-comments audit                      # 不给路径时检查 git ls-files 的全部文件
no-comments audit --allow '^TODO\(' .  # 和 check 用同一套放行规则
```

### 清理存量注释

`clean-comments`、`strip` 和 `verify-strip` 只支持 Python 和 Shell。hook 只拦新增的注释，已有的 Python 和 Shell 注释及 docstring 交给 `clean-comments` skill 清理：逐条核实，然后删除、改写成代码、保留为 `KEEP:`，或修掉注释所辩护的临时方案。两者的判断标准都是本文的「规则」一节。仓库还没接入 hook 时，skill 会在清理分支的第一个提交里加上。

```sh
npx skills add AtticusZeller/no-comments --skill clean-comments
```

skill 需要本机有 uv，它用 uvx 自动获取和自己同版本的 CLI，不用另外安装。

第一次提交用 `strip` 批量应用审查结果。先保存原始 audit 输出，再从同一目录运行：

```sh
no-comments audit path/to/module.py path/to/script.sh > /tmp/audit.txt
no-comments strip /tmp/review.txt --audit /tmp/audit.txt
```

审查表是 UTF-8 纯文本，每行格式为 `路径:行号:列号 | 判定 | 理由 | 证据 | 建议写法`。位置原样取自 audit；`KEEP` 的建议写法是完整的 `# KEEP: ...`，且只能构成一段注释，例如 `# KEEP: literal # x` 不合法。其他判定可用 `-` 占位。命令只应用 `DELETE` 和 `KEEP`，保留 `WORKAROUND` 和 `ENCODE`。

写入前，命令检查所有条目的位置、类型和前 60 个字符是否与原 audit 一致、路径是否经过符号链接，以及改写是否改变生效的 shebang 或 Python 编码声明。核对失败时退出 `2`，不写入任何文件。写入阶段遇到错误也退出 `2`，但不会撤销此前的写入，会报告已经写入的路径。

用 `verify-strip` 检查工作区是否只改了注释。它比较 `--base`（默认 `HEAD`）和工作区；不给文件时检查两者之间有改动的全部 Python、Shell 文件。退出码 `0` 表示只有注释和 docstring 不同，`1` 表示有代码改动并列出文件，`2` 表示出错。删掉的 docstring 会单独列出，因为 typer、click、FastAPI 这类框架可能读取 `__doc__`。

```sh
no-comments verify-strip --base HEAD
```

### 排除目录和框架帮助文本

工具本身没有配置文件，排除目录用 pre-commit 自带的 `exclude`，比如在 hook 下写 `exclude: ^(vendor|migrations)/`。发布给外部用户的库，如果公共 API 确实需要文档，同样用 `exclude` 排除对应目录。typer、FastAPI 这类框架会读取 docstring 作为帮助文本，改成显式传入 `help=`、`description=`。

### ML 代码里的张量形状

形状注释（如 `# (V, 3, 10)`）同样会被拦下，hook 会额外提示改用 jaxtyping。形状写进类型标注后，`reshape`、`permute` 改了形状，测试就会报错，不会像注释那样悄悄过时。jaxtyping 支持 PyTorch、JAX、NumPy、MLX、TensorFlow，不依赖 JAX；mypy 和 pyright 把 `Float[Tensor, "..."]` 当作普通的 `Tensor`，形状靠运行时检查。

```python
from jaxtyping import Float
from torch import Tensor


def render(verts: Float[Tensor, "V 3 10"]) -> Float[Tensor, "1 H W 3"]: ...
```

JAX 的写法相同，把 `Tensor` 换成 `jax.Array`。运行时检查可以只在测试时开启，需要安装 `jaxtyping` 和 `beartype`，`my_pkg` 换成自己的包名：

```toml
[tool.pytest.ini_options]
addopts = "--jaxtyping-packages=my_pkg,beartype.beartype"
```

函数内部的中间张量有两种写法：在开启了检查的函数里写 `assert isinstance(h, Float[Tensor, "B H W 3"])`，维度名和参数共享；或者用 einops 的 `rearrange(x, "b c h w -> b h w c")`，把形状写在模式串里。具体 API 以 jaxtyping 当前版本的文档为准。

## 已知局限

- 同一次改动里删掉一条注释、同时在任一改动的文件里新加一条文本相同的注释，会被当成移动，不报告。
- Shell 脚本按 bash 语法解析；shebang 是 `zsh` 的脚本不检查。
- 文件用运行 hook 的 Python 版本解析，用了更新版本语法的文件会被跳过。
