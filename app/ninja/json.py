from typing import Any, cast, override

from django.http import HttpRequest as DjangoHttpRequest
from ninja.parser import Parser as NinjaParser
from ninja.renderers import JSONRenderer as NinjaJSONRenderer

from app.utils.orjson import serializer as orjson_serializer


class ORJSONRenderer(NinjaJSONRenderer):
    @override
    def render(self, _: Any, data: Any, *, response_status: int) -> bytes:
        return orjson_serializer.dumps(data)


class ORJSONParser(NinjaParser):
    @override
    def parse_body(self, request: DjangoHttpRequest) -> dict[str, Any]:
        return cast(dict[str, Any], orjson_serializer.loads(request.body))
