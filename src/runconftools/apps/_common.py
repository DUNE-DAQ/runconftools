"""
Helpers shared by the cpm-* scripts.

Each apparatus has its local repository in PATH/<apparatus>, as the configuration branches of
different apparatuses have the same names. With -a all, the base is inspected in PATH/_base.
"""

import logging
import re
from collections.abc import Iterable
from pathlib import Path

import click
import git

from runconftools.ConfPool import ConfPool, git_error, repository_key
from runconftools.report import ItemProgress, OutputCapture, Report, Stop

ALL_APPARATUSES = "all"
BASE_POOL_DIR = "_base"

_NAME_REGEX = re.compile(r"^[A-Za-z0-9_]+$")


def split_values(values: Iterable[str]) -> list[str]:
    """Split comma separated option values, dropping empty values and duplicates."""
    items = (v.strip() for value in values for v in value.split(","))
    return list(dict.fromkeys(v for v in items if v))


def parse_apparatuses(ctx: click.Context, param: click.Parameter, values: tuple[str, ...]) -> list[str] | None:
    """Click callback of -a: the list of apparatuses, or None for all."""
    names = split_values(values)
    if not names:
        raise click.BadParameter("at least one apparatus is needed", ctx=ctx, param=param)

    if ALL_APPARATUSES in names:
        if len(names) > 1:
            raise click.BadParameter(f"'{ALL_APPARATUSES}' cannot be combined with other apparatuses", ctx=ctx, param=param)
        return None

    invalid = [n for n in names if not _NAME_REGEX.match(n)]
    if invalid:
        raise click.BadParameter(f"invalid apparatus name(s): {', '.join(invalid)}", ctx=ctx, param=param)
    return names


def validate_release(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Click callback of -r: the release must be usable as prefix of the branch names."""
    if value is None:
        return value
    ## branches are <release>/<configuration> and the release is parsed as the first path component
    if "/" in value or value.startswith("-"):
        raise click.BadParameter(f"'{value}' cannot contain '/' nor start with '-'", ctx=ctx, param=param)
    status, _, _ = git.cmd.Git().check_ref_format(f"refs/heads/{value}/configuration",
                                                   with_extended_output=True, with_exceptions=False)
    if status != 0:
        raise click.BadParameter(f"'{value}' is not valid in a git branch name", ctx=ctx, param=param)
    return value


def apparatus_option(all_help: str):
    """The -a option. all_help says what 'all' means for the script."""
    return click.option(
        "-a", "--apparatus",
        type=click.STRING,
        multiple=True,
        default=("np02",),
        callback=parse_apparatuses,
        help="Apparatuses to act on, either repeating the option or as a comma separated list, "
             f"e.g. '-a np02,np04'. Use '{ALL_APPARATUSES}' for {all_help}. "
             "Each apparatus uses the local repo PATH/<apparatus>",
    )


def operation_url_option():
    """The --operation_url option."""
    return click.option(
        "--operation_url",
        type=click.STRING,
        multiple=True,
        default=(),
        help="URL of the operation repo as <apparatus>=<url>, repeated or comma separated. "
             "Apparatuses without an explicit URL use their default repo. "
             "A plain <url> is accepted when a single apparatus is selected",
    )


def parse_operation_urls(values: Iterable[str], apparatuses: list[str] | None) -> dict[str, str]:
    """
    Parse --operation_url into {apparatus: url}.

    A URL without apparatus is only accepted when a single apparatus is selected.
    """
    urls: dict[str, str] = {}
    plain = []
    for value in split_values(values):
        name, sep, url = value.partition("=")
        ## URLs like https://host/repo?a=b are not pairs since the part before '=' is not a name
        if sep and _NAME_REGEX.match(name):
            if name in urls and urls[name] != url:
                raise click.BadParameter(f"two URLs given for {name}", param_hint="'--operation_url'")
            urls[name] = url
        else:
            plain.append(value)

    if plain:
        if len(plain) > 1 or urls or apparatuses is None or len(apparatuses) != 1:
            raise click.BadParameter(
                "a URL without apparatus is only accepted when a single apparatus is selected, use <apparatus>=<url>",
                param_hint="'--operation_url'",
            )
        urls[apparatuses[0]] = plain[0]
    return urls


def check_repositories(base_url: str | None = None, operation_urls: dict[str, str] | None = None) -> None:
    """
    Check that the repositories can be reached, and that the operation ones have a default branch.

    All the problems are listed in one Stop, before anything is cloned.
    """
    operation_urls = operation_urls or {}
    to_check = ([("base", base_url)] if base_url else []) + [(f"{a} operation", u) for a, u in operation_urls.items()]
    problems = []
    for label, url in to_check:
        logging.debug("Checking the %s repository %s", label, url)
        status, out, err = git.cmd.Git().ls_remote("--symref", url, "HEAD", with_extended_output=True, with_exceptions=False)
        if status != 0:
            problems.append(f"the {label} repository {url} cannot be reached: {git_error(err, f'exit code {status}')}")
        elif label != "base" and not any(line.startswith("ref:") for line in out.splitlines()):
            problems.append(f"the {label} repository {url} has no default branch")

    if problems:
        raise Stop("\n".join(["Cannot use the repositories:", *problems]),
                   hint="Check the URLs and your access: ssh key for ssh URLs, netrc token for https URLs (see the README)")


def base_pool(path: str, base_url: str) -> ConfPool:
    """Base-only pool in PATH/_base, to inspect the base."""
    pool_path = Path(path) / BASE_POOL_DIR
    pool_path.mkdir(parents=True, exist_ok=True)
    return ConfPool(str(pool_path), apparatus=None, operation_url=None, base_url=base_url)


def select_apparatuses(
    path: str,
    base_url: str,
    base: str | None,
    apparatuses: list[str] | None,
    operation_values: Iterable[str],
    ssh: bool,
) -> dict[str, str]:
    """
    Return {apparatus: operation URL} for the selected apparatuses.

    With -a all, the apparatuses come from the base, or are the defaults if there is no base.
    """
    explicit = apparatuses is not None
    if apparatuses is None:
        if base:
            try:
                apparatuses = base_pool(path, base_url).get_apparatuses(base)
            except ValueError as e:
                raise click.UsageError(str(e)) from None
        else:
            apparatuses = ConfPool.default_apparatuses()
        if not apparatuses:
            raise click.UsageError(f"No apparatus found in base {base}")
        logging.debug("Selected apparatuses: %s", ", ".join(apparatuses))

    ## a plain URL is only unambiguous if the user explicitly asked for a single apparatus
    urls = parse_operation_urls(operation_values, apparatuses if explicit else None)
    try:
        operation_urls = ConfPool.set_apparatuses(apparatuses, urls, ssh=ssh)
    except ValueError as e:
        raise click.UsageError(str(e)) from None

    for apparatus, url in operation_urls.items():
        if repository_key(url) == repository_key(base_url):
            raise click.UsageError(f"The base repository {base_url} cannot be the operation repository of {apparatus}")

    for apparatus, url in operation_urls.items():
        logging.debug("Operation repository of %s: %s", apparatus, url)
    return operation_urls


def open_pools(path: str, operation_urls: dict[str, str], base_url: str) -> dict[str, ConfPool]:
    """
    Open one pool per apparatus in PATH/<apparatus>.

    Local repos with uncommitted changes stop the run, as the changes could end up in the configurations.
    """
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True)
    try:
        git.Repo(root)
        logging.warning("%s is a git repo: local repos are now created in %s/<apparatus>", root, root)
    except git.InvalidGitRepositoryError:
        pass

    dirty = []
    for apparatus in operation_urls:
        try:
            if git.Repo(root / apparatus).is_dirty(untracked_files=True):
                dirty.append(str(root / apparatus))
        except (git.InvalidGitRepositoryError, git.NoSuchPathError):
            pass
    if dirty:
        raise Stop("These local repos have uncommitted changes: " + ", ".join(dirty),
                   hint="Inspect them with 'git status', then commit or discard the changes, or use a new PATH")

    pools = {}
    for apparatus, url in operation_urls.items():
        pool_path = root / apparatus
        pool_path.mkdir(exist_ok=True)
        pools[apparatus] = ConfPool(str(pool_path), apparatus=apparatus, operation_url=url, base_url=base_url)
    return pools


def check_apparatuses(pools: dict[str, ConfPool], base: str) -> None:
    """
    Stop the run if the base does not exist or does not have one of the apparatuses.

    Otherwise clean would remove all the configurations of an apparatus missing in the base.
    """
    for apparatus, pool in pools.items():
        try:
            available = pool.get_apparatuses(base)
        except ValueError as e:
            raise click.UsageError(str(e)) from None
        if apparatus not in available:
            raise click.UsageError(
                f"Apparatus {apparatus} is not in base {base}, available apparatuses: {', '.join(available)}"
            )


class GenerationReporter:
    """Shows the generators run by propagate_base for one apparatus."""

    def __init__(self, report: Report, progress: ItemProgress, apparatus: str,
                 capture: OutputCapture | None = None, logs: Path | None = None) -> None:
        """With capture, the output of each generator goes to <logs>/<generator>.log."""
        self.report = report
        self.progress = progress
        self.apparatus = apparatus
        self.capture = capture
        self.logs = logs
        self.succeeded: list[str] = []
        self.failed: list[str] = []

    def _log(self, generator: str) -> Path | None:
        return self.logs / f"{generator}.log" if self.capture and self.logs else None

    def started(self, generator: str) -> None:
        self.progress.start(f"{self.apparatus} · {generator}")
        log = self._log(generator)
        if log is not None:
            self.capture.start(log)

    def finished(self, generator: str, success: bool, reason: str | None) -> None:
        if self.capture:
            self.capture.stop()
        self.progress.finish(f"{self.apparatus} · {generator}", success, reason)
        if success:
            self.succeeded.append(generator)
        else:
            self.failed.append(generator)
            self.report.add_failure(self.apparatus, generator, reason or "failed", log=self._log(generator))
