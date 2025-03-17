#!/usr/bin/env python3

# @file cpm-update is the executable used to interact with the ConfigPool class and propagate changes from a base branch to the relevant operation branches

import click
import logging
import os
import re

from config_management.ConfPool import ConfPool


@click.command(context_settings={'show_default': True}) 
@click.argument("path", type=click.Path(exists=True, file_okay=False, writable=True))
@click.option("-a", "--apparatus",
              type=click.Choice(['np02', 'np04'], case_sensitive=True),
              default="np02", help="Selection of the apparatus")
@click.option(
    "--base_url",
    type=click.STRING,
    default="ssh://git@gitlab.cern.ch:7999/dune-daq/online/ehn1-daqconfigs.git",
    help="Git location of the remote base repo"
)
@click.option(
    "--operation_url",
    type=click.STRING,
    default=None,
    help="Git location of the remote operation repo. If None, the repo is set according to the apparatus"
)
@click.option("-b", "--base", type=click.STRING, default = ConfPool.get_release(),
              help="Base branch to be used as a starting point")
@click.option("-r", "--release", type=click.STRING, default = ConfPool.get_release(),
              help="Operation branch prefix for the generated branches")
@click.option("--conf", type=click.STRING, default=".*",
              help="Regex to select a subset of generators")
@click.option("--push-only", type=click.BOOL, default=False, is_flag=True,
              help="When set, it only pushes local branches, without regenerating")
@click.option("-p", "--push", type=click.BOOL, default=False, is_flag=True,
              help="Pushes the branhces, otherwise they are only created locally")

@click.option(
    "--debug",
    type=click.BOOL,
    default=False,
    is_flag=True,
    help="Set debug print levels",
)
def main(path, apparatus, base_url, operation_url, base, release, conf, push_only, push, debug):

    """
    This script takes the a base branch and propagates the changes to the operation repo, creating the necessary configurations.
    As a default, the branches are not pushed, use -p  or --push-only to perform the push
    """

    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.DEBUG if debug else logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not operation_url :
        match apparatus :
            case "np02" : operation_url = "ssh://git@gitlab.cern.ch:7999/dune-daq/online/np02-configs-operation.git"
            case "np04" : operation_url = "ssh://git@gitlab.cern.ch:7999/dune-daq/online/np04-configs-operations.git"

    pool = ConfPool(path, operation_url=operation_url, base_url=base_url)

    all_ok = True
    if not push_only :
        all_ok = pool.propagate_base(base=base, release_tag=release, conf_regex=re.compile(conf), no_push=True)


    if (not all_ok) and push :
        logging.fatal("Something went wrong in the generation phase so the push is not performed")
        
    if (push and all_ok) or push_only :
        pool.push_configurations(base=base, release_tag=release, conf_regex=re.compile(conf))


