"""Developer tool: make ONE test request to the configured model and print what happened (the key is never printed).

    python -m chatbot.check_llm
"""
import sys

from . import llm
from .config import load_dotenv_once, load_settings


def main():
    load_dotenv_once()
    s = load_settings()
    print("model:", s.model, "| endpoint:", s.base_url or "(default)", "| key set:", bool(s.api_key), "| scope:", s.scope)
    if not s.llm_configured:
        print("RESULT: not configured. Put your key after CAMORRA_LLM_API_KEY= in the .env file and run this again.")
        return 1
    try:
        out = llm.complete(s, [{"role": "user", "content": "Reply with one short friendly sentence in Roman Urdu."}], max_tokens=60)
    except Exception as exc:                      # shown here, for the developer, in this terminal only
        print("RESULT: FAILED ->", exc)
        return 2
    print("RESULT: OK ->", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
