#!/usr/bin/env python3

import git
from git import Repo
import os
import logging
import re
import sys
import importlib
import sh

class ConfPool :
    def __init__( self,
                  path,
                  apparatus:str='np02',
                  operation_url:str=None,
                  base_url:str=None ) -> None :
        self.conf_regex = re.compile("^operation/([^/]+)/(.*)$")
        self.cod_regex = re.compile("^base/(.*)$")
        self.apparatus=apparatus
        try :
            self.repo=Repo(path)
        except git.InvalidGitRepositoryError:
            logging.warning("The repo in %s is empty, cloning from remotes", path)
            self.repo=Repo.clone_from(url=base_url, to_path=path)
        finally:
            remotes = [r.name for r in self.repo.remotes]
            if 'base' not in remotes:
                self.repo.create_remote(name='base', url=base_url)
            if 'operation' not in remotes:
                self.repo.create_remote(name='operation', url=operation_url)
            self.base = self.repo.remote('base')
            self.operation = self.repo.remote('operation')
            logging.info("Repo in %s set with the following remotes:", path)
            for r in self.repo.remotes :
                logging.info("%s -> %s", r.name, r.url)
            sys.path.append(path+'/generators')

        
    def get_cods( self ) -> list[str] :
        self.base.fetch()
        branches = [r.name for r in self.base.refs]
        cods=[]
        for b in branches :
            match = self.cod_regex.match(b)
            if not match : continue
            cods.append(match.group(1))
        return cods

    def setup_conf_path(self) -> None :
        os.environ["DUNEDAQ_DB_DATA_ROOT"]=self.repo.working_dir
        os.environ["DUNEDAQ_DB_PATH"] = f"{self.repo.working_dir}:{os.environ.get('DUNEDAQ_DB_PATH', '')}"
        
    def checkout_cod( self,
                      cod) -> git.refs.head.Head :
        
        cods = self.get_cods()
        if cod not in cods :
            logging.error("%s not in the avilable CODs",cod)
            return None

        ref_name = cod
        local_name = ref_name+"/LOCAL"
        head = self.repo.create_head(local_name, self.base.refs[ref_name]).set_tracking_branch(self.base.refs[ref_name]).checkout()
        self.setup_conf_path()
        return head

    def get_generators(self,
                       cod:str) -> list[str] :
        regex = re.compile('(.*)\.py$')
        self.checkout_cod(cod)
        files=[]
        path=self.repo.working_dir+'/generators/'+self.apparatus
        if os.path.isdir(path) :
            for f in os.listdir(path) :
                if os.path.isfile(os.path.join(path,f)) :
                    match = regex.match(f)
                    if match :
                        files.append(match.group(1))
        return files
            
    
    def get_daq_versions( self ) -> list[str] :
        self.operation.fetch()
        branches = [r.name for r in self.operation.refs]
        versions = []
        for b in branches :
            match = self.conf_regex.match(b)
            if not match : continue
            v = match.group(1)
            if v not in versions:
                versions.append(v)
        return versions
                  
        
    def get_confs( self,
                   release:re.Pattern=re.compile(os.environ["SPACK_RELEASE"]),
                   regex:re.Pattern=re.compile(".*") ) -> list :
        self.operation.fetch()
        branches = [r.name for r in self.operation.refs]
        confs = []
        for b in branches :
            match = self.conf_regex.match(b)
            if match :
                r = match.group(1)
                c = match.group(2)
                if release :
                    if not release.match(r) :
                        continue
                if regex :
                    if not regex.match(c) :
                        continue
                if c not in confs :
                    confs.append(c)
        return confs

    def checkout_conf( self,
                       conf:str,
                       release:str=os.environ["SPACK_RELEASE"]) -> git.refs.head.Head :
        
        confs = self.get_confs(release=re.compile(release))
        if conf not in confs :
            logging.error("%s not in the configurations for %s",conf, release)
            return None

        ref_name = f"{release}/{conf}"
        head = self.repo.create_head(ref_name, self.operation.refs[ref_name]).set_tracking_branch(self.operation.refs[ref_name]).checkout()
        self.setup_conf_path()
        return head


    def generate_conf( self,
                       cod:str,
                       generator:str,
                       release_tag:str=None ) -> bool :

        if not release_tag:
            release_tag = cod

        confs = self.get_confs(release=re.compile(release_tag))

        ref_name = release_tag+'/'+generator

        # prepare the branch
        head = None
        if generator not in confs :
            logging.info(f"New configuration {generator} created from base {cod}")
        else :
            logging.warning(f"Configuration {generator} overrides existing operation branch")
            self.operation.push(f":{ref_name}")

        self.checkout_cod(cod)
        branches = [b.name for b in self.repo.branches]
        logging.debug(",".join(branches))
        if ref_name in branches :
            self.repo.delete_head(ref_name, force=True)
        head = self.repo.create_head(ref_name).checkout()

#            head = self.checkout_conf(generator, release=release_tag)
#            ## merge xtheirs
#            self.repo.git.merge("-Xtheirs", "base/"+cod)
#            logging.info(f"Merge from base {cod}")
#            self.repo.index.commit(f"Update from base {cod}")
#            logging.debug("Commit on branch")


        # run the generator
        ## link the module
        module_name = self.apparatus+'.'+generator
        module = importlib.import_module(module_name)

        ## get the function
        functor = getattr(module, 'generate')

        ## execute the function
        res = functor(self.repo.working_dir)

        # find changed files
        files = self.repo.git.diff(None, name_only=True)
        if not files :
            logging.info("No changes")
            # no new commit
        else:
            file_list = files.split('\n')
            logging.debug("Files that changed: "+", ".join(file_list))
            for f in file_list :
                self.repo.git.add(f)
            # commit
            self.repo.git.commit("-m", f"Execute {generator}")

        # push the branch
        self.operation.push(f"{ref_name}:{ref_name}")
        return res

        
    def propagate_cod( self,
                       cod:str,
                       release_tag=None,
                       conf_regex:re.Pattern=re.compile(".*") ):

        if not release_tag:
            release_tag = cod

        cod_head = self.checkout_cod(cod)
        if not cod_head :
            return
        
        generators = self.get_generators(cod)
        for g in generators :
            if conf_regex.match(g) :
                self.generate_conf(cod=cod, generator=g, release_tag=release_tag)
            
#    def tag( self,
#             base_ref,
#             key_regex ) -> list :

    
