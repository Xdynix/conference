from collections.abc import Callable, Iterable
from typing import (
    Any,
    ClassVar,
    Generic,
    Protocol,
    TypeVar,
    overload,
)

DefaultT = TypeVar("DefaultT")
ValueT = TypeVar("ValueT")

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
        cast: Callable[[str], ValueT] = ...,
    ) -> ValueT: ...
    @overload
    def __call__(
        self,
        option: str,
        default: DefaultT = ...,
        cast: Undefined = ...,
    ) -> str | DefaultT: ...
    @overload
    def __call__(
        self,
        option: str,
        default: DefaultT = ...,
        cast: Callable[[str | DefaultT], ValueT] = ...,
    ) -> ValueT: ...

config: AutoConfig

CsvValueT = TypeVar("CsvValueT", contravariant=True, default=str)
CsvResultT = TypeVar("CsvResultT", covariant=True, default=list[str])

class PostProcess(Protocol[CsvValueT, CsvResultT]):
    @overload
    def __call__(self) -> CsvResultT: ...
    @overload
    def __call__(self, items: Iterable[CsvValueT]) -> CsvResultT: ...

class Csv(Generic[CsvValueT, CsvResultT]):
    def __init__(
        self,
        cast: Callable[[str], CsvValueT] = ...,
        delimiter: str = ...,
        strip: str = ...,
        post_process: PostProcess[CsvValueT, CsvResultT] = ...,
    ): ...
    def __call__(self, value: str) -> CsvResultT: ...

ChoicesValueT = TypeVar("ChoicesValueT", covariant=True, default=str)

class Choices(Generic[ChoicesValueT]):
    def __init__(
        self,
        flat: Iterable[ChoicesValueT] | None = None,
        cast: Callable[[str], ChoicesValueT] = ...,
        choices: Iterable[tuple[ChoicesValueT, Any]] | None = None,
    ): ...
    def __call__(self, value: str) -> ChoicesValueT: ...
