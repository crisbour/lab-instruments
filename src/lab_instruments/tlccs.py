# Most of the code is a pyUSB re-implementation of Thorlabs'
# tlccs library, which is distributed under LGPL2.1.
# The original C code can be found in the tlccs folder.
#
# Some of the original code has not been re-implemeted (in particular
# writing to the EEPROM), and some code was added
# (different amplitude correction modes handled by the ThorSpectra
# software, firmware upload for re-enumeration)

# Resourced from: https://github.com/ElTinmar/ThorPy


from dataclasses import dataclass, field
import array
import usb.core
import usb.util
import struct
import time
import math
from typing import Optional, Tuple, NamedTuple, Dict, List, Union
import numpy as np
from pathlib import Path
from importlib.resources import files
from logging import warning
import inspect
import h5py

import sys
if sys.platform == 'win32':
    import libusb_package
    libusb_backend = libusb_package.get_libusb1_backend()
else:
    libusb_backend = None

class EEPROMChecksumError(Exception): ...
class InvalidUserData(Exception): ...
class Overexposure(Exception): ...
class DeviceNotFound(Exception): ...
class NoUserDataPoint(Exception): ...
class RenumerationFailed(Exception): ...

THORLABS_VID = 0x1313
PID_RANGE    = (0x8080, 0x8089)
CCS100_PID_U = 0x8080  # CCS100 Compact Spectrometer
CCS100_PID   = 0x8081  # CCS100 Compact Spectrometer
CCS125_PID_U = 0x8082  # CCS125 Special Spectrometer
CCS125_PID   = 0x8083  # CCS125 Special Spectrometer
CCS150_PID_U = 0x8084  # CCS150 UV Spectrometer
CCS150_PID   = 0x8085  # CCS150 UV Spectrometer
CCS175_PID_U = 0x8086  # CCS175 NIR Spectrometer
CCS175_PID   = 0x8087  # CCS175 NIR Spectrometer
CCS200_PID_U = 0x8088  # CCS200 UV-NIR Spectrometer
CCS200_PID   = 0x8089  # CCS200 UV-NIR Spectrometer
DEFAULT_RENUMERATION_TIMEOUT = 10.0

TLCCS_SERIAL_NO_LENGTH     = 24
TLCCS_MAX_USER_NAME_SIZE   = 32
TLCCS_NUM_POLY_POINTS      = 4
TLCCS_NUM_PIXELS           = 3648
TLCCS_NUM_FLAG_WORDS       = 1
TLCCS_NUM_CHECKSUMS        = 2
TLCCS_MAX_NUM_USR_ADJ      = 10
TLCCS_AMP_CORR_FACT_MIN    = 0.001
TLCCS_AMP_CORR_FACT_MAX    = 1000.0
ENDPOINT_0_TRANSFERSIZE    = 64
TLCCS_TIMEOUT_DEF          = 2000
TLCCS_CAL_MODE_USER        = 0
TLCCS_CAL_DATA_SET_FACTORY = 0
TLCCS_CAL_DATA_SET_USER    = 1
TLCCS_MIN_INT_TIME         = 1e-5
TLCCS_MAX_INT_TIME         = 60
TLCCS_DEF_INT_TIME         = 0.01
TLCCS_NUM_RAW_PIXELS       = 3694
SH_PERCENT                 = 16.5
TLCCS_NUM_INTEG_CTRL_BYTES = 6

TLCCS_RCMD_READ_EEPROM      = 0x21
TLCCS_RCMD_READ_RAM         = 0xA0
TLCCS_RCMD_GET_STATUS       = 0x30
TLCCS_WCMD_INTEGRATION_TIME = 0x23
TLCCS_WCMD_MODUS            = 0x24
TLCCS_WCMD_RESET            = 0x26
CONTROL_TRANSFER_IN_ZERO    = 0xC0

TLCCS_STATUS_SCAN_IDLE         = 0x0002 # CCS waits for new scan to execute
TLCCS_STATUS_SCAN_TRIGGERED    = 0x0004 # scan in progress
TLCCS_STATUS_SCAN_START_TRANS  = 0x0008 # scan starting
TLCCS_STATUS_SCAN_TRANSFER     = 0x0010 # scan is done, waiting for data transfer to PC
TLCCS_STATUS_WAIT_FOR_EXT_TRIG = 0x0080 # same as IDLE except that external trigger is armed

NO_DARK_PIXELS           = 12 # we got 12 dark pixels
DARK_PIXELS_OFFSET       = 16 # dark pixels start at positon 16 within raw data
SCAN_PIXELS_OFFSET       = 32 # real measurement start at position 32 within raw data
MAX_ADC_VALUE            = 0xFFFF # this is full scale of a 16bit Analog Digital Converter (ADC)
DARK_LEVEL_THRESHOLD     = 0.99 # when dark level is above 99% f.s. of ADC mark scan as invalid (overexposed)
DARK_LEVEL_THRESHOLD_ADC = DARK_LEVEL_THRESHOLD * MAX_ADC_VALUE

MODUS_INTERN_SINGLE_SHOT = 0
MODUS_INTERN_CONTINUOUS  = 1
MODUS_EXTERN_SINGLE_SHOT = 2
MODUS_EXTERN_CONTINUOUS  = 3

CHAR_SZ   = 1
REAL64_SZ = 8
REAL32_SZ = 4
INT32_SZ  = 4
UINT32_SZ = 4
UINT16_SZ = 2
INT16_SZ  = 2
UINT8_SZ  = 1

#===========================================================================
#   On-chip RAM mapping
#===========================================================================

RAM_PROGRAM_START = 0x0000 # main  RAM (program + data)
RAM_PROGRAM_SIZE  = 0X4000
RAM_DATA_START    = 0xE000 # scratch RAM (data only)
RAM_DATA_SIZE     = 0x0200
RAM_BUFFERS_START = 0xE200 # endpoint buffers and control/status registers
RAM_BUFFERS_SIZE  = 0x1E00

#===========================================================================
#   EEPROM mapping: 32kB EEPROM
#===========================================================================

EE_LENGTH_SERIAL_NO               = CHAR_SZ * TLCCS_SERIAL_NO_LENGTH
EE_LENGTH_SW_VERSION              = 4
EE_LENGTH_USER_LABEL              = CHAR_SZ * TLCCS_MAX_USER_NAME_SIZE
EE_LENGTH_FACT_CAL_COEF_FLAG      = 2
EE_LENGTH_FACT_CAL_COEF_DATA      = REAL64_SZ * TLCCS_NUM_POLY_POINTS
EE_LENGTH_USER_CAL_COEF_FLAG      = 2
EE_LENGTH_USER_CAL_COEF_DATA      = REAL64_SZ * TLCCS_NUM_POLY_POINTS
EE_LENGTH_USER_CAL_POINTS_CNT     = 2
EE_LENGTH_USER_CAL_POINTS_DATA    = (INT32_SZ + REAL64_SZ) * TLCCS_MAX_NUM_USR_ADJ
EE_LENGTH_OFFSET_MAX              = 2
EE_LENGTH_ACOR                    = REAL32_SZ * TLCCS_NUM_PIXELS
EE_LENGTH_FLAGS                   = UINT32_SZ * TLCCS_NUM_FLAG_WORDS
EE_LENGTH_CHECKSUMS               = UINT16_SZ * TLCCS_NUM_CHECKSUMS

# eeprom sizes
EE_SIZE_CHECKSUM                  = 2
EE_SIZE_BOOT_CODE                 = 1
EE_SIZE_SERIAL_NO                 = EE_LENGTH_SERIAL_NO
EE_SIZE_SW_VERSION                = EE_LENGTH_SW_VERSION            + EE_SIZE_CHECKSUM
EE_SIZE_USER_LABEL                = EE_LENGTH_USER_LABEL            + EE_SIZE_CHECKSUM
EE_SIZE_FACT_CAL_COEF_FLAG        = EE_LENGTH_FACT_CAL_COEF_FLAG    + EE_SIZE_CHECKSUM
EE_SIZE_FACT_CAL_COEF_DATA        = EE_LENGTH_FACT_CAL_COEF_DATA    + EE_SIZE_CHECKSUM
EE_SIZE_USER_CAL_COEF_FLAG        = EE_LENGTH_USER_CAL_COEF_FLAG    + EE_SIZE_CHECKSUM
EE_SIZE_USER_CAL_COEF_DATA        = EE_LENGTH_USER_CAL_COEF_DATA    + EE_SIZE_CHECKSUM
EE_SIZE_USER_CAL_POINTS_CNT       = EE_LENGTH_USER_CAL_POINTS_CNT   + EE_SIZE_CHECKSUM
EE_SIZE_USER_CAL_POINTS_DATA      = EE_LENGTH_USER_CAL_POINTS_DATA  + EE_SIZE_CHECKSUM
EE_SIZE_OFFSET_MAX                = EE_LENGTH_OFFSET_MAX            + EE_SIZE_CHECKSUM
EE_SIZE_ACOR                      = EE_LENGTH_ACOR                  + EE_SIZE_CHECKSUM
EE_SIZE_FLAGS                     = EE_LENGTH_FLAGS                 + EE_SIZE_CHECKSUM
EE_SIZE_CHECKSUMS                 = EE_LENGTH_CHECKSUMS             + EE_SIZE_CHECKSUM

# eeprom addresses
EE_BOOT_CODE                      = 0
EE_VENDOR_ID                      = 1
EE_PRODUCT_ID                     = 3
EE_DEVICE_ID                      = 5
EE_SERIAL_NO                      = 8
EE_SW_VERSION                     = EE_SERIAL_NO              + EE_SIZE_SERIAL_NO              # software version
EE_USER_LABEL                     = EE_SW_VERSION             + EE_SIZE_SW_VERSION             # user label
EE_FACT_CAL_COEF_FLAG             = EE_USER_LABEL             + EE_SIZE_USER_LABEL             # factory calibration flags
EE_FACT_CAL_COEF_DATA             = EE_FACT_CAL_COEF_FLAG     + EE_SIZE_FACT_CAL_COEF_FLAG     # factory calibration coefficients
EE_USER_CAL_COEF_FLAG             = EE_FACT_CAL_COEF_DATA     + EE_SIZE_FACT_CAL_COEF_DATA     # user calibration flags
EE_USER_CAL_COEF_DATA             = EE_USER_CAL_COEF_FLAG     + EE_SIZE_USER_CAL_COEF_FLAG     # user calibration coefficients
EE_USER_CAL_POINTS_CNT            = EE_USER_CAL_COEF_DATA     + EE_SIZE_USER_CAL_COEF_DATA     # user calibration points count
EE_USER_CAL_POINTS_DATA           = EE_USER_CAL_POINTS_CNT    + EE_SIZE_USER_CAL_POINTS_CNT    # user calibration points
EE_EVEN_OFFSET_MAX                = EE_USER_CAL_POINTS_DATA   + EE_SIZE_USER_CAL_POINTS_DATA   # even offset max
EE_ODD_OFFSET_MAX                 = EE_EVEN_OFFSET_MAX        + EE_SIZE_OFFSET_MAX             # odd offset max
EE_ACOR_FACTORY                   = EE_ODD_OFFSET_MAX         + EE_SIZE_OFFSET_MAX             # amplitude correction, factory setting
EE_ACOR_USER                      = EE_ACOR_FACTORY           + EE_SIZE_ACOR                   # amplitude correction, factory setting
EE_FLAGS                          = EE_ACOR_USER              + EE_SIZE_ACOR                   # flags for e.g. user cal/factory cal
EE_CHECKSUMS                      = EE_FLAGS                  + EE_SIZE_FLAGS                  # checksums for amplitude correction arrays
EE_FREE                           = EE_CHECKSUMS              + EE_SIZE_CHECKSUMS              # free memory


@dataclass
class TLCCS_WL_CAL:
    poly:  array.array = field(default_factory=lambda: array.array('d', [0]*TLCCS_NUM_POLY_POINTS))
    min:   float = 0
    max:   float = 0
    wl:    array.array = field(default_factory=lambda: array.array('d', [0]*TLCCS_NUM_PIXELS))
    valid: int = 0

@dataclass
class TLCCS_USER_CAL_PTS:
    user_cal_node_cnt:   int = 0
    user_cal_node_pixel: array.array = field(default_factory=lambda: array.array('L', [0]*TLCCS_MAX_NUM_USR_ADJ))
    user_cal_node_wl:    array.array = field(default_factory=lambda: array.array('d', [0]*TLCCS_MAX_NUM_USR_ADJ))

@dataclass
class TLCCS_ACOR:
    amplitude_cor: array.array = field(default_factory=lambda: array.array('f', [1.0]*TLCCS_NUM_PIXELS))
    checksum:      int = 0

@dataclass
class TLCCS_VERSION:
    major:    int = 0
    minor:    int = 0
    subminor: int = 0

@dataclass
class TLCCS_DATA:

    # common data
    err_query:              bool  = False
    timeout:                int   = 0
    pid:                    int   = 0x0000
    vid:                    int   = 0x0000

    # device settings
    int_time:               float = 0.01
    even_offset_max:        int   = 1
    odd_offset_max:         int   = 1

    # device calibration
    factory_wavelength_cal: TLCCS_WL_CAL       = field(default_factory = TLCCS_WL_CAL)
    user_wavelength_cal:    TLCCS_WL_CAL       = field(default_factory = TLCCS_WL_CAL)
    user_points:            TLCCS_USER_CAL_PTS = field(default_factory = TLCCS_USER_CAL_PTS)

    factory_amplitude_cal:  TLCCS_ACOR = field(default_factory=TLCCS_ACOR)
    user_amplitude_cal:     TLCCS_ACOR = field(default_factory=TLCCS_ACOR)
    cal_mode:               int = 0

    # version
    firmware_version:       TLCCS_VERSION = field(default_factory=TLCCS_VERSION)
    hardware_version:       TLCCS_VERSION = field(default_factory=TLCCS_VERSION)


def read_EEPROM_wo_CRC(
        dev:     usb.core.Device,
        address: int,
        idx:     int,
        length:  int
    ) -> array.array:

    data          = array.array('B')
    chunk_address = address

    while (length > 0):

        if (length >= ENDPOINT_0_TRANSFERSIZE):
            chunk_length = ENDPOINT_0_TRANSFERSIZE
        else:
            chunk_length = length

        chunk = dev.ctrl_transfer(
            bmRequestType   = CONTROL_TRANSFER_IN_ZERO,
            bRequest        = TLCCS_RCMD_READ_EEPROM,
            wValue          = chunk_address,
            wIndex          = idx,
            data_or_wLength = chunk_length
        )
        data.extend(chunk)

        length        -= len(chunk)
        chunk_address += len(chunk)

    return data


def read_EEPROM(
        dev:     usb.core.Device,
        address: int,
        idx:     int,
        length:  int
    ) -> array.array:

    data = read_EEPROM_wo_CRC(dev, address, idx, length)

    if address >= EE_SW_VERSION:
        checksum = crc16_block(data, length)
        checksum_bytes = read_EEPROM_wo_CRC(dev, address+length, idx, UINT16_SZ)
        eeprom_checksum = struct.unpack('<H', checksum_bytes)[0]
        if(checksum != eeprom_checksum):
            if eeprom_checksum == 0xFFFF:
                #print('Empty data on EEPROM')
                ...

            else:
                raise EEPROMChecksumError

    return data

def read_RAM(
        dev:     usb.core.Device,
        address: int,
        idx:     int,
        length:  int
    ) -> array.array:

    data          = array.array('B')
    chunk_address = address

    while (length > 0):

        if (length >= ENDPOINT_0_TRANSFERSIZE):
            chunk_length = ENDPOINT_0_TRANSFERSIZE
        else:
            chunk_length = length

        chunk = dev.ctrl_transfer(
            bmRequestType = CONTROL_TRANSFER_IN_ZERO,
            bRequest = TLCCS_RCMD_READ_RAM,
            wValue = chunk_address,
            wIndex = idx,
            data_or_wLength = chunk_length
        )
        data.extend(chunk)

        length        -= len(chunk)
        chunk_address += len(chunk)

    return data

def crc16_block(data: array.array, length: int) -> int:

    crc: int = 0xFFFF
    cnt: int = 0

    while length:
        crc     = crc16_update(crc, data[cnt])
        cnt    += 1
        length -= 1

    return crc


def crc16_update(crc, d: int) -> int:

    crc ^= d
    for i in range(8):
        if (crc & 1):
            crc = (crc >> 1) ^ 0xA001
        else:
            crc = (crc >> 1)

    return crc & 0xFFFF


def initialize(dev: usb.core.Device, data: TLCCS_DATA) -> None:

    data.pid      = dev.idProduct
    data.vid      = dev.idVendor
    data.timeout  = TLCCS_TIMEOUT_DEF
    data.cal_mode = TLCCS_CAL_MODE_USER

    set_integration_time(dev, TLCCS_DEF_INT_TIME)
    get_wavelength_parameters(dev, data)
    get_dark_current_offset(dev, data)
    get_firmware_revision(dev, data.firmware_version)
    get_hardware_revision(dev, data.hardware_version)
    get_amplitude_correction(dev, data)

def start_single_scan(dev: usb.core.Device):

    dev.ctrl_transfer(
        bmRequestType   = 0x40,
        bRequest        = TLCCS_WCMD_MODUS,
        wValue          = MODUS_INTERN_SINGLE_SHOT,
        wIndex          = 0x0000,
        data_or_wLength = 0
    )

def start_continuous_scan(dev: usb.core.Device):

    dev.ctrl_transfer(
        bmRequestType   = 0x40,
        bRequest        = TLCCS_WCMD_MODUS,
        wValue          = MODUS_INTERN_CONTINUOUS,
        wIndex          = 0x0000,
        data_or_wLength = 0
    )

def get_device_status(dev: usb.core.Device) -> int:

    status_bytes = dev.ctrl_transfer(
        bmRequestType   = 0xC0,
        bRequest        = TLCCS_RCMD_GET_STATUS,
        wValue          = 0x0000,
        wIndex          = 0x0000,
        data_or_wLength = UINT16_SZ
    )
    status = struct.unpack('<H', status_bytes)[0]
    return status

def get_scan_data(
        dev:  usb.core.Device,
        data: TLCCS_DATA
    ) -> array.array:

    raw_scan_bytes      = dev.read(0x86, TLCCS_NUM_RAW_PIXELS*UINT16_SZ)
    raw_scan_data       = struct.unpack('<' + 'H'*(len(raw_scan_bytes)//2), raw_scan_bytes)
    processed_scan_data = array.array('d', [0]*TLCCS_NUM_PIXELS)

    # dark current average
    dark_com: float = 0.0
    for i in range(NO_DARK_PIXELS):
        dark_com += raw_scan_data[(DARK_PIXELS_OFFSET + i)]
    dark_com /= NO_DARK_PIXELS

    # when dark level is too high we assume an overexposure
    if (dark_com > DARK_LEVEL_THRESHOLD_ADC):
        raise Overexposure

    norm_com = 1.0 / (MAX_ADC_VALUE - dark_com)
    for i in range(TLCCS_NUM_PIXELS):
        processed_scan_data[i] = ((raw_scan_data[SCAN_PIXELS_OFFSET + i]) - dark_com) * norm_com

    return processed_scan_data

def get_scan_data_factory(
        dev:  usb.core.Device,
        data: TLCCS_DATA
    ) -> array.array:

    scan_data = get_scan_data(dev, data)
    for i in range(TLCCS_NUM_PIXELS):
        scan_data[i] *= data.factory_amplitude_cal.amplitude_cor[i]
    return scan_data

def get_scan_data_corrected_range(
        dev: usb.core.Device,
        data: TLCCS_DATA,
        min_wl: float,
        max_wl: float
    ) -> Tuple[array.array, float]:

    idx_min: int = next((i for i, val in enumerate(data.factory_wavelength_cal.wl) if val > min_wl))
    idx_max: int = next((i for i, val in enumerate(data.factory_wavelength_cal.wl) if val > max_wl))
    amplitude_cor: array.array = data.user_amplitude_cal.amplitude_cor[idx_min:idx_max]
    noise_amplification_mult: float = max(amplitude_cor)/min(amplitude_cor)
    noise_amplification_dB: float = 10*math.log10(noise_amplification_mult)

    scan_data = get_scan_data(dev, data)
    for i in range(TLCCS_NUM_PIXELS):
        if i < idx_min or i > idx_max:
            scan_data[i] = 0
        else:
            scan_data[i] *= data.user_amplitude_cal.amplitude_cor[i] / min(amplitude_cor)
    return scan_data, noise_amplification_dB


def find_centered_range(arr: array.array, center: int, threshold: float) -> Tuple[int, int, float, float]:

    n = len(arr)
    left = right = center
    min_val = max_val = arr[center]

    while True:
        expanded = False

        # 1. Try symmetric expansion first
        if left > 0 and right < n - 1:
            new_left, new_right = left - 1, right + 1
            new_min = min(min_val, arr[new_left], arr[new_right])
            new_max = max(max_val, arr[new_left], arr[new_right])
            if new_max / new_min <= threshold:
                left, right = new_left, new_right
                min_val, max_val = new_min, new_max
                expanded = True

        # 2. If symmetric fails (or one side blocked), try one-sided
        if not expanded:
            # try left-only
            if left > 0:
                new_left = left - 1
                new_min = min(min_val, arr[new_left])
                new_max = max(max_val, arr[new_left])
                if new_max / new_min <= threshold:
                    left = new_left
                    min_val, max_val = new_min, new_max
                    expanded = True

            # try right-only
            if not expanded and right < n - 1:
                new_right = right + 1
                new_min = min(min_val, arr[new_right])
                new_max = max(max_val, arr[new_right])
                if new_max / new_min <= threshold:
                    right = new_right
                    min_val, max_val = new_min, new_max
                    expanded = True

        if not expanded:
            break

    return left, right, min_val, max_val

def get_scan_data_corrected_noise(
        dev:                    usb.core.Device,
        data:                   TLCCS_DATA,
        center_wl:              float,
        noise_amplification_dB: float
    ) -> Tuple[array.array, float, float]:

    noise_multiplier = 10**(noise_amplification_dB/10)
    idx_center: int = next((i for i, val in enumerate(data.factory_wavelength_cal.wl) if val >= center_wl))

    idx_left, idx_right, min_correction, max_correction = find_centered_range(
        arr       = data.user_amplitude_cal.amplitude_cor,
        center    = idx_center,
        threshold = noise_multiplier
    )
    wavelength_left  = data.factory_wavelength_cal.wl[idx_left]
    wavelength_right = data.factory_wavelength_cal.wl[idx_right]

    scan_data = get_scan_data(dev, data)
    for i in range(TLCCS_NUM_PIXELS):
        if i < idx_left or i > idx_right:
            scan_data[i] = 0
        scan_data[i] *= data.user_amplitude_cal.amplitude_cor[i] / min_correction

    return scan_data, wavelength_left, wavelength_right

def set_integration_time(dev: usb.core.Device, time: float):

    time_data = encode_integration_time(time)
    dev.ctrl_transfer(
        bmRequestType   = 0x40,
        bRequest        = TLCCS_WCMD_INTEGRATION_TIME,
        wValue          = 0x0000,
        wIndex          = 0x0000,
        data_or_wLength = time_data
    )


def get_integration_time(dev: usb.core.Device) -> float:

    time_bytes = dev.ctrl_transfer(
        bmRequestType   = 0xC0,
        bRequest        = TLCCS_WCMD_INTEGRATION_TIME,
        wValue          = 0x0000,
        wIndex          = 0x0000,
        data_or_wLength = TLCCS_NUM_INTEG_CTRL_BYTES*UINT8_SZ
    )
    return decode_integration_time(time_bytes)

def get_wavelength(data: TLCCS_DATA, factory_or_user: int = TLCCS_CAL_DATA_SET_FACTORY) -> array.array:

    if factory_or_user == TLCCS_CAL_DATA_SET_FACTORY:
        return data.factory_wavelength_cal.wl

    elif factory_or_user == TLCCS_CAL_DATA_SET_USER:
        if not data.user_wavelength_cal.valid:
            raise InvalidUserData
        return data.user_wavelength_cal.wl

    else:
        raise ValueError

def get_wavelength_parameters(dev: usb.core.Device, data: TLCCS_DATA)  -> None:

    data.factory_wavelength_cal.valid = 0
    read_factory_poly(dev, data.factory_wavelength_cal.poly)
    poly_to_wavelength_array(data.factory_wavelength_cal)

    data.user_wavelength_cal.valid = 0
    try:
        read_user_points(dev, data.user_points)
        nodes_to_poly(data.user_points, data.user_wavelength_cal)
        poly_to_wavelength_array(data.user_wavelength_cal)
        data.user_wavelength_cal.valid = 1

    except NoUserDataPoint:
        pass

def get_dark_current_offset(dev: usb.core.Device, data: TLCCS_DATA)  -> None:

    try:
        even_offset_max = read_EEPROM(
            dev,
            address = EE_EVEN_OFFSET_MAX,
            idx = 0,
            length = EE_LENGTH_OFFSET_MAX
        )
        data.even_offset_max = struct.unpack('<H', even_offset_max)[0]

    except EEPROMChecksumError:
        data.even_offset_max = 0xFFFF

    try:
        odd_offset_max = read_EEPROM(
            dev,
            address = EE_ODD_OFFSET_MAX,
            idx = 0,
            length = EE_LENGTH_OFFSET_MAX
        )
        data.odd_offset_max = struct.unpack('<H', odd_offset_max)[0]

    except EEPROMChecksumError:
        data.odd_offset_max = 0xFFFF

def get_firmware_revision(dev: usb.core.Device, firmware_version: TLCCS_VERSION) -> None:
    # TODO

    firmware_version.major    = 0
    firmware_version.minor    = 0
    firmware_version.subminor = 0


def get_hardware_revision(dev: usb.core.Device, hardware_version: TLCCS_VERSION) -> None:
    #TODO

    hardware_version.major    = 0
    hardware_version.minor    = 0
    hardware_version.subminor = 0


def get_amplitude_correction_array(
        dev:               usb.core.Device,
        amplitude_cor_cal: TLCCS_ACOR,
        address:           int
    ) -> None:

    amplitude_cor_bytes = read_EEPROM(
        dev,
        address = address,
        idx     = 0,
        length  = EE_LENGTH_ACOR
    )
    amplitude_cor_data = struct.unpack('<' + 'f'*TLCCS_NUM_PIXELS , amplitude_cor_bytes)
    for i, a in enumerate(amplitude_cor_data):
        amplitude_cor_cal.amplitude_cor[i] = a

    for i in range(TLCCS_NUM_PIXELS):
        if amplitude_cor_cal.amplitude_cor[i] < TLCCS_AMP_CORR_FACT_MIN:
            amplitude_cor_cal.amplitude_cor[i] = TLCCS_AMP_CORR_FACT_MIN

        if amplitude_cor_cal.amplitude_cor[i] > TLCCS_AMP_CORR_FACT_MAX:
            amplitude_cor_cal.amplitude_cor[i] = TLCCS_AMP_CORR_FACT_MAX


def get_amplitude_correction(dev: usb.core.Device, data: TLCCS_DATA) -> None:

    get_amplitude_correction_array(dev, data.factory_amplitude_cal, EE_ACOR_FACTORY)
    get_amplitude_correction_array(dev, data.user_amplitude_cal, EE_ACOR_USER)


def read_factory_poly(dev: usb.core.Device, poly: array.array) -> None:

    data = read_EEPROM(
        dev,
        address = EE_FACT_CAL_COEF_DATA,
        idx     = 0,
        length  = EE_LENGTH_FACT_CAL_COEF_DATA
    )
    poly_coeff = struct.unpack('<' + 'd'*TLCCS_NUM_POLY_POINTS, data)
    for i, coeff in enumerate(poly_coeff):
        poly[i] = coeff

def read_user_points(dev: usb.core.Device, user_points: TLCCS_USER_CAL_PTS) -> None:

    point_count = read_EEPROM(
        dev,
        address = EE_USER_CAL_POINTS_CNT,
        idx     = 0,
        length  = EE_LENGTH_USER_CAL_POINTS_CNT
    )
    cnt = struct.unpack('<H', point_count)[0]

    if cnt == 0xFFFF:
        raise NoUserDataPoint

    point_data = read_EEPROM(
        dev,
        address = EE_USER_CAL_POINTS_DATA,
        idx     = 0,
        length  = EE_LENGTH_USER_CAL_POINTS_DATA
    )

    user_points.user_cal_node_cnt = cnt

    n_bytes_px = cnt*UINT32_SZ
    pixels = struct.unpack('<'+'L'*cnt, point_data[:n_bytes_px])
    for i, px in enumerate(pixels):
        user_points.user_cal_node_pixel[i] = px

    n_bytes_wl = cnt*REAL64_SZ
    wl_start = TLCCS_MAX_NUM_USR_ADJ*UINT32_SZ
    wavelengths = struct.unpack('<'+'d'*cnt, point_data[wl_start:wl_start+n_bytes_wl])
    for i, wl in enumerate(wavelengths):
        user_points.user_cal_node_wl[i] = wl


def nodes_to_poly(user_points: TLCCS_USER_CAL_PTS, user_wavelength_cal: TLCCS_WL_CAL):

    polynomial = np.polyfit(
        user_points.user_cal_node_pixel[:user_points.user_cal_node_cnt],
        user_points.user_cal_node_wl[:user_points.user_cal_node_cnt],
        deg = 3
    )[::-1]

    for i, p in enumerate(polynomial):
        user_wavelength_cal.poly[i] = p

def poly_to_wavelength_array(cal: TLCCS_WL_CAL) -> None:

    direction_flag: int = 0

    for i in range(TLCCS_NUM_PIXELS):
        cal.wl[i] = cal.poly[0] + i * (cal.poly[1] + i * (cal.poly[2] + i * cal.poly[3]))

    if (cal.wl[0] < cal.wl[1]):
        direction_flag = 1
    elif (cal.wl[0] > cal.wl[1]):
        direction_flag = -1
    else:
        raise InvalidUserData

    d = cal.wl[0]
    for i in range(1,TLCCS_NUM_PIXELS):
        if (direction_flag == 1):
            if(cal.wl[i] <= d):
                raise InvalidUserData
        else:
            if(cal.wl[i] <= d):
                raise InvalidUserData
        d = cal.wl[i]

    if (direction_flag == 1):
        cal.min = cal.poly[0]
        cal.max = cal.wl[TLCCS_NUM_PIXELS - 1]
    else:
        cal.min = cal.wl[TLCCS_NUM_PIXELS - 1]
        cal.max = cal.poly[0]


def decode_integration_time(data: array.array, mask: int = 0x0FFF) -> float:

    presc, fill, integ = (val & 0x0FFF for val in struct.unpack('>hhh', data))
    integration_time = (integ - fill + 8) * pow(2.0, presc) / 1_000_000.0
    return integration_time


def encode_integration_time(time_sec: float) -> array.array:

    if not (TLCCS_MIN_INT_TIME<=time_sec<=TLCCS_MAX_INT_TIME):
        raise ValueError('integration time must be between 10us and 60s')

    integ = int(time_sec * 1_000_000)
    integ_max = (4095.0 / (1.0 + 0.01 * SH_PERCENT))
    presc = 0

    while ((integ > integ_max) & (presc < 20)):
        integ >>= 1
        presc += 1

    diff = 0
    if (integ < (TLCCS_NUM_RAW_PIXELS >> presc)):
        diff = (TLCCS_NUM_RAW_PIXELS >> presc) - integ

    fill = int((integ * SH_PERCENT) / 100 + diff)
    integ = integ - 8 + fill
    if (integ > TLCCS_NUM_RAW_PIXELS):
        integ >>= 1
        integ -= 4
        fill >>= 1
        presc += 1

    data = array.array('B')
    data.append((presc & 0xFF00) >> 8)
    data.append(presc & 0x00FF)
    data.append((fill & 0xFF00) >> 8)
    data.append(fill & 0x00FF)
    data.append((integ & 0xFF00) >> 8)
    data.append(integ & 0x00FF)
    data[0] |= 0x00
    data[2] |= 0x10
    data[4] |= 0x20

    return data

def parse_spt(filename):

    records = []
    with open(filename, "rb") as f:
        data = f.read()

    offset = 0
    while offset < len(data):
        # Look for CSPT magic
        if data[offset:offset+4] != b'CSPT':
            offset += 1
            continue

        # Read block length (little endian 4-byte at offset 4)
        block_len = struct.unpack_from("<I", data, offset+4)[0]

        # Sanity check
        if offset + block_len > len(data):
            print(f"Warning: block at {offset} exceeds file length")
            break

        block = data[offset:offset+block_len]

        # Extract fields based on known mapping
        bRequest = block[16]
        wValue   = struct.unpack_from("<H", block, 18)[0]
        wIndex   = struct.unpack_from("<H", block, 20)[0]
        wLength  = struct.unpack_from("<H", block, 28)[0]
        payload  = block[32:32+wLength]

        record = {
            "bRequest": bRequest,
            "wValue": wValue,
            "wIndex": wIndex,
            "wLength": wLength,
            "data": payload
        }
        records.append(record)

        offset += block_len

    return records

def upload_firmware(dev: usb.core.Device, records):

    for i, rec in enumerate(records):
        bmRequestType = 0x40
        try:
            dev.ctrl_transfer(
                bmRequestType,
                rec["bRequest"],
                rec["wValue"],
                rec["wIndex"],
                rec["data"]
            )
        except usb.core.USBError as e:
            print(f"Error sending block {i+1}: {e}")
            break

def dump_eeprom(dev: usb.core.Device) -> array.array:

    eeprom = read_EEPROM_wo_CRC(
        dev,
        address = 0x0000,
        idx = 0x0000,
        length = 0x7FFF
    )
    return eeprom

def hold_cpu(dev: usb.core.Device) -> None:

    dev.ctrl_transfer(
        bmRequestType   = 0x40,
        bRequest        = 0XA0,
        wValue          = 0xE600,
        wIndex          = 0x0000,
        data_or_wLength = [0x01]
    )

def release_cpu(dev: usb.core.Device) -> None:

    dev.ctrl_transfer(
        bmRequestType   = 0x40,
        bRequest        = 0XA0,
        wValue          = 0xE600,
        wIndex          = 0x0000,
        data_or_wLength = [0x00]
    )

def dump_ram(dev: usb.core.Device) -> Tuple[array.array, array.array]:

    hold_cpu(dev)

    program = read_RAM(
        dev,
        address = RAM_PROGRAM_START,
        idx     = 0x0000,
        length  = RAM_PROGRAM_SIZE
    )

    data = read_RAM(
        dev,
        address = RAM_DATA_START,
        idx     = 0x0000,
        length  = RAM_DATA_SIZE
    )

    release_cpu(dev)

    return program, data

def reset_device(dev: usb.core.Device):

    dev.ctrl_transfer(
        bmRequestType   = 0x40,
        bRequest        = TLCCS_WCMD_RESET,
        wValue          = 0x0000,
        wIndex          = 0x0000,
        data_or_wLength = 0
    )


def wait_for_device(
        idVendor:     int,
        idProduct:    int,
        port_numbers: Tuple,
        timeout:      float = DEFAULT_RENUMERATION_TIMEOUT
    ) -> usb.core.Device:

    start = time.time()
    while time.time() - start < timeout:
        dev = usb.core.find(
            idVendor = idVendor,
            idProduct = idProduct,
            backend = libusb_backend,
            custom_match = lambda d: d.port_numbers == port_numbers
        )
        if dev is not None:
            return dev

        time.sleep(0.1)

    raise RenumerationFailed(f"Device {idVendor:04x}:{idProduct:04x} not found after {timeout}s")


def renumerate(
        PID:           int,
        port_numbers:  Tuple,
        firmware_file: str
    ) -> usb.core.Device:

    dev = usb.core.find(
        idVendor     = THORLABS_VID,
        idProduct    = PID,
        backend      = libusb_backend,
        custom_match = lambda d: d.port_numbers == port_numbers
    )

    if dev is None:
        raise DeviceNotFound

    firmware = parse_spt(firmware_file)
    print('Uploading firmware...')
    dev.set_configuration()
    upload_firmware(dev, firmware)
    new_dev = wait_for_device(
        THORLABS_VID,
        PID+1,
        port_numbers
    )
    return new_dev


class DevInfo(NamedTuple):
    vid:           int
    pid:           int
    serial_number: str


DEFAULT_FIRMWARE_PATH = Path(str(files("lab_instruments").joinpath('ccs_firmware')))
#DEFAULT_FIRMWARE_PATH = Path(__file__).parent / 'ccs_firmware'
DEFAULT_FIRMWARE_FILE = {
    CCS100_PID_U: DEFAULT_FIRMWARE_PATH / 'CCS100.spt',
    CCS125_PID_U: DEFAULT_FIRMWARE_PATH / 'CCS125.spt',
    CCS150_PID_U: DEFAULT_FIRMWARE_PATH / 'CCS150.spt',
    CCS175_PID_U: DEFAULT_FIRMWARE_PATH / 'CCS175.spt',
    CCS200_PID_U: DEFAULT_FIRMWARE_PATH / 'CCS200.spt',
}

def list_spectrometers(pid_firmware_map: Dict[int, Path] = DEFAULT_FIRMWARE_FILE) -> List[DevInfo]:
    '''list spectrometers in the CCS family. Uploads firmware if necessary'''

    devices = usb.core.find(
        idVendor     = THORLABS_VID,
        backend      = libusb_backend,
        custom_match = lambda d: d.idProduct in range(*PID_RANGE),
        find_all     = True
    )

    res = []
    for dev in devices:

        # device already initialized
        if dev.idProduct & 1:
            res.append(DevInfo(
                vid           = dev.idVendor,
                pid           = dev.idProduct,
                serial_number = dev.serial_number
            ))

        # need to upload firmware
        else:
            port_numbers = dev.port_numbers
            new_dev = renumerate(
                PID           = dev.idProduct,
                firmware_file = pid_firmware_map[dev.idProduct],
                port_numbers  = port_numbers
                )
            res.append(DevInfo(
                vid           = new_dev.idVendor,
                pid           = new_dev.idProduct,
                serial_number = new_dev.serial_number
            ))

    return res

class TLCCS:

    def __init__(
            self,
            device_info: DevInfo
        ):

        self.dev = usb.core.find(
            idVendor     = device_info.vid,
            idProduct    = device_info.pid,
            backend      = libusb_backend,
            custom_match = lambda d: d.serial_number == device_info.serial_number,
        )

        if self.dev is None:
            raise DeviceNotFound

        self.dev.set_configuration()
        self.dev.reset()

        self.data = TLCCS_DATA()
        initialize(self.dev, self.data)

    def get_wavelength(self, factory_or_user: int = TLCCS_CAL_DATA_SET_FACTORY) -> array.array:
        return get_wavelength(self.data, factory_or_user)

    def start_single_scan(self):
        start_single_scan(self.dev)

    def start_continuous_scan(self):
        start_continuous_scan(self.dev)

    def set_integration_time(self, integration_time: float):
        set_integration_time(self.dev, integration_time)

    def get_integration_time(self) -> float:
        return get_integration_time(self.dev)

    def get_scan_data_factory(self) -> array.array:
        status = 0x0000
        while (status & TLCCS_STATUS_SCAN_TRANSFER) == 0:
            status = get_device_status(self.dev)
        return get_scan_data_factory(self.dev, self.data)

    def get_scan_data_corrected_range(
            self,
            min_wl: float = 321.45,
            max_wl: float = 742.11
        ) -> Tuple[array.array, float]:

        status = 0x0000
        while (status & TLCCS_STATUS_SCAN_TRANSFER) == 0:
            status = get_device_status(self.dev)

        return get_scan_data_corrected_range(
            self.dev,
            self.data,
            min_wl = min_wl,
            max_wl = max_wl
        )

    def get_scan_data_corrected_noise(
            self,
            center_wl:              float = 531.78,
            noise_amplification_dB: float = 1.0
        ) -> Tuple[array.array, float, float]:

        status = 0x0000
        while (status & TLCCS_STATUS_SCAN_TRANSFER) == 0:
            status = get_device_status(self.dev)

        return get_scan_data_corrected_noise(
            self.dev,
            self.data,
            center_wl              = center_wl,
            noise_amplification_dB = noise_amplification_dB
        )

    def close(self):
        self.reset()
        usb.util.dispose_resources(self.dev)
        self.dev = None
        self.data = None

    def reset(self):
        reset_device(self.dev)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

# Decorator to dynamically add methods from TLCCS to Spectrometer
def compose_methods_from_tlccs(cls):
    for name, method in inspect.getmembers(TLCCS, predicate=inspect.isfunction):
        if not hasattr(cls, name):  # Avoid overwriting existing methods
            setattr(cls, name, lambda self, *args, **kwargs: getattr(self.tlccs, name)(*args, **kwargs))
    return cls

@compose_methods_from_tlccs
class Spectrometer:
    tlccs: Union[TLCCS, None] = None
    h5_dict = {}
    wavelengths: array.array = array.array('f4')

    def __init__(self, h5_instrument=None):
        ccs_devices = list_spectrometers()
        if len(ccs_devices) == 0:
            raise DeviceNotFound("No CCS spectrometer found")
        if len(ccs_devices) > 1:
            warning("Multiple CCS spectrometers found, using the first one")
        self.tlccs = TLCCS(ccs_devices[0])
        if h5_instrument is not None:
            self.h5_instrument = h5_instrument
            self.hdf5_describe(h5_instrument)

    def hdf5_describe(self, h5_instrument: h5py.Group):
        # Extract device wavelengths
        if self.tlccs is None:
            raise RuntimeError("TLCCS instance is not initialized")
        self.wavelengths: array.array = self.tlccs.get_wavelength()

        spectrometer_inst = h5_instrument.create_group("spectrometer")
        spectrometer_inst.attrs['NX_class'] = "NXinstrument" # https://manual.nexusformat.org/classes/base_classes/NXsource.html#index-0
        spectrometer_inst.create_dataset("name", data="Thorlabs CCS100-CCS200 Spectrometer")
        spectrometer_inst.create_dataset("type", data="Spectrometer")
        spectrometer_inst.create_dataset("manufacturer", data="Thorlabs")

        spectrometer_datasheet = spectrometer_inst.create_group("specs")
        spectrometer_datasheet.attrs['NX_class'] = 'NXtechnical_data'
        spectrometer_datasheet.create_dataset("datasheet", data="https://www.thorlabs.com/thorproduct.cfm?partnumber=CCS200")

        data = spectrometer_inst.create_group("data")
        data.attrs['NX_class'] = 'NXdata'
        data.attrs['description'] = 'Measured normalized spectrum'
        data.attrs['axes'] = ['intensity:wavelengths']

        wavelengths_ds = data.create_dataset("wavelengths", data=self.wavelengths)
        wavelengths_ds.attrs['units'] = "nm"
        wavelengths_ds.attrs['name'] = "Wavelength"
        wavelengths_ds.attrs['axes'] = "λ"

        intensity_ds = data.create_dataset("intensity", shape=(len(self.wavelengths),), dtype='f4')
        intensity_ds.attrs['units'] = ""
        intensity_ds.attrs['name'] = "Normalized intensity"
        intensity_ds.attrs['axes'] = "Φ"

        self.h5_dict['instrument'] = h5_instrument
        self.h5_dict['spectrometer'] = spectrometer_inst
        self.h5_dict['data'] = data

    def scan_specturm(self, integration_time=5):
        if self.tlccs is None:
            raise DeviceNotFound("Spectrometer not initialized")
        self.tlccs.set_integration_time(integration_time) # in seconds
        self.tlccs.start_single_scan()
        spectrum = self.tlccs.get_scan_data_factory()
        if 'data' in self.h5_dict:
            data_group = self.h5_dict['data']
            intensity_ds = data_group['intensity']
            intensity_ds[:] = spectrum
        return spectrum

