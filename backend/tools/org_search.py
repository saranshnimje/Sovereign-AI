"""
Organization Data Search tool — lets the AI agent search organization data
that the current user is allowed to see.

Searches organization profiles, employees, departments, contacts,
infrastructure, and financials. Non-admin users are restricted to their own
organizations, matching the Data page visibility model.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class OrgSearchInput(BaseModel):
    query: str = Field(
        ..., description="Search query — organization name, employee name, department, or keyword"
    )
    category: str | None = Field(
        None,
        description="Optional filter: 'all', 'employees', 'departments', 'contacts', 'infrastructure', 'financials', 'summary'",
    )


class OrgSearchOutput(BaseModel):
    results: list[dict[str, Any]]
    summary: str


async def execute(validated_input: OrgSearchInput, context: dict) -> dict:
    """Search organization data visible to the requesting user."""
    db = context.get("db")
    user = context.get("user")
    if db is None:
        return {"results": [], "summary": "No database connection available."}
    if user is None or not getattr(user, "id", None):
        return {"results": [], "summary": "No authenticated user context available."}

    from sqlalchemy import select
    from models.data import Organization

    query_text = validated_input.query.lower().strip()
    category = (validated_input.category or "all").lower()

    # Match the Data page access model: normal users see their own records;
    # admins may inspect organization records across the workspace.
    stmt = select(Organization)
    if getattr(user, "role", "") != "admin":
        stmt = stmt.where(Organization.owner_id == str(user.id))

    result = await db.execute(stmt)
    orgs = list(result.scalars().all())
    matches: list[dict[str, Any]] = []

    for org in orgs:
        org_data: dict[str, Any] = {
            "id": org.id,
            "name": org.name,
            "description": org.description,
            "industry": org.industry,
            "location": org.location,
            "website": org.website,
            "founded": org.founded,
            "employee_count": org.employee_count,
            "revenue": org.revenue,
            "ceo": org.ceo,
            "phone": org.phone,
            "email": org.email,
        }
        details = org.details
        searchable_org = " ".join([
            org.name or "", org.description or "", org.industry or "",
            org.location or "", org.ceo or "", org.website or "",
        ]).lower()

        if category in ("all", "summary") and query_text in searchable_org:
            matches.append({
                "type": "organization", **org_data,
                "relevance": "org_profile", "source": "organization_data",
            })
            # Avoid duplicating the same org in detail categories for an org-level hit.
            continue

        if category in ("all", "employees"):
            for emp in details.get("employees", []):
                searchable = " ".join([
                    emp.get("name", ""), emp.get("role", ""),
                    emp.get("department", ""), emp.get("email", ""),
                ]).lower()
                if query_text in searchable or query_text in searchable_org:
                    matches.append({"type": "employee", "organization": org.name,
                                    "org_id": org.id, **emp,
                                    "relevance": "employee", "source": "organization_data"})

        if category in ("all", "departments"):
            for dept in details.get("departments", []):
                searchable = " ".join([
                    dept.get("name", ""), dept.get("head", ""),
                    dept.get("description", ""),
                ]).lower()
                if query_text in searchable or query_text in searchable_org:
                    matches.append({"type": "department", "organization": org.name,
                                    "org_id": org.id, **dept,
                                    "relevance": "department", "source": "organization_data"})

        if category in ("all", "contacts"):
            for contact in details.get("contacts", []):
                searchable = " ".join([
                    contact.get("name", ""), contact.get("role", ""),
                    contact.get("email", ""), contact.get("phone", ""),
                ]).lower()
                if query_text in searchable or query_text in searchable_org:
                    matches.append({"type": "contact", "organization": org.name,
                                    "org_id": org.id, **contact,
                                    "relevance": "contact", "source": "organization_data"})

        if category in ("all", "infrastructure"):
            for item in details.get("infrastructure", []):
                searchable = " ".join([
                    item.get("name", ""), item.get("type", ""),
                    item.get("location", ""), item.get("status", ""),
                ]).lower()
                if query_text in searchable or query_text in searchable_org:
                    matches.append({"type": "infrastructure", "organization": org.name,
                                    "org_id": org.id, **item,
                                    "relevance": "infrastructure", "source": "organization_data"})

        if category in ("all", "financials"):
            financials = details.get("financials", {})
            if isinstance(financials, dict) and financials:
                searchable = json.dumps(financials).lower()
                if query_text in searchable or query_text in searchable_org:
                    matches.append({"type": "financials", "organization": org.name,
                                    "org_id": org.id, **financials,
                                    "relevance": "financials", "source": "organization_data"})

    if not matches:
        summary = f"No results found for '{validated_input.query}'."
    else:
        org_names = list({m.get("organization", m.get("name", "Unknown")) for m in matches})
        types = list({m.get("type", "unknown") for m in matches})
        summary = (
            f"Found {len(matches)} result(s) across {len(org_names)} visible organization(s): "
            f"{', '.join(org_names)}. Categories: {', '.join(types)}."
        )

    return {"results": matches[:50], "summary": summary}
