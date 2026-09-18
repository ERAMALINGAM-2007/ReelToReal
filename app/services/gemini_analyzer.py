import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import google.generativeai as genai
from app.config import settings
from app.models.schema import VideoAnalysisResult, CategoryEnum, Entities

logger = logging.getLogger(__name__)

class GeminiAnalysisError(Exception):
    """Exception raised for errors during Gemini multimodal analysis."""
    pass

SYSTEM_INSTRUCTION = """
You are an expert AI video intelligence engine for 'ReelToReal', an application that converts saved Instagram Reels, YouTube Shorts, and short-form videos into actionable real-world plans and a personal knowledge base.

Your task is to thoroughly analyze both the AUDIO (spoken speech, dialogue, voiceovers, ambient sounds) and the VISUALS (food dishes, venues, scenery, action, interior/exterior decor, text overlays, captions, subtitles, logos).

You MUST output ONLY a valid JSON object matching the exact schema below:

{
  "title": "<Catchy, highly descriptive 4-10 word title of what this clip is about>",
  "category": "<Must be one of: 'food', 'travel', 'activity', 'fitness', 'shopping', 'product', 'tip', 'other'>",
  "transcript_summary": "<Detailed summary of all spoken words, dialogue, tips, and commentary in the audio. If no speech, describe musical cues or audio atmosphere>",
  "visual_summary": "<Detailed summary of visual frames: dishes shown, storefront, ambiance, aesthetics, actions, and especially any on-screen text overlays, titles, or prices>",
  "entities": {
    "place_name": "<Exact business, restaurant, café, peak, beach, or venue name, or null if unspecified>",
    "city": "<City, state, or country, or null if unknown>",
    "address_or_area": "<Specific neighborhood, district, street, or landmark if visible or mentioned, or null>",
    "cuisine_or_type": "<Specific cuisine (e.g. Tonkotsu Ramen, Neapolitan Pizza) or activity type (e.g. Coastal Hike, Pottery Workshop), or null>",
    "price_cues": "<Prices mentioned or visible, e.g. '$15-$25/person', 'Free entry', '$$$', or null>",
    "best_time_to_visit": "<Recommended timing, e.g. 'Sunset', 'Weekdays before 12pm to avoid queue', or null>",
    "highlights": ["<List of specific must-try dishes, scenic spots, or notable features shown/mentioned>"],
    "actionable_tips": ["<List of practical tips: e.g. 'reservations mandatory', 'cash only', 'secret entrance on 2nd floor', 'bring hiking shoes'>"]
  },
  "tags": ["<5 to 10 relevant keywords for filtering and search, e.g. 'ramen', 'tokyo', 'dinner', 'rainy day', 'solo dining'>"],
  "search_blob": "<A rich, dense paragraph combining the title, category, place, city, cuisine, transcript insights, and visual details. This text is embedded for semantic vector search and AI planning>",
  "confidence_notes": "<Brief assessment of clarity or any unverified assumptions, or null>"
}
"""

class GeminiVideoAnalyzer:
    """
    Handles native multimodal video & audio processing using Google Gemini Files API.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if self.api_key and self.api_key.strip() and self.api_key != "your_gemini_api_key_here":
            genai.configure(api_key=self.api_key)
            self._configured = True
        else:
            self._configured = False

    def is_configured(self) -> bool:
        return self._configured

    def analyze_video_file(
        self,
        video_path: Path,
        model_name: Optional[str] = None,
        max_wait_seconds: int = 120
    ) -> VideoAnalysisResult:
        """
        Uploads the video file to Gemini via Files API, waits for processing,
        prompts the model for multimodal understanding, and parses the structured response.
        """
        if not self.is_configured():
            raise GeminiAnalysisError(
                "Gemini API key is not configured. Please add your GEMINI_API_KEY in the .env file or environment."
            )

        if not video_path.exists():
            raise GeminiAnalysisError(f"Video file not found at path: {video_path}")

        primary_model = model_name or settings.GEMINI_MODEL
        uploaded_file = None

        try:
            logger.info(f"Uploading video file to Gemini Files API: {video_path.name}")
            uploaded_file = genai.upload_file(path=str(video_path))
            logger.info(f"File uploaded to Gemini as '{uploaded_file.name}'. Waiting for processing...")

            # Wait for the file to be processed and ready for inference
            start_time = time.time()
            while uploaded_file.state.name == "PROCESSING":
                if time.time() - start_time > max_wait_seconds:
                    raise GeminiAnalysisError(f"Gemini video processing timed out after {max_wait_seconds}s")
                time.sleep(3)
                uploaded_file = genai.get_file(uploaded_file.name)

            if uploaded_file.state.name == "FAILED":
                raise GeminiAnalysisError(f"Gemini failed to process video file: {uploaded_file.name}")

            logger.info(f"Video is ACTIVE and ready on Gemini. Sending multimodal reasoning prompt...")

            # Define candidate models in order of priority
            model_candidates = [primary_model, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
            # Deduplicate while preserving order
            model_candidates = list(dict.fromkeys(model_candidates))

            last_error = None
            response_text = None

            for candidate in model_candidates:
                try:
                    logger.info(f"Trying Gemini model: {candidate}")
                    model = genai.GenerativeModel(
                        model_name=candidate,
                        system_instruction=SYSTEM_INSTRUCTION,
                        generation_config={
                            "response_mime_type": "application/json",
                            "temperature": 0.2,
                        }
                    )

                    prompt = (
                        "Analyze this video clip completely. Understand all spoken audio, music, visual scenes, "
                        "on-screen text, foods, places, and activities. "
                        "Extract all structured entities and actionable details into the required JSON schema."
                    )

                    response = model.generate_content([uploaded_file, prompt])
                    response_text = response.text
                    if response_text:
                        logger.info(f"Successfully received analysis from {candidate}")
                        break
                except Exception as model_err:
                    logger.warning(f"Model {candidate} encountered an error: {model_err}")
                    last_error = model_err
                    continue

            if not response_text:
                raise GeminiAnalysisError(f"Failed to generate content with available Gemini models: {last_error}")

            return self._parse_and_validate_json(response_text)

        except Exception as e:
            logger.error(f"Error in Gemini video analysis: {e}")
            if isinstance(e, GeminiAnalysisError):
                raise
            raise GeminiAnalysisError(f"Video analysis failed: {str(e)}")

        finally:
            # Conserve Gemini storage quota by cleaning up the uploaded file
            if uploaded_file:
                try:
                    genai.delete_file(uploaded_file.name)
                    logger.info(f"Deleted temporary Gemini remote file: {uploaded_file.name}")
                except Exception as del_err:
                    logger.warning(f"Could not delete remote Gemini file {uploaded_file.name}: {del_err}")

    def _parse_and_validate_json(self, raw_json_str: str) -> VideoAnalysisResult:
        """Parses the JSON response and validates it against the Pydantic schema."""
        try:
            # Strip markdown code blocks if present
            cleaned = raw_json_str.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data: Dict[str, Any] = json.loads(cleaned)

            # Ensure valid category
            cat_str = str(data.get("category", "other")).lower()
            valid_cats = [c.value for c in CategoryEnum]
            if cat_str not in valid_cats:
                cat_str = "other"
            data["category"] = cat_str

            # Ensure entities dict exists
            if "entities" not in data or not isinstance(data["entities"], dict):
                data["entities"] = {}

            # Construct search_blob if missing or empty
            if not data.get("search_blob"):
                entities = data["entities"]
                blob_parts = [
                    f"Title: {data.get('title', '')}",
                    f"Category: {data.get('category', '')}",
                    f"Place: {entities.get('place_name', '')}",
                    f"City: {entities.get('city', '')}",
                    f"Cuisine/Type: {entities.get('cuisine_or_type', '')}",
                    f"Transcript: {data.get('transcript_summary', '')}",
                    f"Visuals: {data.get('visual_summary', '')}",
                    f"Highlights: {', '.join(entities.get('highlights', []))}",
                    f"Tips: {', '.join(entities.get('actionable_tips', []))}",
                    f"Tags: {', '.join(data.get('tags', []))}"
                ]
                data["search_blob"] = " | ".join([p for p in blob_parts if p])

            return VideoAnalysisResult.model_validate(data)

        except Exception as e:
            logger.error(f"Failed to parse Gemini JSON output: {e}\nRaw output: {raw_json_str}")
            raise GeminiAnalysisError(f"Could not validate structured model response: {e}")
