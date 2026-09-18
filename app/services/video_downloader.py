import os
import uuid
import logging
from pathlib import Path
from typing import Tuple, Optional
import yt_dlp
from app.config import settings

logger = logging.getLogger(__name__)

# Locate ffmpeg from imageio_ffmpeg if available
try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_PATH = None

class VideoDownloadError(Exception):
    """Exception raised when video downloading fails or is blocked."""
    def __init__(self, message: str, user_friendly_message: str):
        super().__init__(message)
        self.user_friendly_message = user_friendly_message

class VideoDownloader:
    """
    Downloads short-form videos from public URLs (YouTube Shorts, Instagram Reels, TikTok, direct links)
    using yt-dlp with built-in ffmpeg merging and strict timeouts.
    """

    @staticmethod
    def download_video_from_url(url: str) -> Tuple[Path, str]:
        """
        Downloads a video from the specified URL to the temp directory.
        Returns:
            Tuple[Path, str]: (path_to_downloaded_file, extracted_title_or_id)
        Raises:
            VideoDownloadError: if download fails, times out, or is blocked.
        """
        settings.ensure_directories()
        unique_id = uuid.uuid4().hex[:10]
        out_template = str(settings.TEMP_VIDEO_DIR / f"reel_{unique_id}.%(ext)s")

        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best',
            'outtmpl': out_template,
            'merge_output_format': 'mp4',
            'socket_timeout': settings.YT_DLP_TIMEOUT_SECONDS,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'max_filesize': settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024,
        }

        if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
            ydl_opts['ffmpeg_location'] = FFMPEG_PATH

        try:
            logger.info(f"Attempting to download video from URL: {url}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', f"video_{unique_id}")
                
                # Check for merged mp4 file first
                target_mp4 = settings.TEMP_VIDEO_DIR / f"reel_{unique_id}.mp4"
                if target_mp4.exists() and target_mp4.stat().st_size > 0:
                    file_path = target_mp4
                else:
                    # Look for all matches and select the largest file (full video)
                    matches = list(settings.TEMP_VIDEO_DIR.glob(f"reel_{unique_id}.*"))
                    if matches:
                        file_path = max(matches, key=lambda p: p.stat().st_size)
                    else:
                        raise VideoDownloadError(
                            message=f"Downloaded file not found on disk for template {out_template}",
                            user_friendly_message="Video could not be downloaded from this link. Please upload the video file directly."
                        )

                # Clean up any residual fragment files (.f140, .f699, etc.)
                for match in settings.TEMP_VIDEO_DIR.glob(f"reel_{unique_id}.*"):
                    if match != file_path and match.exists():
                        try:
                            os.remove(match)
                        except Exception:
                            pass

                logger.info(f"Successfully prepared full video: {file_path} (Size: {file_path.stat().st_size} bytes)")
                return file_path, title

        except yt_dlp.utils.DownloadError as e:
            logger.warning(f"yt-dlp download error for {url}: {e}")
            raise VideoDownloadError(
                message=str(e),
                user_friendly_message=(
                    "Could not fetch video from this link (platform security might have blocked scraping). "
                    "Please download or screen-record the clip and use the direct File Upload option."
                )
            )
        except Exception as e:
            logger.error(f"Unexpected error during download for {url}: {e}")
            if isinstance(e, VideoDownloadError):
                raise
            raise VideoDownloadError(
                message=str(e),
                user_friendly_message=(
                    "An error occurred while attempting to fetch the video link. "
                    "Please upload the video file directly."
                )
            )

    @staticmethod
    def cleanup_file(file_path: Path):
        """Safely removes a local temporary video file."""
        try:
            if file_path and file_path.exists():
                os.remove(file_path)
                logger.info(f"Cleaned up local video file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {file_path}: {e}")
