import importlib
import logging
import os
import re
import sys
from collections.abc import Iterable, Mapping
from time import perf_counter
from types import ModuleType

import git

from runconftools.Apparatus import Apparatus


def repository_key(url: str) -> str:
    """
    Return a key identifying the repository of a git URL, independently of how the URL is written.

    For example the ssh and https URLs of the same gitlab project have the same key.

    Args:
        url: git URL, i.e. ``<scheme>://[user@]host[:port]/path``, ``[user@]host:path`` or a local path.

    Returns:
        ``<host>/<path>`` for remote URLs, the absolute path for local ones, without a trailing ``.git``.
    """
    u = url.strip().rstrip("/").removesuffix(".git")
    if u.lower().startswith("file://"):
        return os.path.abspath(u[len("file://"):])
    match = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://(?:[^@/]+@)?([^/:]+)(?::[0-9]*)?(/.*)?$", u)
    if match:
        return match.group(1).lower() + "/" + (match.group(2) or "").lstrip("/")
    match = re.match(r"^(?:[^@/]+@)?([^/:]+):(?!//)(.*)$", u)
    if match:
        return match.group(1).lower() + "/" + match.group(2).lstrip("/")
    return os.path.abspath(u)


class FetchTimedRemote(git.Remote):
    '''
    HW: Wrapper around remote, times fetch calls and skips if called again in a fetch_time second window [defaults to 30s]
    '''
    def __init__(self, *args, fetch_timeout: float = 30.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.fetch_timeout = fetch_timeout
        self._fetch_time: float | None = None

    def fetch(self, *args, **kwargs):
        current_fetch_time = perf_counter()
        if self._fetch_time is not None and current_fetch_time - self._fetch_time < self.fetch_timeout:
            logging.debug(f"Fetch called again within {self.fetch_timeout} seconds, skipping fetch")
            return

        self._fetch_time = current_fetch_time
        super().fetch(*args, **kwargs)


class FetchTimedRepo(git.Repo):
    def remote(self, name: str = "origin", fetch_timeout: float = 30.0)->"FetchTimedRemote":
        r = FetchTimedRemote(self, name, fetch_timeout=fetch_timeout)
        if not r.exists():
            raise ValueError(f"Remote named '{name}' didn't exist")
        return r


class ConfPool:
    """
    Local repository linking the base repository to the operation repository of one apparatus.

    The pool can also be base-only, i.e. without an operation repository. In that case only the
    methods that act on the base (e.g. ``get_base_branches``, ``checkout_base``, ``get_apparatuses``,
    ``get_generators``, ``get_verifiers``) can be used, the others raise a ``RuntimeError``.

    The modules of the base (generators, verifiers and common functions) are always imported from the
    ``functions`` directory of the pool's own working tree, see ``import_function``.
    """

    ## a local branch can be pushed only if it points to the commit recorded here, see is_verified
    VERIFIED_REFS = "refs/runconftools/verified/"

    def __init__(
        self,
        path:str,
        apparatus: str | None = "np02",
        operation_url: str | None = None,
        base_url: str | None = None,
        fetch_timeout: float = 30.0
    ) -> None:
        """
        Set up the local repository in ``path``, cloning the base if needed, and its remotes.

        Args:
            path: existing directory, either empty or containing a git repository.
            apparatus: apparatus whose generators are used, i.e. ``functions/generators/<apparatus>``.
                It can be None for a base-only pool.
            operation_url: URL of the operation repository. If None, the existing ``operation`` remote
                is used; if there is none, the pool is base-only.
            base_url: URL of the base repository. Required if ``path`` has to be cloned or if the local
                repository has no ``base`` remote.
            fetch_timeout: time window in seconds in which repeated fetches of a remote are skipped.

        Raises:
            ValueError: if the base repository cannot be set because ``base_url`` is missing.
            RuntimeError: if the default branch of the operation repository cannot be determined.
        """
        self.conf_regex = re.compile(r"^operation/([^/]+)/(.*)$")
        self.base_regex = re.compile(r"^base/(.*)$")
        self.apparatus = apparatus

        try:
            self.repo = FetchTimedRepo(path)
        except git.InvalidGitRepositoryError:
            if not base_url:
                raise ValueError(f"{path} is not a git repository and no base URL is given to clone it") from None
            logging.warning("The repo in %s is empty, cloning from remotes", path)
            self.repo = FetchTimedRepo.clone_from(url=base_url, to_path=path)

        if not self._set_remote("base", base_url):
            raise ValueError(f"The repo in {path} has no base remote and no base URL is given")
        self.base = self.repo.remote("base", fetch_timeout=fetch_timeout)

        self.operation: FetchTimedRemote | None = None
        self.default_regex: re.Pattern | None = None
        if self._set_remote("operation", operation_url):
            self.operation = self.repo.remote("operation", fetch_timeout=fetch_timeout)
        else:
            logging.info("No operation repository is defined, only the base can be used")

        logging.info("Repo in %s set with the following remotes:", path)
        for r in self.repo.remotes:
            logging.info("%s -> %s", r.name, r.url)
        sys.path.append(path + "/functions")

        ## in some places it is useful to know the default branch of the operation repository
        ## so it's set here
        if self.operation is not None:
            self._set_default_branch()

        ## this protection is necessary in case local base branch exist, example develop which is created by default
        ## In principle this could be done on any branch that does not respect the branch structure
        ## But I prefer to have the error exposed and deal with the specifics in a case by case manner
        bases = self.get_base_branches()
        branches = [b.name for b in self.repo.branches]
        for b in bases:
            if b in branches:
                self.repo.refs[b].rename(f"{b}/____BASE____")

    def _set_remote(self, name: str, url: str | None) -> bool:
        """
        Make sure that the remote ``name`` exists and, if ``url`` is given, that it points to ``url``.

        If the remote already exists with a different URL, the URL is updated and the remote-tracking
        branches that do not exist in the new remote are pruned, so that the old remote is never used.

        Args:
            name: name of the remote.
            url: URL of the remote. If None, an existing remote is left untouched.

        Returns:
            True if the remote exists after the call, False if it does not exist and no URL is given.
        """
        remotes = {r.name: r for r in self.repo.remotes}
        if name not in remotes:
            if not url:
                return False
            self.repo.create_remote(name=name, url=url)
            return True

        remote = remotes[name]
        if url and remote.url != url:
            logging.warning("Remote %s points to %s, changing it to %s", name, remote.url, url)
            remote.set_url(url)
            self.repo.git.fetch("--prune", name)
        return True

    def _set_default_branch(self) -> None:
        """
        Find the default branch of the operation repository and set the regex used to ignore it.

        Raises:
            RuntimeError: if the operation repository does not advertise a default branch.
        """
        operation = self._require_operation()
        output = self.repo.git.ls_remote("--symref", operation.url, "HEAD")
        default_branch = None
        for line in output.splitlines():
            if line.startswith("ref:"):
                default_branch = line.split("refs/heads/")[1].split("\t")[0]

        if default_branch is None:
            raise RuntimeError(f"Cannot determine the default branch of {operation.url}")

        logging.info(f"Branch {default_branch} will be ignored in operation")
        self.default_regex = re.compile(rf"^(?:[^/]+/)?{default_branch}$")  ## we only check that it ends with this name

    def _require_operation(self) -> FetchTimedRemote:
        """
        Return the operation remote, failing if the pool is base-only.

        Raises:
            RuntimeError: if no operation repository is defined.
        """
        if self.operation is None:
            raise RuntimeError("No operation repository is defined for this pool, an operation URL is needed")
        return self.operation

    def _require_apparatus(self) -> str:
        """
        Return the apparatus of the pool, failing if it is not set.

        Raises:
            RuntimeError: if no apparatus is defined.
        """
        if not self.apparatus:
            raise RuntimeError("No apparatus is defined for this pool")
        return self.apparatus

    @staticmethod
    def default_apparatuses() -> list[str]:
        """
        Return the apparatuses for which runconftools knows the operation repositories.

        Returns:
            The sorted list of default apparatus names.
        """
        return sorted(Apparatus.values())

    def get_apparatuses(self, base: str | None = None) -> list[str]:
        """
        Return the apparatuses supported by a base branch.

        The apparatuses are the subdirectories of ``functions/generators`` in the base branch.
        If no base is given, the defaults from ``default_apparatuses`` are returned.

        Args:
            base: base branch to inspect. Note that it gets checked out in the local repository.

        Returns:
            The sorted list of apparatus names.

        Raises:
            ValueError: if ``base`` is not among the available base branches.
        """
        if not base:
            return self.default_apparatuses()

        if self.checkout_base(base) is None:
            raise ValueError(f"{base} is not among the available base branches")

        path = os.path.join(self.repo.working_dir, "functions", "generators")
        if not os.path.isdir(path):
            logging.warning("Base %s has no generators", base)
            return []

        ## skip hidden and private directories, e.g. __pycache__, and names that cannot be imported
        return sorted(
            d for d in os.listdir(path)
            if d.isidentifier() and not d.startswith("_") and os.path.isdir(os.path.join(path, d))
        )

    @staticmethod
    def set_apparatuses(
        apparatuses: Iterable[str],
        operation_urls: Mapping[str, str] | None = None,
        ssh: bool = True,
    ) -> dict[str, str]:
        """
        Associate each apparatus with the URL of its operation repository.

        Explicit URLs take precedence, otherwise the default URL of the apparatus is used.

        Args:
            apparatuses: names of the apparatuses. Duplicates are ignored.
            operation_urls: explicit operation URLs, keyed by apparatus.
            ssh: if True the default URLs use ssh, otherwise https.

        Returns:
            Mapping from apparatus name to operation URL, following the order of ``apparatuses``.

        Raises:
            ValueError: if ``operation_urls`` contains an apparatus that is not selected, if an
                apparatus has neither an explicit nor a default URL, or if two apparatuses have the
                same operation repository.
        """
        selected = list(dict.fromkeys(apparatuses))
        operation_urls = dict(operation_urls or {})

        ## a typo in the explicit URLs would silently fall back to a default repository, so it's an error
        unknown = [a for a in operation_urls if a not in selected]
        if unknown:
            raise ValueError(f"Operation URLs given for apparatuses that are not selected: {', '.join(unknown)}")

        urls = {}
        for a in selected:
            if a in operation_urls:
                urls[a] = operation_urls[a]
                continue
            try:
                apparatus = Apparatus.from_string(a)
            except ValueError:
                raise ValueError(f"{a} has no default operation repository, its URL must be given") from None
            urls[a] = apparatus.ssh_url() if ssh else apparatus.https_url()

        ## pushing two apparatuses to the same repository would mix their configurations
        owners: dict[str, str] = {}
        for a, url in urls.items():
            key = repository_key(url)
            if key in owners:
                raise ValueError(f"{owners[key]} and {a} have the same operation repository {url}")
            owners[key] = a
        return urls

    @staticmethod
    def get_release(default:str = "develop") -> str :
        """
        Return the DAQ release of the environment, e.g. ``fddaq-v5.7.2`` for ``fddaq-v5.7.2-a9-1``.

        Args:
            default: value returned if ``SPACK_RELEASE`` is not set or is not a stable release (e.g. a nightly).

        Returns:
            The release name, or ``default``.
        """
        name = os.environ.get("SPACK_RELEASE")
        if not name:
            logging.debug(f"SPACK_RELEASE is not set, using {default} as release")
            return default
        regex = re.compile(r"^([^-]+-v[0-9]+\.[0-9]+\.[0-9]+[^-]*)-[^-]+-[0-9]+$")
        match = regex.match(name)
        if match :
            return match.group(1)
        return default

    @staticmethod
    def is_stable_release(name: str) -> bool:
        """
        Check if a release name is the one of a stable DAQ release, e.g. ``fddaq-v5.7.2``.

        Args:
            name: release name, e.g. the prefix of the operation branches.
        """
        return re.match(r"^[^-/]+-v[0-9]+\.[0-9]+\.[0-9]+[^-/]*$", name) is not None

    def get_base_branches(self) -> list[str]:
        self.base.fetch()
        branches = [r.name for r in self.base.refs]
        ret = []
        for b in branches:
            match = self.base_regex.match(b)
            if not match:
                continue
            ret.append(match.group(1))
        return ret

    def setup_conf_path(self) -> None:
        os.environ["DUNEDAQ_DB_DATA_ROOT"] = self.repo.working_dir
        os.environ["DUNEDAQ_DB_PATH"] = (
            f"{self.repo.working_dir}:{os.environ.get('DUNEDAQ_DB_PATH', '')}"
        )


    def __checkout(self, local_name:str, ref_name:str, remote) -> git.refs.head.Head:
        local_branches = [b.name for b in self.repo.branches]
        head = None
        if local_name not in local_branches :
            head = (
                self.repo.create_head(local_name, remote.refs[ref_name])
                .set_tracking_branch(remote.refs[ref_name])
                .checkout()
            )
        else :
            self.repo.git.checkout(local_name)
            head = self.repo.active_branch

        remote.pull(f"{ref_name}:{local_name}")
        self.setup_conf_path()
        return head
    
    def checkout_base(self, base: str) -> git.refs.head.Head:
        bases = self.get_base_branches()
        if base not in bases:
            logging.error("%s not in the avilable base branches", base)
            return None

        ## as all the local branches will be in the form <version>/<generator> we need a name for the
        ## base. This is the way we are going to store the base
        ref_name = base
        local_name = ref_name + "/____BASE____"
        return self.__checkout(local_name, ref_name, self.base)

    def get_generators(self, base: str) -> list[str]:
        regex = re.compile(r"^(?!__init__)(.*)\.py$")
        apparatus = self._require_apparatus()
        self.checkout_base(base)
        files = []
        path = self.repo.working_dir + "/functions/generators/" + apparatus
        if os.path.isdir(path):
            for f in os.listdir(path):
                if os.path.isfile(os.path.join(path, f)):
                    match = regex.match(f)
                    if match:
                        files.append(match.group(1))
        return files

    def get_verifiers(self, base: str | None = None) -> list[str]:
        regex = re.compile(r"^(?!__init__)(.*)\.py$")
        if base :
            self.checkout_base(base)
            ## otherwise just get the verifiers from the current branch

        files = []
        path = self.repo.working_dir + "/functions/verifiers"
        if os.path.isdir(path):
            for f in os.listdir(path):
                if os.path.isfile(os.path.join(path, f)):
                    match = regex.match(f)
                    if match:
                        files.append(match.group(1))
        return files

    def get_daq_versions(self) -> list[str]:
        operation = self._require_operation()
        operation.fetch()
        branches = [r.name for r in operation.refs]
        versions = []
        for b in branches:
            match = self.conf_regex.match(b)
            if not match:
                continue
            v = match.group(1)
            if v not in versions:
                versions.append(v)
        return versions

    def get_confs(
        self,
        release: re.Pattern | None = None,
        regex: re.Pattern = re.compile(r".*"),
    ) -> list:

        operation = self._require_operation()
        if not release :
            release = re.compile("^"+self.get_release()+"$")

        operation.fetch()
        branches = [r.name for r in operation.refs]
        confs = []
        for b in branches:
            ## we ignore the default because it's confusing
            if self.is_default_branch(b) :
                continue
            match = self.conf_regex.match(b)
            if match:
                r = match.group(1)
                c = match.group(2)
                if release:
                    if not release.match(r):
                        continue
                if regex:
                    if not regex.match(c):
                        continue
                if c not in confs:
                    confs.append(c)
        return confs

    def checkout_conf(
         self, conf: str, release: str | None = None,
    ) -> git.refs.head.Head:

        operation = self._require_operation()
        if not release :
            release = self.get_release()

        confs = self.get_confs(release=re.compile(release))
        if conf not in confs:
            logging.error("%s not in the configurations for %s", conf, release)
            return None

        ref_name = f"{release}/{conf}"
        return self.__checkout(ref_name, ref_name, operation)

    def is_default_branch(self, branch:str) -> bool :
        if self.default_regex is None:
            return False
        return bool(self.default_regex.match(branch))
        
    
    def remove_unused_sessions(self) -> list[str] :

        # file to be saved
        base_module_name = "common."+self._require_apparatus() + ".config_base"
        base_module = None
        try :
            base_module = self.import_function(base_module_name)
        except Exception:
            ## the configuraiton has no base, so it's not safe to delete anything
            return []

        to_be_removed = []
        function_name = "irrelevant_files"
        if hasattr(base_module, function_name):
            functor=getattr(base_module, function_name)
            to_be_removed=functor()
        else:
            ## again, too dangerous to remove things
            return []

        logging.debug("Removing " + ", ".join(to_be_removed))
        try :
            files = self.repo.index.remove(to_be_removed, working_tree=True)
            logging.debug("Removed " + ", ".join(files))
        except Exception :
            logging.warning("forcefully removing " + ", ".join(to_be_removed))
            for f in to_be_removed :
                self.repo.git.rm("-f", f)
            files = to_be_removed

        return files



    def import_function(self, module_name: str) -> ModuleType:
        """
        Import a module from the ``functions`` directory of the local repository, e.g. ``generators.np02.monitoring``.

        Python caches the imported modules, so after a checkout, or with several pools in the same process,
        a plain import could return the code of another branch or of another pool.
        Hence the modules previously imported from the ``functions`` directories are dropped from the cache
        and the ``functions`` directory of this pool is put first in ``sys.path``.

        Args:
            module_name: full name of the module, relative to the ``functions`` directory.

        Returns:
            The freshly imported module.
        """
        functions = os.path.join(self.repo.working_dir, "functions")
        if functions in sys.path:
            sys.path.remove(functions)
        sys.path.insert(0, functions)

        ## the packages provided by the functions directories, e.g. generators, verifiers, common
        packages = {"generators", "verifiers", "common", module_name.split(".")[0]}
        for name in list(sys.modules):
            if name.split(".")[0] in packages:
                del sys.modules[name]
        importlib.invalidate_caches()

        return importlib.import_module(module_name)

    def _set_verified(self, branch: str, verified: bool) -> None:
        """
        Record, or forget, that the current commit of a local branch comes from a successful generation.

        The record is the local ref ``refs/runconftools/verified/<branch>``, which is never pushed.

        Args:
            branch: name of the local branch.
            verified: if True the current commit of the branch is recorded, otherwise the record is removed.
        """
        ref = self.VERIFIED_REFS + branch
        if verified:
            self.repo.git.update_ref(ref, self.repo.heads[branch].commit.hexsha)
        else:
            self.repo.git.update_ref("-d", ref)

    def is_verified(self, branch: str) -> bool:
        """
        Check that a local branch is exactly the result of a successful generation.

        A generation is successful if the generator, the verifiers and the validator all succeeded.
        Any later change of the branch, e.g. a failed regeneration or a manual commit, makes it unverified.

        Args:
            branch: name of the local branch.

        Returns:
            True if the branch exists and points to the commit recorded by a successful generation.
        """
        if branch not in [h.name for h in self.repo.heads]:
            return False
        try:
            verified = self.repo.git.rev_parse("--verify", "--quiet", self.VERIFIED_REFS + branch)
        except git.GitCommandError:
            return False
        return verified == self.repo.heads[branch].commit.hexsha

    def generate_conf(
            self, base: str, generator: str,
            release_tag: str | None = None, log_message: str | None = None, no_push:bool = False
    ) -> bool:
        operation = self._require_operation()
        apparatus = self._require_apparatus()
        if not release_tag:
            release_tag = base

        confs = self.get_confs(release=re.compile(f"^{release_tag}$"))

        logging.debug("Available confs: " + ", ".join(confs))

        ref_name = release_tag + "/" + generator

        ## until this generation succeeds, the branch must not be pushed
        self._set_verified(ref_name, False)

        ## leftovers in the working tree would end up in this configuration
        if self.repo.is_dirty(untracked_files=True):
            raise RuntimeError(f"The repo in {self.repo.working_dir} has uncommitted changes, {generator} is not generated")

        # prepare the branch
        if generator not in confs:
            logging.info(f"New configuration {generator} created from base {base}")
            self.checkout_base(base)
            branches = [b.name for b in self.repo.branches]
            logging.debug(",".join(branches))
            if ref_name in branches:
                self.repo.delete_head(ref_name, force=True)
            self.repo.create_head(ref_name).checkout()
        else:
            logging.warning(
                f"Configuration {generator} overrides existing operation branch"
            )
            self.checkout_conf(generator, release=release_tag)
            # whipe out the branch
            files = self.repo.index.remove(["."], r=True, working_tree=True)
            logging.debug("Removing " + ", ".join(files))
            self.repo.git.checkout(f"base/{base}", ".")
            logging.info(f"Restore from base {base}")


        ## prepare the message for commit
        message = f"Execute {generator} on {base}"
        if log_message:
            message += f": {log_message}"

        try:
            res = self._run_generator(apparatus, generator, message)
        except Exception:
            ## keep the partial result for debugging and leave a clean working tree for the next generation
            try:
                self.commit(f"{message} [failed with an exception]")
            except Exception as e:
                logging.error(f"Failed to commit the partial result of {generator}: {e}")
            raise

        if not res:
            return res

        self._set_verified(ref_name, True)

        # push the branch
        if not no_push :
            operation.push(f"{ref_name}")

        return res

    def _run_generator(self, apparatus: str, generator: str, message: str) -> bool:
        """
        Run a generator, the verifiers and the validator on the checked out branch, committing the result.

        Args:
            apparatus: apparatus of the generator.
            generator: name of the generator.
            message: commit message.

        Returns:
            True if the generator, the verifiers and the validator all succeeded.
        """
        # run the generator
        ## link the module
        module_name = "generators."+apparatus + "." + generator
        module = self.import_function(module_name)

        ## get the function
        genctor = getattr(module, "generate")

        ## execute the function
        res = genctor(self.repo.working_dir)

        ## we commmit even if the result is false because having the local result
        ## might be useful for debugging
        if not res:
            self.commit(message)
            return res

        self.remove_unused_sessions()

        ## verfication which might produce files
        logging.info("---- Verification ----")
        very = self.verify()

        self.commit(message)

        ## stop the process if veryfication failed
        if not very :
            logging.error(f"Verfication failed for {generator}")
            return None

        ## validate
        if hasattr(module, "validate"):
            valctor = getattr(module, "validate")
            res = valctor(self.repo.working_dir)
            if not res :
                logging.error(f"Validation failed for {generator}")
                return res
        else:
            logging.warning(f"{generator} has no validation")

        return res

    def propagate_base(
        self, base: str, release_tag:str|None=None,
            conf_regex: re.Pattern = re.compile(r".*"),
            no_push:bool = False
    ) -> bool :    ## we return True if it's ok to proceed with a push because all went well
        self._require_operation()
        if not release_tag:
            release_tag = base

        base_head = self.checkout_base(base)
        if not base_head:
            return None

        ## find the log
        message = self.base.refs[base].commit.message

        generators = self.get_generators(base)
        ret = True
        for g in generators:
            if conf_regex.match(g):
                logging.info("\n")
                logging.info("---------------------------------------------")
                logging.info(f"Generating {g}")
                logging.info("---------------------------------------------")
                try :
                    result = self.generate_conf( base=base, generator=g, release_tag=release_tag,
                                                 log_message=message, no_push=no_push
                                                )
                    if not result :
                        ret = False
                except Exception as e:
                    logging.error(f"Exception raised when trying to generate {g}: {e}")
                    ret = False

        return ret

    def get_local_configurations(self,
                                 base:str,
                                 release_tag:str|None = None,
                                 conf_regex: re.Pattern = re.compile(r".*") ) -> list[str] | None :
        """
        Return the local branches of the generators of the base selected by ``conf_regex``.

        Args:
            base: base branch defining the generators.
            release_tag: release prefix of the branches, defaults to ``base``.
            conf_regex: regex selecting the generators, matched from the start of the name.

        Returns:
            The existing local branches, ``<release_tag>/<generator>``, or None if the base does not exist.
        """
        if not release_tag:
            release_tag = base

        if self.checkout_base(base) is None:
            return None

        local_branches = [b.name for b in self.repo.branches]
        return [
            f"{release_tag}/{g}" for g in self.get_generators(base)
            if conf_regex.match(g) and f"{release_tag}/{g}" in local_branches
        ]

    def get_unverified_configurations(self,
                                      base:str,
                                      release_tag:str|None = None,
                                      conf_regex: re.Pattern = re.compile(r".*") ) -> list[str] :
        """
        Return the local branches that ``push_configurations`` would push but that are not verified.

        See ``get_local_configurations`` for the arguments and ``is_verified`` for the definition of verified.
        """
        branches = self.get_local_configurations(base, release_tag, conf_regex) or []
        return [b for b in branches if not self.is_verified(b)]

    def check_push(self,
                   base:str,
                   release_tag:str|None = None,
                   conf_regex: re.Pattern = re.compile(r".*") ) -> list[str] :
        """
        Check, without pushing, that ``push_configurations`` would succeed.

        The branches must all be verified (see ``is_verified``) and must be accepted by the operation
        repository, which is checked with a dry-run push: this detects unreachable repositories, missing
        credentials and branches changed remotely in the meantime. Rules enforced by the server when
        receiving a push, e.g. protected branches, are not checked.

        See ``get_local_configurations`` for the arguments.

        Returns:
            The problems found, empty if the push can go ahead.
        """
        self._require_operation()
        branches = self.get_local_configurations(base, release_tag, conf_regex)
        if branches is None:
            return [f"{base} is not among the available base branches"]

        problems = [f"{b} does not come from a successful generation" for b in branches if not self.is_verified(b)]
        if problems or not branches:
            return problems

        status, out, err = self.repo.git.push("--dry-run", "--porcelain", "operation", *branches,
                                              with_extended_output=True, with_exceptions=False)
        if status != 0:
            rejected = [line.split("\t", 1)[1] for line in out.splitlines() if line.startswith("!")]
            problems = [f"push rejected: {r}" for r in rejected] or [f"push failed: {err.strip().splitlines()[-1] if err.strip() else status}"]
        return problems

    def push_configurations(self,
                            base:str,
                            release_tag:str|None = None,
                            conf_regex: re.Pattern = re.compile(r".*") ) -> bool :
        """
        Push the local branches of the generators of the base selected by ``conf_regex``.

        Nothing is pushed unless all those branches come from a successful generation (see ``is_verified``),
        so a failed or broken configuration never reaches the operation repository.

        See ``get_local_configurations`` for the arguments.

        Returns:
            True if all the branches were pushed, False if nothing was pushed because the base does not
            exist or some branches are not verified.
        """
        operation = self._require_operation()
        branches = self.get_local_configurations(base, release_tag, conf_regex)
        if branches is None:
            logging.error(f"{base} not in the available base branches, nothing is pushed")
            return False

        unverified = [b for b in branches if not self.is_verified(b)]
        if unverified:
            logging.error(f"Nothing is pushed to {self.apparatus} operations, "
                          f"these branches do not come from a successful generation: {', '.join(unverified)}")
            return False

        if not branches:
            logging.warning(f"No local configurations to push to {self.apparatus} operations")
        for b in branches:
            logging.info(f"Pushing {b} to {self.apparatus} operations")
            operation.push(b)
        return True

    def clean(self,
              base:str,
              release_tag:str|None = None) -> list[str] :

        operation = self._require_operation()
        if not release_tag:
            release_tag = base
            
        base_head = self.checkout_base(base)
        if not base_head:
            return []

        generators = self.get_generators(base)
        confs = self.get_confs(release=re.compile(f"^{release_tag}$"))

        logging.debug("Available confs: " + ", ".join(confs))
        logging.debug("Available generators: " + ", ".join(generators))

        ## without generators every configuration would look obsolete, which is surely a mistake
        if not generators:
            logging.error(f"Base {base} has no generators for {self.apparatus}, nothing is removed")
            return []

        ## while removing we have to be careful to not remove the default branch
        branches = []
        for c in confs :
            if c in generators :
                continue
            branch = f"{release_tag}/{c}"
            if self.is_default_branch(branch) :
                logging.debug(f"{branch} is not removed because it's the remote default")
                continue
            branches.append(branch)

        if branches:
            logging.warning(f"These {self.apparatus} configurations have no generator in base {base} "
                            f"and are removed: {', '.join(branches)}")

        ret = []
        for branch in branches :
            try :
                logging.info(f"Removing {branch} from {self.apparatus} operations")
                operation.push(f":{branch}")
                ret.append(branch)
            except Exception :
                logging.warning(f"Failed to remove {branch}")

        return ret

    def verify(self) -> bool :
        verifiers = self.get_verifiers()
        ## every base has verifiers, finding none means that something is wrong
        if not verifiers :
            logging.error("No verifiers are available, the configuration cannot be verified")
            return False
        for v in verifiers:
            module_name = "verifiers."+v
            module = self.import_function(module_name)
            functor = getattr(module, "verify")
            res = functor(self.repo.working_dir)
            if not res :
                logging.error(f"{v} failed")
                return False

        logging.info("Verification successful!")
        return True


    def commit(self, message: str) -> bool:
        """
        Stage all the changes (modified, deleted and new files) and commit them.

        The changes already in the index are committed too, e.g. the base restored by ``generate_conf``.

        Args:
            message: commit message.

        Returns:
            True if a commit was made, False if there was nothing to commit.
        """
        ## new files are added too, in case they are useful for backup
        for f in self.repo.untracked_files:
            logging.info(f"Adding new file: {f}")
        self.repo.git.add(A=True)

        ## compare the index with HEAD, so that changes staged before the call are not missed
        if not self.repo.is_dirty(index=True, working_tree=False, untracked_files=False):
            logging.debug("Nothing to commit")
            return False

        logging.debug("Files that changed: " + ", ".join(d.a_path for d in self.repo.index.diff("HEAD")))
        self.repo.git.commit("-m", message)
        return True


    def remove_configurations(self,
                              release:str|None=None,
                              conf_regex: re.Pattern = re.compile(r".*") ) -> list[str] :

        operation = self._require_operation()
        versions = self.get_daq_versions()

        if not release:
            logging.warning("No release specified, nothing is removed")
            return []

        if release not in versions :
            logging.warning(f"{release} not among the available versions")
            return []

        confs = self.get_confs(release=re.compile("^"+release+"$"),
                               regex=conf_regex)

        ret = []
        for c in confs :
            branch = f"{release}/{c}"
            if self.is_default_branch(branch) :
                logging.debug(f"{branch} is not removed because it's the remote default")
                continue
            try :
                operation.push(f":{branch}")
                ret.append(branch)
            except Exception :
                logging.warning(f"Failed to remove {branch}")

        return ret

#    def tag( self,
#             base_ref,
#             key_regex ) -> list :
