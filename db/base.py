"""
Declarative base shared by every model in db/models.py.

Every ORM class inherits from this. Keeping it in its own file (rather than
defining it inside models.py) avoids circular imports later when scripts/
or ml/ need to import Base without pulling in the full model graph.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
