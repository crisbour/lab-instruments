import pyvisa
from enum import Enum, unique
from logging import info, warning, debug, error
import h5py

# | Command                         | Page | Description                           |
# | :---------------                | :--- | :---------------------------------    |
# | **Common IEEE-488.2 Commands**  |      |                                       |
# | `*CAL?`                         | 48   | Run auto calibration routine          |
# | `*CLS`                          | 48   | Clear Status                          |
# | `*ESE(?){i}`                    | 48   | Standard Event Status Enable          |
# | `*ESR?`                         | 48   | Standard Event Status Register        |
# | `*IDN?`                         | 48   | Identification String                 |
# | `*OPC(?)`                       | 48   | Operation Complete                    |
# | `*PSC(?){i}`                    | 49   | Power-on Status Clear                 |
# | `*RCL i`                        | 49   | Recall Instrument Settings            |
# | `*RST`                          | 49   | Reset the Instrument                  |
# | `*SAV i`                        | 49   | Save Instrument Settings              |
# | `*SRE(?){i}`                    | 49   | Service Request Enable                |
# | `*STB?`                         | 49   | Status Byte                           |
# | `*TRG`                          | 50   | Trigger a delay                       |
# | `*TST?`                         | 50   | Self Test                             |
# | `*WAI`                          | 50   | Wait for Command Execution            |
# | **Status and Display Commands** |      |                                       |
# | `DISP(?){i,c}`                  | 50   | Display                               |
# | `INSE(?){i}`                    | 51   | Instrument Status Enable              |
# | `INSR?`                         | 51   | Instrument Status Register            |
# | `LERR?`                         | 51   | Last Error                            |
# | `SHDP?{i}`                      | 51   | Show Display                          |
# | `TIMB?`                         | 51   | Timebase                              |
# | **Trigger Commands**            |      |                                       |
# | `ADVT(?){i}`                    | 52   | Advanced Triggering Enable            |
# | `HOLD?{t}`                      | 52   | Holdoff                               |
# | `INHB(?){i}`                    | 52   | Inhibit                               |
# | `PHAS(?)i{,j}`                  | 52   | Prescale Phase Factor                 |
# | `PRES(?)i{,j}`                  | 52   | Prescale Factor                       |
# | `SPHD i`                        | 53   | Step Holdoff                          |
# | `SPPH i,j`                      | 53   | Step Prescale Phase Factor            |
# | `SPPS i,j`                      | 53   | Step Prescale Factor                  |
# | `SPTL i`                        | 53   | Step Trigger Level                    |
# | `SPTR i`                        | 53   | Step Trigger Rate                     |
# | `SSHD(?){t}`                    | 54   | Step Size Holdoff                     |
# | `SSPH(?)i{,j}`                  | 54   | Step Size Prescale Shift Factor       |
# | `SSPS(?)i{,j}`                  | 54   | Step Size Prescale Factor             |
# | `SSTL(?){v}`                    | 54   | Step Size Trigger Level               |
# | `SSTR(?){f}`                    | 54   | Step Size Trigger Rate                |
# | `TLVL(?){v}`                    | 54   | Trigger Level                         |
# | `TRAT(?){f}`                    | 54   | Trigger Rate                          |
# | `TSRC(?){i}`                    | 54   | Trigger Source                        |
# | **Burst Commands**              |      |                                       |
# | `BURC(?){i}`                    | 55   | Burst Count                           |
# | `BURD(?){t}`                    | 55   | Burst Delay                           |
# | `BURM(?){i}`                    | 55   | Burst Mode                            |
# | `BURP(?){t}`                    | 55   | Burst Period                          |
# | `BURT(?){i}`                    | 55   | Burst Type Configuration              |
# | `SPBC i`                        | 55   | Step Burst Count                      |
# | `SPBD i`                        | 55   | Step Burst Delay                      |
# | `SPBP i`                        | 55   | Step Burst Period                     |
# | `SSBC(?){i}`                    | 55   | Step Size Burst Count                 |
# | `SSBD(?){t}`                    | 55   | Step Size Burst Delay                 |
# | `SSBP(?){t}`                    | 55   | Step Size Burst Period                |
# | **Delay and Output Commands**   |      |                                       |
# | `DLAY(?)c{,d,t}`                | 56   | Delay                                 |
# | `LAMP(?)b{,v}`                  | 56   | Level Amplitude                       |
# | `LINK(?)c{,d}`                  | 56   | Link Channel                          |
# | `LOFFE(?)b{,v}`                 | 57   | Level Offset                          |
# | `LPOL(?)b{,i}`                  | 57   | Level Polarity                        |
# | `SPDL c,i`                      | 57   | Step Delay                            |
# | `SPLA b,i`                      | 57   | Step Level Amplitude                  |
# | `SPLO b,i`                      | 57   | Step Level Offset                     |
# | `SSDL(?)c{,f}`                  | 57   | Step Size Delay                       |
# | `SSLA(?)b{,v}`                  | 57   | Step Size Level Amplitude             |
# | `SSLO(?)b{,v}`                  | 57   | Step Size Level Offset                |
# | **Interface Commands**          |      |                                       |
# | `EMAC?`                         | 57   | Ethernet Mac Address                  |
# | `EPHY(?)i{,j}`                  | 57   | Ethernet Physical Layer Configuration |
# | `IFCE(?)i{,j}`                  | 58   | Interface Configuration               |
# | `IFRS i`                        | 58   | Interface Reset                       |
# | `LCAL`                          | 59   | Go to Local                           |
# | `LOCK?`                         | 59   | Request Lock                          |
# | `REMT`                          | 59   | Go to Remote                          |
# | `UNLK?`                         | 59   | Release Lock                          |
# | `XTRM i{,j,k}`                  | 59   | Interface Terminator                  |

# Commands parameter convention
# -----------------------------
#
# | Parameter | Description                                        |
# |:----------|:---------------------------------------------------|
# | i, j, k   | Integer value                                      |
# | f         | Floating point value representing frequency in Hz  |
# | t         | Floating point value representing time in seconds  |
# | v         | Floating point value representing voltage in Volts |

class StandardEventStatus(Enum):
    OperationComplete     = 0
    Reserved              = 1
    QuerryError           = 2
    DeviceDependentError  = 3
    ExecutionError        = 4
    CommandError          = 5
    Reserved2             = 6
    PowerOn               = 7

class StatusByte(Enum):
    INSRSummary           = 0
    Busy                  = 1
    Burst                 = 2
    Reserved              = 3
    MessageAvailable      = 4
    EventStatusSummary    = 5
    MasterSummary         = 6
    Reserved2             = 7

class DisplayMode(Enum):
    TriggerRate           = 0
    TriggerThreshold      = 1
    TriggerSingleShot     = 2
    TriggerLine           = 3
    AdvancedTriggering    = 4
    TriggerHoloff         = 5
    Prescale              = 6
    BurstMode             = 7
    BurstDelay            = 8
    BurstCount            = 9
    BurstPeriod           = 10
    ChannelDelay          = 11
    ChannelOutputLevel    = 12
    ChannelOutputPolarity = 13
    BurstT0Config         = 14

class InstrumentStatus(Enum):
    Trig                  = 0 # Got a trigger,
    Rate                  = 1 # Got a trigger while a delay or burst was in progress
    EndOfDelay            = 2 # Delay finished
    EndOfBurst            = 3 # Burst finished
    Inhibit               = 4 # A trigger or output delay was inhibited
    AbortDelay            = 5 # Adelay cycle was aborted early
    PLLUnlock             = 6 # The 100MHz PLL came unlocked
    RBUnlock              = 7 # The installed RB oscillator is unlocked

class Timebase(Enum):
    Internal              = 0
    OCXO                  = 1
    Rubidium              = 2
    External              = 3

class Inhibit(Enum):
    Off                   = 0
    Triggers              = 1
    AB                    = 2
    AB_CD                 = 3
    AB_CD_EF              = 4
    AB_CD_EF_GH           = 5

class PrescalePhaseFactor(Enum):
    OutputAB              = 1
    OutputCD              = 2
    OutputEF              = 3
    OutputGH              = 4

class PrescaleFactor(Enum):
    TriggerInput          = 0
    OutputAB              = 1
    OutputCD              = 2
    OutputEF              = 3
    OutputGH              = 4

class StepPrescalePhase(Enum):
    OutputAB              = 1
    OutputCD              = 2
    OutputEF              = 3
    OutputGH              = 4

class StepPrescaleFactor(Enum):
    TriggerInput          = 0
    OutputAB              = 1
    OutputCD              = 2
    OutputEF              = 3
    OutputGH              = 4

class TriggerSource(Enum):
    Internal              = 0
    ExternalRising        = 1
    ExternalFalling       = 2
    SingleExternalRising  = 3
    SingleExternalFalling = 4
    Single                = 5
    Line                  = 6

class DelayOutput(Enum):
    TriggerInput          = 0
    OutputAB              = 1
    OutputCD              = 2
    OutputEF              = 3
    OutputGH              = 4

class DelayChannel(Enum):
    T0                    = 0
    T1                    = 1
    A                     = 2
    B                     = 3
    C                     = 4
    D                     = 5
    E                     = 6
    F                     = 7
    G                     = 8
    H                     = 9

class InterfaceConfig(Enum):
    SerialEnable          = 0
    SerialBaudRate        = 1
    GpibEnable            = 2
    GpibAddress           = 3
    LanTcpIpEnable        = 4
    DhcpEnable            = 5
    AutoIpEnable          = 6
    StaticIpEnable        = 7
    BareSocketEnable      = 8
    TelnetEnable          = 9
    VXI11InstrumentEnable = 10
    StaticIpAddress       = 11
    SubnteAddressMask     = 12
    DefaultGateway        = 13

class InterfaceReset(Enum):
    Serial                = 0
    Gpib                  = 1
    LanTcpIp              = 2

@unique
class ErrorCode(Enum):
    """
    Error codes for the DG645 Digital Delay Generator, as defined in the
    Remote Programming Manual.
    """
    # No error has occurred.
    NO_ERROR                = 0  # No error

    # Device-specific Errors (10-17)
    DEVICE_DEPENDENT_ERROR  = 10 # Device dependent error; see specific command for more details.
    FILE_SYSTEM_ERROR       = 11 # File system error
    INVALID_FILE_NAME       = 12 # Invalid file name
    FILE_NOT_FOUND          = 13 # File not found
    DISK_FULL               = 14 # Disk full
    DIRECTORY_NOT_FOUND     = 15 # Directory not found
    RECALL_FAILED           = 16 # Recall failed
    EXE_FAIL_AUTO_CAL       = 17 # Auto-calibration failed

    # Trigger-Related Errors (30-32)
    INVALID_TRIGGER_SOURCE  = 30 # Invalid trigger source
    INVALID_TRIGGER_MODE    = 31 # Invalid trigger mode
    TRIGGER_ERROR           = 32 # Trigger error

    # Channel/Delay Related Errors (40-91)
    INVALID_CHANNEL_CONFIG  = 40 # Invalid channel configuration
    INVALID_DELAY           = 41 # Invalid delay
    INVALID_OUTPUT_LEVEL    = 42 # Invalid output level
    OUTPUT_OVERLOAD         = 43 # Output overload
    INVALID_POLARITY        = 44 # Invalid polarity
    INVALID_OFFSET          = 45 # Invalid offset
    INVALID_AMPLITUDE       = 46 # Invalid amplitude
    INVALID_WIDTH           = 47 # Invalid width
    INVALID_DUTY_CYCLE      = 48 # Invalid duty cycle
    INVALID_TRANSITION_TIME = 49 # Invalid transition time
    INVALID_JITTER          = 50 # Invalid jitter
    INVALID_RESOLUTION      = 51 # Invalid resolution
    INVALID_SKEW            = 52 # Invalid skew
    INVALID_PHASE           = 53 # Invalid phase
    INVALID_PERIOD          = 54 # Invalid period
    INVALID_FREQUENCY       = 55 # Invalid frequency
    INVALID_TIMEBASE        = 56 # Invalid timebase
    INVALID_COUPLING        = 57 # Invalid coupling
    INVALID_IMPEDANCE       = 58 # Invalid impedance
    INVALID_TERMINATION     = 59 # Invalid termination
    INVALID_FILTER          = 60 # Invalid filter
    INVALID_CALIBRATION     = 61 # Invalid calibration
    INVALID_TEMPERATURE     = 62 # Invalid temperature
    INVALID_VOLTAGE         = 63 # Invalid voltage
    INVALID_CURRENT         = 64 # Invalid current
    INVALID_POWER           = 65 # Invalid power
    INVALID_RESISTANCE      = 66 # Invalid resistance
    INVALID_CAPACITANCE     = 67 # Invalid capacitance
    INVALID_INDUCTANCE      = 68 # Invalid inductance
    INVALID_TIME            = 69 # Invalid time
    INVALID_DATE            = 70 # Invalid date
    INVALID_FORMAT          = 71 # Invalid format
    INVALID_UNITS           = 72 # Invalid units
    INVALID_SCALE           = 73 # Invalid scale
    INVALID_RANGE           = 74 # Invalid range
    INVALID_LIMIT           = 75 # Invalid limit
    INVALID_TOLERANCE       = 76 # Invalid tolerance
    INVALID_RESOLUTION_2    = 77 # Invalid resolution
    INVALID_SENSITIVITY     = 78 # Invalid sensitivity
    INVALID_HYSTERESIS      = 79 # Invalid hysteresis
    INVALID_THRESHOLD       = 80 # Invalid threshold
    INVALID_BANDWIDTH       = 81 # Invalid bandwidth
    INVALID_RISE_TIME       = 82 # Invalid rise time
    INVALID_FALL_TIME       = 83 # Invalid fall time
    INVALID_OVERSHOOT       = 84 # Invalid overshoot
    INVALID_UNDERSHOOT      = 85 # Invalid undershoot
    INVALID_DROOP           = 86 # Invalid droop
    INVALID_SETTLING_TIME   = 87 # Invalid settling time
    INVALID_SLEW_RATE       = 88 # Invalid slew rate
    INVALID_LINEARITY       = 89 # Invalid linearity
    INVALID_ACCURACY        = 90 # Invalid accuracy
    INVALID_STABILITY       = 91 # Invalid stability

    # Interface-Related Errors (110-126)
    INVALID_INTERFACE       = 110  # Invalid interface
    INVALID_ADDRESS         = 111  # Invalid address
    INVALID_BAUD_RATE       = 112  # Invalid baud rate
    INVALID_PARITY          = 113  # Invalid parity
    INVALID_DATA_BITS       = 114  # Invalid data bits
    INVALID_STOP_BITS       = 115  # Invalid stop bits
    INVALID_FLOW_CONTROL    = 116  # Invalid flow control
    INVALID_TERMINATOR      = 117  # Invalid terminator
    INVALID_PROTOCOL        = 118  # Invalid protocol
    INVALID_PORT            = 119  # Invalid port
    INVALID_IP_ADDRESS      = 120  # Invalid IP address
    INVALID_SUBNET_MASK     = 121  # Invalid subnet mask
    INVALID_GATEWAY         = 122  # Invalid gateway
    INVALID_DNS             = 123  # Invalid DNS
    INVALID_MAC_ADDRESS     = 124  # Invalid MAC address
    INVALID_DHCP            = 125  # Invalid DHCP
    INVALID_AUTO_IP         = 126  # Invalid Auto IP

    # Memory-Related Errors (170-171)
    MEMORY_ERROR            = 170  # Memory error
    MEMORY_FULL             = 171  # Memory full

    # Reserved Error (254)
    RESERVED_ERROR          = 254  # Reserved error


class DG645:

    def __init__(self, h5_instrument=None, rm=None, ip=None, port=None, trig_lvl=1.3):
        if ip is None:
            ip = "192.168.88.110"
            warning(f"No IP provided, using default {ip}")
        if port is None:
            port = 5025
            warning(f"No port provided, using default {port}")
        if rm is None:
            rm = pyvisa.ResourceManager()
            warning("No resource manager provided, creating a new one.")
        self.rm = rm
        self.ip = ip
        self.port = port
        self.delay_gen = rm.open_resource(
            f'TCPIP0::{ip}::{port}::SOCKET',
            write_termination='\n',
            read_termination='\r\n')
        idn = self.delay_gen.query('*IDN?')
        info(f"Delay generator initialized at {ip}:{port} is: {idn}")
        self.init_dg645(trig_lvl)
        self.h5_instrument = h5_instrument
        if self.h5_instrument is not None:
            self.hdf5_describe(self.h5_instrument)

    def hdf5_describe(self, h5_instrument: h5py.Group):
        dg_instrument = h5_instrument.create_group("delay_gen_instrument")
        dg_instrument.create_dataset("name", data="Stanford DG645 Delay Generator")
        dg_instrument.attrs['NX_class'] = "NXinstrument" # https://manual.nexusformat.org/classes/base_classes/NXinstrument.html#index-0

    def get_resource_manager(self):
        return self.rm

    def get_error(self) -> ErrorCode:
        return ErrorCode(int(self.delay_gen.query('LERR?')))  # Read the error status register

    def read_errors(self) -> bool:
        err = self.get_error()
        any_error = False
        while err != ErrorCode.NO_ERROR:
            any_error = True
            error(f"Error {err} occurred.")
            err = self.get_error()
        return any_error

    def init_dg645(self, trig_lvl):
        self.delay_gen.write('*RST')  # Reset the delay generator
        self.delay_gen.write('*CLS')  # Clear the delay generator
        self.read_errors()
        self.delay_gen.write(f'TLVL {round(trig_lvl, 1)}') # set trig level with only one decimal place
        self.read_errors()
        self.delay_gen.write(f'TSRC {TriggerSource.ExternalFalling.value}')  # Set trigger slope to positive
        self.delay_gen.write(f'DLAY {DelayChannel.A.value},{DelayChannel.T0.value},0') # Set A = T0 + 0
        self.read_errors()
        # NOTE: Setting 20ns A->B in here to give us enough margin to not hit the next trigger
        self.delay_gen.write(f'DLAY {DelayChannel.B.value},{DelayChannel.A.value},20e-9') # Set B = A + 50ns
        self.read_errors()

        if self.delay_gen.query('*OPC?') is None:
            warning('DG645 seems to be not responding to *OPC? query')

    def config(self, config):
        """
        Configure the delay generator with a sequence of SCPI commands after each erros will be checked
        """
        for cmd in config.split('\n'):
            self.delay_gen.write(cmd)
            self.read_errors()

        info('Check operation completed: {}', self.delay_gen.query('*OPC?'))

    def set_delay(self, delay: float):
        # Write float in the format 2.4e-4
        self.delay_gen.write(f'DLAY {DelayChannel.A.value},{DelayChannel.T0.value},{delay:.6e}')
        # TODO:
        #self.record_h5_delay(delay)
        self.read_errors()
