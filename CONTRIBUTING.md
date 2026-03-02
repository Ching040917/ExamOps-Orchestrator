# Contributing

Thanks for your interest in contributing to ExamOps Orchestrator. Please follow these guidelines to make collaboration smooth.

**Primary maintainers / contributors**

- @[lerlerchan](https://github.com/lerlerchan)
- @[CalvinTeo]https://github.com/calvin139
- @[qqrey](https://github.com/qqrey6)
- @[Ching](https://github.com/Ching040917)

Getting started

- Fork the repo and open a branch named using the pattern `feature/<short-desc>` or `fix/<short-desc>`.
- Run linters and tests locally before opening a PR:

```bash
pip install -r requirements.txt
pip install pre-commit black isort flake8 pytest
pre-commit run --all-files
black .
isort .
pytest
```

Code style

- We use `black` for formatting and `isort` for imports. `flake8` is the primary linter.
- Keep functions small and focused. Add tests for new behavior.

Pull requests

- Open PRs against `main` and link to an issue when applicable.
- Ensure CI passes: formatting/lint/tests.
- Keep PR descriptions concise and include motivation and the change summary.

Tests

- Add tests to the `tests/` directory and update `pytest.ini` if necessary.

Security & secrets

- Never commit secrets or credentials. Use environment variables or a secrets manager.

Support

If you need help, open an issue and tag one of the maintainers listed above.
