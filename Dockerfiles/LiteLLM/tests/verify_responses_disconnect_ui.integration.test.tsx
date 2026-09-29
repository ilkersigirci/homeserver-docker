import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { LogDetailContent } from "@/components/view_logs/LogDetailsDrawer/LogDetailContent";
import type { LogEntry } from "@/components/view_logs/columns";

describe("cancelled Responses logs", () => {
  it.each([true, false])(
    "shows partial output when present (%s) alongside the error",
    async (hasOutput) => {
      const user = userEvent.setup();
      const logEntry = {
        request_id: "cancelled-response-check",
        api_key: "test-key",
        team_id: "test-team",
        model: "gpt-4o",
        model_id: "gpt-4o",
        call_type: "aresponses",
        spend: 0,
        total_tokens: 0,
        prompt_tokens: 0,
        completion_tokens: 0,
        startTime: "2026-09-29T00:00:00Z",
        endTime: "2026-09-29T00:00:01Z",
        cache_hit: "miss",
        request_duration_ms: 1000,
        messages: [{ role: "user", content: "Tell me about Ankara" }],
        response: hasOutput
          ? {
              object: "response",
              status: "cancelled",
              usage: null,
              output: [
                {
                  type: "message",
                  role: "assistant",
                  status: "incomplete",
                  content: [
                    {
                      type: "output_text",
                      text: "Partial answer about Ankara",
                      annotations: [],
                    },
                  ],
                },
              ],
            }
          : {},
        metadata: {
          status: "failure",
          error_information: {
            error_code: "499",
            error_message: "Client disconnected the request",
            error_class: "APIError",
          },
        },
        request_tags: {},
        custom_llm_provider: "openai",
        api_base: "https://api.example.com",
      } as LogEntry;

      render(<LogDetailContent logEntry={logEntry} />);

      expect(screen.getByRole("alert")).toHaveTextContent("499");
      expect(
        screen.getByText(
          hasOutput
            ? "Partial answer about Ankara"
            : "No response data available",
        ),
      ).toBeVisible();
      await user.click(screen.getByRole("tab", { name: "JSON" }));
      await user.click(screen.getByRole("tab", { name: "Response" }));
      expect(
        screen.getByRole("tabpanel", { name: "Response", exact: true }),
      ).toHaveTextContent(
        hasOutput
          ? "Partial answer about Ankara"
          : "Client disconnected the request",
      );
    },
  );
});
