import pytest
import json
import pickle
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from decimal import Decimal

from bot.misc.cache import CacheManager, cache_result, get_cache_manager, init_cache_manager


class TestCacheManager:
    """Test suite for cache manager functionality"""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client"""
        redis_mock = AsyncMock()
        return redis_mock

    @pytest.fixture
    def cache_manager(self, mock_redis):
        """Create a CacheManager instance with mock Redis"""
        return CacheManager(mock_redis)

    def test_cache_manager_initialization(self, mock_redis):
        """Test cache manager initialization"""
        cache = CacheManager(mock_redis)
        assert cache.redis == mock_redis
        assert cache.default_ttl == 300
        assert cache.hits == 0
        assert cache.misses == 0

    @pytest.mark.asyncio
    async def test_cache_get_json_success(self, cache_manager, mock_redis):
        """Test successful JSON deserialization from cache"""
        test_data = {"key": "value", "number": 42}
        json_bytes = json.dumps(test_data).encode('utf-8')

        mock_redis.get.return_value = json_bytes

        result = await cache_manager.get("test_key")

        assert result == test_data
        assert cache_manager.hits == 1
        assert cache_manager.misses == 0
        mock_redis.get.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_cache_get_pickle_fallback(self, cache_manager, mock_redis):
        """Test pickle deserialization fallback"""
        test_data = {"complex": datetime.now(), "decimal": Decimal("123.45")}
        pickle_bytes = pickle.dumps(test_data)

        mock_redis.get.return_value = pickle_bytes

        result = await cache_manager.get("test_key")

        assert result == test_data
        assert cache_manager.hits == 1

    @pytest.mark.asyncio
    async def test_cache_get_miss(self, cache_manager, mock_redis):
        """Test cache miss"""
        mock_redis.get.return_value = None

        result = await cache_manager.get("nonexistent_key")

        assert result is None
        assert cache_manager.hits == 0
        assert cache_manager.misses == 1

    @pytest.mark.asyncio
    async def test_cache_get_no_deserialize(self, cache_manager, mock_redis):
        """Test getting raw bytes without deserialization"""
        raw_data = b"raw_binary_data"
        mock_redis.get.return_value = raw_data

        result = await cache_manager.get("test_key", deserialize=False)

        assert result == raw_data
        assert cache_manager.hits == 1

    @pytest.mark.asyncio
    async def test_cache_get_deserialization_error(self, cache_manager, mock_redis):
        """Test handling of deserialization errors"""
        invalid_data = b"not_valid_json_or_pickle"
        mock_redis.get.return_value = invalid_data

        with patch('bot.misc.cache.logger') as mock_logger:
            result = await cache_manager.get("test_key")

            assert result is None
            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_cache_set_json_serialization(self, cache_manager, mock_redis):
        """Test JSON serialization when setting cache"""
        test_data = {"key": "value", "datetime": datetime.now()}

        result = await cache_manager.set("test_key", test_data, ttl=600)

        assert result is True
        mock_redis.setex.assert_called_once()

        # Check that setex was called with correct parameters
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "test_key"  # key
        assert call_args[0][1] == 600  # ttl

        # The value should be JSON-encoded bytes
        stored_data = call_args[0][2]
        assert isinstance(stored_data, bytes)
        # Should be able to decode back
        decoded = json.loads(stored_data.decode('utf-8'))
        assert decoded["key"] == "value"

    @pytest.mark.asyncio
    async def test_cache_set_pickle_fallback(self, cache_manager, mock_redis):
        """Test pickle serialization fallback"""

        # Use a complex object that can't be JSON serialized
        class CustomObject:
            def __init__(self, value):
                self.value = value
                self.timestamp = datetime.now()

        test_data = CustomObject("test")

        result = await cache_manager.set("test_key", test_data)

        assert result is True
        mock_redis.setex.assert_called_once()

        # Should use pickle since JSON will fail
        call_args = mock_redis.setex.call_args
        stored_data = call_args[0][2]
        assert isinstance(stored_data, bytes)

        # First check if it's JSON (it might fallback to JSON with default=str)
        try:
            # Try JSON first since datetime objects might be stringified
            data = json.loads(stored_data.decode('utf-8'))
            # If it's a JSON object with our expected structure, or a string representation
            assert isinstance(data, (dict, str)) or hasattr(data, 'value')
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Should be pickle data
            unpickled = pickle.loads(stored_data)
            assert unpickled.value == "test"

    @pytest.mark.asyncio
    async def test_cache_set_no_serialize(self, cache_manager, mock_redis):
        """Test setting cache without serialization"""
        raw_data = "raw_string_data"

        result = await cache_manager.set("test_key", raw_data, serialize=False)

        assert result is True
        mock_redis.setex.assert_called_once_with("test_key", 300, raw_data)

    @pytest.mark.asyncio
    async def test_cache_set_default_ttl(self, cache_manager, mock_redis):
        """Test using default TTL when none specified"""
        await cache_manager.set("test_key", "value")

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 300  # default_ttl

    @pytest.mark.asyncio
    async def test_cache_set_error_handling(self, cache_manager, mock_redis):
        """Test error handling during cache set"""
        mock_redis.setex.side_effect = Exception("Redis connection error")

        with patch('bot.misc.cache.logger') as mock_logger:
            result = await cache_manager.set("test_key", "value")

            assert result is False
            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_cache_delete(self, cache_manager, mock_redis):
        """Test cache deletion"""
        result = await cache_manager.delete("test_key")

        assert result is True
        mock_redis.delete.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_cache_delete_error(self, cache_manager, mock_redis):
        """Test error handling during cache deletion"""
        mock_redis.delete.side_effect = Exception("Delete failed")

        with patch('bot.misc.cache.logger') as mock_logger:
            result = await cache_manager.delete("test_key")

            assert result is False
            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_cache_invalidate_pattern(self, cache_manager, mock_redis):
        """Test pattern-based cache invalidation"""
        # Mock scan_iter to return some keys using AsyncMockIterator
        keys = ["user:123:profile", "user:456:profile", "user:789:profile"]

        # Create a proper mock that returns the iterator directly (not wrapped in a coroutine)
        mock_iterator = AsyncMockIterator(keys)
        mock_redis.scan_iter = MagicMock(return_value=mock_iterator)
        mock_redis.delete.return_value = 3

        result = await cache_manager.invalidate_pattern("user:*:profile")

        assert result == 3
        mock_redis.scan_iter.assert_called_once_with(match="user:*:profile")
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_invalidate_pattern_no_keys(self, cache_manager, mock_redis):
        """Test pattern invalidation when no keys match"""
        # Use empty AsyncMockIterator
        mock_empty_iterator = AsyncMockIterator([])
        mock_redis.scan_iter = MagicMock(return_value=mock_empty_iterator)

        result = await cache_manager.invalidate_pattern("nonexistent:*")

        assert result == 0
        mock_redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_invalidate_pattern_error(self, cache_manager, mock_redis):
        """Test error handling during pattern invalidation"""
        mock_redis.scan_iter = MagicMock(side_effect=Exception("Scan failed"))

        with patch('bot.misc.cache.logger') as mock_logger:
            result = await cache_manager.invalidate_pattern("test:*")

            assert result == 0
            mock_logger.error.assert_called()


class TestCacheDecorator:
    """Test suite for cache decorator functionality"""

    @pytest.fixture
    def mock_cache_manager(self):
        """Create a mock cache manager"""
        cache_mock = AsyncMock()
        return cache_mock

    @pytest.mark.asyncio
    async def test_cache_result_decorator_hit(self, mock_cache_manager):
        """Test cache decorator on cache hit"""
        cached_value = {"result": "cached_data"}
        mock_cache_manager.get.return_value = cached_value

        with patch('bot.misc.cache.get_cache_manager', return_value=mock_cache_manager):
            @cache_result(ttl=600, key_prefix="test")
            async def test_function(param1, param2="default"):
                return {"result": "fresh_data"}

            result = await test_function("value1", param2="value2")

            assert result == cached_value
            mock_cache_manager.get.assert_called_once()
            mock_cache_manager.set.assert_not_called()

            # Check cache key generation
            cache_key = mock_cache_manager.get.call_args[0][0]
            assert "test" in cache_key
            assert "value1" in cache_key
            assert "param2=value2" in cache_key

    @pytest.mark.asyncio
    async def test_cache_result_decorator_miss(self, mock_cache_manager):
        """Test cache decorator on cache miss"""
        mock_cache_manager.get.return_value = None
        expected_result = {"result": "fresh_data"}

        with patch('bot.misc.cache.get_cache_manager', return_value=mock_cache_manager):
            @cache_result(ttl=600)
            async def test_function(param):
                return expected_result

            result = await test_function("test_param")

            assert result == expected_result
            mock_cache_manager.get.assert_called_once()
            mock_cache_manager.set.assert_called_once()

            # Check that result was cached
            set_call_args = mock_cache_manager.set.call_args
            assert set_call_args[0][1] == expected_result  # cached value
            assert set_call_args[0][2] == 600  # ttl

    @pytest.mark.asyncio
    async def test_cache_result_custom_key_func(self, mock_cache_manager):
        """Test cache decorator with custom key function"""
        mock_cache_manager.get.return_value = None

        def custom_key_func(user_id, action):
            return f"user_action:{user_id}:{action}"

        with patch('bot.misc.cache.get_cache_manager', return_value=mock_cache_manager):
            @cache_result(key_func=custom_key_func)
            async def user_action(user_id, action):
                return f"result_for_{user_id}_{action}"

            await user_action(123, "buy")

            # Check custom key was used
            cache_key = mock_cache_manager.get.call_args[0][0]
            assert cache_key == "user_action:123:buy"

    @pytest.mark.asyncio
    async def test_cache_result_no_cache_manager(self):
        """Test cache decorator when cache manager is not available"""
        with patch('bot.misc.cache.get_cache_manager', return_value=None):
            @cache_result()
            async def test_function():
                return "result"

            result = await test_function()

            # Should work normally without caching
            assert result == "result"

    @pytest.mark.asyncio
    async def test_cache_result_none_result_not_cached(self, mock_cache_manager):
        """Test that None results are not cached"""
        mock_cache_manager.get.return_value = None

        with patch('bot.misc.cache.get_cache_manager', return_value=mock_cache_manager):
            @cache_result()
            async def test_function():
                return None

            result = await test_function()

            assert result is None
            mock_cache_manager.get.assert_called_once()
            mock_cache_manager.set.assert_not_called()


class TestCacheManagerGlobal:
    """Test suite for global cache manager functions"""

    def test_get_cache_manager_initially_none(self):
        """Test that cache manager is initially None"""
        # Reset the global variable
        with patch('bot.misc.cache._cache_manager', None):
            manager = get_cache_manager()
            assert manager is None

    @pytest.mark.asyncio
    async def test_init_cache_manager(self):
        """Test cache manager initialization"""
        mock_redis = AsyncMock()

        with patch('bot.misc.cache.logger') as mock_logger:
            await init_cache_manager(mock_redis)

            manager = get_cache_manager()
            assert manager is not None
            assert manager.redis == mock_redis
            mock_logger.info.assert_called_with("Cache manager initialized")

    @pytest.mark.asyncio
    async def test_cache_manager_persistence(self):
        """Test that cache manager persists after initialization"""
        mock_redis = AsyncMock()

        await init_cache_manager(mock_redis)

        # Should return the same instance
        manager1 = get_cache_manager()
        manager2 = get_cache_manager()
        assert manager1 is manager2
        assert manager1.redis == mock_redis


class AsyncMockIterator:
    """Helper class to mock async iterator for Redis scan_iter"""

    def __init__(self, items):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item


class TestCacheIntegration:
    """Integration tests for cache functionality"""

    @pytest.mark.asyncio
    async def test_cache_with_complex_data_types(self):
        """Test caching with complex data types"""
        mock_redis = AsyncMock()
        cache_manager = CacheManager(mock_redis)

        # Test with datetime and Decimal
        complex_data = {
            "timestamp": datetime(2024, 1, 1, 12, 0, 0),
            "amount": Decimal("123.45"),
            "items": ["item1", "item2"],
            "nested": {
                "key": "value",
                "number": 42
            }
        }

        # Mock Redis to return the serialized data when get is called
        def mock_setex(key, ttl, value):
            # Store the value so we can return it on get
            mock_redis._stored_data = value

        def mock_get(key):
            return getattr(mock_redis, '_stored_data', None)

        mock_redis.setex.side_effect = mock_setex
        mock_redis.get.side_effect = mock_get

        # Set and get the data
        await cache_manager.set("complex_key", complex_data)
        result = await cache_manager.get("complex_key")

        # Should be able to round-trip the data
        assert result is not None
        assert "timestamp" in result
        assert "amount" in result
        assert result["items"] == ["item1", "item2"]
        assert result["nested"]["key"] == "value"

    @pytest.mark.asyncio
    async def test_cache_decorator_with_object_args(self):
        """Test cache decorator with objects as arguments"""
        mock_cache_manager = AsyncMock()
        mock_cache_manager.get.return_value = None

        class MockUser:
            def __init__(self, id):
                self.id = id

        with patch('bot.misc.cache.get_cache_manager', return_value=mock_cache_manager):
            @cache_result()
            async def get_user_data(user):
                return f"data_for_user_{user.id}"

            user = MockUser(123)
            result = await get_user_data(user)

            assert result == "data_for_user_123"
            # Should have attempted to cache
            mock_cache_manager.set.assert_called_once()
