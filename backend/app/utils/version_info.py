"""Collect software version metadata for traceability records."""
import importlib
import sys


def get_version(package: str) -> str:
    try:
        mod = importlib.import_module(package)
        return getattr(mod, "__version__", "unknown")
    except ImportError:
        return "not-installed"


_CACHED_VERSIONS = None


def _collect_versions_impl() -> dict:
    packages = {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "fastapi": get_version("fastapi"),
        "pydantic": get_version("pydantic"),
        "sqlalchemy": get_version("sqlalchemy"),
        "numpy": get_version("numpy"),
        "trimesh": get_version("trimesh"),
        "scipy": get_version("scipy"),
    }
    # Try cadquery
    try:
        import cadquery as cq
        packages["cadquery"] = getattr(cq, "__version__", "installed")
    except ImportError:
        packages["cadquery"] = "not-installed"
    return packages


def collect_versions() -> dict:
    """Return a dict of key dependency versions (cached)."""
    global _CACHED_VERSIONS
    if _CACHED_VERSIONS is None:
        _CACHED_VERSIONS = _collect_versions_impl()
    return dict(_CACHED_VERSIONS)
