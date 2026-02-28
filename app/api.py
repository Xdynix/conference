from app.conference.api.conference import router as conference_router
from app.conference.api.email import router as email_router
from app.conference.api.file import router as conference_file_router
from app.conference.api.invitation import router as invitation_router
from app.conference.api.keyword_set import router as keyword_set_router
from app.conference.api.paper import router as paper_router
from app.conference.api.payment import router as payment_router
from app.conference.api.registration import router as registration_router
from app.conference.api.review import router as review_router
from app.conference.api.role_assignment import router as role_assignment_router
from app.conference.api.user import router as conference_user_router
from app.core.api.api_key import router as api_key_router
from app.core.api.password_reset import router as password_reset_router
from app.core.api.session import router as session_router
from app.core.api.user import router as user_router
from app.misc.api import router as misc_router
from app.ninja.core import AppNinjaAPI
from app.verikit.api import router as verikit_router

api = AppNinjaAPI.build()


for router in (
    api_key_router,
    conference_file_router,
    conference_router,
    conference_user_router,
    email_router,
    invitation_router,
    keyword_set_router,
    misc_router,
    paper_router,
    password_reset_router,
    payment_router,
    registration_router,
    review_router,
    role_assignment_router,
    session_router,
    user_router,
    verikit_router,
):
    api.add_router("", router)
