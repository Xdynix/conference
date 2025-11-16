__all__ = (
    "SearchUserRegistry",
    "search_user_registry",
)


class SearchUserRegistry:
    """Registry for user search query lookups.

    Allows Django apps to extend the user list endpoint's search parameter by
    registering ORM lookup paths. These lookups are combined with the core search fields
    to enable comprehensive user search.
    """

    def __init__(self) -> None:
        self._registry = set[str]()

    def register(self, *queries: str) -> None:
        """Register ORM lookup paths for user search.

        Args:
            *queries: Django ORM lookup paths (e.g., ``profile__name__icontains``).
        """
        self._registry.update(queries)

    def get_queries(self) -> frozenset[str]:
        """Return all registered search query lookups.

        Returns:
            Immutable set of registered ORM lookup paths.
        """
        return frozenset(self._registry)


search_user_registry = SearchUserRegistry()
