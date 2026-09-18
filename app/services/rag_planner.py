import logging
from typing import List, Optional
import google.generativeai as genai

from app.config import settings
from app.models.schema import PlanQueryRequest, PlanQueryResponse, CitationItem, SavedItem
from app.services.embedding_service import EmbeddingService
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """
You are the ReelToReal Personal AI Planner. Your job is to generate concrete, enjoyable, and personalized plans (e.g. evening plans, weekend itineraries, date nights, food tours) grounded DIRECTLY in the user's saved short-form videos.

CRITICAL RULES:
1. Base your recommendations primarily on the PROVIDED SAVED ITEMS from the user's knowledge base.
2. For each recommendation, explicitly cite the clip by name/ID, e.g., "[Clip: <Title> / <Place>]".
3. Include practical details directly from what was extracted (e.g., must-try dishes, actionable tips like 'cash only' or 'arrive before sunset').
4. If there are fewer relevant saved clips than requested, use what you have enthusiastically, and gracefully bridge any gaps with helpful advice.
5. Format your output clearly in clean, beautiful Markdown with headers, bullet points, timings (e.g., 6:30 PM - Appetizers & Vibes), and actionable highlights.
"""

class RAGPlannerService:
    """
    RAG-powered conversational planner that retrieves saved clips and synthesizes grounded plans.
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
        """Generates a personalized plan based on user query and retrieved clips."""
        user_query = request.query.strip()
        if not user_query:
            return PlanQueryResponse(
                query="",
                plan_narrative="Please provide a query for your plan (e.g., 'Plan my Friday evening with a ramen spot and a dessert spot').",
                citations=[],
                referenced_item_ids=[]
            )

        # 1. Compute query embedding
        query_embedding = []
        if self.embedding_service.is_configured():
            try:
                query_embedding = self.embedding_service.generate_embedding(
                    text=user_query,
                    task_type="retrieval_query"
                )
            except Exception as e:
                logger.warning(f"Failed to generate query embedding: {e}")

        # 2. Retrieve top-k similar items
        retrieved_results = self.storage_service.search_similar_items(
            query_embedding=query_embedding,
            top_k=request.max_items
        )

        # If no items stored yet, return guidance
        if not retrieved_results:
            all_items = self.storage_service.get_all_items()
            if not all_items:
                return PlanQueryResponse(
                    query=user_query,
                    plan_narrative=(
                        "You don't have any saved videos in your knowledge base yet!\n\n"
                        "💡 **Get Started**: Upload a video file or paste an Instagram Reel / YouTube Short link in the Ingest tab to start building your personal AI knowledge base."
                    ),
                    citations=[],
                    referenced_item_ids=[]
                )

        # 3. Format citations
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
            )
            context_blocks.append(block)

        context_text = "\n\n".join(context_blocks)

        # 4. Generate grounded plan narrative with Gemini
        prompt = (
            f"USER QUERY: \"{user_query}\"\n\n"
            f"RELEVANT ITEMS RETRIEVED FROM USER'S SAVED KNOWLEDGE BASE:\n\n"
            f"{context_text}\n\n"
            f"Create a personalized, step-by-step actionable plan answering the user's query. "
            f"Grounded specifically in the above saved clips. Explicitly mention the clip titles and places."
        )

        candidates = [settings.GEMINI_MODEL, "gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
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
            plan_narrative = f"### Plan for: {user_query}\n\nHere are the top matches from your saved videos:\n\n"
            for item, _ in retrieved_results:
                plan_narrative += f"- **{item.analysis.title}** ({item.analysis.entities.place_name or item.analysis.category.value}): {item.analysis.transcript_summary}\n"

        return PlanQueryResponse(
            query=user_query,
            plan_narrative=plan_narrative,
            citations=citations,
            referenced_item_ids=referenced_ids
        )
