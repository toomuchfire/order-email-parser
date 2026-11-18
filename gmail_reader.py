"""Read unread order emails from a Gmail test inbox over IMAP.

Needs 2-step verification on the Gmail account and a 16-character app password
(Google Account > Security > App passwords). Put them in .env, never in code.
The reader only fetches mail. It cannot send, and it does not delete anything.
"""

import email
import html
import imaplib
import logging
import re
from email import policy

logger = logging.getLogger(__name__)


class GmailError(Exception):
    """Could not connect, log in, or read the inbox."""


def _html_to_text(markup):
    markup = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", markup)
    text = html.unescape(re.sub(r"<[^>]+>", " ", markup))
    return re.sub(r"[ \t]+", " ", text)


def message_to_text(raw_bytes):
    """Turn a raw email into the plain text the parser reads: key headers, then the body.
    The subject and sender are kept because they often identify the account."""
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)
    headers = f"From: {msg['From']}\nSubject: {msg['Subject']}\nDate: {msg['Date']}\n\n"
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is None:
        return headers
    text = body.get_content()
    if body.get_content_type() == "text/html":
        text = _html_to_text(text)
    return headers + text.strip()


class GmailInbox:
    def __init__(self, address, app_password, folder="INBOX", host="imap.gmail.com"):
        self.address, self.app_password, self.folder, self.host = address, app_password, folder, host
        self.conn = None

    def __enter__(self):
        try:
            self.conn = imaplib.IMAP4_SSL(self.host)
            self.conn.login(self.address, self.app_password)
            status, _ = self.conn.select(self.folder)
            if status != "OK":
                raise GmailError(f"Could not open folder '{self.folder}'")
        except imaplib.IMAP4.error as exc:
            raise GmailError(
                f"Gmail login failed ({exc}). Check 2-step verification is on and that "
                "GMAIL_APP_PASSWORD is an app password, not your normal password."
            ) from exc
        except OSError as exc:
            raise GmailError(f"Could not reach {self.host}: {exc}") from exc
        return self

    def __exit__(self, *exc_info):
        if self.conn is not None:
            try:
                self.conn.logout()
            except (imaplib.IMAP4.error, OSError):
                pass

    def fetch_unread(self, limit=None):
        """Return [(uid, text)] for unread mail. BODY.PEEK leaves the mail marked unread."""
        status, data = self.conn.uid("search", None, "UNSEEN")
        if status != "OK":
            raise GmailError("Search for unread mail failed")
        uids = data[0].split()
        if limit:
            uids = uids[:limit]

        results = []
        for uid in uids:
            status, parts = self.conn.uid("fetch", uid, "(BODY.PEEK[])")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                logger.warning("Could not fetch message %s, skipping", uid.decode())
                continue
            results.append((uid.decode(), message_to_text(parts[0][1])))
        logger.info("Fetched %d unread message(s) from %s", len(results), self.folder)
        return results

    def mark_read(self, uids):
        for uid in uids:
            self.conn.uid("store", uid, "+FLAGS", "\\Seen")
