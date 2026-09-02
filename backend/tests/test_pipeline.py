"""End-to-end tests for the analysis pipeline.

Run from the project root:

    pytest backend/tests -q

Covers requirement composition, resume parsing, skill extraction with the
ambiguous-name rules, matching credit, scoring bounds, ATS checks, the honesty
guarantees of the rewrite engine, job-description parsing and the HTTP API.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from ml.nlp_pipeline import find_metrics, get_pipeline  # noqa: E402
from ml.scoring_engine import ComponentScore, ScoringEngine  # noqa: E402
from services.ai_service import _introduces_metric, get_ai_service  # noqa: E402
from services.analysis_service import get_analysis_service  # noqa: E402
from services.ats_analyzer import get_ats_analyzer  # noqa: E402
from services.chat_service import get_chat_service  # noqa: E402
from services.jd_parser import get_jd_parser  # noqa: E402
from services.job_matcher import get_job_matcher  # noqa: E402
from services.knowledge_base import get_knowledge_base  # noqa: E402
from services.resume_parser import ResumeParsingError, extract_text, get_resume_parser  # noqa: E402
from services.section_scorer import get_section_scorer  # noqa: E402
from services.skill_extractor import get_skill_extractor  # noqa: E402

SAMPLES = BACKEND.parent / "samples"


@pytest.fixture(scope="module")
def sample_text() -> str:
    return (SAMPLES / "sample_resume.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def strong_text() -> str:
    return (SAMPLES / "strong_resume.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(sample_text):
    return get_resume_parser().parse_text(sample_text, "sample_resume.txt")


@pytest.fixture(scope="module")
def parsed_strong(strong_text):
    return get_resume_parser().parse_text(strong_text, "strong_resume.txt")


@pytest.fixture(scope="module")
def analysis(parsed):
    return get_analysis_service().analyse_target(
        parsed, "amazon", "machine-learning-engineer", "entry"
    )


# ---------------------------------------------------------------- datasets --


class TestKnowledgeBase:
    def test_datasets_meet_the_documented_minimums(self):
        kb = get_knowledge_base()
        assert len(kb.companies) >= 8
        assert len(kb.roles) >= 10
        assert len(kb.skills) >= 100
        assert len(kb.projects) >= 15
        assert len(kb.levels) == 4

    def test_every_referenced_skill_exists_in_the_ontology(self):
        """Datasets must not reference skills the extractor cannot detect."""
        kb = get_knowledge_base()
        unknown: list[str] = []
        for role in kb.roles.values():
            for tier in ("required_skills", "preferred_skills", "optional_skills"):
                for entry in role.get(tier, []):
                    if not kb.canonical_skill(entry["skill"]):
                        unknown.append(f"{role['id']}:{entry['skill']}")
            for soft in role.get("soft_skills", []):
                if not kb.canonical_skill(soft):
                    unknown.append(f"{role['id']}:{soft}")
        for company in kb.companies.values():
            for focus in company.get("focus_skills", []):
                if not kb.canonical_skill(focus["skill"]):
                    unknown.append(f"{company['id']}:{focus['skill']}")
        for project in kb.projects:
            for skill in project["skills_taught"]:
                if not kb.canonical_skill(skill):
                    unknown.append(f"{project['id']}:{skill}")
        assert not unknown, f"skills missing from skills.json: {unknown}"

    def test_company_profile_changes_the_requirement_set(self):
        kb = get_knowledge_base()
        amazon = kb.build_requirement("amazon", "machine-learning-engineer", "entry")
        nvidia = kb.build_requirement("nvidia", "machine-learning-engineer", "entry")

        assert "AWS" in [s.skill for s in amazon.by_tier("required")]
        assert "CUDA" in [s.skill for s in nvidia.skills[0:] if True] or "CUDA" in nvidia.skill_names()
        assert amazon.skill_names() != nvidia.skill_names()

    def test_curated_override_is_applied(self):
        kb = get_knowledge_base()
        curated = kb.build_requirement("amazon", "machine-learning-engineer", "entry")
        composed = kb.build_requirement("apple", "nlp-engineer", "entry")
        assert curated.curated is True
        assert composed.curated is False
        # Uncurated combinations must still produce a usable profile.
        assert len(composed.by_tier("required")) >= 5

    def test_experience_level_rescales_importance_and_weights(self):
        kb = get_knowledge_base()
        intern = kb.build_requirement("google", "software-engineer", "intern")
        senior = kb.build_requirement("google", "software-engineer", "senior")
        assert intern.weights["experience"] < senior.weights["experience"]
        assert intern.weights["projects"] > senior.weights["projects"]

    def test_unknown_target_raises(self):
        kb = get_knowledge_base()
        with pytest.raises(KeyError):
            kb.build_requirement("not-a-company", "software-engineer", "entry")
        with pytest.raises(KeyError):
            kb.build_requirement("google", "not-a-role", "entry")


# ------------------------------------------------------------------ parser --


class TestResumeParser:
    def test_contact_extraction(self, parsed):
        assert parsed.contact["name"] == "Ananya Sharma"
        assert parsed.contact["email"] == "ananya.sharma@example.com"
        assert "linkedin.com/in/" in parsed.contact["linkedin"]
        assert "github.com/" in parsed.contact["github"]

    def test_sections_are_segmented(self, parsed):
        for section in ("skills", "experience", "projects", "education", "certifications"):
            assert parsed.sections.get(section), f"missing section: {section}"

    def test_experience_entries_with_durations(self, parsed):
        assert len(parsed.experience) == 2
        first = parsed.experience[0]
        assert "Machine Learning Intern" in first.title
        assert first.duration_months == 6
        assert len(first.bullets) >= 3

    def test_education_does_not_bleed_across_lines(self, parsed):
        entry = parsed.education[0]
        assert entry.degree.lower().startswith("b.tech")
        assert "Ramaiah Institute" in entry.institution
        assert "\n" not in entry.institution
        assert entry.year == "2025"

    def test_projects_and_certifications(self, parsed):
        assert len(parsed.projects) >= 2
        assert any("Movie" in p.name for p in parsed.projects)
        assert len(parsed.certifications) >= 1

    def test_pdf_and_docx_round_trip(self):
        """Real binary formats must parse to the same structured content."""
        pytest.importorskip("pymupdf")
        pytest.importorskip("docx")
        pdf, docx_file = SAMPLES / "sample_resume.pdf", SAMPLES / "sample_resume.docx"
        if not pdf.exists() or not docx_file.exists():
            pytest.skip("run `python samples/make_samples.py` to generate binary samples")
        parser = get_resume_parser()
        for path in (pdf, docx_file):
            result = parser.parse(path.read_bytes(), path.name)
            assert result.contact["email"] == "ananya.sharma@example.com"
            assert result.metadata["words"] > 200
            assert len(result.experience) >= 2

    def test_unsupported_and_empty_files_raise_clear_errors(self):
        with pytest.raises(ResumeParsingError) as exc:
            extract_text(b"data", "resume.rtf")
        assert "Unsupported file type" in str(exc.value)

        with pytest.raises(ResumeParsingError):
            extract_text(b"%PDF-1.4 not really a pdf", "broken.pdf")


# --------------------------------------------------------------- extractor --


class TestSkillExtractor:
    def test_finds_declared_and_applied_skills(self, parsed):
        skills = {s.name: s for s in get_skill_extractor().extract(parsed)}
        assert "Python" in skills
        assert skills["Python"].applied, "Python is used in bullets, not merely listed"
        assert "Docker" in skills
        assert skills["Docker"].declared_only, "Docker only appears in the skills list"

    def test_evidence_is_recorded(self, parsed):
        skills = {s.name: s for s in get_skill_extractor().extract(parsed)}
        assert skills["Python"].evidence
        assert skills["Python"].evidence[0].snippet

    @pytest.mark.parametrize(
        "text",
        [
            "Helped go to market with the R&D team and wrote a C-level summary.",
            "Reported R-squared values for the go-to-market model.",
            "Delivered a C-suite presentation on go-live readiness.",
        ],
    )
    def test_ambiguous_short_names_are_not_false_positives(self, text):
        found = get_skill_extractor().extract_from_text(text)
        assert not ({"C", "R", "Go"} & set(found)), f"false positive in: {text}"

    def test_ambiguous_skills_still_match_their_aliases(self):
        found = get_skill_extractor().extract_from_text(
            "Built microservices in golang and csharp on dotnet core"
        )
        assert {"Go", "C#", ".NET"} <= set(found)

    def test_ambiguous_names_are_still_detected_when_real(self):
        extractor = get_skill_extractor()
        found = extractor.extract_from_text("Languages: C, C++, Go, R, Python")
        for expected in ("C", "C++", "Go", "R", "Python"):
            assert expected in found, f"{expected} should be detected in a language list"

    def test_alias_matching(self):
        extractor = get_skill_extractor()
        found = extractor.extract_from_text("Built models with sklearn and k8s on GCP using pyspark")
        assert "Scikit-learn" in found
        assert "Kubernetes" in found
        assert "Google Cloud Platform" in found
        assert "Apache Spark" in found


# ----------------------------------------------------------------- matcher --


class TestJobMatcher:
    def test_credit_rules(self, parsed):
        kb = get_knowledge_base()
        requirement = kb.build_requirement("amazon", "machine-learning-engineer", "entry")
        skills = get_skill_extractor().extract(parsed)
        result = get_job_matcher().match(parsed, skills, requirement)

        by_skill = {m.skill: m for m in result.matches}
        assert by_skill["Python"].status == "matched"
        assert by_skill["Python"].credit == 1.0
        assert by_skill["Docker"].status == "partial", "listed but never demonstrated"
        assert by_skill["AWS"].status == "missing"
        assert by_skill["AWS"].credit == 0.0
        assert by_skill["AWS"].priority == "high"

    def test_buckets_are_disjoint_and_complete(self, analysis):
        gap = analysis["skill_gap"]
        counts = gap["counts"]
        bucketed = (
            counts["matched"] + counts["partial"] + counts["missing_high"]
            + counts["missing_medium"] + counts["missing_low"] + counts["optional"]
        )
        assert bucketed == counts["total_requirements"]

    def test_company_specificity(self, parsed_strong):
        """The same resume must score differently against different targets."""
        service = get_analysis_service()
        amazon = service.analyse_target(parsed_strong, "amazon", "machine-learning-engineer", "mid")
        nvidia = service.analyse_target(parsed_strong, "nvidia", "machine-learning-engineer", "mid")
        netflix = service.analyse_target(parsed_strong, "netflix", "data-engineer", "mid")

        scores = {
            "amazon": amazon["scoring"]["overall_score"],
            "nvidia": nvidia["scoring"]["overall_score"],
            "netflix": netflix["scoring"]["overall_score"],
        }
        assert len(set(scores.values())) == 3, f"targets produced identical scores: {scores}"
        # A cloud/AWS-heavy ML resume fits Amazon better than NVIDIA (CUDA/C++).
        assert scores["amazon"] > scores["nvidia"]
        assert "CUDA" in [m["skill"] for m in nvidia["skill_gap"]["missing_high_priority"]]

    def test_stronger_resume_scores_higher(self, parsed, parsed_strong):
        service = get_analysis_service()
        weak = service.analyse_target(parsed, "amazon", "machine-learning-engineer", "entry")
        strong = service.analyse_target(parsed_strong, "amazon", "machine-learning-engineer", "entry")
        assert strong["scoring"]["overall_score"] > weak["scoring"]["overall_score"] + 20


# ----------------------------------------------------------------- scoring --


class TestScoringEngine:
    def test_weights_normalise(self):
        engine = ScoringEngine({"skills": 70, "keywords": 30})
        assert pytest.approx(sum(engine.weights.values()), abs=1e-9) == 1.0

    def test_overall_is_a_weighted_mean(self):
        engine = ScoringEngine({"skills": 0.5, "keywords": 0.5})
        report = engine.score(
            [
                ComponentScore("skills", 80, "d"),
                ComponentScore("keywords", 40, "d"),
            ]
        )
        assert pytest.approx(report.overall, abs=0.01) == 60.0

    def test_score_bounds_and_band(self, analysis):
        scoring = analysis["scoring"]
        assert 0 <= scoring["overall_score"] <= 100
        assert scoring["band"]
        for component in scoring["breakdown"]:
            assert 0 <= component["score"] <= 100
            assert component["method"], "every component must explain its method"
            assert component["detail"], "every component must explain its result"

    def test_breakdown_reconstructs_the_overall_score(self, analysis):
        scoring = analysis["scoring"]
        total = sum(c["contribution"] for c in scoring["breakdown"])
        weight = sum(c["weight"] for c in scoring["breakdown"])
        assert pytest.approx(total / weight, abs=0.15) == scoring["overall_score"]


# --------------------------------------------------------------------- ATS --


class TestATSAnalyzer:
    def test_score_and_checks(self, parsed, analysis):
        ats = analysis["ats"]
        assert 0 <= ats["score"] <= 100
        assert len(ats["checks"]) >= 12
        for check in ats["checks"]:
            assert check["status"] in {"pass", "warn", "fail"}
            assert 0 <= check["points"] <= check["max_points"]

    def test_detects_missing_structure(self):
        bare = get_resume_parser().parse_text(
            "John Doe john@example.com\n" + "I worked on things and helped the team. " * 30
        )
        report = get_ats_analyzer().analyse(bare)
        failed = {c["id"] for c in report["checks"] if c["status"] == "fail"}
        assert "standard_headings" in failed
        assert report["score"] < 65


# --------------------------------------------------------------- AI honesty --


class TestHonestyGuarantees:
    def test_no_metric_is_invented(self, analysis):
        """A rewrite must never add a number the candidate did not provide."""
        for items in analysis["ai_suggestions"]["sections"].values():
            for item in items:
                if item["kind"] != "rewrite":
                    continue
                original_numbers = set(find_metrics(item["original"]))
                for metric in find_metrics(item["suggested"]):
                    assert metric in original_numbers or "[" in item["suggested"], (
                        f"invented metric {metric!r} in: {item['suggested']}"
                    )

    def test_missing_metrics_become_placeholders(self, analysis):
        rewrites = [
            item
            for item in analysis["ai_suggestions"]["sections"]["experience"]
            if item["kind"] == "rewrite" and not find_metrics(item["original"])
        ]
        assert rewrites, "the sample resume has unquantified bullets to rewrite"
        assert all("[add a measurable result" in item["suggested"] for item in rewrites)

    def test_support_verbs_are_never_promoted_to_ownership(self):
        """'Helped' must not become 'Led' - that would overstate the role."""
        service = get_ai_service()
        bullet = "Helped the data team with cleaning and preprocessing of transaction records"
        parsed = get_resume_parser().parse_text(
            "Experience\nData Intern | Acme | Jan 2024 - May 2024\n- " + bullet + "\n" * 2
            + "Skills\nPython, SQL\n"
        )
        kb = get_knowledge_base()
        requirement = kb.build_requirement("amazon", "data-analyst", "entry")
        skills = get_skill_extractor().extract(parsed)
        match = get_job_matcher().match(parsed, skills, requirement)
        rewritten, reasons, _tags = service._rewrite_bullet(bullet, match)
        for inflated in ("Led ", "Owned ", "Managed ", "Spearheaded "):
            assert not rewritten.startswith(inflated), f"support role inflated: {rewritten}"
        assert reasons

    def test_every_rewrite_is_labelled_for_verification(self, analysis):
        for items in analysis["ai_suggestions"]["sections"].values():
            for item in items:
                if item["requires_verification"]:
                    assert "SUGGESTED REWRITE" in item["label"]

    def test_llm_metric_screen(self):
        assert _introduces_metric("Built a model", "Built a model with 94% accuracy") is True
        assert _introduces_metric("Improved accuracy by 12%", "Raised accuracy by 12%") is False
        assert _introduces_metric("Built a model", "Designed and built a model") is False

    def test_assistant_refuses_fabrication(self, analysis):
        chat = get_chat_service()
        for question in (
            "Can you add AWS experience I don't have?",
            "Just put Kubernetes on there even though I never used it",
            "Make up a project for me",
        ):
            assert chat._detect_intent(question) == "fabricate"
            answer = chat.answer(question, analysis)["answer"]
            assert "won't help" in answer or "will not help" in answer

    def test_assistant_answers_honest_questions_helpfully(self, analysis):
        chat = get_chat_service()
        result = chat.answer("How can I improve my resume without adding fake experience?", analysis)
        assert result["intent"] == "honest"
        assert "fabricate" in result["answer"]

    def test_assistant_is_grounded_in_the_analysis(self, analysis):
        answer = get_chat_service().answer("Why is my score what it is?", analysis)["answer"]
        assert f"{analysis['scoring']['overall_score']:.0f}" in answer
        assert analysis["target"]["company"]["name"] in answer


# --------------------------------------------------------- section scores --


class TestSectionScores:
    SECTIONS = {"summary", "skills", "experience", "projects", "education"}

    def test_every_section_is_scored_and_bounded(self, analysis):
        scored = analysis["section_scores"]["sections"]
        assert {s["key"] for s in scored} == self.SECTIONS
        for section in scored:
            assert 0 <= section["score"] <= 100
            assert section["verdict"] in {"strong", "adequate", "weak", "missing"}
            assert section["checks"], "a section score must show its working"
            for check in section["checks"]:
                assert 0 <= check["points"] <= check["max_points"]
                assert check["detail"]

    def test_score_is_the_sum_of_its_checks(self, analysis):
        for section in analysis["section_scores"]["sections"]:
            earned = sum(c["points"] for c in section["checks"])
            available = sum(c["max_points"] for c in section["checks"])
            assert pytest.approx(section["score"], abs=0.2) == (earned / available) * 100

    def test_missing_sections_score_zero_and_are_flagged(self):
        bare = get_resume_parser().parse_text(
            "Jane Doe jane@example.com\n\nSKILLS\nPython, SQL, Docker, AWS, Machine Learning\n"
        )
        kb = get_knowledge_base()
        requirement = kb.build_requirement("amazon", "machine-learning-engineer", "entry")
        skills = get_skill_extractor().extract(bare)
        match = get_job_matcher().match(bare, skills, requirement)
        result = get_section_scorer().score(bare, match)

        by_key = {s["key"]: s for s in result["sections"]}
        for absent in ("experience", "projects", "education", "summary"):
            assert by_key[absent]["present"] is False
            assert by_key[absent]["verdict"] == "missing"
        assert by_key["skills"]["present"] is True

    def test_a_strong_resume_outscores_a_weak_one_per_section(self, parsed, parsed_strong):
        service = get_analysis_service()
        weak = service.analyse_target(parsed, "amazon", "machine-learning-engineer", "entry")
        strong = service.analyse_target(parsed_strong, "amazon", "machine-learning-engineer", "entry")
        assert strong["section_scores"]["overall"] > weak["section_scores"]["overall"]

    def test_generic_summary_is_penalised(self, analysis):
        """The sample summary says 'Passionate about…' - that must cost points."""
        summary = next(
            s for s in analysis["section_scores"]["sections"] if s["key"] == "summary"
        )
        specificity = next(c for c in summary["checks"] if c["label"] == "Specific, not generic")
        assert specificity["status"] == "fail"
        assert "generic" in specificity["detail"].lower()

    def test_weakest_section_surfaces_as_an_insight(self, analysis):
        weakest = min(analysis["section_scores"]["sections"], key=lambda s: s["score"])
        if weakest["score"] < 70:
            titles = [i["title"] for i in analysis["insights"] if i["type"] == "section"]
            assert titles and weakest["label"] in titles[0]

    def test_charts_expose_section_scores(self, analysis):
        chart = analysis["charts"]["section_scores"]
        assert {c["key"] for c in chart} == self.SECTIONS
        assert all(0 <= c["score"] <= 100 for c in chart)


# ---------------------------------------------------------- recommendations --


class TestRecommendations:
    def test_projects_close_real_gaps(self, analysis):
        projects = analysis["project_recommendations"]
        assert projects
        gap = analysis["skill_gap"]
        gaps = {
            m["skill"]
            for bucket in (
                "missing_high_priority", "missing_medium_priority", "missing_low_priority",
                "optional", "partially_matched",
            )
            for m in gap[bucket]
        }
        for project in projects:
            assert project["skills_closed"], "a recommendation must close something"
            assert set(project["skills_closed"]) & gaps

    def test_top_project_targets_the_highest_priority_gap(self, analysis):
        top = analysis["project_recommendations"][0]
        high = {m["skill"] for m in analysis["skill_gap"]["missing_high_priority"]}
        assert set(top["skills_closed"]) & high

    def test_roadmap_is_ordered_and_bounded(self, analysis):
        roadmap = analysis["learning_roadmap"]
        assert roadmap["phases"]
        assert [p["phase"] for p in roadmap["phases"]] == list(
            range(1, len(roadmap["phases"]) + 1)
        )
        projection = roadmap["projection"]
        assert (
            projection["current_skills_score"]
            <= projection["after_presentation_fixes"]
            <= projection["after_closing_high_priority"]
            <= 100
        )

    def test_priority_plan_is_sorted_by_priority(self, analysis):
        rank = {"high": 3, "medium": 2, "low": 1}
        ranks = [rank[item["priority"]] for item in analysis["skill_priority_plan"]]
        assert ranks == sorted(ranks, reverse=True)


# ------------------------------------------------------- job descriptions --


class TestJobDescriptionParser:
    JD = """
    Machine Learning Engineer, Personalisation — Amazon

    Basic Qualifications:
    - 3+ years of experience with Python and machine learning
    - Experience deploying models to production with AWS and Docker
    - Strong SQL and data pipeline experience

    Preferred Qualifications:
    - Experience with Amazon SageMaker and MLOps practices
    - Familiarity with Apache Spark and Kubernetes

    Responsibilities:
    - Build and deploy machine learning models serving millions of customers
    - Own model monitoring and automated retraining pipelines end to end
    """

    def test_extracts_required_and_preferred_separately(self):
        requirement, analysis = get_jd_parser().parse(self.JD)
        required = {s["skill"] for s in analysis["required_skills"]}
        preferred = {s["skill"] for s in analysis["preferred_skills"]}
        assert {"Python", "Machine Learning", "AWS", "Docker", "SQL"} <= required
        assert "Amazon SageMaker" in preferred
        assert analysis["years_required"] == 3.0
        assert analysis["responsibilities"]

    def test_detects_company_and_role(self):
        _requirement, analysis = get_jd_parser().parse(self.JD)
        assert analysis["detected_company"] == "Amazon"
        assert "Machine Learning Engineer" in analysis["detected_role"]

    def test_fusion_keeps_both_sources(self):
        parser = get_jd_parser()
        requirement, _ = parser.parse(self.JD)
        fused = parser.fuse_with_target(requirement, "amazon", "machine-learning-engineer", "mid")
        assert fused.company_name == "Amazon"
        assert "customer obsession" in [k.lower() for k in fused.keywords]
        assert "AWS" in fused.skill_names()

    def test_short_input_is_rejected(self):
        with pytest.raises(ValueError):
            get_jd_parser().parse("We need an engineer.")

    def test_full_pipeline_runs_on_a_pasted_jd(self, parsed):
        requirement, jd_analysis = get_jd_parser().parse(self.JD)
        result = get_analysis_service().run(parsed, requirement, jd_analysis=jd_analysis)
        assert 0 <= result["scoring"]["overall_score"] <= 100
        assert result["job_description_analysis"]["required_skills"]


# ----------------------------------------------------------------- the API --


@pytest.fixture(scope="module")
def client():
    """A TestClient bound to the real app, with lifespan startup executed."""
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as test_client:
        yield test_client


class TestAPI:
    def test_health(self, client):
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["datasets"]["companies"] >= 8

    def test_catalog(self, client):
        body = client.get("/api/catalog").json()
        assert len(body["companies"]) >= 8
        assert len(body["roles"]) >= 10
        assert body["skill_count"] >= 100

    def test_upload_and_analyse(self, client, sample_text):
        upload = client.post(
            "/api/resume/upload",
            files={"file": ("sample_resume.txt", sample_text.encode(), "text/plain")},
        )
        assert upload.status_code == 200
        resume_id = upload.json()["resume_id"]

        response = client.post(
            "/api/analyze",
            json={
                "resume_id": resume_id,
                "company": "amazon",
                "role": "machine-learning-engineer",
                "level": "entry",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        for key in (
            "scoring", "ats", "skill_gap", "ai_suggestions",
            "project_recommendations", "learning_roadmap", "charts",
        ):
            assert key in payload

        stored = client.get(f"/api/analysis/{payload['analysis_id']}")
        assert stored.status_code == 200
        assert stored.json()["scoring"]["overall_score"] == payload["scoring"]["overall_score"]

    def test_upload_validation(self, client):
        assert client.post(
            "/api/resume/upload", files={"file": ("virus.exe", b"MZ", "application/octet-stream")}
        ).status_code == 415
        assert client.post(
            "/api/resume/upload", files={"file": ("empty.txt", b"", "text/plain")}
        ).status_code == 400

    def test_analysis_error_paths(self, client):
        assert client.post(
            "/api/analyze", json={"resume_id": 1, "company": "nope", "role": "software-engineer"}
        ).status_code == 404
        assert client.post(
            "/api/analyze", json={"resume_id": 999999, "company": "amazon", "role": "software-engineer"}
        ).status_code == 404
        assert client.post(
            "/api/analyze", json={"company": "amazon", "role": "software-engineer"}
        ).status_code == 400
        assert client.post("/api/analyze", json={"company": "amazon"}).status_code == 422

    def test_project_recommendation_endpoint(self, client):
        response = client.post(
            "/api/projects/recommend",
            json={"missing_skills": ["AWS", "Docker", "MLOps"], "role": "machine-learning-engineer"},
        )
        assert response.status_code == 200
        assert response.json()["projects"]

    def test_chat_endpoint(self, client):
        response = client.post("/api/chat", json={"question": "What should I learn first?"})
        assert response.status_code == 200
        assert response.json()["answer"]

    def test_dashboard_is_served(self, client):
        page = client.get("/")
        assert page.status_code == 200
        assert "Resume Intelligence" in page.text


def test_nlp_backend_reports_itself():
    info = get_pipeline().info()
    assert info["backend"] in {"spacy", "spacy-blank", "regex"}
    assert info["detail"]
