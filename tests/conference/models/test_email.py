from app.conference.models import EmailSendLog


class TestEmailSendLog:
    def test_str(self) -> None:
        log = EmailSendLog(correlation_id="acceptance-letter:abc123")
        assert str(log) == "acceptance-letter:abc123"
