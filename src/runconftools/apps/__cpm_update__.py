#!/usr/bin/env python3

# @file cpm-update is the executable used to interact with the ConfigPool class and propagate changes from a base branch to the relevant operation branches
import logging
import os
import re
import sys

import click
from click.core import ParameterSource

from runconftools.apps._common import (
    apparatus_option,
    check_apparatuses,
    check_repositories,
    log_apparatus,
    open_pools,
    operation_url_option,
    select_apparatuses,
)
from runconftools.ConfPool import ConfPool


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
@click.option("-r", "--release", type=click.STRING, default = ConfPool.get_release,
              help="Operation branch prefix for the generated branches. Defaults to the release from SPACK_RELEASE, or develop if it's not set or not a stable release")
@click.option("--conf", type=click.STRING, default=".*",
              help="Regex to select a subset of generators, matched from the start of the name (end it with '$' to match the whole name)")
@click.option("--push-only", type=click.BOOL, default=False, is_flag=True,
              help="When set, it skips the generation and only pushes the existing local branches. "
                   "Nothing is pushed unless all of them come from a successful generation")
@click.option("-p", "--push", type=click.BOOL, default=False, is_flag=True,
              help="Pushes the branches, otherwise they are only created locally")

@click.option(
    "--debug",
    type=click.BOOL,
    default=False,
    is_flag=True,
    help="Set debug print levels",
)
@click.pass_context
def main(ctx, path, apparatus, base_url, operation_url, base, release, conf, push_only, push, debug):

    """
    This script takes the base branch and propagates the changes to the operation repos, creating the necessary configurations.
    As a default, the branches are not pushed, use -p  or --push-only to perform the push.
    When several apparatuses are selected, nothing is pushed unless the generation succeeded for all of them.
    """

    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.DEBUG if debug else logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ## outside of a DAQ environment the defaults fall back to develop, which must not be pushed by accident
    if (push or push_only) and not os.environ.get("SPACK_RELEASE"):
        implicit = [f"--{p}" for p in ("base", "release") if ctx.get_parameter_source(p) == ParameterSource.DEFAULT]
        if implicit:
            raise click.UsageError(f"SPACK_RELEASE is not set: {' and '.join(implicit)} must be given explicitly when pushing")
    logging.info(f"Base: {base}, release: {release}")

    conf_regex = re.compile(conf)

    check_repositories(base_url=base_url)
    operation_urls = select_apparatuses(path, base_url, base, apparatus, operation_url, ssh=True)
    check_repositories(operation_urls=operation_urls)
    pools = open_pools(path, operation_urls, base_url)
    check_apparatuses(pools, base)

    ## a regex matching nothing is most likely a mistake, and apparatuses it does not concern are left untouched
    for name, pool in list(pools.items()):
        if not any(conf_regex.match(g) for g in pool.get_generators(base)):
            logging.warning("No %s generator matches '%s', %s is skipped", name, conf, name)
            del pools[name]
    if not pools:
        raise click.UsageError(f"No generator of the selected apparatuses matches '{conf}'")

    failed = []
    if not push_only :
        for name, pool in pools.items():
            log_apparatus(name)
            if not pool.propagate_base(base=base, release_tag=release, conf_regex=conf_regex, no_push=True):
                failed.append(name)

    if failed :
        logging.error("Something went wrong in the generation phase for: %s", ", ".join(failed))
        if push :
            logging.fatal("The push is not performed for any apparatus")
        sys.exit(1)

    if push or push_only :
        ## only branches coming from a successful generation and accepted by the operation repos
        ## can be pushed, and they are checked for all the apparatuses before pushing anything
        problems = {}
        for name, pool in pools.items():
            pool_problems = pool.check_push(base=base, release_tag=release, conf_regex=conf_regex)
            if pool_problems:
                problems[name] = pool_problems
        if problems :
            for name, pool_problems in problems.items():
                for problem in pool_problems:
                    logging.error("%s: %s", name, problem)
            logging.fatal("The push is not performed for any apparatus")
            sys.exit(1)

        for name, pool in pools.items():
            if not pool.push_configurations(base=base, release_tag=release, conf_regex=conf_regex):
                logging.fatal("Push failed for %s, the remaining apparatuses are not pushed", name)
                sys.exit(1)

        logging.info("Removing configurations whose generators are gone")
        for name, pool in pools.items():
            removals = pool.clean(base=base, release_tag=release)
            if not removals:
                logging.info("Nothing to remove for %s", name)
