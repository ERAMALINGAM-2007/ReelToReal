import json
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from collections import Counter
import numpy as np

from app.config import settings
from app.models.schema import SavedItem, VideoAnalysisResult, MapPin, UserProfile, KnowledgeBaseStats

logger = logging.getLogger(__name__)

class StorageService:
    """
    SQLite-based personal knowledge base and vector storage engine with cosine similarity search,
    per-user isolation, user profiles, and knowledge base analytics.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = str(db_path or settings.DB_PATH)
        self._init_db()

    def _init_db(self):
        settings.ensure_directories()
        with sqlite3.connect(self.db_path) as conn:
            # 1. Users Profile Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            now_iso = datetime.utcnow().isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, display_name, created_at) VALUES (?, ?, ?)",
                ("default", "My Personal Knowledge Base", now_iso)
            )

            # 2. Saved Items Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS saved_items (
                    id TEXT PRIMARY KEY,
                    user_id TEXT DEFAULT 'default',
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
                    personal_notes TEXT DEFAULT '',
                    search_blob TEXT NOT NULL,
                    embedding_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            # 3. Graceful schema migrations if table existed previously without user_id or personal_notes
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(saved_items)")
            columns = [row[1] for row in cursor.fetchall()]
            if "user_id" not in columns:
                logger.info("Migrating SQLite schema: adding 'user_id' column")
                conn.execute("ALTER TABLE saved_items ADD COLUMN user_id TEXT DEFAULT 'default'")
            if "personal_notes" not in columns:
                logger.info("Migrating SQLite schema: adding 'personal_notes' column")
                conn.execute("ALTER TABLE saved_items ADD COLUMN personal_notes TEXT DEFAULT ''")

            conn.commit()

    # --- User Profile Management ---

    def list_users(self) -> List[UserProfile]:
        """Returns all registered user profiles."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, display_name, created_at FROM users ORDER BY created_at ASC")
            return [UserProfile(user_id=r[0], display_name=r[1], created_at=r[2]) for r in cursor.fetchall()]

    def create_user(self, user_id: str, display_name: str) -> UserProfile:
        """Creates or registers a new user profile."""
        clean_uid = user_id.strip().lower().replace(" ", "_")
        now_iso = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO users (user_id, display_name, created_at) VALUES (?, ?, ?)",
                (clean_uid, display_name.strip(), now_iso)
            )
            conn.commit()
        return UserProfile(user_id=clean_uid, display_name=display_name.strip(), created_at=now_iso)

    # --- Saved Items CRUD (User Scoped) ---

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
        media_url: Optional[str] = None,
        user_id: str = "default",
        personal_notes: str = ""
    ) -> SavedItem:
        """Saves a new analyzed video item and its embedding into the user's personal knowledge base."""
        created_at = datetime.utcnow().isoformat()
        analysis_json = analysis.model_dump_json()
        embedding_json = json.dumps(embedding) if embedding else None

        # Ensure user exists
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, display_name, created_at) VALUES (?, ?, ?)",
                (user_id, f"User {user_id}", created_at)
            )

            conn.execute("""
                INSERT OR REPLACE INTO saved_items (
                    id, user_id, source_type, source_identifier, media_path, media_url,
                    analysis_json, category, title, place_name, city,
                    latitude, longitude, geocoded_address, personal_notes, search_blob, embedding_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item_id, user_id, source_type, source_identifier, media_path, media_url,
                analysis_json, analysis.category.value, analysis.title,
                analysis.entities.place_name, analysis.entities.city,
                latitude, longitude, geocoded_address, personal_notes, analysis.search_blob,
                embedding_json, created_at
            ))
            conn.commit()

        return SavedItem(
            id=item_id,
            user_id=user_id,
            source_type=source_type,
            source_identifier=source_identifier,
            media_url=media_url,
            analysis=analysis,
            latitude=latitude,
            longitude=longitude,
            geocoded_address=geocoded_address,
            personal_notes=personal_notes,
            created_at=created_at
        )

    def get_all_items(
        self,
        category: Optional[str] = None,
        user_id: Optional[str] = "default"
    ) -> List[SavedItem]:
        """Retrieves all saved items for a specific user, optionally filtered by category."""
        items = []
        query = ("SELECT id, user_id, source_type, source_identifier, media_url, "
                 "analysis_json, latitude, longitude, geocoded_address, personal_notes, created_at FROM saved_items")
        conditions = []
        params = []

        if user_id and user_id.lower() != "all":
            conditions.append("user_id = ?")
            params.append(user_id)

        if category and category.lower() != "all":
            conditions.append("category = ?")
            params.append(category.lower())

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            for r in rows:
                analysis = VideoAnalysisResult.model_validate_json(r[5])
                items.append(SavedItem(
                    id=r[0],
                    user_id=r[1],
                    source_type=r[2],
                    source_identifier=r[3],
                    media_url=r[4],
                    analysis=analysis,
                    latitude=r[6],
                    longitude=r[7],
                    geocoded_address=r[8],
                    personal_notes=r[9] or "",
                    created_at=r[10]
                ))
        return items

    def get_item_by_id(self, item_id: str, user_id: Optional[str] = None) -> Optional[SavedItem]:
        """Retrieves a single saved item by its unique ID and optional user filter."""
        query = ("SELECT id, user_id, source_type, source_identifier, media_url, "
                 "analysis_json, latitude, longitude, geocoded_address, personal_notes, created_at "
                 "FROM saved_items WHERE id = ?")
        params = [item_id]
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            r = cursor.fetchone()
            if not r:
                return None
            analysis = VideoAnalysisResult.model_validate_json(r[5])
            return SavedItem(
                id=r[0],
                user_id=r[1],
                source_type=r[2],
                source_identifier=r[3],
                media_url=r[4],
                analysis=analysis,
                latitude=r[6],
                longitude=r[7],
                geocoded_address=r[8],
                personal_notes=r[9] or "",
                created_at=r[10]
            )

    def update_item(
        self,
        item_id: str,
        user_id: Optional[str] = None,
        personal_notes: Optional[str] = None,
        tags: Optional[List[str]] = None,
        place_name: Optional[str] = None,
        city: Optional[str] = None
    ) -> Optional[SavedItem]:
        """Updates user annotations (personal notes) or entity details for a saved clip."""
        item = self.get_item_by_id(item_id, user_id=user_id)
        if not item:
            return None

        analysis = item.analysis
        if personal_notes is not None:
            item.personal_notes = personal_notes
        if tags is not None:
            analysis.tags = tags
        if place_name is not None:
            analysis.entities.place_name = place_name
        if city is not None:
            analysis.entities.city = city

        # Recompute search blob to include updated notes/tags
        notes_part = f"Notes: {item.personal_notes}" if item.personal_notes else ""
        if notes_part and notes_part not in analysis.search_blob:
            analysis.search_blob = f"{analysis.search_blob} | {notes_part}"

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE saved_items
                SET personal_notes = ?,
                    analysis_json = ?,
                    place_name = ?,
                    city = ?,
                    search_blob = ?
                WHERE id = ?
            """, (
                item.personal_notes,
                analysis.model_dump_json(),
                analysis.entities.place_name,
                analysis.entities.city,
                analysis.search_blob,
                item_id
            ))
            conn.commit()

        item.analysis = analysis
        return item

    def delete_item(self, item_id: str, user_id: Optional[str] = None) -> bool:
        """Deletes an item from the personal knowledge base."""
        query = "DELETE FROM saved_items WHERE id = ?"
        params = [item_id]
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount > 0

    def count_items(self, user_id: Optional[str] = None) -> int:
        """Returns the total number of saved items, optionally scoped to a user."""
        query = "SELECT COUNT(*) FROM saved_items"
        params = []
        if user_id and user_id.lower() != "all":
            query += " WHERE user_id = ?"
            params.append(user_id)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()[0]

    def get_map_pins(self, user_id: Optional[str] = "default") -> List[MapPin]:
        """Retrieves geocoded pins for map visualization, scoped to a user's knowledge base."""
        pins = []
        query = """
            SELECT id, title, category, latitude, longitude, place_name, city, analysis_json, media_url
            FROM saved_items
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        """
        params = []
        if user_id and user_id.lower() != "all":
            query += " AND user_id = ?"
            params.append(user_id)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
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
        top_k: int = 5,
        user_id: Optional[str] = "default"
    ) -> List[Tuple[SavedItem, float]]:
        """
        Calculates cosine similarity between query embedding and stored items belonging to the user.
        Returns a list of tuples: (SavedItem, similarity_score) sorted descending by score.
        """
        if not query_embedding:
            items = self.get_all_items(user_id=user_id)[:top_k]
            return [(item, 0.5) for item in items]

        query_vec = np.array(query_embedding, dtype=np.float32)
        norm_query = np.linalg.norm(query_vec)
        if norm_query == 0:
            return []

        query = ("SELECT id, user_id, source_type, source_identifier, media_url, "
                 "analysis_json, latitude, longitude, geocoded_address, personal_notes, created_at, embedding_json "
                 "FROM saved_items WHERE embedding_json IS NOT NULL")
        params = []
        if user_id and user_id.lower() != "all":
            query += " AND user_id = ?"
            params.append(user_id)

        results = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

            for r in rows:
                try:
                    item_vec = np.array(json.loads(r[11]), dtype=np.float32)
                    norm_item = np.linalg.norm(item_vec)
                    if norm_item == 0:
                        continue
                    # Cosine similarity: (A . B) / (||A|| * ||B||)
                    score = float(np.dot(query_vec, item_vec) / (norm_query * norm_item))
                    
                    analysis = VideoAnalysisResult.model_validate_json(r[5])
                    saved_item = SavedItem(
                        id=r[0],
                        user_id=r[1],
                        source_type=r[2],
                        source_identifier=r[3],
                        media_url=r[4],
                        analysis=analysis,
                        latitude=r[6],
                        longitude=r[7],
                        geocoded_address=r[8],
                        personal_notes=r[9] or "",
                        created_at=r[10]
                    )
                    results.append((saved_item, score))
                except Exception as e:
                    logger.warning(f"Error calculating similarity for item {r[0]}: {e}")

        # Sort by similarity score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    # --- Knowledge Base Analytics & Export ---

    def get_user_stats(self, user_id: str = "default") -> KnowledgeBaseStats:
        """Calculates rich metrics for the user's personal knowledge base."""
        items = self.get_all_items(user_id=user_id)
        categories_counter = Counter([item.analysis.category.value for item in items])
        mapped_count = sum(1 for item in items if item.latitude is not None and item.longitude is not None)
        
        cities = [item.analysis.entities.city for item in items if item.analysis.entities.city]
        top_cities = [city for city, _ in Counter(cities).most_common(5)]

        return KnowledgeBaseStats(
            user_id=user_id,
            total_items=len(items),
            categories=dict(categories_counter),
            total_mapped_places=mapped_count,
            top_cities=top_cities
        )

    def export_user_data(self, user_id: str = "default") -> Dict[str, Any]:
        """Exports the entire personal knowledge base for backup/portability."""
        items = self.get_all_items(user_id=user_id)
        stats = self.get_user_stats(user_id)
        return {
            "version": "1.0",
            "exported_at": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "stats": stats.model_dump(),
            "items": [item.model_dump() for item in items]
        }
