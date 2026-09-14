"""Build-time checks for outbound W3C trace-context propagation."""

from typing import Final

import litellm
from opentelemetry.sdk.trace import TracerProvider

from litellm.integrations.otel.logger import OpenTelemetryV2
from litellm.integrations.otel.model.config import OpenTelemetryV2Config
from litellm.integrations.otel.plumbing.context import set_request_root_span


def main() -> None:
    provider: Final = TracerProvider()
    logger: Final = OpenTelemetryV2(
        config=OpenTelemetryV2Config(enable_metrics=False, enable_events=False),
        tracer_provider=provider,
    )
    tracer: Final = provider.get_tracer("homeserver-litellm-build-check")
    original_setting: Final = litellm.forward_traceparent_to_llm_provider

    try:
        with tracer.start_as_current_span("proxy request") as request_span:
            set_request_root_span(request_span)

            original: Final = "00-11111111111111111111111111111111-2222222222222222-01"
            headers: dict[str, str] = {"traceparent": original}
            litellm.forward_traceparent_to_llm_provider = True
            logger.log_pre_api_call(
                model="lgos/test",
                messages=[],
                kwargs={
                    "litellm_call_id": "propagated-call",
                    "call_type": "responses",
                    "model": "lgos/test",
                    "additional_args": {"headers": headers},
                },
            )

            carrier: Final = logger._open_llm_calls.pop("propagated-call")
            assert carrier.span is not None
            expected: Final = (
                f"00-{carrier.span.get_span_context().trace_id:032x}-"
                f"{carrier.span.get_span_context().span_id:016x}-01"
            )
            assert headers["traceparent"] == expected
            assert headers["traceparent"] != original
            carrier.span.end()

            disabled_headers: dict[str, str] = {"traceparent": original}
            litellm.forward_traceparent_to_llm_provider = False
            logger.log_pre_api_call(
                model="lgos/test",
                messages=[],
                kwargs={
                    "litellm_call_id": "disabled-call",
                    "call_type": "responses",
                    "model": "lgos/test",
                    "additional_args": {"headers": disabled_headers},
                },
            )
            disabled_carrier: Final = logger._open_llm_calls.pop("disabled-call")
            assert disabled_carrier.span is not None
            assert disabled_headers["traceparent"] == original
            disabled_carrier.span.end()
    finally:
        litellm.forward_traceparent_to_llm_provider = original_setting
        provider.shutdown()


if __name__ == "__main__":
    main()
