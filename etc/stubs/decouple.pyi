from collections.abc import Callable, Iterable
from typing import (
    ClassVar,
    Generic,
    Protocol,
    TypeVar,
    overload,
)

DT = TypeVar("DT")
VT = TypeVar("VT")

class Undefined: ...

class Repository:
    def __contains__(self, key: str) -> bool: ...
    def __getitem__(self, key: str) -> str: ...

class AutoConfig:
    SUPPORTED: ClassVar[dict[str, Repository]]

    @overload
    def __call__(
        self,
        option: str,
        default: Undefined = ...,
        cast: Undefined = ...,
    ) -> str: ...
    @overload
    def __call__(
        self,
        option: str,
        default: Undefined = ...,
        cast: Callable[[str], VT] = ...,
    ) -> VT: ...
    @overload
    def __call__(
        self,
        option: str,
        default: DT = ...,
        cast: Undefined = ...,
    ) -> str | DT: ...
    @overload
    def __call__(
        self,
        option: str,
        default: DT = ...,
        cast: Callable[[str | DT], VT] = ...,
    ) -> VT: ...

config: AutoConfig

IT = TypeVar("IT", contravariant=True, default=str)
CT = TypeVar("CT", covariant=True, default=list[str])

class PostProcess(Protocol[IT, CT]):
    @overload
    def __call__(self) -> CT: ...
    @overload
    def __call__(self, items: Iterable[IT]) -> CT: ...

class Csv(Generic[IT, CT]):
    def __init__(
        self,
        cast: Callable[[str], IT] = ...,
        delimiter: str = ...,
        strip: str = ...,
        post_process: PostProcess[IT, CT] = ...,
    ): ...
    def __call__(self, value: str) -> CT: ...
