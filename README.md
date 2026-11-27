# no-comments

`no-comments` 是一个 pre-commit hook，在提交时拦截新增的代码注释和 docstring，支持 Python、Shell、TypeScript 和 TSX。

Claude Code、Codex 等 agent 写的注释，多是变更叙事、对代码的复述，或者已经过时的说明。后来的 agent 会把这些文字当成可信的规格，进而误读代码，并模仿着写出更多注释。代码做什么交给命名、类型和结构表达，改动历史交给 git，必须遵守的约束写成测试或类型。

## 快速开始

安装 [pre-commit](https://pre-commit.com/#install)，在业务仓库的 `.pre-commit-config.yaml` 里加入：

```yaml
repos:
  - repo: https://github.com/AtticusZeller/no-comments
    rev: v0.8.0
    hooks:
      - id: no-comments
```

运行 `pre-commit install` 后，每次 `git commit` 都会用 `no-comments check` 检查暂存区里新增的内容。发现违规时，提交被拦下，每条违规输出一行 `path:line:col: NC001 comment not allowed: <前 60 个字符>`，最后附一段写给 agent 的修改提示。`check` 的退出码：`0` 通过，`1` 有违规，`2` 无法完成检查（如参数错误、不在 git 仓库或无法解析 TypeScript）。

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

Python 和 Shell 的一行里接连写的几段注释分开判断，比如 `x = f()  # noqa  # 说明`：`# noqa` 放行，`# 说明` 照常检查。分段的位置是前面有两个以上空白的 `#`，或者前后都是空白的 `#`。

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

### 支持范围

`check`、`audit`、`strip` 和 `verify-strip` 支持 Python（`.py`、`.pyi`）、Shell（`.sh`、`.bash`）、TypeScript（`.ts`，含 `.d.ts`）和 TSX（`.tsx`）。其他扩展名或无扩展名的脚本可通过首行 shebang 识别：Python 解释器名是 `python` 或带数字版本后缀，Shell 是 `sh`、`bash`、`dash`、`ksh`、`ash`。经 pre-commit 接入时，传入的文件还受 hook 类型过滤。

独立 JavaScript 和 JSONC（如含注释的 `tsconfig.json`）[不在支持范围内](https://github.com/AtticusZeller/no-comments/issues/36)，CSS、HTML、YAML、TOML 和 Dockerfile 也不支持。不递归解析字符串中的内嵌代码，例如 `bash -c '...'` 参数里的 Shell 注释。`verify-strip` 通过不代表这些文件没有改动。

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
      run: uvx --from git+https://github.com/AtticusZeller/no-comments@v0.8.0 no-comments check -- {staged_files}
```

使用 Husky 时，安装 Husky 并运行 `npx husky init`，然后在 `.husky/pre-commit` 中加入以下命令。生成目录写在 Git 的排除路径规格里；可追加多条 `':(exclude,glob)目录/**'`。没有待检查的文件时不会启动 `uvx`：

```sh
# .husky/pre-commit
git diff --cached --name-only --diff-filter=ACMR -z -- \
  ':(glob)**/*.ts' ':(glob)**/*.tsx' ':(exclude,glob)src/generated/**' | \
  xargs -0 sh -c '
    [ "$#" -gt 0 ] || exit 0
    exec uvx --from git+https://github.com/AtticusZeller/no-comments@v0.8.0 no-comments check -- "$@"
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

可以用固定版本的 `uvx` 临时运行，也可以安装 CLI（后续示例假定已安装）：

```sh
uvx --from git+https://github.com/AtticusZeller/no-comments@v0.8.0 no-comments audit
uv tool install git+https://github.com/AtticusZeller/no-comments@v0.8.0
```

`audit` 列出指定路径下所有违规的注释和 docstring，不区分新旧，跳过符号链接及通过符号链接访问的文件。传入目录时只遍历 Git 跟踪的文件。即使列出违规，正常完成也返回 `0`；遇到错误返回 `2`。

```sh
no-comments audit                      # 不给路径时检查 git ls-files 中支持的文件
no-comments audit --allow '^TODO\(' .  # 和 check 用同一套放行规则
```

### 清理存量注释

用 `clean-comments` skill 逐条核实存量注释和 docstring，再删除、改写成代码、保留为 `KEEP:`，或修掉注释所解释的临时方案。skill 按本文规则判断，沿用同一文件范围；尚未接入 hook 时，会先单独提交 hook 配置。

```sh
npx skills add AtticusZeller/no-comments --skill clean-comments
```

skill 需要本机有 uv，它用 uvx 自动获取和自己同版本的 CLI，不用另外安装。

第一次提交用 `strip` 批量应用审查结果。先保存原始 audit 输出，再从同一目录运行：

```sh
no-comments audit path/to/module.py path/to/script.sh path/to/component.tsx > /tmp/audit.txt
no-comments strip /tmp/review.txt --audit /tmp/audit.txt
```

审查表是 UTF-8 纯文本，每行格式为 `路径:行号:列号 | 判定 | 理由 | 证据 | 建议写法`。位置原样取自 audit；`KEEP` 的建议必须是一段完整的单行注释：Python 和 Shell 用 `# KEEP: ...`，TypeScript 和 TSX 用 `// KEEP: ...` 或 `/* KEEP: ... */`。TypeScript 和 TSX 改写时沿用原注释的形式与位置，保留 JSX 的花括号。其他判定可用 `-` 占位。命令只应用 `DELETE` 和 `KEEP`，保留 `WORKAROUND` 和 `ENCODE`。

删除 JSX 注释时，如果花括号中没有表达式或其他保留的注释，则一并移除花括号，并去掉因此形成的空行。如果删除会合并两个有内容的 JSX 文本子节点、改变语句结构或字面量，命令拒绝改写。生成文件应排除在审查范围外。编译器读取的注释指令不能由 `strip` 删除或改写成 KEEP，应按 WORKAROUND 或 ENCODE 处理。

写入前，命令检查所有条目的位置、类型和前 60 个字符是否与原 audit 一致、路径是否经过符号链接，以及改写是否改变生效的 shebang 或 Python 编码声明。核对失败时退出 `2`，不写入任何文件。写入阶段遇到错误也退出 `2`，但不会撤销此前的写入，会报告已经写入的路径。

`verify-strip` 比较 `--base`（默认 `HEAD`）和工作区。不传文件时，检查 Git diff 列出的受支持文件，不含未跟踪文件。它比较去除普通注释后的代码；对 TypeScript 和 TSX，还会列出发生变化的编译指令。退出码 `0` 表示未检出代码改动，`1` 表示检出代码改动并列出文件，`2` 表示出错。删掉的 docstring 会单独列出，因为 typer、click、FastAPI 这类框架可能读取 `__doc__`。

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
- Shell 文件按 Bash 语法解析，不支持通过 `zsh` shebang 识别脚本。删除 CRLF 行尾的注释可能改变 Bash 收到的参数，而校验未必能发现；由不换行空格分隔的多段注释可能无法只删中段。见 [#30](https://github.com/AtticusZeller/no-comments/issues/30)。
- `check` 和 `audit` 遇到非 UTF-8 文件或 Python 解析失败时警告并跳过；Python 语法受运行工具的 Python 版本限制。`strip` 和 `verify-strip` 遇到非 UTF-8 源码会报错。UTF-8 可以带字节顺序标记（BOM）。
- `check` 和 `audit` 会对无法解析的目标 TypeScript 或 TSX 文件报错。模块属性里的 Unicode 换行、同文本注释的定位和换行后的重导出 `with` 仍有边界问题，见 [#32](https://github.com/AtticusZeller/no-comments/issues/32)。
- TypeScript 和 TSX 的清理仍需跑项目自己的类型检查。`verify-strip` 可能漏报编译指令覆盖范围变化或非法尾逗号，也可能误识别 `@jsxRuntime` 或拒绝合法的自动分号插入写法。见 [#35](https://github.com/AtticusZeller/no-comments/issues/35)。
