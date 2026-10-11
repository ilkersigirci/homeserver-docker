import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MODEL_MAX_BUDGET_PREMIUM_HINT } from "@/components/key_team_helpers/ModelMaxBudgetEditor";
import { fetchAvailableModelsForTeamOrKey } from "@/components/key_team_helpers/fetch_available_models_team_key";
import { fetchMCPAccessGroups, teamCreateCall } from "@/components/networking";
import Teams from "@/components/Teams";
import { renderWithProviders } from "./test-utils";

// Teams renders with premiumUser false, the value the proxy's session token
// carries in this image, and must offer the controls premium-ui.patch unlocks.
// The mocks follow the dashboard's own Teams.test.tsx.

const mocks = vi.hoisted(() => ({
  teamInfo: vi.fn(),
  tableProps: {
    current: null as null | { onSelectTeam: (team: object) => void },
  },
}));

vi.mock("@/components/mcp_server_management/MCPServerSelector", () => ({
  default: () => <div />,
}));
vi.mock("@/components/skills/SkillSelector", () => ({
  default: () => <div />,
}));
vi.mock("@/app/(dashboard)/hooks/useCan", () => ({ default: () => true }));
vi.mock("@/components/TeamsPage/TeamsTable", () => ({
  TeamsTable: (props: { onSelectTeam: (team: object) => void }) => {
    mocks.tableProps.current = props;
    return <div />;
  },
}));
vi.mock("@/components/networking", () => ({
  teamCreateCall: vi.fn(),
  teamDeleteCall: vi.fn(),
  fetchMCPAccessGroups: vi.fn(),
  getGuardrailsList: vi.fn().mockResolvedValue({ guardrails: [] }),
  getPoliciesList: vi.fn().mockResolvedValue({ policies: [] }),
  getDefaultTeamSettings: vi.fn().mockResolvedValue({ values: {} }),
}));
vi.mock("@/app/(dashboard)/hooks/teams/useTeams", () => ({
  teamsTableKeys: { all: ["teamsTable"] },
}));
vi.mock("@/app/(dashboard)/hooks/teams/useTeamMetadataSchema", () => ({
  useTeamMetadataSchema: () => ({ data: [], isLoading: false }),
}));
vi.mock(
  "@/components/key_team_helpers/fetch_available_models_team_key",
  () => ({
    fetchAvailableModelsForTeamOrKey: vi.fn(),
    getModelDisplayName: (model: string) => model,
    unfurlWildcardModelsInList: (teamModels: string[]) => teamModels,
  }),
);
vi.mock("@/components/team/TeamInfo", () => ({
  __esModule: true,
  default: (props: { premiumUser?: boolean }) => {
    mocks.teamInfo(props);
    return <div />;
  },
}));
vi.mock("@/components/ModelSelect/ModelSelect", () => {
  const ModelSelect = React.forwardRef<HTMLInputElement, { id?: string }>(
    ({ id }, ref) => <input ref={ref} id={id} type="text" />,
  );
  ModelSelect.displayName = "ModelSelect";
  return { ModelSelect };
});
vi.mock("@/app/(dashboard)/hooks/organizations/useOrganizations", () => ({
  useOrganizations: () => ({ data: null }),
}));
vi.mock("@/app/(dashboard)/hooks/accessGroups/useAccessGroups", () => ({
  useAccessGroups: () => ({ data: [], isLoading: false, isError: false }),
}));
vi.mock("@/components/common_components/AccessGroupSelector", () => ({
  default: () => <div />,
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.tableProps.current = null;
  vi.mocked(fetchAvailableModelsForTeamOrKey).mockResolvedValue(["gpt-4"]);
  vi.mocked(fetchMCPAccessGroups).mockResolvedValue([]);
  vi.mocked(teamCreateCall).mockResolvedValue({ team_id: "new-team" });
});

const renderTeams = () =>
  renderWithProviders(
    <Teams
      accessToken="token"
      userID="user-1"
      userRole="Admin"
      premiumUser={false}
    />,
  );

const openCreateModal = async () => {
  renderTeams();
  act(() => {
    fireEvent.click(screen.getAllByRole("button", { name: /create team/i })[0]);
  });
  await waitFor(() =>
    expect(screen.getByLabelText(/team name/i)).toBeInTheDocument(),
  );
  fireEvent.change(screen.getByLabelText(/team name/i), {
    target: { value: "Unlocked Team" },
  });
};

describe("Teams without a license", () => {
  it("opens team details with the unlocked controls", async () => {
    renderTeams();

    await waitFor(() => expect(mocks.tableProps.current).not.toBeNull());
    act(() =>
      mocks.tableProps.current?.onSelectTeam({
        team_id: "team-1",
        team_alias: "Team",
        models: [],
      }),
    );

    await waitFor(() => expect(mocks.teamInfo).toHaveBeenCalled());
    expect(mocks.teamInfo).toHaveBeenLastCalledWith(
      expect.objectContaining({ premiumUser: true }),
    );
  });

  it("lets a new team get per-model budgets", async () => {
    await openCreateModal();

    expect(
      screen.getByRole("button", { name: /Add Model Budget/i }),
    ).toBeEnabled();
    expect(
      screen.queryByText(MODEL_MAX_BUDGET_PREMIUM_HINT),
    ).not.toBeInTheDocument();
  });

  it("sends the disable-global-guardrails switch for a new team", async () => {
    await openCreateModal();
    fireEvent.click(screen.getByText("Additional Settings"));
    await waitFor(() =>
      expect(
        screen.getAllByText(/Team Member Key Duration/).length,
      ).toBeGreaterThan(0),
    );

    const switches = screen.getAllByRole("switch");
    fireEvent.click(switches[switches.length - 1]);
    const buttons = screen.getAllByRole("button", { name: /create team/i });
    fireEvent.click(buttons[buttons.length - 1]);

    await waitFor(() => expect(teamCreateCall).toHaveBeenCalled());
    expect(vi.mocked(teamCreateCall).mock.calls[0][1]).toMatchObject({
      disable_global_guardrails: true,
    });
  });
});
