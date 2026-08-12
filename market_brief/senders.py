"""Delivery — where a finished brief goes.

The pipeline does not care how a brief is delivered, so delivery is one small
interface with two implementations: print it (the default, and what the CLI
uses) or POST it to a WhatsApp HTTP API gateway.

A sender is anything with::

    async def send(self, text: str, label: str = "") -> bool

`label` is a short human tag for logs ("market brief"). The return value is
whether delivery succeeded — a sender must never raise into the pipeline, or a
dead transport takes the whole job down with it.
"""

import logging
import sys

logger = logging.getLogger(__name__)


class ConsoleSender:
    """Prints the brief to stdout. The default, and what ``--once`` uses.

    Deliberately the default everywhere: a misconfigured deployment that
    prints to a terminal is harmless, one that posts to the wrong chat is not.

    Writes through the raw stdout buffer as UTF-8 rather than using ``print``.
    The brief carries emoji and Arabic by design, and a Windows console
    defaults to cp1252 — a plain ``print`` raises UnicodeEncodeError there and
    the whole brief is lost to a character. Encoding is forced here, once,
    instead of asking every user to set PYTHONIOENCODING.
    """

    name = "console"

    async def send(self, text: str, label: str = "") -> bool:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is None:  # a wrapped/captured stdout (pytest, a pipe helper)
            print(text)
            return True
        buffer.write(text.encode("utf-8", "replace") + b"\n")
        buffer.flush()
        return True


class WhatsAppSender:
    """STUB — POSTs a brief to a WhatsApp HTTP API gateway. Not implemented.

    This is intentionally left as a documented contract rather than a working
    client: the gateway is deployment-specific, and shipping a half-configured
    one invites sending a brief to the wrong number.

    The contract, as implemented against a WAHA-compatible gateway
    (https://waha.devlike.pro — any gateway exposing the same shape works):

        POST {base_url}/api/sendText
        Headers:  X-Api-Key: {api_key}      # gateway-wide key, if the
                                            # deployment sets one
                  Content-Type: application/json
        Body:     {"session": "default",
                   "chatId":  "<id>@c.us",  # or "<id>@g.us" for a group
                   "text":    "<the brief>"}
        Success:  HTTP 2xx. The response body carries the message id; the
                  pipeline does not read it.

    Notes for whoever implements it:
      * The gateway holds the WhatsApp session, not this app. Pairing,
        re-pairing, and QR handling all live there.
      * Secrets belong in the environment, never in config.yaml. Read the key
        from an env var and let config.yaml carry only the base URL, session
        name, and chat id.
      * Formatting is WhatsApp's, not Markdown: ``*bold*``, ``_italic_``,
        ``- `` bullets, no headers. The compose prompt already targets this.
      * Keep `send` total. Log the failure, return False, and let the caller
        decide — a delivery outage must not lose the brief.
    """

    name = "whatsapp"

    def __init__(self, base_url: str = "", session: str = "default",
                 chat_id: str = "", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.chat_id = chat_id
        self._api_key = api_key

    async def send(self, text: str, label: str = "") -> bool:
        raise NotImplementedError(
            "WhatsAppSender is a documented stub — implement the POST described "
            "in its docstring, or use ConsoleSender."
        )


def get_sender(backend: str = "console", **options):
    """Build the configured sender. Unknown backend → console, with a warning.

    Falling back to console rather than raising is deliberate: a typo in
    config.yaml should cost you a printed brief, not the run.
    """
    key = (backend or "console").strip().lower()
    if key in ("console", "stdout", ""):
        return ConsoleSender()
    if key in ("whatsapp", "wa"):
        return WhatsAppSender(
            base_url=str(options.get("base_url", "")),
            session=str(options.get("session", "default")),
            chat_id=str(options.get("chat_id", "")),
            api_key=str(options.get("api_key", "")),
        )
    logger.warning("Unknown delivery backend %r — using console", backend)
    return ConsoleSender()
