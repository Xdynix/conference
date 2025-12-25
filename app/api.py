from app.conference.api.code_pool import router as code_pool_router
from app.conference.api.conference import router as conference_router
from app.conference.api.invitation import router as invitation_router
from app.conference.api.keyword_set import router as keyword_set_router
from app.conference.api.paper import router as paper_router
from app.conference.api.profile import router as profile_router
from app.conference.api.review import router as review_router
from app.conference.api.role_assignment import router as role_assignment_router
from app.core.api.password_reset import router as password_reset_router
from app.core.api.session import router as session_router
from app.core.api.user import router as user_router
from app.misc.api import router as misc_router
from app.ninja.core import AppNinjaAPI
from app.verikit.api import router as verikit_router

api = AppNinjaAPI.build()

api.add_router("", code_pool_router)
api.add_router("", conference_router)
api.add_router("", invitation_router)
api.add_router("", keyword_set_router)
api.add_router("", misc_router)
api.add_router("", paper_router)
api.add_router("", password_reset_router)
api.add_router("", profile_router)
api.add_router("", review_router)
api.add_router("", role_assignment_router)
api.add_router("", session_router)
api.add_router("", user_router)
api.add_router("", verikit_router)
