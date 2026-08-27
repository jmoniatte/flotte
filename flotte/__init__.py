from importlib.metadata import version, PackageNotFoundError

REPOSITORY_URL = "https://github.com/jmoniatte/flotte"

try:
    __version__ = version("flotte")
except PackageNotFoundError:
    __version__ = "0.0.0"
