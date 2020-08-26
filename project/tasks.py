"""Development tasks."""

import os
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path

import invoke

PY_SRC_PATHS = [Path("src"), Path("tests"), Path("tasks.py")]
PY_SRC_LIST = [str(p) for p in PY_SRC_PATHS]
PY_SRC = " ".join(PY_SRC_LIST)
MAIN_PYTHON = "3.6"
PYTHON_VERSIONS = ["3.6", "3.7", "3.8", "3.10"]


def get_poetry_venv(python_version):
    """Return the path to a poetry venv."""
    current_venv = os.environ["VIRTUAL_ENV"]
    if current_venv.endswith(f"py{python_version}"):
        return current_venv
    return "-".join(current_venv.split("-")[:-1]) + f"-py{python_version}"


@contextmanager
def setpath(path):
    """Set the PATH environment variable in a with clause."""
    current_path = os.environ["PATH"]
    os.environ["PATH"] = f"{path}:{current_path}"
    yield
    os.environ["PATH"] = current_path


def python(versions):
    """Run a task onto multiple Python versions."""
    if not versions:
        return lambda _: _

    if isinstance(versions, str):
        versions = [versions]

    def decorator(func):
        @wraps(func)
        def wrapped(context, *args, **kwargs):
            for version in versions:
                with setpath(Path(get_poetry_venv(version)) / "bin"):
                    context.python_version = version
                    func(context, *args, **kwargs)
                    del context.python_version

        return wrapped

    return decorator


@invoke.task
def changelog(context):
    """Update the changelog in-place with latest commits."""
    context.run(
        "failprint -t 'Updating changelog' -- python scripts/update_changelog.py "
        "CHANGELOG.md '<!-- insertion marker -->' '^## \\[v?(?P<version>[^\\]]+)'",
        pty=True,
    )


@invoke.task
def check_code_quality(context):
    """Check the code quality."""
    from failprint.cli import run as failprint

    code = failprint(title="Checking code quality", cmd=["flake8", "--config=config/flake8.ini", *PY_SRC_LIST])
    context.run("false" if code != 0 else "true")


@invoke.task
def check_dependencies(context):
    """Check for vulnerabilities in dependencies."""
    context.run(
        "poetry export -f requirements.txt --without-hashes |"
        "failprint --no-pty -t 'Checking dependencies' -- pipx run safety check --stdin --full-report",
        pty=True,
    )


@invoke.task
def check_docs(context):
    """Check if the documentation builds correctly."""
    context.run("failprint -t 'Building documentation' -- mkdocs build -s", pty=True)


@invoke.task
@python(PYTHON_VERSIONS)
def check_types(context):
    """Check that the code is correctly typed."""
    context.run(
        f"failprint -t 'Type-checking ({context.python_version})' -- mypy --config-file config/mypy.ini " + PY_SRC,
        pty=True,
    )


@invoke.task(check_code_quality, check_types, check_docs, check_dependencies)
def check(context):
    """Check it all!"""


@invoke.task
def clean(context):
    """Delete temporary files."""
    context.run("rm -rf .coverage*")
    context.run("rm -rf .mypy_cache")
    context.run("rm -rf .pytest_cache")
    context.run("rm -rf build")
    context.run("rm -rf dist")
    context.run("rm -rf pip-wheel-metadata")
    context.run("rm -rf site")
    context.run("find . -type d -name __pycache__ | xargs rm -rf")
    context.run("find . -name '*.rej' -delete")


@invoke.task
def docs_regen(context):
    """Regenerate some documentation pages."""
    context.run(f"python scripts/regen_docs.py")


@invoke.task(docs_regen)
def docs(context):
    """Build the documentation locally."""
    context.run("mkdocs build")


@invoke.task(docs_regen)
def docs_serve(context, host="127.0.0.1", port=8000):
    """Serve the documentation (localhost:8000)."""
    context.run(f"mkdocs serve -a {host}:{port}")


@invoke.task(docs_regen)
def docs_deploy(context):
    """Deploy the documentation on GitHub pages."""
    context.run("mkdocs gh-deploy")


@invoke.task  # noqa: A001 (we don't mind shadowing the format builtin)
def format(context):
    """Run formatting tools on the code."""
    context.run("failprint -t 'Removing unused imports' -- autoflake -ir --remove-all-unused-imports " + PY_SRC)
    context.run("failprint -t 'Ordering imports' -- isort -y -rc " + PY_SRC)
    context.run("failprint -t 'Formatting code' -- black " + PY_SRC)


@invoke.task
def release(context, version):
    """Release a new Python package."""
    context.run(f"failprint -t 'Bumping version in pyproject.toml' -- poetry version {version}")
    context.run("failprint -t 'Staging files' -- git add pyproject.toml CHANGELOG.md setup.py")
    context.run(f"failprint -t 'Committing changes' -- git commit -m 'chore: Prepare release {version}'")
    context.run(f"failprint -t 'Tagging commit' -- git tag {version}")
    context.run("failprint -t 'Pushing commits' --no-pty -- git push")
    context.run("failprint -t 'Pushing tags' --no-pty -- git push --tags")
    context.run("failprint -t 'Building dist/wheel' -- poetry build")
    context.run("failprint -t 'Publishing version' -- poetry publish")
    context.run("failprint -t 'Deploying docs' -- poetry run mkdocs gh-deploy")


@invoke.task
def setup(context):
    """Setup the development environments (install dependencies)."""
    for python in PYTHON_VERSIONS:
        message = f"Setting up Python {python} environment"
        print(message + "\n" + "-" * len(message))
        context.run(f"poetry env use {python} &>/dev/null")
        opts = "--no-dev --extras tests" if python != MAIN_PYTHON else ""
        context.run(f"poetry install {opts} || true", pty=True)
    context.run("poetry env use system &>/dev/null")


@invoke.task
def combine(context):
    """Combine coverage data from multiple runs."""
    context.run("failprint -t 'Combining coverage data' -- coverage combine --rcfile=config/coverage.ini")


@invoke.task
def coverage(context):
    """Report coverage as text and HTML."""
    context.run("coverage report --rcfile=config/coverage.ini")
    context.run("coverage html --rcfile=config/coverage.ini")


@invoke.task(post=[combine])
@python(PYTHON_VERSIONS)
def test(context, match=""):
    """Run the test suite."""
    context.run(
        f"failprint -t 'Running tests ({context.python_version})' -- "
        "coverage run --rcfile=config/coverage.ini -m "
        f"pytest -c config/pytest.ini -k '{match}'",
        pty=True,
    )