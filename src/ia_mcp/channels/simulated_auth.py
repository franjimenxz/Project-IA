import hashlib
import hmac
from collections.abc import Callable, MutableSet
from datetime import UTC, datetime, timedelta

ACCOUNT_HEADER = "X-Simulated-Account"
TIMESTAMP_HEADER = "X-Simulated-Timestamp"
SIGNATURE_HEADER = "X-Simulated-Signature"
SIMULATED_HMAC_SECRET = b"ia-mcp-simulated-non-production-secret"
MAX_AGE = timedelta(seconds=300)


class SimulatedAuthError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


def sign_simulated(
    account: str,
    timestamp: str,
    body: bytes,
    *,
    secret: bytes = SIMULATED_HMAC_SECRET,
) -> str:
    payload = f"{account}.{timestamp}.".encode() + body
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


class SimulatedAuthenticator:
    def __init__(
        self,
        *,
        secret: bytes = SIMULATED_HMAC_SECRET,
        clock: Callable[[], datetime],
        replay_store: MutableSet[str],
        max_age: timedelta = MAX_AGE,
    ) -> None:
        self._secret = secret
        self._clock = clock
        self._replay_store = replay_store
        self._max_age = max_age

    def authenticate(
        self,
        *,
        account: str | None,
        timestamp: str | None,
        signature: str | None,
        body: bytes,
    ) -> str:
        if not account or not timestamp or not signature:
            raise SimulatedAuthError(
                "invalid_signature",
                "Simulated credentials are invalid.",
            )
        expected = sign_simulated(account, timestamp, body, secret=self._secret)
        try:
            matches = hmac.compare_digest(expected, signature)
        except (TypeError, ValueError):
            matches = False
        if not matches:
            raise SimulatedAuthError(
                "invalid_signature",
                "Simulated credentials are invalid.",
            )
        try:
            sent_at = datetime.fromtimestamp(int(timestamp), tz=UTC)
        except (TypeError, ValueError, OverflowError, OSError) as exc:
            raise SimulatedAuthError(
                "invalid_signature",
                "Simulated credentials are invalid.",
            ) from exc
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        if sent_at > now + timedelta(seconds=5) or now - sent_at > self._max_age:
            raise SimulatedAuthError(
                "stale_timestamp",
                "Simulated credentials are invalid.",
            )
        replay_key = f"{account}:{timestamp}:{signature}"
        if replay_key in self._replay_store:
            raise SimulatedAuthError(
                "replayed_request",
                "Simulated credentials are invalid.",
            )
        self._replay_store.add(replay_key)
        return account
