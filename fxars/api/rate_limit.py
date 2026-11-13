"""FIX-11-REDIS: Rate Limit backend (memory | redis)."""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

logger = logging.getLogger('fxars.api.rate_limit')


class MemoryRateLimiter:
    # FIX-07-MAX-BUCKETS: جلوگیری از memory exhaustion با محدودیت تعداد bucket
    DEFAULT_MAX_BUCKETS = 10000

    def __init__(self, limit, window_seconds=60, *, max_buckets=None):
        self.limit = limit
        self.window = window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()
        self._max_buckets = max_buckets or self.DEFAULT_MAX_BUCKETS
        self._eviction_count = 0

    def allow(self, key):
        now = time.monotonic()
        with self._lock:
            # FIX-07-MAX-BUCKETS: eviction قبل از افزودن bucket جدید
            if key not in self._hits and len(self._hits) >= self._max_buckets:
                self._evict_oldest()
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True

    def _evict_oldest(self):
        """حذف قدیمی‌ترین bucket برای آزاد کردن حافظه."""
        if not self._hits:
            return
        # پیدا کردن bucket با قدیمی‌ترین آخرین hit
        oldest_key = min(
            self._hits.items(),
            key=lambda kv: kv[1][-1] if kv[1] else 0.0,
        )[0]
        del self._hits[oldest_key]
        self._eviction_count += 1

    @property
    def eviction_count(self):
        return self._eviction_count

    def hits_for(self, key):
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                return 0
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            return len(bucket)

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            result = {}
            empty_keys = []
            for key, bucket in list(self._hits.items()):
                while bucket and now - bucket[0] > self.window:
                    bucket.popleft()
                if bucket:
                    result[key] = len(bucket)
                else:
                    empty_keys.append(key)
            # FIX-07-MAX-BUCKETS: پاکسازی bucketهای خالی
            for k in empty_keys:
                del self._hits[k]
            return result


class RedisRateLimiter:
    def __init__(self, url, limit, window_seconds=60, *, prefix='fxars:rl:', socket_timeout=2.0):
        import redis
        self._client = redis.Redis.from_url(url, socket_timeout=socket_timeout,
                                            socket_connect_timeout=socket_timeout,
                                            decode_responses=True)
        self._client.ping()
        self.limit = limit
        self.window = window_seconds
        self.prefix = prefix

    def _full_key(self, key): return f'{self.prefix}{key}'

    def allow(self, key):
        full = self._full_key(key)
        now_ms = int(time.time() * 1000)
        cutoff = now_ms - self.window * 1000
        member = f'{now_ms}-{threading.get_ident()}'
        pipe = self._client.pipeline()
        pipe.zremrangebyscore(full, 0, cutoff)
        pipe.zcard(full)
        pipe.zadd(full, {member: now_ms})
        pipe.expire(full, self.window + 5)
        _, count, _, _ = pipe.execute()
        return int(count) < self.limit

    def hits_for(self, key):
        full = self._full_key(key)
        cutoff = int(time.time() * 1000) - self.window * 1000
        self._client.zremrangebyscore(full, 0, cutoff)
        return int(self._client.zcard(full))

    def snapshot(self):
        result = {}
        for full in self._client.scan_iter(match=f'{self.prefix}*', count=200):
            count = self._client.zcard(full)
            if count:
                result[full[len(self.prefix):]] = int(count)
        return result


def build_rate_limiter(settings):
    backend = (settings.api.rate_limit_backend or 'memory').lower()
    limit = int(settings.api.rate_limit_per_minute)
    if backend == 'redis':
        url = settings.api.redis_url
        if not url:
            logger.warning('rate_limit_backend=redis but redis_url empty; fallback')
            return MemoryRateLimiter(limit, 60)
        try:
            return RedisRateLimiter(url, limit, 60, prefix=settings.api.rate_limit_prefix)
        except Exception as exc:
            logger.warning('Redis unreachable (%s); fallback to memory', exc)
            return MemoryRateLimiter(limit, 60)
    return MemoryRateLimiter(limit, 60)
