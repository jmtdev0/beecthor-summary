# Changelog

### 29/03/2026
* Monitor ligero de posiciones implementado: `polymarket_assistant/run_monitor.py` se ejecuta cada 2 horas (horas impares UTC), evalúa stop-loss (≤20%) y take-profit (≥88%) sin GPT, firma orden SELL on-chain y hace commit a GitHub para que el móvil la ejecute.
* Scripts del móvil movidos al repositorio bajo `phone/`: `polymarket_executor.py` y nuevo `polymarket_monitor_executor.py` (lee `last_monitor_action.json` en lugar de `last_run_summary.json`).
* Ficheros systemd del monitor añadidos a `server/`: `polymarket-monitor.service` y `polymarket-monitor.timer` (horas impares UTC, intercalado con el ciclo completo en horas pares).

### 28/03/2026
* Horario del operador cambiado a 4 ejecuciones diarias: 01:00, 07:30, 13:30 y 20:00 UTC.
* Rutina diaria de Beecthor automatizada: el ciclo de las 20:00 UTC ahora ejecuta `summarize_beecthor.py --auto` antes del ciclo de Polymarket. Genera el resumen via Copilot CLI, lo envía a Telegram y hace commit, dejando el contexto fresco para el análisis de mercado.
* Añadido `--auto` flag a `scripts/summarize_beecthor.py`: nueva función `generate_summary_via_copilot()` llama a Copilot CLI (sin `--continue`) y rellena los campos `macro_summary`, `resumen` y `full_analysis` del mensaje de Telegram.
* Pipeline de ejecución en móvil validado end-to-end: 2 trades confirmados on-chain en Polygon. Flujo completo: servidor firma la orden (py-clob-client) → commit a GitHub → móvil (Termux) lee via GitHub API y hace POST al CLOB con IP residencial.
* Corregido `POLY_ADDRESS` en `polymarket_executor.py`: usaba `POLY_FUNDER` en lugar de `POLY_SIGNER_ADDRESS` en las cabeceras L2 HMAC (causaba 400 "order signer address has to be the address of the API KEY").
* API key de Polymarket re-derivada (la anterior había expirado): nueva key `ca7621b0-...` actualizada en el `.env` del servidor y del móvil.
* `polymarket_executor.py` actualizado para usar el endpoint de GitHub Contents API en lugar de `raw.githubusercontent.com` (la CDN de raw tiene caché de varios minutos).
* Corregidos dos bugs en `--force-bet`: slug con año en lugar de nombre del mes (`2026-03-27` → `march-27`), y outcome case-insensitive (`NO` → `No`).
* Horario del operador ajustado a 00:00 / 06:00 / 12:00 / 18:00 UTC tras analizar las horas reales de subida de los últimos 10 vídeos de Beecthor (rango 15:00–17:17 UTC). El ciclo de Beecthor se movió de las 20:00 a las 18:00 UTC (~1h tras el vídeo en lugar de ~4h).
* Notificaciones de órdenes redirigidas al chat personal de Telegram (ID 6104762145) en lugar del grupo; el resumen diario de Beecthor sigue yendo al grupo.
* Rutina diaria: vídeo `FVN4f7I-fMA` analizado y enviado a Telegram. Rebote táctico probable hacia 68.0K-68.6K, continuación bajista como escenario principal y objetivo técnico de 59K mientras no recupere 72K.

### 27/03/2026
* Diagnosticado y corregido fallo silencioso del operador de Polymarket: `systemd` no exponía `HOME=/root`, por lo que `gh auth status` fallaba en cada ciclo. Solución: `GH_TOKEN` añadido al `.env` del servidor + `Environment=HOME=/root` en el servicio.
* Añadido logging local por ciclo en el servidor: cada ejecución genera `/var/log/polymarket-operator/cycle-<timestamp>.log` con el JSON completo de la decisión.
* Primer ciclo autónomo exitoso confirmado: NO_ACTION (BTC $66,058), commiteado y pusheado a main.


* Servidor Hetzner (168.119.231.76) configurado desde cero: Ubuntu + XFCE + xrdp + VS Code + Firefox. Seguridad: firewall (ufw), SSH solo con clave, fail2ban.
* Operador de Polymarket desplegado de forma autónoma en el servidor con systemd timer (cada 4 horas). LLM: Copilot CLI (GPT-5.4) con `--continue` para contexto persistente entre ciclos.
* Corregido `fetch_active_btc_markets`: ahora busca por slug de evento diario (`what-price-will-bitcoin-hit-on-{month}-{day}`) en vez de la API genérica de Gamma que no devolvía estos mercados.
* PLAYBOOK.md actualizado: pasos del ciclo definidos (stop-loss → take-profit → analizar → buscar → apostar), probabilidad mínima subida a 50%, cap de $1 por apuesta mientras el portfolio < $15.
* Auto-commit + push tras cada ciclo con resumen de la decisión en el mensaje del commit.
* Rutina diaria: vídeo `F1Sxj6esnqo` analizado y enviado a Telegram. Soporte clave en 65K, posible rebote táctico a 68-70K y sesgo principal aún bajista mientras no recupere estructura.

### 26/03/2026
* Rutina diaria: vídeo `ev14kX8L4Ww` analizado y enviado a Telegram. Sesgo de rebote correctivo desde la zona 67.9K-68.4K hacia 73.26K-74.04K y vigilancia de cortos en 73.5K+.

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
