from app.misc.api import router as misc_router
from app.ninja.core import AppNinjaAPI

api = AppNinjaAPI.build()

api.add_router("", misc_router)
