import argparse
import json
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.config import settings
from app.services.gemini_analyzer import GeminiVideoAnalyzer, GeminiAnalysisError
from app.services.video_downloader import VideoDownloader, VideoDownloadError

console = Console()

def print_banner():
    console.print(
        Panel.fit(
            "[bold cyan]ReelToReal AI[/bold cyan] - Multimodal Video & Audio Understanding Pipeline\n"
            "[italic]Extracts transcript, visuals, categories, places, cuisines, and actionable tips[/italic]",
            border_style="cyan"
        )
    )

def display_analysis_result(result):
    console.print("\n[bold green]✓ Video Analysis Completed Successfully![/bold green]\n")
    
    # Overview Table
    table = Table(title="Extracted Video Intelligence", show_header=True, header_style="bold magenta")
    table.add_column("Field", style="dim", width=20)
    table.add_column("Extracted Information", style="white")

    table.add_row("Title", f"[bold]{result.title}[/bold]")
    table.add_row("Category", f"[yellow]{result.category.value.upper()}[/yellow]")
    table.add_row("Place Name", result.entities.place_name or "[dim]Not specified[/dim]")
    table.add_row("City / Area", f"{result.entities.city or ''} {f'({result.entities.address_or_area})' if result.entities.address_or_area else ''}".strip() or "[dim]Not specified[/dim]")
    table.add_row("Cuisine / Activity", result.entities.cuisine_or_type or "[dim]Not specified[/dim]")
    table.add_row("Price Cues", result.entities.price_cues or "[dim]Not specified[/dim]")
    table.add_row("Best Time", result.entities.best_time_to_visit or "[dim]Not specified[/dim]")
    table.add_row("Tags", ", ".join(result.tags) if result.tags else "[dim]None[/dim]")

    console.print(table)

    # Detailed Summaries
    console.print(Panel(result.transcript_summary, title="[bold blue]Audio & Speech Summary[/bold blue]", border_style="blue"))
    console.print(Panel(result.visual_summary, title="[bold purple]Visual & Frame Summary[/bold purple]", border_style="purple"))

    if result.entities.highlights:
        console.print("[bold yellow]Highlights / Must-Try:[/bold yellow]")
        for h in result.entities.highlights:
            console.print(f"  • {h}")

    if result.entities.actionable_tips:
        console.print("\n[bold red]Actionable Tips / Practical Info:[/bold red]")
        for tip in result.entities.actionable_tips:
            console.print(f"  • {tip}")

    console.print("\n[bold dim]Semantic Search Blob (Ready for Vector Embeddings):[/bold dim]")
    console.print(f"[dim]{result.search_blob}[/dim]\n")

def main():
    print_banner()

    parser = argparse.ArgumentParser(description="Process video file or URL with Gemini Multimodal API")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", "-f", type=str, help="Path to local video file (.mp4, .mov, etc.)")
    group.add_argument("--url", "-u", type=str, help="Public URL of Instagram Reel, YouTube Short, or video")
    parser.add_argument("--api-key", "-k", type=str, default=None, help="Optional Gemini API key override")
    parser.add_argument("--model", "-m", type=str, default=None, help="Gemini model name")

    args = parser.parse_args()

    analyzer = GeminiVideoAnalyzer(api_key=args.api_key)

    if not analyzer.is_configured():
        console.print(
            "[bold red]Error:[/bold red] GEMINI_API_KEY is not configured.\n"
            "Please add your key in [bold yellow].env[/bold yellow] file or pass it with [bold cyan]--api-key YOUR_KEY[/bold cyan].\n"
            "You can get a free key at: [link=https://aistudio.google.com/]https://aistudio.google.com/[/link]"
        )
        sys.exit(1)

    video_path = None
    cleanup_needed = False

    try:
        if args.url:
            console.print(f"[cyan]Downloading video from URL:[/cyan] {args.url}")
            video_path, title = VideoDownloader.download_video_from_url(args.url)
            cleanup_needed = True
            console.print(f"[green]Downloaded:[/green] {title}")
        else:
            video_path = Path(args.file)
            if not video_path.exists():
                console.print(f"[bold red]Error:[/bold red] File does not exist: {video_path}")
                sys.exit(1)

        console.print(f"[cyan]Processing video via Gemini Files API with multimodal reasoning...[/cyan]")
        result = analyzer.analyze_video_file(video_path, model_name=args.model)
        display_analysis_result(result)

    except VideoDownloadError as e:
        console.print(f"\n[bold red]Download Error:[/bold red] {e.user_friendly_message}")
        console.print(f"[dim]Technical details: {e}[/dim]")
    except GeminiAnalysisError as e:
        console.print(f"\n[bold red]Analysis Error:[/bold red] {e}")
    except Exception as e:
        console.print(f"\n[bold red]Unexpected Error:[/bold red] {e}")
    finally:
        if cleanup_needed and video_path:
            VideoDownloader.cleanup_file(video_path)

if __name__ == "__main__":
    main()
