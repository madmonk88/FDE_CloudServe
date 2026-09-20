"""Ask the provider what your key can actually run.

    python -m scripts.list_models
    python -m scripts.list_models --probe          # also test-call the top result
    python -m scripts.list_models --set-env        # print the .env lines to use

Model catalogues move faster than anyone's documentation. Over the course of
this build, OpenRouter retired the free Llama 3.3 70B and started returning a
404 pointing at the paid one, and Groq returned `model_not_found` for a model
its own documentation still listed as in production. Choosing a model id from
a web page is guesswork; asking the provider's `/models` endpoint with the key
you actually hold is not.

So this asks. It works against any OpenAI-compatible provider, because it uses
the base URL and key already in your configuration.

If the run says a model does not exist, run this before changing anything
else. It is faster than reading release notes and it cannot be out of date.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from src.config import get_settings  # noqa: E402

# Substrings worth flagging, in preference order. Instruction-tuned chat
# models of a size that suits this workload; embedding, audio, moderation and
# vision-only models are not useful here.
PREFERRED = [
    "llama-3.3-70b",
    "llama-3.1-70b",
    "llama-3.1-8b",
    "llama-4",
    "gpt-oss-120b",
    "gpt-oss-20b",
    "qwen",
    "mixtral",
    "gemma",
]

EXCLUDE = ["whisper", "embed", "tts", "guard", "moderation", "rerank", "vision-only"]


def looks_usable(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(x in lowered for x in EXCLUDE)


def rank(model_id: str) -> int:
    lowered = model_id.lower()
    for i, p in enumerate(PREFERRED):
        if p in lowered:
            return i
    return len(PREFERRED)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List the models your key can use.")
    parser.add_argument("--probe", action="store_true", help="Test-call the top candidate.")
    parser.add_argument(
        "--set-env", action="store_true", help="Print the .env lines for the top candidate."
    )
    parser.add_argument("--all", action="store_true", help="Show every model, unfiltered.")
    args = parser.parse_args(argv)

    settings = get_settings(refresh=True)
    cfg = settings.model

    if not cfg.api_key:
        print(
            "No API key configured. Set GROQ_API_KEY or OPENROUTER_API_KEY in .env.",
            file=sys.stderr,
        )
        return 2

    base = cfg.base_url.rstrip("/")
    print(f"\nprovider : {cfg.provider}")
    print(f"base url : {base}")
    print(f"currently configured model: {cfg.model}")
    print("-" * 68)

    try:
        response = httpx.get(
            f"{base}/models",
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=30.0,
        )
    except Exception as exc:
        print(f"could not reach {base}/models: {exc}", file=sys.stderr)
        return 1

    if response.status_code == 401:
        print("The provider rejected the key (401). Check it was pasted in full.", file=sys.stderr)
        return 1
    if response.status_code >= 400:
        print(f"{base}/models returned {response.status_code}: {response.text[:300]}", file=sys.stderr)
        return 1

    payload = response.json()
    models = payload.get("data") or payload.get("models") or []
    ids = sorted({str(m.get("id")) for m in models if isinstance(m, dict) and m.get("id")})

    if not ids:
        print("The provider returned no models.", file=sys.stderr)
        return 1

    print(f"{len(ids)} model(s) available to this key\n")

    shown = ids if args.all else [m for m in ids if looks_usable(m)]
    shown = sorted(shown, key=lambda m: (rank(m), m))

    configured_ok = cfg.model in ids
    for model_id in shown:
        marker = ""
        if model_id == cfg.model:
            marker = "   <- currently configured"
        elif rank(model_id) < len(PREFERRED) and not configured_ok:
            marker = ""
        print(f"  {model_id}{marker}")

    print()
    if configured_ok:
        print(f"Your configured model ({cfg.model}) IS available. If a run still")
        print("fails with model_not_found, the failure is elsewhere.")
    else:
        print(f"Your configured model ({cfg.model}) is NOT in this list.")
        print("That is why the run fails. Pick one from above.")

    candidates = [m for m in shown if rank(m) < len(PREFERRED)]
    top = candidates[0] if candidates else (shown[0] if shown else None)

    if top and not configured_ok:
        print()
        print(f"Suggested: {top}")

    if args.set_env and top:
        print()
        print("Put these in .env:")
        print("-" * 68)
        print(f"LLM_BASE_URL={base}")
        print(f"LLM_MODEL={top}")
        print("-" * 68)

    if args.probe and top:
        print()
        print(f"probing {top} ...")
        try:
            probe = httpx.post(
                f"{base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {cfg.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": top,
                    "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
                    "max_tokens": 10,
                    "temperature": 0,
                },
                timeout=45.0,
            )
            if probe.status_code >= 400:
                print(f"  FAILED {probe.status_code}: {probe.text[:300]}")
                return 1
            content = (probe.json()["choices"][0]["message"]["content"] or "").strip()
            print(f"  ok — replied {content[:60]!r}")
            print()
            print(f"  Use it: set LLM_MODEL={top} in .env")
        except Exception as exc:
            print(f"  probe failed: {exc}")
            return 1

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
