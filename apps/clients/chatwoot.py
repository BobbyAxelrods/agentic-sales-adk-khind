"""Async Chatwoot REST API client for outbound WhatsApp message delivery."""

from __future__ import annotations

import asyncio
import logging

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from apps.config import settings

logger = logging.getLogger(__name__)

_SEND_TIMEOUT = 15.0   # seconds — text messages
_MEDIA_TIMEOUT = 60.0  # seconds — image/video uploads

# Module-level persistent client — connection pool reused across all calls.
# Instantiated lazily on first use so tests can swap it out before import side-effects.
_http: httpx.AsyncClient | None = None


def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=_SEND_TIMEOUT)
    return _http


def _is_retryable(exc: BaseException) -> bool:
    """Retry on 5xx responses and network-level errors. Never retry 4xx."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.ConnectError, httpx.TimeoutException))


_retry = retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    stop=stop_after_attempt(3),
    reraise=True,
)


class ChatwootClient:
    """Thin async wrapper around Chatwoot API v1.

    All methods are no-ops when Chatwoot is not configured, so the server
    starts cleanly in local dev without credentials.
    """

    @property
    def _configured(self) -> bool:
        return bool(
            settings.chatwoot_base_url
            and settings.chatwoot_api_token
            and settings.chatwoot_account_id
        )

    def _base(self, conversation_id: str) -> str:
        base = settings.chatwoot_base_url.rstrip("/")
        return (
            f"{base}/api/v1/accounts/{settings.chatwoot_account_id}"
            f"/conversations/{conversation_id}"
        )

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {"api_access_token": settings.chatwoot_api_token}

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def send_text(self, conversation_id: str, text: str) -> None:
        """Send a plain text reply to a Chatwoot conversation."""
        if not self._configured:
            logger.warning("Chatwoot not configured — skipping send_text: %.80s", text)
            return
        if not text.strip():
            return

        @_retry
        async def _do() -> None:
            r = await _get_http().post(
                f"{self._base(conversation_id)}/messages",
                headers={**self._auth_headers, "Content-Type": "application/json"},
                json={"content": text, "message_type": "outgoing", "private": False},
            )
            r.raise_for_status()

        await _do()

    async def send_attachment(
        self,
        conversation_id: str,
        data: bytes,
        filename: str,
        content_type: str,
    ) -> None:
        """Upload a media file as an outgoing attachment."""
        if not self._configured:
            logger.warning("Chatwoot not configured — skipping send_attachment: %s", filename)
            return
        if not data:
            return

        @_retry
        async def _do() -> None:
            # Use a dedicated client for media — longer timeout, separate connection.
            async with httpx.AsyncClient(timeout=_MEDIA_TIMEOUT) as client:
                r = await client.post(
                    f"{self._base(conversation_id)}/messages",
                    headers=self._auth_headers,
                    # Chatwoot multipart fields expect lowercase string booleans.
                    data={"message_type": "outgoing", "private": "false"},
                    files={"attachments[]": (filename, data, content_type)},
                )
                r.raise_for_status()

        await _do()

    async def get_conversation_status(self, conversation_id: str) -> str | None:
        """Return the conversation's current status ("pending", "open" ...), or None on error.

        The bot owns a chat while it is pending. Messages sent with the agent bot's token
        never change the status, so the bot does not set it back to pending itself.
        """
        if not self._configured:
            return None
        try:
            r = await _get_http().get(self._base(conversation_id), headers=self._auth_headers)
            r.raise_for_status()
            return r.json().get("status")
        except Exception:
            logger.warning("get_conversation_status failed (conv=%s)", conversation_id)
            return None

    async def escalate_conversation(
        self,
        conversation_id: str,
        label: str,
        state: dict,
    ) -> bool:
        """Unified escalation: disable bot, apply label, post context note, assign agent/team.

        Steps:
        1. Toggle status to 'open' — disables the bot gate (must complete first).
        2. In parallel: add the label + post private context note + assign to agent or team.

        Assignment uses CHATWOOT_HUMAN_AGENT_ID if set, else CHATWOOT_HUMAN_TEAM_ID.
        If neither is set the conversation is labelled but not assigned.
        Returns True once the chat is open; a failed step 2 call is logged only.
        """
        if not self._configured:
            logger.warning("Chatwoot not configured — skipping escalation (conv=%s).", conversation_id)
            return False

        context_lines = [
            f"Escalation label: {label}",
            f"Purchase stage:   {state.get('purchase_stage', '-')}",
            f"Language:         {state.get('language', '-')}",
            "",
            "── Customer details ──",
            f"Product:  {state.get('product_interest', '-')}",
            f"Location: {state.get('customer_location', '-')}",
        ]
        # Append collected application fields if any
        app_details = state.get("application_details") or {}
        if app_details.get("full_name"):
            context_lines.append(f"Name:     {app_details['full_name']}")
        if app_details.get("whatsapp_number"):
            context_lines.append(f"Phone:    {app_details['whatsapp_number']}")
        if app_details.get("ic_number"):
            context_lines.append(f"IC:       {app_details['ic_number']}")

        private_note = "🤖 Bot escalated to human agent.\n\n" + "\n".join(context_lines)
        base = self._base(conversation_id)
        headers = self._auth_headers

        client = _get_http()
        json_headers = {**headers, "Content-Type": "application/json"}

        async def add_label() -> httpx.Response:
            # POST /labels replaces all of the chat's labels, so send the current ones too.
            labels: list[str] = []
            try:
                current = await client.get(f"{base}/labels", headers=headers)
                current.raise_for_status()
                labels = list(current.json().get("payload") or [])
            except Exception:
                logger.warning(
                    "Could not read the labels of conv=%s; setting %s only.", conversation_id, label
                )
            if label not in labels:
                labels.append(label)
            return await client.post(f"{base}/labels", headers=json_headers, json={"labels": labels})

        try:
            # Step 1 — open conversation (disables bot gate)
            (await client.post(
                f"{base}/toggle_status",
                headers=headers,
                json={"status": "open"},
            )).raise_for_status()

            # Step 2 — label + private note + assignment in parallel
            steps = {
                "label": add_label(),
                "note": client.post(
                    f"{base}/messages",
                    headers=json_headers,
                    json={"content": private_note, "message_type": "outgoing", "private": True},
                ),
            }
            if settings.chatwoot_human_agent_id:
                steps["assignment"] = client.post(
                    f"{base}/assignments",
                    headers=json_headers,
                    json={"assignee_id": int(settings.chatwoot_human_agent_id)},
                )
            elif settings.chatwoot_human_team_id:
                steps["assignment"] = client.post(
                    f"{base}/assignments",
                    headers=json_headers,
                    json={"team_id": int(settings.chatwoot_human_team_id)},
                )

            results = await asyncio.gather(*steps.values(), return_exceptions=True)
        except Exception:
            logger.exception(
                "escalate_conversation failed (conv=%s label=%s)", conversation_id, label
            )
            return False

        for step, result in zip(steps, results):
            if isinstance(result, BaseException) or not result.is_success:
                logger.error(
                    "escalate_conversation: %s failed (conv=%s label=%s): %s",
                    step, conversation_id, label,
                    result if isinstance(result, BaseException) else result.status_code,
                )
        logger.info(
            "escalate_conversation: conv=%s label=%s handed to human.", conversation_id, label
        )
        return True


# Module-level singleton — import and use directly.
chatwoot = ChatwootClient()
