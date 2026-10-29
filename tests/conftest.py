import subprocess
import sys
from pathlib import Path

import pytest

GENERATOR = '''
from pathlib import Path

def generate(path: str) -> bool:
    ## modify a tracked file, as real generators do
    Path(path, "README.md").write_text("{apparatus}")
    return {result}
'''


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def remote_branches(url: Path) -> set[str]:
    out = git("ls-remote", "--heads", str(url))
    return {line.split("refs/heads/")[1] for line in out.splitlines()}


def push_base_branch(base: Path, work: Path, branch: str, generators: dict[str, dict[str, bool | str]],
                     verifiers: bool = True) -> None:
    """
    Push ``branch`` to ``base``, built in the new repo ``work``.

    ``generators[apparatus][name]`` is either the result of the default generator or the generator source.
    If ``verifiers`` is True, the base has a verifier that always succeeds.
    """
    git("init", "-q", "-b", branch, str(work))
    (work / "README.md").write_text(branch)
    ## as in the real base, so that importing the generators leaves the working tree clean
    (work / ".gitignore").write_text("__pycache__/\n*.py[cod]\n")
    if verifiers:
        (work / "functions" / "verifiers").mkdir(parents=True)
        (work / "functions" / "verifiers" / "__init__.py").write_text("")
        (work / "functions" / "verifiers" / "always_ok.py").write_text("def verify(path: str) -> bool:\n    return True\n")
    for apparatus, gens in generators.items():
        d = work / "functions" / "generators" / apparatus
        d.mkdir(parents=True)
        (d / "__init__.py").write_text("")
        for name, result in gens.items():
            source = result if isinstance(result, str) else GENERATOR.format(apparatus=apparatus, result=result)
            (d / f"{name}.py").write_text(source)
    git("add", "-A", cwd=work)
    git("commit", "-qm", f"base {branch}", cwd=work)
    git("push", "-q", str(base), branch, cwd=work)


@pytest.fixture(autouse=True)
def git_identity(monkeypatch):
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "test")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "test@example.com")


@pytest.fixture(autouse=True)
def isolate_imports():
    """Every pool appends to sys.path and the generators are cached in sys.modules, undo both."""
    path = list(sys.path)
    yield
    sys.path[:] = path
    for name in list(sys.modules):
        if name.split(".")[0] in ("generators", "verifiers", "common"):
            del sys.modules[name]


@pytest.fixture
def remotes(tmp_path):
    """
    Bare base and operation repos.

    Base branches:
     - ``v1``: np02 (gen_a, shared) and np04 (gen_b, shared)
     - ``old``: np02 only
     - ``broken``: like v1, but np04/gen_b fails
    """
    base = tmp_path / "remotes" / "base.git"
    git("init", "-q", "--bare", str(base))
    branches = {
        "v1": {"np02": {"gen_a": True, "shared": True}, "np04": {"gen_b": True, "shared": True}},
        "old": {"np02": {"gen_a": True}},
        "broken": {"np02": {"gen_a": True}, "np04": {"gen_b": False}},
    }
    for branch, generators in branches.items():
        push_base_branch(base, tmp_path / "remotes" / f"base_{branch}", branch, generators)

    ops = {}
    for apparatus in ("np02", "np04"):
        op = tmp_path / "remotes" / f"{apparatus}.git"
        git("init", "-q", "--bare", "-b", "main", str(op))
        op_work = tmp_path / "remotes" / f"{apparatus}_work"
        git("init", "-q", "-b", "main", str(op_work))
        (op_work / "README.md").write_text(apparatus)
        git("add", "-A", cwd=op_work)
        git("commit", "-qm", "init", cwd=op_work)
        git("push", "-q", str(op), "main", cwd=op_work)
        ops[apparatus] = op

    return {"base": base, "ops": ops}
