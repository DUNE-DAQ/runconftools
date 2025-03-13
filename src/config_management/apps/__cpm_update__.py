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
@click.option("-b", "--base", type=click.STRING, default = ConfPool.get_release() )
@click.option("-r", "--release", type=click.STRING, default = ConfPool.get_release() )
@click.option("--conf", type=click.STRING, default=".*")
@click.option("--push-only", type=click.BOOL, default=False, is_flag=True,
              help="When set, it only pushes local branches, without regenerating")
@click.option("--no-push", type=click.BOOL, default=False, is_flag=True,
              help="Executes the generators only on local branches without pushing")

@click.option(
    "--debug",
    type=click.BOOL,
    default=False,
    is_flag=True,
    help="Set debug print levels",
)
def main(path, apparatus, base_url, operation_url, base, release, conf, push_only, no_push, debug):

    """
    This script takes the a base branch and propagates the changes to the operaiton repo, creating the necessary configurations.
    """

    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.DEBUG if debug else logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    pool = ConfPool(path, operation_url=operation_url, base_url=base_url)

    if not push_only :
        pool.propagate_base(base=base, release_tag=release, conf_regex=re.compile(conf), no_push=True)

    if not no_push :
        pool.push_configurations(base=base, release_tag=release, conf_regex=re.compile(conf))


