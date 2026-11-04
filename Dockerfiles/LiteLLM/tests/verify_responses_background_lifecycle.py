"""Verify a background Responses stream announces its Response before any output."""

import asyncio
import json
from collections.abc import AsyncIterator

import litellm

RESPONSE = {
    "id": "resp_background",
    "created_at": 1,
    "model": "graph",
    "object": "response",
    "output": [],
    "status": "queued",
    "background": True,
}
ACCEPTED = (
    {"type": "response.created", "sequence_number": 0, "response": RESPONSE},
    {"type": "response.queued", "sequence_number": 1, "response": RESPONSE},
)
DELTA = {
    "type": "response.output_text.delta",
    "sequence_number": 2,
    "item_id": "msg_1",
    "output_index": 0,
    "content_index": 0,
    "delta": "done",
    "logprobs": [],
}
COMPLETED = {
    "type": "response.completed",
    "sequence_number": 3,
    "response": {
        **RESPONSE,
        "status": "completed",
        "usage": {
            "input_tokens": 1,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 1,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 2,
        },
    },
}


def _frame(event: dict[str, object]) -> bytes:
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()


async def _queued_run(
    gate: asyncio.Event,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Serve one Responses stream whose run waits in its queue until the gate opens."""
    head = await reader.readuntil(b"\r\n\r\n")
    length = next(
        int(line.split(b":", 1)[1])
        for line in head.lower().split(b"\r\n")
        if line.startswith(b"content-length:")
    )
    await reader.readexactly(length)
    writer.write(
        b"HTTP/1.1 200 OK\r\n"
        b"content-type: text/event-stream\r\n"
        b"connection: close\r\n\r\n"
    )
    for event in ACCEPTED:
        writer.write(_frame(event))
    await writer.drain()
    await gate.wait()
    for event in (DELTA, COMPLETED):
        writer.write(_frame(event))
    await writer.drain()
    writer.close()


async def _accept(
    router: litellm.Router,
) -> tuple[list[object], AsyncIterator[object]]:
    stream = await router.aresponses(
        model="graph", input="Report", background=True, stream=True
    )
    events = aiter(stream)
    return [await anext(events) for _ in ACCEPTED], events


async def main() -> None:
    gate = asyncio.Event()
    server = await asyncio.start_server(
        lambda reader, writer: _queued_run(gate, reader, writer), "127.0.0.1", 0
    )
    port = server.sockets[0].getsockname()[1]
    router = litellm.Router(
        model_list=[
            {
                "model_name": "graph",
                "litellm_params": {
                    "model": "openai/graph",
                    "api_base": f"http://127.0.0.1:{port}/v1",
                    "api_key": "key",
                },
                "model_info": {"supports_native_streaming": True},
            }
        ]
    )
    async with server:
        try:
            # The client needs the Response ID to cancel the run while it waits,
            # and a fallback cannot replace a run that keeps going.
            accepted, events = await asyncio.wait_for(_accept(router), timeout=5)
        finally:
            gate.set()
        rest = [event async for event in events]

    assert [event.type for event in accepted] == [e["type"] for e in ACCEPTED]
    assert [event.type for event in rest] == [DELTA["type"], COMPLETED["type"]]
    print("Responses background lifecycle check passed")


if __name__ == "__main__":
    asyncio.run(main())
