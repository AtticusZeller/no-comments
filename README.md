# no-comments

pre-commit hook：拦截新增行上的代码注释（Python、Shell）。只检查本次新增的行；`# KEEP: <原因>` 和工具指令（`noqa`、`type:`、`shellcheck` 等）放行。

## 在业务仓库启用

`.pre-commit-config.yaml`：

```yaml
repos:
  - repo: https://github.com/AtticusZeller/no-comments
    rev: v0.1.0
    hooks:
      - id: no-comments
        exclude: ^(vendor|migrations)/
```

## 在 CI 里检查一段提交范围

```sh
pre-commit run no-comments --from-ref origin/main --to-ref HEAD
```

不带 ref 运行 `pre-commit run --all-files` 时，只检查暂存区里新增的行，已经提交的文件会全部通过。要全量检查，用 `no-comments audit`。

## 列出存量注释

```sh
uv tool install git+https://github.com/AtticusZeller/no-comments@v0.1.0
no-comments audit            # git ls-files 里的全部文件
no-comments audit src tests  # 指定路径
```

## 待定

- docstring 在语法上是字符串，目前不检查；是否纳入检查待定。
- `git mv` 后的文件：`git diff -- FILE` 只看到新路径，整个文件被当作新增，原有注释会被报告。
- 改动一行已有行尾注释的代码时，这一行算新增行，原注释也会被报告。
- `audit` 跳过默认放行的注释（`KEEP:`、工具指令等），但不支持 `--allow`。
