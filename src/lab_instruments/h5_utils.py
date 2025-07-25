import h5py
from datetime import datetime
from logging import info, warning, debug, error
from .load_qc import jl

def mark_h5_user(h5_file: h5py.File):
    user = h5_file.create_group("User")
    user.attrs['NX_class'] = 'NXuser'
    user.create_dataset('name', data = 'Cristian Bourceanu')
    user.create_dataset('role', data = 'PhD Student')
    user.create_dataset('affiliation', data = "IMNS UoE, Dr. Istvan Gyongy's Group")
    user.create_dataset('email', data='v.c.bourceanu@sms.ed.ac.uk')

def mark_h5_start(h5_file: h5py.File):
    h5_file.attrs['HDF5_Version'] = h5py.version.hdf5_version
    h5_file.attrs['NeXus_version'] = 'Unknown'
    h5_file.attrs['file_time'] = str(datetime.now())

def create_nx_class(h5_group: h5py.Group, name: str, nx_class_id):
    nx_class = h5_group.create_group(name)
    nx_class.attrs['NX_class'] = nx_class_id
    return nx_class

def hdf5_describe_qc(h5_instrument: h5py.Group, qc) -> h5py.Group:
    qc_detector = h5_instrument.create_group("QuantiCam_192x128")
    qc_detector.attrs['NX_class'] = "NXdetector" # https://manual.nexusformat.org/classes/base_classes/NXsource.html#index-0
    qc_detector.create_dataset("name", data="QuantiCam SPAD array 192x128 sensor")
    qc_detector.create_dataset("type", data="SPAD array sensor")
    qc_detector.create_dataset("manufacturer", data="UoE")
    #qc_datasheet = qc_detector.create_group("specs")
    qc_detector.create_dataset("frame_size", data=(192,128))
    qc_stop_clk_spec = qc_detector.create_dataset("STOP_CLK", data=10e6)
    qc_stop_clk_spec.attrs['units'] = "Hz"

    qc_config_group = qc_detector.create_group("config")
    qc_config_group.attrs['NX_class'] = "NXparameters"

    timestamps = qc_detector.create_dataset("timestamps", data=())
    timestamps.attrs['units'] = "TDC code"

    bitfile_path = qc_detector.create_dataset("bitfile_path", data=qc.fpga.bitfile)
    bitfile_path.attrs['description'] = "FPGA bitfile path"
    bitfile_path.attrs['type'] = "filepath"

    info("Log QuantiCam configuration in the instrument, but WARN: this might change on the fly")
    qc_config_dict = jl.parse_json(jl.to_json(qc.config))
    for config_key in qc_config_dict:
        qc_config_group.create_dataset(config_key, data=qc_config_dict[config_key])

    return qc_detector
