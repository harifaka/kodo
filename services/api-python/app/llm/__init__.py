"""DeepSeek Architecture Copilot (Phase 5): OpenAI-compatible client, IR context packing, workflows."""

from app.llm.config import LlmConfig, LlmOverride, resolve_config
from app.llm.errors import LlmError

__all__ = ["LlmConfig", "LlmError", "LlmOverride", "resolve_config"]
