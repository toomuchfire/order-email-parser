import pytest

from order_parser import ExtractionError, check_shape, extract_order, parse_json_reply

CATALOG = {"200102": {"name": "Casa Pellarini Chianti Classico Riserva 2022 (750ml/12)", "price": 204, "pack_size": 12}}

GOOD = '{"is_order": true, "account": "Harbor & Vine", "lines": [{"text": "2 Pellarini Riserva", "quantity": 2, "unit": "case", "sku": "200102", "confidence": "high", "alternatives": []}]}'


class ThinkingBlock:
    """Like the SDK's ThinkingBlock: has no .text attribute."""
    thinking = "reasoning..."


class Reply:
    def __init__(self, text, with_thinking=False):
        blocks = [ThinkingBlock()] if with_thinking else []
        self.content = blocks + [type("Block", (), {"text": text})()]


class StubClient:
    """Returns the queued replies in order. Counts calls."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        return Reply(self.replies.pop(0))


def test_parses_clean_json():
    assert extract_order("email", StubClient(GOOD), CATALOG)["account"] == "Harbor & Vine"


def test_strips_markdown_fences():
    assert parse_json_reply(f"```json\n{GOOD}\n```")["is_order"] is True


def test_retries_once_on_bad_json_then_succeeds():
    client = StubClient("Sure! Here is the order:", GOOD)
    assert extract_order("email", client, CATALOG)["lines"][0]["sku"] == "200102"
    assert client.calls == 2


def test_gives_up_after_two_bad_replies():
    client = StubClient("nope", "still nope")
    with pytest.raises(ExtractionError):
        extract_order("email", client, CATALOG)
    assert client.calls == 2


def test_wrong_shape_counts_as_bad_reply():
    client = StubClient('{"customer": "x"}', GOOD)
    assert extract_order("email", client, CATALOG)["is_order"] is True


def test_check_shape_rejects_non_dict_lines():
    with pytest.raises(ValueError):
        check_shape({"is_order": True, "lines": ["200102"]})


def test_skips_thinking_block_before_text():
    class ThinkingClient(StubClient):
        def create(self, **kwargs):
            self.calls += 1
            return Reply(self.replies.pop(0), with_thinking=True)

    assert extract_order("email", ThinkingClient(GOOD), CATALOG)["account"] == "Harbor & Vine"


def test_reply_with_no_text_blocks_is_retried():
    class NoTextClient(StubClient):
        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return type("R", (), {"content": [ThinkingBlock()]})()
            return Reply(self.replies.pop(0))

    client = NoTextClient(GOOD)
    assert extract_order("email", client, CATALOG)["is_order"] is True
    assert client.calls == 2


def test_prompt_lists_wines_but_no_prices():
    from order_parser import build_system_prompt
    prompt = build_system_prompt(CATALOG)
    assert "200102 | Casa Pellarini Chianti Classico Riserva 2022" in prompt
    assert "204" not in prompt
