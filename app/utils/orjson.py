from typing import Any

import orjson
from ulid import ULID


def default(obj: Any) -> Any:
    """Serialize non-standard type."""
    match obj:
        case ULID():
            return str(obj)
        case _:  # pragma: no cover
            raise TypeError


class ORJSONSerializer:
    @classmethod
    def dumps(cls, obj: Any) -> bytes:
        return orjson.dumps(
            obj,
            option=orjson.OPT_UTC_Z,
            default=default,
        )

    @classmethod
    def loads(cls, data: bytes) -> Any:
        return orjson.loads(data)


serializer = ORJSONSerializer()
