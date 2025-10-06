import os
from importlib.resources import files

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

# Following is to use git root as the path that contains Julia dependency and lock files
#git_root = get_git_root(os.path.dirname(__file__))
#if git_root:
#    os.environ["JULIA_PROJECT"] = git_root

# Locate the directory containing Project.toml and Manifest.toml
julia_toml_path = files("lab_instruments")

# Set JULIA_PROJECT environment variable
os.environ["JULIA_PROJECT"] = str(julia_toml_path)

print("JULIA_PROJECT set to:", os.environ["JULIA_PROJECT"])

os.environ["PYTHON_JULIAPKG_PROJECT"] = os.path.abspath("./julia_env")
from juliacall import Main as jl

# Run Pkg.instantiate() and Pkg.resolve()
jl.seval(f'using Pkg; Pkg.activate("{julia_toml_path}")')
jl.seval("using Pkg")
jl.seval("Pkg.instantiate()")
#jl.seval("Pkg.resolve()")

jl.seval('using QuantiCam')
jl.seval('using Serde')

__all__ = ["jl"]
