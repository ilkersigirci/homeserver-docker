#!/usr/bin/env python3
"""Export annotations from hypothes.is and import them into another h instance."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


LIMIT_MAX = 200
EXPORT_SORT = "id"
EXPORT_ORDER = "asc"


class ApiError(RuntimeError):
    """Raised when a Hypothesis API request fails."""


def normalize_api_url(url: str) -> str:
    url = url.rstrip("/")
    if not url.endswith("/api"):
        url = f"{url}/api"
    return url


def normalize_app_url(url: str) -> str:
    url = url.rstrip("/")
    if url.endswith("/api"):
        url = url[:-4]
    return url


def api_request(
    method: str,
    api_url: str,
    path: str,
    *,
    token: str | None = None,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    url = f"{api_url}{path}"
    if params:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{query}"

    data = None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ApiError(f"{method} {url} failed with HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"{method} {url} failed: {exc.reason}") from exc

    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ApiError(f"{method} {url} returned non-JSON data") from exc


def get_userid(api_url: str, token: str) -> str:
    profile = api_request("GET", api_url, "/profile", token=token)
    userid = profile.get("userid")
    if not userid:
        raise ApiError("Could not determine userid from /api/profile")
    return userid


def export_annotations(args: argparse.Namespace) -> int:
    source_api = normalize_api_url(args.source_url)
    source_user = args.source_user or get_userid(source_api, args.source_token)

    annotations: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    search_after = None

    while True:
        params: dict[str, Any] = {
            "limit": LIMIT_MAX,
            "sort": EXPORT_SORT,
            "order": EXPORT_ORDER,
            "user": source_user,
        }
        if search_after:
            params["search_after"] = search_after

        result = api_request(
            "GET", source_api, "/search", token=args.source_token, params=params
        )
        rows = result.get("rows", [])
        if not isinstance(rows, list):
            raise ApiError("/api/search returned an unexpected response")
        if not rows:
            break

        for row in rows:
            row_id = row.get("id")
            if row_id and row_id not in seen_ids:
                annotations.append(row)
                seen_ids.add(row_id)

        next_search_after = rows[-1].get(EXPORT_SORT)
        if len(rows) < LIMIT_MAX or not next_search_after:
            break
        if next_search_after == search_after:
            raise ApiError("Pagination stopped making progress")
        search_after = next_search_after

    export_doc = {
        "source_api": source_api,
        "source_user": source_user,
        "exported_at": datetime.now(UTC).isoformat(),
        "count": len(annotations),
        "annotations": annotations,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(export_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Exported {len(annotations)} annotations for {source_user} to {output}")
    return 0


def is_shared(annotation: dict[str, Any]) -> bool:
    group = annotation.get("group", "__world__")
    permissions = annotation.get("permissions") or {}
    return permissions.get("read") == [f"group:{group}"]


def parse_group_map(group_map_args: list[str]) -> dict[str, str]:
    mapping = {}
    for item in group_map_args:
        if "=" not in item:
            raise ValueError(f"Invalid --group-map value: {item}")
        old_group, new_group = item.split("=", 1)
        if not old_group or not new_group:
            raise ValueError(f"Invalid --group-map value: {item}")
        mapping[old_group] = new_group
    return mapping


def public_permissions(group: str) -> dict[str, list[str]]:
    return {"read": [f"group:{group}"]}


def sanitize_annotation(
    annotation: dict[str, Any],
    *,
    id_map: dict[str, str],
    group_map: dict[str, str],
    unknown_group_policy: str,
) -> dict[str, Any] | None:
    old_group = annotation.get("group", "__world__")
    shared = is_shared(annotation)

    payload = {
        key: copy.deepcopy(annotation[key])
        for key in ("uri", "text", "tags", "target", "document", "metadata")
        if key in annotation
    }

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata = copy.deepcopy(metadata)
    metadata["migrated_from_hypothesis"] = {
        "id": annotation.get("id"),
        "user": annotation.get("user"),
        "created": annotation.get("created"),
        "updated": annotation.get("updated"),
    }
    payload["metadata"] = metadata

    references = annotation.get("references") or []
    if references:
        payload["references"] = [id_map[reference] for reference in references]

    if not shared:
        payload["group"] = "__world__"
        return payload

    if old_group == "__world__":
        payload["group"] = "__world__"
        payload["permissions"] = public_permissions("__world__")
        return payload

    if old_group in group_map:
        new_group = group_map[old_group]
        payload["group"] = new_group
        payload["permissions"] = public_permissions(new_group)
        return payload

    if unknown_group_policy == "private":
        payload["group"] = "__world__"
        return payload
    if unknown_group_policy == "world":
        payload["group"] = "__world__"
        payload["permissions"] = public_permissions("__world__")
        return payload
    if unknown_group_policy == "keep":
        payload["group"] = old_group
        payload["permissions"] = public_permissions(old_group)
        return payload
    if unknown_group_policy == "skip":
        return None

    raise ValueError(f"Unhandled unknown group policy: {unknown_group_policy}")


def import_annotations(args: argparse.Namespace) -> int:
    dest_api = normalize_api_url(args.dest_url)
    dest_app_url = normalize_app_url(args.dest_url)
    group_map = parse_group_map(args.group_map)
    export_doc = json.loads(Path(args.input).read_text(encoding="utf-8"))
    annotations = export_doc.get("annotations")
    if not isinstance(annotations, list):
        raise ValueError("Input file does not contain an annotations list")

    pending = {
        annotation["id"]: annotation
        for annotation in annotations
        if isinstance(annotation, dict) and annotation.get("id")
    }
    id_map: dict[str, str] = {}
    skipped = 0
    imported = 0

    if args.limit:
        pending = dict(list(pending.items())[: args.limit])

    while pending:
        progressed = False
        for old_id, annotation in list(pending.items()):
            references = annotation.get("references") or []
            if not all(reference in id_map for reference in references):
                continue

            payload = sanitize_annotation(
                annotation,
                id_map=id_map,
                group_map=group_map,
                unknown_group_policy=args.unknown_group_policy,
            )
            if payload is None:
                skipped += 1
                del pending[old_id]
                progressed = True
                continue

            if args.dry_run:
                id_map[old_id] = f"dry-run-{old_id}"
            else:
                created = api_request(
                    "POST",
                    dest_api,
                    "/annotations",
                    token=args.dest_token,
                    payload=payload,
                )
                new_id = created.get("id")
                if not new_id:
                    raise ApiError(f"Import of annotation {old_id} returned no id")
                id_map[old_id] = new_id
                if args.sleep:
                    time.sleep(args.sleep)

            imported += 1
            del pending[old_id]
            progressed = True

        if not progressed:
            unresolved = ", ".join(list(pending.keys())[:10])
            raise ApiError(
                "Could not import remaining annotations because their parents "
                f"were not found in the export/import set: {unresolved}"
            )

    action = "Would import" if args.dry_run else "Imported"
    print(f"{action} {imported} annotations into {dest_api}; skipped {skipped}")

    if getattr(args, "restore_timestamps", False) and not args.dry_run:
        run_container_timestamp_restore(
            app_url=dest_app_url,
            container=args.container,
            container_script_path=args.container_script_path,
            no_reindex=args.no_reindex,
        )

    return 0


def migrate_annotations(args: argparse.Namespace) -> int:
    export_annotations(args)
    import_args = argparse.Namespace(**vars(args))
    import_args.input = args.output
    return import_annotations(import_args)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    normalized = value.replace("Z", "+00:00")
    timestamp = datetime.fromisoformat(normalized)
    if timestamp.tzinfo is None:
        return timestamp

    return timestamp.astimezone(UTC).replace(tzinfo=None)


def restore_timestamps(args: argparse.Namespace) -> int:
    try:
        from h import models
        from h.cli import bootstrap
        from h.search import index
    except ImportError as exc:
        raise RuntimeError(
            "restore-timestamps must run inside the Hypothesis app container "
            "because it uses h's app models and search indexer"
        ) from exc

    app_url = args.app_url or os.environ.get("APP_URL")
    if not app_url:
        raise ValueError("--app-url or APP_URL is required")

    request = bootstrap(normalize_app_url(app_url), False)
    query = (
        request.db.query(
            models.Annotation,
            models.AnnotationSlim,
            models.AnnotationMetadata,
        )
        .join(models.AnnotationSlim, models.AnnotationSlim.pubid == models.Annotation.id)
        .join(
            models.AnnotationMetadata,
            models.AnnotationMetadata.annotation_id == models.AnnotationSlim.id,
        )
        .filter(models.AnnotationMetadata.data.has_key("migrated_from_hypothesis"))
        .order_by(models.Annotation.created.asc())
    )
    if args.limit:
        query = query.limit(args.limit)

    ids = []
    changed = 0
    for annotation, slim, metadata in query:
        migrated = metadata.data.get("migrated_from_hypothesis", {})
        created = parse_timestamp(migrated.get("created"))
        updated = parse_timestamp(migrated.get("updated")) or created
        if created is None or updated is None:
            continue

        ids.append(annotation.id)

        already_restored = (
            annotation.created == created
            and annotation.updated == updated
            and slim.created == created
            and slim.updated == updated
        )
        if already_restored:
            continue

        changed += 1
        if not args.dry_run:
            annotation.created = created
            annotation.updated = updated
            slim.created = created
            slim.updated = updated

    if args.dry_run:
        request.tm.abort()
    else:
        request.tm.commit()

    print(f"matched={len(ids)} changed={changed}")

    if args.dry_run or args.no_reindex:
        return 0

    request.tm.begin()
    indexer = index.BatchIndexer(request.db, request.es, request)
    errors = set(ids)
    for _ in range(2):
        errors = indexer.index(list(errors))
        if not errors:
            break
    request.tm.commit()

    if errors:
        raise RuntimeError(f"Reindex failed for {len(errors)} annotation(s): {errors}")

    print(f"reindexed={len(ids)}")
    return 0


def run_container_timestamp_restore(
    *,
    app_url: str,
    container: str,
    container_script_path: str,
    no_reindex: bool,
) -> None:
    source_script = Path(__file__).resolve()
    target = f"{container}:{container_script_path}"
    subprocess.run(["docker", "cp", str(source_script), target], check=True)

    command = [
        "docker",
        "exec",
        container,
        "python",
        container_script_path,
        "restore-timestamps",
        "--app-url",
        app_url,
    ]
    if no_reindex:
        command.append("--no-reindex")

    subprocess.run(command, check=True)


def add_export_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source-url",
        default="https://hypothes.is",
        help="Source Hypothesis service or API URL",
    )
    parser.add_argument(
        "--source-token",
        default=os.environ.get("HYPOTHESIS_TOKEN"),
        help="Source API token, or HYPOTHESIS_TOKEN",
    )
    parser.add_argument(
        "--source-user",
        help="Source userid, for example acct:alice@hypothes.is. Defaults to /api/profile.",
    )
    parser.add_argument("--output", required=True, help="Export JSON path")


def add_import_args(
    parser: argparse.ArgumentParser, *, include_input: bool = True
) -> None:
    parser.add_argument(
        "--dest-url",
        required=True,
        help="Destination Hypothesis service or API URL",
    )
    parser.add_argument(
        "--dest-token",
        default=os.environ.get("LOCAL_HYPOTHESIS_TOKEN"),
        help="Destination API token, or LOCAL_HYPOTHESIS_TOKEN",
    )
    if include_input:
        parser.add_argument("--input", required=True, help="Export JSON path")
    parser.add_argument(
        "--group-map",
        action="append",
        default=[],
        metavar="OLD=NEW",
        help="Map an official group id to an existing local group id",
    )
    parser.add_argument(
        "--unknown-group-policy",
        choices=("private", "world", "skip", "keep"),
        default="private",
        help="What to do with shared annotations from unmapped non-public groups",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate without POSTing")
    parser.add_argument("--limit", type=int, help="Import only the first N annotations")
    parser.add_argument(
        "--sleep",
        type=float,
        default=0,
        help="Seconds to sleep between create requests",
    )
    parser.add_argument(
        "--restore-timestamps",
        action="store_true",
        help="After importing, restore original timestamps using the local h container",
    )
    parser.add_argument(
        "--container",
        default="hypothesis",
        help="Hypothesis app container used with --restore-timestamps",
    )
    parser.add_argument(
        "--container-script-path",
        default="/tmp/migrate-annotations.py",
        help="Where to copy this script inside the container",
    )
    parser.add_argument(
        "--no-reindex",
        action="store_true",
        help="Restore DB timestamps without reindexing Elasticsearch",
    )


def add_restore_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--app-url",
        default=os.environ.get("APP_URL"),
        help="Destination app URL. Defaults to APP_URL inside the container.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-reindex", action="store_true")
    parser.add_argument("--limit", type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export")
    add_export_args(export_parser)
    export_parser.set_defaults(func=export_annotations)

    import_parser = subparsers.add_parser("import")
    add_import_args(import_parser)
    import_parser.set_defaults(func=import_annotations)

    migrate_parser = subparsers.add_parser("migrate")
    add_export_args(migrate_parser)
    add_import_args(migrate_parser, include_input=False)
    migrate_parser.set_defaults(func=migrate_annotations)

    restore_parser = subparsers.add_parser("restore-timestamps")
    add_restore_args(restore_parser)
    restore_parser.set_defaults(func=restore_timestamps)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in {"export", "migrate"} and not args.source_token:
        parser.error("--source-token or HYPOTHESIS_TOKEN is required")
    if args.command in {"import", "migrate"} and not args.dest_token:
        parser.error("--dest-token or LOCAL_HYPOTHESIS_TOKEN is required")

    try:
        return args.func(args)
    except (ApiError, ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
