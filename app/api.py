from app.conference.api.profile import router as profile_router
from app.core.api.password_reset import router as password_reset_router
from app.core.api.session import router as session_router
from app.core.api.user import router as user_router
from app.misc.api import router as misc_router
from app.ninja.core import AppNinjaAPI
from app.verikit.api import router as verikit_router

api = AppNinjaAPI.build()

api.add_router("", misc_router)
api.add_router("", password_reset_router)
api.add_router("", profile_router)
api.add_router("", session_router)
api.add_router("", user_router)
api.add_router("", verikit_router)
