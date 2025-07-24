import pyvisa
import h5py
import numpy as np
import logging
import colorlog
from logging import info, warning, debug, error
from datetime import datetime
from time import sleep

# Define wavelengths for measurement
wavelengths_default = [450, 515, 640]  # Wavelengths in nanometers


class PM400Error(Exception):
    pass

class PowerMeter:
    _wavelengths_range = np.linspace(400, 1100, 50)  # nm
    h5_instrument = None
    h5_dict = {}
    pm_resource : pyvisa.resources.Resource
    rm : pyvisa.ResourceManager
    def __init__(self, h5_instrument=None, rm=None, visa_id=None):
        if rm is None:
            rm = pyvisa.ResourceManager()
            warning("No resource manager provided, creating a new one.")
        self.rm = rm
        if visa_id is None:
            warning(f"No VISA device provided, scanning resources for a PM400")
            try:
                visa_id = self._find_pm400()
                info(f"PM400 found at {visa_id}")
            except:
                visa_id = 'USB0::4883::32885::P5003184::0::INSTR'  # Replace with actual USB resource name
                warning(f"No PM400 found, using default: {visa_id}")
        self.visa_id = visa_id
        info(f"Connecting to {visa_id}...")
        self.pm_resource = rm.open_resource(visa_id)

        if h5_instrument is not None:
            self.h5_instrument = h5_instrument
            self.hdf5_describe(h5_instrument)

        try:
            self.pm_resource.write('*RST')  # Reset device to default settings
            self.pm_resource.write('*CLS')  # Clear status
            info("Starting measurements...")
        except Exception as e:
            error(f"An error occurred: {e}")

    def _find_pm400(self):
        """Auto-discovers the first PM400 in VISA resources."""
        info(f"Available resources: {self.rm.list_resources()}")
        for res in self.rm.list_resources():
            try:
                inst = self.rm.open_resource(res)
                idn = inst.query("*IDN?")
                if "PM400" in idn:
                    inst.close()
                    return res
                inst.close()
            except Exception:
                continue
        raise PM400Error("No PM400 instrument found.")

    def _check_idn(self):
        """Checks that the connected device is a PM400."""
        idn = self.pm_resource.query("*IDN?").strip()
        if "PM400" not in idn:
            raise PM400Error(f"Connected device is not a PM400: {idn}")

    def get_idn(self):
        """Returns the pm_resourcerument identification string."""
        return self.pm_resource.query("*IDN?").strip()

    def set_wavelength(self, wavelength):
        """
        Configures the PM400 to measure at a specific wavelength.
        """
        self.pm_resource.write(f'SENS:CORR:WAV {wavelength}')  # Set wavelength
        debug(f"Wavelength set to {wavelength} nm.")

    def get_wavelength(self):
        """
        Gets the current measurement wavelength in nanometers.
        """
        return float(self.pm_resource.query("SENS:CORR:WAV?"))

    def read_power(self):
        """
        Reads the current measured optical power in Watts.
        """
        return float(self.pm_resource.query('MEAS:POW?'))  # Query power measurement

    def read_flux(self):
        """
        Reads the current measured irradiance in W/m^2.
        """
        wavelegth = float(self.get_wavelength())
        power = self.read_power()
        # TODO convert in photons/s
        # Photon energy E = h*c/λ
        h = 6.626e-34  # Planck's constant (J*s)
        c = 3e8  # Speed of light (m/s)
        flux = power / (h * c / (wavelegth * 1e-9))  # in photons/s
        return flux

    def hdf5_describe(self, h5_instrument: h5py.Group):
        pm_detector = h5_instrument.create_group("power_meter")
        pm_detector.attrs['NX_class'] = "NXinstrument" # https://manual.nexusformat.org/classes/base_classes/NXsource.html#index-0
        pm_detector.create_dataset("name", data="Thorlabs PM400 400-1100nm")
        pm_detector.create_dataset("type", data="Power meter")
        pm_detector.create_dataset("manufacturer", data="Thorlabs")

        pm_datasheet = pm_detector.create_group("specs")
        pm_datasheet.attrs['NX_class'] = 'NXtechnical_data'
        pm_datasheet.create_dataset("datasheet", data="https://www.thorlabs.com/drawings/13fefd4ddeb72e3c-6D730A86-A702-B53C-E9E377EA603B3CBE/PM400-Manual.pdf")

        data = pm_detector.create_group("data")
        data.attrs['NX_class'] = 'NXdata'
        data.attrs['description'] = 'Measured power data'
        # TODO: Change into iradiance photons/cm2/s
        data.attrs['axes'] = ['power:wavelength']

        self.h5_dict['instrument'] = h5_instrument
        self.h5_dict['detector'] = pm_detector
        self.h5_dict['data'] = data

    def scan_spectrum(self, wavelengths_range=None):
        if wavelengths_range is None:
            wavelengths_range = self._wavelengths_range

        # FIXME: Don't panic if there is no hdf5 handler
        self.h5_dict['data'].attrs['start_time'] = datetime.now().isoformat()
        wavelength_ds = self.h5_dict['data'].create_dataset('wavelength', shape=(len(wavelengths_range),) ,dtype='f4')
        wavelength_ds.attrs['units'] = 'nm'
        power_ds = self.h5_dict['data'].create_dataset('power', shape=(len(wavelengths_range),) ,dtype='f4')
        power_ds.attrs['units'] = 'W'
        flux_ds = self.h5_dict['data'].create_dataset('flux', shape=(len(wavelengths_range),) ,dtype='f4')
        flux_ds.attrs['units'] = 'photons/s'

        info(f"Power meter scanning wavelengths: [{wavelengths_range[0]}, {wavelengths_range[-1]}]")

        for (idx,wavelength) in enumerate(wavelengths_range):
            self.set_wavelength(wavelength)
            sleep(1)
            power = self.read_power()
            flux = self.read_flux()
            debug(f"Measured power at {wavelength} nm: {power} W")
            wavelength_ds[idx] = wavelength
            power_ds[idx] = power
            flux_ds[idx] = flux

        self.h5_dict['data'].attrs['end_time'] = datetime.now().isoformat()
