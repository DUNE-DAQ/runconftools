# How to create a new generator

Creating a configuration is almost the same as creating a generator for that configuration. 
Once the generator is created the configuration is created by scripts. 

## Generator structure
Generators are stored in the base repo, as they are specific for the base that they have to work upon in order to create the necessary configuration. 
Specifically, they are stored in the folder `functions/generators` directory in the subdirectory specific for the apparatus relevant for the generator. 

Generators are python modules and are expected to be named with with `<configuration_name>.py`. 

Generators will have to contains a generate function with signature
```python
def generate( path:str ) -> bool :
```
Where the incoming path is mandatory and is expected to point to the location of the base repository on which the generator will act.
This will be handled by the configuration management scripts. 

The generate function must return `True` once the generation is successfully completed. 
Otherwise, it should return `False` or raise an exception. 

A generator should assume that the environmental variables necessary to operate on the OKS files in the base are correctly setup and should not try to set them. 

### Good practices

As the generator is a python script, one could do everything. 
Yet it is recommended that the configuration files are managed through the OKS, conffwk or daqconf python interfaces/scripts. 

It also recommended that we limit the change of the objects to just changing the references rather than the attributes of the objects. 
Although in some cases that might be unavoidable. 

## generator testing

Generators should be tested before committing and before starting updating the operation repository. 
In order to test the generator, it is recommended that that the generator contains the block
```python
if __name__ == '__main__':
    globals()["generate"](sys.argv[1])
```

So that the generator can be tested by simply executing
```bash
python my_generator.py /path/to/base 
```
Or something very similar in spirit. 

While developing, personal experience suggested that is quite useful to develop the generator initially saving the file outside the local base git repository. 
In this way the chages made to the base by executing the generator can simply be reverted with a 
```bash
(cd /path/to/base; git restore)
```
Once the development is done and the result of the generator is tested, ideally with a succesful run, the file can be added to the base git repository, committed, pushed to the remote base and the operation repository can be updated. 

## Validators

Similarly to the generate function, the same file can contain - but it's not mandatory - a 
```Python
def validate( path:str ) -> bool :
```
function. 
This is used to perform specific operations that validate the validity of that configuration. 
As the `generate` function, this is called by the configuration management scripts. 

The function must return `True` in case the configuration is found to be correct by the function, or `False` otherwise. 

## Example

```python
#!/usr/bin/env python3
import sys

import conffwk
import confmodel

import daqconf.enable as enable

def generate( path:str ) -> bool :
    entry = path+'/sessions/np02-session.data.xml'
    session="np02-session"

    # enable all the det streams for the daphne
    enable.enable(entry, False, ["np02-pds107-s00-sid50"], session)

    db = conffwk.Configuration("oksconflibs:"+entry)

    # change the daphne configuration
    daphne_app = db.get_dal("DaphneApplication", "daphne-app")
    daphne_conf = db.get_dal("DaphneConf", "full_mode_bias_off")
    daphne_app.configuration = daphne_conf
    db.update_dal(daphne_app)
    
    
    # change the descriptor of the queue rule in the flx readout app
    queue_rule = db.get_dal("QueueConnectionRule", "daphne-raw-data-rule")
    queue_descriptor = db.get_dal("QueueDescriptor", "daphne-fullstream-raw-input")
    queue_rule.descriptor=queue_descriptor
    db.update_dal(queue_rule)


    # change the link handler in the RU
    readout_app = db.get_dal("ReadoutApplication", "runp02srv030flx4")
    data_handler = db.get_dal("DataHandlerConf", "pds-handler-numa0-fullstream")
    readout_app.link_handler = data_handler
    db.update_dal(readout_app)

    # Change the felix controller
    flx_controller_app = db.get_dal("DaqApplication", "pds-felix")
    full_stream_controller_module = db.get_dal("FelixCardControllerModule", "np02-pds-controller-fullstream")
    flx_controller_app.modules=[full_stream_controller_module]
    db.update_dal(flx_controller_app)

    # change the protocol to full
    flx_senders = db.get_dals("FelixDataSender")
    for s in flx_senders :
        s.protocol = "full"
        db.update_dal(s)
    
    db.commit()
    
    return True

if __name__ == '__main__':
    globals()["generate"](sys.argv[1])

```

This is an example of a generator that uses both `daqconf` and `conffwk` scripts. 
As you can see, most of the time, it is just changing the reference between the objects. 
The only exception is the `FelixDataSender` class that it's part of the topology description of the connections. 
Therefore its objects are not duplicated. 
