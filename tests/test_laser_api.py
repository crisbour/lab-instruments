import pytest
from logging import info, warning, debug, error
import logging
from time import sleep

from lab_instruments import laser as pq

def test_laser_creation():
    try:
        info("Initialise the laser")
        laser = pq.PrimaController()
        sleep(1)
        info("Set laser in NarrowPulse mode")
        laser.set_mode(pq.PrimaMode.NarrowPulse)
        laser.set_power(0)
    except Exception as e:
        print(f"gRPC call failed: {e}")

