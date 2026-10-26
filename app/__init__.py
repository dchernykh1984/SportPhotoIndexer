"""SportPhotoIndexer: indexes a folder of race photos by bib for the cycling site."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version


def version() -> str:
    try:
        return _dist_version("sport-photo-indexer")
    except PackageNotFoundError:  # a frozen build carries no package metadata
        return "frozen"
