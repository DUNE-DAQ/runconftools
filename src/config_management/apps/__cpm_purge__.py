#!/usr/bin/env python3

import click
import logging
import os
import re

from runconftools.ConfPool import ConfPool


@click.command(context_settings={'show_default': True}) 
@click.argument("path", type=click.Path(exists=True, file_okay=False, writable=True))
@click.option("-a", "--apparatus",
              type=click.Choice(['np02', 'np04'], case_sensitive=True),
              default="np02", help="Selection of the apparatus")
@click.option(
    "--base_url",
    type=click.STRING,
    default="ssh://git@gitlab.cern.ch:7999/dune-daq/online/ehn1-daqconfigs.git",
    help="URL of the remote base repo"
)
@click.option(
    "--operation_url",
    type=click.STRING,
    default=None,
    help="URL of the remote operation repo. If None, the repo is set according to the apparatus"
)
@click.option("-r", "--release", type=click.STRING, default =None,
              help="Operation branch prefix for the branches to be deleted")
@click.option("--conf", type=click.STRING, default=".*",
              help="Regex to select a subset of branches")

@click.option(
    "--debug",
    type=click.BOOL,
    default=False,
    is_flag=True,
    help="Set debug print levels",
)
def main(path, apparatus, base_url, operation_url, release, conf, debug):

    """
    Removes from the operation repo the selected configurations for a given release 
    """

    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.DEBUG if debug else logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not operation_url :
        match apparatus :
            case "np02" : operation_url = "ssh://git@gitlab.cern.ch:7999/dune-daq/online/np02-configs-operation.git"
            case "np04" : operation_url = "ssh://git@gitlab.cern.ch:7999/dune-daq/online/np04-configs-operation.git"

    pool = ConfPool(path, operation_url=operation_url, base_url=base_url, apparatus=apparatus)

    removed = pool.remove_configurations(release=release, conf_regex=re.compile(conf))
    logging.info("Removed branches: %s", ", ".join(removed))


