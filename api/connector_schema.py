"""Turn a connector's pydantic Config class into a JSON-serializable field
list the frontend can render a form from — the fallback path for any source
or target the wizard doesn't have a hand-authored field spec for (custom
connectors, or new ones added to udi-connectors without a matching frontend
change).
"""

import types
import typing
from typing import Any

from pydantic import SecretStr
from udi_connectors import get_source_class, get_target_class

# Bookkeeping fields that exist on Config classes but were never meant to be
# set directly through the connection-creation form.
_INTERNAL_FIELDS = {"source_type", "target_type", "last_checkpoint"}


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _jsonable_default(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def _describe_field(name: str, info: Any) -> dict:
    annotation, optional = _unwrap_optional(info.annotation)
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    ui_type = "text"
    options: list[str] | None = None

    if origin is typing.Literal:
        ui_type = "select"
        options = [str(a) for a in args]
    elif annotation is bool:
        ui_type = "checkbox"
    elif annotation in (int, float):
        ui_type = "number"
    elif annotation is SecretStr:
        ui_type = "password"
    elif annotation is dict or origin is dict or annotation is list or origin is list:
        ui_type = "json"

    required = info.is_required()
    return {
        "name": name,
        "type": ui_type,
        "required": required,
        "optional": optional,
        "default": None if required else _jsonable_default(info.default),
        "options": options,
        "description": info.description,
    }


def describe_source(name: str) -> list[dict] | None:
    cls = get_source_class(name)
    if cls is None:
        return None
    fields = cls.Config.model_fields
    return [_describe_field(n, f) for n, f in fields.items() if n not in _INTERNAL_FIELDS]


def describe_target(name: str) -> list[dict] | None:
    cls = get_target_class(name)
    if cls is None:
        return None
    fields = cls.Config.model_fields
    return [_describe_field(n, f) for n, f in fields.items() if n not in _INTERNAL_FIELDS]
