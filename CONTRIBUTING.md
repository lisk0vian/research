# Contributing

Thank you for your interest in contributing to this research repository.
This document explains how to contribute effectively.

## How to Contribute

### Reporting Issues

- Use the GitHub issue tracker to report bugs or suggest improvements.
- Include steps to reproduce, expected behavior, and actual behavior.
- For data or paper content issues, reference the specific paper slug
  (e.g., `c15-2026`, `c20-2026`).

### Submitting Changes

1. **Fork** the repository and create a branch from `main`.
2. **Follow the naming convention**: `feature/description` or `fix/description`.
3. **Write clear commit messages** following
   [Conventional Commits](https://www.conventionalcommits.org/).
4. **Run the validator** before pushing:
   ```bash
   python scripts/paper_validate.py
   ```
5. **Run the test suite**:
   ```bash
   pytest -q
   ```
6. **Open a pull request** against `main`.

### Code Style

- **Python**: Follow PEP 8. Use type hints where practical.
- **YAML**: 2-space indentation, no trailing whitespace.
- **Templates**: Keep templates minimal and well-documented with comments.
- **License headers**: Every new source file must include the SPDX header:
  ```python
  # SPDX-License-Identifier: MIT
  # Copyright (c) 2026 Jerremi Aron Chancan Labajos
  ```

### Adding a New Paper

New papers follow the standardized structure defined in `AGENTS.md`.
Use the creation script:

```bash
python scripts/paper_new.py --slug <slug> --journal <journal> --author id:role:order
```

Do not manually create paper folders.

### Adding a New Journal

```bash
python scripts/paper_journal.py --add-journal <slug> --meta meta.json
```

## Licensing

By contributing to this repository, you agree that your contributions
will be licensed under the same dual-license model:

- **Code** (scripts, tools, tests): [MIT License](./LICENSE)
- **Research content** (manuscripts, figures, results):
  [CC BY 4.0](./LICENSE-CONTENT)

Unless you explicitly state otherwise, any contribution intentionally
submitted for inclusion in this repository shall be licensed as above,
without any additional terms or conditions.

## Questions

If you have questions about contributing, open a discussion in the
GitHub repository or contact the maintainer directly.