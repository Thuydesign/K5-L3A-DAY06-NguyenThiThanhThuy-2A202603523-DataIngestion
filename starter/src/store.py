"""Persistent local exact-cosine vector search using embedded Qdrant."""
import math
import uuid
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    HnswConfigDiff,
    MatchValue,
    PointStruct,
    VectorParams,
)

from .models import Chunk


class QdrantVectorStore:
    def __init__(self, path: Path, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.dimensions = dimensions
        self.client = QdrantClient(path=str(self.path))

    def create_schema(self) -> None:
        for strategy in ("A", "B", "C"):
            collection = self._collection(strategy)
            if not self.client.collection_exists(collection):
                self.client.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(
                        size=self.dimensions,
                        distance=Distance.COSINE,
                    ),
                    hnsw_config=HnswConfigDiff(m=0),
                )

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if strategy not in {"A", "B", "C"}:
            raise ValueError(f"Unknown strategy: {strategy}")
        if len(chunks) != len(vectors):
            raise ValueError("Each chunk must have exactly one embedding vector")
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise ValueError("Chunk IDs must be unique within a strategy")

        collection = self._collection(strategy)
        if not self.client.collection_exists(collection):
            self.create_schema()

        points = []
        for chunk, vector in zip(chunks, vectors):
            self._validate_vector(vector)
            metadata = {
                **chunk.metadata,
                "document_id": chunk.document_id,
                "source": chunk.source,
                "page": chunk.page,
            }
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{strategy}:{chunk.chunk_id}"))
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "chunk_id": chunk.chunk_id,
                        "document_id": chunk.document_id,
                        "source": chunk.source,
                        "page": chunk.page,
                        "text": chunk.text,
                        "metadata": metadata,
                    },
                )
            )

        # Clear before replacement so changed documents cannot leave obsolete chunks.
        self.client.delete(
            collection_name=collection,
            points_selector=FilterSelector(filter=Filter(must=[])),
            wait=True,
        )
        if points:
            self.client.upsert(collection_name=collection, points=points, wait=True)

    def search(
        self,
        strategy: str,
        query_vector: list[float],
        top_k: int = 3,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_vector(query_vector)
        if strategy not in {"A", "B", "C"}:
            raise ValueError(f"Unknown strategy: {strategy}")
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        query_filter = None
        if filters:
            conditions = []
            for key, value in filters.items():
                if key in {"document_id", "source", "page"}:
                    payload_key = key
                else:
                    payload_key = f"metadata.{key}"
                conditions.append(
                    FieldCondition(key=payload_key, match=MatchValue(value=value))
                )
            query_filter = Filter(must=conditions)

        response = self.client.query_points(
            collection_name=self._collection(strategy),
            query=query_vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        results = []
        for point in response.points:
            payload = point.payload or {}
            results.append(
                {
                    "chunk_id": payload["chunk_id"],
                    "document_id": payload["document_id"],
                    "source": payload["source"],
                    "page": payload["page"],
                    "text": payload["text"],
                    "metadata": payload["metadata"],
                    "score": float(point.score),
                }
            )
        return results

    @staticmethod
    def _collection(strategy: str) -> str:
        return f"day6_{strategy.lower()}"

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self.dimensions:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.dimensions}, got {len(vector)}"
            )
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("Embedding vector contains a non-finite value")

    def close(self) -> None:
        self.client.close()
