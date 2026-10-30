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


# ---------------------------------------------------------------- push only verified configurations


def update_args(tmp_path, remotes, base, *extra, apparatuses=("np02", "np04")):
    return [str(tmp_path / "area"), "-a", ",".join(apparatuses), "--base_url", str(remotes["base"]),
            *op_args(remotes, *apparatuses), "-b", base, "-r", "rel", *extra]


def test_push_only_pushes_successful_generation(tmp_path, remotes):
    assert run(cpm_update.main, update_args(tmp_path, remotes, "v1")).exit_code == 0
    assert remote_branches(remotes["ops"]["np02"]) == {"main"}
    assert run(cpm_update.main, update_args(tmp_path, remotes, "v1", "--push-only")).exit_code == 0
    assert remote_branches(remotes["ops"]["np02"]) == {"main", "rel/gen_a", "rel/shared"}
    assert remote_branches(remotes["ops"]["np04"]) == {"main", "rel/gen_b", "rel/shared"}


def test_push_only_refuses_failed_generation(tmp_path, remotes):
    ## np04/gen_b fails, np02 succeeds: nothing at all is pushed
    assert run(cpm_update.main, update_args(tmp_path, remotes, "broken")).exit_code == 1
    result = run(cpm_update.main, update_args(tmp_path, remotes, "broken", "--push-only"))
    assert result.exit_code == 1
    assert remote_branches(remotes["ops"]["np02"]) == {"main"}
    assert remote_branches(remotes["ops"]["np04"]) == {"main"}


def test_push_only_refuses_failed_regeneration(tmp_path, remotes):
    ## a successful generation followed by a failed one of the same branch
    assert run(cpm_update.main, update_args(tmp_path, remotes, "v1", apparatuses=("np04",))).exit_code == 0
    assert run(cpm_update.main, update_args(tmp_path, remotes, "broken", apparatuses=("np04",))).exit_code == 1
    result = run(cpm_update.main, update_args(tmp_path, remotes, "v1", "--push-only", apparatuses=("np04",)))
    assert result.exit_code == 1
    assert remote_branches(remotes["ops"]["np04"]) == {"main"}


def test_push_only_refuses_modified_branch(tmp_path, remotes):
    assert run(cpm_update.main, update_args(tmp_path, remotes, "v1", apparatuses=("np02",))).exit_code == 0
    area = tmp_path / "area" / "np02"
    git("checkout", "-q", "rel/gen_a", cwd=area)
    (area / "README.md").write_text("manual change")
    git("commit", "-qam", "manual", cwd=area)
    result = run(cpm_update.main, update_args(tmp_path, remotes, "v1", "--push-only", apparatuses=("np02",)))
    assert result.exit_code == 1
    assert remote_branches(remotes["ops"]["np02"]) == {"main"}


def test_push_configurations_refuses_unverified(tmp_path, remotes):
    pool = ConfPool(pool_dir(tmp_path), apparatus="np04", operation_url=str(remotes["ops"]["np04"]),
                    base_url=str(remotes["base"]))
    assert not pool.propagate_base("broken", release_tag="rel", no_push=True)
    assert pool.is_verified("rel/gen_b") is False
    assert pool.get_unverified_configurations("broken", release_tag="rel") == ["rel/gen_b"]
    assert pool.push_configurations("broken", release_tag="rel") is False
    assert remote_branches(remotes["ops"]["np04"]) == {"main"}

    assert pool.propagate_base("v1", release_tag="rel", no_push=True)
    assert pool.is_verified("rel/gen_b") and pool.is_verified("rel/shared")
    assert pool.push_configurations("v1", release_tag="rel") is True
    assert remote_branches(remotes["ops"]["np04"]) == {"main", "rel/gen_b", "rel/shared"}


# ---------------------------------------------------------------- safety checks


CRASHING_GENERATOR = """
from pathlib import Path

def generate(path: str) -> bool:
    Path(path, "leftover.txt").write_text("partial")
    raise RuntimeError("boom")
"""


def test_repository_key():
    from runconftools.ConfPool import repository_key
    ssh = repository_key("ssh://git@gitlab.cern.ch:7999/dune-daq/online/np02-configs-operation.git")
    assert ssh == repository_key("https://gitlab.cern.ch/dune-daq/online/np02-configs-operation.git")
    assert ssh == repository_key("git@gitlab.cern.ch:dune-daq/online/np02-configs-operation")
    assert ssh != repository_key("https://gitlab.cern.ch/dune-daq/online/np04-configs-operation.git")
    assert repository_key("/a/b.git") == repository_key("file:///a/b") == "/a/b"


def test_set_apparatuses_rejects_shared_repository():
    with pytest.raises(ValueError, match="same operation repository"):
        ConfPool.set_apparatuses(["np02", "np04"], {"np04": Apparatus.NP02.https_url()})


def test_operation_repo_cannot_be_the_base(tmp_path, remotes):
    args = [str(tmp_path / "area"), "-a", "np02", "--base_url", str(remotes["base"]),
            "--operation_url", f"np02={remotes['base']}", "-b", "v1", "-r", "rel"]
    result = CliRunner().invoke(cpm_update.main, args)
    assert result.exit_code == 2
    assert "cannot be the operation repository of np02" in result.output


def test_unreachable_repositories_fail_before_cloning(tmp_path, remotes):
    empty = tmp_path / "remotes" / "empty.git"
    git("init", "-q", "--bare", str(empty))
    args = [str(tmp_path / "area"), "-a", "np02,np04", "--base_url", str(remotes["base"]),
            "--operation_url", f"np02={tmp_path / 'missing.git'},np04={empty}", "-b", "v1", "-r", "rel"]
    result = CliRunner().invoke(cpm_update.main, args)
    assert result.exit_code == 1
    assert "np02 operation repository" in result.output and "cannot be reached" in result.output
    assert "np04 operation repository" in result.output and "no default branch" in result.output
    assert not (tmp_path / "area").exists()


def test_pushing_without_spack_release_needs_explicit_base_and_release(tmp_path, remotes, monkeypatch):
    monkeypatch.delenv("SPACK_RELEASE", raising=False)
    args = [str(tmp_path / "area"), "-a", "np02", "--base_url", str(remotes["base"]), *op_args(remotes, "np02"), "-p"]
    result = CliRunner().invoke(cpm_update.main, args)
    assert result.exit_code == 2
    assert "--base and --release must be given explicitly" in result.output
    result = CliRunner().invoke(cpm_update.main, [*args, "-b", "v1"])
    assert result.exit_code == 2
    assert "--release must be given explicitly" in result.output


def test_conf_matching_nothing(tmp_path, remotes):
    result = CliRunner().invoke(cpm_update.main, update_args(tmp_path, remotes, "v1", "--conf", "nothing", "-p"))
    assert result.exit_code == 2
    assert "No generator of the selected apparatuses matches" in result.output


def test_conf_skips_apparatuses_without_matches(tmp_path, remotes):
    ## np04 has no gen_a: it is neither generated, pushed nor cleaned
    assert run(cpm_update.main, update_args(tmp_path, remotes, "v1", "--conf", "gen_a", "-p")).exit_code == 0
    assert remote_branches(remotes["ops"]["np02"]) == {"main", "rel/gen_a"}
    assert remote_branches(remotes["ops"]["np04"]) == {"main"}
    assert not (tmp_path / "area" / "np04").exists() or "rel/gen_b" not in git("branch", cwd=tmp_path / "area" / "np04")


def test_clean_removes_configurations_without_generator(tmp_path, remotes):
    assert run(cpm_update.main, update_args(tmp_path, remotes, "v1", "-p", apparatuses=("np02",))).exit_code == 0
    ## the base "old" has no np02/shared
    assert run(cpm_update.main, update_args(tmp_path, remotes, "old", "-p", apparatuses=("np02",))).exit_code == 0
    assert remote_branches(remotes["ops"]["np02"]) == {"main", "rel/gen_a"}


def test_clean_refuses_base_without_generators(tmp_path, remotes):
    push_base_branch(remotes["base"], tmp_path / "remotes" / "base_empty", "empty", {"np02": {}})
    assert run(cpm_update.main, update_args(tmp_path, remotes, "v1", "-p", apparatuses=("np02",))).exit_code == 0
    pool = ConfPool(str(tmp_path / "area" / "np02"), apparatus="np02")
    assert pool.clean("empty", release_tag="rel") == []
    assert remote_branches(remotes["ops"]["np02"]) == {"main", "rel/gen_a", "rel/shared"}


def test_push_is_checked_against_the_remote_before_pushing(tmp_path, remotes):
    assert run(cpm_update.main, update_args(tmp_path, remotes, "v1")).exit_code == 0

    ## someone else pushes rel/gen_a to np02 in the meantime
    other = tmp_path / "other"
    git("clone", "-q", str(remotes["ops"]["np02"]), str(other))
    git("checkout", "-q", "-b", "rel/gen_a", cwd=other)
    (other / "README.md").write_text("someone else")
    git("commit", "-qam", "other", cwd=other)
    git("push", "-q", "origin", "rel/gen_a", cwd=other)

    result = run(cpm_update.main, update_args(tmp_path, remotes, "v1", "--push-only"))
    assert result.exit_code == 1
    assert remote_branches(remotes["ops"]["np02"]) == {"main", "rel/gen_a"}
    assert git("show", "rel/gen_a:README.md", cwd=remotes["ops"]["np02"]) == "someone else"
    assert remote_branches(remotes["ops"]["np04"]) == {"main"}


def test_uncommitted_changes_are_refused(tmp_path, remotes):
    assert run(cpm_update.main, update_args(tmp_path, remotes, "v1", apparatuses=("np02",))).exit_code == 0
    (tmp_path / "area" / "np02" / "stray.txt").write_text("x")
    result = CliRunner().invoke(cpm_update.main, update_args(tmp_path, remotes, "v1", apparatuses=("np02",)))
    assert result.exit_code == 1
    assert "uncommitted changes" in result.output


def test_crashing_generator_does_not_leak_into_other_configurations(tmp_path, remotes):
    push_base_branch(remotes["base"], tmp_path / "remotes" / "base_crash", "crash",
                     {"np02": {"boom": CRASHING_GENERATOR, "gen_a": True, "gen_c": True}})
    result = run(cpm_update.main, update_args(tmp_path, remotes, "crash", apparatuses=("np02",)))
    assert result.exit_code == 1

    area = tmp_path / "area" / "np02"
    pool = ConfPool(str(area), apparatus="np02")
    assert not pool.repo.is_dirty(untracked_files=True)
    assert "[failed with an exception]" in git("log", "-1", "--format=%s", "rel/boom", cwd=area)
    assert not pool.is_verified("rel/boom")
    for branch in ("rel/gen_a", "rel/gen_c"):
        assert pool.is_verified(branch)
        assert "leftover.txt" not in git("ls-tree", "--name-only", branch, cwd=area)


# ---------------------------------------------------------------- consistency checks


def test_setup_rejects_missing_base_and_apparatus(tmp_path, remotes):
    common = [str(tmp_path / "area"), "--base_url", str(remotes["base"]), *op_args(remotes, "np02", "np04")]
    result = CliRunner().invoke(cpm_setup.main, [*common, "-a", "np02,np04", "-r", "nope"])
    assert result.exit_code == 2
    assert "nope is not among the available base branches" in result.output
    result = CliRunner().invoke(cpm_setup.main, [*common, "-a", "np02,np04", "-r", "old"])
    assert result.exit_code == 2
    assert "np04 is not in base old" in result.output


def test_setup_missing_configuration_fails(tmp_path, remotes):
    common = [str(tmp_path / "area"), "-a", "np02", "--base_url", str(remotes["base"]), *op_args(remotes, "np02")]
    assert run(cpm_update.main, [*common, "-b", "v1", "-r", "rel", "-p"]).exit_code == 0
    assert run(cpm_setup.main, [*common, "-b", "v1", "-r", "rel", "-c", "missing"]).exit_code == 1
    assert run(cpm_setup.main, [*common, "-b", "v1", "-r", "rel", "-c", "gen_a"]).exit_code == 0


def test_purge_requires_release_and_fails_when_nothing_matches(tmp_path, remotes):
    common = [str(tmp_path / "area"), "-a", "np02", "--base_url", str(remotes["base"]), *op_args(remotes, "np02")]
    assert CliRunner().invoke(cpm_purge.main, common).exit_code == 2
    assert run(cpm_update.main, [*common, "-b", "v1", "-r", "tmp", "-p"]).exit_code == 0
    assert run(cpm_purge.main, [*common, "-r", "unknown"]).exit_code == 1
    assert run(cpm_purge.main, [*common, "-r", "tmp", "--conf", "nothing"]).exit_code == 1
    assert remote_branches(remotes["ops"]["np02"]) == {"main", "tmp/gen_a", "tmp/shared"}


def test_missing_verifiers_fail_the_generation(tmp_path, remotes):
    push_base_branch(remotes["base"], tmp_path / "remotes" / "base_nover", "nover", {"np02": {"gen_a": True}},
                     verifiers=False)
    result = run(cpm_update.main, update_args(tmp_path, remotes, "nover", "-p", apparatuses=("np02",)))
    assert result.exit_code == 1
    assert remote_branches(remotes["ops"]["np02"]) == {"main"}


def test_is_stable_release():
    assert ConfPool.is_stable_release("fddaq-v5.7.2")
    assert ConfPool.is_stable_release("fddaq-v5.7.2rc1")
    assert not ConfPool.is_stable_release("develop")
    assert not ConfPool.is_stable_release("mroda-test")


def test_release_mismatch_warns(tmp_path, remotes, monkeypatch):
    monkeypatch.setenv("SPACK_RELEASE", "fddaq-v5.6.0-a9-1")
    push_base_branch(remotes["base"], tmp_path / "remotes" / "base_stable", "fddaq-v5.7.2", {"np02": {"gen_a": True}})
    args = [str(tmp_path / "area"), "-a", "np02", "--base_url", str(remotes["base"]), *op_args(remotes, "np02"),
            "-b", "fddaq-v5.7.2", "-r", "fddaq-v5.7.2"]
    result = run(cpm_update.main, args)
    assert result.exit_code == 0
    assert "might not be compatible" in result.output


@pytest.mark.parametrize("release", ["a/b", "-x", "bad name", "a..b", "x.lock"])
def test_invalid_release_names(tmp_path, remotes, release):
    args = [str(tmp_path / "area"), "-a", "np02", "--base_url", str(remotes["base"]), *op_args(remotes, "np02"),
            "-b", "v1", "-r", release]
    for main in (cpm_update.main, cpm_purge.main, cpm_setup.main):
        result = CliRunner().invoke(main, args if main is not cpm_purge.main else [a for a in args if a not in ("-b", "v1")])
        assert result.exit_code == 2, (main, release)
        assert "Invalid value for '-r'" in result.output


# ---------------------------------------------------------------- reporting


def test_report_on_failure(tmp_path, remotes):
    result = run(cpm_update.main, update_args(tmp_path, remotes, "broken", "-p"))
    assert result.exit_code == 1
    out = result.output
    assert "Step 1/6 · Checking options and repositories" in out
    assert "Step 3/6 · Generating configurations" in out
    assert "Step 4/6" not in out
    assert "100%] np04 · gen_b — generate() returned False" in out
    assert "Failed configurations" in out and "np04/gen_b — generate() returned False" in out
    assert "✘ FAILED" in out and "Stopped during step 3/6 Generating configurations" in out
    assert "Nothing was pushed to any operation repository." in out
    assert "Generators without validation (" in out


def test_report_on_success(tmp_path, remotes):
    result = run(cpm_update.main, update_args(tmp_path, remotes, "v1"))
    assert result.exit_code == 0
    out = result.output
    assert "Step 3/3 · Generating configurations" in out
    assert "[4/4 100%]" in out
    assert "✔ SUCCESS" in out and "4 configurations generated for np02, np04" in out
    assert "Nothing was pushed: run again with --push-only to push them." in out


def test_report_on_unexpected_exception(tmp_path, remotes, monkeypatch):
    def broken_clean(self, base, release_tag=None):
        raise OSError("disk full")

    monkeypatch.setattr(ConfPool, "clean", broken_clean)
    result = CliRunner().invoke(cpm_update.main, update_args(tmp_path, remotes, "v1", "-p"))
    assert result.exit_code == 1
    assert "Unexpected OSError: disk full" in result.output
    assert "Stopped during step 6/6 Removing obsolete configurations" in result.output


def test_report_hint_on_unreachable_repository(tmp_path, remotes):
    args = [str(tmp_path / "area"), "-a", "np02", "--base_url", str(remotes["base"]),
            "--operation_url", f"np02={tmp_path / 'missing.git'}", "-b", "v1", "-r", "rel"]
    result = CliRunner().invoke(cpm_update.main, args)
    assert result.exit_code == 1
    assert "fatal:" in result.output
    assert "→ Check the URLs and your access" in result.output


NOISY_GENERATOR = """
import ctypes

def generate(path: str) -> bool:
    for i in range(2000):
        print(f"python output {{NAME}} {i}")
    libc = ctypes.CDLL(None)
    for i in range(500):
        libc.printf(b"c output {{NAME}} %d\\n", i)
    return True
"""


def test_report_keeps_output_order_in_log_files(tmp_path, remotes):
    ## as in a log file: stdout is buffered, stdout and stderr go to the same file
    import subprocess
    import sys

    gens = {name: NOISY_GENERATOR.replace("{{NAME}}", name) for name in ("noisy_a", "noisy_b")}
    push_base_branch(remotes["base"], tmp_path / "remotes" / "base_noisy", "noisy", {"np02": gens})
    log = tmp_path / "run.log"
    with log.open("w") as f:
        result = subprocess.run(
            [sys.executable, "-c", "from runconftools.apps.__cpm_update__ import main; main()",
             *update_args(tmp_path, remotes, "noisy", apparatuses=("np02",))],
            stdout=f, stderr=subprocess.STDOUT, check=False,
        )
    lines = log.read_text().splitlines()
    assert result.returncode == 0, "\n".join(lines[-40:])

    summary = next(i for i, line in enumerate(lines) if "Summary" in line)
    for name in ("noisy_a", "noisy_b"):
        result_line = next(i for i, line in enumerate(lines) if "✔" in line and f"np02 · {name}" in line)
        last_output = max(i for i, line in enumerate(lines) if line.endswith(f"output {name} 1999")
                          or line.endswith(f"output {name} 499"))
        assert last_output < result_line < summary
    assert all("output noisy" not in line for line in lines[summary:])


def test_quiet_saves_generator_output_in_logs(tmp_path, remotes):
    import sys

    failing = NOISY_GENERATOR.replace("{{NAME}}", "noisy_bad").replace("return True", "return False")
    gens = {"noisy_a": NOISY_GENERATOR.replace("{{NAME}}", "noisy_a"), "noisy_bad": failing}
    push_base_branch(remotes["base"], tmp_path / "remotes" / "base_quiet", "quiet", {"np02": gens})
    stdout = sys.stdout
    result = run(cpm_update.main, update_args(tmp_path, remotes, "quiet", "-q", apparatuses=("np02",)))
    assert sys.stdout is stdout
    assert result.exit_code == 1
    out = result.output
    running = out.split("Summary")[0]
    assert "output noisy" not in running
    assert "noisy_a has no validation" not in running
    ## the generators run in directory order
    lines = out.splitlines()
    assert any(line.lstrip().startswith("✔ [") and line.endswith("np02 · noisy_a") for line in lines)
    assert any(line.lstrip().startswith("✘ [") and line.endswith("np02 · noisy_bad — generate() returned False")
               for line in lines)

    logs = tmp_path / "area" / "_logs" / "np02"
    good = (logs / "noisy_a.log").read_text().splitlines()
    assert sum(line.startswith("python output noisy_a") for line in good) == 2000
    assert sum(line.startswith("c output noisy_a") for line in good) == 500
    assert f"output: {logs / 'noisy_bad.log'}" in out
    assert "│ c output noisy_bad 499" in out
    assert "The output of the generators is in" in out


def test_quiet_log_file_has_no_generator_output(tmp_path, remotes):
    import subprocess
    import sys

    gens = {name: NOISY_GENERATOR.replace("{{NAME}}", name) for name in ("noisy_a", "noisy_b")}
    push_base_branch(remotes["base"], tmp_path / "remotes" / "base_noisy", "noisy", {"np02": gens})
    log = tmp_path / "run.log"
    with log.open("w") as f:
        result = subprocess.run(
            [sys.executable, "-c", "from runconftools.apps.__cpm_update__ import main; main()",
             *update_args(tmp_path, remotes, "noisy", "--quiet", apparatuses=("np02",))],
            stdout=f, stderr=subprocess.STDOUT, check=False,
        )
    text = log.read_text()
    assert result.returncode == 0, text[-3000:]
    assert "output noisy" not in text
    for name in ("noisy_a", "noisy_b"):
        assert any(line.lstrip().startswith("✔ [") and line.endswith(f"np02 · {name}") for line in text.splitlines())
    assert "✔ SUCCESS" in text
    assert len((tmp_path / "area" / "_logs" / "np02" / "noisy_b.log").read_text().splitlines()) == 2500
