import re

import click
import pytest
from click.testing import CliRunner
from conftest import git, push_base_branch, remote_branches

from runconftools.Apparatus import Apparatus
from runconftools.apps import __cpm_purge__ as cpm_purge
from runconftools.apps import __cpm_setup__ as cpm_setup
from runconftools.apps import __cpm_update__ as cpm_update
from runconftools.apps._common import parse_operation_urls, split_values
from runconftools.ConfPool import ConfPool


def op_args(remotes, *apparatuses):
    return ["--operation_url", ",".join(f"{a}={remotes['ops'][a]}" for a in apparatuses)]


# ---------------------------------------------------------------- ConfPool


def pool_dir(tmp_path):
    path = tmp_path / "pool"
    path.mkdir(exist_ok=True)
    return str(path)


def test_get_apparatuses_from_base(tmp_path, remotes):
    pool = ConfPool(pool_dir(tmp_path), apparatus=None, base_url=str(remotes["base"]))
    assert pool.operation is None
    assert pool.get_apparatuses("v1") == ["np02", "np04"]
    assert pool.get_apparatuses("old") == ["np02"]


def test_get_apparatuses_skips_non_apparatus_entries(tmp_path, remotes):
    pool = ConfPool(pool_dir(tmp_path), apparatus=None, base_url=str(remotes["base"]))
    pool.get_apparatuses("v1")
    generators = tmp_path / "pool" / "functions" / "generators"
    (generators / "__pycache__").mkdir()
    (generators / "not-a-module").mkdir()
    (generators / "file.py").write_text("")
    assert pool.get_apparatuses("v1") == ["np02", "np04"]


def test_get_apparatuses_defaults_without_base(tmp_path, remotes):
    pool = ConfPool(pool_dir(tmp_path), apparatus=None, base_url=str(remotes["base"]))
    assert pool.get_apparatuses() == sorted(Apparatus.values())
    assert ConfPool.default_apparatuses() == sorted(Apparatus.values())


def test_get_apparatuses_unknown_base(tmp_path, remotes):
    pool = ConfPool(pool_dir(tmp_path), apparatus=None, base_url=str(remotes["base"]))
    with pytest.raises(ValueError, match="not among the available base branches"):
        pool.get_apparatuses("nope")


def test_base_only_pool_rejects_operation_methods(tmp_path, remotes):
    pool = ConfPool(pool_dir(tmp_path), apparatus="np02", base_url=str(remotes["base"]))
    assert sorted(pool.get_generators("v1")) == ["gen_a", "shared"]
    assert not pool.is_default_branch("operation/main")
    with pytest.raises(RuntimeError, match="No operation repository"):
        pool.get_confs()
    with pytest.raises(RuntimeError, match="No operation repository"):
        pool.propagate_base("v1")
    with pytest.raises(RuntimeError, match="No operation repository"):
        pool.remove_configurations(release="v1")


def test_missing_base_url(tmp_path):
    with pytest.raises(ValueError, match="no base URL"):
        ConfPool(pool_dir(tmp_path))


def test_operation_added_and_changed_later(tmp_path, remotes):
    path = pool_dir(tmp_path)
    ConfPool(path, apparatus="np02", base_url=str(remotes["base"]))
    pool = ConfPool(path, apparatus="np02", operation_url=str(remotes["ops"]["np02"]))
    assert pool.operation.url == str(remotes["ops"]["np02"])
    assert pool.is_default_branch("operation/main")

    ## an existing remote pointing elsewhere is updated, not silently reused
    pool = ConfPool(path, apparatus="np04", operation_url=str(remotes["ops"]["np04"]))
    assert pool.operation.url == str(remotes["ops"]["np04"])


def test_set_apparatuses_defaults():
    urls = ConfPool.set_apparatuses(["np04", "np02", "np04"])
    assert urls == {"np04": Apparatus.NP04.ssh_url(), "np02": Apparatus.NP02.ssh_url()}
    assert list(urls) == ["np04", "np02"]
    assert ConfPool.set_apparatuses(["np02"], ssh=False) == {"np02": Apparatus.NP02.https_url()}


def test_set_apparatuses_overrides():
    urls = ConfPool.set_apparatuses(["np02", "new_det"], {"new_det": "/x.git"})
    assert urls == {"np02": Apparatus.NP02.ssh_url(), "new_det": "/x.git"}


def test_set_apparatuses_errors():
    with pytest.raises(ValueError, match="no default operation repository"):
        ConfPool.set_apparatuses(["new_det"])
    with pytest.raises(ValueError, match="not selected"):
        ConfPool.set_apparatuses(["np02"], {"np4": "/x.git"})


# ---------------------------------------------------------------- option parsing


def test_split_values():
    assert split_values(("np02, np04", "np02", "", "vd_coldbox,")) == ["np02", "np04", "vd_coldbox"]


def test_parse_operation_urls():
    assert parse_operation_urls(["np02=/a,np04=/b"], ["np02", "np04"]) == {"np02": "/a", "np04": "/b"}
    assert parse_operation_urls(["ssh://h:7999/a.git"], ["np02"]) == {"np02": "ssh://h:7999/a.git"}
    assert parse_operation_urls(["https://h/a?x=y"], ["np02"]) == {"np02": "https://h/a?x=y"}
    assert parse_operation_urls([], ["np02"]) == {}
    for values, apparatuses in ((["/a"], ["np02", "np04"]), (["/a"], None), (["/a", "np04=/b"], ["np02", "np04"]),
                                (["np02=/a", "np02=/b"], ["np02"])):
        with pytest.raises(click.BadParameter):
            parse_operation_urls(values, apparatuses)


# ---------------------------------------------------------------- command line


def run(main, args):
    result = CliRunner().invoke(main, args, catch_exceptions=False)
    print(result.output)
    return result


def test_update_list_pushes_each_apparatus_to_its_repo(tmp_path, remotes):
    args = [str(tmp_path / "area"), "-a", "np02", "-a", "np04", "--base_url", str(remotes["base"]),
            *op_args(remotes, "np02", "np04"), "-b", "v1", "-r", "rel", "-p"]
    assert run(cpm_update.main, args).exit_code == 0

    assert remote_branches(remotes["ops"]["np02"]) == {"main", "rel/gen_a", "rel/shared"}
    assert remote_branches(remotes["ops"]["np04"]) == {"main", "rel/gen_b", "rel/shared"}
    ## the configuration with the same name is generated by the generator of the right apparatus
    for apparatus in ("np02", "np04"):
        content = git("show", "rel/shared:README.md", cwd=remotes["ops"][apparatus])
        assert content == apparatus
    assert not (tmp_path / "area" / "_base").exists()


def test_update_all_uses_the_base(tmp_path, remotes):
    args = [str(tmp_path / "area"), "-a", "all", "--base_url", str(remotes["base"]),
            *op_args(remotes, "np02"), "-b", "old", "-r", "rel", "-p"]
    assert run(cpm_update.main, args).exit_code == 0
    assert remote_branches(remotes["ops"]["np02"]) == {"main", "rel/gen_a"}
    assert remote_branches(remotes["ops"]["np04"]) == {"main"}
    assert sorted(p.name for p in (tmp_path / "area").iterdir()) == ["_base", "np02"]


def test_update_failure_pushes_nothing(tmp_path, remotes):
    args = [str(tmp_path / "area"), "-a", "np02,np04", "--base_url", str(remotes["base"]),
            *op_args(remotes, "np02", "np04"), "-b", "broken", "-r", "rel", "-p"]
    result = run(cpm_update.main, args)
    assert result.exit_code == 1
    assert remote_branches(remotes["ops"]["np02"]) == {"main"}
    assert remote_branches(remotes["ops"]["np04"]) == {"main"}


def test_update_rejects_apparatus_not_in_base(tmp_path, remotes):
    args = [str(tmp_path / "area"), "-a", "np02,np04", "--base_url", str(remotes["base"]),
            *op_args(remotes, "np02", "np04"), "-b", "old", "-r", "rel", "-p"]
    result = CliRunner().invoke(cpm_update.main, args)
    assert result.exit_code == 2
    assert "np04 is not in base old" in result.output
    assert remote_branches(remotes["ops"]["np02"]) == {"main"}


def test_update_rejects_bad_apparatus_options(tmp_path, remotes):
    common = [str(tmp_path / "area"), "--base_url", str(remotes["base"]), "-b", "v1"]
    for extra in (["-a", "all,np02"], ["-a", "np02,np04", "--operation_url", "/x.git"],
                  ["-a", "np02", "--operation_url", "np04=/x.git"], ["-a", "unknown_det"]):
        result = CliRunner().invoke(cpm_update.main, common + extra)
        assert result.exit_code == 2, extra


def test_purge_list(tmp_path, remotes):
    common = [str(tmp_path / "area"), "-a", "np02,np04", "--base_url", str(remotes["base"]),
              *op_args(remotes, "np02", "np04")]
    assert run(cpm_update.main, [*common, "-b", "v1", "-r", "tmp", "-p"]).exit_code == 0
    assert run(cpm_purge.main, [*common, "-r", "tmp", "--conf", re.escape("shared")]).exit_code == 0
    assert remote_branches(remotes["ops"]["np02"]) == {"main", "tmp/gen_a"}
    assert remote_branches(remotes["ops"]["np04"]) == {"main", "tmp/gen_b"}


def test_setup_list_checks_out_each_apparatus(tmp_path, remotes):
    common = [str(tmp_path / "area"), "-a", "np02,np04", "--base_url", str(remotes["base"]),
              *op_args(remotes, "np02", "np04")]
    assert run(cpm_update.main, [*common, "-b", "v1", "-r", "rel", "-p"]).exit_code == 0
    assert run(cpm_setup.main, [*common, "-b", "v1", "-r", "rel", "-c", "shared"]).exit_code == 0
    for apparatus in ("np02", "np04"):
        area = tmp_path / "area" / apparatus
        assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=area).strip() == "rel/shared"
        assert (area / "README.md").read_text() == apparatus


# ---------------------------------------------------------------- commit

NEW_FILE_GENERATOR = """
from pathlib import Path

def generate(path: str) -> bool:
    Path(path, "new_file.txt").write_text("new")
    return True
"""

NOOP_GENERATOR = """
def generate(path: str) -> bool:
    return True
"""


def test_generator_adding_only_new_files_is_committed(tmp_path, remotes):
    push_base_branch(remotes["base"], tmp_path / "remotes" / "base_new", "new", {"np02": {"adder": NEW_FILE_GENERATOR}})
    args = [str(tmp_path / "area"), "-a", "np02", "--base_url", str(remotes["base"]),
            *op_args(remotes, "np02"), "-b", "new", "-r", "rel", "-p"]
    assert run(cpm_update.main, args).exit_code == 0
    assert git("show", "rel/adder:new_file.txt", cwd=remotes["ops"]["np02"]) == "new"


def test_base_changes_reach_existing_noop_configuration(tmp_path, remotes):
    work = tmp_path / "remotes" / "base_noop"
    push_base_branch(remotes["base"], work, "noop", {"np02": {"noop": NOOP_GENERATOR}})
    args = [str(tmp_path / "area"), "-a", "np02", "--base_url", str(remotes["base"]),
            *op_args(remotes, "np02"), "-b", "noop", "-r", "rel", "-p"]
    assert run(cpm_update.main, args).exit_code == 0
    assert git("show", "rel/noop:README.md", cwd=remotes["ops"]["np02"]) == "noop"

    ## change the base: the existing configuration is regenerated and must pick up the change
    (work / "README.md").write_text("updated")
    git("commit", "-qam", "update base", cwd=work)
    git("push", "-q", str(remotes["base"]), "noop", cwd=work)
    assert run(cpm_update.main, args).exit_code == 0
    assert git("show", "rel/noop:README.md", cwd=remotes["ops"]["np02"]) == "updated"


def test_commit_returns_whether_something_was_committed(tmp_path, remotes):
    path = tmp_path / "pool"
    pool = ConfPool(pool_dir(tmp_path), apparatus="np02", base_url=str(remotes["base"]))
    pool.checkout_base("v1")
    head = pool.repo.head.commit
    assert not pool.commit("nothing")
    assert pool.repo.head.commit == head

    (path / "README.md").unlink()
    (path / "added.txt").write_text("x")
    assert pool.commit("delete and add")
    assert not pool.repo.is_dirty(untracked_files=True)
    assert {d.a_path for d in head.diff(pool.repo.head.commit)} == {"README.md", "added.txt"}


def test_get_release(monkeypatch):
    monkeypatch.delenv("SPACK_RELEASE", raising=False)
    assert ConfPool.get_release() == "develop"
    assert ConfPool.get_release(default="x") == "x"
    monkeypatch.setenv("SPACK_RELEASE", "fddaq-v5.7.2-a9-1")
    assert ConfPool.get_release() == "fddaq-v5.7.2"
    monkeypatch.setenv("SPACK_RELEASE", "NFD_DEV_261029_A9")
    assert ConfPool.get_release() == "develop"
