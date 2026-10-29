"""A scripted stand-in for the OpenAI and Anthropic clients, for the tests and the examples: no key, no network.

    backend = mock.backend(first_reply, second_reply)           # Muse Spark Open's shape: a forced tool call
    backend = mock.backend(reply, mode="json_schema")           # Muse Spark 1.3's shape: JSON in the content
    backend = mock.backend(reply, mode="anthropic")             # Claude's shape: a thinking block, then the JSON text
    writer.write(lines, backend)

Each script item is a reply (a dict, or a raw string for broken JSON), {"_content_only": True, "content": ...,
"finish_reason": ...} for a host that answers in the content instead of the tool call (or runs out of tokens), or an
exception to raise.
"""
import json
from types import SimpleNamespace

from . import writer


class ScriptedClient:
    def __init__(self, *script, mode="tool"):
        self.script, self.mode, self.calls = list(script), mode, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.messages = SimpleNamespace(create=self._create)   # the Anthropic SDK's surface
        self.closed = False

    def close(self):
        self.closed = True

    def _create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        content_only = isinstance(item, dict) and item.get("_content_only")
        finish = item.get("finish_reason", "stop") if content_only else "stop"
        if content_only:
            item = item["content"]
        text = item if isinstance(item, str) else json.dumps(item)
        if self.mode == "anthropic":
            stop = {"stop": "end_turn", "length": "max_tokens"}.get(finish, finish)
            blocks = [SimpleNamespace(type="thinking", thinking="", signature="sig")]
            blocks += [SimpleNamespace(type="text", text=text)] if text else []
            return SimpleNamespace(content=blocks, stop_reason=stop, usage=None)
        if self.mode == "json_schema" or content_only:
            msg = SimpleNamespace(content=text, tool_calls=None)
        else:
            call = SimpleNamespace(id="call_1", type="function",
                                   function=SimpleNamespace(name=writer.TOOL_NAME, arguments=text))
            msg = SimpleNamespace(content=None, tool_calls=[call])
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)], usage=None)


def backend(*script, mode="tool"):
    if mode == "anthropic":
        model = writer.PROVIDERS["anthropic"]["models"][0]
        return writer.AnthropicBackend(name=model, model=model, client=ScriptedClient(*script, mode=mode))
    name = "muse-spark-open" if mode == "tool" else "muse-spark-1.3"
    return writer.Backend(name=name, model=writer.HOSTS[name]["model"], mode=mode,
                          client=ScriptedClient(*script, mode=mode))
