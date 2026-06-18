#!/usr/bin/env python3
"""Generate and apply historical Perps Tips without sending Telegram messages."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ANALYSES_LOG = REPO_ROOT / "analyses_log.json"
DEFAULT_TRANSCRIPTS_DIR = REPO_ROOT / "transcripts"
DEFAULT_MANIFEST = REPO_ROOT / "server_runtime_logs" / "perps_tip_backfill_2026_q2.json"
DEFAULT_MONTHS = ("2026-04", "2026-05", "2026-06")
TIP_MARKER = "⚡ <b>Perps Tip</b>"
MACRO_MARKER = "🧭 <b>Visión macro</b>"
MAX_TIP_CHARS = 360
MAX_TRANSCRIPT_CHARS = 14_000

CONDITION_RE = re.compile(r"\b(si|cuando|mientras|tras|siempre que|solo si|en caso de)\b", re.I)
DIRECTION_RE = re.compile(r"\b(short|long|corto|cortos|largo|largos)\b", re.I)
WAIT_RE = re.compile(
    r"\b(manos quietas|esperar|no hay|sin (?:una )?(?:apertura|entrada|señal|configuración|zona).{0,20}clara|no forzar)\b",
    re.I,
)
HINDSIGHT_RE = re.compile(
    r"\b(como (?:ya )?sabemos|después vimos|posteriormente vimos|acabó (?:subiendo|bajando)|"
    r"terminó (?:subiendo|bajando)|finalmente (?:subió|bajó)|se cumplió|no se cumplió)\b",
    re.I,
)
HTML_RE = re.compile(r"<[^>]+>")
LEVEL_RE = re.compile(
    r"(?<![\w])(?:\d+(?:[.,]\d+)?\s*[kK]|\d{1,3}(?:[.,]\d{3})+|\d{4,6})(?![\w])"
)


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(rendered)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def parse_months(raw: str) -> tuple[str, ...]:
    months = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not months or any(not re.fullmatch(r"\d{4}-\d{2}", month) for month in months):
        raise ValueError("Months must be a comma-separated YYYY-MM list")
    return months


def missing_tip_entries(entries: list[dict[str, Any]], months: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        entry
        for entry in entries
        if str(entry.get("timestamp") or "")[:7] in months
        and TIP_MARKER not in str(entry.get("message") or "")
    ]


def find_transcript(video_id: str, transcripts_dir: Path) -> Path | None:
    matches = sorted(transcripts_dir.glob(f"{video_id}_*.txt"))
    return matches[0] if matches else None


def build_historical_source(entry: dict[str, Any], transcripts_dir: Path) -> tuple[str, str]:
    message = str(entry.get("message") or "").strip()
    video_id = str(entry.get("video_id") or "").strip()
    transcript_path = find_transcript(video_id, transcripts_dir)
    if transcript_path is None:
        return f"HISTORICAL SUMMARY:\n{message}", "summary_only"

    transcript = transcript_path.read_text(encoding="utf-8").strip()
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n[historical transcript truncated]"
    return (
        f"HISTORICAL SUMMARY:\n{message}\n\nHISTORICAL TRANSCRIPT:\n{transcript}",
        "summary_and_transcript",
    )


def normalize_price_level(token: str) -> int | None:
    value = token.strip().lower().replace(" ", "")
    if value.endswith("k"):
        number = value[:-1].replace(",", ".")
        try:
            normalized = round(float(number) * 1000)
        except ValueError:
            return None
        return normalized if normalized >= 1000 else None

    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", value):
        value = value.replace(".", "").replace(",", "")
    try:
        normalized = int(value)
    except ValueError:
        return None
    return normalized if normalized >= 1000 else None


def extract_price_levels(text: str) -> set[int]:
    levels = set()
    for match in LEVEL_RE.finditer(text):
        normalized = normalize_price_level(match.group(0))
        if normalized is not None:
            levels.add(normalized)
    return levels


def validate_tip(tip: str, source: str) -> list[str]:
    errors: list[str] = []
    if not tip.strip():
        return ["tip is empty"]
    if tip != tip.strip():
        errors.append("tip has leading or trailing whitespace")
    if "\n" in tip or "\r" in tip:
        errors.append("tip must be one line")
    if len(tip) > MAX_TIP_CHARS:
        errors.append(f"tip exceeds {MAX_TIP_CHARS} characters")
    if HTML_RE.search(tip):
        errors.append("tip contains HTML")
    if HINDSIGHT_RE.search(tip):
        errors.append("tip contains hindsight language")
    is_wait = bool(WAIT_RE.search(tip))
    if not is_wait and not (CONDITION_RE.search(tip) and DIRECTION_RE.search(tip)):
        errors.append("tip must contain a conditional long/short setup or an explicit wait instruction")

    source_levels = extract_price_levels(source)
    invented_levels = sorted(extract_price_levels(tip) - source_levels)
    if invented_levels:
        errors.append(f"tip contains levels absent from the historical source: {invented_levels}")
    return errors


def build_prompt(
    entry: dict[str, Any],
    source: str,
    previous_tip: str = "",
    validation_errors: list[str] | None = None,
) -> str:
    date = str(entry.get("timestamp") or "")[:10]
    video_id = str(entry.get("video_id") or "")
    retry_context = ""
    if previous_tip or validation_errors:
        retry_context = (
            "\nA previous draft was rejected. Correct it without weakening the historical constraints.\n"
            f"Rejected draft: {previous_tip}\n"
            f"Validation errors: {validation_errors or []}\n"
        )
    return f"""Create one historical Perps Tip for Beecthor video {video_id}, dated {date}.

Write strictly from the information available on that date. Ignore everything that happened later and do not use external knowledge, current prices, or hindsight. Use only Beecthor's thesis and levels in the historical source below.

Requirements:
- Return one concise Spanish sentence, at most {MAX_TIP_CHARS} characters, with no HTML or line breaks.
- Prefer a conditional setup: "Si/cuando BTC ...", then long or short and Beecthor's stated target.
- Every numerical level in the tip must appear in the historical source.
- Do not claim that an outcome later happened.
- If there is no clear setup, recommend waiting or "manos quietas" instead of inventing one.
- Do not mention the historical BTC price unless it materially clarifies the setup.
{retry_context}
HISTORICAL SOURCE:
{source}
"""


def parse_llm_json(raw: str) -> dict[str, Any]:
    stripped = raw.strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(stripped):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise RuntimeError(f"Codex output did not contain valid JSON: {stripped[:500]}")
    if not isinstance(value, dict):
        raise RuntimeError("Codex output must be a JSON object")
    return value


def generate_tip_with_codex(
    entry: dict[str, Any],
    source: str,
    model: str = "",
    previous_tip: str = "",
    validation_errors: list[str] | None = None,
) -> str:
    codex_bin = shutil.which("codex")
    if not codex_bin:
        raise RuntimeError("Codex CLI not found in PATH")
    video_id = str(entry.get("video_id") or "")
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["video_id", "perps_tip"],
        "properties": {
            "video_id": {"type": "string", "enum": [video_id]},
            "perps_tip": {"type": "string"},
        },
    }
    prompt = build_prompt(entry, source, previous_tip, validation_errors)
    env = os.environ.copy()
    env.setdefault("LANG", "en_US.UTF-8")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    with tempfile.TemporaryDirectory() as temp_dir:
        schema_path = Path(temp_dir) / "schema.json"
        output_path = Path(temp_dir) / "result.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        command = [
            codex_bin,
            "exec",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
        ]
        if model:
            command.extend(["--model", model])
        command.append("-")
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            env=env,
            timeout=600,
            check=False,
        )
        raw = output_path.read_text(encoding="utf-8") if output_path.exists() else result.stdout

    if result.returncode != 0:
        raise RuntimeError(
            f"Codex exited {result.returncode}: stdout={result.stdout[:1000]} stderr={result.stderr[:1000]}"
        )
    payload = parse_llm_json(raw)
    if payload.get("video_id") != video_id:
        raise RuntimeError(f"Codex returned unexpected video_id: {payload.get('video_id')!r}")
    return str(payload.get("perps_tip") or "")


def new_manifest(months: tuple[str, ...]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "months": list(months),
        "generated_at": utc_now(),
        "updated_at": utc_now(),
        "entries": [],
    }


def load_manifest(path: Path, months: tuple[str, ...]) -> dict[str, Any]:
    if not path.exists():
        return new_manifest(months)
    manifest = load_json(path)
    if manifest.get("schema_version") != 1:
        raise RuntimeError("Unsupported manifest schema_version")
    if tuple(manifest.get("months") or []) != months:
        raise RuntimeError("Manifest months do not match requested months")
    if not isinstance(manifest.get("entries"), list):
        raise RuntimeError("Manifest entries must be a list")
    return manifest


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = utc_now()
    atomic_write_json(path, manifest)


def generate_manifest(
    analyses_log: Path,
    transcripts_dir: Path,
    manifest_path: Path,
    months: tuple[str, ...],
    expected_count: int | None,
    max_attempts: int,
    model: str,
) -> int:
    entries = load_json(analyses_log)
    targets = missing_tip_entries(entries, months)
    if expected_count is not None and len(targets) != expected_count:
        raise RuntimeError(f"Expected {expected_count} missing tips, found {len(targets)}")

    manifest = load_manifest(manifest_path, months)
    by_video_id = {
        str(item.get("video_id")): item
        for item in manifest["entries"]
        if isinstance(item, dict) and item.get("video_id")
    }
    target_ids = {str(entry.get("video_id") or "") for entry in targets}
    by_video_id = {video_id: item for video_id, item in by_video_id.items() if video_id in target_ids}

    for index, entry in enumerate(targets, start=1):
        video_id = str(entry.get("video_id") or "")
        existing = by_video_id.get(video_id)
        if existing and existing.get("status") == "valid":
            print(f"[{index}/{len(targets)}] {video_id}: cached")
            continue

        source, source_kind = build_historical_source(entry, transcripts_dir)
        tip = str((existing or {}).get("perps_tip") or "")
        errors = list((existing or {}).get("validation_errors") or [])
        attempts = int((existing or {}).get("attempts") or 0)
        runtime_error = ""

        for _ in range(max_attempts):
            attempts += 1
            try:
                tip = generate_tip_with_codex(entry, source, model, tip, errors)
                errors = validate_tip(tip, source)
                runtime_error = ""
            except Exception as exc:  # Keep the rest of the resumable batch moving.
                runtime_error = str(exc)
                errors = [runtime_error]
            if not errors:
                break

        item = {
            "video_id": video_id,
            "date": str(entry.get("timestamp") or "")[:10],
            "source_kind": source_kind,
            "status": "valid" if not errors else "error",
            "perps_tip": tip,
            "attempts": attempts,
            "validation_errors": errors,
        }
        if runtime_error:
            item["runtime_error"] = runtime_error
        by_video_id[video_id] = item
        manifest["entries"] = [by_video_id[str(target.get("video_id") or "")] for target in targets]
        save_manifest(manifest_path, manifest)
        print(f"[{index}/{len(targets)}] {video_id}: {item['status']}")

    invalid = [item for item in manifest["entries"] if item.get("status") != "valid"]
    print(f"Manifest: {len(manifest['entries']) - len(invalid)} valid, {len(invalid)} invalid")
    return 1 if invalid else 0


def manifest_entries_by_id(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("video_id")): item
        for item in manifest.get("entries") or []
        if isinstance(item, dict) and item.get("video_id")
    }


def insert_perps_tip(message: str, tip: str) -> tuple[str, bool]:
    if TIP_MARKER in message:
        return message, False
    position = message.find(MACRO_MARKER)
    if position == -1:
        raise RuntimeError("Message has no Visión macro insertion marker")
    escaped_tip = html.escape(tip, quote=False)
    block = f"{TIP_MARKER}\n{escaped_tip}\n\n"
    return message[:position] + block + message[position:], True


def apply_manifest(
    analyses_log: Path,
    transcripts_dir: Path,
    manifest_path: Path,
    months: tuple[str, ...],
    expected_count: int | None,
) -> int:
    entries = load_json(analyses_log)
    targets = missing_tip_entries(entries, months)
    if not targets:
        print("No missing Perps Tips. Nothing to apply.")
        return 0
    if expected_count is not None and len(targets) != expected_count:
        raise RuntimeError(f"Expected {expected_count} missing tips, found {len(targets)}")

    manifest = load_manifest(manifest_path, months)
    manifest_by_id = manifest_entries_by_id(manifest)
    target_ids = {str(entry.get("video_id") or "") for entry in targets}
    missing_ids = sorted(target_ids - manifest_by_id.keys())
    invalid_ids = sorted(
        video_id
        for video_id in target_ids
        if manifest_by_id.get(video_id, {}).get("status") != "valid"
    )
    if missing_ids or invalid_ids:
        raise RuntimeError(f"Manifest is incomplete: missing={missing_ids}, invalid={invalid_ids}")

    changed = 0
    for entry in entries:
        video_id = str(entry.get("video_id") or "")
        if video_id not in target_ids:
            continue
        tip = str(manifest_by_id[video_id].get("perps_tip") or "")
        source, _ = build_historical_source(entry, transcripts_dir)
        errors = validate_tip(tip, source)
        if errors:
            raise RuntimeError(f"Tip for {video_id} failed validation during apply: {errors}")
        updated_message, inserted = insert_perps_tip(str(entry.get("message") or ""), tip)
        if inserted:
            entry["message"] = updated_message
            changed += 1

    atomic_write_json(analyses_log, entries)
    print(f"Applied {changed} Perps Tips to {analyses_log}")
    return changed


def print_audit(analyses_log: Path, months: tuple[str, ...]) -> None:
    entries = load_json(analyses_log)
    targets = missing_tip_entries(entries, months)
    counts = Counter(str(entry.get("timestamp") or "")[:7] for entry in targets)
    print(f"Missing Perps Tips: {len(targets)}")
    for month in months:
        print(f"{month}: {counts.get(month, 0)}")


def print_report(manifest_path: Path, months: tuple[str, ...]) -> int:
    manifest = load_manifest(manifest_path, months)
    print("date\tvideo_id\tsource\tstatus\ttip")
    invalid = 0
    for item in manifest.get("entries") or []:
        status = str(item.get("status") or "")
        invalid += status != "valid"
        tip = str(item.get("perps_tip") or "").replace("\t", " ").replace("\n", " ")
        print(
            f"{item.get('date', '')}\t{item.get('video_id', '')}\t"
            f"{item.get('source_kind', '')}\t{status}\t{tip}"
        )
    return 1 if invalid else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("audit", "generate", "report", "apply"))
    parser.add_argument("--analyses-log", type=Path, default=DEFAULT_ANALYSES_LOG)
    parser.add_argument("--transcripts-dir", type=Path, default=DEFAULT_TRANSCRIPTS_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--months", default=",".join(DEFAULT_MONTHS))
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--model", default=os.environ.get("BEECTHOR_CODEX_MODEL", ""))
    args = parser.parse_args()
    months = parse_months(args.months)

    if args.mode == "audit":
        print_audit(args.analyses_log, months)
        return 0
    if args.mode == "report":
        return print_report(args.manifest, months)
    if args.mode == "generate":
        return generate_manifest(
            args.analyses_log,
            args.transcripts_dir,
            args.manifest,
            months,
            args.expected_count,
            args.max_attempts,
            args.model,
        )
    apply_manifest(
        args.analyses_log,
        args.transcripts_dir,
        args.manifest,
        months,
        args.expected_count,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
