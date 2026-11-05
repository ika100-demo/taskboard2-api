"""Request and response schemas for the tasks API."""

import datetime
import re
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints

Title = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200),
]

_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse_due_date(value: object) -> datetime.date | None:
    """Parse a strict YYYY-MM-DD string; ``None`` stays ``None``."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("due_date must be a string in YYYY-MM-DD format")
    if not _DATE_RE.fullmatch(value):
        raise ValueError("due_date must be in YYYY-MM-DD format")
    return datetime.date.fromisoformat(value)


DueDate = Annotated[datetime.date | None, BeforeValidator(parse_due_date)]


class TaskCreate(BaseModel):
    title: Title
    due_date: DueDate = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    due_date: datetime.date | None
