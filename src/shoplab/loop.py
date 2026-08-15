"""The agent loop: model call -> tool calls -> tool results, until done.

Chapter 02 builds ``run_agent``, the plain while-loop agent that the rest of
the course instruments, evaluates, and defends. Its canonical body lives
between sentinels, byte-identical to the notebook. Stop reasons: ``finish``
(the model called the finish tool), ``text`` (it answered in prose), or
``max_steps`` (it ran out of turns).
"""

import json
from dataclasses import dataclass

import shoplab.llm
from shoplab.tools import run_tool, to_openai_tools


@dataclass
class AgentResult:
    """What a run produced: ``answer`` is the finish-tool args dict, a plain
    text string, or None when the loop hit ``max_steps``."""
    answer: dict | str | None
    steps: int
    messages: list
    stop_reason: str  # "finish" | "text" | "max_steps"


# >>> shoplab.loop.run_agent
def run_agent(task, tools, *, model=None, system=None, max_steps=8,
              on_step=None, before_tool=None, max_result_chars=2000):
    """Run the tool-calling loop: one model call per step, execute every tool
    call it makes, stop on the finish tool, a plain-text answer, or max_steps."""
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": task})
    for step in range(1, max_steps + 1):
        r = shoplab.llm.complete(messages, model=model, tools=to_openai_tools(tools))
        msg = r.choices[0].message
        # real litellm messages become plain dicts; test fakes pass through as-is
        messages.append(msg.model_dump(exclude_none=True)
                        if hasattr(msg, "model_dump") else msg)
        if on_step:
            on_step(step, msg)
        if msg.tool_calls:
            for tc in msg.tool_calls:
                name, ok = tc.function.name, True
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except ValueError:
                    ok, args = False, {}
                    result = json.dumps({"error": "tool arguments were not valid JSON"})
                else:
                    if before_tool is not None and before_tool(name, args) is False:
                        ok, result = False, '{"error": "blocked by policy"}'
                    else:
                        result = run_tool(tools, name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": result[:max_result_chars]})
                if ok and name == "finish":
                    return AgentResult(answer=args, steps=step,
                                       messages=messages, stop_reason="finish")
        elif msg.content:
            return AgentResult(answer=msg.content, steps=step,
                               messages=messages, stop_reason="text")
    return AgentResult(answer=None, steps=max_steps, messages=messages,
                       stop_reason="max_steps")
# <<< shoplab.loop.run_agent
