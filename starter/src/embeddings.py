"""Local CPU embeddings through FastEmbed; model files are cached on this machine."""
import math
import os
from pathlib import Path
from typing import Protocol

from fastembed import TextEmbedding


DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one local model vector per input text, in input order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with stored document vectors."""
        ...


class MyEmbedder:
    """Run a real multilingual embedding model locally without any API provider."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name.strip()
        if not self.model_name:
            raise ValueError("EMBEDDING_MODEL must name a supported local model")

        model_info = next(
            (
                model
                for model in TextEmbedding.list_supported_models()
                if model["model"] == self.model_name
            ),
            None,
        )
        if model_info is None:
            supported = ", ".join(
                model["model"] for model in TextEmbedding.list_supported_models()
            )
            raise ValueError(
                f"Unsupported FastEmbed model {self.model_name!r}. "
                f"Choose a supported model: {supported}"
            )
        self.dimensions = int(model_info["dim"])
        self.license = str(model_info.get("license", "unspecified"))
        default_cache = Path.home() / ".cache" / "fastembed"
        cache_dir = Path(os.getenv("FASTEMBED_CACHE_PATH", str(default_cache))).expanduser()
        self._model = TextEmbedding(
            model_name=self.model_name,
            cache_dir=str(cache_dir),
            local_files_only=os.getenv("FASTEMBED_LOCAL_FILES_ONLY", "").lower() == "true",
        )
        self.request_count = 0
        self.total_tokens = 0
        self.token_usage_complete = False

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = [self._validate_vector(vector) for vector in self._model.embed(texts)]
        if len(vectors) != len(texts):
            raise ValueError("Local embedding model returned an incomplete document batch")
        return vectors

    def embed_query(self, question: str) -> list[float]:
        vectors = [
            self._validate_vector(vector)
            for vector in self._model.query_embed([question])
        ]
        if len(vectors) != 1:
            raise ValueError("Local embedding model returned an invalid query batch")
        return vectors[0]

    def _validate_vector(self, value: object) -> list[float]:
        try:
            vector = [float(item) for item in value]
        except (TypeError, ValueError) as error:
            raise ValueError("Local embedding model returned a non-numeric vector") from error
        if len(vector) != self.dimensions:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.dimensions}, got {len(vector)}"
            )
        if not all(math.isfinite(item) for item in vector):
            raise ValueError("Local embedding model returned a non-finite vector value")
        return vector
