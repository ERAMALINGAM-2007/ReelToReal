import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import chromadb
from chromadb.config import Settings as ChromaSettings
from app.config import settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "reeltoreal_items"
COLLECTION_METADATA = {
    "hnsw:space": "cosine",
    "embedding_model": "models/gemini-embedding-2",
    "embedding_dimensions": 768
}

class VectorStoreService:
    """
    Local persistent vector store service for ReelToReal using ChromaDB.
    Maintains a dedicated collection ('reeltoreal_items') with cosine similarity,
    enforcing user-level isolation and strict metadata sanitization.
    """

    def __init__(self, chroma_dir: Optional[Path] = None):
        self.chroma_dir = Path(chroma_dir or settings.CHROMA_DIR)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        
        self.client = chromadb.PersistentClient(
            path=str(self.chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self._init_collection()

    def _init_collection(self):
        """Initializes or retrieves the reeltoreal_items collection with cosine distance metric."""
        try:
            collection = self.client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata=COLLECTION_METADATA
            )
            logger.info(f"ChromaDB collection '{COLLECTION_NAME}' ready at {self.chroma_dir}")
            return collection
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB collection '{COLLECTION_NAME}': {e}")
            raise

    def reset_collection(self):
        """Recreates the collection from scratch (used during migration and resets)."""
        try:
            self.client.delete_collection(name=COLLECTION_NAME)
            logger.info(f"Deleted existing ChromaDB collection '{COLLECTION_NAME}' for clean recreate.")
        except Exception:
            pass
        self.collection = self.client.create_collection(
            name=COLLECTION_NAME,
            metadata=COLLECTION_METADATA
        )
        logger.info(f"Fresh ChromaDB collection '{COLLECTION_NAME}' created.")

    @staticmethod
    def sanitize_metadata(user_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Sanitizes metadata dictionary to only contain supported primitive values
        (str, int, float, bool). Omit None or replace with empty strings.
        Always ensures user_id is present.
        """
        sanitized: Dict[str, Any] = {"user_id": str(user_id or "default")}
        if not metadata:
            return sanitized

        for k, v in metadata.items():
            if k == "user_id":
                continue
            if v is None:
                sanitized[k] = ""
            elif isinstance(v, (str, int, float, bool)):
                sanitized[k] = v
            elif isinstance(v, (list, dict)):
                # Flatten or stringify complex types for Chroma metadata compatibility
                sanitized[k] = ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)
            else:
                sanitized[k] = str(v)
        return sanitized

    def upsert_item(
        self,
        item_id: str,
        user_id: str,
        search_blob: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Upserts a document into ChromaDB.
        Args:
            item_id: Unique saved item ID (matches SQLite primary key)
            user_id: Owner user ID for isolation
            search_blob: Full textual compilation for the document
            embedding: 768-dimensional Gemini embedding vector
            metadata: Lightweight attributes (title, category, place, city, created_at)
        """
        if not item_id or not embedding:
            logger.warning(f"Cannot upsert item {item_id}: missing ID or embedding vector.")
            return False

        clean_meta = self.sanitize_metadata(user_id, metadata)

        try:
            self.collection.upsert(
                ids=[str(item_id)],
                documents=[search_blob or ""],
                embeddings=[embedding],
                metadatas=[clean_meta]
            )
            logger.debug(f"Successfully upserted item {item_id} into ChromaDB (user: {user_id})")
            return True
        except Exception as e:
            logger.error(f"Failed to upsert item {item_id} into ChromaDB: {e}")
            return False

    def update_item(
        self,
        item_id: str,
        user_id: str,
        search_blob: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Updates an existing document in ChromaDB."""
        return self.upsert_item(
            item_id=item_id,
            user_id=user_id,
            search_blob=search_blob,
            embedding=embedding,
            metadata=metadata
        )

    def delete_item(self, item_id: str) -> bool:
        """Deletes a document from ChromaDB by ID."""
        try:
            self.collection.delete(ids=[str(item_id)])
            logger.info(f"Deleted item {item_id} from ChromaDB")
            return True
        except Exception as e:
            logger.error(f"Failed to delete item {item_id} from ChromaDB: {e}")
            return False

    def search(
        self,
        user_id: str,
        query_embedding: List[float],
        top_k: int = 5
    ) -> List[Tuple[str, float]]:
        """
        Performs semantic vector search against user-scoped bookmarks.
        Returns:
            List of (item_id, cosine_similarity_score) tuples, sorted descending.
        """
        if not query_embedding:
            return []

        user_clean = str(user_id or "default")

        try:
            # 1. Check user item count first to handle empty collection / user cleanly
            total_items = self.collection.count()
            if total_items == 0:
                logger.info("ChromaDB collection is empty; returning 0 results.")
                return []

            # Check if this user has any items
            user_results = self.collection.get(
                where={"user_id": user_clean},
                limit=1
            )
            if not user_results or not user_results.get("ids"):
                logger.info(f"User '{user_clean}' has no indexed items in ChromaDB.")
                return []

            # Clamp top_k to a reasonable bound
            effective_top_k = max(1, min(top_k, 50, total_items))

            # Query Chroma with user filter
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=effective_top_k,
                where={"user_id": user_clean},
                include=["documents", "metadatas", "distances"]
            )

            hits: List[Tuple[str, float]] = []
            if results and results.get("ids") and results["ids"][0]:
                ids = results["ids"][0]
                distances = results["distances"][0] if results.get("distances") else [0.0] * len(ids)

                for item_id, dist in zip(ids, distances):
                    # Chroma cosine distance = 1 - cosine_similarity
                    similarity = max(0.0, min(1.0, 1.0 - float(dist)))
                    hits.append((item_id, similarity))

            # Sort descending by similarity
            hits.sort(key=lambda x: x[1], reverse=True)
            return hits

        except Exception as e:
            logger.error(f"Error executing ChromaDB search for user '{user_clean}': {e}")
            return []

    def count(self, user_id: Optional[str] = None) -> int:
        """Returns the total number of items, optionally filtered by user_id."""
        try:
            if user_id and user_id.lower() != "all":
                res = self.collection.get(where={"user_id": str(user_id)})
                return len(res.get("ids", []))
            return self.collection.count()
        except Exception as e:
            logger.error(f"Failed to count ChromaDB items: {e}")
            return 0
