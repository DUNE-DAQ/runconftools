cmake_minimum_required(VERSION 3.12)
project(config-management VERSION 0.0.0)

find_package(daq-cmake REQUIRED)

daq_setup_environment()

find_package(appmodel REQUIRED)
find_package(conffwk REQUIRED)
find_package(appfwk REQUIRED)
find_package(Boost COMPONENTS unit_test_framework REQUIRED)

##############################################################################


# See https://dune-daq-sw.readthedocs.io/en/latest/packages/daq-cmake/#daq_codegen
 # daq_protobuf_codegen( opmon/*.proto )

##############################################################################


# See https://dune-daq-sw.readthedocs.io/en/latest/packages/daq-cmake/#daq_add_library

 # daq_add_library( *.cpp LINK_LIBRARIES appfwk::appfwk fmt::fmt) # Any source files and/or dependent libraries to link in not yet determined
##############################################################################


# See https://dune-daq-sw.readthedocs.io/en/latest/packages/daq-cmake/#daq_add_plugin

 # daq_add_plugin(DaphneV2ControllerModule duneDAQModule LINK_LIBRARIES daphnemodules appmodel::appmodel)

##############################################################################


# See https://dune-daq-sw.readthedocs.io/en/latest/packages/daq-cmake/#daq_add_unit_test

 # daq_add_unit_test(DaphneInterface_test LINK_LIBRARIES daphnemodules) 

##############################################################################

daq_install()


