import os

os.path.dirname(__file__)

def get_git_root(path=None):
    if path is None:
        path = os.getcwd()
    while True:
        if os.path.exists(os.path.join(path, ".git")):
            return path
        parent = os.path.dirname(path)
        if parent == path:  # reached root of filesystem
            return None
        path = parent


os.environ["PYTHON_JULIAPKG_PROJECT"] = os.path.abspath("./julia_env")
from juliacall import Main as jl, convert as jlconvert

git_root = get_git_root(os.path.dirname(__file__))
if git_root:
    os.environ["JULIA_PROJECT"] = git_root

jl.seval('using QuantiCam')
jl.seval('using Serde')
