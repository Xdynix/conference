from app.misc.api import router as misc_router
from app.ninja.core import AppNinjaAPI
from app.verikit.api import router as verikit_router

api = AppNinjaAPI.build()

api.add_router("", misc_router)
api.add_router("", verikit_router)
