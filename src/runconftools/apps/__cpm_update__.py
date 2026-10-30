#!/usr/bin/env python3

# @file cpm-update is the executable used to interact with the ConfigPool class and propagate changes from a base branch to the relevant operation branches
import os
import re
from pathlib import Path

import click
from click.core import ParameterSource

from runconftools.apps._common import (
    GenerationReporter,
    apparatus_option,
    check_apparatuses,
    check_repositories,
    open_pools,
    operation_url_option,
    select_apparatuses,
    validate_release,
)
from runconftools.ConfPool import ConfPool
from runconftools.report import OutputCapture, Report, Stop

## directory of PATH where the output of the generators is saved in quiet mode
LOGS_DIR = "_logs"


@click.command(context_settings={'show_default': True})
@click.argument("path", type=click.Path(exists=False, file_okay=False, readable=True, writable=True))
@apparatus_option("all the apparatuses defined in the base")
@click.option(
    "--base_url",
    type=click.STRING,
    default="ssh://git@gitlab.cern.ch:7999/dune-daq/online/ehn1-daqconfigs.git",
    help="URL of the remote base repo"
)
@operation_url_option()
@click.option("-b", "--base", type=click.STRING, default = ConfPool.get_release,
              help="Base branch to be used as a starting point. Defaults to the release from SPACK_RELEASE, or develop if it's not set or not a stable release")
@click.option("-r", "--release", type=click.STRING, default = ConfPool.get_release, callback=validate_release,
              help="Operation branch prefix for the generated branches. Defaults to the release from SPACK_RELEASE, or develop if it's not set or not a stable release")
@click.option("--conf", type=click.STRING, default=".*",
              help="Regex to select a subset of generators, matched from the start of the name (end it with '$' to match the whole name)")
@click.option("--push-only", type=click.BOOL, default=False, is_flag=True,
              help="When set, it skips the generation and only pushes the existing local branches. "
                   "Nothing is pushed unless all of them come from a successful generation")
@click.option("-p", "--push", type=click.BOOL, default=False, is_flag=True,
              help="Pushes the branches, otherwise they are only created locally")

@click.option("-q", "--quiet", type=click.BOOL, default=False, is_flag=True,
              help=f"Do not print the output of the generators and verifiers, save it in PATH/{LOGS_DIR}/<apparatus>/<generator>.log instead. "
                   "Only the steps, the results and the errors are printed, the warnings are in the summary")
@click.option(
    "--debug",
    type=click.BOOL,
    default=False,
    is_flag=True,
    help="Set debug print levels",
)
@click.pass_context
def main(ctx, path, apparatus, base_url, operation_url, base, release, conf, push_only, push, quiet, debug):

    """
    This script takes the base branch and propagates the changes to the operation repos, creating the necessary configurations.
    As a default, the branches are not pushed, use -p  or --push-only to perform the push.
    When several apparatuses are selected, nothing is pushed unless the generation succeeded for all of them.
    """

    pushing = push or push_only
    steps = ["Checking options and repositories", "Preparing local repositories"]
    if not push_only:
        steps.append("Generating configurations")
    if pushing:
        steps += ["Checking the push", "Pushing configurations", "Removing obsolete configurations"]
    mode = "push only" if push_only else ("generate and push" if push else "generate locally, no push")
    context = {
        "Path": path,
        "Apparatuses": "all" if apparatus is None else ", ".join(apparatus),
        "Base": base,
        "Release": release,
        "Generators": conf,
        "Mode": mode,
        "Environment": os.environ.get("SPACK_RELEASE") or "SPACK_RELEASE not set",
    }
    logs = Path(path) / LOGS_DIR
    if quiet:
        context["Output"] = f"quiet, generator output in {logs}"

    with Report("cpm-update", steps, context=context, debug=debug, quiet=quiet) as report:
        report.columns = ["Selected", "Generated", "Pushed", "Removed", "Result"]
        report.step("Checking options and repositories")

        ## outside of a DAQ environment the defaults fall back to develop, which must not be pushed by accident
        if pushing and not os.environ.get("SPACK_RELEASE"):
            implicit = [f"--{p}" for p in ("base", "release") if ctx.get_parameter_source(p) == ParameterSource.DEFAULT]
            if implicit:
                raise click.UsageError(f"SPACK_RELEASE is not set: {' and '.join(implicit)} must be given explicitly when pushing")

        ## the generators use the software of the environment, which should match a stable release
        environment = ConfPool.get_release(default="")
        if not push_only and ConfPool.is_stable_release(release) and release != environment:
            report.warn(f"Generating configurations for {release} with the software of "
                        f"{os.environ.get('SPACK_RELEASE') or 'no DAQ release'}, they might not be compatible")

        conf_regex = re.compile(conf)

        check_repositories(base_url=base_url)
        report.ok(f"Base repository reachable: {base_url}")
        operation_urls = select_apparatuses(path, base_url, base, apparatus, operation_url, ssh=True)
        check_repositories(operation_urls=operation_urls)
        report.table("Operation repositories", ["Apparatus", "Repository"], [[a, u] for a, u in operation_urls.items()])
        report.ok(f"{len(operation_urls)} operation repositories reachable")

        report.step("Preparing local repositories")
        pools = open_pools(path, operation_urls, base_url)
        check_apparatuses(pools, base)

        ## a regex matching nothing is most likely a mistake, and apparatuses it does not concern are left untouched
        selected = {}
        for name, pool in list(pools.items()):
            generators = [g for g in pool.get_generators(base) if conf_regex.match(g)]
            if generators:
                selected[name] = generators
                report.ok(f"{name}: {len(generators)} generators selected, local repo {pool.repo.working_dir}")
                report.set_result(name, "Selected", str(len(generators)))
            else:
                report.warn(f"No {name} generator matches '{conf}', {name} is skipped")
                report.set_result(name, "Selected", "0")
                report.set_result(name, "Result", "⚠ skipped")
                del pools[name]
        if not pools:
            raise click.UsageError(f"No generator of the selected apparatuses matches '{conf}'")

        if not push_only:
            report.step("Generating configurations")
            report.group_warnings(r"(?P<item>\S+) has no validation", "Generators without validation")
            total = sum(len(g) for g in selected.values())
            capture = OutputCapture() if quiet else None
            with report.progress(total) as progress:
                listeners = {}
                try:
                    for name, pool in pools.items():
                        report.current_apparatus = name
                        listeners[name] = GenerationReporter(report, progress, name, capture=capture, logs=logs / name)
                        pool.propagate_base(base=base, release_tag=release, conf_regex=conf_regex, no_push=True,
                                            listener=listeners[name])
                finally:
                    ## never leave stdout redirected, e.g. when interrupted in the middle of a generator
                    if capture:
                        capture.stop()
                report.current_apparatus = None
            if quiet:
                report.notes.append(f"The output of the generators is in {logs}/<apparatus>/<generator>.log.")

            failed = 0
            for name, listener in listeners.items():
                failed += len(listener.failed)
                done = len(listener.succeeded) + len(listener.failed)
                if listener.failed:
                    report.set_result(name, "Generated", f"✘ {len(listener.succeeded)}/{done}")
                    report.set_result(name, "Result", "✘ failed")
                else:
                    report.set_result(name, "Generated", f"✔ {done}")
                    report.set_result(name, "Result", "✔ generated, not pushed" if push else "✔ generated")
            if failed:
                if push:
                    report.notes.append("Nothing was pushed to any operation repository.")
                report.notes.append(f"The failed branches are kept for inspection in {path}/<apparatus>.")
                raise Stop(f"{failed} of {total} configurations failed",
                           hint="Fix the failing generators or the base (see 'Failed configurations'), then run again")

        if not pushing:
            for name in pools:
                report.set_result(name, "Result", "✔ generated")
            report.success_message = f"{total} configurations generated for {', '.join(pools)}"
            report.notes.append("Nothing was pushed: run again with --push-only to push them.")
            return

        report.step("Checking the push")
        ## only branches coming from a successful generation and accepted by the operation repos
        ## can be pushed, and they are checked for all the apparatuses before pushing anything
        branches = {}
        blocked = []
        for name, pool in pools.items():
            report.current_apparatus = name
            branches[name] = pool.get_local_configurations(base=base, release_tag=release, conf_regex=conf_regex) or []
            problems = pool.check_push(base=base, release_tag=release, conf_regex=conf_regex)
            for problem in problems:
                report.error(f"{name}: {problem}")
            if problems:
                blocked.append(name)
                report.set_result(name, "Result", "✘ push refused")
            elif branches[name]:
                report.ok(f"{name}: {len(branches[name])} configurations can be pushed")
            else:
                report.warn(f"{name}: no local configurations to push")
        report.current_apparatus = None
        if blocked:
            report.notes.append("Nothing was pushed to any operation repository.")
            raise Stop(f"The push check failed for {', '.join(blocked)}",
                       hint="Regenerate the configurations (without --push-only), or check the operation repositories")

        report.step("Pushing configurations")
        pushed = []
        for name, pool in pools.items():
            report.current_apparatus = name
            try:
                ok = pool.push_configurations(base=base, release_tag=release, conf_regex=conf_regex)
            except Exception as e:
                ok = False
                report.error(f"{name}: {e}")
            if not ok:
                report.set_result(name, "Result", "✘ push failed")
                report.notes.append(f"Already pushed: {', '.join(pushed)}." if pushed else "Nothing was pushed.")
                raise Stop(f"Pushing to {name} failed, the remaining apparatuses are not pushed",
                           hint="Check the error above, then run again with --push-only")
            pushed.append(name)
            report.ok(f"{name}: {len(branches[name])} configurations pushed")
            report.set_result(name, "Pushed", f"✔ {len(branches[name])}")
        report.current_apparatus = None

        report.step("Removing obsolete configurations")
        removed_total = 0
        for name, pool in pools.items():
            report.current_apparatus = name
            removals = pool.clean(base=base, release_tag=release)
            removed_total += len(removals)
            if removals:
                report.ok(f"{name}: removed {', '.join(removals)}")
            else:
                report.info(f"{name}: nothing to remove")
            report.set_result(name, "Removed", str(len(removals)))
            report.set_result(name, "Result", "✔ done")
        report.current_apparatus = None

        pushed_total = sum(len(b) for b in branches.values())
        report.success_message = f"{pushed_total} configurations pushed to {', '.join(pools)}"
        if removed_total:
            report.notes.append(f"{removed_total} obsolete configurations removed.")
