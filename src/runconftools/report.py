"""
Reporting for the ``cpm-*`` scripts: numbered steps, progress, collected problems and a final summary.

On a terminal the output uses colours, a live progress bar and the rich log format.
Otherwise, e.g. when the output is redirected to a file, it is plain text with one timestamped
line per log record, so that it can be read and searched with the usual tools.
"""

import ctypes
import logging
import os
import re
import sys
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import click
from rich import box
from rich.console import Console, Group
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

## how many warnings are listed in the summary, the others are only counted
MAX_WARNINGS = 10
## how many lines of the output of a failed item are shown in the summary
TAIL_LINES = 10

try:
    _LIBC = ctypes.CDLL(None)
except OSError:
    _LIBC = None


def flush_stdout() -> None:
    """
    Write out what the generators printed so far, before the report prints anything.

    The report goes to stderr, which is written immediately, while stdout is buffered when it is not
    a terminal, e.g. in a log file: without this, the output of the generators would end up after the
    lines reporting their result, and its last part even after the summary. Both the python buffer and
    the C ones (used by the C++ libraries) are flushed.
    """
    try:
        sys.stdout.flush()
    except (AttributeError, OSError, ValueError):
        pass
    if _LIBC is not None:
        try:
            _LIBC.fflush(None)
        except (AttributeError, OSError):
            pass


class _OrderedStreamHandler(logging.StreamHandler):
    """Stream handler flushing stdout before each record, see ``flush_stdout``."""

    def emit(self, record: logging.LogRecord) -> None:
        flush_stdout()
        super().emit(record)


class OutputCapture:
    """
    Send what is printed to stdout to a file, e.g. the output of a generator in quiet mode.

    Both ``sys.stdout`` and the stdout file descriptor are redirected, so that the output of the
    C++ libraries is captured too. The report itself prints to stderr and is not affected.
    """

    def __init__(self) -> None:
        self._file = None
        self._saved_stdout = None
        self._saved_fd: int | None = None
        self._fd: int | None = None

    def start(self, path: Path) -> None:
        """Start sending stdout to ``path``, which is overwritten."""
        self.stop()
        flush_stdout()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "w", buffering=1)
        try:
            self._fd = sys.__stdout__.fileno()
            self._saved_fd = os.dup(self._fd)
            os.dup2(self._file.fileno(), self._fd)
        except (AttributeError, OSError, ValueError):
            ## no real stdout, e.g. in some test runners: only the python output is captured
            self._fd = self._saved_fd = None
        self._saved_stdout = sys.stdout
        sys.stdout = self._file

    def stop(self) -> None:
        """Restore stdout, if it is captured."""
        if self._file is None:
            return
        flush_stdout()
        sys.stdout = self._saved_stdout
        if self._saved_fd is not None:
            os.dup2(self._saved_fd, self._fd)
            os.close(self._saved_fd)
        self._file.close()
        self._file = None
        self._saved_fd = self._fd = None


@dataclass
class Failure:
    """An item, e.g. a configuration, that failed."""

    apparatus: str
    item: str
    reason: str
    ## file with the output of the item and its last lines, in quiet mode
    log: Path | None = None
    tail: list[str] = field(default_factory=list)


class Stop(Exception):
    """Stop the run: the message is reported as the error that stopped it."""

    def __init__(self, message: str, hint: str | None = None, exit_code: int = 1) -> None:
        """
        Args:
            message: what went wrong.
            hint: what the user can do about it.
            exit_code: exit code of the script.
        """
        super().__init__(message)
        self.hint = hint
        self.exit_code = exit_code


@dataclass
class Problem:
    """A warning or an error, with where it happened."""

    level: int
    message: str
    where: str
    step: int
    apparatus: str | None


class _Collector(logging.Handler):
    """Logging handler storing the warnings and errors in the report."""

    def __init__(self, report: "Report") -> None:
        super().__init__(logging.WARNING)
        self.report = report

    def emit(self, record: logging.LogRecord) -> None:
        self.report._record(record.levelno, record.getMessage())


class ItemProgress:
    """Progress of a sequence of items, e.g. the generators, see ``Report.progress``."""

    def __init__(self, report: "Report", progress: Progress, task: int, total: int) -> None:
        self.report = report
        self.progress = progress
        self.task = task
        self.total = total
        self.done = 0

    def start(self, label: str) -> None:
        """Announce that the item ``label`` is being processed."""
        flush_stdout()
        self.progress.update(self.task, description=label)
        if not self.report.console.is_terminal:
            self.report.console.print(Text(f"  … {self._counter(self.done + 1)} {label}"), soft_wrap=True)

    def finish(self, label: str, success: bool, reason: str | None = None) -> None:
        """Record the result of the item ``label``."""
        flush_stdout()
        self.done += 1
        self.progress.advance(self.task)
        line = Text("  ")
        line.append("✔ " if success else "✘ ", style="bold green" if success else "bold red")
        line.append(self._counter(self.done), style="dim")
        line.append(f" {label}", style="" if success else "red")
        if reason:
            line.append(f" — {reason}", style="red")
        self.report.console.print(line, soft_wrap=True)

    def _counter(self, n: int) -> str:
        percentage = 100 * n / self.total if self.total else 100
        width = len(str(self.total))
        return f"[{n:>{width}}/{self.total} {percentage:3.0f}%]"


class Report:
    """
    Context manager reporting a run of a script.

    It prints the header and the numbered steps, collects all the warnings and errors (including the
    ones logged by the library), and always ends with a summary: a table of the results per apparatus,
    the problems and a final verdict. The exceptions stopping the run (``Stop`` and click errors) are
    reported in the summary and turned into the exit code of the script.

    Example::

        with Report("cpm-update", ["Checking", "Generating"], context={"Base": base}) as report:
            report.step("Checking")
            ...
            raise Stop("something is wrong", hint="fix it")
    """

    def __init__(self, title: str, steps: list[str], context: dict[str, str] | None = None, debug: bool = False,
                 quiet: bool = False) -> None:
        """
        Args:
            title: name of the script.
            steps: names of all the steps that will be executed, in order.
            context: parameters of the run shown in the header, e.g. the base and the release.
            debug: whether the debug messages are printed.
            quiet: if True only the errors are logged while running, the warnings are only in the summary.
        """
        self.title = title
        self.steps = steps
        self.context = context or {}
        self.debug = debug
        self.quiet = quiet
        self.console = Console(stderr=True, highlight=False)

        self.current_step = 0
        self.current_apparatus: str | None = None
        self.problems: list[Problem] = []

        ## summary table: one row per apparatus, in the order of the columns
        self.columns: list[str] = []
        self.rows: dict[str, dict[str, str]] = {}
        ## items, e.g. configurations, that failed
        self.failures: list[Failure] = []
        ## steps in which the failures were recorded: their errors are already explained by the failures
        self._failure_steps: set[int] = set()
        ## warnings collapsed in the summary: (regex with an 'item' group, title)
        self._warning_groups: list[tuple[re.Pattern, str]] = []
        ## extra lines of the final verdict, e.g. what was not done
        self.notes: list[str] = []
        self.success_message = "All done"

        self._handlers: list[logging.Handler] = []
        self._level = logging.NOTSET
        self._start = 0.0

    # ------------------------------------------------------------------ context manager

    def __enter__(self) -> "Report":
        self._start = time.monotonic()
        root = logging.getLogger()
        self._level = root.level
        root.setLevel(logging.DEBUG if self.debug else logging.INFO)

        if self.console.is_terminal:
            output: logging.Handler = RichHandler(console=self.console, show_path=False, markup=False,
                                                  rich_tracebacks=True, log_time_format="%H:%M:%S")
        else:
            output = _OrderedStreamHandler(sys.stderr)
            output.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        if self.quiet and not self.debug:
            output.setLevel(logging.ERROR)
        self._handlers = [output, _Collector(self)]
        for handler in self._handlers:
            root.addHandler(handler)

        self._header()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        exit_code = 0
        hint = None
        flush_stdout()
        try:
            if exc_type is None:
                pass
            elif issubclass(exc_type, Stop):
                exit_code, hint = exc.exit_code, exc.hint
                self._record(logging.ERROR, str(exc))
            elif issubclass(exc_type, click.ClickException):
                exit_code = exc.exit_code
                self._record(logging.ERROR, exc.format_message())
                if isinstance(exc, click.UsageError):
                    hint = f"Run {self.title} --help to see the options"
            elif issubclass(exc_type, KeyboardInterrupt):
                exit_code = 130
                self._record(logging.ERROR, "Interrupted by the user")
            elif issubclass(exc_type, SystemExit):
                exit_code = exc.code if isinstance(exc.code, int) else 1
                if exit_code:
                    self._record(logging.ERROR, f"Exited with code {exit_code}")
            else:
                exit_code = 1
                if self.console.is_terminal:
                    self.console.print_exception()
                else:
                    traceback.print_exception(exc_type, exc, tb, file=sys.stderr)
                self._record(logging.ERROR, f"Unexpected {exc_type.__name__}: {exc}")
            self._summary(exit_code, hint)
        finally:
            root = logging.getLogger()
            for handler in self._handlers:
                root.removeHandler(handler)
            root.setLevel(self._level)

        if exit_code:
            raise SystemExit(exit_code) from None
        return False

    # ------------------------------------------------------------------ progress of the run

    @property
    def where(self) -> str:
        """Description of the current step and apparatus."""
        if not self.current_step:
            where = "start-up"
        else:
            where = f"step {self.current_step}/{len(self.steps)} {self.steps[self.current_step - 1]}"
        if self.current_apparatus:
            where += f", {self.current_apparatus}"
        return where

    def step(self, name: str) -> None:
        """Start the step ``name``, which must be one of the steps given at construction."""
        self.current_step = self.steps.index(name) + 1
        self.current_apparatus = None
        flush_stdout()
        self.console.print()
        self.console.print(Rule(Text(f" Step {self.current_step}/{len(self.steps)} · {name} ", style="bold cyan"),
                                style="cyan", align="left"))

    @contextmanager
    def apparatus(self, name: str) -> Iterator[None]:
        """Context in which the messages concern the apparatus ``name``."""
        self.current_apparatus = name
        self.console.print(Text(f"▸ {name}", style="bold"))
        try:
            yield
        finally:
            self.current_apparatus = None

    @contextmanager
    def progress(self, total: int) -> Iterator[ItemProgress]:
        """
        Show the progress of ``total`` items, with a live bar on a terminal.

        Each finished item is also printed with its counter and percentage, so they are in the log too.
        """
        columns = [SpinnerColumn(), TextColumn("{task.description}"), BarColumn(),
                   TextColumn("{task.percentage:>3.0f}%"), TextColumn("{task.completed}/{task.total}"),
                   TimeElapsedColumn()]
        with Progress(*columns, console=self.console, disable=not self.console.is_terminal) as progress:
            task = progress.add_task("", total=total)
            yield ItemProgress(self, progress, task, total)

    # ------------------------------------------------------------------ messages

    def info(self, message: str) -> None:
        """Print an informative line."""
        flush_stdout()
        self.console.print(Text(f"  {message}"), soft_wrap=True)

    def ok(self, message: str) -> None:
        """Print a line about something that succeeded."""
        self._line("✔", message, "green")

    def warn(self, message: str) -> None:
        """Print a warning, which is also listed in the summary."""
        self._line("⚠", message, "yellow")
        self._record(logging.WARNING, message)

    def error(self, message: str) -> None:
        """Print an error, which is also listed in the summary."""
        self._line("✘", message, "red")
        self._record(logging.ERROR, message)

    def table(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        """Print a table."""
        flush_stdout()
        table = Table(title=title, title_justify="left", title_style="bold", box=box.ROUNDED, header_style="bold")
        for column in columns:
            table.add_column(column, overflow="fold")
        for row in rows:
            table.add_row(*row)
        self.console.print(table)

    def add_failure(self, apparatus: str, item: str, reason: str, log: Path | None = None) -> None:
        """
        Record that ``item`` (e.g. a configuration) of ``apparatus`` failed, for the summary.

        The errors logged in the same step for an apparatus are then not repeated in the summary.

        Args:
            apparatus: apparatus of the item.
            item: what failed.
            reason: why it failed.
            log: file with the output of the item, whose last lines are shown in the summary.
        """
        tail = []
        if log is not None:
            try:
                lines = [line.rstrip() for line in log.read_text(errors="replace").splitlines() if line.strip()]
                tail = [line[:200] for line in lines[-TAIL_LINES:]]
            except OSError:
                pass
        self.failures.append(Failure(apparatus, item, reason, log, tail))
        self._failure_steps.add(self.current_step)

    def group_warnings(self, pattern: str, title: str) -> None:
        """
        Collapse the warnings matching ``pattern`` into a single line of the summary.

        Args:
            pattern: regex matching the whole warning, with a group named ``item`` listed in the line.
            title: title of the line, e.g. "Generators without validation".
        """
        self._warning_groups.append((re.compile(pattern), title))

    def set_result(self, apparatus: str, column: str, value: str) -> None:
        """Set a cell of the summary table, adding the row and the column if needed."""
        if column not in self.columns:
            self.columns.append(column)
        self.rows.setdefault(apparatus, {})[column] = value

    # ------------------------------------------------------------------ internals

    def _line(self, icon: str, message: str, style: str) -> None:
        flush_stdout()
        line = Text("  ")
        line.append(f"{icon} ", style=f"bold {style}")
        line.append(message, style=style if style != "green" else "")
        self.console.print(line, soft_wrap=True)

    def _record(self, level: int, message: str) -> None:
        self.problems.append(Problem(level, message, self.where, self.current_step, self.current_apparatus))

    def _header(self) -> None:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold")
        grid.add_column()
        for key, value in self.context.items():
            grid.add_row(key, Text(str(value)))
        steps = " → ".join(self.steps)
        grid.add_row("Steps", Text(steps))
        self.console.print(Panel(grid, title=Text(self.title, style="bold"), title_align="left",
                                 border_style="cyan", expand=False))

    def _summary(self, exit_code: int, hint: str | None) -> None:
        flush_stdout()
        console = self.console
        console.print()
        console.print(Rule(Text(" Summary ", style="bold"), style="bold"))

        if self.rows:
            ## columns declared in advance but never filled, e.g. Pushed when not pushing, are hidden
            columns = [c for c in self.columns if any(c in values for values in self.rows.values())]
            table = Table(box=box.ROUNDED, header_style="bold")
            table.add_column("Apparatus", style="bold")
            for column in columns:
                table.add_column(column, justify="center")
            for apparatus, values in self.rows.items():
                cells = []
                for column in columns:
                    value = values.get(column, "-")
                    style = {"✔": "green", "✘": "red", "⚠": "yellow"}.get(value[:1], "")
                    cells.append(Text(value, style=style))
                table.add_row(apparatus, *cells)
            console.print(table)

        if self.failures:
            console.print(Text("Failed configurations", style="bold red"))
            for failure in self.failures:
                line = Text("  ✘ ", style="bold red")
                line.append(f"{failure.apparatus}/{failure.item}", style="red")
                line.append(f" — {failure.reason}")
                console.print(line, soft_wrap=True)
                if failure.log is not None:
                    console.print(Text(f"    output: {failure.log}", style="dim"), soft_wrap=True)
                for tail_line in failure.tail:
                    console.print(Text(f"    │ {tail_line}", style="dim"), soft_wrap=True)

        errors = [p for p in self.problems if p.level >= logging.ERROR]
        ## the errors of a failed configuration are already summarised by its reason
        explained = [p for p in errors if p.step in self._failure_steps and p.apparatus]
        errors = [p for p in errors if p not in explained]
        if errors or explained:
            console.print(Text(f"Errors ({len(errors) + len(explained)})", style="bold red"))
            for p in errors:
                self._problem(p, "✘", "red")
            if explained:
                count = f"{len(explained)} error" + ("s" if len(explained) > 1 else "")
                console.print(Text(f"  {count} of the failed configurations, see the log above", style="dim"),
                              soft_wrap=True)

        warnings = [p for p in self.problems if logging.WARNING <= p.level < logging.ERROR]
        groups: dict[str, list[str]] = {}
        single = []
        for p in warnings:
            for pattern, title in self._warning_groups:
                match = pattern.fullmatch(p.message)
                if match:
                    item = match.group("item")
                    groups.setdefault(title, []).append(f"{p.apparatus}/{item}" if p.apparatus else item)
                    break
            else:
                single.append(p)
        if warnings:
            console.print(Text(f"Warnings ({len(warnings)})", style="bold yellow"))
            for title, items in groups.items():
                line = Text("  ⚠ ", style="bold yellow")
                line.append(f"{title} ({len(items)}): ")
                line.append(", ".join(items), style="dim")
                console.print(line, soft_wrap=True)
            for p in single[:MAX_WARNINGS]:
                self._problem(p, "⚠", "yellow")
            if len(single) > MAX_WARNINGS:
                console.print(Text(f"  … and {len(single) - MAX_WARNINGS} more, see the log above", style="dim"))

        elapsed = time.monotonic() - self._start
        duration = f"{int(elapsed // 60)}m {elapsed % 60:.0f}s" if elapsed >= 60 else f"{elapsed:.1f}s"
        if exit_code:
            stopped = f"Stopped during {self.where}" if self.current_step else "Stopped before starting"
            lines = [Text(stopped, style="bold")]
            lines += [Text(note) for note in self.notes]
            if hint:
                lines.append(Text(f"→ {hint}", style="bold"))
            title, style = "✘ FAILED", "red"
        else:
            lines = [Text(self.success_message, style="bold")]
            lines += [Text(note) for note in self.notes]
            if errors:
                title, style = "⚠ COMPLETED WITH ERRORS", "yellow"
            else:
                title, style = "✔ SUCCESS", "green"
        lines.append(Text(f"{self.title} finished in {duration}, exit code {exit_code}", style="dim"))
        console.print(Panel(Group(*lines), title=Text(f" {title} ", style=f"bold {style}"), title_align="left",
                            border_style=style, expand=False))

    def _problem(self, problem: Problem, icon: str, style: str) -> None:
        message = problem.message.replace("\n", "\n    ")
        line = Text(f"  {icon} ", style=f"bold {style}")
        line.append(message)
        line.append(f"  [{problem.where}]", style="dim")
        self.console.print(line, soft_wrap=True)
