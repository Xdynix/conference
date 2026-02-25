__all__ = ("router",)

from . import (  # noqa: F401
    acceptance_letter,
    announce,
    claim,
    create,
    decide,
    delete,
    download,
    feedback,
    get,
    labels,
    list,
    relocate,
    set_final_limit,
    submit,
    transfer,
    update,
    upload,
    withdraw,
)
from .core import router
