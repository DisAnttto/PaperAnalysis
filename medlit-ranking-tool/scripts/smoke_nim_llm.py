"""One-shot check that the configured NVIDIA NIM (Kimi) endpoint responds.

Run from repo root: py -3 scripts/smoke_nim_llm.py
"""

import asyncio
import sys
from pathlib import Path

# Ensure package root is importable
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


async def main() -> int:
    from openai import AsyncOpenAI

    from app.core.config import get_llm_client_config, get_llm_extra_request_kwargs

    cfg = get_llm_client_config()
    if cfg.backend != "nvidia_nim":
        print(f"Expected LLM_BACKEND=nvidia_nim, got backend={cfg.backend!r}")
        return 1
    if not cfg.api_key:
        print("NVIDIA_NIM_API_KEY is empty.")
        return 1

    print(f"backend={cfg.backend} model={cfg.model!r} base_url={cfg.base_url!r}")
    client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=120.0)
    resp = await client.chat.completions.create(
        model=cfg.model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": 'Reply with exactly one word: "pong"'},
        ],
        temperature=0.0,
        max_tokens=32,
        **get_llm_extra_request_kwargs(),
    )
    text = (resp.choices[0].message.content or "").strip()
    print(f"response: {text!r}")
    if not text:
        print("Empty response from model.")
        return 1
    print("OK — NVIDIA NIM Kimi responded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
