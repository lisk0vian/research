---
name: tgrep
description: Use tgrep instead of grep/rg for content search. Trigram-indexed, ripgrep-compatible regex search with client/server architecture. Triggers on any need to search file contents, find symbols, TODOs, or list searchable files.
---

# tgrep — fast indexed grep (grep replacement)

`tgrep` is ripgrep with a pre-built trigram index. Same flags as `rg` for common searches, but milliseconds on large trees once indexed. Installed via Scoop (`tgrep 1.0.8`).

Rule: **prefer `tgrep` over `grep`/`rg` via Bash for every content search.** Keep using the dedicated `Grep` tool only when the task explicitly calls for it.

## Mental model

```
tgrep index .        # once per repo: build index into ./.tgrep
tgrep serve .        # once per session: keep index warm, watch for changes
tgrep -- "pattern" . # every search: auto-uses server > disk index > full scan
```

Resolution order: running server (fastest) → on-disk `.tgrep/` index (fast, snapshot) → full scan (slow, warns on stderr). The command is identical in all three cases.

## Setup (once per repo)

```bash
tgrep serve . &
tgrep status .
```

- `serve` builds the index in background if missing and answers queries while building.
- Do not commit `.tgrep/` (add to `.gitignore`).
- If no background process can persist, skip `serve`: run `tgrep index .` and re-run it after any edit a later search must see.
- Non-git directory with `.gitignore`: pass `--no-require-git` to `index`, `serve`, and searches.

## Searching (ripgrep-compatible)

```bash
tgrep -- "fn parse_config" .             # regex, default
tgrep -F -- "Vec<Option<T>>" .           # literal string (preferred for symbols)
tgrep -w -t rust -- handle .             # whole word, Rust files only
tgrep -g "src/**" -C 2 -- "TODO|FIXME" . # glob scope, 2 lines context
tgrep -l -- "impl .* for Server" .       # filenames only (broad queries first)
tgrep -c -- deprecated .                 # count per file
tgrep -i -- error .                      # case-insensitive
tgrep -S -- readme .                     # smart-case
tgrep -v -- pattern .                    # invert match
tgrep -o -- pattern .                    # only matching text
tgrep -m 5 -- pattern .                  # max 5 matches per file
tgrep -A 3 -B 2 -- pattern .             # after/before context
tgrep --vimgrep -- pattern .             # file:line:col:text (jump targets)
tgrep --json -- pattern .                # ripgrep-compatible JSON stream
tgrep --files -t py .                    # list searchable files, no search
tgrep --type-list                        # all file types
tgrep -q -- pattern .                    # yes/no only, read exit code
```

Agent rules of thumb:

- **Always put `--` before the pattern** and pass the root explicitly. A bare `index|serve|search|status|count-files|help` parses as a subcommand, so `tgrep -- serve .` searches for the word "serve". All flags go before `--`.
- **Prefer `-F`** for symbols or user-typed strings (no regex-escaping mistakes).
- **Scope with `-t`/`-g` before `-m`.** Negative-only globs (`--glob '!.git'`) stay indexed; positive glob overrides may force a full scan.
- **Broad query → `-l` first**, then search the specific files. Keeps output small.
- **Context reads → `-C 2`/`-C 3`.**
- **Yes/no → `-q`**, read exit code (0 = match, 1 = no match, 2 = error).

## Freshness (load-bearing)

- **Server running:** results reflect the last processed watcher event. A search right after an edit can run before the index catches up → use `--no-index` when the latest edit must be visible.
- **Disk index only:** results reflect the last `tgrep index`. New files are invisible until re-index.
- **`tgrep index .` does NOT update a running server.** Restart `serve` or wait for its watcher.
- `tgrep status .` shows `Indexing: complete` / hidden-file coverage. It is a readiness signal, not a freshness guarantee.

## Keep index/serve/search flags aligned

These describe the index set — use identical values on `index`, `serve`, and every search or results silently differ:

- `--exclude <DIR>` (`index`/`serve` only, repeatable)
- `--index-path <DIR>`, `--max-filesize <N>` / `--no-max-filesize`, `--no-require-git`, `--no-ignore`

```bash
tgrep index . --exclude vendor --index-path /tmp/idx
tgrep serve . --exclude vendor --index-path /tmp/idx
tgrep -- "pattern" . --index-path /tmp/idx
```

Default skips files > 64 MiB (deliberate divergence from `rg`). A directly named file is still searched.

## Flags that bypass the index (slow on large repos)

`--no-index`, `--no-ignore` + variants, `-u`/`-uu`/`-uuu`, positive `--glob`/`--iglob`, `-a`/`--text`, `--binary`, `-E`/`--encoding`, naming a single file. Use deliberately.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `warning: no index at ... - scanning every file` | No index where the search looked | Same `--index-path` everywhere, or run `tgrep index .` / `serve` |
| `Server unreachable, falling back to local index` | Server died / stale `serve.json` | Restart `tgrep serve .` |
| New file not found, no server | Disk index predates the file | Re-run `tgrep index .` |
| New file not found, server running | Build in progress / event queued | Wait, or `--no-index` for that search |
| Slow despite server | Flag bypasses index (see above) | Drop the flag or scope with `-t`/`-g` |

## Reference

- Full CLI flags: `tgrep --help` (mirrors `rg`); subcommands `index`, `serve`, `status`, `count-files`.
- Upstream docs: `https://github.com/microsoft/tgrep` (`README.md` = flags, `AGENTS.md` = agent guide).
