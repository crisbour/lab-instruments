from lab_instruments import power_meter
from logging import info

def test_pm400_creation():
    try:
        pm400 = power_meter.PowerMeter()
    except power_meter.PM400Error as e:
        info(f"PM400Error: {e}")
    except ValueError as e:
        info(f"PM400 not connected: {e}")
    except Exception as e:
        raise e

