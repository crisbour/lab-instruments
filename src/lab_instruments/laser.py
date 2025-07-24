import h5py

import os
from pathlib import Path
from typing import Union
from enum import Enum
from logging import info, warning, debug
import numpy as np

import grpc
import sepia2_client_py.api_pb2 as api_pb2
import sepia2_client_py.api_pb2_grpc as api_pb2_grpc

from typing import Dict, Optional

from sklearn.neighbors import NearestNeighbors

class PrimaMode(Enum):
    Off         = "off"
    CW          = "cw"
    BroadPulse  = "broad_pulse"
    NarrowPulse = "narrow_pulse"

    def to_pb(self):
        if self == PrimaMode.Off:
            return api_pb2.OperationMode.Off
        elif self == PrimaMode.CW:
            return api_pb2.OperationMode.CW
        elif self == PrimaMode.BroadPulse:
            return api_pb2.OperationMode.BroadPulse
        elif self == PrimaMode.NarrowPulse:
            return api_pb2.OperationMode.NarrowPulse
        else:
            raise ValueError("Invalid mode")

class PrimaColor(Enum):
    BLUE  = "450_nm"
    GREEN = "515_nm"
    RED   = "640_nm"

    @staticmethod
    def from_idx(idx: int):
        """
        Decode the color index from the enum value.
        Args:
            idx (int): The index of the color.
        Returns:
            PrimaColor: The corresponding PrimaColor enum value.
        """
        if idx == 0:
            return PrimaColor.BLUE
        elif idx == 1:
            return PrimaColor.GREEN
        elif idx == 2:
            return PrimaColor.RED
        else:
            raise ValueError("Invalid color index")

    def get_idx(self):
        """
        Decode the color index from the enum value.
        Returns:
            int: The decoded color index.
            RED -> 0,
            GREEN -> 1,
            BLUE -> 2,
        """
        if self == PrimaColor.BLUE:
            return 0
        elif self == PrimaColor.GREEN:
            return 1
        elif self == PrimaColor.RED:
            return 2
        else:
            raise ValueError("Invalid color index")
    @property
    def value_nm(self):
        return int(self.value.split('_')[0])


class PrimaSpecs:
    """
    Class representing specifications for Prima laser systems.

    This class loads and processes laser power measurements from HDF5 files
    stored in the PicoQuant characterization directory.
    """
    name = None
    # FIXME: Index PrimaMode from mode_name instead of relying on correct order
    _mode_names = ["cw", "broad_pulse", "narrow_pulse"]
    _modes = [mode.value for mode in PrimaMode]
    _measurements_files = [measurement+'_measurements.h5' for measurement in _mode_names]
    _power_dict = {}
    def __init__(self, pq_char_path: Union[str, Path, None] = None):
        """
        Initialize the PrimaSpecs object.

        Args:
            pq_char_path: Path to the picoquant characterization directory.
                          If None, uses the DATASTORE_3D_PATH environment variable
                          to locate the default characterization directory.

        Raises:
            ValueError: If pq_char_path is None and DATASTORE_3D_PATH is not set.
            FileNotFoundError: If the specified path does not exist.
        """
        if pq_char_path is None:
            if 'DATASTORE_3D_PATH' not in os.environ:
                raise ValueError("pq_char_path cannot be None and DATASTORE_3D_PATH is not set.")
            DATASTORE_3D_PATH = os.environ['DATASTORE_3D_PATH']
            pq_char_path = os.path.join(DATASTORE_3D_PATH, 'ms_lidar/experiments/characterisation/laser/prima_picoquant')
        if not os.path.exists(pq_char_path):
            raise FileNotFoundError(f"Path {pq_char_path} does not exist.")
        self.pq_char_path = Path(pq_char_path)
        self.extract_power(self.pq_char_path)

    def extract_power(self, pq_char_path: Path):
        """
        Extract power measurements from the HDF5 files in the characterization directory.

        This method reads all measurement types defined in _measurements and populates
        the _power_dict with the measured power values for each color group.

        Args:
            pq_char_path: Path to the picoquant characterization directory.

        Raises:
            FileNotFoundError: If a measurement directory does not exist.
        """
        info("Begin extracting power profiles... modes={}, measurements_files={}".format(self._modes, self._measurements_files))
        # Filter self._modes to ignore "off"
        active_modes = [mode for mode in self._modes if mode != "off"]
        for (mode, h5_filename) in zip(active_modes, self._measurements_files):
            h5_filepath = os.path.join(pq_char_path, h5_filename)
            if not os.path.exists(h5_filepath):
                raise FileNotFoundError(f"Path {h5_filepath} does not exist.")
            self._power_dict[mode] = {}
            with h5py.File(h5_filepath, 'r') as h5_file:
                for group_name in h5_file:
                    group = h5_file[group_name]
                    if self.name is None:
                        self.name = group['instrument_laser']['name']
                    # Store power value in dictionary
                    power = group['results']['measured_power'][()]
                    self._power_dict[mode][group_name] = power
        info(f"Finished extracting power profiles for {self.name} with power dict: {self._power_dict.keys()}")

    # Given a desired power we want to set, lookup in power_dict using a polynomial fitting for the points around the best match to return per_mille value
    def get_per_mille_power(self, mode: Union[str, PrimaMode], wavelength: Union[str, PrimaColor], desired_power: float) -> tuple[int, float]:
        if isinstance(mode, PrimaMode):
            # Trying to convert to PrimaMode
            mode = mode.value
        if isinstance(wavelength, PrimaColor):
            wavelength = wavelength.value
        y_values = self._power_dict[mode][wavelength]
        nbrs = NearestNeighbors(n_neighbors=3)
        nbrs.fit(y_values.reshape(-1, 1))
        (y,x) = nbrs.kneighbors(np.array([[desired_power]]))
        x_sorted = np.sort(x.flatten())
        median_x = x_sorted[len(x_sorted) // 2]
        power = y_values[median_x]
        info(f"Error between {desired_power} and {power} for per_mille={median_x} is {abs(desired_power - power)}")
        return (median_x, power)

    def get_per_mille_flux(self, mode: Union[str, PrimaMode], color: Union[str, PrimaColor], desired_flux: float) -> tuple[int, float]:
        h = 6.62607015e-34  # Planck's constant
        if isinstance(color, str):
            color = PrimaColor[color]
        desired_power = self.convert_flux_to_power(color, desired_flux) # W
        info(f"Desired flux: {desired_flux} photons/s, Desired power: {desired_power} W")
        return self.get_per_mille_power(mode, color, desired_power)

    def get_frequency(self, color: PrimaColor) -> float:
        return 3e8 / (color.value_nm * 1e-9)  # Speed of light in m/s divided by wavelength in meters

    def convert_power_to_flux(self, color: PrimaColor, power: float) -> float:
        """
        Convert power to flux using the formula:
        flux = power / (h * 2 * pi * freq)
        """
        h = 6.62607015e-34
        return power / (h * 2 * np.pi * self.get_frequency(color))

    def convert_flux_to_power(self, color: PrimaColor, flux: float) -> float:
        """
        Convert flux to power using the formula:
        power = flux * (h * 2 * pi * freq)
        """
        h = 6.62607015e-34
        return flux * (h * 2 * np.pi * self.get_frequency(color))

class PrimaController:
    stub:    api_pb2_grpc.Sepia2Stub
    pri_req: api_pb2.PriRequest

    mode: PrimaMode = PrimaMode.Off
    wl: PrimaColor  = PrimaColor.RED
    power: float    = 0
    flux: float     = 0
    per_mille: int  = 0

    h5_dict = {}
    address = 'eng-7383.hyena-royal.ts.net:50051'

    # Make dictionary with max powers for each PrimaColor
    _max_power_dict: Dict[PrimaColor, Optional[float]] = {
        PrimaColor.BLUE: None,
        PrimaColor.GREEN: None,
        PrimaColor.RED: None
    }

    def __init__(self, h5_instrument=None, address=None):
        if address is None:
            warning(f"No address provided, using default {self.address}")
        else:
            self.address = address
        self.h5_instrument = h5_instrument
        self.spec = PrimaSpecs()
        if self.h5_instrument is not None:
            self.hdf5_describe(self.h5_instrument)
        self.init_pq_laser()

    def __del__(self):
        # In case user forgets to turn off the laser
        self.set_mode(PrimaMode.Off)

    def hdf5_describe(self, h5_instrument: h5py.Group):
        laser_source = h5_instrument.create_group("PQ_RGB_Prima_Laser")
        laser_source.attrs['NX_class'] = "NXsource" # https://manual.nexusformat.org/classes/base_classes/NXsource.html#index-0
        laser_source.create_dataset("name", data="Prima PicoQuant RGB Laser")
        laser_source.create_dataset("type", data="Picosecond pulsed laser")
        laser_source.create_dataset("manufacturer", data="PicoQuant GmbH")

        laser_datasheet = laser_source.create_group("specs")
        laser_datasheet.attrs['NX_class'] = 'NXtechnical_data'
        laser_datasheet.create_dataset("datasheet", data="https://www.picoquant.com/images/uploads/downloads/datasheet_prima_.pdf")
        wavelengths_spec = laser_source.create_dataset("wavelengths", data=[450,515,640])
        wavelengths_spec.attrs['units'] = "nm"
        energy = laser_source.create_dataset("energy", data=10)
        energy.attrs['units'] = "mW"
        pulse_width = laser_source.create_dataset("pulse_width", data=(100,200))
        pulse_width.attrs['units'] = "ps"

        laser_api = laser_source.create_group("API")
        laser_api.attrs['NX_class'] = 'NXtechnical_data'

        data = laser_source.create_group("data")
        data.attrs['NX_class'] = 'NXdata'

        wavelengths = data.create_dataset("wavelengths", shape=(0,), maxshape=(None,), dtype='f4')
        wavelengths.attrs['units'] = "nm"
        wavelengths.attrs['name'] = "Wavelength used"
        wavelengths.attrs['axes'] = "λ"

        flux = data.create_dataset("photon_flux", shape=(0,), maxshape=(None,), dtype='f4')
        flux.attrs['units'] = "photons/s"
        flux.attrs['name'] = "Photon flux"
        flux.attrs['axes'] = "Φ"

        power = data.create_dataset("power", shape=(0,), maxshape=(None,), dtype='f4')
        power.attrs['units'] = "W"
        power.attrs['name'] = "Power"
        power.attrs['axes'] = "P"

        per_mille = data.create_dataset("per_mille", shape=(0,), maxshape=(None,), dtype='u2')
        per_mille.attrs['units'] = '‰'
        per_mille.attrs['name'] = "Per mille"
        per_mille.attrs['axes'] = "per mille"

        self.h5_dict['instrument'] = h5_instrument
        self.h5_dict['source'] = laser_source
        self.h5_dict['api'] = laser_api
        self.h5_dict['data'] = data

    def write_h5_attrs(self, group, field, content):
        if group in self.h5_dict:
            self.h5_dict[group].attrs[field] = content
        else:
            warning(f"Group {group} not found in h5_dict. Cannot write attribute {field} with content {content}.")

    def write_h5_data(self, field, content):
        if 'data' not in self.h5_dict:
            debug("Data group not found in h5_dict. Skip logging!")
            return
        if field not in self.h5_dict['data']:
            info(f"dataset fields: {type(self.h5_dict['data'])}")
            warning(f"Field {field} not found in data group... creating a new one")
            ds = self.h5_dict['data'].create_dataset(field, shape=(1,), maxshape=(None,), data=[content])
            ds.attrs['units'] = 'unknown'
            ds.attrs['axes'] = 'unknown'
        else:
            prev_len = self.h5_dict['data'][field].shape[0]
            self.h5_dict['data'][field].resize((prev_len + 1,))
            self.h5_dict['data'][field][prev_len] = content
            self.h5_dict['data'][field][prev_len] = content

    def init_pq_laser(self):
        # Now you can use the generated classes and functions
        channel = grpc.insecure_channel(self.address)  # Replace with your server's address
        stub = api_pb2_grpc.Sepia2Stub(channel)
        response = stub.LIB_GetVersion(api_pb2.Empty())  # Check PQ-Laser version
        info(response)
        self.write_h5_attrs('api', 'PQ Lib Version', response.version)  # Store PQ-Laser version in HDF5 file)

        if not stub.USB_IsOpenDevice(api_pb2.DeviceIdx(dev_idx=0)).value:  # Check if USB is open
            info(stub.USB_OpenDevice(api_pb2.DeviceIdx(dev_idx=0)))  # Open USB device
            info("USB device opened.")

        fwr_version = stub.FWR_GetVersion(api_pb2.DeviceIdx(dev_idx=0)).value  # Get firmware version
        info(f"USB(0) FWR version: {fwr_version}")
        self.write_h5_attrs('api', 'PQ FWR Version', fwr_version)

        usb_descr = stub.USB_GetStrDescriptor(api_pb2.DeviceIdx(dev_idx=0)).value  # Get USB descriptor
        info(f"USB(0) descriptor: {usb_descr}")
        self.write_h5_attrs('api', 'PQ USB descriptor', usb_descr)

        module_cnt = stub.FWR_GetModuleMap(api_pb2.GetModuleMapRequest(dev_idx=0, perform_restart=True)).value
        info(f"USB(0) alloc module map: {module_cnt}")  # Get module map
        self.write_h5_attrs('api', 'PQ USB module count', module_cnt)

        for map_idx in range(module_cnt):
            module_info = stub.FWR_GetModuleInfoByMapIdx(api_pb2.MapIdxRequest(dev_idx=0, map_idx=map_idx))
            info(f"USB(0) module map[{map_idx}]: {module_info}")  # logging.info module map
            self.write_h5_attrs('api', f'PQ USB module map[{map_idx}]', str(module_info))

        # WARN: Slot 100 seems to be the laser control slot, but not sure why
        pri_request = api_pb2.PriRequest(dev_idx=0, slot_id=100)

        pri_info = stub.PRI_GetDeviceInfo(pri_request)  # Get device info
        info(f"USB(0) PRI device info: {pri_info}")
        self.write_h5_attrs('api', 'PQ PRI device info', str(pri_info))

        freq_limits = stub.PRI_GetFrequencyLimits(pri_request)  # Get frequency limits
        info(f"USB(0) PRI frequency limits: {freq_limits}")
        self.write_h5_attrs('api', 'PQ PRI frequency limits', str(freq_limits))

        wl_req  = api_pb2.WavelengthRequest(pri_req = pri_request, wl_idx=2)
        stub.PRI_SetWavelengthIdx(wl_req)  # Set wavelength
        stub.PRI_SetIntensity(api_pb2.SetIntensityRequest(wl_req = wl_req, intensity=0))  # Set intensity per mille
        # NOTE: By default we set the laser in NarrowPulse mode as this is the mode that is of most importance to us
        stub.PRI_SetOperationMode(api_pb2.OperationModeRequest(pri_req = pri_request, oper_mode_enum=api_pb2.OperationMode.NarrowPulse))
        stub.PRI_SetTriggerSource(api_pb2.TriggerSourceRequest(pri_req = pri_request, trg_src_idx=4))  # Set trigger source to external rising
        stub.PRI_SetTriggerLevel(api_pb2.TriggerLevelRequest(pri_req = pri_request, trg_lvl=1000))  # Set trigger level to 1000mV

        self.stub = stub
        self.pri_req = pri_request

        return stub, pri_request

    def set_mode(self, mode: Union[PrimaMode, api_pb2.OperationMode.ValueType]):
        pb_mode: api_pb2.OperationMode.ValueType = mode.to_pb() if isinstance(mode, PrimaMode) else mode
        pq_mode: PrimaMode = mode if isinstance(mode, PrimaMode) else PrimaMode(pb_mode)
        self.stub.PRI_SetOperationMode(api_pb2.OperationModeRequest(pri_req = self.pri_req, oper_mode_enum=pb_mode))
        # TODO: Convert from api_pb2 mode as well
        self.mode = pq_mode

    def set_wavelength(self, wavelength: Union[int, str, PrimaColor]):
        if isinstance(wavelength, str):
            self.wl = PrimaColor[wavelength]
        elif isinstance(wavelength, int):
            self.wl = PrimaColor.from_idx(wavelength)
        else:
            self.wl = wavelength

        self.write_h5_data('wavelengths', self.wl.value_nm)

        wl_req  = api_pb2.WavelengthRequest(pri_req = self.pri_req, wl_idx=self.wl.get_idx())
        self.stub.PRI_SetWavelengthIdx(wl_req)
        self.write_h5_data('wavelengths_idx', self.wl.get_idx())

    def set_flux(self, flux: float):
        """
        Set the laser flux in photons per second.
        Args:
            flux (float): The desired flux in photons per second.
        """
        if self.mode == PrimaMode.Off:
            raise ValueError("Laser is off, cannot set flux.")

        self.per_mille, self.power = self.spec.get_per_mille_flux(self.mode, self.wl, flux)
        self.flux = self.spec.convert_power_to_flux(self.wl, self.power)

        self.write_h5_data('photon_flux', self.flux)
        self.write_h5_data('power', self.power)
        self.write_h5_data('per_mille', self.per_mille)

        info(f"Setting laser to {flux} photons/s ({self.power} W) with per mille={self.per_mille}")
        wl_req  = api_pb2.WavelengthRequest(pri_req = self.pri_req, wl_idx=self.wl.get_idx())
        self.stub.PRI_SetIntensity(api_pb2.SetIntensityRequest(wl_req = wl_req, intensity=self.per_mille))

    def set_power(self, power: float):
        """
        Set the laser power in W.
        Args:
            power (float): The desired power in W.
        """
        if self.mode == PrimaMode.Off:
            raise ValueError("Laser is off, cannot set power.")
        self.per_mille, self.power = self.spec.get_per_mille_power(self.mode, self.wl, power)
        self.flux = self.spec.convert_power_to_flux(self.wl, self.power)

        self.write_h5_data('power', self.power)
        self.write_h5_data('per_mille', self.per_mille)

        info(f"Setting laser to {self.power}≈{power} W with per mille={self.per_mille}")
        wl_req  = api_pb2.WavelengthRequest(pri_req = self.pri_req, wl_idx=self.wl.get_idx())
        self.stub.PRI_SetIntensity(api_pb2.SetIntensityRequest(wl_req = wl_req, intensity=self.per_mille))

    def set_max_power(self, power: Union[float, Dict[PrimaColor, Optional[float]]]):
        """
        Set the maximum power for the laser.
        Args:
            power (float): The desired maximum power in W.
        """
        if isinstance(power, dict):
            for color, max_power in power.items():
                self._max_power_dict[color] = max_power
        else:
            for color in self._max_power_dict.keys():
                self._max_power_dict[color] = float(power)
            #self._max_power_dict[self.wl] = power

    def get_power(self) -> float:
        return self.power

    def get_flux(self) -> float:
        return self.flux

    def get_per_mille(self) -> int:
        return self.per_mille
