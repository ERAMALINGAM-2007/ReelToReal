import time
import uuid
import shutil
import logging
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, HTTPException, status, Query
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
    MapPin
)
from app.services.gemini_analyzer import GeminiVideoAnalyzer, GeminiAnalysisError
from app.services.video_downloader import VideoDownloader, VideoDownloadError
from app.services.embedding_service import EmbeddingService
from app.services.storage_service import StorageService
from app.services.geocoding_service import GeocodingService
from app.services.rag_planner import RAGPlannerService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("reeltoreal")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="ReelToReal: AI-Powered Personal Planner & Multimodal Video Understanding Engine."
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
analyzer = GeminiVideoAnalyzer()
embedding_service = EmbeddingService()
storage_service = StorageService()
geocoding_service = GeocodingService()
rag_planner = RAGPlannerService(embedding_service, storage_service)

# Mount local media directory for serving saved video clips
settings.ensure_directories()
app.mount("/media", StaticFiles(directory=str(settings.MEDIA_DIR)), name="media")

# Static frontend directory
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/api/health", response_model=HealthResponse, tags=["General"])
async def health_check():
    return HealthResponse(
        status="healthy",
        gemini_api_configured=analyzer.is_configured(),
        model_configured=settings.GEMINI_MODEL,
        embedding_model_configured=settings.GEMINI_EMBEDDING_MODEL,
        total_saved_items=storage_service.count_items(),
        temp_dir=str(settings.TEMP_VIDEO_DIR)
    )

@app.get("/api/items", response_model=List[SavedItem], tags=["Knowledge Base"])
async def list_saved_items(category: Optional[str] = Query(None, description="Filter by category")):
    """Retrieves all saved items in the personal knowledge base."""
    return storage_service.get_all_items(category=category)

@app.get("/api/items/{item_id}", response_model=SavedItem, tags=["Knowledge Base"])
async def get_saved_item(item_id: str):
    """Retrieves a single saved item by ID."""
    item = storage_service.get_item_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    return item

@app.delete("/api/items/{item_id}", tags=["Knowledge Base"])
async def delete_saved_item(item_id: str):
    """Deletes an item from the knowledge base."""
    success = storage_service.delete_item(item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found.")
    return {"success": True, "message": "Item deleted."}

@app.get("/api/map/pins", response_model=List[MapPin], tags=["Map View"])
async def get_map_pins():
    """Retrieves all geocoded locations for plotting on Leaflet map."""
    return storage_service.get_map_pins()

@app.post("/api/plan", response_model=PlanQueryResponse, tags=["AI Planner"])
async def generate_plan_endpoint(payload: PlanQueryRequest):
    """
    RAG-grounded natural language planner: Retrieves saved clips and generates a concrete itinerary.
    """
    return rag_planner.generate_plan(payload)

@app.post("/api/process/file", response_model=VideoProcessResponse, tags=["Ingestion & Analysis"])
async def process_video_file(file: UploadFile = File(...)):
    """
    Direct file upload pipeline:
    1. Ingestion & validation.
    2. Gemini Multimodal Analysis (Audio + Visuals + On-screen text).
    3. OpenStreetMap Geocoding.
    4. Gemini Embedding generation (models/embedding-001).
    5. Persistence in SQLite Knowledge Base.
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

        # 4. Embedding Generation
        embedding = []
        try:
            embedding = embedding_service.generate_embedding(
                analysis_result.search_blob,
                task_type="retrieval_document"
            )
        except Exception as emb_err:
            logger.warning(f"Embedding error: {emb_err}")

        # 5. Save to Knowledge Base
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
            media_url=media_url
        )

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
    2. Runs Gemini multimodal intelligence.
    3. Geocodes location.
    4. Computes semantic embedding.
    5. Saves to knowledge base.
    """
    start_time = time.time()
    url = payload.url.strip()

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

        # 4. Embedding
        embedding = []
        try:
            embedding = embedding_service.generate_embedding(
                analysis_result.search_blob,
                task_type="retrieval_document"
            )
        except Exception as emb_err:
            logger.warning(f"Embedding error: {emb_err}")

        # 5. Save to Knowledge Base
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
            media_url=media_url
        )

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
