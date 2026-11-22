"""
TestSphere-AI — Database Package.

Document storage (Firestore in production) behind the ``Store`` interface.
"""

from backend.database.session import get_db, get_store, init_db, set_store
from backend.database.store import Record, Store, StoreUnavailableError

__all__ = ["get_db", "get_store", "init_db", "set_store", "Record", "Store", "StoreUnavailableError"]
