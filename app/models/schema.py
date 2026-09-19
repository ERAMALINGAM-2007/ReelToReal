from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class CategoryEnum(str, Enum):
    FOOD = "food"
    TRAVEL = "travel"
    ACTIVITY = "activity"
    FITNESS = "fitness"
    SHOPPING = "shopping"
    PRODUCT = "product"
    TIP = "tip"
    OTHER = "other"

class Entities(BaseModel):
    place_name: Optional[str] = Field(
        None, description="Name of the restaurant, café, viewpoint, landmark, store, or venue mentioned or shown"
    )
    city: Optional[str] = Field(
        None, description="City, region, or general geographic location"
    )
    address_or_area: Optional[str] = Field(
        None, description="Specific neighborhood, district, or street address if visible/mentioned"
    )
    cuisine_or_type: Optional[str] = Field(
        None, description="Cuisine type (e.g. Ramen, Italian, Street Food) or specific activity type (e.g. Hiking, Pilates)"
    )
    price_cues: Optional[str] = Field(
        None, description="Price indicators, average cost, budget-friendly cues or specific prices mentioned"
    )
    best_time_to_visit: Optional[str] = Field(
        None, description="Timing, opening hours, sunset, seasonality, or best days/hours to go"
    )
    highlights: List[str] = Field(
        default_factory=list,
        description="Key dishes to order, specific photo spots, signature items, or unique attractions"
    )
    actionable_tips: List[str] = Field(
        default_factory=list,
        description="Crucial advice (e.g. 'book 2 weeks in advance', 'bring cash', 'parking is tight', 'ask for secret menu')"
    )

class TimelineEvent(BaseModel):
    time_or_sequence: str = Field(
        ..., description="Timestamp or time of day (e.g. '0:00 - 0:15 / Morning', 'Afternoon', 'Evening')"
    )
    activity: str = Field(
        default="", description="Specific activity performed, discussed, or shown"
    )
    location: Optional[str] = Field(
        None, description="Venue, shop, restaurant, room, or location name if identifiable"
    )
    audio_details: str = Field(
        default="", description="Everything said, explained, or heard in the audio for this part"
    )
    visual_details: str = Field(
        default="", description="Everything visually shown on screen: objects, outfits, food, on-screen text, surroundings"
    )

class VideoAnalysisResult(BaseModel):
    title: str = Field(..., description="Short, descriptive title capturing the core subject of the clip")
    category: CategoryEnum = Field(..., description="Primary classification of the content")
    transcript_summary: str = Field(
        ..., description="Comprehensive summary of what is spoken, voiceover dialogue, audio explanations, and background audio cues"
    )
    full_audio_transcript: Optional[str] = Field(
        None, description="Exhaustive, detailed transcription/breakdown of all spoken dialogue, tips, and voiceovers"
    )
    visual_summary: str = Field(
        ..., description="Comprehensive summary of what is visually shown across all frames"
    )
    timeline_events: List[TimelineEvent] = Field(
        default_factory=list,
        description="Exhaustive chronological sequence of EVERY activity, scene, routine, and event in the video from start to finish"
    )
    all_places_visited: List[str] = Field(
        default_factory=list,
        description="Complete list of all places, shops, venues, or locations visited or shown in the clip"
    )
    all_products_or_items: List[str] = Field(
        default_factory=list,
        description="Complete list of all foods, drinks, skincare, gadgets, clothing, or items featured"
    )
    entities: Entities = Field(default_factory=Entities, description="Structured extracted key entities")
    tags: List[str] = Field(
        default_factory=list,
        description="Keywords for filtering (e.g. ['ramen', 'tokyo', 'dinner', 'rainy day', 'cheap eats'])"
    )
    search_blob: str = Field(
        ...,
        description="Unified semantic text blob combining title, category, transcript, visuals, timeline, and entities for embedding generation"
    )
    confidence_notes: Optional[str] = Field(
        None, description="Notes on clarity, audio quality, or assumptions made if video was partially ambiguous"
    )

class SavedItem(BaseModel):
    id: str = Field(..., description="Unique ID for the saved clip")
    user_id: str = Field(default="default", description="Owner user ID of the saved knowledge")
    source_type: str = Field(..., description="'file_upload' or 'url'")
    source_identifier: str = Field(..., description="Original filename or source URL")
    media_url: Optional[str] = Field(None, description="Local served video URL or source link")
    analysis: VideoAnalysisResult
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geocoded_address: Optional[str] = None
    personal_notes: Optional[str] = Field(default="", description="User's custom notes or annotations")
    created_at: str = Field(..., description="ISO 8601 timestamp")

class ItemUpdateRequest(BaseModel):
    personal_notes: Optional[str] = None
    tags: Optional[List[str]] = None
    place_name: Optional[str] = None
    city: Optional[str] = None

class UserProfile(BaseModel):
    user_id: str
    display_name: str
    created_at: Optional[str] = None

class KnowledgeBaseStats(BaseModel):
    user_id: str
    total_items: int
    categories: Dict[str, int]
    total_mapped_places: int
    top_cities: List[str]

class VideoProcessRequest(BaseModel):
    url: str = Field(..., description="Public link to Instagram Reel, YouTube Short, or direct video URL")
    user_id: Optional[str] = Field(default="default", description="User ID for personal knowledge base")

class VideoProcessResponse(BaseModel):
    success: bool
    message: str
    source_type: str = Field(..., description="'file_upload' or 'url'")
    source_identifier: str = Field(..., description="File name or original URL")
    item: Optional[SavedItem] = None
    analysis: Optional[VideoAnalysisResult] = None
    processing_time_seconds: Optional[float] = None
    error_details: Optional[str] = None

class ChatMessage(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message text")

class PlanStop(BaseModel):
    stop_number: int
    time_or_period: str = Field(..., description="e.g. '6:30 PM - 7:30 PM' or 'Morning'")
    place_name: str
    activity: str
    item_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class PlanQueryRequest(BaseModel):
    query: str = Field(..., description="Natural language prompt, e.g. 'plan my evening - Chinese dinner'")
    max_items: int = Field(5, description="Maximum number of relevant saved clips to retrieve for context")
    user_id: Optional[str] = Field(default="default", description="User ID for personal knowledge base scoping")
    chat_history: List[ChatMessage] = Field(default_factory=list, description="Prior conversation history for multi-turn planning")

class CitationItem(BaseModel):
    id: str
    title: str
    category: str
    place_name: Optional[str] = None
    city: Optional[str] = None
    media_url: Optional[str] = None
    similarity_score: float

class PlanQueryResponse(BaseModel):
    query: str
    plan_narrative: str
    citations: List[CitationItem]
    referenced_item_ids: List[str]
    stops: List[PlanStop] = Field(default_factory=list, description="Structured timetable stops with coordinates for map routing")

class MapPin(BaseModel):
    id: str
    title: str
    category: str
    latitude: float
    longitude: float
    place_name: Optional[str] = None
    city: Optional[str] = None
    highlights: List[str] = []
    actionable_tips: List[str] = []
    media_url: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    gemini_api_configured: bool
    model_configured: str
    embedding_model_configured: str
    total_saved_items: int
    temp_dir: str

