# Changelog

### 01/03/2025
* Initial project setup: GitHub Actions workflow for Beecthor Bitcoin summary
* Python script to fetch latest YouTube video, extract transcript, summarize with Groq (Llama 3.3 70B), and send to Telegram
* Supports `youtube-transcript-api` primary method with `yt-dlp` VTT fallback
* Persists last processed video ID in `last_video_id.txt` to avoid duplicate messages
