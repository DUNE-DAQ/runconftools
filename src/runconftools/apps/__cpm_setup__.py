#!/usr/bin/env python3

# @file cpm-setup is the executable used to interact with the ConfigPool class and setup a working environment
import re

import click

from runconftools.apps._common import (
    apparatus_option,
    check_apparatuses,
    check_repositories,
    open_pools,
    operation_url_option,
    select_apparatuses,
    validate_release,
)
from runconftools.ConfPool import ConfPool
from runconftools.report import Report, Stop


@click.command(context_settings={'show_default': True})
@click.argument("path", type=click.Path(exists=False, file_okay=False, writable=True))
@apparatus_option("all the apparatuses defined in the base")
@click.option(
    "--base_url",
    type=click.STRING,
    default="https://gitlab.cern.ch/dune-daq/online/ehn1-daqconfigs.git",
    help="URL of the base repository"
)
@operation_url_option()
@click.option("-r", "--release", type=click.STRING, default = ConfPool.get_release, callback=validate_release,
              help="Release whose configurations are listed. Defaults to the release from SPACK_RELEASE, or develop if it's not set or not a stable release")
@click.option("-b", "--base", type=click.STRING, default = None, help="Base branch to inspect. If None, it's set equal to the release")
@click.option("-c", "--conf", type=click.STRING, default=None, help="Configuration key to be checked out. If None, the base is checked out instead")
@click.option(
    "--debug",
    type=click.BOOL,
    default=False,
    is_flag=True,
    help="Set debug print levels",
)
def main(path, apparatus, base_url, operation_url, release, base, conf, debug):

    """
    Set up a local repo per apparatus and print some information.
    If the conf option is specified, the chosen configuration from operation is checked out for inspection.
    """

    if not base :
        base = release

    steps = ["Checking options and repositories", "Preparing local repositories", "Inspecting configurations"]
    if conf:
        steps.append("Checking out the configuration")
    context = {
        "Path": path,
        "Apparatuses": "all" if apparatus is None else ", ".join(apparatus),
        "Base": base,
        "Release": release,
    }
    if conf:
        context["Configuration"] = conf

    with Report("cpm-setup", steps, context=context, debug=debug) as report:
        report.columns = ["Generators", "Configurations", "Checked out"]
        report.step("Checking options and repositories")
        check_repositories(base_url=base_url)
        report.ok(f"Base repository reachable: {base_url}")
        operation_urls = select_apparatuses(path, base_url, base, apparatus, operation_url, ssh=False)
        check_repositories(operation_urls=operation_urls)
        report.table("Operation repositories", ["Apparatus", "Repository"], [[a, u] for a, u in operation_urls.items()])
        report.ok(f"{len(operation_urls)} operation repositories reachable")

        report.step("Preparing local repositories")
        pools = open_pools(path, operation_urls, base_url)
        check_apparatuses(pools, base)
        for name, pool in pools.items():
            report.ok(f"{name}: local repo {pool.repo.working_dir}")

        report.step("Inspecting configurations")
        bases = []
        for name, pool in pools.items():
            report.current_apparatus = name
            bases = pool.get_base_branches()
            versions = pool.get_daq_versions()
            gens = pool.get_generators(base=base)
            confs = pool.get_confs(release=re.compile(release))
            verifiers = pool.get_verifiers(base=base)
            report.table(name, ["", "Available"], [
                ["Releases in operation", ", ".join(sorted(versions))],
                [f"Generators in {base}", ", ".join(sorted(gens))],
                [f"Configurations of {release}", ", ".join(sorted(confs))],
                ["Verifiers", ", ".join(sorted(verifiers))],
            ])
            report.set_result(name, "Generators", str(len(gens)))
            report.set_result(name, "Configurations", str(len(confs)))
        report.current_apparatus = None
        report.info(f"Base branches: {', '.join(sorted(bases))}")

        if conf:
            report.step("Checking out the configuration")
            missing = []
            for name, pool in pools.items():
                report.current_apparatus = name
                if pool.checkout_conf(release=release, conf=conf) is None:
                    missing.append(name)
                    report.error(f"{name}: configuration {conf} of {release} not found")
                    report.set_result(name, "Checked out", "✘ not found")
                else:
                    report.ok(f"{name}: {release}/{conf} checked out in {pool.repo.working_dir}")
                    report.set_result(name, "Checked out", "✔")
            report.current_apparatus = None
            if len(missing) == len(pools):
                raise Stop(f"Configuration {conf} of {release} not found for any apparatus",
                           hint="Check the name in 'Configurations' above")

        report.success_message = f"Local repos ready in {path} for {', '.join(pools)}"
