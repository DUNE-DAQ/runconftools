#!/usr/bin/env python3

import re

import click

from runconftools.apps._common import (
    apparatus_option,
    check_repositories,
    open_pools,
    operation_url_option,
    select_apparatuses,
    validate_release,
)
from runconftools.report import Report, Stop


@click.command(context_settings={'show_default': True})
@click.argument("path", type=click.Path(exists=False, file_okay=False, writable=True))
@apparatus_option("all the apparatuses with a default operation repo")
@click.option(
    "--base_url",
    type=click.STRING,
    default="ssh://git@gitlab.cern.ch:7999/dune-daq/online/ehn1-daqconfigs.git",
    help="URL of the remote base repo"
)
@operation_url_option()
@click.option("-r", "--release", type=click.STRING, required=True, callback=validate_release,
              help="Operation branch prefix for the branches to be deleted")
@click.option("--conf", type=click.STRING, default=".*",
              help="Regex to select a subset of branches, matched from the start of the configuration name (end it with '$' to match the whole name)")

@click.option(
    "--debug",
    type=click.BOOL,
    default=False,
    is_flag=True,
    help="Set debug print levels",
)
def main(path, apparatus, base_url, operation_url, release, conf, debug):

    """
    Removes from the operation repos the selected configurations for a given release
    """

    steps = ["Checking options and repositories", "Preparing local repositories", "Removing configurations"]
    context = {
        "Path": path,
        "Apparatuses": "all (defaults)" if apparatus is None else ", ".join(apparatus),
        "Release": release,
        "Configurations": conf,
    }

    with Report("cpm-purge", steps, context=context, debug=debug) as report:
        report.step("Checking options and repositories")
        check_repositories(base_url=base_url)
        report.ok(f"Base repository reachable: {base_url}")
        ## there is no base here, so 'all' stands for the default apparatuses
        operation_urls = select_apparatuses(path, base_url, None, apparatus, operation_url, ssh=True)
        check_repositories(operation_urls=operation_urls)
        report.table("Operation repositories", ["Apparatus", "Repository"], [[a, u] for a, u in operation_urls.items()])
        report.ok(f"{len(operation_urls)} operation repositories reachable")

        report.step("Preparing local repositories")
        pools = open_pools(path, operation_urls, base_url)
        for name, pool in pools.items():
            report.ok(f"{name}: local repo {pool.repo.working_dir}")

        report.step("Removing configurations")
        removed_total = 0
        for name, pool in pools.items():
            report.current_apparatus = name
            removed = pool.remove_configurations(release=release, conf_regex=re.compile(conf))
            removed_total += len(removed)
            if removed:
                report.ok(f"{name}: removed {', '.join(removed)}")
                report.set_result(name, "Removed", f"✔ {len(removed)}")
            else:
                report.warn(f"Nothing removed from {name}")
                report.set_result(name, "Removed", "⚠ 0")
        report.current_apparatus = None

        if not removed_total:
            raise Stop(f"No configuration of {release} matching '{conf}' was found, nothing is removed",
                       hint="Check the release (-r) and the --conf regex, e.g. with cpm-setup")
        report.success_message = f"{removed_total} configurations of {release} removed"
