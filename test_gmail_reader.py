from email.message import EmailMessage

from gmail_reader import message_to_text


def build(subject="Order - Harbor & Vine", html_only=False):
    msg = EmailMessage()
    msg["From"] = "Dana <dana@harborandvine.example>"
    msg["To"] = "orders@test-inbox.example"
    msg["Subject"] = subject
    msg["Date"] = "Mon, 2 Nov 2026 09:14:00 -0800"
    if html_only:
        msg.set_content("<html><body><p>1 case Valmera Valpolicella<br>2 Chablis</p>"
                        "<div>Dana &amp; team</div></body></html>", subtype="html")
    else:
        msg.set_content("1 case Vireaux Cremant Brut\n1 case Valmera Valpolicella\n\nDana")
    return msg.as_bytes()


def test_plain_email_keeps_headers_and_body():
    text = message_to_text(build())
    assert "Subject: Order - Harbor & Vine" in text
    assert "From: Dana <dana@harborandvine.example>" in text
    assert "1 case Vireaux Cremant Brut" in text


def test_html_only_email_is_flattened_to_lines():
    text = message_to_text(build(html_only=True))
    assert "1 case Valmera Valpolicella\n2 Chablis" in text
    assert "<p>" not in text and "Dana & team" in text


def test_multipart_prefers_the_plain_text_part():
    msg = EmailMessage()
    msg["Subject"] = "x"
    msg.set_content("plain version: 2 Chablis")
    msg.add_alternative("<p>html version: 2 Chablis</p>", subtype="html")
    text = message_to_text(msg.as_bytes())
    assert "plain version" in text and "html version" not in text


def test_email_with_no_body_returns_just_headers():
    msg = EmailMessage()
    msg["Subject"] = "empty"
    assert message_to_text(msg.as_bytes()).startswith("From: None")
