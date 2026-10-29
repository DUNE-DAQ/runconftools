"""
Contract with runconf-ui (https://github.com/DUNE-DAQ/runconf-ui), the shifter interface.

runconf-ui uses ConfPool directly, in src/runconf_ui/repo_manager/detail/remote_repo_manager.py
and, on the mroda/repo_manager branch, emulation_repo_manager.py. These tests replay its calls,
with the same positional arguments, so that a change of ConfPool breaking runconf-ui fails here.
"""

import inspect
import re

import pytest
from conftest import git

from runconftools.ConfPool import ConfPool


@pytest.fixture
def repos(tmp_path):
    """Base with two branches, operation repo with a default branch and some configurations."""
    base = tmp_path / "base.git"
    git("init", "-q", "--bare", str(base))
    for branch in ("fddaq-v5.7.2", "develop"):
        w = tmp_path / f"base_{branch}"
        git("init", "-q", "-b", branch, str(w))
        (w / "sessions").mkdir(parents=True)
        (w / "sessions" / "emu-session.data.xml").write_text(f"emulation {branch}")
        git("add", "-A", cwd=w)
        git("commit", "-qm", "base", cwd=w)
        git("push", "-q", str(base), branch, cwd=w)

    ops = tmp_path / "ops.git"
    git("init", "-q", "--bare", "-b", "main", str(ops))
    w = tmp_path / "ops_w"
    git("init", "-q", "-b", "main", str(w))
    (w / "README.md").write_text("ops")
    git("add", "-A", cwd=w)
    git("commit", "-qm", "init", cwd=w)
    git("push", "-q", str(ops), "main", cwd=w)

    def push_conf(branch):
        git("checkout", "-q", "-b", branch, "main", cwd=w)
        (w / "sessions").mkdir(exist_ok=True)
        (w / "sessions" / "np02-session.data.xml").write_text(branch)
        git("add", "-A", cwd=w)
        git("commit", "-qm", branch, cwd=w)
        git("push", "-q", str(ops), branch, cwd=w)

    for branch in ("fddaq-v5.7.2/monitoring", "fddaq-v5.7.2/pds_only", "develop/monitoring"):
        push_conf(branch)
    return {"base": str(base), "ops": str(ops), "push_conf": push_conf}


def test_signatures():
    ## ConfPool(str(conf_directory), apparatus, operation_url, base_url)
    assert list(inspect.signature(ConfPool.__init__).parameters)[1:5] == ["path", "apparatus", "operation_url", "base_url"]
    ## get_confs(re.compile(...)) and checkout_conf(conf, daq_version)
    assert list(inspect.signature(ConfPool.get_confs).parameters)[1] == "release"
    assert list(inspect.signature(ConfPool.checkout_conf).parameters)[1:3] == ["conf", "release"]
    assert list(inspect.signature(ConfPool.checkout_base).parameters)[1] == "base"
    for method in ("get_daq_versions", "get_base_branches", "get_release"):
        assert callable(getattr(ConfPool, method))


def test_remote_repo_manager(tmp_path, repos, monkeypatch):
    monkeypatch.setenv("SPACK_RELEASE", "fddaq-v5.7.2-a9-1")
    conf_dir = tmp_path / "np02-runs"
    conf_dir.mkdir(parents=True, exist_ok=True)
    pool = ConfPool(str(conf_dir), "np02", repos["ops"], repos["base"])

    assert sorted(pool.get_daq_versions()) == ["develop", "fddaq-v5.7.2"]
    assert sorted(pool.get_confs(re.compile("^fddaq-v5.7.2$"))) == ["monitoring", "pds_only"]
    assert pool.get_confs(re.compile("^develop$")) == ["monitoring"]
    assert pool.get_release() == "fddaq-v5.7.2"

    pool.checkout_conf("pds_only", "fddaq-v5.7.2")
    assert next(conf_dir.rglob("np02-session.data.xml")).read_text() == "fddaq-v5.7.2/pds_only"
    pool.checkout_conf("monitoring", "develop")
    assert next(conf_dir.rglob("np02-session.data.xml")).read_text() == "develop/monitoring"

    ## runconf-ui restarted on the same cache, after a new configuration was pushed
    repos["push_conf"]("fddaq-v5.7.2/beam")
    pool = ConfPool(str(conf_dir), "np02", repos["ops"], repos["base"])
    assert sorted(pool.get_confs(re.compile("^fddaq-v5.7.2$"))) == ["beam", "monitoring", "pds_only"]
    pool.checkout_conf("beam", "fddaq-v5.7.2")
    assert next(conf_dir.rglob("np02-session.data.xml")).read_text() == "fddaq-v5.7.2/beam"


def test_default_version_outside_daq_environment(monkeypatch):
    monkeypatch.delenv("SPACK_RELEASE", raising=False)
    assert ConfPool.get_release() == "develop"


@pytest.mark.parametrize("operation", [True, False])
def test_emulation_repo_manager(tmp_path, repos, operation):
    ## it only needs the base, so it can also use a base-only pool
    emu_dir = tmp_path / "np02-emu-runs"
    emu_dir.mkdir(parents=True, exist_ok=True)
    pool = ConfPool(str(emu_dir), "np02", repos["ops"] if operation else None, repos["base"])
    assert sorted(pool.get_base_branches()) == ["develop", "fddaq-v5.7.2"]
    pool.checkout_base("develop")
    assert next(emu_dir.rglob("emu-session.data.xml")).read_text() == "emulation develop"
