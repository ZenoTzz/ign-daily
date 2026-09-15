#!/usr/bin/env python3
"""Verify Terra, then migrate production translator configuration from Luna."""

from __future__ import annotations

import json
import os
import stat
import urllib.request
from pathlib import Path

OLD_MODEL = "gpt-5.6-luna"
NEW_MODEL = "gpt-5.6-terra"

def read_env(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return lines, values

def atomic_text(path: Path, text: str) -> None:
    metadata = path.stat()
    mode = stat.S_IMODE(metadata.st_mode)
    temp = path.with_name(path.name + ".terra.tmp")
    temp.write_text(text, encoding="utf-8")
    os.chmod(temp, mode)
    # os.replace() keeps the temporary file's ownership, not the target's.
    # Preserve both ownership and mode so cron workers can still read secrets.
    if hasattr(os, "chown"):
        os.chown(temp, metadata.st_uid, metadata.st_gid)
    os.replace(temp, path)

def probe(base_url: str, api_key: str) -> None:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps({
            "model": NEW_MODEL,
            "messages": [{"role": "user", "content": "Reply with exactly READY"}],
            "max_tokens": 16,
            "temperature": 0,
        }).encode(),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode())
    content = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    response_model = str(body.get("model") or "")
    if response.status != 200 or content != "READY" or "terra" not in response_model.lower():
        raise RuntimeError(f"Terra probe failed: status={response.status}, content={content!r}, response_model={response_model!r}")
    print(json.dumps({"http_status": response.status, "content": content, "response_model": response_model}))

def main() -> None:
    app = Path(os.environ.get("APP_DIR", "/srv/ign-daily"))
    env_path = app / ".env"
    config_path = app / "data" / "automation-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    model_keys = ("api_model", "api_title_model", "api_fulltext_model")
    needs_migration = any(config.get(key) == OLD_MODEL for key in model_keys) or any(
        item.get("model") == OLD_MODEL for item in config.get("api_models", [])
    )
    if not needs_migration:
        print("TERRA_MIGRATION_NOOP")
        return
    env_lines, env_values = read_env(env_path)
    api_key = env_values.get("TRANSLATOR_API_KEY")
    if not api_key:
        raise RuntimeError("TRANSLATOR_API_KEY is required for the Terra probe")
    probe(str(config.get("api_base_url") or "https://api.apikey.fan/v1"), api_key)
    for key in model_keys:
        if config.get(key) == OLD_MODEL:
            config[key] = NEW_MODEL
    for item in config.get("api_models", []):
        if item.get("model") == OLD_MODEL:
            item.update({
                "label": "GPT-5.6 Terra (APIKEY.FAN 外接版)",
                "model": NEW_MODEL,
                "base_url": "https://api.apikey.fan/v1",
                "input_cache_hit_usd_per_million": "",
                "input_cache_miss_usd_per_million": "",
                "output_usd_per_million": "",
            })
    config["updated_at"] = "2026-09-14T00:00:00.000Z"
    config["notes"] = "Production uses the APIKEY.FAN external-script group with GPT-5.6 Terra. API keys must stay in server or GitHub secrets."
    rewritten_env = []
    model_seen = False
    for line in env_lines:
        if line.startswith("TRANSLATOR_MODEL="):
            rewritten_env.append("TRANSLATOR_MODEL=" + NEW_MODEL)
            model_seen = True
        else:
            rewritten_env.append(line)
    if not model_seen:
        rewritten_env.append("TRANSLATOR_MODEL=" + NEW_MODEL)
    atomic_text(config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    atomic_text(env_path, "\n".join(rewritten_env) + "\n")
    print("TERRA_MIGRATION_COMPLETE")

if __name__ == "__main__":
    main()
