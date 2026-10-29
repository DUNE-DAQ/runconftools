#!/usr/bin/env python3

import logging
import re
import sys

import click

from runconftools.apps._common import (
    apparatus_option,
    check_repositories,
    log_apparatus,
    open_pools,
    operation_url_option,
    select_apparatuses,
    validate_release,
)


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

    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.DEBUG if debug else logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    check_repositories(base_url=base_url)
    ## there is no base here, so 'all' stands for the default apparatuses
    operation_urls = select_apparatuses(path, base_url, None, apparatus, operation_url, ssh=True)
    check_repositories(operation_urls=operation_urls)
    pools = open_pools(path, operation_urls, base_url)

    removed_any = False
    for name, pool in pools.items():
        log_apparatus(name)
        removed = pool.remove_configurations(release=release, conf_regex=re.compile(conf))
        if removed:
            removed_any = True
            logging.info("Removed branches from %s: %s", name, ", ".join(removed))
        else:
            logging.warning("Nothing removed from %s", name)

    if not removed_any:
        logging.error(f"No configuration of {release} matching '{conf}' was found, nothing is removed")
        sys.exit(1)
