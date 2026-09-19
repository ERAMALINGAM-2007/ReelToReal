"""
Comprehensive ChromaDB Integration & Vector Synchronization Test Suite for ReelToReal.
Verifies:
1. ChromaDB initialization, cosine space, and fixed 768 dimensions.
2. Insertion & Semantic Vector Retrieval.
3. Strict Double User Isolation (Chroma where + SQLite verification).
4. Update flow: full search_blob rebuild & vector re-embedding.
5. Deletion synchronization across SQLite and ChromaDB.
6. Persistence across app restart (re-instantiated VectorStoreService).
7. Failed synchronization recovery (reconciliation / repair).
8. End-to-end RAG Planner execution with ChromaDB retrieval.
"""
import sys
import io
import shutil
import tempfile
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.config import settings
from app.models.schema import (
    VideoAnalysisResult,
    CategoryEnum,
    Entities,
    PlanQueryRequest,
    ChatMessage
)
from app.services.storage_service import StorageService
from app.services.embedding_service import EmbeddingService
from app.services.vector_store_service import VectorStoreService
from app.services.rag_planner import RAGPlannerService

def run_tests():
    print("=" * 65)
    print("Running ReelToReal ChromaDB Vector Store Test Suite")
    print("=" * 65)

    # Use isolated test directory for database and chroma to avoid polluting production data
    test_dir = Path(tempfile.mkdtemp(prefix="reeltoreal_test_"))
    test_db = test_dir / "test_reeltoreal.db"
    test_chroma = test_dir / "test_chroma_db"

    try:
        storage = StorageService(db_path=test_db)
        vector_store = VectorStoreService(chroma_dir=test_chroma)
        embedder = EmbeddingService()
        planner = RAGPlannerService(
            embedding_service=embedder,
            storage_service=storage,
            vector_store=vector_store
        )

        # -------------------------------------------------------------
        # Test 1: Fixed 768 Dimensions & Collection Metadata
        # -------------------------------------------------------------
        print("\n[Test 1/8] Verifying Fixed 768 Dimensions & Collection Metadata...")
        col_meta = vector_store.collection.metadata
        assert col_meta.get("hnsw:space") == "cosine", f"Expected cosine space, got {col_meta.get('hnsw:space')}"
        assert col_meta.get("embedding_dimensions") == 768, f"Expected 768 dims in metadata, got {col_meta.get('embedding_dimensions')}"
        
        # Test vector generation
        dummy_vec = embedder.generate_embedding("Tokyo ramen test", output_dimensionality=768)
        assert len(dummy_vec) == 768, f"Expected 768 dims vector, got {len(dummy_vec)}"
        print("  [PASS] ChromaDB collection configured with cosine space and 768 fixed dimensions.")

        # -------------------------------------------------------------
        # Test 2: Insertion & Semantic Retrieval
        # -------------------------------------------------------------
        print("\n[Test 2/8] Testing Insertion & Semantic Retrieval...")
        analysis_ramen = VideoAnalysisResult(
            title="Legendary Shinjuku Tonkotsu Ramen",
            category=CategoryEnum.FOOD,
            transcript_summary="Rich pork bone broth simmered for 12 hours with garlic and tender chashu.",
            visual_summary="Steaming bowl of creamy broth, handmade noodles, cozy wooden counter.",
            entities=Entities(
                place_name="Tatsunoya",
                city="Tokyo",
                address_or_area="Shinjuku",
                cuisine_or_type="Tonkotsu Ramen",
                highlights=["Garlic Tsukemen"],
                actionable_tips=["Cash only vending machine"]
            ),
            tags=["ramen", "shinjuku", "tokyo", "noodles"],
            search_blob="Legendary Shinjuku Tonkotsu Ramen | Food | Tatsunoya | Tokyo | Garlic Tsukemen | Cash only"
        )
        
        # Save in SQLite
        saved_item = storage.save_item(
            item_id="item_test_ramen",
            source_type="file_upload",
            source_identifier="ramen_clip.mp4",
            analysis=analysis_ramen,
            embedding=dummy_vec,
            user_id="user_alice",
            vector_sync_status="pending"
        )
        assert saved_item.vector_sync_status == "pending"

        # Upsert in ChromaDB
        ok = vector_store.upsert_item(
            item_id=saved_item.id,
            user_id="user_alice",
            search_blob=saved_item.analysis.search_blob,
            embedding=dummy_vec,
            metadata={
                "user_id": "user_alice",
                "title": saved_item.analysis.title,
                "category": saved_item.analysis.category.value,
                "place_name": saved_item.analysis.entities.place_name,
                "city": saved_item.analysis.entities.city,
                "created_at": saved_item.created_at
            }
        )
        assert ok is True
        storage.update_sync_status(saved_item.id, "synced")
        assert vector_store.count("user_alice") == 1

        # Search with same query vector
        hits = vector_store.search(user_id="user_alice", query_embedding=dummy_vec, top_k=3)
        assert len(hits) == 1
        assert hits[0][0] == "item_test_ramen"
        assert hits[0][1] > 0.99  # Identical vector cosine similarity ~ 1.0
        print(f"  [PASS] Successfully retrieved item '{hits[0][0]}' with similarity {hits[0][1]:.4f}.")

        # -------------------------------------------------------------
        # Test 3: Strict Double User Isolation
        # -------------------------------------------------------------
        print("\n[Test 3/8] Testing Strict Double User Isolation...")
        # User Bob searches with Alice's query vector
        bob_hits = vector_store.search(user_id="user_bob", query_embedding=dummy_vec, top_k=5)
        assert len(bob_hits) == 0, f"User isolation breached in ChromaDB! Bob received: {bob_hits}"

        # SQLite secondary check: even if Bob somehow knew Alice's ID, SQLite rejects it
        bob_sqlite_item = storage.get_item_by_id("item_test_ramen", user_id="user_bob")
        assert bob_sqlite_item is None, "User isolation breached in SQLite!"
        print("  [PASS] Double isolation verified: Bob cannot retrieve Alice's items from Chroma or SQLite.")

        # -------------------------------------------------------------
        # Test 4: Update Flow (Search Blob Rebuild & Re-embedding)
        # -------------------------------------------------------------
        print("\n[Test 4/8] Testing Edit Flow & Search Blob Rebuild...")
        # Update notes and tags
        updated = storage.update_item(
            item_id="item_test_ramen",
            user_id="user_alice",
            personal_notes="Must try the spicy level 3!",
            tags=["ramen", "shinjuku", "spicy"]
        )
        assert "Notes: Must try the spicy level 3!" in updated.analysis.search_blob
        assert "Tags: ramen, shinjuku, spicy" in updated.analysis.search_blob

        # Re-embed updated content
        new_vec = embedder.generate_embedding(updated.analysis.search_blob, output_dimensionality=768)
        assert len(new_vec) == 768
        
        vector_store.update_item(
            item_id="item_test_ramen",
            user_id="user_alice",
            search_blob=updated.analysis.search_blob,
            embedding=new_vec,
            metadata={
                "user_id": "user_alice",
                "title": updated.analysis.title,
                "category": updated.analysis.category.value,
                "place_name": updated.analysis.entities.place_name,
                "city": updated.analysis.entities.city,
                "created_at": updated.created_at
            }
        )
        # Verify updated item is searchable with new query
        spicy_query_vec = embedder.generate_embedding("spicy ramen level 3", output_dimensionality=768)
        updated_hits = vector_store.search(user_id="user_alice", query_embedding=spicy_query_vec, top_k=1)
        assert len(updated_hits) == 1
        assert updated_hits[0][0] == "item_test_ramen"
        print("  [PASS] Edit flow successfully rebuilt search blob, re-embedded, and updated ChromaDB.")

        # -------------------------------------------------------------
        # Test 5: Deletion Synchronization
        # -------------------------------------------------------------
        print("\n[Test 5/8] Testing Deletion Synchronization...")
        # Create temporary item to delete
        storage.save_item(
            item_id="item_to_delete",
            source_type="url",
            source_identifier="https://example.com/reel/1",
            analysis=analysis_ramen,
            embedding=dummy_vec,
            user_id="user_alice"
        )
        vector_store.upsert_item(
            item_id="item_to_delete",
            user_id="user_alice",
            search_blob="Temporary item",
            embedding=dummy_vec
        )
        assert vector_store.count("user_alice") == 2

        # Delete from both
        storage.delete_item("item_to_delete", user_id="user_alice")
        vector_store.delete_item("item_to_delete")

        assert storage.get_item_by_id("item_to_delete") is None
        assert vector_store.count("user_alice") == 1
        print("  [PASS] Item removed cleanly from both SQLite and ChromaDB.")

        # -------------------------------------------------------------
        # Test 6: Persistence Across App Restart
        # -------------------------------------------------------------
        print("\n[Test 6/8] Testing Persistence Across Service Restart...")
        # Simulate app restart by deleting instance and re-instantiating against the same directory
        del vector_store
        del storage

        restored_storage = StorageService(db_path=test_db)
        restored_vector_store = VectorStoreService(chroma_dir=test_chroma)
        
        assert restored_vector_store.count("user_alice") == 1
        restarted_hits = restored_vector_store.search(
            user_id="user_alice",
            query_embedding=dummy_vec,
            top_k=3
        )
        assert len(restarted_hits) == 1
        assert restarted_hits[0][0] == "item_test_ramen"
        print("  [PASS] VectorStoreService successfully restored index and retrieved items after simulated restart.")

        # -------------------------------------------------------------
        # Test 7: Failed Synchronization Recovery & Reconciliation
        # -------------------------------------------------------------
        print("\n[Test 7/8] Testing Failed Synchronization Recovery...")
        # Create an item in SQLite marked as 'failed' (simulating Chroma failure during upload)
        unsynced_analysis = VideoAnalysisResult(
            title="Secret Kyoto Bamboo Ridge Hike",
            category=CategoryEnum.ACTIVITY,
            transcript_summary="A hidden bamboo trail leading to an incredible scenic view of Kyoto.",
            visual_summary="Tall bamboo grove, tranquil mountain path.",
            entities=Entities(place_name="Arashiyama Trail", city="Kyoto"),
            tags=["hike", "nature", "kyoto"],
            search_blob="Secret Kyoto Bamboo Ridge Hike | Activity | Arashiyama Trail | Kyoto"
        )
        restored_storage.save_item(
            item_id="item_unsynced_hike",
            source_type="file_upload",
            source_identifier="hike.mp4",
            analysis=unsynced_analysis,
            user_id="user_alice",
            vector_sync_status="failed"
        )

        unsynced_list = restored_storage.get_unsynced_items()
        assert any(i.id == "item_unsynced_hike" for i in unsynced_list)
        print(f"  Simulated 1 failed item: '{unsynced_list[0].id}' marked as '{unsynced_list[0].vector_sync_status}'.")

        # Run reconciliation
        for item in restored_storage.get_unsynced_items():
            emb = embedder.generate_embedding(item.analysis.search_blob, output_dimensionality=768)
            ok = restored_vector_store.upsert_item(
                item_id=item.id,
                user_id=item.user_id,
                search_blob=item.analysis.search_blob,
                embedding=emb,
                metadata={
                    "user_id": item.user_id,
                    "title": item.analysis.title,
                    "category": item.analysis.category.value,
                    "place_name": item.analysis.entities.place_name,
                    "city": item.analysis.entities.city,
                    "created_at": item.created_at
                }
            )
            if ok:
                restored_storage.update_sync_status(item.id, "synced")

        # Verify recovery
        assert len(restored_storage.get_unsynced_items()) == 0
        hike_item = restored_storage.get_item_by_id("item_unsynced_hike")
        assert hike_item.vector_sync_status == "synced"
        assert restored_vector_store.count("user_alice") == 2
        print("  [PASS] Reconciliation recovered failed item; marked 'synced' and indexed in ChromaDB.")

        # -------------------------------------------------------------
        # Test 8: Full RAG Planner Execution via ChromaDB Retrieval
        # -------------------------------------------------------------
        print("\n[Test 8/8] Testing RAG Planner Execution with ChromaDB Retrieval...")
        restored_planner = RAGPlannerService(
            embedding_service=embedder,
            storage_service=restored_storage,
            vector_store=restored_vector_store
        )

        plan_resp = restored_planner.generate_plan(
            PlanQueryRequest(
                query="Find a great ramen dinner in Shinjuku",
                user_id="user_alice",
                max_items=3
            )
        )
        assert len(plan_resp.citations) > 0
        assert any(c.id == "item_test_ramen" for c in plan_resp.citations)
        print(f"  [PASS] RAG Planner successfully retrieved '{plan_resp.citations[0].title}' via ChromaDB.")
        print(f"  Narrative snippet: {plan_resp.plan_narrative[:100]}...")

        print("\n" + "=" * 65)
        print("ALL 8 CHROMADB INTEGRATION & RESILIENCE TESTS PASSED SUCCESSFULLY! [OK]")
        print("=" * 65)

    finally:
        # Cleanup temporary test directory
        try:
            shutil.rmtree(test_dir)
        except Exception:
            pass

if __name__ == "__main__":
    run_tests()
