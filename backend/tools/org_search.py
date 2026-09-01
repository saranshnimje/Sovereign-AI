"""
Organization Data Search tool — lets the AI agent search company information.

Searches across organization profiles, employees, departments, contacts,
infrastructure, and financials. Returns structured results the agent can
use to answer user questions about organizations.
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


async def execute(
    validated_input: OrgSearchInput,
    context: dict,
) -> dict:
    """Search organization data from the database."""
    db = context.get("db")
    if db is None:
        return {"results": [], "summary": "No database connection available."}

    from sqlalchemy import select, or_
    from models.data import Organization

    query_text = validated_input.query.lower().strip()
    category = (validated_input.category or "all").lower()

    # Fetch all organizations (agent has read access to all)
    result = await db.execute(select(Organization))
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

        # --- Summary match (org-level fields) ---
        searchable_org = " ".join([
            org.name or "",
            org.description or "",
            org.industry or "",
            org.location or "",
            org.ceo or "",
            org.website or "",
        ]).lower()

        if category in ("all", "summary"):
            if query_text in searchable_org:
                matches.append({"type": "organization", **org_data, "relevance": "org_profile"})
                continue

        # --- Employee search ---
        if category in ("all", "employees"):
            employees = details.get("employees", [])
            for emp in employees:
                emp_searchable = " ".join([
                    emp.get("name", ""),
                    emp.get("role", ""),
                    emp.get("department", ""),
                    emp.get("email", ""),
                ]).lower()
                if query_text in emp_searchable or query_text in searchable_org:
                    matches.append({
                        "type": "employee",
                        "organization": org.name,
                        "org_id": org.id,
                        **emp,
                        "relevance": "employee",
                    })

        # --- Department search ---
        if category in ("all", "departments"):
            departments = details.get("departments", [])
            for dept in departments:
                dept_searchable = " ".join([
                    dept.get("name", ""),
                    dept.get("head", ""),
                    dept.get("description", ""),
                ]).lower()
                if query_text in dept_searchable or query_text in searchable_org:
                    matches.append({
                        "type": "department",
                        "organization": org.name,
                        "org_id": org.id,
                        **dept,
                        "relevance": "department",
                    })

        # --- Contact search ---
        if category in ("all", "contacts"):
            contacts = details.get("contacts", [])
            for contact in contacts:
                contact_searchable = " ".join([
                    contact.get("name", ""),
                    contact.get("role", ""),
                    contact.get("email", ""),
                    contact.get("phone", ""),
                ]).lower()
                if query_text in contact_searchable or query_text in searchable_org:
                    matches.append({
                        "type": "contact",
                        "organization": org.name,
                        "org_id": org.id,
                        **contact,
                        "relevance": "contact",
                    })

        # --- Infrastructure search ---
        if category in ("all", "infrastructure"):
            infra = details.get("infrastructure", [])
            for item in infra:
                infra_searchable = " ".join([
                    item.get("name", ""),
                    item.get("type", ""),
                    item.get("location", ""),
                    item.get("status", ""),
                ]).lower()
                if query_text in infra_searchable or query_text in searchable_org:
                    matches.append({
                        "type": "infrastructure",
                        "organization": org.name,
                        "org_id": org.id,
                        **item,
                        "relevance": "infrastructure",
                    })

        # --- Financials search ---
        if category in ("all", "financials"):
            financials = details.get("financials", {})
            if isinstance(financials, dict) and financials:
                fin_searchable = json.dumps(financials).lower()
                if query_text in fin_searchable or query_text in searchable_org:
                    matches.append({
                        "type": "financials",
                        "organization": org.name,
                        "org_id": org.id,
                        **financials,
                        "relevance": "financials",
                    })

    # Build summary
    if not matches:
        summary = f"No results found for '{validated_input.query}'."
    else:
        org_names = list({m.get("organization", "Unknown") for m in matches})
        types = list({m.get("type", "unknown") for m in matches})
        summary = (
            f"Found {len(matches)} result(s) across {len(org_names)} organization(s): "
            f"{', '.join(org_names)}. "
            f"Categories: {', '.join(types)}."
        )

    return {"results": matches[:50], "summary": summary}
