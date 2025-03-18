import git
import logging
import os
import re
import sys
import importlib


class ConfPool:
    def __init__(
        self,
        path:str,
        apparatus: str = "np02",
        operation_url: str = None,
        base_url: str = None,
    ) -> None:
        self.conf_regex = re.compile("^operation/([^/]+)/(.*)$")
        self.base_regex = re.compile("^base/(.*)$")
        self.apparatus = apparatus
        try:
            self.repo = git.Repo(path)
        except git.InvalidGitRepositoryError:
            logging.warning("The repo in %s is empty, cloning from remotes", path)
            self.repo = git.Repo.clone_from(url=base_url, to_path=path)
        finally:
            remotes = [r.name for r in self.repo.remotes]
            if "base" not in remotes:
                self.repo.create_remote(name="base", url=base_url)
            if "operation" not in remotes:
                self.repo.create_remote(name="operation", url=operation_url)
            self.base = self.repo.remote("base")
            self.operation = self.repo.remote("operation")
            logging.info("Repo in %s set with the following remotes:", path)
            for r in self.repo.remotes:
                logging.info("%s -> %s", r.name, r.url)
            sys.path.append(path + "/functions")

        ## this protection is necessary in case local base branch exist, example develop which is created by default
        ## In principle this could be done on any branch that does not respect the branch structure
        ## But I prefer to have the error exposed and deal with the specifics in a case by case manner
        bases = self.get_base_branches()
        branches = [b.name for b in self.repo.branches]
        for b in bases:
            if b in branches:
                self.repo.refs[b].rename(f"{b}/____BASE____")

    @staticmethod
    def get_release(default:str = "develop") -> str :
        name = os.environ["SPACK_RELEASE"]
        regex = re.compile("^([^-]+-v[0-9]+\.[0-9]+\.[0-9]+[^-]*)-[^-]+-[0-9]+$")
        match = regex.match(name)
        if match :
            return match.group(1)
        else :
            return default
                
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

    def checkout_base(self, base: str) -> git.refs.head.Head:
        bases = self.get_base_branches()
        if base not in bases:
            logging.error("%s not in the avilable base branches", base)
            return None

        ## as all the local branches will be in the form <version>/<generator> we need a name for the
        ## base. This is the way we are going to store the base
        ref_name = base
        local_name = ref_name + "/____BASE____"
        head = (
            self.repo.create_head(local_name, self.base.refs[ref_name])
            .set_tracking_branch(self.base.refs[ref_name])
            .checkout()
        )
        self.base.pull(f"{ref_name}:{local_name}")
        self.setup_conf_path()
        return head

    def get_generators(self, base: str) -> list[str]:
        regex = re.compile("(.*)\.py$")
        self.checkout_base(base)
        files = []
        path = self.repo.working_dir + "/functions/generators/" + self.apparatus
        if os.path.isdir(path):
            for f in os.listdir(path):
                if os.path.isfile(os.path.join(path, f)):
                    match = regex.match(f)
                    if match:
                        files.append(match.group(1))
        return files

    def get_verifiers(self, base: str = None) -> list[str]:
        regex = re.compile("(.*)\.py$")
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
        self.operation.fetch()
        branches = [r.name for r in self.operation.refs]
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
        release: re.Pattern = None,
        regex: re.Pattern = re.compile(".*"),
    ) -> list:

        if not release :
            release = re.compile("^"+self.get_release()+"$")
            
        self.operation.fetch()
        branches = [r.name for r in self.operation.refs]
        confs = []
        for b in branches:
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
         self, conf: str, release: str = None,
    ) -> git.refs.head.Head:

        if not release :
            release =  self.get_release()
            
        confs = self.get_confs(release=re.compile(release))
        if conf not in confs:
            logging.error("%s not in the configurations for %s", conf, release)
            return None

        ref_name = f"{release}/{conf}"
        head = (
            self.repo.create_head(ref_name, self.operation.refs[ref_name])
            .set_tracking_branch(self.operation.refs[ref_name])
            .checkout()
        )
        self.operation.pull(f"{ref_name}")
        self.setup_conf_path()
        return head

    def generate_conf(
            self, base: str, generator: str,
            release_tag: str = None, log_message: str = None, no_push:bool = False
    ) -> bool:
        if not release_tag:
            release_tag = base

        confs = self.get_confs(release=re.compile(release_tag))

        ref_name = release_tag + "/" + generator

        # prepare the branch
        head = None
        if generator not in confs:
            logging.info(f"New configuration {generator} created from base {base}")
            self.checkout_base(base)
            branches = [b.name for b in self.repo.branches]
            logging.debug(",".join(branches))
            if ref_name in branches:
                self.repo.delete_head(ref_name, force=True)
            head = self.repo.create_head(ref_name).checkout()
        else:
            logging.warning(
                f"Configuration {generator} overrides existing operation branch"
            )
            head = self.checkout_conf(generator, release=release_tag)
            # whipe out the branch
            files = self.repo.index.remove(["."], r=True, working_tree=True)
            logging.debug("Removing " + ", ".join(files))
            self.repo.git.checkout(f"base/{base}", ".")
            logging.info(f"Restore from base {base}")

        # run the generator
        ## link the module
        module_name = "generators."+self.apparatus + "." + generator
        module = importlib.import_module(module_name)

        ## get the function
        genctor = getattr(module, "generate")

        ## execute the function
        res = genctor(self.repo.working_dir)

        ## we commmit even if the result is false because having the local result
        ## might be useful for debugging
        message = ""
        if log_message:
            message = f"Execute {generator} on {base}: {log_message}"
        else:
            message = f"Execute {generator} on {base}"
        self.commit(message)

        if not res:
            return res

        ## verfication
        logging.info("\n Verification")
        very = self.verify()
        if not very :
            logging.error(f"Verfication failed for {generator}")
            return 
        
        ## validate
        if hasattr(module, "validate"):
            valctor = getattr(module, "validate")
            res = valctor(self.repo.working_dir)
            if not res :
                logging.error(f"Validation failed for {generator}")
                return res
        else:
            logging.warning(f"{generator} has no validation")
        
        # push the branch
        if not no_push :
            self.operation.push(f"{ref_name}")
            
        return res

    def propagate_base(
        self, base: str, release_tag:str=None,
            conf_regex: re.Pattern = re.compile(".*"),
            no_push:bool = False
    ) -> bool :    ## we return True if it's ok to proceed with a push because all went well
        if not release_tag:
            release_tag = base

        base_head = self.checkout_base(base)
        if not base_head:
            return

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

    def push_configurations(self,
                            base:str,
                            release_tag:str = None,
                            conf_regex: re.Pattern = re.compile(".*") ) :

        if not release_tag:
            release_tag = base
            
        base_head = self.checkout_base(base)
        if not base_head:
            return

        generators = self.get_generators(base)
        local_branches = [b.name for b in self.repo.branches]
        for g in generators:
            if conf_regex.match(g):
                ref_name = f"{release_tag}/{g}"
                if ref_name in local_branches :
                    logging.info(f"Pushing {ref_name} to {self.apparatus} operations")
                    self.operation.push(f"{ref_name}")

    def verify(self) -> bool :
        verifiers = self.get_verifiers()
        if not verifiers :
            logging.warning("No verfiers are available")
        for v in verifiers:
            module_name = "verifiers."+v
            module = importlib.import_module(module_name)
            functor = getattr(module, "verify")
            res = functor(self.repo.working_dir)
            if not res :
                logging.error(f"{v} failed")
                return False

        logging.info("Verification successful!")
        return True
            
        
    def commit(self, message: str):
        # find the changes
        files = self.repo.git.diff(None, name_only=True)
        if not files:
            return

        file_list = files.split("\n")
        logging.debug("Files that changed: " + ", ".join(file_list))
        for f in file_list:
            self.repo.git.add(f)
        # commit
        self.repo.git.commit("-m", message)


    def remove_configurations(self,
                              release:str=None,
                              conf_regex: re.Pattern = re.compile(".*") ) -> list[str] :

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
            self.operation.push(f":{branch}")
            ret.append(branch)

        return ret

#    def tag( self,
#             base_ref,
#             key_regex ) -> list :
