import re
import json
import logging
from typing import List, Optional
import google.generativeai as genai

from app.config import settings
from app.models.schema import (
    PlanQueryRequest,
    PlanQueryResponse,
    CitationItem,
    SavedItem,
    PlanStop,
    ChatMessage
)
from app.services.embedding_service import EmbeddingService
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """
You are the ReelToReal Personal AI Planner. Your job is to generate concrete, enjoyable, and personalized plans (e.g. evening plans, weekend itineraries, date nights, food tours) grounded DIRECTLY in the user's saved short-form videos.

CRITICAL RULES:
1. Base your recommendations primarily on the PROVIDED SAVED ITEMS from the user's personal knowledge base.
2. For each recommendation, explicitly cite the clip by name/ID, e.g., "[Clip: <Title> / <Place>]".
3. Include practical details directly from what was extracted (e.g., must-try dishes, actionable tips like 'cash only' or 'arrive before sunset').
4. If this is a follow-up in an ongoing conversation, maintain continuity, adapt recommendations, and address the user's follow-up request directly.
5. If there are fewer relevant saved clips than requested, use what you have enthusiastically, and gracefully bridge any gaps with helpful advice.
6. Format your output clearly in clean, beautiful Markdown with headers, bullet points, timings (e.g., 6:30 PM - Dinner & Atmosphere), and actionable highlights.
7. At the very end of your response, output a JSON block delimited by ```json_stops ... ``` containing an array of stops for map routing:
```json_stops
[
  {
    "stop_number": 1,
    "time_or_period": "6:30 PM",
    "place_name": "<Place Name>",
    "activity": "<Short summary of activity/food>",
    "item_id": "<Item ID if from saved clips>"
  }
]
```
"""

class RAGPlannerService:
    """
    RAG-powered conversational planner that retrieves saved clips and synthesizes grounded plans
    with multi-turn conversational memory and structured map routing stops.
    """

    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        storage_service: Optional[StorageService] = None,
        api_key: Optional[str] = None
    ):
        self.embedding_service = embedding_service or EmbeddingService()
        self.storage_service = storage_service or StorageService()
        self.api_key = api_key or settings.GEMINI_API_KEY
        if self.api_key and self.api_key.strip() and self.api_key != "your_gemini_api_key_here":
            genai.configure(api_key=self.api_key)
            self._configured = True
        else:
            self._configured = False

    def generate_plan(self, request: PlanQueryRequest) -> PlanQueryResponse:
        """Generates a personalized plan based on user query, conversation history, and retrieved clips."""
        user_query = request.query.strip()
        if not user_query:
            return PlanQueryResponse(
                query="",
                plan_narrative="Please provide a query for your plan (e.g., 'Plan my Friday evening with a ramen spot and a dessert spot').",
                citations=[],
                referenced_item_ids=[],
                stops=[]
            )

        user_id = request.user_id or "default"

        # 1. Compute query embedding (combine short follow-ups with previous user context)
        effective_search_query = user_query
        if request.chat_history and len(user_query.split()) < 4:
            prev_user_queries = [m.content for m in request.chat_history if m.role == "user"]
            if prev_user_queries:
                effective_search_query = f"{prev_user_queries[-1]} {user_query}"

        query_embedding = []
        if self.embedding_service.is_configured():
            try:
                query_embedding = self.embedding_service.generate_embedding(
                    text=effective_search_query,
                    task_type="retrieval_query"
                )
            except Exception as e:
                logger.warning(f"Failed to generate query embedding: {e}")

        # 2. Retrieve top-k similar items for this user
        retrieved_results = self.storage_service.search_similar_items(
            query_embedding=query_embedding,
            top_k=request.max_items,
            user_id=user_id
        )

        # If no items stored yet, return guidance
        if not retrieved_results:
            all_items = self.storage_service.get_all_items(user_id=user_id)
            if not all_items:
                return PlanQueryResponse(
                    query=user_query,
                    plan_narrative=(
                        "You don't have any saved videos in your personal knowledge base yet!\n\n"
                        "💡 **Get Started**: Upload a video file or paste an Instagram Reel / YouTube Short link to begin saving clips to your knowledge base."
                    ),
                    citations=[],
                    referenced_item_ids=[],
                    stops=[]
                )

        # 3. Format citations and context blocks
        citations: List[CitationItem] = []
        referenced_ids = []
        context_blocks = []

        for item, score in retrieved_results:
            citations.append(CitationItem(
                id=item.id,
                title=item.analysis.title,
                category=item.analysis.category.value,
                place_name=item.analysis.entities.place_name,
                city=item.analysis.entities.city,
                media_url=item.media_url,
                similarity_score=round(score, 3)
            ))
            referenced_ids.append(item.id)

            timeline_str = ""
            if hasattr(item.analysis, 'timeline_events') and item.analysis.timeline_events:
                timeline_str = "\n- Chronological Timeline & Activities:\n" + "\n".join([
                    f"  * [{t.time_or_sequence}] {t.activity} ({t.location or 'General'}): Spoken='{t.audio_details}', Visuals='{t.visual_details}'"
                    for t in item.analysis.timeline_events
                ])

            notes_str = f"\n- User Personal Notes: {item.personal_notes}" if item.personal_notes else ""

            block = (
                f"### Saved Item: {item.analysis.title} (ID: {item.id})\n"
                f"- Category: {item.analysis.category.value}\n"
                f"- Place: {item.analysis.entities.place_name or 'N/A'}\n"
                f"- Location: {item.analysis.entities.city or ''} {f'({item.analysis.entities.address_or_area})' if item.analysis.entities.address_or_area else ''}\n"
                f"- Cuisine/Activity: {item.analysis.entities.cuisine_or_type or 'N/A'}\n"
                f"- Highlights: {', '.join(item.analysis.entities.highlights) if item.analysis.entities.highlights else 'N/A'}\n"
                f"- Actionable Tips: {', '.join(item.analysis.entities.actionable_tips) if item.analysis.entities.actionable_tips else 'N/A'}\n"
                f"- Spoken Info: {item.analysis.transcript_summary}\n"
                f"- Visual Details: {item.analysis.visual_summary}\n"
                f"{notes_str}"
                f"{timeline_str}\n"
            )
            context_blocks.append(block)

        context_text = "\n\n".join(context_blocks)

        # 4. Multi-Turn Conversation History Context
        history_text = ""
        if request.chat_history:
            history_lines = []
            for msg in request.chat_history[-6:]:
                sender = "User" if msg.role == "user" else "AI Planner"
                history_lines.append(f"{sender}: {msg.content}")
            history_text = "PREVIOUS CONVERSATION TURNS:\n" + "\n".join(history_lines) + "\n\n"

        prompt = (
            f"{history_text}"
            f"CURRENT USER QUERY: \"{user_query}\"\n\n"
            f"RELEVANT ITEMS RETRIEVED FROM USER'S PERSONAL KNOWLEDGE BASE:\n\n"
            f"{context_text}\n\n"
            f"Create a personalized, step-by-step actionable plan answering the user's query. "
            f"Grounded specifically in the above saved clips. Explicitly cite the clip titles and places. "
            f"At the very end of your response, output the ```json_stops ... ``` block as required by your instructions."
        )

        candidates = [
            settings.GEMINI_MODEL,
            "gemini-3.8-flash",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-2.5-flash"
        ]
        candidates = list(dict.fromkeys(candidates))

        plan_narrative = ""
        for cand in candidates:
            try:
                model = genai.GenerativeModel(
                    model_name=cand,
                    system_instruction=PLANNER_SYSTEM_PROMPT,
                    generation_config={"temperature": 0.4}
                )
                response = model.generate_content(prompt)
                if response and response.text:
                    plan_narrative = response.text
                    break
            except Exception as e:
                logger.warning(f"RAG plan generation failed with model {cand}: {e}")

        if not plan_narrative:
            # Fallback simple synthesis if API call was unavailable
            plan_narrative = f"### Plan for: {user_query}\n\nHere are the top matches from your personal knowledge base:\n\n"
            for item, _ in retrieved_results:
                plan_narrative += f"- **{item.analysis.title}** ({item.analysis.entities.place_name or item.analysis.category.value}): {item.analysis.transcript_summary}\n"

        # 5. Extract structured stops and strip json_stops delimiters
        stops: List[PlanStop] = []
        raw_stops_match = re.search(r"```json_stops\s*([\s\S]*?)\s*```", plan_narrative)
        item_lookup = {item.id: item for item, _ in retrieved_results}

        if raw_stops_match:
            try:
                parsed_stops = json.loads(raw_stops_match.group(1))
                if isinstance(parsed_stops, list):
                    for s in parsed_stops:
                        item_id = s.get("item_id")
                        matched_item = item_lookup.get(item_id)
                        lat = matched_item.latitude if matched_item else None
                        lon = matched_item.longitude if matched_item else None
                        stops.append(PlanStop(
                            stop_number=s.get("stop_number", len(stops) + 1),
                            time_or_period=s.get("time_or_period", "Scheduled"),
                            place_name=s.get("place_name", "Destination"),
                            activity=s.get("activity", ""),
                            item_id=item_id,
                            latitude=lat,
                            longitude=lon
                        ))
            except Exception as parse_err:
                logger.warning(f"Could not parse stops JSON from planner: {parse_err}")
            
            plan_narrative = re.sub(r"```json_stops\s*[\s\S]*?\s*```", "", plan_narrative).strip()

        # Fallback stops extraction: assign stops for all retrieved items with coordinates
        if not stops:
            slot_names = ["6:00 PM - First Stop", "7:45 PM - Second Stop", "9:00 PM - Third Stop"]
            stop_idx = 1
            for item, _ in retrieved_results:
                if item.latitude is not None and item.longitude is not None:
                    time_label = slot_names[stop_idx - 1] if stop_idx <= len(slot_names) else f"Stop {stop_idx}"
                    stops.append(PlanStop(
                        stop_number=stop_idx,
                        time_or_period=time_label,
                        place_name=item.analysis.entities.place_name or item.analysis.title,
                        activity=item.analysis.entities.cuisine_or_type or item.analysis.category.value,
                        item_id=item.id,
                        latitude=item.latitude,
                        longitude=item.longitude
                    ))
                    stop_idx += 1
                    if stop_idx > 3:
                        break

        return PlanQueryResponse(
            query=user_query,
            plan_narrative=plan_narrative,
            citations=citations,
            referenced_item_ids=referenced_ids,
            stops=stops
        )
