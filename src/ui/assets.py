from functools import lru_cache

from PyQt5.QtGui import QIcon

from src.core.utils import asset_path


@lru_cache(maxsize=None)
def app_icon() -> QIcon:
    """Shared application icon (geforce.ico).

    Created on first call, so only call it once a QApplication exists.
    """
    return QIcon(str(asset_path("geforce.ico")))
