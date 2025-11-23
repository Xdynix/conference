from app.conference.api.conference import router as conference_router
from app.conference.api.invitation import router as invitation_router
from app.conference.api.keyword_set import router as keyword_set_router
from app.conference.api.profile import router as profile_router
from app.core.api.password_reset import router as password_reset_router
from app.core.api.session import router as session_router
from app.core.api.user import router as user_router
from app.misc.api import router as misc_router
from app.ninja.core import AppNinjaAPI
from app.verikit.api import router as verikit_router

api = AppNinjaAPI.build()

api.add_router("", conference_router)
api.add_router("", invitation_router)
api.add_router("", keyword_set_router)
api.add_router("", misc_router)
api.add_router("", password_reset_router)
api.add_router("", profile_router)
api.add_router("", session_router)
api.add_router("", user_router)
api.add_router("", verikit_router)
