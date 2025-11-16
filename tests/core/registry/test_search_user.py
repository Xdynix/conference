from app.core.registry.search_user import SearchUserRegistry


class TestSearchUserRegistry:
    def test_register_accumulates_queries(self) -> None:
        registry = SearchUserRegistry()

        registry.register("username__icontains", "email__icontains")

        assert registry.get_queries() == {
            "username__icontains",
            "email__icontains",
        }
