# config-management

This pythin repository has the goal of interfacing with the operation repostiories used to store the configuration used for runnning. 
As the configurations are generated from `ehn1-configs`, also known as the base repository, the scripts start from the base to construct the necessary operation branches, which are ultimately the configurations. 

## Configuration branches
The branches on the operation repostiories are named as `<version>/<configuration_key>`. 
For stable configurations, `<version>` is in the form of `fddaq-v5.2.2`, but in general it can be any string specified at the time that the generators are executed. 
The `<configuration_key>` is the name of the generator used to create the configuration. 

## Installation


## Scripts 
Experts interacting with the operation repository have just a few scripts that they can use. 
All the scrip names start with `cpm-` that stands for Configuration Pool Management.


### cpm-setup 
This is mostly a diagnostic scripts designed to setup a local area linked to both base and operation repostiories and to print some information about the configurations.

```bash
Usage: cpm-setup [OPTIONS] PATH

  Set up a local repo and prints some informations.  If the conf option is
  specified, the relevant configuration from operation is checked out for
  inspection.

Options:
  -a, --apparatus TEXT  [default: np02]
  --base_url TEXT       [default: ssh://git@gitlab.cern.ch:7999/dune-
                        daq/online/ehn1-daqconfigs.git]
  --operation_url TEXT  [default: ssh://git@gitlab.cern.ch:7999/dune-
                        daq/online/np02-configs-operation.git]
  -r, --release TEXT    [default: fddaq-v5.2.2]
  -b, --base TEXT
  -c, --conf TEXT
  --debug               Set debug print levels
  --help                Show this message and exit.
```

The `PATH` has to be an existing location and has to be either empty or a valid `ehn1-configs` repository. 
Be aware that if the directory contains a repostiories some local changes might be lost, so please push all the changes that are important. 

The script simply sets up a git repository and prints some information about the release. 

The information printed is:
 - The list of available branches in the base, without any filtering;
 - The list of available releases in operation;
 - The list of available generators in the selected base;
 - The list of configurations on operation for the selected release;
 - The list of verifiers to be called once a configuration is generated.

### cpm-update
This is the script that takes the a base branche and propagates the changes to the operaiton repo, creating the necessary configurations. 

```bash

```



