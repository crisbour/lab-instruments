# Lab Instruments Wrappers + APIs

This projects bundles together in a python package all APIs necessary to interface with the custom instrumentation that we have available in the lab:
- Prima PicoQuant laser controller
    - gRPC client API, interfaces remotely with the server controlling
  the laser through USB
    - Uses callibration data to set the power/flux to the desired value based on
      the measurements available in 3D_VISION/ms_lidar/experiments/characterisation/laser/prima_picoquant
- Power meter Thorlabs PM400 wrapper for the SCPI commands to set wavelenghts
and read power/flux
- QuantiCam calls to the [QuantiCam.jl](https://git.ecdf.ed.ac.uk/lidar-research/instruments/quanticam.jl) julia project
- Stanford Delay Generator DG645 wrapper to the SCPI commands
