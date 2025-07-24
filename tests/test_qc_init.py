import os
from lab_instruments import jl as qc_jl

def test_qc_init():
    qc_jl.seval('using QuantiCam')
    here_dir = os.path.dirname(__file__)
    fw_path = os.path.join(here_dir, 'qc_extras', 'photon_cnt_tcspc_xem7310-a200_v1.7.bit')
    config_path = os.path.join(here_dir, 'qc_extras', 'tcspc.json')
    qc = qc_jl.QCBoard(fw_path, config_path)
