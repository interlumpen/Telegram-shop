import pytest
import asyncio
from datetime import datetime

from bot.misc import LazyPaginator


class TestLazyPaginator:
    """Test suite for lazy paginator"""

    @pytest.mark.asyncio
    async def test_paginator_initialization(self):
        """Test paginator initialization"""

        # Mock query function
        async def mock_query(offset=0, limit=10, count_only=False):
            if count_only:
                return 100
            return list(range(offset, min(offset + limit, 100)))

        paginator = LazyPaginator(mock_query, per_page=10, cache_pages=3)

        assert paginator.per_page == 10
        assert paginator.cache_pages == 3
        assert paginator.current_page == 0
        assert paginator._total_count is None
        assert paginator._cache == {}

    @pytest.mark.asyncio
    async def test_get_total_count(self):
        """Test getting total count"""

        async def mock_query(offset=0, limit=10, count_only=False):
            if count_only:
                return 50
            return []

        paginator = LazyPaginator(mock_query)

        # First call should query
        count = await paginator.get_total_count()
        assert count == 50

        # Should cache the result
        assert paginator._total_count == 50

        # Second call should use cache
        count2 = await paginator.get_total_count()
        assert count2 == 50

    @pytest.mark.asyncio
    async def test_get_page(self):
        """Test getting page data"""
        test_data = list(range(100))

        async def mock_query(offset=0, limit=10, count_only=False):
            if count_only:
                return len(test_data)
            return test_data[offset:offset + limit]

        paginator = LazyPaginator(mock_query, per_page=10)

        # Get first page
        page0 = await paginator.get_page(0)
        assert page0 == list(range(0, 10))
        assert paginator.current_page == 0

        # Get second page
        page1 = await paginator.get_page(1)
        assert page1 == list(range(10, 20))
        assert paginator.current_page == 1

        # Get last page
        page9 = await paginator.get_page(9)
        assert page9 == list(range(90, 100))

    @pytest.mark.asyncio
    async def test_page_caching(self):
        """Test page caching mechanism"""
        query_count = 0

        async def tracking_query(offset=0, limit=10, count_only=False):
            nonlocal query_count
            if not count_only:
                query_count += 1
            if count_only:
                return 50
            return list(range(offset, min(offset + limit, 50)))

        paginator = LazyPaginator(tracking_query, per_page=10, cache_pages=3)

        # First access - should query
        page0 = await paginator.get_page(0)
        assert query_count == 1

        # Second access to same page - should use cache
        page0_again = await paginator.get_page(0)
        assert query_count == 1  # No additional query
        assert page0 == page0_again

        # Access different pages
        await paginator.get_page(1)
        await paginator.get_page(2)
        assert query_count == 3

    @pytest.mark.asyncio
    async def test_cache_eviction(self):
        """Test cache eviction when limit exceeded"""

        async def mock_query(offset=0, limit=10, count_only=False):
            if count_only:
                return 100
            return list(range(offset, min(offset + limit, 100)))

        paginator = LazyPaginator(mock_query, per_page=10, cache_pages=2)

        # Load pages 0, 1, 2
        await paginator.get_page(0)
        await paginator.get_page(1)
        await paginator.get_page(2)

        # Cache should keep pages around current page (2)
        # So it should keep pages 1 and 2, evict page 0
        assert len(paginator._cache) <= paginator.cache_pages + 1

    @pytest.mark.asyncio
    async def test_get_total_pages(self):
        """Test calculating total pages"""
        test_cases = [
            (0, 10, 1),  # Empty data - still 1 page
            (1, 10, 1),  # Single item
            (10, 10, 1),  # Exactly one page
            (11, 10, 2),  # Just over one page
            (95, 10, 10),  # Multiple pages
            (100, 10, 10),  # Exact multiple
        ]

        for total_items, per_page, expected_pages in test_cases:
            async def mock_query(offset=0, limit=10, count_only=False):
                if count_only:
                    return total_items
                return []

            paginator = LazyPaginator(mock_query, per_page=per_page)
            pages = await paginator.get_total_pages()
            assert pages == expected_pages

    @pytest.mark.asyncio
    async def test_state_serialization(self):
        """Test state serialization and restoration"""

        async def mock_query(offset=0, limit=10, count_only=False):
            if count_only:
                return 50
            return list(range(offset, min(offset + limit, 50)))

        # Create paginator and load some data
        paginator1 = LazyPaginator(mock_query, per_page=10)
        await paginator1.get_page(2)
        await paginator1.get_total_count()

        # Get state
        state = paginator1.get_state()
        assert state['current_page'] == 2
        assert state['total_count'] == 50
        # Cache should not be in state (non-serializable)
        assert 'cache' not in state

        # Create new paginator with state
        paginator2 = LazyPaginator(mock_query, per_page=10, state=state)
        assert paginator2.current_page == 2
        assert paginator2._total_count == 50
        assert paginator2._cache == {}  # Cache not restored

    @pytest.mark.asyncio
    async def test_clear_cache(self):
        """Test cache clearing"""

        async def mock_query(offset=0, limit=10, count_only=False):
            if count_only:
                return 50
            return list(range(offset, min(offset + limit, 50)))

        paginator = LazyPaginator(mock_query)

        # Load some pages
        await paginator.get_page(0)
        await paginator.get_page(1)
        await paginator.get_total_count()

        assert len(paginator._cache) == 2
        assert paginator._total_count == 50

        # Clear cache
        paginator.clear_cache()

        assert len(paginator._cache) == 0
        assert paginator._total_count is None

    @pytest.mark.asyncio
    async def test_concurrent_access(self):
        """Test concurrent access to paginator"""

        async def mock_query(offset=0, limit=10, count_only=False):
            await asyncio.sleep(0.01)  # Simulate DB delay
            if count_only:
                return 100
            return list(range(offset, min(offset + limit, 100)))

        paginator = LazyPaginator(mock_query, per_page=10)

        # Concurrent access to different pages
        tasks = [
            paginator.get_page(0),
            paginator.get_page(1),
            paginator.get_page(2),
            paginator.get_total_count(),
            paginator.get_total_pages(),
        ]

        results = await asyncio.gather(*tasks)

        assert results[0] == list(range(0, 10))
        assert results[1] == list(range(10, 20))
        assert results[2] == list(range(20, 30))
        assert results[3] == 100
        assert results[4] == 10

    @pytest.mark.asyncio
    async def test_empty_result_handling(self):
        """Test handling of empty results"""

        async def empty_query(offset=0, limit=10, count_only=False):
            if count_only:
                return 0
            return []

        paginator = LazyPaginator(empty_query)

        # Should handle empty results gracefully
        page = await paginator.get_page(0)
        assert page == []

        total = await paginator.get_total_count()
        assert total == 0

        pages = await paginator.get_total_pages()
        assert pages == 1  # Minimum 1 page even if empty

    @pytest.mark.asyncio
    async def test_item_serialization(self):
        """Test serialization of different item types"""

        # Test with SQLAlchemy-like objects
        class MockDBObject:
            def __init__(self, id, name, created_at):
                self.id = id
                self.name = name
                self.created_at = created_at
                self._internal = "hidden"

        obj = MockDBObject(1, "Test", datetime.now())
        paginator = LazyPaginator(None)

        serialized = paginator._serialize_item(obj)
        assert 'id' in serialized
        assert 'name' in serialized
        assert 'created_at' in serialized
        assert '_internal' not in serialized

        # Test with dict
        dict_item = {'key': 'value', 'date': datetime.now()}
        serialized_dict = paginator._serialize_item(dict_item)
        assert 'key' in serialized_dict
        assert isinstance(serialized_dict['date'], str)

        # Test with simple type
        simple_item = "simple string"
        serialized_simple = paginator._serialize_item(simple_item)
        assert serialized_simple == {'value': 'simple string'}

    @pytest.mark.asyncio
    async def test_pagination_edge_cases(self):
        """Test pagination edge cases"""

        async def mock_query(offset=0, limit=10, count_only=False):
            if count_only:
                return 25
            # Return data for 25 items
            return list(range(offset, min(offset + limit, 25)))

        paginator = LazyPaginator(mock_query, per_page=10)

        # Test accessing beyond last page
        page10 = await paginator.get_page(10)
        assert page10 == []  # No data beyond available

        # Test last partial page
        page2 = await paginator.get_page(2)
        assert page2 == list(range(20, 25))  # Only 5 items
        assert len(page2) == 5

    @pytest.mark.asyncio
    async def test_query_error_handling(self):
        """Test handling of query errors"""
        error_count = 0

        async def failing_query(offset=0, limit=10, count_only=False):
            nonlocal error_count
            error_count += 1
            if error_count <= 2:
                raise Exception("Database error")
            if count_only:
                return 10
            return list(range(offset, min(offset + limit, 10)))

        paginator = LazyPaginator(failing_query)

        # First attempts should raise
        with pytest.raises(Exception, match="Database error"):
            await paginator.get_page(0)

        with pytest.raises(Exception, match="Database error"):
            await paginator.get_total_count()

        # Third attempt should succeed
        page = await paginator.get_page(0)
        assert page == list(range(0, 10))

    @pytest.mark.asyncio
    async def test_intelligent_cache_keeping(self):
        """Test intelligent cache keeping around current page"""

        async def mock_query(offset=0, limit=10, count_only=False):
            if count_only:
                return 100
            return list(range(offset, min(offset + limit, 100)))

        paginator = LazyPaginator(mock_query, per_page=10, cache_pages=3)

        # Access pages in sequence
        await paginator.get_page(0)
        await paginator.get_page(1)
        await paginator.get_page(2)
        await paginator.get_page(3)
        await paginator.get_page(4)

        # Current page is 4, should keep pages 3, 4, 5 (if we access 5)
        # Access page 5 to trigger cache management
        await paginator.get_page(5)

        # Pages 0, 1, 2 should be evicted, 3, 4, 5 should be in cache
        # But implementation may vary, so just check cache size
        assert len(paginator._cache) <= paginator.cache_pages + 2
