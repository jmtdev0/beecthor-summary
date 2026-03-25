# Changelog

### 25/03/2026
* Rutina diaria: vídeo `rZ7c6g8mXF0` analizado y enviado a Telegram. BTC: 70.897$ / 61.304€ — SOL: 91.77$. Robot score: 8.4/10.

### 24/03/2026
* Añadidos `AGENTS.md` y `copilot-instructions.md` en la raíz para documentar el flujo diario, el uso de la venv local y la regla de previsualizar el mensaje antes de enviarlo cuando el usuario lo pida.
* Generada una previsualización del mensaje del nuevo vídeo de hoy sin enviarlo todavía a Telegram, para revisión manual previa.
* Actualizada la plantilla del mensaje de Telegram: la cabecera ahora incluye visión macro explícita y el spoiler resume de forma adaptativa las secciones típicas de Beecthor (macro, conteo actual, liquidaciones, Fibonacci, Value Area/POC, EMAs, AVWAP y conclusión operativa).
* El `robot score` deja de depender de una segunda llamada a Groq y pasa a calcularse localmente desde la transcripción, con justificación breve incluida en el mensaje.
* Eliminado Groq del flujo por completo: ya no se usa ni para resumir ni para transcribir audio. El script queda como recolector de transcripción/precios y el resumen final pasa a redactarse manualmente en chat por el agente.

### 16/03/2026
* Procesado vídeo tb-EC3nhdfM (entry #13, BTC $74,239). Robot score 8.7/10.
* Añadido Tier 2.5 al fallback de transcripción: yt-dlp descarga audio directo de YouTube + Groq Whisper transcribe. Se activa cuando el vídeo es tan reciente que YouTube aún no ha generado subtítulos automáticos.
* Añadido `--js-runtimes node` a todos los comandos yt-dlp (requerido desde versiones recientes de yt-dlp).
* Enviado mensaje de apuesta Bet #2 resuelta al grupo de Telegram (win por 21 minutos, $74,050 high).

### 15/03/2026
* Rutina diaria: vídeo `cBXHBcXrtpo` analizado y enviado a Telegram (entrada #12 del log). BTC: 71.735$ / 62.841€ — SOL: 88.60$. Robot score: 8.2/10.
* Prompt de robot score refinado: se desaconseja explícitamente el valor 8.2 y valores redondos, se anima a usar decimales (7.3, 8.7…) y el comentario debe citar algo concreto del vídeo de hoy.

### 14/03/2026
* Rutina diaria: vídeo `Op0XFls2yS0` analizado y enviado a Telegram (entrada #10 del log). BTC: 70.903$ / 61.824€ — SOL: 88.14$. Robot score: 8.2/10.
* Rutina diaria: vídeo `eBJ9P9wME3k` analizado y enviado a Telegram (entrada #11 del log). BTC: 70.681$ / 61.657€ — SOL: 87.00$. Robot score: 8.2/10.
* Prompt de resumen mejorado: incluye obligatoriamente un comentario macro sobre si BTC se dirige a ATH o a mínimos de ciclo.
* Prompt de robot score mejorado: escala detallada de 0 a 10 con criterios explícitos y sin ancla numérica en el ejemplo, para obtener puntuaciones más variadas y precisas.

### 12/03/2026
* Rutina diaria: vídeo `oOuduDegqK8` analizado y enviado a Telegram.
* Añadido Tier 2 al sistema de transcripción: yt-dlp descarga el `.es.vtt` directamente de YouTube (Tier 1 youtube-transcript-api seguía fallando; Invidious seguía inaccesible).
* Añadido `python-dotenv` al script — carga `.env` automáticamente sin pasos manuales en la shell.
* Script completamente reescrito: ahora incluye precios BTC/SOL (CoinGecko), índice robot, análisis HTML con spoiler, guardado de transcripción, actualización de `analyses_log.json` y commit automático a git.
* Nuevo flag `--backfill <VIDEO_ID>`: recupera transcripción, genera análisis y añade entrada al log sin re-enviar a Telegram (usado hoy para `oOuduDegqK8`).
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
