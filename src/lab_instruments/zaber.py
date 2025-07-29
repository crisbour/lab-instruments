from zaber_motion import Units
from zaber_motion.ascii import Connection
import serial.tools.list_ports

from logging import info

class ZaberStage:
    """A class to control the Zaber stage."""
    abs_pos = 0.0  # Zero value at absolute position of the stage
    rel_pos = 0.0  # Relative position of the stage to the zero position
    connection = None
    port = '/dev/ttyUSB1'  # Default port for the Zaber stage
    VID = 0x0403  # substitute with your device's VID
    PID = 0x6001  # substitute with your device's PID
    def __init__(self, port=None):
        if port:
            self.port = port
        else:
            self.port = self._find_serial_port(self.VID, self.PID)

        if not self.port:
            raise ValueError(f"Zaber stage not found on port {self.port}.")
        connection = Connection.open_serial_port(self.port)
        device_list = connection.detect_devices()
        info("Found {} devices".format(len(device_list)))
        device = device_list[0]
        # Initialize the Zaber stage here
        axis = device.get_axis(1)
        if not axis.is_homed():
          axis.home()

        self.connection = connection
        self.device = device
        self.axis = axis

    def _find_serial_port(self, vid, pid):
        vid_hex = format(vid, '04x')
        pid_hex = format(pid, '04x')
        for port in serial.tools.list_ports.comports():
            if (hasattr(port, 'vid') and hasattr(port, 'pid') and
                port.vid is not None and port.pid is not None):
                if port.vid == vid and port.pid == pid:
                    return port.device
            # Some environments, check 'hwid' string too:
            if port.hwid:
                if vid_hex in port.hwid.lower() and pid_hex in port.hwid.lower():
                    return port.device
        return None

    def zero(self, position):
        """Move the stage to a specified position and zero there."""
        # Move to 10mm
        info(f"Linear stage zero at {position} mm absolute distance")
        self.abs_pos = position  # Initial absolute position in mm
        self.axis.move_absolute(self.abs_pos, Units.LENGTH_MILLIMETRES)
        self.rel_pos = 0.0

    def move(self, new_rel_pos):
        """Move the stage to a position relative to zero position."""
        delta_x = new_rel_pos - self.rel_pos
        self.rel_pos = new_rel_pos
        info(f"Move linear stage by {delta_x} mm to (x-x_0) = {new_rel_pos} mm")
        self.axis.move_relative(delta_x, Units.LENGTH_MILLIMETRES)

    def __del__(self):
        """Close the connection when the object is deleted."""
        if self.connection:
            self.connection.close()
            info("Zaber stage connection closed.")
        else:
            info("No Zaber stage connection to close.")


