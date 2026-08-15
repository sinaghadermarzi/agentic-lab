"""SimpleNamespace stand-ins shaped like litellm ModelResponse objects.

Just enough structure for shoplab.llm.complete and shoplab.loop.run_agent:
``response.choices[0].message`` (with content / tool_calls), ``response.usage``,
and ``response._hidden_params["response_cost"]``. No network, no litellm.
"""

import json
from types import SimpleNamespace


def make_response(message, *, prompt_tokens=7, completion_tokens=3, cost=0.000008):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens,
                              completion_tokens=completion_tokens),
        _hidden_params={"response_cost": cost},
    )


def make_text_msg(content, **kw):
    """A response whose message is a plain assistant text turn."""
    return make_response(
        SimpleNamespace(role="assistant", content=content, tool_calls=None), **kw)


def make_tool_call_msg(name, args, tool_call_id="call-1", **kw):
    """A response whose message carries one tool call.

    ``args`` is normally a dict (JSON-encoded into function.arguments); pass a
    raw string instead to simulate malformed arguments from the model.
    """
    arguments = args if isinstance(args, str) else json.dumps(args)
    tc = SimpleNamespace(
        id=tool_call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )
    return make_response(
        SimpleNamespace(role="assistant", content=None, tool_calls=[tc]), **kw)
