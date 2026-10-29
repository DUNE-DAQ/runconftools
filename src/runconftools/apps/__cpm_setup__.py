#!/usr/bin/env python3

# @file cpm-setup is the executable used to interact with the ConfigPool class and setup a working environment
import logging
import re

import click

from runconftools.apps._common import (
    apparatus_option,
    log_apparatus,
    open_pools,
    operation_url_option,
    select_apparatuses,
)
from runconftools.ConfPool import ConfPool


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
@click.option("-r", "--release", type=click.STRING, default = ConfPool.get_release())
@click.option("-b", "--base", type=click.STRING, default = None, help="If None, it's set equal to the release")
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
    Set up a local repo per apparatus and prints some information.
    If the conf option is specified, the chosen configuration from operation is checked out for inspection.
    """

    logging.basicConfig( format="%(asctime)s %(levelname)-8s %(message)s",
                         level=logging.DEBUG if debug else logging.INFO,
                         datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not base :
        base = release

    operation_urls = select_apparatuses(path, base_url, base, apparatus, operation_url, ssh=False)
    pools = open_pools(path, operation_urls, base_url)

    for name, pool in pools.items():
        log_apparatus(name)

        bases = pool.get_base_branches()
        logging.info("Available bases: {}".format(", ".join(bases)))

        versions = pool.get_daq_versions()
        logging.info(
            "Configurations are available for the following releases: {}".format(
                ", ".join(versions)
            )
        )

        gens = pool.get_generators(base=base)
        logging.info("Available Generators: {}".format(", ".join(gens)))

        confs = pool.get_confs(release=re.compile(release))
        logging.info("Available Configurations: {}".format(", ".join(confs)))

        verifiers = pool.get_verifiers(base=base)
        logging.info("Available verifiers: {}".format(", ".join(verifiers)))

        if conf:
            pool.checkout_conf(release=release, conf=conf)
