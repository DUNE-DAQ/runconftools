#!/usr/bin/env python3

# @file cpm-setupo is the executable used to interact with the ConfigPool class and setup a working environment

import click
import logging
import os
import re

from config_management.ConfPool import ConfPool



def cli(path, apparatus, base, operation, release, conf, debug):
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.DEBUG if debug else logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    pool = ConfPool(path, operation_url=operation, base_url=base)

    cods = pool.get_cods()
    logging.info("Available CODs: {}".format(", ".join(cods)))

    versions = pool.get_daq_versions()
    logging.info(
        "Configurations are available for the following releases: {}".format(
            ", ".join(versions)
        )
    )

    gens = pool.get_generators(cod=release)
    logging.info("Available Generators: {}".format(", ".join(gens)))

    confs = pool.get_confs(release=re.compile(release))
    logging.info("Available Configurations: {}".format(", ".join(confs)))

    if conf:
        pool.checkout_conf(release=release, conf=conf)


@click.command(context_settings={'show_default': True})
@click.argument("path", type=click.Path(exists=True, file_okay=False, writable=True))
@click.option("-a", "--apparatus", type=click.STRING, default="np02")
@click.option(
    "-b",
    "--base",
    type=click.STRING,
    default="ssh://git@gitlab.cern.ch:7999/dune-daq/online/ehn1-daqconfigs.git",
)
@click.option(
    "-o",
    "--operation",
    type=click.STRING,
    default="ssh://git@gitlab.cern.ch:7999/dune-daq/online/np02-configs-operation.git",
)
@click.option("-r", "--release", type=click.STRING, default=os.environ["SPACK_RELEASE"])
@click.option("-c", "--conf", type=click.STRING, default=None)
@click.option(
    "--debug",
    type=click.BOOL,
    default=False,
    is_flag=True,
    help="Set debug print levels",
)
def main(
    path: str,
    apparatus: str,
    base: str,
    operation: str,
    release: str,
    conf: str,
    debug: bool,
):
    """
    Add a docstring
    """
    cli(
        path, apparatus, base, operation, release, conf, debug
    ) 
