# Workflow for configuration creation and update

This is an example on how changes in the base repository can happen. 

### Area setup
```bash
source /cvmfs/dunedaq.opensciencegrid.org/setup_dunedaq.sh
setup_dbt latest_v5
dbt-create fddaq-v5.2.2-a9 MyArea
cd MyArea/
source env.sh 
dbt-workarea-env 
dbt-build
git clone https://github.com/DUNE-DAQ/runconftools.git
cd runconftools
pip install .
cd ..
```

At this point, you have a working environment with the tools necessary to propagate the changes to the operation repo once we are happy with the result. 
The next step is to have a local base configuration area to modify. 
The following starts from the configuration for the DAQ version `fddaq-v5.2.2-a9-1`. 
```bash
git clone ssh://git@gitlab.cern.ch:7999/dune-daq/online/ehn1-daqconfigs.git EHN1-configs 
cd EHN1-configs 
git checkout fddaq-v5.2.2 -b mroda/my_dev
```
At this point you can make the changes you need.

### Some suggestions 
If you need to develop a generator, I suggest you write the generator outside the local git repo so you can test the generator on the base.
In case it's not ok, use a simple git restore to return the repository to its initial state. 
Once you are happy with the generator, you can move the file inside the repo and add it to git.

### Push review and testing 
Whatever the changes you made, commit and push to a branch on the base repo.

```bash
git commit . -m "My dev"
git push origin mroda/my_dev
```

At this point you open the merge request towards the branch you started from, in this case `fddaq-v5.2.2`.
Before the merge things should be tested and reviewed, if possible. 
But the test depends on the type of changes. 
If you just added a generator but the OKS objects in the base are unchanged, then there is no need to test all the generators.
Assuming the new generator is tested by the developers, we can just merge.
If there are changes in the OKS objects, we need to test that the generators are still functioning correctly.
As the OKS objects can be shared by several apparati, the generators of all of them should be tested.
So before merging, I would test the generators doing the following:
```bash
cd ..   ##to go back to the previous level
## run the generators on a test area so local changes are not lost, by default nothing is pushed
cpm-update -a all -b mroda/my_dev -r mroda-test TempTest
```
Here you will see if the generators keep working correctly. 
You can even inspect all the generated branches, in the local repository of each apparatus, e.g. `TempTest/np02`. 
If only some apparati are affected by the change, they can be listed instead of `all`, e.g. `-a np02,np02_emu`.

If you need to push the branches on operation so that they can be tested by a shifter, you can do that too. 
In this case simply push with:
```bash
cpm-update -a all -b mroda/my_dev -r mroda-test --push-only TempTest
```
using the same apparati as for the generation. 
Only push if the generation was successful, as `--push-only` does not check it.
If the local area has served its purpose, just remove it:
```bash
rm -rf TempTest
```
All the changes are safe on remote repositories. 

If all the branches are ok on the operation side, then all is well and we can merge, if not, we need to fix the merge request.

### Regeneration of the operation branches
Once the merge is done we just need to recreate the operation branches for the patch, but this time we push to branches with the right version. 

Most likely this is an operation done by run coordinators. 

```bash
cpm-update -a all -b fddaq-v5.2.2 -r fddaq-v5.2.2 -p Temp
## please note that the specification of base and release at this point might be the defaults 
## And it might not be necessary to specify them.
rm -rf Temp 
```
With `-p`, nothing is pushed unless the generation succeeded for all the apparati. 

If test branches were created on the operation remote repositories, those should be deleted:
```bash
cpm-purge -a all -r mroda-test Temp
rm -rf Temp
```

