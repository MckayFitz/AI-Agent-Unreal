# Testing

## Local

Use a Python environment that matches the repo dependencies, then run:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py"
```

## CI

GitHub Actions runs the Python test suite on pushes and pull requests using the workflow in `.github/workflows/python-tests.yml`.

## Current Scope

The automated checks currently cover the FastAPI backend and analysis logic.

The Unreal plugin still needs editor-side validation in a local Unreal environment.
