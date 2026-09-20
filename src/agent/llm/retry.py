"""Retry Manager - Stub"""
import asyncio

class RetryConfig:
    def __init__(self, attempts=3, min_delay_ms=500, max_delay_ms=10000, jitter=0.1, should_retry=None, **kw):
        self.attempts = attempts
        self.should_retry = should_retry

class RetryManager:
    async def execute(self, fn, *a, **kw):
        try:
            return await fn(*a, **kw)
        except:
            return None
    
    async def execute_with_retry(self, fn, retry_config, op_name=""):
        """Call fn() with retry"""
        last_err = None
        for i in range(retry_config.attempts if hasattr(retry_config, 'attempts') else 3):
            try:
                return await fn()
            except Exception as e:
                last_err = e
                if i < 2:
                    await asyncio.sleep(0.1)
        raise last_err if last_err else Exception("All retries failed")
    
    async def record_failure(self, *a, **kw): pass
_instance = RetryManager()
def get_retry_manager(): return _instance
