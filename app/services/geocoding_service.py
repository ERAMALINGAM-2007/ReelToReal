import time
import logging
import sqlite3
from typing import Optional, Tuple
import requests
from app.config import settings

logger = logging.getLogger(__name__)

class GeocodingService:
    """
    Geocodes place names and cities using OpenStreetMap Nominatim with local caching
    and respectful rate limiting (~1 req/sec).
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or settings.DB_PATH)
        self.last_request_time = 0.0
        self._init_cache_table()

    def _init_cache_table(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS geocode_cache (
                        query TEXT PRIMARY KEY,
                        latitude REAL,
                        longitude REAL,
                        display_name TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize geocode cache: {e}")

    def geocode(self, place_name: Optional[str], city: Optional[str] = None, address: Optional[str] = None) -> Tuple[Optional[float], Optional[float], Optional[str]]:
        """
        Geocodes a location query. Returns (latitude, longitude, display_name).
        Checks local SQLite cache first.
        """
        # Formulate query
        parts = []
        if place_name and place_name.strip():
            parts.append(place_name.strip())
        if address and address.strip():
            parts.append(address.strip())
        if city and city.strip():
            parts.append(city.strip())

        if not parts:
            return None, None, None

        query = ", ".join(parts)
        query_key = query.lower().strip()

        # Check cache
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT latitude, longitude, display_name FROM geocode_cache WHERE query = ?", (query_key,))
                row = cursor.fetchone()
                if row:
                    logger.info(f"Geocode cache hit for '{query}': ({row[0]}, {row[1]})")
                    return row[0], row[1], row[2]
        except Exception as e:
            logger.warning(f"Cache lookup error: {e}")

        # Rate limit to ~1 request per second
        elapsed = time.time() - self.last_request_time
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)

        headers = {
            "User-Agent": "ReelToReal-PersonalPlanner/1.0 (contact: demo@reeltoreal.ai)"
        }
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": query,
            "format": "json",
            "limit": 1
        }

        try:
            self.last_request_time = time.time()
            logger.info(f"Nominatim geocoding request for: '{query}'")
            resp = requests.get(url, params=params, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    display_name = data[0].get("display_name", query)

                    # Save to cache
                    self._save_to_cache(query_key, lat, lon, display_name)
                    return lat, lon, display_name

            # If specific query failed, try city only as fallback
            if city and city.strip() and len(parts) > 1:
                logger.info(f"Retrying geocoding fallback with city only: '{city}'")
                return self.geocode(place_name=None, city=city, address=None)

            # Save negative result to cache to avoid spamming
            self._save_to_cache(query_key, None, None, None)
            return None, None, None

        except Exception as e:
            logger.error(f"Geocoding failed for '{query}': {e}")
            return None, None, None

    def _save_to_cache(self, query_key: str, lat: Optional[float], lon: Optional[float], display_name: Optional[str]):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO geocode_cache (query, latitude, longitude, display_name)
                    VALUES (?, ?, ?, ?)
                """, (query_key, lat, lon, display_name))
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to cache geocode result: {e}")
