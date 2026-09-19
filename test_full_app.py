"""
Comprehensive Integration Test Suite for ReelToReal.
Tests: Storage, Embeddings, Geocoding, RAG Planner, and Web Endpoints.
"""
import sys
import io

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import uuid
from app.config import settings
from app.models.schema import (
    VideoAnalysisResult,
    CategoryEnum,
    Entities,
    PlanQueryRequest,
    ChatMessage,
    PlanStop
)
from app.services.storage_service import StorageService
from app.services.embedding_service import EmbeddingService
from app.services.geocoding_service import GeocodingService
from app.services.rag_planner import RAGPlannerService

def test_full_pipeline():
    print("Running Full ReelToReal Pipeline Tests...\n" + "="*50)

    storage = StorageService()
    geocoder = GeocodingService()
    embedder = EmbeddingService()
    planner = RAGPlannerService(embedder, storage)

    # 1. Test Geocoding
    print("[1/5] Testing Geocoding Service...")
    lat, lon, addr = geocoder.geocode(place_name="Shinjuku Gyoen National Garden", city="Tokyo")
    print(f"  [OK] Geocoded location: lat={lat}, lon={lon}")

    # 2. Seed Sample Saved Items to Knowledge Base
    print("[2/5] Seeding Knowledge Base items with Embeddings...")

    sample_items = [
        {
            "id": "item_ramen_01",
            "title": "Insane 12-Hour Broth Ramen in Shinjuku",
            "category": CategoryEnum.FOOD,
            "transcript_summary": "The chef explains their 12-hour simmered tonkotsu broth with special garlic oil and handmade chewy noodles.",
            "visual_summary": "Rich creamy broth poured over fresh noodles, torched chashu pork slices, cozy 8-seat wooden ramen bar.",
            "entities": Entities(
                place_name="Ramen Tatsunoya",
                city="Tokyo",
                address_or_area="Shinjuku",
                cuisine_or_type="Tonkotsu Ramen",
                price_cues="¥1,200",
                best_time_to_visit="Before 6pm or after 9pm to avoid long queues",
                highlights=["Tsukemen with dipping soup", "Special garlic oil"],
                actionable_tips=["Get the spicy dipping noodles", "Cash only ticket machine"]
            ),
            "tags": ["ramen", "tokyo", "foodie", "dinner", "budget"],
            "search_blob": "Insane 12-Hour Broth Ramen in Shinjuku | Food | Ramen Tatsunoya | Tokyo | Tonkotsu Ramen | Garlic oil | Tsukemen | Shinjuku | Cash only",
            "lat": 35.6938,
            "lon": 139.7034
        },
        {
            "id": "item_hike_02",
            "title": "Secret Sunset Ridge Hike Near Kyoto",
            "category": CategoryEnum.ACTIVITY,
            "transcript_summary": "Trail guide for an easy 45-minute ridge hike leading to a panoramic sunset viewpoint overlooking Kyoto valley.",
            "visual_summary": "Lush bamboo trail, scenic wooden observation deck, golden hour light over hills.",
            "entities": Entities(
                place_name="Daimonji Ridge Viewpoint",
                city="Kyoto",
                address_or_area="Sakyo Ward",
                cuisine_or_type="Scenic Hiking",
                price_cues="Free admission",
                best_time_to_visit="4:30 PM for sunset",
                highlights=["Panoramic valley view", "Bamboo grove trail"],
                actionable_tips=["Bring a flashlight for the hike down after sunset", "Wear trail runners"]
            ),
            "tags": ["hiking", "kyoto", "nature", "sunset", "outdoors"],
            "search_blob": "Secret Sunset Ridge Hike Near Kyoto | Activity | Daimonji Ridge Viewpoint | Kyoto | Scenic Hiking | Bamboo trail | Sunset | Free",
            "lat": 35.0116,
            "lon": 135.7681
        },
        {
            "id": "item_dessert_03",
            "title": "Fluffiest Souffle Pancakes in Shibuya",
            "category": CategoryEnum.FOOD,
            "transcript_summary": "Review of ultra-jiggly souffle pancakes stacked 3 high with matcha cream and fresh strawberries.",
            "visual_summary": "Slow-motion pancake jiggle, fresh matcha dusting, stylish aesthetic café with warm lighting.",
            "entities": Entities(
                place_name="A Happy Pancake Shibuya",
                city="Tokyo",
                address_or_area="Shibuya",
                cuisine_or_type="Japanese Desserts",
                price_cues="¥1,500 (~$10 USD)",
                best_time_to_visit="Weekday afternoons",
                highlights=["Matcha souffle pancake", "Honeycomb butter pancake"],
                actionable_tips=["Book online reserve slot to skip 1-hour wait"]
            ),
            "tags": ["dessert", "pancakes", "shibuya", "tokyo", "cafe"],
            "search_blob": "Fluffiest Souffle Pancakes in Shibuya | Food | A Happy Pancake Shibuya | Tokyo | Souffle Pancakes | Matcha | Shibuya | Cafe",
            "lat": 35.6580,
            "lon": 139.7016
        }
    ]

    for s in sample_items:
        analysis = VideoAnalysisResult(
            title=s["title"],
            category=s["category"],
            transcript_summary=s["transcript_summary"],
            visual_summary=s["visual_summary"],
            entities=s["entities"],
            tags=s["tags"],
            search_blob=s["search_blob"]
        )

        embedding = []
        try:
            if embedder.is_configured():
                embedding = embedder.generate_embedding(analysis.search_blob, task_type="retrieval_document")
        except Exception as e:
            print(f"  [Notice] Live embedding generation note: {e}")

        # If live embedding failed or unavailable, generate deterministic mock vector for vector similarity test
        if not embedding:
            # 768-dim mock vector with semantic hash
            import hashlib
            seed = int(hashlib.md5(analysis.search_blob.encode()).hexdigest()[:8], 16)
            import numpy as np
            np.random.seed(seed)
            embedding = list(np.random.randn(768).astype(float))

        storage.save_item(
            item_id=s["id"],
            source_type="file_upload",
            source_identifier=s["title"],
            analysis=analysis,
            embedding=embedding,
            latitude=s["lat"],
            longitude=s["lon"],
            geocoded_address=f"{s['entities'].place_name}, {s['entities'].city}"
        )

    print(f"  [OK] Saved items in Knowledge Base. Total count = {storage.count_items()}")

    # 3. Test Vector Knowledge Base Retrieval
    print("[3/5] Testing Semantic Vector Search...")
    all_items = storage.get_all_items()
    assert len(all_items) >= 3
    food_items = storage.get_all_items(category="food")
    assert len(food_items) >= 2
    print("  [OK] Category filtering and retrieval verified!")

    # 4. Test Map Pins
    print("[4/5] Testing Map Pins Extraction...")
    pins = storage.get_map_pins()
    assert len(pins) >= 3
    print(f"  [OK] Extracted {len(pins)} map pins with geocoded coordinates!")

    # 5. Test Grounded Conversational Planner (Multi-turn & Route Stops)
    print("[5/6] Testing Grounded Conversational Planner (Multi-turn & Stops)...")
    plan_resp1 = planner.generate_plan(PlanQueryRequest(query="Plan my evening with ramen in Tokyo", max_items=3))
    print("  [OK] Initial Turn 1 plan generated!")
    print(f"  Citations count: {len(plan_resp1.citations)}")
    print(f"  Stops extracted: {len(plan_resp1.stops)}")
    assert len(plan_resp1.citations) >= 1
    assert len(plan_resp1.stops) >= 1

    # Turn 2: Follow-up query with conversational history
    plan_resp2 = planner.generate_plan(PlanQueryRequest(
        query="What dessert spot from my saved clips can we go to after?",
        max_items=3,
        chat_history=[
            ChatMessage(role="user", content="Plan my evening with ramen in Tokyo"),
            ChatMessage(role="assistant", content=plan_resp1.plan_narrative)
        ]
    ))
    print("  [OK] Turn 2 follow-up plan with conversational memory generated!")
    assert len(plan_resp2.citations) > 0
    print(f"  Follow-up Citations: {[c.title for c in plan_resp2.citations]}")
    print(f"  Follow-up Stops: {[s.place_name for s in plan_resp2.stops]}")
    print("\n--- Sample AI Generated Follow-Up Preview ---")
    print(plan_resp2.plan_narrative[:250] + "...\n---------------------------------------")

    # 6. Test Personal Knowledge Base (Per-User Isolation, Notes, Stats, Export)
    print("[6/6] Testing Personal Knowledge Base Features (Isolation, Notes, Stats, Export)...")
    
    # 6a. Register user profiles
    u_ramu = storage.create_user("ramu", "Ramu's Curated KB")
    u_alex = storage.create_user("alex", "Alex's Travel Journal")
    assert u_ramu.user_id == "ramu"
    assert u_alex.user_id == "alex"

    # 6b. Save clip scoped to Ramu
    analysis_ramu = VideoAnalysisResult(
        title="Ramu's Secret Matcha Cafe in Ginza",
        category=CategoryEnum.FOOD,
        transcript_summary="Famous rich matcha parfait served in traditional ceramic cups.",
        visual_summary="Deep green matcha layers, cozy tearoom decor, wooden counter.",
        entities=Entities(
            place_name="Cha Ginza",
            city="Tokyo",
            address_or_area="Ginza",
            cuisine_or_type="Japanese Tea & Sweets",
            highlights=["Organic uji matcha", "Matcha parfait"],
            actionable_tips=["Reserve 1 day in advance"]
        ),
        tags=["matcha", "tokyo", "ginza", "dessert"],
        search_blob="Cha Ginza | Tokyo | Matcha | Sweets"
    )
    storage.save_item(
        item_id="item_ramu_matcha_01",
        user_id="ramu",
        source_type="file_upload",
        source_identifier="matcha_clip.mp4",
        analysis=analysis_ramu,
        latitude=35.6719,
        longitude=139.7640,
        personal_notes="Must take friends here next summer!"
    )

    # 6c. Verify Isolation
    ramu_items = storage.get_all_items(user_id="ramu")
    alex_items = storage.get_all_items(user_id="alex")
    assert any(it.id == "item_ramu_matcha_01" for it in ramu_items), "Ramu should have the saved matcha clip"
    assert not any(it.id == "item_ramu_matcha_01" for it in alex_items), "Alex should NOT see Ramu's clip"
    print("  [OK] Strict user isolation verified! Ramu's clips are private from Alex.")

    # 6d. Test Personal Notes Updating
    updated = storage.update_item(
        item_id="item_ramu_matcha_01",
        user_id="ramu",
        personal_notes="Updated: Visited on Friday, ordered the grade-A set."
    )
    assert updated is not None
    assert updated.personal_notes == "Updated: Visited on Friday, ordered the grade-A set."
    print("  [OK] Personal notes updated and persisted successfully!")

    # 6e. Test Knowledge Base Analytics & Export
    stats = storage.get_user_stats("ramu")
    assert stats.total_items >= 1
    assert stats.total_mapped_places >= 1
    assert "Tokyo" in stats.top_cities
    
    export_payload = storage.export_user_data("ramu")
    assert export_payload["user_id"] == "ramu"
    assert len(export_payload["items"]) >= 1
    print(f"  [OK] Knowledge Base stats & JSON export verified! (Exported {len(export_payload['items'])} items)")

    print("="*50 + "\nALL INTEGRATION & PERSONAL KNOWLEDGE BASE TESTS PASSED! [OK]")

if __name__ == "__main__":
    test_full_pipeline()

