# EditorConfig

## What it is

EditorConfig is a tiny file format, `.editorconfig`, that tells code editors how to write files: which character encoding, line endings, indentation and whether to trim trailing spaces. Most editors read it automatically (some through a plugin), so everyone who opens the project gets the same settings without installing anything project-specific.

## Why this repository uses it

Mixed tabs and spaces, Windows and Unix line endings, and trailing whitespace make diffs noisy and hide real changes in review. In a `Makefile` a wrong indentation character is an actual error, so the file also protects the build.

## Where it appears

| Path | What it does |
| --- | --- |
| `.editorconfig` | 18 lines, applied to the whole repository. |

## How it works underneath

1. The editor looks for `.editorconfig` in the folder of the file you opened, then in parent folders, until one says `root = true`.
2. Section headers like `[*.md]` are glob patterns. Properties apply to files that match. Later sections override earlier ones.
3. The editor applies the properties when you open or save the file. Nothing checks them at build time; the formatter (`ruff format`, `tech/ruff.md`) enforces the Python parts independently.

### Ideas you need first

- **A text editor.** The program you type code in. Different editors have different defaults for tabs, line endings and trailing spaces.
- **A line ending.** The invisible character(s) that end a line: `LF` on macOS and Linux, `CRLF` on older Windows files. Mixed endings make changes look bigger than they are.
- **A glob pattern.** A short way to name many files: `*.md` is "every file ending in .md"; `[*.{yml,json}]` is "every .yml or .json file".

## Walkthrough of this repository's use

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 4
```
`root = true`: stop searching upward. For every file: UTF-8 text; Unix line endings (`lf`); end with exactly one newline; trim spaces at line ends; indent with spaces, four per level (Python's convention).

```ini
[*.{yml,yaml,json,toml,html,css}]
indent_size = 2
```
Data, config and web files use two spaces.

```ini
[Makefile]
indent_style = tab
```
Recipe lines in a Makefile must start with a tab (`tech/make.md`).

```ini
[*.md]
trim_trailing_whitespace = false
```
In Markdown two trailing spaces at the end of a line mean "line break", so trimming would change the meaning.

## Try it yourself

1. Read it:
   ```bash
   cat .editorconfig
   ```
   Expect the sections above.
2. Check for tabs in Python files (there should be none):
   ```bash
   grep -rlP "\t" src --include='*.py' | head
   ```
   (`-P` may be unavailable on macOS `grep`; then use `grep -rl $'\t' src --include='*.py'`.) Expect no output.
3. Check that the Makefile uses tabs where required:
   ```bash
   grep -c $'^\t' Makefile
   ```
   Expect a large number (every recipe line).
4. Check line endings:
   ```bash
   file Makefile pyproject.toml | head
   ```
   Expect no mention of "CRLF".

## Mistakes people make

- Assuming EditorConfig enforces anything. It only instructs editors; CI uses ruff and `make lint`.
- Forgetting the Makefile section and getting "missing separator" errors.
- Trimming trailing spaces in Markdown where they matter.

## Check yourself

1. What does `root = true` do?
   *Stops the search for further `.editorconfig` files in parent folders.*
2. Why does the Makefile section differ?
   *Recipes require tab indentation.*
3. Which tool enforces Python formatting in CI?
   *`ruff format --check`.*
4. What does `insert_final_newline` do?
   *Makes the editor end each file with a newline.*
5. Why is trimming disabled for `*.md`?
   *Two trailing spaces can mean a line break in Markdown.*

## Further reading

- EditorConfig specification and property list: https://editorconfig.org/
