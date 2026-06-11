# Beecthor Summary Style Guide

## Goal

Daily Telegram summaries should keep a stable editorial structure when the transcript supports it. The structure is a guide, not a rigid template: omit or merge sections that are not clearly present in the video.

## Visible Message

- Add a visible `⚡ <b>Perps Tip</b>` whenever possible.
- The Perps Tip must be one concise conditional sentence based on the video thesis, not a blind signal.
- If Beecthor does not give clear levels or setup, the tip should explicitly recommend waiting / `manos quietas`.
- Keep the macro view visible above the spoiler.
- Keep the short summary concrete, level-driven, and operational.
- Use 3-5 bullets starting with `•`.
- Prefer specific levels and scenarios over generic market commentary.

## Perps Tip Examples

- `Si BTC llega a 65.000 y rechaza la zona, el setup sería buscar short hacia 62.000.`
- `Si BTC pierde 61.000 con intención, aumentaría la probabilidad de continuación hacia 58.000.`
- `Ahora mismo no hay una apertura clara de short o long según el vídeo; manos quietas hasta que el precio confirme.`

## Spoiler Structure

Inside `full_analysis`, try to preserve these sections in this order:

1. `📊 <b>Situación actual</b>`
   - Where BTC is now, what zone it is testing, and what recent move matters.

2. `🎯 <b>Escenario principal</b>`
   - Beecthor's preferred path if the transcript makes one clear.

3. `🔻 <b>Escenario alternativo</b>`
   - The main invalidating or competing path.

4. `📉 <b>Macro (largo plazo)</b>`
   - Larger Elliott/macro context: ATH path, cycle lows, ABC, wave 4/5, etc.

5. `🧮 <b>Conteo y niveles técnicos</b>`
   - Current count, Fibonacci, Value Area/POC, EMAs, AVWAP, CME gap, order blocks, supports and resistances.

6. `💧 <b>Liquidaciones</b>`
   - Only when the transcript clearly mentions liquidity, leverage, sweeps, or liquidation zones.

7. `⚠️ <b>Niveles clave</b>`
   - Supports, resistances, invalidations, targets. Use bullets if useful.

8. `💡 <b>Estrategia que plantea</b>`
   - What Beecthor says he would do or avoid: entries, no-trade conditions, stop/invalidations, patience.

## Rules

- Do not invent indicators, levels, targets, or setups.
- If a section is absent or weak in the transcript, omit it or say that it is not developed clearly.
- The automated flow rejects summaries whose `full_analysis` does not contain at least three recognized HTML section headings.
- Keep the text in Spanish and Telegram-compatible HTML.
- Do not include Markdown headings inside Telegram payloads.
- Do not include `<tg-spoiler>` inside `full_analysis`; `build_message()` wraps it.
