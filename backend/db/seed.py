"""Seed the relational database from the JSON knowledge base.

The JSON datasets remain the source of truth. This mirrors them into tables so
the data is queryable (and so a PostgreSQL deployment has the same reference
data), then materialises every curated company x role x level requirement.

Idempotent: running it twice updates rows instead of duplicating them.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Company, CompanyRequirement, JobRole, Skill
from services.knowledge_base import get_knowledge_base


def seed_reference_data(session: Session) -> dict[str, int]:
    kb = get_knowledge_base()
    counts = {"companies": 0, "roles": 0, "skills": 0, "requirements": 0}

    # -- skills ------------------------------------------------------------
    existing_skills = {s.name: s for s in session.scalars(select(Skill)).all()}
    for definition in kb.skills.values():
        row = existing_skills.get(definition.name)
        if row is None:
            row = Skill(name=definition.name)
            session.add(row)
        row.category = definition.category
        row.aliases = definition.aliases
        row.related = definition.related
        row.learn_weeks = definition.learn_weeks
        row.emerging = definition.emerging
        counts["skills"] += 1

    # -- companies ---------------------------------------------------------
    existing_companies = {c.slug: c for c in session.scalars(select(Company)).all()}
    for slug, profile in kb.companies.items():
        row = existing_companies.get(slug)
        if row is None:
            row = Company(slug=slug)
            session.add(row)
            existing_companies[slug] = row
        row.name = profile["name"]
        row.tagline = profile.get("tagline", "")
        row.values = profile.get("values", [])
        row.keywords = profile.get("keywords", [])
        row.profile = profile
        counts["companies"] += 1

    # -- roles -------------------------------------------------------------
    existing_roles = {r.slug: r for r in session.scalars(select(JobRole)).all()}
    for slug, profile in kb.roles.items():
        row = existing_roles.get(slug)
        if row is None:
            row = JobRole(slug=slug)
            session.add(row)
            existing_roles[slug] = row
        row.title = profile["title"]
        row.family = profile.get("family", "")
        row.summary = profile.get("summary", "")
        row.profile = profile
        counts["roles"] += 1

    session.flush()

    # -- curated requirement profiles --------------------------------------
    existing_requirements = {
        (r.company_id, r.role_id, r.level): r
        for r in session.scalars(select(CompanyRequirement)).all()
    }
    for (company_slug, role_slug) in kb.overrides.keys():
        company = existing_companies.get(company_slug)
        role = existing_roles.get(role_slug)
        if not company or not role:
            continue
        for level in kb.levels:
            requirement = kb.build_requirement(company_slug, role_slug, level)
            key = (company.id, role.id, level)
            row = existing_requirements.get(key)
            if row is None:
                row = CompanyRequirement(company_id=company.id, role_id=role.id, level=level)
                session.add(row)
                existing_requirements[key] = row
            row.curated = requirement.curated
            row.required_skills = [s.to_dict() for s in requirement.by_tier("required")]
            row.preferred_skills = [s.to_dict() for s in requirement.by_tier("preferred")]
            row.optional_skills = [s.to_dict() for s in requirement.by_tier("optional")]
            row.keywords = requirement.keywords
            row.responsibilities = requirement.responsibilities
            counts["requirements"] += 1

    session.commit()
    return counts


def ensure_requirement_row(
    session: Session, company_slug: str, role_slug: str, level: str
) -> CompanyRequirement | None:
    """Fetch (or materialise) the requirement row for an arbitrary target."""
    kb = get_knowledge_base()
    company = session.scalar(select(Company).where(Company.slug == company_slug))
    role = session.scalar(select(JobRole).where(JobRole.slug == role_slug))
    if company is None or role is None:
        return None

    row = session.scalar(
        select(CompanyRequirement).where(
            CompanyRequirement.company_id == company.id,
            CompanyRequirement.role_id == role.id,
            CompanyRequirement.level == level,
        )
    )
    if row is not None:
        return row

    try:
        requirement = kb.build_requirement(company_slug, role_slug, level)
    except KeyError:
        return None

    row = CompanyRequirement(
        company_id=company.id,
        role_id=role.id,
        level=level,
        curated=requirement.curated,
        required_skills=[s.to_dict() for s in requirement.by_tier("required")],
        preferred_skills=[s.to_dict() for s in requirement.by_tier("preferred")],
        optional_skills=[s.to_dict() for s in requirement.by_tier("optional")],
        keywords=requirement.keywords,
        responsibilities=requirement.responsibilities,
    )
    session.add(row)
    session.commit()
    return row


if __name__ == "__main__":  # pragma: no cover - manual seeding entry point
    from db.database import SessionLocal, engine
    from db.database import Base

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as s:
        result = seed_reference_data(s)
    print("Seeded:", result)
