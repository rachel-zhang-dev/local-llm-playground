"""local-llm-playground: experiments with local & cloud LLMs (DeepSeek, Hermes, GPT, MiMo)."""

from local_llm_playground.client import ChatMessage, ChatResponse, LLMClient
from local_llm_playground.config import MODELS, get_model

__version__ = "0.1.0"
__all__ = ["MODELS", "ChatMessage", "ChatResponse", "LLMClient", "get_model"]
