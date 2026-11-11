import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import KeysPanel from "@/components/chat/KeysPanel";
import {
  MODEL_MAX_BUDGET_PREMIUM_HINT,
  ModelMaxBudgetEditor,
  type ModelMaxBudget,
} from "@/components/key_team_helpers/ModelMaxBudgetEditor";
import {
  getCallbackConfigsCall,
  getCallbacksCall,
  keyListCall,
} from "@/components/networking";
import Settings from "@/components/settings";
import { renderWithProviders } from "./test-utils";

// Every check renders with premiumUser false, the value the proxy's session token
// carries in this image, and expects the control premium-ui.patch unlocks.

vi.mock("@/components/networking", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/networking")>()),
  keyListCall: vi.fn(),
  regenerateKeyCall: vi.fn(),
  getCallbacksCall: vi.fn(),
  getCallbackConfigsCall: vi.fn(),
  setCallbacksCall: vi.fn(),
  serviceHealthCheck: vi.fn(),
  deleteCallback: vi.fn(),
  alertingSettingsCall: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/components/alerting/alerting_settings", () => ({
  __esModule: true,
  default: () => <div />,
}));
vi.mock("@/components/email_settings", () => ({
  __esModule: true,
  default: () => <div />,
}));
vi.mock("@/components/CloudZeroCostTracking/CloudZeroCostTracking", () => ({
  __esModule: true,
  default: () => <div />,
}));

beforeAll(() => {
  if (!window.ResizeObserver) {
    window.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe("per-model budgets for users, keys, and teams", () => {
  const renderEditor = (value: ModelMaxBudget) =>
    renderWithProviders(
      <ModelMaxBudgetEditor
        value={value}
        onChange={vi.fn()}
        availableModels={["gpt-4o"]}
        premiumUser={false}
      />,
    );

  it("leaves a stored budget editable", () => {
    renderEditor({ "gpt-4o": { budget_limit: 5, time_period: "30d" } });

    expect(screen.getByPlaceholderText("Max spend ($)")).toBeEnabled();
    expect(
      screen.getByRole("button", { name: /Add Model Budget/i }),
    ).toBeEnabled();
    expect(
      screen.queryByText(MODEL_MAX_BUDGET_PREMIUM_HINT),
    ).not.toBeInTheDocument();
  });

  it("lets a first budget be added", () => {
    renderEditor({});

    expect(
      screen.getByRole("button", { name: /Add Model Budget/i }),
    ).toBeEnabled();
  });
});

describe("chat key rotation", () => {
  it("offers Rotate for each key", async () => {
    vi.mocked(keyListCall).mockResolvedValue({
      keys: [
        {
          token: "hashed",
          key_name: "sk-...abcd",
          key_alias: "laptop",
          spend: 0,
          created_at: null,
        },
      ],
    });
    renderWithProviders(
      <KeysPanel accessToken="token" userId="user-1" premiumUser={false} />,
    );

    expect(await screen.findByRole("button", { name: /Rotate/ })).toBeEnabled();
  });
});

describe("region outage alerts", () => {
  it("shows the alert switch instead of an upgrade link", async () => {
    const user = userEvent.setup();
    vi.mocked(getCallbacksCall).mockResolvedValue({
      callbacks: [],
      available_callbacks: [],
      alerts: [],
    });
    vi.mocked(getCallbackConfigsCall).mockResolvedValue([]);
    render(
      <Settings
        accessToken="token"
        userRole="admin"
        userID="user-1"
        premiumUser={false}
      />,
    );

    await user.click(
      await screen.findByRole("tab", { name: "Alerting Types" }),
    );

    const row = screen.getByText("Region Outage Alerts").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByRole("switch")).toBeEnabled();
    expect(screen.queryByText(/Enterprise Feature/)).not.toBeInTheDocument();
  });
});
