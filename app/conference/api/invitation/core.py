from typing import Any

from ninja import Router

from app.conference.models import Invitation
from app.conference.types import Invitation as InvitationSchema

router = Router(tags=["Invitation"], exclude_none=True)


class InvitationResponse(InvitationSchema):
    @staticmethod
    def resolve_interested_keywords(invitation: Invitation) -> list[str]:
        return [keyword.text for keyword in invitation.interested_keywords.all()]

    @staticmethod
    def resolve_conference_roles(invitation: Invitation) -> list[str]:
        return [entry.role for entry in invitation.conference_role_entries.all()]

    @staticmethod
    def resolve_track_roles(invitation: Invitation) -> list[dict[str, Any]]:
        return [
            {"uid": entry.track.uid, "role": entry.role}
            for entry in invitation.track_role_entries.all()
        ]
