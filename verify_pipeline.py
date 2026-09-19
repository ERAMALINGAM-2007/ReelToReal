"""
Verification test script for ReelToReal processing pipeline components.
"""
import sys
import io

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json
from pathlib import Path
from app.config import settings
from app.models.schema import VideoAnalysisResult, CategoryEnum, Entities, HealthResponse
from app.services.gemini_analyzer import GeminiVideoAnalyzer
from app.services.video_downloader import VideoDownloader, VideoDownloadError

def test_schema_serialization():
    print("[1/4] Testing Schema validation & serialization...")
    sample_data = {
        "title": "Hidden Ramen Gem in Shinjuku",
        "category": "food",
        "transcript_summary": "Creator talks about 12-hour simmered tonkotsu broth with handmade noodles.",
        "visual_summary": "Steaming bowl of chashu ramen, vibrant neon alleyway exterior, wooden bar seating.",
        "entities": {
            "place_name": "Ramen Nagi Shinjuku",
            "city": "Tokyo",
            "address_or_area": "Golden Gai, Shinjuku",
            "cuisine_or_type": "Tonkotsu Ramen",
            "price_cues": "¥1,100 (~$8 USD)",
            "best_time_to_visit": "After 10pm or before 6pm to avoid line",
            "highlights": ["Special niboshi broth", "Thick pork chashu"],
            "actionable_tips": ["Buy ticket at vending machine before sitting", "Cash only"]
        },
        "tags": ["ramen", "tokyo", "foodie", "budget-friendly", "dinner"],
        "search_blob": "Hidden Ramen Gem in Shinjuku | Food | Ramen Nagi Shinjuku | Tokyo | Tonkotsu Ramen | 12-hour broth | Golden Gai | Cash only",
        "confidence_notes": "High confidence based on clear on-screen signage and spoken menu items."
    }

    result = VideoAnalysisResult.model_validate(sample_data)
    assert result.category == CategoryEnum.FOOD
    assert result.entities.place_name == "Ramen Nagi Shinjuku"
    assert len(result.entities.highlights) == 2
    assert len(result.entities.actionable_tips) == 2
    print("  [OK] Schema validated successfully!")

def test_gemini_json_parser():
    print("[2/4] Testing Gemini response parser...")
    analyzer = GeminiVideoAnalyzer(api_key="mock_key_for_parser_test")
    raw_json_markdown = """```json
    {
      "title": "Top 3 Sunset Spots in Santorini",
      "category": "travel",
      "transcript_summary": "Guide highlights the best views avoiding Oia crowds.",
      "visual_summary": "Whitewashed cliffs, deep blue sea, caldera view at dusk.",
      "entities": {
        "place_name": "Imerovigli Caldera Edge",
        "city": "Santorini",
        "address_or_area": "Imerovigli",
        "cuisine_or_type": "Scenic Viewpoint",
        "price_cues": "Free",
        "best_time_to_visit": "6:30 PM",
        "highlights": ["Skaros Rock view", "Quiet terrace"],
        "actionable_tips": ["Arrive 45 mins before sunset to find a spot"]
      },
      "tags": ["travel", "santorini", "greece", "sunset"],
      "search_blob": "",
      "confidence_notes": null
    }
    ```"""
    parsed = analyzer._parse_and_validate_json(raw_json_markdown)
    assert parsed.title == "Top 3 Sunset Spots in Santorini"
    assert parsed.category == CategoryEnum.TRAVEL
    assert parsed.entities.place_name == "Imerovigli Caldera Edge"
    assert len(parsed.search_blob) > 0  # Auto-generated
    print("  [OK] Parser handled markdown code blocks and auto-generated search_blob successfully!")

def test_downloader_fallback():
    print("[3/4] Testing VideoDownloader fallback error handling...")
    try:
        VideoDownloader.download_video_from_url("https://invalid-non-existent-url-domain.xyz/reel/12345")
        assert False, "Should have thrown VideoDownloadError"
    except VideoDownloadError as e:
        assert "upload" in e.user_friendly_message.lower()
        print("  [OK] Graceful fallback error message verified!")

def test_mime_resolution():
    print("[4/5] Testing MIME type resolution for Gemini upload...")
    from app.services.gemini_analyzer import resolve_media_mime_type
    assert resolve_media_mime_type(Path("sample.mp4")) == "video/mp4"
    assert resolve_media_mime_type(Path("sample.webm")) == "video/webm"
    assert resolve_media_mime_type(Path("sample.mkv")) == "video/x-matroska"
    assert resolve_media_mime_type(Path("sample.mov")) == "video/quicktime"
    assert resolve_media_mime_type(Path("sample.unknown_ext")) == "video/mp4"
    print("  [OK] MIME type resolution handles all formats and Windows fallbacks correctly!")

def test_config_and_health():
    print("[5/5] Testing configuration and directories...")
    assert settings.TEMP_VIDEO_DIR.exists()
    health = HealthResponse(
        status="healthy",
        gemini_api_configured=settings.has_gemini_key(),
        model_configured=settings.GEMINI_MODEL,
        embedding_model_configured=settings.GEMINI_EMBEDDING_MODEL,
        total_saved_items=0,
        temp_dir=str(settings.TEMP_VIDEO_DIR)
    )
    print(f"  [OK] Health status: {health.status}, Gemini configured: {health.gemini_api_configured}")

if __name__ == "__main__":
    print("Running ReelToReal Pipeline Tests...\n" + "="*45)
    test_schema_serialization()
    test_gemini_json_parser()
    test_downloader_fallback()
    test_mime_resolution()
    test_config_and_health()
    print("="*45 + "\nALL 5 TESTS PASSED SUCCESSFULLY! [OK]")
