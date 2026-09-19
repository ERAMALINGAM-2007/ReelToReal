import time
import uuid
import shutil
import logging
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import aiofiles

from app.config import settings, BASE_DIR
from app.models.schema import (
    VideoProcessRequest,
    VideoProcessResponse,
    PlanQueryRequest,
    PlanQueryResponse,
    HealthResponse,
    SavedItem,
    MapPin,
    ItemUpdateRequest,
    UserProfile,
    KnowledgeBaseStats
)
from app.services.gemini_analyzer import GeminiVideoAnalyzer, GeminiAnalysisError
from app.services.video_downloader import VideoDownloader, VideoDownloadError
from app.services.embedding_service import EmbeddingService
from app.services.storage_service import StorageService
from app.services.geocoding_service import GeocodingService
from app.services.rag_planner import RAGPlannerService
from app.services.vector_store_service import VectorStoreService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("reeltoreal")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="ReelToReal: AI-Powered Personal Planner & Multimodal Video Understanding Engine with ChromaDB Vector Store."
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Services
settings.ensure_directories()
analyzer = GeminiVideoAnalyzer()
embedding_service = EmbeddingService()
storage_service = StorageService()
geocoding_service = GeocodingService()
vector_store = VectorStoreService()
rag_planner = RAGPlannerService(embedding_service, storage_service, vector_store)

# Mount local media directory for serving saved video clips
app.mount("/media", StaticFiles(directory=str(settings.MEDIA_DIR)), name="media")

# Static frontend directory
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.on_event("startup")
async def startup_reconciliation():
    """Reconciles any unsynced or failed vectors into ChromaDB on application startup."""
    try:
        unsynced = storage_service.get_unsynced_items()
        if unsynced:
            logger.info(f"Startup check: found {len(unsynced)} unsynced items. Reconciling with ChromaDB...")
            for itm in unsynced:
                try:
                    emb = []
                    if embedding_service.is_configured():
                        emb = embedding_service.generate_embedding(
                            itm.analysis.search_blob,
                            task_type="retrieval_document",
                            output_dimensionality=settings.EMBEDDING_DIMENSION
                        )
                    if emb:
                        ok = vector_store.upsert_item(
                            item_id=itm.id,
                            user_id=itm.user_id,
                            search_blob=itm.analysis.search_blob,
                            embedding=emb,
                            metadata={
                                "user_id": itm.user_id,
                                "title": itm.analysis.title,
                                "category": itm.analysis.category.value,
                                "place_name": itm.analysis.entities.place_name,
                                "city": itm.analysis.entities.city,
                                "created_at": itm.created_at
                            }
                        )
                        if ok:
                            storage_service.update_sync_status(itm.id, "synced")
                            logger.info(f"Reconciled item {itm.id} to ChromaDB.")
                except Exception as sync_err:
                    logger.warning(f"Could not reconcile item {itm.id} during startup: {sync_err}")
    except Exception as e:
        logger.warning(f"Error during startup vector reconciliation: {e}")

@app.get("/api/health", response_model=HealthResponse, tags=["General"])
async def health_check():
    return HealthResponse(
        status="healthy",
        gemini_api_configured=analyzer.is_configured(),
        model_configured=settings.GEMINI_MODEL,
        embedding_model_configured=settings.GEMINI_EMBEDDING_MODEL,
        total_saved_items=storage_service.count_items(),
        chroma_indexed_items=vector_store.count(),
        temp_dir=str(settings.TEMP_VIDEO_DIR)
    )

@app.get("/api/items", response_model=List[SavedItem], tags=["Knowledge Base"])
async def list_saved_items(
    category: Optional[str] = Query(None, description="Filter by category"),
    user_id: Optional[str] = Query("default", description="Filter by user profile")
):
    """Retrieves all saved items in the personal knowledge base for a user."""
    return storage_service.get_all_items(category=category, user_id=user_id)

@app.get("/api/items/{item_id}", response_model=SavedItem, tags=["Knowledge Base"])
async def get_saved_item(
    item_id: str,
    user_id: Optional[str] = Query(None, description="Optional user scoping")
):
    """Retrieves a single saved item by ID with double user isolation."""
    item = storage_service.get_item_by_id(item_id, user_id=user_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    return item

@app.put("/api/items/{item_id}", response_model=SavedItem, tags=["Knowledge Base"])
async def update_saved_item(
    item_id: str,
    payload: ItemUpdateRequest,
    user_id: Optional[str] = Query(None, description="Optional user scoping")
):
    """
    Updates personal notes, tags, or metadata for a saved item,
    rebuilds search_blob from scratch, re-embeds, and synchronizes ChromaDB.
    """
    # 1. Update SQLite and rebuild search_blob
    updated = storage_service.update_item(
        item_id=item_id,
        user_id=user_id,
        title=payload.title,
        category=payload.category,
        personal_notes=payload.personal_notes,
        tags=payload.tags,
        place_name=payload.place_name,
        city=payload.city
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Item not found.")

    # 2. Re-embed at fixed 768 dimensions and synchronize ChromaDB
    try:
        new_emb = []
        if embedding_service.is_configured():
            new_emb = embedding_service.generate_embedding(
                updated.analysis.search_blob,
                task_type="retrieval_document",
                output_dimensionality=settings.EMBEDDING_DIMENSION
            )
        if new_emb:
            sync_ok = vector_store.update_item(
                item_id=item_id,
                user_id=updated.user_id,
                search_blob=updated.analysis.search_blob,
                embedding=new_emb,
                metadata={
                    "user_id": updated.user_id,
                    "title": updated.analysis.title,
                    "category": updated.analysis.category.value,
                    "place_name": updated.analysis.entities.place_name,
                    "city": updated.analysis.entities.city,
                    "created_at": updated.created_at
                }
            )
            status_val = "synced" if sync_ok else "failed"
            storage_service.update_sync_status(item_id, status_val)
            updated.vector_sync_status = status_val
    except Exception as e:
        logger.warning(f"Failed to synchronize ChromaDB vector for item {item_id}: {e}")
        storage_service.update_sync_status(item_id, "failed")
        updated.vector_sync_status = "failed"

    return updated

@app.delete("/api/items/{item_id}", tags=["Knowledge Base"])
async def delete_saved_item(
    item_id: str,
    user_id: Optional[str] = Query(None, description="Optional user scoping")
):
    """Deletes an item from SQLite and ChromaDB."""
    success = storage_service.delete_item(item_id, user_id=user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found.")
    
    # Delete from ChromaDB
    try:
        vector_store.delete_item(item_id)
    except Exception as e:
        logger.warning(f"Could not remove {item_id} from ChromaDB: {e}")

    return {"success": True, "message": "Item deleted."}

@app.get("/api/kb/stats", response_model=KnowledgeBaseStats, tags=["Knowledge Base"])
async def get_knowledge_base_stats(
    user_id: str = Query("default", description="User ID for personal stats")
):
    """Retrieves personal knowledge base metrics and breakdown."""
    return storage_service.get_user_stats(user_id=user_id)

@app.get("/api/kb/export", tags=["Knowledge Base"])
async def export_knowledge_base(
    user_id: str = Query("default", description="User ID to export")
):
    """Exports full personal knowledge base as downloadable JSON."""
    return storage_service.export_user_data(user_id=user_id)

@app.get("/api/users", response_model=List[UserProfile], tags=["Users & Profiles"])
async def list_user_profiles():
    """Lists all registered user profiles."""
    return storage_service.list_users()

@app.post("/api/users", response_model=UserProfile, tags=["Users & Profiles"])
async def create_user_profile(payload: UserProfile):
    """Creates or switches to a user profile."""
    return storage_service.create_user(payload.user_id, payload.display_name)

@app.get("/api/map/pins", response_model=List[MapPin], tags=["Map View"])
async def get_map_pins(user_id: Optional[str] = Query("default", description="User scoping")):
    """Retrieves all geocoded locations for plotting on Leaflet map for a user."""
    return storage_service.get_map_pins(user_id=user_id)

@app.post("/api/plan", response_model=PlanQueryResponse, tags=["AI Planner"])
async def generate_plan_endpoint(payload: PlanQueryRequest):
    """
    RAG-grounded natural language planner:
    Retrieves saved clips from ChromaDB and generates a concrete itinerary grounded in evidence.
    """
    return rag_planner.generate_plan(payload)

@app.post("/api/process/file", response_model=VideoProcessResponse, tags=["Ingestion & Analysis"])
async def process_video_file(
    file: UploadFile = File(...),
    user_id: str = Form("default")
):
    """
    Direct file upload pipeline:
    1. Ingestion & validation.
    2. Gemini Multimodal Analysis (gemini-3.8-flash).
    3. OpenStreetMap Geocoding.
    4. Gemini Embedding generation (models/gemini-embedding-2 @ 768 dims).
    5. Persistence in SQLite Knowledge Base.
    6. Upsert into ChromaDB vector database.
    """
    settings.ensure_directories()
    start_time = time.time()
    
    file_ext = Path(file.filename or "video.mp4").suffix.lower()
    allowed_extensions = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{file_ext}'. Allowed formats: {', '.join(allowed_extensions)}"
        )

    unique_id = uuid.uuid4().hex[:12]
    temp_path = settings.TEMP_VIDEO_DIR / f"upload_{unique_id}_{file.filename}"
    media_filename = f"clip_{unique_id}{file_ext}"
    media_dest_path = settings.MEDIA_DIR / media_filename

    try:
        # Save temp file
        async with aiofiles.open(temp_path, 'wb') as out_file:
            while content := await file.read(1024 * 1024):
                await out_file.write(content)

        if not analyzer.is_configured():
            return VideoProcessResponse(
                success=False,
                message="GEMINI_API_KEY is not configured. Please add your key to the .env file.",
                source_type="file_upload",
                source_identifier=file.filename or "unknown",
                processing_time_seconds=round(time.time() - start_time, 2),
                error_details="Missing GEMINI_API_KEY in environment or .env file."
            )

        # 1. Gemini Multimodal Analysis
        analysis_result = analyzer.analyze_video_file(temp_path)

        # 2. Permanent media storage for playback in UI
        shutil.copyfile(str(temp_path), str(media_dest_path))
        media_url = f"/media/{media_filename}"

        # 3. Geocoding
        lat, lon, geo_addr = None, None, None
        try:
            lat, lon, geo_addr = geocoding_service.geocode(
                place_name=analysis_result.entities.place_name,
                city=analysis_result.entities.city,
                address=analysis_result.entities.address_or_area
            )
        except Exception as geo_err:
            logger.warning(f"Geocoding error: {geo_err}")

        # 4. Embedding Generation (Fixed 768 Dimensions)
        embedding = []
        try:
            embedding = embedding_service.generate_embedding(
                analysis_result.search_blob,
                task_type="retrieval_document",
                output_dimensionality=settings.EMBEDDING_DIMENSION
            )
        except Exception as emb_err:
            logger.warning(f"Embedding error: {emb_err}")

        # 5. Save to SQLite (Source of Truth)
        saved_item = storage_service.save_item(
            item_id=unique_id,
            source_type="file_upload",
            source_identifier=file.filename or "uploaded_clip",
            analysis=analysis_result,
            embedding=embedding,
            latitude=lat,
            longitude=lon,
            geocoded_address=geo_addr,
            media_path=str(media_dest_path),
            media_url=media_url,
            user_id=user_id,
            vector_sync_status="pending"
        )

        # 6. Upsert to ChromaDB Vector Store
        if embedding:
            try:
                chroma_ok = vector_store.upsert_item(
                    item_id=unique_id,
                    user_id=user_id,
                    search_blob=analysis_result.search_blob,
                    embedding=embedding,
                    metadata={
                        "user_id": user_id,
                        "title": analysis_result.title,
                        "category": analysis_result.category.value,
                        "place_name": analysis_result.entities.place_name,
                        "city": analysis_result.entities.city,
                        "created_at": saved_item.created_at
                    }
                )
                sync_val = "synced" if chroma_ok else "failed"
                storage_service.update_sync_status(unique_id, sync_val)
                saved_item.vector_sync_status = sync_val
            except Exception as chroma_err:
                logger.warning(f"ChromaDB upsert error for {unique_id}: {chroma_err}")
                storage_service.update_sync_status(unique_id, "failed")
                saved_item.vector_sync_status = "failed"

        elapsed = round(time.time() - start_time, 2)
        return VideoProcessResponse(
            success=True,
            message="Video analyzed and saved to knowledge base successfully.",
            source_type="file_upload",
            source_identifier=file.filename or "uploaded_clip",
            item=saved_item,
            analysis=analysis_result,
            processing_time_seconds=elapsed
        )

    except GeminiAnalysisError as e:
        logger.error(f"Gemini analysis error: {e}")
        return VideoProcessResponse(
            success=False,
            message=f"Gemini analysis failed: {str(e)}",
            source_type="file_upload",
            source_identifier=file.filename or "unknown",
            processing_time_seconds=round(time.time() - start_time, 2),
            error_details=str(e)
        )
    except Exception as e:
        logger.error(f"Error processing video: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error processing video: {str(e)}"
        )
    finally:
        VideoDownloader.cleanup_file(temp_path)

@app.post("/api/process/url", response_model=VideoProcessResponse, tags=["Ingestion & Analysis"])
async def process_video_url(payload: VideoProcessRequest):
    """
    URL Ingestion Pipeline:
    1. Downloads video from YouTube Shorts / Reels.
    2. Runs Gemini multimodal intelligence (gemini-3.8-flash).
    3. Geocodes location with OpenStreetMap.
    4. Computes semantic embedding (models/gemini-embedding-2 @ 768 dims).
    5. Saves to SQLite.
    6. Upserts to ChromaDB vector store.
    """
    start_time = time.time()
    url = payload.url.strip()
    user_id = payload.user_id or "default"

    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty.")

    downloaded_path = None
    try:
        downloaded_path, title = VideoDownloader.download_video_from_url(url)
        
        if not analyzer.is_configured():
            return VideoProcessResponse(
                success=False,
                message="GEMINI_API_KEY is not configured. Please add your key to the .env file.",
                source_type="url",
                source_identifier=url,
                processing_time_seconds=round(time.time() - start_time, 2),
                error_details="Missing GEMINI_API_KEY in environment or .env file."
            )

        # 1. Gemini Multimodal Analysis
        analysis_result = analyzer.analyze_video_file(downloaded_path)

        # 2. Persist media
        unique_id = uuid.uuid4().hex[:12]
        file_ext = downloaded_path.suffix or ".mp4"
        media_filename = f"clip_{unique_id}{file_ext}"
        media_dest_path = settings.MEDIA_DIR / media_filename
        shutil.copyfile(str(downloaded_path), str(media_dest_path))
        media_url = f"/media/{media_filename}"

        # 3. Geocoding
        lat, lon, geo_addr = None, None, None
        try:
            lat, lon, geo_addr = geocoding_service.geocode(
                place_name=analysis_result.entities.place_name,
                city=analysis_result.entities.city,
                address=analysis_result.entities.address_or_area
            )
        except Exception as geo_err:
            logger.warning(f"Geocoding error: {geo_err}")

        # 4. Embedding Generation (Fixed 768 Dimensions)
        embedding = []
        try:
            embedding = embedding_service.generate_embedding(
                analysis_result.search_blob,
                task_type="retrieval_document",
                output_dimensionality=settings.EMBEDDING_DIMENSION
            )
        except Exception as emb_err:
            logger.warning(f"Embedding error: {emb_err}")

        # 5. Save to SQLite (Source of Truth)
        saved_item = storage_service.save_item(
            item_id=unique_id,
            source_type="url",
            source_identifier=url,
            analysis=analysis_result,
            embedding=embedding,
            latitude=lat,
            longitude=lon,
            geocoded_address=geo_addr,
            media_path=str(media_dest_path),
            media_url=media_url,
            user_id=user_id,
            vector_sync_status="pending"
        )

        # 6. Upsert to ChromaDB Vector Store
        if embedding:
            try:
                chroma_ok = vector_store.upsert_item(
                    item_id=unique_id,
                    user_id=user_id,
                    search_blob=analysis_result.search_blob,
                    embedding=embedding,
                    metadata={
                        "user_id": user_id,
                        "title": analysis_result.title,
                        "category": analysis_result.category.value,
                        "place_name": analysis_result.entities.place_name,
                        "city": analysis_result.entities.city,
                        "created_at": saved_item.created_at
                    }
                )
                sync_val = "synced" if chroma_ok else "failed"
                storage_service.update_sync_status(unique_id, sync_val)
                saved_item.vector_sync_status = sync_val
            except Exception as chroma_err:
                logger.warning(f"ChromaDB upsert error for {unique_id}: {chroma_err}")
                storage_service.update_sync_status(unique_id, "failed")
                saved_item.vector_sync_status = "failed"

        elapsed = round(time.time() - start_time, 2)
        return VideoProcessResponse(
            success=True,
            message="Video downloaded, analyzed, and added to knowledge base.",
            source_type="url",
            source_identifier=url,
            item=saved_item,
            analysis=analysis_result,
            processing_time_seconds=elapsed
        )

    except VideoDownloadError as e:
        logger.warning(f"Video download fallback: {e}")
        return VideoProcessResponse(
            success=False,
            message=e.user_friendly_message,
            source_type="url",
            source_identifier=url,
            processing_time_seconds=round(time.time() - start_time, 2),
            error_details=str(e)
        )
    except GeminiAnalysisError as e:
        logger.error(f"Gemini analysis error: {e}")
        return VideoProcessResponse(
            success=False,
            message=f"Gemini analysis failed: {str(e)}",
            source_type="url",
            source_identifier=url,
            processing_time_seconds=round(time.time() - start_time, 2),
            error_details=str(e)
        )
    finally:
        if downloaded_path:
            VideoDownloader.cleanup_file(downloaded_path)

# Serve Frontend HTML
@app.get("/", tags=["Frontend"])
async def serve_index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "message": "Frontend static file is loading..."
    }
