import pytest
from bot.misc.lazy_paginator import LazyPaginator


async def _mock_query(offset=0, limit=10, count_only=False):
    """Mock query function returning numbered items."""
    total = 25
    if count_only:
        return total
    return list(range(offset, min(offset + limit, total)))


async def _empty_query(offset=0, limit=10, count_only=False):
    if count_only:
        return 0
    return []


class TestLazyPaginator:

    @pytest.mark.asyncio
    async def test_get_page_basic(self):
        p = LazyPaginator(_mock_query, per_page=10)
        items = await p.get_page(0)
        assert items == list(range(10))

    @pytest.mark.asyncio
    async def test_get_page_second(self):
        p = LazyPaginator(_mock_query, per_page=10)
        items = await p.get_page(1)
        assert items == list(range(10, 20))

    @pytest.mark.asyncio
    async def test_get_page_last(self):
        p = LazyPaginator(_mock_query, per_page=10)
        items = await p.get_page(2)
        assert items == list(range(20, 25))

    @pytest.mark.asyncio
    async def test_get_total_count(self):
        p = LazyPaginator(_mock_query, per_page=10)
        assert await p.get_total_count() == 25

    @pytest.mark.asyncio
    async def test_get_total_pages(self):
        p = LazyPaginator(_mock_query, per_page=10)
        assert await p.get_total_pages() == 3

    @pytest.mark.asyncio
    async def test_page_caching(self):
        call_count = 0

        async def counting_query(offset=0, limit=10, count_only=False):
            nonlocal call_count
            call_count += 1
            if count_only:
                return 10
            return list(range(offset, offset + limit))

        p = LazyPaginator(counting_query, per_page=10)
        await p.get_page(0)
        await p.get_page(0)  # Should use cache
        # 1 call for first get_page, 0 for second (cached)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_cache_eviction(self):
        p = LazyPaginator(_mock_query, per_page=5, cache_pages=2)
        await p.get_page(0)
        await p.get_page(1)
        await p.get_page(2)
        await p.get_page(3)
        await p.get_page(4)
        # With cache_pages=2, old pages should be evicted
        assert len(p._cache) <= 3  # cache_pages + nearby

    @pytest.mark.asyncio
    async def test_state_round_trip(self):
        p = LazyPaginator(_mock_query, per_page=10)
        await p.get_page(1)
        state = p.get_state()
        assert state['current_page'] == 1
        assert state['total_count'] is None or state['total_count'] == 25

        # Restore from state
        p2 = LazyPaginator(_mock_query, per_page=10, state=state)
        assert p2.current_page == 1

    @pytest.mark.asyncio
    async def test_empty_results(self):
        p = LazyPaginator(_empty_query, per_page=10)
        items = await p.get_page(0)
        assert items == []
        assert await p.get_total_count() == 0
        assert await p.get_total_pages() == 1  # min 1

    @pytest.mark.asyncio
    async def test_clear_cache(self):
        p = LazyPaginator(_mock_query, per_page=10)
        await p.get_page(0)
        assert len(p._cache) > 0
        p.clear_cache()
        assert len(p._cache) == 0
        assert p._total_count is None
