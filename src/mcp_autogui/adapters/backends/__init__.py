"""Registration of bundled desktop-specific implementations."""

from ...desktop_backend import register_desktop_backend
from . import treeland_deepin, x11_deepin


def register_builtin_backends() -> None:
    register_desktop_backend(treeland_deepin.BACKEND_ID, treeland_deepin.create_backend)
    register_desktop_backend(x11_deepin.BACKEND_ID, x11_deepin.create_backend)
