import logging
from typing import List, Optional
import google.generativeai as genai
from app.config import settings

logger = logging.getLogger(__name__)

class EmbeddingService:
    """
    Generates text embeddings using Google Gemini's Embedding API (e.g. models/embedding-001).
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = settings.GEMINI_EMBEDDING_MODEL
        if self.api_key and self.api_key.strip() and self.api_key != "your_gemini_api_key_here":
            genai.configure(api_key=self.api_key)
            self._configured = True
        else:
            self._configured = False

    def is_configured(self) -> bool:
        return self._configured

    def generate_embedding(
        self,
        text: str,
        task_type: str = "retrieval_document",
        output_dimensionality: Optional[int] = None
    ) -> List[float]:
        """
        Generates an embedding vector for the provided text.
        Args:
            text: The text to embed.
            task_type: 'retrieval_document' or 'retrieval_query' or 'semantic_similarity'
            output_dimensionality: Fixed output vector dimension (e.g. 768)
        Returns:
            List[float]: The embedding vector.
        """
        if not self.is_configured():
            raise ValueError("Gemini API key is not configured for EmbeddingService.")

        if not text or not text.strip():
            return []

        target_dims = output_dimensionality or getattr(settings, "EMBEDDING_DIMENSION", 768)

        # Normalize model aliases (e.g. 'embedding-002', 'gemini-embedding-002' -> 'models/gemini-embedding-2')
        norm_model = self.model
        if "embedding-002" in norm_model or "embedding-2" in norm_model:
            norm_model = "models/gemini-embedding-2"
        elif "embedding-001" in norm_model or "embedding-1" in norm_model:
            norm_model = "models/gemini-embedding-001"

        # Candidate embedding models
        candidates = [
            norm_model,
            "models/gemini-embedding-2",
            "models/gemini-embedding-2-preview",
            "models/gemini-embedding-001"
        ]
        candidates = list(dict.fromkeys(candidates))

        last_err = None
        for cand in candidates:
            try:
                try:
                    result = genai.embed_content(
                        model=cand,
                        content=text,
                        task_type=task_type,
                        output_dimensionality=target_dims
                    )
                except Exception:
                    try:
                        result = genai.embed_content(
                            model=cand,
                            content=text,
                            task_type=task_type
                        )
                    except Exception:
                        result = genai.embed_content(
                            model=cand,
                            content=text
                        )

                if isinstance(result, dict) and "embedding" in result:
                    return result["embedding"]
                elif hasattr(result, "embedding"):
                    return result.embedding
            except Exception as e:
                logger.warning(f"Embedding attempt with {cand} failed: {e}")
                last_err = e

        raise ValueError(f"Failed to generate embedding with candidates {candidates}: {last_err}")
