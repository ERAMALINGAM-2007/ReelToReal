"""
ReelToReal Migration & Vector Synchronization Utility
Migrates and synchronizes all SQLite saved items to ChromaDB vector store.
- Reconstructs search_blob from scratch (zero stale fragments)
- Re-embeds each document with models/gemini-embedding-2 at fixed 768 dimensions
- Updates SQLite with the 768-dim embedding and sets vector_sync_status = 'synced'
- Upserts documents and sanitized metadata into ChromaDB collection 'reeltoreal_items'
- Acts as a safe re-sync / repair tool
"""
import sys
import io
import argparse
import logging

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.config import settings
from app.services.storage_service import StorageService
from app.services.embedding_service import EmbeddingService
from app.services.vector_store_service import VectorStoreService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("migration")

def migrate(recreate_collection: bool = False, repair_only: bool = False):
    print("=" * 60)
    print("ReelToReal SQLite -> ChromaDB Migration & Sync Tool")
    print(f"Target Chroma Directory: {settings.CHROMA_DIR}")
    print(f"Embedding Model: {settings.GEMINI_EMBEDDING_MODEL} (dims: {settings.EMBEDDING_DIMENSION})")
    print(f"Mode: {'Repair Unsynced Only' if repair_only else 'Full Migration'}")
    print("=" * 60)

    storage = StorageService()
    embedder = EmbeddingService()
    vector_store = VectorStoreService()

    if recreate_collection:
        print("\n[!] Recreating ChromaDB collection 'reeltoreal_items' from scratch...")
        vector_store.reset_collection()

    if repair_only:
        items = storage.get_unsynced_items()
        print(f"\nFound {len(items)} items needing vector sync/repair.")
    else:
        items = storage.get_all_items(user_id="all")
        print(f"\nFound {len(items)} total items in SQLite knowledge base.")

    if not items:
        print("No items to migrate. All records are up to date!")
        return

    synced_count = 0
    failed_count = 0

    for idx, item in enumerate(items, 1):
        print(f"\n[{idx}/{len(items)}] Processing: '{item.analysis.title}' (ID: {item.id}, User: {item.user_id})")

        # 1. Rebuild clean search blob from scratch
        fresh_blob = storage.rebuild_search_blob(item.analysis, item.personal_notes)
        item.analysis.search_blob = fresh_blob

        # 2. Re-embed at fixed 768 dimensions
        embedding = []
        if embedder.is_configured():
            try:
                embedding = embedder.generate_embedding(
                    text=fresh_blob,
                    task_type="retrieval_document",
                    output_dimensionality=settings.EMBEDDING_DIMENSION
                )
            except Exception as emb_err:
                logger.error(f"Embedding generation failed for item {item.id}: {emb_err}")

        # 3. Sanitize metadata
        metadata = {
            "user_id": item.user_id,
            "title": item.analysis.title,
            "category": item.analysis.category.value,
            "place_name": item.analysis.entities.place_name or "",
            "city": item.analysis.entities.city or "",
            "created_at": item.created_at
        }

        # 4. Upsert to ChromaDB
        chroma_ok = False
        if embedding and len(embedding) == settings.EMBEDDING_DIMENSION:
            chroma_ok = vector_store.upsert_item(
                item_id=item.id,
                user_id=item.user_id,
                search_blob=fresh_blob,
                embedding=embedding,
                metadata=metadata
            )

        # 5. Update SQLite sync status & new embedding
        if chroma_ok:
            storage.update_item(
                item_id=item.id,
                user_id=item.user_id,
                personal_notes=item.personal_notes,
                new_embedding=embedding,
                vector_sync_status="synced"
            )
            print(f"  [OK] Successfully indexed in ChromaDB and marked 'synced' in SQLite.")
            synced_count += 1
        else:
            storage.update_sync_status(item.id, "failed")
            print(f"  [FAIL] Failed to index in ChromaDB. Marked 'failed' in SQLite.")
            failed_count += 1

    print("\n" + "=" * 60)
    print("Migration Summary:")
    print(f"  Total Processed: {len(items)}")
    print(f"  Successfully Synced: {synced_count}")
    print(f"  Failed: {failed_count}")
    print(f"  ChromaDB Indexed Total: {vector_store.count()} items")
    print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate and synchronize SQLite records to ChromaDB")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate ChromaDB collection from scratch before migration"
    )
    parser.add_argument(
        "--repair-only",
        action="store_true",
        help="Only process items marked 'pending' or 'failed' in SQLite"
    )
    args = parser.parse_args()

    migrate(recreate_collection=args.recreate, repair_only=args.repair_only)
