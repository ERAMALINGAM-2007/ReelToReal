import json
import time
import logging
import mimetypes
from pathlib import Path
from typing import Optional, Dict, Any, List
import google.generativeai as genai
from app.config import settings
from app.models.schema import VideoAnalysisResult, CategoryEnum, Entities, TimelineEvent

logger = logging.getLogger(__name__)

MIME_TYPE_MAPPING = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv",
    ".3gp": "video/3gpp",
    ".ts": "video/mp2t",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
    ".ogv": "video/ogg",
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}

def resolve_media_mime_type(file_path: Path) -> str:
    """Robustly determines the MIME type for media uploads, avoiding Windows registry lookup issues."""
    ext = file_path.suffix.lower()
    if ext in MIME_TYPE_MAPPING:
        return MIME_TYPE_MAPPING[ext]
    guessed, _ = mimetypes.guess_type(str(file_path))
    if guessed:
        return guessed
    return "video/mp4"

class GeminiAnalysisError(Exception):
    """Exception raised for errors during Gemini multimodal analysis."""
    pass

SYSTEM_INSTRUCTION = """
You are the master multimodal video understanding intelligence engine for 'ReelToReal'.

CRITICAL DIRECTIVE: YOUR ANALYSIS MUST BE 100% EXHAUSTIVE, DETAILED, AND COMPLETE.
Do NOT simply give a high-level summary. If a vlogger or creator covers their entire day, multi-stop tour, multiple activities, or a complex routine, YOU MUST CAPTURE EVERY SINGLE THING that occurs in both AUDIO and VISUALS from the first second (0:00) to the last second of the clip.

You MUST extract and output ONLY a valid JSON object matching the exact schema below:

{
  "title": "<Catchy, highly descriptive 4-10 word title capturing the entire clip>",
  "category": "<Must be one of: 'food', 'travel', 'activity', 'fitness', 'shopping', 'product', 'tip', 'other'>",
  "transcript_summary": "<Comprehensive overview of all speech, commentary, dialogue, voiceover, and musical cues>",
  "full_audio_transcript": "<Near-verbatim, exhaustive breakdown of EVERYTHING said, explained, or discussed by the speaker(s) across the whole video>",
  "visual_summary": "<Exhaustive summary of all visual scenes, outfits, camera movements, decor, lighting, foods, actions, and on-screen text overlays/captions>",
  "timeline_events": [
    {
      "time_or_sequence": "<e.g. '0:00 - 0:12 / Morning', '0:13 - 0:30 / Midday', '0:31 - 0:50 / Evening'>",
      "activity": "<Detailed description of what the person is doing or demonstrating in this specific segment>",
      "location": "<Exact venue, restaurant, room, park, shop, or location name, or null>",
      "audio_details": "<What is being said, explained, or heard in the audio during this specific segment>",
      "visual_details": "<What is visually seen: items used, food dishes, decor, clothes, on-screen text, brand names, visual actions>"
    }
  ],
  "all_places_visited": [
    "<List of EVERY single place, venue, cafe, store, landmark, or location visited or shown>"
  ],
  "all_products_or_items": [
    "<List of EVERY food item, drink, beauty product, tool, piece of clothing, or gadget featured>"
  ],
  "entities": {
    "place_name": "<Primary business, restaurant, café, viewpoint, landmark, or venue name, or null if multiple/unspecified>",
    "city": "<City, region, or country, or null if unknown>",
    "address_or_area": "<Specific neighborhood, district, or street if mentioned or shown, or null>",
    "cuisine_or_type": "<Specific cuisine type (e.g. Japanese Ramen) or activity type (e.g. Daily Vlog, Skincare Routine, Bouldering), or null>",
    "price_cues": "<Prices, budget indicators, entry costs, or price tags mentioned/shown, or null>",
    "best_time_to_visit": "<Timing, opening hours, or best time mentioned, or null>",
    "highlights": [
      "<List of all notable moments, must-try dishes, key steps, or standout features>"
    ],
    "actionable_tips": [
      "<List of ALL actionable tips, life hacks, advice, warnings, or recommendations given in the video>"
    ]
  },
  "tags": [
    "<8 to 15 relevant searchable tags covering all activities, locations, vibes, and topics in the video>"
  ],
  "search_blob": "<A dense, comprehensive textual compilation of title, timeline activities, transcript, places, products, and tips for vector search>",
  "confidence_notes": "<Brief assessment of clarity or audio/video fidelity, or null>"
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
        prompts the model for exhaustive multimodal understanding, and parses the structured response.
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
            mime_type = resolve_media_mime_type(video_path)
            logger.info(f"Uploading video file to Gemini Files API: {video_path.name} (mime_type: {mime_type})")
            uploaded_file = genai.upload_file(path=str(video_path), mime_type=mime_type)
            logger.info(f"File uploaded to Gemini as '{uploaded_file.name}'. Waiting for processing...")

            start_time = time.time()
            while uploaded_file.state.name == "PROCESSING":
                if time.time() - start_time > max_wait_seconds:
                    raise GeminiAnalysisError(f"Gemini video processing timed out after {max_wait_seconds}s")
                time.sleep(3)
                uploaded_file = genai.get_file(uploaded_file.name)

            if uploaded_file.state.name == "FAILED":
                raise GeminiAnalysisError(f"Gemini failed to process video file: {uploaded_file.name}")

            logger.info("Video is ACTIVE and ready on Gemini. Sending exhaustive multimodal reasoning prompt...")

            # Define candidate models in order of priority, using active Google Generative AI v1beta models
            model_candidates = [
                primary_model,
                "gemini-3.8-flash",
                "gemini-3.5-flash",
                "gemini-3.6-flash",
                "gemini-3.7-flash",
                "gemini-2.5-flash"
            ]
            model_candidates = list(dict.fromkeys(model_candidates))

            last_error = None
            response_text = None
            encountered_quota = False

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
                        "Perform an EXHAUSTIVE, COMPLETE analysis of this video clip. "
                        "Do not leave anything out. Break down every single sequential scene, activity, routine step, "
                        "conversation, dish, product, location, and spoken insight from 0:00 to the end into the 'timeline_events' array. "
                        "Extract all places visited, all products shown, and all actionable tips into the strict JSON schema."
                    )

                    response = model.generate_content([uploaded_file, prompt])
                    if response and response.text:
                        response_text = response.text
                        logger.info(f"Successfully received analysis from {candidate}")
                        break
                except Exception as model_err:
                    err_str = str(model_err)
                    if "429" in err_str or "ResourceExhausted" in type(model_err).__name__:
                        encountered_quota = True
                    logger.warning(f"Model {candidate} encountered an error: {model_err}")
                    last_error = model_err
                    continue

            if not response_text:
                if encountered_quota:
                    raise GeminiAnalysisError(
                        f"Gemini API free tier quota limit reached (429 ResourceExhausted). "
                        f"Please wait for your free-tier daily quota to reset or upgrade your Google AI Studio key: {last_error}"
                    )
                raise GeminiAnalysisError(f"Failed to generate content with available Gemini models: {last_error}")

            return self._parse_and_validate_json(response_text)

        except Exception as e:
            logger.error(f"Error in Gemini video analysis: {e}")
            if isinstance(e, GeminiAnalysisError):
                raise
            raise GeminiAnalysisError(f"Video analysis failed: {str(e)}")

        finally:
            if uploaded_file:
                try:
                    genai.delete_file(uploaded_file.name)
                    logger.info(f"Deleted temporary Gemini remote file: {uploaded_file.name}")
                except Exception as del_err:
                    logger.warning(f"Could not delete remote Gemini file {uploaded_file.name}: {del_err}")

    def _parse_and_validate_json(self, raw_json_str: str) -> VideoAnalysisResult:
        """Parses the JSON response and validates it against the Pydantic schema."""
        try:
            cleaned = raw_json_str.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data: Dict[str, Any] = json.loads(cleaned)

            cat_str = str(data.get("category", "other")).lower()
            valid_cats = [c.value for c in CategoryEnum]
            if cat_str not in valid_cats:
                cat_str = "other"
            data["category"] = cat_str

            if "entities" not in data or not isinstance(data["entities"], dict):
                data["entities"] = {}

            if "timeline_events" not in data or not isinstance(data["timeline_events"], list):
                data["timeline_events"] = []

            if "all_places_visited" not in data or not isinstance(data["all_places_visited"], list):
                data["all_places_visited"] = []

            if "all_products_or_items" not in data or not isinstance(data["all_products_or_items"], list):
                data["all_products_or_items"] = []

            # Auto-construct search_blob if missing or empty
            if not data.get("search_blob"):
                entities = data["entities"]
                timeline_summary = " ; ".join([
                    f"[{t.get('time_or_sequence', '')}] {t.get('activity', '')}: {t.get('audio_details', '')} ({t.get('visual_details', '')})"
                    for t in data["timeline_events"]
                ])
                blob_parts = [
                    f"Title: {data.get('title', '')}",
                    f"Category: {data.get('category', '')}",
                    f"Place: {entities.get('place_name', '')}",
                    f"City: {entities.get('city', '')}",
                    f"All Places: {', '.join(data.get('all_places_visited', []))}",
                    f"All Products: {', '.join(data.get('all_products_or_items', []))}",
                    f"Timeline: {timeline_summary}",
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
