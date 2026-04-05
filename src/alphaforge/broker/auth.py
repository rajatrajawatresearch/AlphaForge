"""Kite Connect authentication flow with session persistence."""

import json
import logging
from datetime import datetime
from pathlib import Path

from kiteconnect import KiteConnect

from ..utils.errors import AuthError
from ..utils.time import IST

logger = logging.getLogger("alphaforge.broker")

SESSION_FILE = Path("data/.session.json")


def _save_session(access_token: str, public_token: str) -> None:
    """Persist session to disk for same-day reuse."""
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    session_data = {
        "access_token": access_token,
        "public_token": public_token,
        "date": datetime.now(IST).strftime("%Y-%m-%d"),
        "timestamp": datetime.now(IST).isoformat(),
    }
    SESSION_FILE.write_text(json.dumps(session_data, indent=2))
    logger.info("Session saved to %s", SESSION_FILE)


def _load_session() -> dict | None:
    """Load a persisted session if it's from today."""
    if not SESSION_FILE.exists():
        return None

    try:
        data = json.loads(SESSION_FILE.read_text())
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if data.get("date") == today and data.get("access_token"):
            logger.info("Reusing today's saved session")
            return data
        logger.info("Saved session is stale (from %s), need fresh auth", data.get("date"))
        return None
    except (json.JSONDecodeError, KeyError):
        return None


def authenticate(api_key: str, api_secret: str) -> KiteConnect:
    """Authenticate with Kite Connect.

    First tries to reuse a saved session from today.
    If unavailable, prompts user for request_token via login URL.

    Returns:
        Authenticated KiteConnect instance.
    """
    kite = KiteConnect(api_key=api_key)

    # Try saved session
    saved = _load_session()
    if saved:
        kite.set_access_token(saved["access_token"])
        try:
            profile = kite.profile()
            logger.info("Authenticated as %s (reused session)", profile.get("user_name", "unknown"))
            return kite
        except Exception:
            logger.warning("Saved session invalid, need fresh auth")

    # Fresh authentication
    login_url = kite.login_url()
    print("\n" + "=" * 60)
    print("  KITE CONNECT AUTHENTICATION")
    print("=" * 60)
    print(f"\n  1. Open this URL in your browser:\n\n     {login_url}\n")
    print("  2. Log in with your Zerodha credentials")
    print("  3. After redirect, copy the 'request_token' from the URL")
    print("     (It's the value after ?request_token= in the redirect URL)")
    print("\n" + "=" * 60)

    request_token = input("\n  Paste request_token here: ").strip()

    if not request_token:
        raise AuthError("No request_token provided")

    try:
        session = kite.generate_session(request_token, api_secret=api_secret)
        access_token = session["access_token"]
        public_token = session.get("public_token", "")

        kite.set_access_token(access_token)
        _save_session(access_token, public_token)

        profile = kite.profile()
        logger.info("Authenticated as %s", profile.get("user_name", "unknown"))
        print(f"\n  Authenticated as: {profile.get('user_name', 'unknown')}")
        print(f"  Email: {profile.get('email', 'N/A')}")
        print(f"  Broker: {profile.get('broker', 'N/A')}")
        print()

        return kite

    except Exception as e:
        raise AuthError(f"Authentication failed: {e}") from e
