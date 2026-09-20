"""Model Fallback - Stub"""
class ModelFallbackManager:
    async def status(self): return {"status": "ok"}
    def record_failure(self, *a, **kw): pass
    def record_success(self, *a, **kw): pass
    def get_current_model(self, *a, **kw): return {"name": "google/gemma-4-26b-a4b"}
    def get_fallback_provider(self): return None
    def get_fallback_chain(self): return []
    async def switch_model(self, *a, **kw): return True

class FallbackHandler:
    @staticmethod
    async def status(req): return {"status": "ok"}
_instance = ModelFallbackManager()
def get_fallback_manager(): return _instance
