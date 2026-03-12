# Changelog

### 12/03/2026
* Rutina diaria: vídeo `oOuduDegqK8` analizado y enviado a Telegram.
* Añadido Tier 2 al sistema de transcripción: yt-dlp descarga el `.es.vtt` directamente de YouTube (Tier 1 youtube-transcript-api seguía fallando; Invidious seguía inaccesible).
* Añadido `python-dotenv` al script — carga `.env` automáticamente sin pasos manuales en la shell.
* Script completamente reescrito: ahora incluye precios BTC/SOL (CoinGecko), índice robot, análisis HTML con spoiler, guardado de transcripción, actualización de `analyses_log.json` y commit automático a git.
* README actualizado para ser guía completa de autoservicio: descripción del flujo, formato del mensaje, pasos de ejecución detallados y notas técnicas.

### 11/03/2026
* Rutina diaria: vídeo `rr0iPFxu6-0` ("BITCOIN TRAPPED!") analizado y enviado a Telegram (entrada 8 del log). BTC: 70.965$ (+0.67%) — SOL: 86.82$ (-0.66%). Robot score: 8.2/10.
* Robot score ahora incluye un breve comentario justificativo en el mensaje.

### 10/03/2026
* Rutina diaria: vídeo `4AdGq7RQSvc` ("¡NO TE CONFÍES!") analizado y enviado a Telegram (entrada 7 del log). BTC: 70.492$ / 60.611€ (+2.83%) — SOL: 87.40$ / 75.15€ (+7.00%).
* Nueva funcionalidad: transcripciones guardadas en carpeta `transcripts/` (un fichero por día).
* Nuevo formato de mensaje: precios de BTC y SOL (ayer vs. ahora con % de variación).
* Commits diarios a main activados.

### 09/03/2026
* Rutina diaria: vídeo `cKzm8x0JP5I` ("A NEW HOPE!") analizado y enviado a Telegram (entrada 6 del log). BTC: 68.555$ / 59.198€.

### 08/03/2026
* Rutina diaria: vídeo `EnT3I6hzCmw` ("MACRO COUNTDOWN!") analizado y enviado a Telegram (entrada 5 del log). BTC: 67.106$ / 57.765€.
* Nuevo formato de mensaje: resumen visible + análisis completo como spoiler (parse_mode HTML).

### 07/03/2026
* Rutina diaria: vídeo `yTz2oN6PQhA` ("MAXIMUM PAIN!") analizado y enviado a Telegram (entrada 4 del log). BTC: 67.628$ / 58.214€.
* Rutina diaria: vídeo `BNxWfRQ0RNA` ("¡ES UNA TRAMPA!") analizado y enviado a Telegram (entrada 3 del log). BTC: 68.323$ / 58.785€.

### 04/03/2026
* Ejecución manual del workflow: obtenida transcripción del último vídeo de Beecthor (`_zyxYZO67-8`) y análisis de Bitcoin generado con Groq (sin envío a Telegram)
* Identificado que Tier 1 (youtube-transcript-api) falla con vídeos recientes y las instancias Invidious están inaccesibles desde la red local; se usa yt-dlp directamente como alternativa para descarga de captions
* Análisis de fiabilidad de Beecthor a partir de sus últimos 10 vídeos: descarga de transcripciones, extracción de predicciones y valoración global de acierto. Resultado enviado a Telegram

### 01/03/2026
* Descartado GitHub Actions como plataforma de ejecución (IPs bloqueadas por YouTube)
* Añadido sistema de transcripción en 3 niveles: youtube-transcript-api → Invidious captions → Invidious audio + Groq Whisper
* Guía de despliegue en Oracle Cloud Always Free VPS documentada
* Guía de despliegue en Termux (Android) documentada como alternativa al VPS

### 01/03/2025
* Initial project setup: GitHub Actions workflow for Beecthor Bitcoin summary
* Python script to fetch latest YouTube video, extract transcript, summarize with Groq (Llama 3.3 70B), and send to Telegram
* Supports `youtube-transcript-api` primary method with `yt-dlp` VTT fallback
* Persists last processed video ID in `last_video_id.txt` to avoid duplicate messages
