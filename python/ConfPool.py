#!/usr/bin/env python3

import git
from git import Repo
import logging

class ConfPool :
    def __init__( self,
                  path,
                  operation_url:str=None,
                  base_url:str=None ) -> None :
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
        
#    def get_cods( self ) -> list :

#    def get_confs( self,
#                   regex ) -> list :

#    def propagate_cod( self,
#                       base_ref,
#                       key_regex ) -> list :

#    def tag( self,
#             base_ref,
#             key_regex ) -> list :

    
