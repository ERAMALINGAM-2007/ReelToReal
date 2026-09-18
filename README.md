# 🎬 ReelToReal — AI-Powered Personal Planner

> **Transform saved Instagram Reels and YouTube Shorts into an organized, searchable personal knowledge base with conversational AI planning and interactive map view.**

---

## 🌟 Overview

Everyone saves endless Instagram Reels, TikToks, and YouTube Shorts — a hidden ramen gem, a weekend ridge hike, or "5 cafes to try in the city" — only for them to sit forgotten in saved folders.

**ReelToReal** leverages **Google Gemini Multimodal AI** to understand both what is spoken (audio transcription) and what is shown (dishes, places, aesthetic decor, on-screen text overlays). It extracts structured entities, generates semantic vector embeddings, and enables natural language planning (e.g. *"Plan my Friday evening with ramen and dessert"*), grounded directly in your saved bookmarks.

---

## 🚀 Key Features

- **⚡ Multimodal Video Understanding in 1 Call**:
  Uses Gemini's native video understanding (`gemini-3.8-flash`) via the Gemini Files API. In a single API call, speech, scenery, dishes, venues, and on-screen text are parsed jointly without separate Whisper/frame extraction pipelines.
- **🏷️ Automated Categorization & Entity Extraction**:
  Extracts place names, cities, neighborhoods, cuisine types, price cues, must-try highlights, and actionable tips (e.g., *"cash only"*, *"arrive before sunset"*).
- **🧠 Personal Vector Knowledge Base (RAG)**:
  Embeds extracted content using `models/gemini-embedding-001` and stores them in a local SQLite vector store with cosine similarity retrieval.
- **🪄 Conversational AI Planner**:
  Answers natural-language planning queries by retrieving relevant bookmarks and generating step-by-step itineraries that cite the source clips.
- **🗺️ Interactive Map View**:
  Geocodes locations with OpenStreetMap Nominatim and plots color-coded category pins (🍜 Food, ✈️ Travel, 🧗 Activity, etc.) on an interactive Leaflet.js map.
- **📁 Dual Ingestion Paths**:
  Reliable drag-and-drop video file upload (`.mp4`, `.mov`, `.webm`, `.mkv`) + public URL scraping via `yt-dlp` with graceful fallback handling.

---

## 🛠️ Tech Stack ($0 Zero-Cost Architecture)

| Layer | Technology | Cost |
|---|---|---|
| **Multimodal AI** | Google Gemini (`gemini-3.8-flash`) | Free Tier (Google AI Studio) |
| **Embeddings** | Gemini (`models/gemini-embedding-001`) | Free Tier |
| **Backend** | FastAPI (Python 3.10+) | Open Source / Free |
| **Database & Vector Store** | SQLite + NumPy Cosine Similarity | Local / Free |
| **Geocoding** | OpenStreetMap Nominatim | Free (No API key needed) |
| **Map Rendering** | Leaflet.js + OpenStreetMap Tiles | Free (No API key needed) |
| **Frontend** | Vanilla JS + HTML5 + Glassmorphism CSS | Static / Free |
| **Link Scraping** | `yt-dlp` | Open Source |

---

## 📂 Project Structure

```
ReelToReal/
├── app/
│   ├── config.py                 # Environment and application configuration
│   ├── main.py                   # FastAPI application & API endpoints
│   ├── models/
│   │   └── schema.py             # Pydantic schemas (Entities, SavedItem, RAG Plan, MapPins)
│   └── services/
│       ├── gemini_analyzer.py    # Native multimodal video reasoning engine
│       ├── embedding_service.py  # Gemini text embeddings generator
│       ├── storage_service.py    # Knowledge base & vector cosine search
│       ├── geocoding_service.py  # OpenStreetMap geocoder with caching & rate-limit
│       ├── rag_planner.py        # Grounded conversational planner
│       └── video_downloader.py   # Ingestion & link scraping with fallback
├── data/
│   ├── reeltoreal.db             # Local SQLite database
│   └── media/                    # Permanent media storage for clip playback
├── static/                       # Web Application Frontend
│   ├── index.html                # App UI (Feed, Planner Chat, Map View)
│   ├── css/style.css             # Glassmorphism dark mode design system
│   └── js/
│       ├── app.js                # Feed rendering, search, file upload
│       ├── chat.js               # Conversational AI planner & citation handling
│       └── map.js                # Leaflet interactive map with custom pins
├── test_full_app.py              # End-to-end integration test suite
├── test_pipeline.py              # Standalone CLI test utility
├── verify_pipeline.py            # Component unit test suite
├── requirements.txt              # Python dependencies
├── .env.example                  # Environment configuration template
└── README.md
```

---

## 🏁 Quick Start

### 1. Clone the Repository
```bash
git clone https://github.com/ERAMALINGAM-2007/ReelToReal.git
cd ReelToReal
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure API Key
Create a `.env` file from `.env.example`:
```bash
cp .env.example .env
```
Add your free Gemini API key from [Google AI Studio](https://aistudio.google.com/):
```env
GEMINI_API_KEY=AIzaSy...your_gemini_api_key...
GEMINI_MODEL=gemini-3.8-flash
GEMINI_EMBEDDING_MODEL=models/gemini-embedding-001
```

### 4. Run the Web Application
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Open your browser at **`http://localhost:8000`**.

---

## 🧪 Testing

Run the automated integration test suite:
```bash
python test_full_app.py
```

Process a single video via CLI:
```bash
python test_pipeline.py --file path/to/your/clip.mp4
```

---

## 📄 License
MIT License.
