import pytest
from faker import Faker
from pytest_mock import MockerFixture

from app.conference.models import (
    Conference,
    Keyword,
    UserConferenceProfile,
)
from app.conference.services import (
    KeywordService,
    UserConferenceProfileService,
)
from app.core.models import User


async def create_keywords(*texts: str) -> list[Keyword]:
    keywords = []
    for text in texts:
        keyword = await Keyword.objects.acreate(text=text)
        keywords.append(keyword)
    return keywords


@pytest.fixture
async def user(faker: Faker) -> User:
    return await User.objects.acreate_user(username=faker.user_name())


@pytest.fixture
async def conference(faker: Faker) -> Conference:
    return await Conference.objects.acreate(
        name=faker.slug(),
        display_name=faker.sentence(),
    )


@pytest.fixture
async def profile(user: User, conference: Conference) -> UserConferenceProfile:
    return await UserConferenceProfile.objects.acreate(
        user=user,
        conference=conference,
        desired_paper_count=5,
    )


@pytest.mark.django_db(transaction=True)
class TestUserConferenceProfileServiceUpdateProfile:
    async def test_update_desired_paper_count_only(
        self,
        profile: UserConferenceProfile,
    ) -> None:
        await UserConferenceProfileService.update_profile(
            profile=profile,
            desired_paper_count=10,
        )

        await profile.arefresh_from_db()
        assert profile.desired_paper_count == 10

    async def test_update_interested_keywords_only(
        self,
        profile: UserConferenceProfile,
    ) -> None:
        await create_keywords("machine-learning", "deep-learning")
        old_keywords = await create_keywords("old-keyword")
        await profile.interested_keywords.aset(old_keywords)

        await UserConferenceProfileService.update_profile(
            profile=profile,
            interested_keywords=["machine-learning", "deep-learning"],
        )

        profile_keywords = [
            kw
            async for kw in profile.interested_keywords.values_list("text", flat=True)
        ]
        assert profile_keywords == ["deep-learning", "machine-learning"]

    async def test_update_both_fields(
        self,
        profile: UserConferenceProfile,
    ) -> None:
        await create_keywords("machine-learning", "ai")

        await UserConferenceProfileService.update_profile(
            profile=profile,
            desired_paper_count=15,
            interested_keywords=["machine-learning", "ai"],
        )

        await profile.arefresh_from_db()
        assert profile.desired_paper_count == 15
        profile_keywords = [
            kw
            async for kw in profile.interested_keywords.values_list("text", flat=True)
        ]
        assert profile_keywords == ["ai", "machine-learning"]

    async def test_update_with_empty_keywords_list(
        self,
        profile: UserConferenceProfile,
    ) -> None:
        old_keywords = await create_keywords("old-keyword")
        await profile.interested_keywords.aset(old_keywords)

        await UserConferenceProfileService.update_profile(
            profile=profile,
            interested_keywords=[],
        )

        assert not await profile.interested_keywords.aexists()

    async def test_no_op_when_both_none(
        self,
        profile: UserConferenceProfile,
    ) -> None:
        keywords = await create_keywords("existing")
        await profile.interested_keywords.aset(keywords)
        original_count = profile.desired_paper_count

        await UserConferenceProfileService.update_profile(profile=profile)

        await profile.arefresh_from_db()
        assert profile.desired_paper_count == original_count
        profile_keywords = [
            kw
            async for kw in profile.interested_keywords.values_list("text", flat=True)
        ]
        assert profile_keywords == ["existing"]

    async def test_validates_keywords_before_updating_paper_count(
        self,
        mocker: MockerFixture,
        profile: UserConferenceProfile,
    ) -> None:
        mock_validate_keyword = mocker.patch.object(
            KeywordService,
            "validate_keyword_texts",
            side_effect=ValueError("Unknown keywords: invalid"),
        )

        with pytest.raises(ValueError, match="Unknown keywords: invalid"):
            await UserConferenceProfileService.update_profile(
                profile=profile,
                desired_paper_count=20,
                interested_keywords=["invalid"],
            )

        mock_validate_keyword.assert_called_once_with(["invalid"])
        await profile.arefresh_from_db()
        # `desired_paper_count` should not be updated due to validation failure.
        assert profile.desired_paper_count == 5
