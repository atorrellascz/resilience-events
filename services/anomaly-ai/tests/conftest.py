# conftest.py — loaded by pytest BEFORE any test module in this folder.
#
# The app's db.py reads DATABASE_URL at import time and fails fast if it's
# missing. Unit tests never touch a real database (they use fakes), but
# importing the service still triggers that import chain. We set a dummy URL so
# the module loads cleanly; no real connection is ever opened (the engine is
# created lazily and our fakes bypass it entirely).
import os

os.environ.setdefault("DATABASE_URL", "mysql+aiomysql://test:test@localhost/test")