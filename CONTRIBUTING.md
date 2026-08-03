# Contributing

Focused bug reports and small, reviewable pull requests are welcome.

## Bug reports

Include:

- application version;
- Windows version;
- Ollama model;
- steps to reproduce;
- expected result;
- actual result;
- sanitized log excerpt.

Do not include credentials, private media links or a real `Data` folder.

## Pull requests

Before opening a pull request:

```bash
python -m compileall -q .
python -m pytest -q
python tools/check_entrypoint_imports.py
python -c "import content_agent.main"
```

Keep changes narrow and describe how the queue, portable data and platform retry behavior were protected.
