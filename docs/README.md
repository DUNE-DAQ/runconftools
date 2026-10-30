# runconftools

This python repository interfaces with the operation repositories that store the configurations used at EHN1. 
The configurations are generated from the base `ehn1-daqconfigs`, https://gitlab.cern.ch/dune-daq/online/ehn1-daqconfigs.
The scripts start from the base to construct the necessary operation branches, which are ultimately the configurations. 

This repository is intended for direct use by experts only. 
Shifters will use these interfaces indirectly via the shifter interface. 

## High level view
According to our configuration model, the different configurations to be used for operations are stored in different branches of operation repositories. 
No one is expected to interface directly with those repositories: all operations are expected to be done via the interfaces defined in `runconftools`.
There is one operation repository for each apparatus.  
The definition of which apparati are available depends on the base repository: they are the subdirectories of `functions/generators` in the base branch, so different base branches can define different apparati.
In the interfaces defined in `runconftools` we simply provide default values for apparati and their URLs (see `src/runconftools/Apparatus.py`). By no means should this stop the development of other repos.

The branches in the operation repositories are derived using configuration generation functions (known as generators), starting from a base repository. 
The base repository contains both OKS objects and generators used to create operation configurations. 
How to write a generator is described in [generator_creation.md](generator_creation.md), while [workflow.md](workflow.md) shows how a change in the base reaches the operation repositories.

## Configuration branches
The branches on the operation repositories are named as `<version>/<configuration_key>`. 
For stable configurations, `<version>` is in the form of `fddaq-v5.x.y` (e.g. `fddaq-v5.7.2`), but in general it can be any string specified at the time that the generators are executed. 
The `<configuration_key>` is the name of the generator used to create the configuration. 

Here are some examples:
 - `develop/monitoring_no_tpg` is the configuration called `monitoring_no_tpg` compatible with the OKS schema published with the nightly build including the develop branches used at the time of generation.
 - `fddaq-v5.7.2/daphne_selftrigger` is the configuration called `daphne_selftrigger` to be used with DAQ version v5.7.2. Note that this is used also for prep-release branches and release candidates of the DAQ for v5.7.2. 
 - `mroda-test/monitoring_no_tpg` is a temporary configuration that might eventually replace the current `monitoring_no_tpg` pending testing. These temporary branches should be created if a particular configuration must be tested from the shifter.
   This is necessary as the shifter interface only sees whatever is stored in the operation repo. 

The default branch of each operation repository is ignored when listing the configurations and is never removed by the scripts.

## Installation
This is a python package, which requires python 3.10 or newer, so just checkout the repo and call
```bash
git clone https://github.com/DUNE-DAQ/runconftools.git
cd runconftools
pip install .
```
Please remember that this requires the proxy from EHN1 machines. 

### Access to the repositories
In order to run the scripts you need access to CERN gitlab repositories and you should
 - setup an ssh key to CERN gitlab, in order to use `cpm-update` and `cpm-purge`, which use ssh URLs by default
 - setup a netrc file to allow your git to access the configuration repositories via a token, which is used by `cpm-setup` as it uses https URLs by default

In the np04 machines, for the user `np04daq` this is already setup.

### netrc configuration
The gitlab token is contained in the home of `np04daq` in the file `.netrc`. For obvious reason we cannot share it freely. 
Copy the file in your home directory. 
Please note that the file has to be visible only from the user, so you need to log in as `np04daq` and copy the content, you cannot just copy the file. 
In your file, change the username to your username. 
Make sure that your file has the following permissions:
```bash
-rw------- 1 np04daq np-comp 74 Mar 14 12:56 .netrc
```

The next step is to configure git so that it uses the .netrc file. 
This can be done by adding to your `.gitconfig` file the following block:
```
[credential]
        helper = netrc
```

## Scripts 
This repository provides the following scripts.
All script names start with `cpm-`, which stands for Configuration Pool Management.

The default release (`-r`) and, for `cpm-update`, the default base (`-b`) are taken from the DAQ environment: 
for `SPACK_RELEASE=fddaq-v5.7.2-a9-1` they are `fddaq-v5.7.2`. 
If `SPACK_RELEASE` is not set or is not a stable release (e.g. a nightly), they default to `develop`. 
To avoid pushing `develop` by accident, when `SPACK_RELEASE` is not set `cpm-update` requires `-b` and `-r` to be given explicitly in order to push. 
The base and release in use are always printed.

As the configuration branches are named `<release>/<configuration_key>`, a release cannot contain `/`, cannot start with `-` and must be valid in a git branch name. 

### Output and exit codes
All the scripts report what they do in the same way:
 - a header with the parameters of the run (path, apparati, base, release, ...) and the list of the steps;
 - each step starts with a line `Step <i>/<n> · <name>`, so it is always clear where the script is;
 - during the generation, every configuration is printed with its result, counter and percentage, e.g. `✔ [ 7/48  15%] np02 · monitoring` or `✘ [ 8/48  17%] np04 · femb_pulser — verifier readout_verification failed`, and on a terminal a live progress bar is shown;
 - a summary at the end, also when the script stops because of an error: a table with the result of each apparatus, 
   the failed configurations with the reason, all the errors and warnings with the step (and apparatus) where they happened, 
   and a final verdict, `SUCCESS`, `COMPLETED WITH ERRORS` or `FAILED`. 
   A failure says at which step the script stopped, what was not done (e.g. `Nothing was pushed to any operation repository.`) and what to do next.

On a terminal the output is coloured. When it is redirected, e.g. to a file, it is plain text and every log line has a timestamp, so it can be searched with the usual tools. 
The colours can also be disabled with the `NO_COLOR` environment variable. 

The generators and the verifiers print a lot. With `cpm-update -q` (`--quiet`) their output is not printed but saved in `PATH/_logs/<apparatus>/<generator>.log`, overwritten at every run, 
so that only the steps, the result of each configuration and the errors are printed, while the warnings are listed in the summary. 
If a configuration fails, the summary shows its log file and its last lines. 
The details of the git operations and of the generators are printed with `--debug`.

The exit code is `0` on success, `1` when the script stops because of a failure, `2` for wrong options and `130` when interrupted.

### Checks before starting
Before anything is cloned or changed, all the scripts check that:
 - the base and the operation repositories can be reached (which also checks your credentials) and that each operation repository has a default branch;
 - no two apparati share the same operation repository, also when written as ssh and https URLs, and the base is not used as an operation repository;
 - the local repositories `PATH/<apparatus>` have no uncommitted changes, which could end up in the configurations. 
   Inspect them with `git status`, then commit or discard the changes, or use a new `PATH`.

The operation repository used for each apparatus is printed.

### Working on several apparatuses
All the scripts accept one or more apparatuses with `-a`, either repeating the option or as a comma separated list:
```bash
cpm-update -b fddaq-v5.7.2 -r fddaq-v5.7.2 -a np02,np04 TempTest
cpm-update -b fddaq-v5.7.2 -r fddaq-v5.7.2 -a np02 -a np04 TempTest
```
If `-a` is not given, only `np02` is used.
`-a all` selects all the apparatuses: for `cpm-setup` and `cpm-update` these are the apparati defined in the selected base, 
for `cpm-purge`, which has no base, these are the apparati with a default operation repository in `runconftools`.

Every apparatus gets its own local repository in `PATH/<apparatus>` (e.g. `TempTest/np02`), since the configuration branches of different apparati share the same names. 
`PATH` and its subdirectories are created if needed. 
With `-a all`, the base is inspected in `PATH/_base`.

> [!NOTE]
> Up to version 1.3, the local repository was `PATH` itself. 
> Since 1.4 it is `PATH/<apparatus>`, also when a single apparatus is selected, so an area created with an older version is not reused. 
> In particular, `cpm-update --push-only` only pushes the branches generated in `PATH/<apparatus>`.

The operation repositories default to the ones known by `runconftools`. 
They can be overridden per apparatus with `--operation_url <apparatus>=<url>`, which is mandatory for apparati without a default.
A plain `--operation_url <url>` is still accepted when a single apparatus is selected.
If an existing local repository points to a different operation (or base) repository than the requested one, its remote is updated with a warning.

### cpm-setup 
This is a diagnostic script designed to setup a local area linked to both base and operation repositories and to print some information about the configurations.

```
Usage: cpm-setup [OPTIONS] PATH

  Set up a local repo per apparatus and print some information. If the conf
  option is specified, the chosen configuration from operation is checked out
  for inspection.

Options:
  -a, --apparatus TEXT  Apparatuses to act on, either repeating the option or
                        as a comma separated list, e.g. '-a np02,np04'. Use
                        'all' for all the apparatuses defined in the base.
                        Each apparatus uses the local repo PATH/<apparatus>
                        [default: np02]
  --base_url TEXT       URL of the base repository  [default:
                        https://gitlab.cern.ch/dune-
                        daq/online/ehn1-daqconfigs.git]
  --operation_url TEXT  URL of the operation repo as <apparatus>=<url>,
                        repeated or comma separated. Apparatuses without an
                        explicit URL use their default repo. A plain <url> is
                        accepted when a single apparatus is selected
  -r, --release TEXT    Release whose configurations are listed. Defaults to
                        the release from SPACK_RELEASE, or develop if it's not
                        set or not a stable release  [default: (dynamic)]
  -b, --base TEXT       Base branch to inspect. If None, it's set equal to the
                        release
  -c, --conf TEXT       Configuration key to be checked out. If None, the base
                        is checked out instead
  --debug               Set debug print levels
  --help                Show this message and exit.
```

For each apparatus, `PATH/<apparatus>` has to be either empty or a valid `ehn1-daqconfigs` repository. 
If the directory contains a local repository, local changes may be lost so please push all changes that are important before calling `cpm-setup` on a non-empty directory.

As for `cpm-update`, the base must exist and define each selected apparatus. 

This script sets up a git repository per apparatus and prints, for each of them: 
 - The list of available branches in the base, without any filtering;
 - The list of available releases in operation;
 - The list of available generators in the selected base;
 - The list of configurations in the operation repository for the selected release;
 - The list of verifiers called once a configuration is generated.

With `-c`, the configuration is checked out in the repository of each apparatus. 
If it does not exist for some apparati an error is printed, and if it does not exist for any of them the script exits with an error.

### cpm-update
This is the script that takes a base branch and propagates the changes to the operation repositories, creating the necessary configurations. 

```
Usage: cpm-update [OPTIONS] PATH

  This script takes the base branch and propagates the changes to the
  operation repos, creating the necessary configurations. As a default, the
  branches are not pushed, use -p  or --push-only to perform the push. When
  several apparatuses are selected, nothing is pushed unless the generation
  succeeded for all of them.

Options:
  -a, --apparatus TEXT  Apparatuses to act on, either repeating the option or
                        as a comma separated list, e.g. '-a np02,np04'. Use
                        'all' for all the apparatuses defined in the base.
                        Each apparatus uses the local repo PATH/<apparatus>
                        [default: np02]
  --base_url TEXT       URL of the remote base repo  [default:
                        ssh://git@gitlab.cern.ch:7999/dune-
                        daq/online/ehn1-daqconfigs.git]
  --operation_url TEXT  URL of the operation repo as <apparatus>=<url>,
                        repeated or comma separated. Apparatuses without an
                        explicit URL use their default repo. A plain <url> is
                        accepted when a single apparatus is selected
  -b, --base TEXT       Base branch to be used as a starting point. Defaults
                        to the release from SPACK_RELEASE, or develop if it's
                        not set or not a stable release  [default: (dynamic)]
  -r, --release TEXT    Operation branch prefix for the generated branches.
                        Defaults to the release from SPACK_RELEASE, or develop
                        if it's not set or not a stable release  [default:
                        (dynamic)]
  --conf TEXT           Regex to select a subset of generators, matched from
                        the start of the name (end it with '$' to match the
                        whole name)  [default: .*]
  --push-only           When set, it skips the generation and only pushes the
                        existing local branches. Nothing is pushed unless all
                        of them come from a successful generation
  -p, --push            Pushes the branches, otherwise they are only created
                        locally
  -q, --quiet           Do not print the output of the generators and
                        verifiers, save it in
                        PATH/_logs/<apparatus>/<generator>.log instead. Only
                        the steps, the results and the errors are printed, the
                        warnings are in the summary
  --debug               Set debug print levels
  --help                Show this message and exit.
```

As for the setup, `PATH/<apparatus>` has to be either empty or a valid `ehn1-daqconfigs` repository. 
As previously, ensure local changes are pushed before using an existing path with this script.
It is recommended that a new directory is created for the operation. 
It can be deleted once the propagation is complete. 

Each selected apparatus must be defined in the base, otherwise the script stops before generating anything.

The script starts by checking out the required base. 
Then, for every generator of the apparatus in the base, it creates the branches using the `release` option as `version` to be used in the branch name. 
The generators to be executed are selected using a regex with the option `conf`, which is matched from the start of the generator name. 
For example
```bash
cpm-update -a np04 -r mroda --conf "monitoring" Test
```
will create branches called `mroda/monitoring<something>` (e.g. `mroda/monitoring` and `mroda/monitoring_no_tpg`) and will ignore all the other generators.
Use `--conf "monitoring$"` to select only `monitoring`.
If the regex matches no generator of an apparatus, that apparatus is skipped: it is neither generated, nor pushed, nor cleaned. 
If it matches no generator at all, the script stops with an error.

The generators use the software of the DAQ environment: when generating configurations for a stable release (e.g. `-r fddaq-v5.7.2`) from the environment of a different release, a warning is printed. 

When generators are executed, so are the configuration verifiers. 
If the base has no verifiers, the configurations cannot be verified and the generation fails. 
If present, the configuration validator associated to the generator is also executed. 
If a generator, a verifier or a validator fails, the generation is considered failed but the local branch is kept, which allows to investigate the issue. 
The changes are committed to the local branch, also when the generator raised an exception (the commit message then ends with `[failed with an exception]`), so the working tree is clean for the next generator.

By default, the script does not push.
This is done explicitly with the `-p` option.
With `-p`, the branches are pushed only if the generation succeeded for all the selected generators of all the selected apparati: if anything failed, nothing is pushed and the script exits with an error.

After a local generation, `cpm-update` can be followed up with another call with `--push-only`, which skips the generation and pushes the local branches corresponding to the existing generators selected by `conf`. 

A branch that failed or is broken is never pushed, neither with `-p` nor with `--push-only`. 
When a generation succeeds (generator, verifiers and validator), its commit is recorded in the local ref `refs/runconftools/verified/<branch>`; 
the record is removed as soon as the branch is regenerated, and a branch is only pushed if it still points to the recorded commit. 
So `--push-only` refuses branches whose last generation failed, branches changed by hand after the generation, and branches generated by versions before 1.4. 
If any selected branch of any selected apparatus is not verified, nothing is pushed and the script exits with an error: regenerate the configurations first.

Before pushing anything, the push of every branch of every apparatus is also tried with `git push --dry-run`. 
This detects missing credentials and branches that were changed on the operation repository in the meantime, in which case nothing is pushed. 
Rules applied by the server when receiving the push, like protected branches, cannot be checked in advance.

After pushing, with either `-p` or `--push-only`, the branches of the release whose generators no longer exist in the base are removed from the operation repositories. 
The branches to be removed are printed before removing them. 
If the base has no generators for an apparatus, nothing is removed from its operation repository, as all its configurations would look obsolete. 
Note that the removal compares with the base given with `-b`: always use the base the release was generated from.

### cpm-purge
Sometimes temporary branches must be pushed to operation repositories as they need to be tested through the shifter interface.
Once the test is done the branches should be removed with `cpm-purge`.
```
Usage: cpm-purge [OPTIONS] PATH

  Removes from the operation repos the selected configurations for a given
  release

Options:
  -a, --apparatus TEXT  Apparatuses to act on, either repeating the option or
                        as a comma separated list, e.g. '-a np02,np04'. Use
                        'all' for all the apparatuses with a default operation
                        repo. Each apparatus uses the local repo
                        PATH/<apparatus>  [default: np02]
  --base_url TEXT       URL of the remote base repo  [default:
                        ssh://git@gitlab.cern.ch:7999/dune-
                        daq/online/ehn1-daqconfigs.git]
  --operation_url TEXT  URL of the operation repo as <apparatus>=<url>,
                        repeated or comma separated. Apparatuses without an
                        explicit URL use their default repo. A plain <url> is
                        accepted when a single apparatus is selected
  -r, --release TEXT    Operation branch prefix for the branches to be deleted
                        [required]
  --conf TEXT           Regex to select a subset of branches, matched from the
                        start of the configuration name (end it with '$' to
                        match the whole name)  [default: .*]
  --debug               Set debug print levels
  --help                Show this message and exit.
```

This removes the branches for the release specified with `-r`, which is mandatory.
As for the update script, the configuration keys can be selected using a regex with the option `--conf`, which is matched from the start of the configuration name. 
If nothing is removed from any of the selected apparati, e.g. because the release or the configurations do not exist, the script exits with an error. 
For example, `cpm-purge -a all -r mroda-test Temp` removes all the `mroda-test` configurations from all the operation repositories.

## Python interface
The scripts are thin wrappers around the `ConfPool` class, which can be used directly. 
A `ConfPool` links a local repository to the base and to the operation repository of one apparatus:
```python
from pathlib import Path

from runconftools.ConfPool import ConfPool

## base-only pool: no operation repository, only the base related methods can be used
## the directory must exist, and be either empty or a local repository
Path("Temp/_base").mkdir(parents=True, exist_ok=True)
pool = ConfPool("Temp/_base", apparatus=None, base_url="https://gitlab.cern.ch/dune-daq/online/ehn1-daqconfigs.git")
apparati = pool.get_apparatuses("fddaq-v5.7.2")   ## e.g. ['np02', 'np02_emu', 'np04', 'np04_emu', 'vd_coldbox']
defaults = pool.get_apparatuses()                 ## without a base, the defaults known by runconftools

## operation URL of each apparatus, explicit URLs override the defaults
urls = ConfPool.set_apparatuses(apparati, {"np02": "ssh://..."}, ssh=True)
```
Methods that need an operation repository raise a `RuntimeError` on a base-only pool. 
`push_configurations` only pushes branches that come from a successful generation, see `is_verified` and `get_unverified_configurations`. 
`ConfPool` is used directly by [runconf-ui](https://github.com/DUNE-DAQ/runconf-ui), the shifter interface: `tests/test_runconf_ui_contract.py` replays its calls, so keep it passing (or update runconf-ui together) when changing `ConfPool`. 
The progress of `propagate_base` can be followed with its `listener` argument (see `GenerationListener`), and after a failed `generate_conf` the reason is in `last_failure`. 
The generators, verifiers and common functions are always imported from the working tree of the pool calling them, so several pools and bases can be used in the same process.

## Development
The tests use local git repositories only, and can be run with
```bash
pip install ".[dev]"
pytest
```
Linting is done with `ruff check`.
