# Workflow for configuration creation and update

This is an example on how changes in the base repository can happen. 

### Area setup
```bash
dbt-create fddaq-v5.2.2-a9 MyArea
cd MyArea/
source env.sh 
dbt-workarea-env 
dbt-build
git clone ssh://git@gitlab.cern.ch:7999/dune-daq/online/config-management.git 
cd config-management
pip install .
cd ..
```

At this point, you have a working environment with the tools necessary to propagate the changes to the operation repo once we are happy with the result. 
The next step is to have a local configuration area to modify. 
The following starts from the configuration for the DAQ version `fddaq-v5.2.2-a9-1`. 
```bash
git clone ssh://git@gitlab.cern.ch:7999/dune-daq/online/ehn1-daqconfigs.git EHN1-configs 
cd EHN1-configs 
git checkout fddaq-v5.2.2 -b mroda/my_dev
```
At this point here you do the changes you need.
If you need to develop a generator, I suggest you write the generator outside the local git repo so you can test the generator on the base.
In case it's not ok, use a simple git restore to return the repository at its initial state. 
Once you are happy with the generator, you can move the file inside the repo and add it to git.

Whatever the changes you made, commit and push to a branch on the base repo.

```bash
git commit . -m "My dev"
git push origin mroda/my_dev
```

At this point you open the merge request toward the branche you started from, in this case `fddaq-v5.2.2`.
Before the merge things should be tested and reviewed, if possible. 
But the test depends on the type of changes. 
If you just added a generator but the OKS objects in the base are unchanged, then there is no need to test all the generators.
Assuming the new generator are tested by the developers, we can just merge.
If there are changes in the OKS objects, we need to test that the generators are still functioning correctly.
So before merging, I would test the generator doing the following:
```bash
cd ..   ##to go back to the previous level
mkdir TempTest ## to run the generator on a test area so local changes are not lost
cpm-update -b mroda/my_dev -r mroda-test --no-push TempTest 
```
Here you will see if the generators keep working correctly. 
You can even inspect all the generated branches. 

If you need to push the branches on operation so that they can be tested by a shifter, you can do that too. 
In this case simply push with:
```bash
cpm-update -b mroda/my_dev -r mroda-test --push-only TempTest
```
If the local area has ended its purpose, just remove it:
```bash
rm -rf TempTest
```
As all the changes are not pushed should it be necessary. 

If all the branches are ok on the operation side, then all is well and we can merge, if not, we need to fix the merge request.
Once the merge is done we just need to recreate the operation branches for the patch, but this time we push to 

```bash
mkdir Temp
cpm-update -b fddaq-v5.2.2 -r fddaq-v5.2.2 Temp 
## please note that the specification of base and release at this point might be the defaults 
## And it might not be necessary to specify them.
rm -rf Temp 
```

If test branches were creating on the operation remote repository, those should be deleted.

