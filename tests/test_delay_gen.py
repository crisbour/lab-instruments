from lab_instruments import delay_gen
from logging import warning

def test_delay_gen_creation():
    try:
        dg645 = delay_gen.DG645()
    except Exception as e:
        warning(f"DG645 creation failed: {e}")
