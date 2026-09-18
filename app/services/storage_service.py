import json
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import numpy as np

from app.config import settings
from app.models.schema import SavedItem, VideoAnalysisResult, MapPin

logger = logging.getLogger(__name__)

class StorageService:
    """
    SQLite-based knowledge base and vector storage engine with cosine similarity search.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = str(db_path or settings.DB_PATH)
        self._init_db()

    def _init_db(self):
        settings.ensure_directories()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS saved_items (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source_identifier TEXT NOT NULL,
                    media_path TEXT,
                    media_url TEXT,
                    analysis_json TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    place_name TEXT,
                    city TEXT,
                    latitude REAL,
                    longitude REAL,
                    geocoded_address TEXT,
                    search_blob TEXT NOT NULL,
                    embedding_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def save_item(
        self,
        item_id: str,
        source_type: str,
        source_identifier: str,
        analysis: VideoAnalysisResult,
        embedding: Optional[List[float]] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        geocoded_address: Optional[str] = None,
        media_path: Optional[str] = None,
        media_url: Optional[str] = None
    ) -> SavedItem:
        """Saves a new analyzed video item and its embedding into the database."""
        created_at = datetime.utcnow().isoformat()
        analysis_json = analysis.model_dump_json()
        embedding_json = json.dumps(embedding) if embedding else None

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO saved_items (
                    id, source_type, source_identifier, media_path, media_url,
                    analysis_json, category, title, place_name, city,
                    latitude, longitude, geocoded_address, search_blob, embedding_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item_id, source_type, source_identifier, media_path, media_url,
                analysis_json, analysis.category.value, analysis.title,
                analysis.entities.place_name, analysis.entities.city,
                latitude, longitude, geocoded_address, analysis.search_blob,
                embedding_json, created_at
            ))
            conn.commit()

        return SavedItem(
            id=item_id,
            source_type=source_type,
            source_identifier=source_identifier,
            media_url=media_url,
            analysis=analysis,
            latitude=latitude,
            longitude=longitude,
            geocoded_address=geocoded_address,
            created_at=created_at
        )

    def get_all_items(self, category: Optional[str] = None) -> List[SavedItem]:
        """Retrieves all saved items, optionally filtered by category."""
        items = []
        query = "SELECT id, source_type, source_identifier, media_url, analysis_json, latitude, longitude, geocoded_address, created_at FROM saved_items"
        params = []
        if category and category.lower() != "all":
            query += " WHERE category = ?"
            params.append(category.lower())
        query += " ORDER BY created_at DESC"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            for r in rows:
                analysis = VideoAnalysisResult.model_validate_json(r[4])
                items.append(SavedItem(
                    id=r[0],
                    source_type=r[1],
                    source_identifier=r[2],
                    media_url=r[3],
                    analysis=analysis,
                    latitude=r[5],
                    longitude=r[6],
                    geocoded_address=r[7],
                    created_at=r[8]
                ))
        return items

    def get_item_by_id(self, item_id: str) -> Optional[SavedItem]:
        """Retrieves a single saved item by its unique ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, source_type, source_identifier, media_url, analysis_json,
                       latitude, longitude, geocoded_address, created_at
                FROM saved_items WHERE id = ?
            """, (item_id,))
            r = cursor.fetchone()
            if not r:
                return None
            analysis = VideoAnalysisResult.model_validate_json(r[4])
            return SavedItem(
                id=r[0],
                source_type=r[1],
                source_identifier=r[2],
                media_url=r[3],
                analysis=analysis,
                latitude=r[5],
                longitude=r[6],
                geocoded_address=r[7],
                created_at=r[8]
            )

    def delete_item(self, item_id: str) -> bool:
        """Deletes an item from the knowledge base."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM saved_items WHERE id = ?", (item_id,))
            conn.commit()
            return cursor.rowcount > 0

    def count_items(self) -> int:
        """Returns the total number of saved items."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM saved_items")
            return cursor.fetchone()[0]

    def get_map_pins(self) -> List[MapPin]:
        """Retrieves all geocoded pins for map visualization."""
        pins = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, title, category, latitude, longitude, place_name, city, analysis_json, media_url
                FROM saved_items
                WHERE latitude IS NOT NULL AND longitude IS NOT NULL
            """)
            rows = cursor.fetchall()
            for r in rows:
                analysis = VideoAnalysisResult.model_validate_json(r[7])
                pins.append(MapPin(
                    id=r[0],
                    title=r[1],
                    category=r[2],
                    latitude=r[3],
                    longitude=r[4],
                    place_name=r[5],
                    city=r[6],
                    highlights=analysis.entities.highlights,
                    actionable_tips=analysis.entities.actionable_tips,
                    media_url=r[8]
                ))
        return pins

    def search_similar_items(
        self,
        query_embedding: List[float],
        top_k: int = 5
    ) -> List[Tuple[SavedItem, float]]:
        """
        Calculates cosine similarity between query embedding and all stored item embeddings.
        Returns a list of tuples: (SavedItem, similarity_score) sorted descending by score.
        """
        if not query_embedding:
            # Fallback to returning recent items
            items = self.get_all_items()[:top_k]
            return [(item, 0.5) for item in items]

        query_vec = np.array(query_embedding, dtype=np.float32)
        norm_query = np.linalg.norm(query_vec)
        if norm_query == 0:
            return []

        results = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, source_type, source_identifier, media_url, analysis_json,
                       latitude, longitude, geocoded_address, created_at, embedding_json
                FROM saved_items
                WHERE embedding_json IS NOT NULL
            """)
            rows = cursor.fetchall()

            for r in rows:
                try:
                    item_vec = np.array(json.loads(r[9]), dtype=np.float32)
                    norm_item = np.linalg.norm(item_vec)
                    if norm_item == 0:
                        continue
                    # Cosine similarity: (A . B) / (||A|| * ||B||)
                    score = float(np.dot(query_vec, item_vec) / (norm_query * norm_item))
                    
                    analysis = VideoAnalysisResult.model_validate_json(r[4])
                    saved_item = SavedItem(
                        id=r[0],
                        source_type=r[1],
                        source_identifier=r[2],
                        media_url=r[3],
                        analysis=analysis,
                        latitude=r[5],
                        longitude=r[6],
                        geocoded_address=r[7],
                        created_at=r[8]
                    )
                    results.append((saved_item, score))
                except Exception as e:
                    logger.warning(f"Error calculating similarity for item {r[0]}: {e}")

        # Sort by similarity score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]
