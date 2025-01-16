#!/usr/bin/env python3

import git
from git import Repo
import os
import logging
import re

class ConfPool :
    def __init__( self,
                  path,
                  operation_url:str=None,
                  base_url:str=None ) -> None :
        self.conf_regex = re.compile("^operation/([^/]+)/(.*)$")
        self.cod_regex = re.compile("^base/(.*)$")
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
        
    def get_cods( self ) -> list[str] :
        self.base.fetch()
        branches = [r.name for r in self.base.refs]
        cods=[]
        for b in branches :
            match = self.cod_regex.match(b)
            if not match : continue
            cods.append(match.group(1))
        return cods
        
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
                       release:str=os.environ["SPACK_RELEASE"]) -> bool :
        
        confs = self.get_confs(release=re.compile(release))
        if conf not in confs :
            logging.error("{} not in the configurations for {}".format(conf, release))
            return False

        ref_name = release+'/'+conf
        self.repo.create_head(ref_name, self.operation.refs[ref_name]).set_tracking_branch(self.operation.refs[ref_name]).checkout()
        return True
    
    #    def propagate_cod( self,
#                       cod,
#                       release_tag,
#                       conf_regex:re.Pattern=re.compile(".*") ) -> list :

#    def tag( self,
#             base_ref,
#             key_regex ) -> list :

    
