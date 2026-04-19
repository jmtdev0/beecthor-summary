# Changelog

### 19/04/2026
* `doc/polymarket_assistant/PLAYBOOK.md` actualizado con las lecciones recientes de `doc/JUGADA.md`: selección explícita entre daily/weekly/floor, `nearest strike first` rebajado a heurística y no veto, y nueva regla anti-chase para strikes que requieren una extensión extra tras un movimiento ya avanzado.
* El playbook ahora exige reconciliar `account_state.json` con `trade_log.json` y registrar también los cierres por expiry/resolution, no solo los take profits.
* Nuevo informe `doc/polymarket_assistant/ANALISIS_GENERAL_2026-04-19.md` con balance general del operador, principales fallos observados y escenarios prudentes de PnL mensual.
* Aplicados tres cambios prioritarios al operador: reconciliación como bloqueo duro de nuevas entradas, liberación de slot daily/weekly cuando una posición cae a `<=20%` sin venderla, e invalidación de órdenes pendientes viejas o repriced por encima de `max_entry_probability`.
* `/private/chat` ahora incluye una vista read-only del display de VS Code en el VPS, con refresco disparado solo desde el navegador cliente y captura bajo demanda en el servidor.
* Añadidos botones manuales `SELL 25% / 50% / 75% / 100%` en el dashboard de Polymarket para posiciones abiertas: encolan `REDUCE_POSITION` o `CLOSE_POSITION`, evitan duplicados y lanzan el executor del móvil en background.
* El dashboard de Polymarket mueve la venta manual a un modal con confirmación explícita por porcentaje, evitando que los controles `SELL` se solapen con el título de la posición en tarjetas estrechas.
* Corregido el modal de venta manual del dashboard: el confirm de JavaScript ya no rompe el script renderizado, así que el botón `SELL...` vuelve a abrir el popup correctamente.

### 18/04/2026
* Documentación centralizada bajo `doc/`, manteniendo `AGENTS.md` en la raíz como symlink de compatibilidad para tooling.
* El ciclo automático de Codex ahora usa `doc/polymarket_assistant/codex_cycle_prompt.md` como template mínimo de una sola línea y delega las instrucciones detalladas en `doc/polymarket_assistant/codex_cycle_instructions.md`.
* `run_cycle.py` y `scripts/summarize_beecthor.py` actualizados para leer/escribir sus Markdown canónicos desde `doc/`.
* `/root/run_polymarket_cycle.sh` actualizado para renderizar el nuevo prompt corto referenciando el `.md` de instrucciones.

### 16/04/2026
* `fetch_positions()` fix: posiciones resueltas ya no se muestran a GPT. Doble filtro: (1) `redeemable: true` excluye inmediatamente la posición; (2) comparación de fecha ahora timezone-aware (`end_dt.replace(tzinfo=UTC)` para fechas sin hora), eliminando el `TypeError` silencioso que dejaba pasar posiciones expiradas.
* Nuevo flujo automático del operador: `/root/run_polymarket_cycle.sh` deja de llamar a Copilot CLI directamente y pasa a usar a Codex en el chat de VS Code como motor de decisión. Cada ciclo exporta un snapshot fresh, envía un prompt corto con `run_id`, espera un `decision_file`, y luego ejecuta `run_cycle_codex.py --decision-file`. Si Codex no responde o el JSON es inválido, el wrapper fuerza `NO_ACTION`.
* Añadidos `polymarket_assistant/run_cycle_codex.py`, `polymarket_assistant/export_context_snapshot.py` y `polymarket_assistant/codex_cycle_prompt.md` para soportar el nuevo flujo de snapshot + prompt runtime hacia Codex, dejando `run_cycle.py` como ciclo base sin cambios específicos de Codex.
* `run_cycle_codex.py`: los `NO_ACTION` generados por fallback automático de Codex siguen registrándose en estado y logs, pero ya no envían resumen por Telegram.
* `polymarket-operator.timer` actualizado a horas pares UTC cada 2 horas; `polymarket-monitor.timer` se mantiene en horas impares.

### 14/04/2026
* Multi-position opening implemented: `run_cycle.py` now proposes up to 3 independent position slots per cycle (1 daily price-hit + 1 weekly price-hit + 1 floor). `execution.details` changed from a single dict to a list to accommodate multiple orders per cycle.
* "Bitcoin above $X" floor markets added: new `_fetch_floor_event_slugs()`, `parse_floor_market()`, and `fetch_active_floor_markets()` functions discover and expose contested (45–82% YES probability) floor markets to GPT. GPT can now bet YES on floor markets when Beecthor identifies strong support levels.
* `infer_position_market_type()` added to `run_cycle.py`: infers `floor`, `daily`, or `weekly` from position slug/event_slug patterns, since `fetch_positions()` does not return a `market_type` field natively.
* `validate_decision()` rewritten to enforce per-type slot limits independently: max 1 daily, max 1 weekly, max 1 floor, total cap 3 (`max_open_positions` raised from 2 → 3 in `account_state.json`, `max_floor_positions: 1` added).
* `copilot_prompt.md` updated with `new_floor_position` schema and floor market decision rules.
* `phone/polymarket_executor.py` rewritten to read from `pending_orders.json` (multi-order queue) instead of `last_run_summary.json`, with order-ID-based dedup via `~/.polymarket_executed_order_ids` (24h pruning).
* Dashboard (`server/copilot_chat.py`) fixed: `build_polymarket_snapshot()` and `build_cycle_trace_entries()` now handle `execution.details` as either a list or a dict — previously caused `AttributeError: 'list' object has no attribute 'get'`.
* **RDP fix (Hetzner VPS)**: resolved black-screen-on-login issue. Root cause: orphaned `xfce4-session` (PID 22258) running since March 26 held `org.xfce.SessionManager` on the systemd user dbus — every new xrdp connection tried to start a second XFCE session, which exited in 0 seconds. Fix: identified the conflict via `dbus-send ListNames` + xrdp-sesman log, then killed all orphaned XFCE processes (`xfce4-session`, `xfwm4`, `xfce4-panel`, `xfdesktop`, etc.) and removed the stale `/tmp/.X10-lock`. RDP login restored.
* Phantom position fix verified: `account_state.open_positions` reconciliation against live Polymarket slugs confirmed working — expired 70k dip position no longer shown to GPT.
* First profitable closed trade confirmed: `will-bitcoin-dip-to-74k-on-april-13` YES opened at BTC $74,779 — monitor auto-closed at take-profit when BTC touched $73,007. Realized PnL: +$1.2194.

### 10/04/2026
* `phone/polymarket_monitor_executor.py`: fix bug crítico en `build_order_dict` para órdenes SELL — `taker_amount` se computaba con el `amount` sin redondear, produciendo un precio efectivo `taker/maker > 1` que Polymarket rechazaba con 400. Ahora `taker_amount` se deriva del `maker_amount` ya redondeado. **Primer take-profit ejecutado correctamente** (`will-bitcoin-reach-73k-on-april-10`, YES, 1.92 shares @ 0.999).
* `phone/polymarket_monitor_executor.py`: detecta error 404 del order book (mercado ya resuelto) y lo trata como señal de auto-redención de Polymarket — cierre graceful sin error ni Telegram de fallo.
* `trade_log.json`: añadidas entradas manuales para `will-bitcoin-reach-73k-on-april-9` — posición abierta y TP/claim hechos por el usuario manualmente (servidor bloqueado por `min_entry_probability`, ya eliminado).

### 09/04/2026
* PLAYBOOK: regla de frescura del vídeo de Beecthor relajada — vídeo de D-1 se considera válido para apostar; D-2+ requiere confirmación extra.
* PLAYBOOK + código: stop-loss desactivado en fase inicial (portfolio < $15) — solo take-profit automático.
* Eliminado validador duro `min_entry_probability` del código — la decisión de probabilidad mínima pasa a ser responsabilidad exclusiva del PLAYBOOK y GPT.
* `phone/polymarket_monitor_executor.py`: SL eliminado, un solo intento de ejecución (sin reintentos).
* Dashboard Flask: timestamps de trazas convertidos a CET/CEST (Europe/Madrid).
* Dashboard Flask: `fetch_live_positions` corregido con `sizeThreshold=0.01` para excluir posiciones resueltas con size 0.
* Dashboard Flask: `classify_market_bucket` mejorado para cubrir patrones de slug semanales (`april-6-12`).
* Crons del móvil corregidos: rutas absolutas y `.` en lugar de `source` para compatibilidad con `/bin/sh` de crond.

### 08/04/2026
* Fix `get_transcript` en `phone/beecthor_summarizer.py`: migrado a la API instanciada de `youtube-transcript-api` v1.2.4+ (`YouTubeTranscriptApi().fetch()`), eliminando el método de clase obsoleto `list_transcripts`.
* Instalado `yt-dlp` en Termux como fallback de transcript.
* Añadido `. ~/.polymarket.env` a `~/.bashrc` del móvil para exponer `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` al cron.
* Nuevo cron en el móvil a las 16:45 UTC como disparo anticipado del summarizer (antes de las 17:45 existentes).
* Resumen del vídeo `x1A0itOzi18` generado y enviado al grupo de Telegram.

### 06/04/2026
* Backfill completado de dos vídeos pendientes de Beecthor en el repo principal: `IGDvoXUCgAA` y `-ZXOMl3jFqw`, ambos añadidos a `analyses_log.json` sin reenvío a Telegram y con transcript guardado en `transcripts/`.
* `phone/beecthor_summarizer.py` ampliado con `--video-id` y `--backfill`, detección portable del repo local y persistencia de entradas sin tocar `last_video_id.txt`.
* Lógica de transcript del summarizer del móvil desacoplada del script principal: ahora resuelve transcript localmente con `youtube-transcript-api` y fallback `yt-dlp` sin depender de variables de entorno de Telegram.
* Nuevo `CHAT.md` en la raíz como memoria conversacional desde 2026-04-06, con timestamps en Europe/Madrid y nota de contexto previo para continuidad con otros LLMs o agentes.
* `server/copilot_chat.py` evolucionado a dashboard Flask único con galería pública de Beecthor, zona privada de Polymarket, visor de logs, APIs JSON y endpoint `/api/mobile-log` para ingesta de eventos estructurados del móvil.
* Nuevo cliente ligero `phone/log_client.py` y emisión de eventos desde `polymarket_executor.py`, `polymarket_monitor_executor.py` y `beecthor_summarizer.py` para centralizar observabilidad en JSONL local del servidor.

### 01/04/2026
* Rutina diaria: vídeo `KpxFOusqi0g` analizado y enviado a Telegram. Rebote correctivo con resistencias en 69.6K-71.5K, sesgo principal aún bajista y objetivo técnico de continuidad hacia 58.9K mientras no invalide por arriba.

### 31/03/2026
* Rutina diaria: vídeo `z2bD36xFFz0` preparado para Telegram con sesgo principal bajista, resistencia clave en 67.8K-69K, posible extensión hacia 71K y objetivo de caída todavía orientado a 59.9K / 57K-58K si la corrección termina.

### 30/03/2026
* Copilot CLI instalado en Termux (Android ARM64): fix con symlink `node-pty/build/Release/pty.node → prebuilds/android-arm64/pty.node`. Autenticado con GH_TOKEN del servidor.
* Sistema de cola de órdenes (`pending_orders.json`): el servidor acumula órdenes pendientes en lugar de sobreescribir `last_run_summary.json`. El móvil ejecuta todas las pendientes en una pasada con deduplicación por `order_id`.
* Descubrimiento de mercados semanales: `fetch_active_btc_markets()` ahora consulta el tag `weekly` de Gamma API además de los slugs diarios. Scope reducido a daily + weekly (mensuales y anuales excluidos).
* Fix `nearest_strike_ok`: la regla de strike más cercano primero ahora se aplica por tipo de mercado (daily vs weekly) independientemente, evitando que un diario más cercano bloquee un semanal.
* Dos posiciones abiertas hoy desde el móvil: `will-bitcoin-dip-to-67k-on-march-30` YES @ 0.47 y `will-bitcoin-dip-to-66k-march-30-april-5` YES @ 0.65.
* Script `phone/beecthor_summarizer.py`: obtiene el último vídeo via RSS del canal, descarga transcript con `youtube-transcript-api`, llama a Copilot CLI con los últimos 2 ejemplos del log como formato de referencia, y hace commit+push a `analyses_log.json`. Cron diario a las 19:45 UTC.
* `phone/SETUP.md` actualizado con instrucciones completas y correctas para reinstalar desde cero.

### 29/03/2026
* Monitor ligero de posiciones implementado: `polymarket_assistant/run_monitor.py` se ejecuta cada 2 horas (horas impares UTC), evalúa stop-loss (≤20%) y take-profit (≥88%) sin GPT, firma orden SELL on-chain y hace commit a GitHub para que el móvil la ejecute.
* Analizado y enviado a Telegram el resumen del vídeo z2bD36xFFz0 con la tesis bajista, resistencias en 67.8k-69k y objetivo de continuidad hacia 59.9k.
* Ficheros systemd del monitor añadidos a `server/`: `polymarket-monitor.service` y `polymarket-monitor.timer` (horas impares UTC, intercalado con el ciclo completo en horas pares).
* Añadida interfaz web de chat con Copilot (`server/copilot_chat.py`): Flask app con login por contraseña, historial persistente y acceso desde el móvil vía VS Code Port Forwarding (puerto 5050).
* Playbook: hard rule ≥85% → no entrar nunca. Cartera ampliada a 5 posiciones (1 diaria + 2 semanales + 2 mensuales), con instrucción de entrar pronto en semanales y mensuales.
* Rutina diaria: vídeo `S9Rla5wtsJE` analizado y enviado a Telegram. Sesgo principal bajista, posible barrido hacia 67K-70K y objetivo técnico de fondo en 59K mientras no recupere 72K.

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
