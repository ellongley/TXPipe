DESC 3x2pt Pipeline Stages
--------------------------

This is a collection of modules for the DESC 3x2pt pipeline.
We will build up the modules needed for the analysis as shown in the Pipelines repository.

It builds on the pipette repository for the infrastructure.

Goals
-----

- Test using parsl for some of our larger more complex analyses.
- Build and test a prototype pipeline infrastructure.
- Build and run prototype.
- Perform and publish a DC2 3x2pt analysis.


Installation
------------

Requires python3, numpy, scipy, pyyaml, fitsio, h5py (which in turn needs HDF5), and parsl.

Needs the pipette DESC library on the python path (which is not quite stable enough to be worth a setup.py yet).


Cori
----

These dependencies are all already prepared on cori - use this environment:

```bash
module swap PrgEnv-intel  PrgEnv-gnu
module unload darshan
module load hdf5-parallel/1.10.1
module load python/3.6-anaconda-4.4
module load cfitsio/3.370-reentrant
source activate /global/projecta/projectdirs/lsst/groups/WL/users/zuntz/env
```

Running the pipeline
--------------------

Make sure that the pipette directory is on your PYTHONPATH and pipette/bin is on your PATH.
Then you can run:

```bash
pipette test/test.yml
```
to run the implemented stages

Implementation
--------------

Each pipeline stage is implemented as a python class inheriting from pipette.Pipeline stage.  These subclasses should:

- have a "name" attribute string.
- have class attributes "inputs" and "outputs", each of which is a list of tuple pairs with a string tag and a FileType class.
- (optionally)  define a "config_options" dictionary of options it expects to find in its section of the main config file, with the value as a default for the option or "None" for no default.
- implement a "run" method doing the actual work of the class.

Some implementation notes:

- Our catalogs will be large. Wherever possible stages should operate on chunks of their input data at once. Pipette has some methods for this (see README)
- Pipeline stages shouldn't copy existing columns to new data.
- No ASCII output allowed!
- Python 3.6
- We will do code review
- One file per box (?)



Volunteers
----------

- Chihway C & Emily PL - TXTwoPointReal (WLPipe porting & testing)
- David A - TXSysMapMaker
- Anze S - SACC
- Tim E - TXCov
- Alex M - TXSourceSummarizer
- Antonino T & David A - TXTwoPointPower
