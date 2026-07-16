from typing import Callable, List, Optional, Dict


class LazyPaginator:
    """
    Paginator with lazy loading of data from database
    """

    def __init__(
            self,
            query_func: Callable,
            per_page: int = 10,
            cache_pages: int = 3,
            state: Optional[Dict] = None
    ):
        """
        Args:
            query_func: Function to query data (offset, limit) -> List
            per_page: Items per page
            cache_pages: Number of pages in cache
            state: Previous paginator state (dict) for cache restoration
        """
        self.query_func = query_func
        self.per_page = per_page
        self.cache_pages = cache_pages

        # Restore from dictionary or create new.
        self._cache = {}
        self._total_count = None
        if state and isinstance(state, dict):
            self.current_page = state.get('current_page', 0)
        else:
            self.current_page = 0

    async def get_total_count(self) -> int:
        """Get the total number of items"""
        if self._total_count is None:
            self._total_count = await self.query_func(count_only=True)
        return self._total_count

    async def get_page(self, page: int) -> List:
        """
        Get the data for the page

        Args:
            page: Page number (starting from 0)

        Returns:
            List of page elements
        """
        self.current_page = page

        # Check cache
        if page in self._cache:
            return self._cache[page]

        # Load data
        offset = page * self.per_page
        items = await self.query_func(
            offset=offset,
            limit=self.per_page
        )

        # Save to cache
        self._cache[page] = items

        # Clear old cache if limit exceeded
        if len(self._cache) > self.cache_pages:
            # Keep pages around current page
            pages_to_keep = set()
            total_pages = await self.get_total_pages()
            for i in range(max(0, page - 1), min(page + 2, total_pages)):
                pages_to_keep.add(i)

            # Remove pages not in range
            for cached_page in list(self._cache.keys()):
                if cached_page not in pages_to_keep and len(self._cache) > self.cache_pages:
                    del self._cache[cached_page]

        return items

    async def get_total_pages(self) -> int:
        """Get total number of pages"""
        total = await self.get_total_count()
        return max(1, (total + self.per_page - 1) // self.per_page)

    def get_state(self) -> Dict:
        """Get current state for FSM storage.

        Excludes the page cache (non-serializable ORM objects) and total_count
        (intentionally recomputed on restore so page counts never go stale).
        """
        return {
            'current_page': self.current_page,
        }

    def clear_cache(self):
        """Clear cache"""
        self._cache.clear()
        self._total_count = None