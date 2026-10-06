"""Research shortlist, not a deployed-model ranking. Official cards linked in docs."""

CANDIDATES = {
    "gemma4-e4b": {"model_id": "google/gemma-4-E4B-it", "loader": "multimodal"},
    "phi4-mini": {"model_id": "microsoft/Phi-4-mini-instruct", "loader": "causal"},
    "qwen3-4b": {"model_id": "Qwen/Qwen3-4B-Instruct-2507", "loader": "causal"},
    "smollm3-3b": {"model_id": "HuggingFaceTB/SmolLM3-3B", "loader": "causal"},
    "lfm25-12b": {"model_id": "LiquidAI/LFM2.5-1.2B-Instruct", "loader": "causal"},
    "qwen35-4b": {"model_id": "Qwen/Qwen3.5-4B", "loader": "image_text"},
}
