import os
import uuid
import logging
from pathlib import Path
from typing import Tuple, Optional
import yt_dlp
from app.config import settings

logger = logging.getLogger(__name__)

class VideoDownloadError(Exception):
    """Exception raised when video downloading fails or is blocked."""
    def __init__(self, message: str, user_friendly_message: str):
        super().__init__(message)
        self.user_friendly_message = user_friendly_message

class VideoDownloader:
    """
    Downloads short-form videos from public URLs (YouTube Shorts, Instagram Reels, TikTok, direct links)
    using yt-dlp with strict timeouts and robust fallbacks.
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
            'format': 'best[ext=mp4]/bestvideo+bestaudio/best',
            'outtmpl': out_template,
            'socket_timeout': settings.YT_DLP_TIMEOUT_SECONDS,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'max_filesize': settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024,
        }

        try:
            logger.info(f"Attempting to download video from URL: {url}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', f"video_{unique_id}")
                filename = ydl.prepare_filename(info)
                
                # Check for possible extension change (e.g. mp4)
                file_path = Path(filename)
                if not file_path.exists():
                    # Fallback check for any file starting with reel_{unique_id}
                    matches = list(settings.TEMP_VIDEO_DIR.glob(f"reel_{unique_id}.*"))
                    if matches:
                        file_path = matches[0]
                    else:
                        raise VideoDownloadError(
                            message=f"Downloaded file not found on disk for template {out_template}",
                            user_friendly_message="Video could not be downloaded from this link. Please upload the video file directly."
                        )

                logger.info(f"Successfully downloaded video to: {file_path}")
                return file_path, title

        except yt_dlp.utils.DownloadError as e:
            logger.warning(f"yt-dlp download error for {url}: {e}")
            raise VideoDownloadError(
                message=str(e),
                user_friendly_message=(
                    "Could not fetch video from this link (Instagram/platform security might have blocked scraping). "
                    "Please download or screen-record the clip and use the direct File Upload option."
                )
            )
        except Exception as e:
            logger.error(f"Unexpected error during download for {url}: {e}")
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
