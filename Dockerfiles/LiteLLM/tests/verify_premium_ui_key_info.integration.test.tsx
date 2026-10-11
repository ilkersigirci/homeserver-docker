import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import useAuthorized from "@/app/(dashboard)/hooks/useAuthorized";
import useTeams from "@/app/(dashboard)/hooks/useTeams";
import type { KeyResponse } from "@/components/key_team_helpers/key_list";
import KeyInfoView from "@/components/templates/key_info_view";
import { renderWithProviders } from "./test-utils";

// The key page renders with premiumUser false, the value the proxy's session
// token carries in this image, and must offer the controls premium-ui.patch
// unlocks. The mocks follow the dashboard's own key_info_view.test.tsx.

const editView = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/app/(dashboard)/hooks/organizations/useOrganizations", () => ({
  useOrganizations: () => ({ data: [] }),
}));
vi.mock("@/components/templates/key_edit_view", () => ({
  KeyEditView: (props: { premiumUser?: boolean }) => {
    editView(props);
    return <div />;
  },
}));
vi.mock("@/components/templates/KeyAutoRouterUsageTab", () => ({
  default: () => <div />,
}));
vi.mock("@/components/templates/KeySavingsTab", () => ({
  default: () => <div />,
}));
vi.mock("@/app/(dashboard)/hooks/useTeams", () => ({ default: vi.fn() }));
vi.mock("@/app/(dashboard)/hooks/useAuthorized", () => ({ default: vi.fn() }));
vi.mock("@/app/(dashboard)/hooks/projects/useProjects", () => ({
  useProjects: () => ({ data: [], isLoading: false }),
}));
vi.mock("@/app/(dashboard)/hooks/mcpServers/useMCPServers", () => ({
  useMCPServers: () => ({ data: [] }),
}));
vi.mock("@/app/(dashboard)/hooks/mcpServers/useMCPToolsets", () => ({
  useMCPToolsets: () => ({ data: [] }),
}));
vi.mock("@/components/networking", () => ({
  serverRootPath: "",
  keyDeleteCall: vi.fn().mockResolvedValue({}),
  keyUpdateCall: vi.fn().mockResolvedValue({}),
  getPolicyInfoWithGuardrails: vi
    .fn()
    .mockResolvedValue({ resolved_guardrails: [] }),
}));
vi.mock("@/app/(dashboard)/hooks/keys/useResetKeySpend", () => ({
  useResetKeySpend: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/utils/dataUtils", () => ({
  copyToClipboard: vi.fn().mockResolvedValue(true),
  formatNumberWithCommas: (value: number, decimals?: number) =>
    value.toFixed(decimals ?? 2),
}));

const KEY = {
  token: "test-token-123",
  token_id: "test-token-123",
  key_name: "sk-...TUuw",
  key_alias: "laptop",
  spend: 0,
  total_spend: 0,
  max_budget: 0,
  expires: "null",
  models: [],
  aliases: {},
  config: {},
  user_id: "owner",
  team_id: null,
  project_id: null,
  max_parallel_requests: 10,
  metadata: { logging: [], tags: [] },
  tpm_limit: 10,
  rpm_limit: 10,
  duration: "30d",
  budget_duration: "30d",
  budget_reset_at: "never",
  allowed_cache_controls: [],
  allowed_routes: [],
  permissions: {},
  model_spend: {},
  model_max_budget: {},
  soft_budget_cooldown: false,
  blocked: false,
  litellm_budget_table: {},
  organization_id: null,
  created_at: "2025-10-29T01:26:41.613000Z",
  updated_at: "2025-10-29T01:47:33.980000Z",
  team_spend: 0,
  team_alias: "",
  team_tpm_limit: 0,
  team_rpm_limit: 0,
  team_max_budget: 0,
  team_models: [],
  team_blocked: false,
  soft_budget: 0,
  team_model_aliases: {},
  team_member_spend: 0,
  team_metadata: {},
  end_user_id: "owner",
  end_user_tpm_limit: 10,
  end_user_rpm_limit: 10,
  end_user_max_budget: 0,
  last_refreshed_at: Date.now(),
  api_key: "sk-...TUuw",
  user_role: "user",
  rpm_limit_per_model: {},
  tpm_limit_per_model: {},
  user_tpm_limit: 10,
  user_rpm_limit: 10,
  user_email: "owner@example.com",
  object_permission: {
    object_permission_id: "perm-1",
    mcp_servers: [],
    mcp_access_groups: [],
    mcp_tool_permissions: {},
    vector_stores: [],
  },
  auto_rotate: false,
} as unknown as KeyResponse;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useTeams).mockReturnValue({ teams: [], setTeams: vi.fn() });
  vi.mocked(useAuthorized).mockReturnValue({
    accessToken: "token",
    userId: "admin",
    userRole: "proxy_admin",
    premiumUser: false,
    token: "token",
    userEmail: null,
    disabledPersonalKeyCreation: null,
    showSSOBanner: false,
  } as unknown as ReturnType<typeof useAuthorized>);
});

const renderKey = () =>
  renderWithProviders(
    <KeyInfoView
      keyData={KEY}
      onClose={() => {}}
      keyId="key-1"
      onKeyDataUpdate={() => {}}
      teams={[]}
    />,
  );

describe("key page without a license", () => {
  it("lets the key be regenerated", async () => {
    renderKey();

    expect(
      await screen.findByRole("button", { name: /Regenerate Key/ }),
    ).toBeEnabled();
  });

  it("opens the edit form with the unlocked fields", async () => {
    const user = userEvent.setup();
    renderKey();

    await user.click(await screen.findByRole("tab", { name: /settings/i }));
    await user.click(screen.getByRole("button", { name: /edit settings/i }));

    await waitFor(() => expect(editView).toHaveBeenCalled());
    expect(editView).toHaveBeenLastCalledWith(
      expect.objectContaining({ premiumUser: true }),
    );
  });
});
