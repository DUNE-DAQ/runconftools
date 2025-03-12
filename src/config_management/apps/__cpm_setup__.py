#!/usr/bin/env python3

# @file cpm-setupo is the executable used to interact with the ConfigPool class and setup a working environment

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
@click.option("-r", "--release", type=click.STRING, default = ConfPool.get_release())
@click.option("-c", "--conf", type=click.STRING, default=None)
@click.option(
    "--debug",
    type=click.BOOL,
    default=False,
    is_flag=True,
    help="Set debug print levels",
)
def main(path, apparatus, base_url, operation_url, release, conf, debug):

    """
    Add a docstring
    """

    logging.basicConfig( format="%(asctime)s %(levelname)-8s %(message)s",
                         level=logging.DEBUG if debug else logging.INFO,
                         datefmt="%Y-%m-%d %H:%M:%S",
    )

    pool = ConfPool(path, operation_url=operation_url, base_url=base_url)

    bases = pool.get_base_branches()
    logging.info("Available baess: {}".format(", ".join(bases)))

    versions = pool.get_daq_versions()
    logging.info(
        "Configurations are available for the following releases: {}".format(
            ", ".join(versions)
        )
    )

    gens = pool.get_generators(base=release)
    logging.info("Available Generators: {}".format(", ".join(gens)))

    confs = pool.get_confs(release=re.compile(release))
    logging.info("Available Configurations: {}".format(", ".join(confs)))

    if conf:
        pool.checkout_conf(release=release, conf=conf)


