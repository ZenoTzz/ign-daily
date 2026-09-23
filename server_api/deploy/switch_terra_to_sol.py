#!/usr/bin/env python3
"""Probe GPT-6 Sol, then switch the production title and fulltext model."""

from __future__ import annotations

import json
import os
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path


OLD_MODEL = "gpt-5.6-terra"
NEW_MODEL = "gpt-6-sol"
BASE_URL = "https://api.apikey.fan/v1"


def env_lines_and_values(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return lines, values


def atomic_text(path: Path, content: str) -> None:
    metadata = path.stat()
    temp = path.with_name(path.name + ".sol.tmp")
    try:
        temp.write_text(content, encoding="utf-8")
        os.chmod(temp, stat.S_IMODE(metadata.st_mode))
        if hasattr(os, "chown"):
            os.chown(temp, metadata.st_uid, metadata.st_gid)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def probe(api_key: str, base_url: str) -> None:
    payload = {
        "model": NEW_MODEL,
        "messages": [{"role": "user", "content": "Reply with the JSON object {\"ok\":true}."}],
        "response_format": {"type": "json_object"},
        "reasoning_effort": "low",
        "max_completion_tokens": 512,
        "stream": False,
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GPT-6 Sol relay probe returned HTTP {exc.code}") from exc
    content = result.get("choices", [{}])[0].get("message", {}).get("content") or ""
    try:
        success = json.loads(content).get("ok") is True
    except (ValueError, AttributeError):
        success = False
    if not success:
        raise RuntimeError("GPT-6 Sol relay probe did not return the requested JSON")
    response_model = str(result.get("model") or "")
    if response_model and response_model.casefold() != NEW_MODEL:
        raise RuntimeError(f"Relay returned a different model: {response_model}")
    print(json.dumps({"probe": "ok", "requested_model": NEW_MODEL, "response_model": response_model}))


def updated_config(config: dict) -> dict:
    keys = ("api_model", "api_title_model", "api_fulltext_model")
    current = {key: config.get(key) for key in keys}
    if any(value not in {OLD_MODEL, NEW_MODEL} for value in current.values()):
        raise RuntimeError(f"Unexpected current model settings: {current}")
    updated = dict(config)
    for key in keys:
        updated[key] = NEW_MODEL
    updated["api_title_thinking"] = "low"
    updated["api_fulltext_thinking"] = "low"
    models = []
    for entry in config.get("api_models", []):
        item = dict(entry)
        if item.get("model") == OLD_MODEL:
            item.update({"label": "GPT-6 Sol (APIKEY.FAN 外接版)", "model": NEW_MODEL})
        models.append(item)
    updated["api_models"] = models
    updated["updated_at"] = "2026-09-23T00:00:00.000Z"
    updated["notes"] = "Production uses APIKEY.FAN with GPT-6 Sol at low reasoning. API keys remain in server secrets."
    return updated


def main() -> None:
    app = Path(os.environ.get("APP_DIR", "/srv/ign-daily"))
    env_path = app / ".env"
    config_path = app / "data" / "automation-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if all(config.get(key) == NEW_MODEL for key in ("api_model", "api_title_model", "api_fulltext_model")) and all(
        config.get(key) == "low" for key in ("api_title_thinking", "api_fulltext_thinking")
    ):
        print("GPT6_SOL_MIGRATION_NOOP")
        return
    updated = updated_config(config)
    if str(config.get("api_base_url") or "").rstrip("/") != BASE_URL:
        raise RuntimeError("Production API base URL differs from the expected relay")
    lines, values = env_lines_and_values(env_path)
    api_key = values.get("TRANSLATOR_API_KEY")
    if not api_key:
        raise RuntimeError("TRANSLATOR_API_KEY is missing from the server secret file")
    probe(api_key, BASE_URL)

    rewritten = []
    found = False
    for line in lines:
        if line.startswith("TRANSLATOR_MODEL="):
            rewritten.append("TRANSLATOR_MODEL=" + NEW_MODEL)
            found = True
        else:
            rewritten.append(line)
    if not found:
        rewritten.append("TRANSLATOR_MODEL=" + NEW_MODEL)
    atomic_text(env_path, "\n".join(rewritten) + "\n")
    atomic_text(config_path, json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
    print("GPT6_SOL_MIGRATION_COMPLETE")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"GPT6_SOL_MIGRATION_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
