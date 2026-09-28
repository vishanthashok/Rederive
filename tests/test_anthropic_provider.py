from types import SimpleNamespace

from server.llm import AnthropicProvider, render_prompt


class StubMessages:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.replies.pop(0)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def provider(replies):
    p = AnthropicProvider.__new__(AnthropicProvider)
    p._client = SimpleNamespace(messages=StubMessages(replies))
    return p


def test_recipe_call_uses_sonnet_without_sampling_params():
    p = provider(["User works at Initech."])
    out = p.run_recipe("Extract the employer.\n{inputs}", "default", {}, ["I work at Initech."], [])
    assert out == "User works at Initech."
    call = p._client.messages.calls[0]
    assert call["model"] == "claude-sonnet-5"
    assert "extra_body" not in call and call["output_config"] == {"effort": "low"}
    assert "[1] I work at Initech." in call["messages"][0]["content"]


def test_judge_calls_use_haiku_at_temperature_zero():
    p = provider(['{"differs": false}', '{"reveals": true}', "not json"])
    assert p.claims_equal("a", "b") is True
    assert p.reveals("ends in 0199", "512-555-0199") is True
    # An unparseable answer fails closed: treat the texts as different.
    assert p.claims_equal("a", "b") is False
    for call in p._client.messages.calls:
        assert call["model"] == "claude-haiku-4-5" and call["extra_body"] == {"temperature": 0}


def test_exclusions_are_added_to_prompt():
    prompt = render_prompt("Summarize.\n{inputs}", ["x"], ["512-555-0199"])
    assert "Do not include it, paraphrase it, or hint at it" in prompt
    assert "- 512-555-0199" in prompt
