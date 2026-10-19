"""Build-time checks for patches/permanent/premium-features.patch.

Each check runs with `premium_user` False, as this image always does, and
exercises one license-gated MIT feature the patch unlocks.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import litellm
from fastapi import HTTPException
from litellm.proxy._types import (
    LiteLLM_AuditLogs,
    LitellmUserRoles,
    Member,
    TeamMemberAddRequest,
    TeamMemberUpdateRequest,
    UserAPIKeyAuth,
)

_ADMIN = UserAPIKeyAuth(user_role=LitellmUserRoles.PROXY_ADMIN, user_id="admin", api_key="sk-admin")


def _message(error: Exception) -> str:
    return str(getattr(error, "message", None) or getattr(error, "detail", None) or error)


def _verify_premium_metadata() -> None:
    """Key/team metadata fields, request-time guardrails and policies, SCIM, and loggers share this check."""
    from litellm.proxy.admin_mcp import _require_enterprise_license
    from litellm.proxy.utils import _premium_user_check, premium_user_check

    for check in (premium_user_check, _premium_user_check):
        check()
        check("tags")

    # The new shared license helper must still gate unreviewed features.
    try:
        _require_enterprise_license()
    except HTTPException as error:
        assert error.status_code == 403
    else:
        raise AssertionError("Hosted admin MCP was unexpectedly unlocked")


def _verify_model_budgets() -> None:
    from litellm.proxy.management_endpoints.common_utils import validate_team_model_max_budget
    from litellm.proxy.management_endpoints.key_management_endpoints import validate_model_max_budget
    from litellm.types.utils import BudgetConfig

    validate_model_max_budget({"gpt-4o": {"budget_limit": 5, "time_period": "30d"}})
    validate_team_model_max_budget(
        {"gpt-4o": BudgetConfig(budget_limit=5, time_period="30d")},
        premium_user=False,
    )


async def _verify_key_regeneration() -> None:
    """Regeneration passes the old license gate and stops at the missing database."""
    from litellm.proxy import proxy_server
    from litellm.proxy.management_endpoints.key_management_endpoints import regenerate_key_fn

    with patch.object(proxy_server, "prisma_client", None):
        try:
            await regenerate_key_fn(key="sk-existing", data=None, user_api_key_dict=_ADMIN, litellm_changed_by=None)
        except Exception as error:
            assert "DB not connected" in _message(error), _message(error)
        else:
            raise AssertionError("regeneration unexpectedly succeeded without a database")


async def _verify_team_admins() -> None:
    from litellm.proxy import proxy_server
    from litellm.proxy.management_endpoints.team_endpoints import team_call_validation_checks, team_member_update

    team_call_validation_checks(
        prisma_client=MagicMock(),
        data=TeamMemberAddRequest(team_id="team-1", member=Member(role="admin", user_id="user-1")),
        premium_user=False,
    )

    # An admin role passes the old license gate and fails later, at the mocked database.
    with patch.object(proxy_server, "prisma_client", MagicMock()):
        try:
            await team_member_update(
                data=TeamMemberUpdateRequest(team_id="team-1", user_id="user-1", role="admin"),
                http_request=MagicMock(),
                user_api_key_dict=_ADMIN,
            )
        except Exception as error:
            assert "premium feature" not in _message(error), _message(error)
        else:
            raise AssertionError("team member update unexpectedly succeeded without a database")


async def _verify_audit_logs() -> None:
    """Audit logs are written once store_audit_logs opts in."""
    from litellm.proxy import proxy_server
    from litellm.proxy.management_helpers import audit_logs

    repository = MagicMock()
    repository.return_value.table.create = AsyncMock()
    entry = LiteLLM_AuditLogs(
        id="audit-1",
        updated_at=litellm.utils.get_utc_datetime(),
        action="updated",
        table_name="LiteLLM_VerificationToken",
        object_id="key-1",
    )
    with (
        patch.object(litellm, "store_audit_logs", True),
        patch.object(proxy_server, "prisma_client", MagicMock()),
        patch.object(audit_logs, "AuditLogRepository", repository),
    ):
        await audit_logs.create_audit_log_for_update(entry)
    repository.return_value.table.create.assert_awaited_once()


async def _verify_region_outage_alert_setting() -> None:
    from litellm.proxy import proxy_server

    config_table = SimpleNamespace(find_first=AsyncMock(return_value=None))
    with (
        patch.object(proxy_server, "prisma_client", MagicMock()),
        patch.object(proxy_server, "_config_param_table", lambda _client: config_table),
    ):
        settings = await proxy_server.alerting_settings(user_api_key_dict=_ADMIN)
    ttl = next(setting for setting in settings if setting.field_name == "region_outage_alert_ttl")
    assert ttl.premium_field is False


async def _verify() -> None:
    _verify_premium_metadata()
    _verify_model_budgets()
    await _verify_key_regeneration()
    await _verify_team_admins()
    await _verify_audit_logs()
    await _verify_region_outage_alert_setting()


def main() -> None:
    from litellm.proxy import proxy_server

    with patch.object(proxy_server, "premium_user", False):
        asyncio.run(_verify())
    print("Premium feature checks passed")


if __name__ == "__main__":
    main()
