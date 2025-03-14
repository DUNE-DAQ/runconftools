#!/usr/bin/env python3

# @file cpm-setupo is the executable used to interact with the ConfigPool class and setup a working environment

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
    default="https://gitlab.cern.ch/dune-daq/online/ehn1-daqconfigs.git",
)
@click.option(
    "--operation_url",
    type=click.STRING,
    default=None,
)
@click.option("-r", "--release", type=click.STRING, default = ConfPool.get_release())
@click.option("-b", "--base", type=click.STRING, default = None, help="If None, it's set equal to the release")
@click.option("-c", "--conf", type=click.STRING, default=None)
@click.option(
    "--debug",
    type=click.BOOL,
    default=False,
    is_flag=True,
    help="Set debug print levels",
)
def main(path, apparatus, base_url, operation_url, release, base, conf, debug):

    """
    Set up a local repo and prints some informations. 
    If the conf option is specified, the relevant configuration from operation is checked out for inspection. 
    """

    logging.basicConfig( format="%(asctime)s %(levelname)-8s %(message)s",
                         level=logging.DEBUG if debug else logging.INFO,
                         datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not operation_url :
        match apparatus :
            case "np02" : operation_url = "https://gitlab.cern.ch/dune-daq/online/np02-configs-operation.git"
            case "np04" : operation_url = "https://gitlab.cern.ch/dune-daq/online/np04-configs-operations.git"
        
    pool = ConfPool(path, operation_url=operation_url, base_url=base_url)

    bases = pool.get_base_branches()
    logging.info("Available bases: {}".format(", ".join(bases)))

    versions = pool.get_daq_versions()
    logging.info(
        "Configurations are available for the following releases: {}".format(
            ", ".join(versions)
        )
    )

    if not base :
        base = release
    gens = pool.get_generators(base=base)
    logging.info("Available Generators: {}".format(", ".join(gens)))

    confs = pool.get_confs(release=re.compile(release))
    logging.info("Available Configurations: {}".format(", ".join(confs)))

    verifiers = pool.get_verifiers(base=base)
    logging.info("Available verifiers: {}".format(", ".join(verifiers)))
    
    if conf:
        pool.checkout_conf(release=release, conf=conf)


