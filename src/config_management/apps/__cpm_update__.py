#!/usr/bin/env python3

# @file cpm-update is the executable used to interact with the ConfigPool class and propagate changes from a base branch to the relevant operation branches

import click
import logging
import os
import re

from config_management.ConfPool import ConfPool


@click.command(context_settings={'show_default': True}) 
@click.argument("path", type=click.Path(exists=True, file_okay=False, writable=True))
@click.option("-a", "--apparatus", type=click.STRING, default="np02")
@click.option(
    "--base_url",
    type=click.STRING,
    default="ssh://git@gitlab.cern.ch:7999/dune-daq/online/ehn1-daqconfigs.git",
)
@click.option(
    "--operation_url",
    type=click.STRING,
    default="ssh://git@gitlab.cern.ch:7999/dune-daq/online/np02-configs-operation.git",
)
@click.option("-b", "--base", type=click.STRING, default=os.environ["SPACK_RELEASE"])
@click.option("-r", "--release", type=click.STRING, default=os.environ["SPACK_RELEASE"])
@click.option("--conf", type=click.STRING, default=".*")
@click.option(
    "--debug",
    type=click.BOOL,
    default=False,
    is_flag=True,
    help="Set debug print levels",
)
def main(path, apparatus, base_url, operation_url, base, release, conf, debug):

    """
    Add a docstring
    """

    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.DEBUG if debug else logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    pool = ConfPool(path, operation_url=operation_url, base_url=base_url)
    pool.propagate_base(base=base, release_tag=release, conf_regex=re.compile(conf))


