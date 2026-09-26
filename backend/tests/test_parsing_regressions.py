"""Regressions found against a real user's resume.

Every test here corresponds to a bug that silently wrecked the score rather than
raising anything. They were found by feeding a builder-generated resume back
into the builder - a normal thing for a user to do, and something no earlier
test covered.

The failures were:

* PDF ligatures ("fi", "fl", "ffi" as single glyphs) survived parsing, so
  "Artificial Intelligence" never matched the ontology and a B.Tech read as a
  non-technical field of study.
* A blank line between bullets was treated as a new entry, inventing title-less
  jobs and turning eight bullets into eight separate "projects".
* "Tech:" and "Link:" lines became projects of their own.
* The renderer emitted a literal "Experience" header for a title-less entry,
  which our own parser then read as yet another entry - so each rebuild
  multiplied the damage.
* Bullets that already carried "[add a measurable result …]" collected another
  one on every rebuild.

Run from the project root:

    pytest backend/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.analysis_service import get_analysis_service  # noqa: E402
from services.knowledge_base import get_knowledge_base  # noqa: E402
from services.resume_builder import BuildOptions, get_resume_builder  # noqa: E402
from services.resume_parser import get_resume_parser  # noqa: E402

SAMPLES = BACKEND.parent / "samples"

FI, FL, FFI = "ﬁ", "ﬂ", "ﬃ"


@pytest.fixture(scope="module")
def parsed():
    text = (SAMPLES / "sample_resume.txt").read_text(encoding="utf-8")
    return get_resume_parser().parse_text(text, "sample_resume.txt")


@pytest.fixture(scope="module")
def requirement():
    return get_knowledge_base().build_requirement(
        "amazon", "machine-learning-engineer", "entry"
    )


class TestLigatures:
    def test_pdf_ligatures_are_normalised(self):
        raw = (
            "ROHIT KUMAR\nrohit@example.com\n\n"
            "TECHNICAL SKILLS\n"
            f"Tools: ML{FL}ow, MS O{FFI}ce\n"
            f"ML & AI: Arti{FI}cial Intelligence, Classi{FI}cation\n\n"
            "EDUCATION\nB.Tech in Information Technology, 2022\n"
        )
        parsed = get_resume_parser().parse_text(raw)
        for glyph in (FI, FL, FFI):
            assert glyph not in parsed.raw_text
        assert "MLflow" in parsed.raw_text
        assert "Artificial" in parsed.raw_text

    def test_a_ligatured_skill_is_still_detected(self):
        from services.skill_extractor import get_skill_extractor

        raw = (
            "ROHIT KUMAR\nrohit@example.com\n\n"
            f"TECHNICAL SKILLS\nTools: ML{FL}ow, Docker\n\n"
            f"PROJECTS\nModel tracking\n- Tracked runs with ML{FL}ow and Docker\n"
        )
        parsed = get_resume_parser().parse_text(raw)
        found = {s.name for s in get_skill_extractor().extract(parsed)}
        assert "MLflow" in found


class TestEntryGrouping:
    def test_blank_separated_bullets_stay_with_their_role(self):
        raw = (
            "ROHIT KUMAR\nrohit@example.com\n\n"
            "EXPERIENCE\n"
            "Web Development Intern | Webnexa Solutions | Jun 2025 - Jul 2025\n\n"
            "- Built the front end of the company website using HTML and CSS\n\n"
            "- Helped the team with testing and fixing bugs in the reporting flow\n\n"
            "- Applied Git and teamwork on a real production project\n"
        )
        parsed = get_resume_parser().parse_text(raw)
        assert len(parsed.experience) == 1, [e.title for e in parsed.experience]
        assert len(parsed.experience[0].bullets) == 3
        assert parsed.experience[0].title == "Web Development Intern"
        assert parsed.experience[0].date_range

    def test_blank_separated_bullets_stay_with_their_project(self):
        raw = (
            "ROHIT KUMAR\nrohit@example.com\n\n"
            "PROJECTS\n"
            "House Price Prediction\n\n"
            "- Trained a model to predict house prices using Python and Scikit-learn\n\n"
            "- Applied linear regression and did data cleaning with Pandas\n\n"
            "Tech: Python, Scikit-learn, Pandas\n"
        )
        parsed = get_resume_parser().parse_text(raw)
        assert len(parsed.projects) == 1, [p.name for p in parsed.projects]
        assert len(parsed.projects[0].bullets) == 2
        assert parsed.projects[0].name == "House Price Prediction"

    def test_metadata_lines_never_become_projects(self):
        raw = (
            "ROHIT KUMAR\nrohit@example.com\n\n"
            "PROJECTS\nMovie Recommender\n"
            "- Built a recommender in Python on a Kaggle dataset of ratings\n\n"
            "Tech: Python\n\nLink: github.com/rohit/movies\n"
        )
        parsed = get_resume_parser().parse_text(raw)
        names = [p.name.lower() for p in parsed.projects]
        assert "tech" not in names
        assert "link" not in names
        assert parsed.projects[0].tech_hint

    def test_a_real_second_role_is_still_its_own_entry(self):
        """The grouping fix must not merge genuinely separate jobs."""
        raw = (
            "ROHIT KUMAR\nrohit@example.com\n\n"
            "EXPERIENCE\n"
            "ML Intern | Alpha Labs | Jan 2024 - Jun 2024\n"
            "- Trained models in Python on production data\n\n"
            "Backend Intern | Beta Corp | Jul 2024 - Dec 2024\n"
            "- Built REST APIs in Flask for internal tools\n"
        )
        parsed = get_resume_parser().parse_text(raw)
        assert len(parsed.experience) == 2, [e.title for e in parsed.experience]
        assert {e.organisation for e in parsed.experience} == {"Alpha Labs", "Beta Corp"}


class TestTechnicalField:
    @pytest.mark.parametrize(
        "line,is_technical",
        [
            ("B.Tech, Technology - Awadh Institute, 2022", True),
            ("B.Tech in Information Technology, 2022", True),
            ("B.Sc in Computer Science, 2021", True),
            ("Bachelor of Arts in History, 2021", False),
        ],
    )
    def test_field_relevance(self, line, is_technical, requirement):
        raw = f"ROHIT KUMAR\nrohit@example.com\n\nEDUCATION\n{line}\n"
        parsed = get_resume_parser().parse_text(raw)
        payload = get_analysis_service().run(parsed, requirement)
        education = next(
            c for c in payload["scoring"]["breakdown"] if c["label"].startswith("Education")
        )
        relevant = "not obviously technical" not in education["detail"]
        assert relevant is is_technical, education["detail"]


class TestBuilderIdempotence:
    """Rebuilding a generated resume must not degrade it."""

    @staticmethod
    def _chain(resume, requirement, rounds: int = 3):
        parser, builder = get_resume_parser(), get_resume_builder()
        results = []
        text = resume.raw_text
        for _ in range(rounds):
            reparsed = parser.parse_text(text, "generated.txt")
            built = builder.build(reparsed, requirement, BuildOptions())
            results.append(built)
            text = built["text"]
        return results

    def test_placeholders_do_not_multiply(self, parsed, requirement):
        counts = [r["placeholder_count"] for r in self._chain(parsed, requirement)]
        assert counts[1] <= counts[0], counts
        assert counts[2] <= counts[1], counts

    def test_no_bullet_collects_two_blanks(self, parsed, requirement):
        final = self._chain(parsed, requirement)[-1]["text"]
        for line in final.split("\n"):
            assert line.count("[add a measurable result") <= 1, line
            assert line.count("<the specific tools you used>") <= 1, line

    def test_structure_is_stable_across_rebuilds(self, parsed, requirement):
        results = self._chain(parsed, requirement)
        shapes = [
            (len(r["resume"]["projects"]), len(r["resume"]["experience"])) for r in results
        ]
        assert shapes[1] == shapes[2], shapes

    def test_score_does_not_drift_downwards(self, parsed, requirement):
        scores = [r["score"]["after"] for r in self._chain(parsed, requirement)]
        assert scores[2] >= scores[1] - 0.1, scores

    def test_no_phantom_section_headers_are_emitted(self, parsed, requirement):
        built = get_resume_builder().build(parsed, requirement, BuildOptions())
        lines = [l.strip() for l in built["text"].split("\n")]
        assert "Experience" not in lines
        assert "Project" not in lines

    def test_a_project_name_is_not_printed_twice(self, parsed, requirement):
        built = get_resume_builder().build(parsed, requirement, BuildOptions())
        for project in built["resume"]["projects"]:
            if project["name"] and project["description"]:
                assert project["description"].strip().lower() != project["name"].strip().lower()


class TestRecommendedProjects:
    def test_projects_are_named_but_never_written_in(self, parsed, requirement):
        built = get_resume_builder().build(parsed, requirement, BuildOptions())
        recommended = built["recommended_projects"]
        assert recommended, "a resume with gaps should get project suggestions"

        for project in recommended:
            assert project["title"] and project["skills_closed"]
            assert project["resume_bullet_template"]
            # Named as something to build - never inserted into the document.
            assert project["title"] not in built["text"]
        assert "will not be" in built["projects_note"]

    def test_templates_keep_their_blanks(self, parsed, requirement):
        built = get_resume_builder().build(parsed, requirement, BuildOptions())
        for project in built["recommended_projects"]:
            template = project["resume_bullet_template"]
            assert "<" in template or "[" in template, template

class TestUserSelectedProjects:
    """Adding a recommended project is opt-in, and arrives as a scaffold.

    A skill is a word; a project is a story an interviewer will dig into. So a
    selected project is inserted with its blanks intact and the export refuses
    to run until they are filled - otherwise stripping the blanks would turn a
    template into a claim the candidate never made."""

    PROJECT_ID = 'e2e-ml-aws'

    def test_nothing_is_added_by_default(self, parsed, requirement):
        built = get_resume_builder().build(parsed, requirement, BuildOptions())
        assert built['projects_added']['built'] == []
        assert built['projects_added']['in_progress'] == []
        assert built['added_project_warning'] == ''

    def test_a_selected_project_is_added_with_its_blanks(self, parsed, requirement):
        built = get_resume_builder().build(
            parsed, requirement, BuildOptions(projects_built=[self.PROJECT_ID])
        )
        assert built['projects_added']['built']
        title = built['projects_added']['built'][0]
        assert title in built['text']
        assert built['unfilled_blanks'] > 0
        assert built['added_project_warning']
        assert any(c['section'] == 'Projects' for c in built['changes'])

    def test_the_added_bullet_invents_no_number(self, parsed, requirement):
        built = get_resume_builder().build(
            parsed, requirement, BuildOptions(projects_built=[self.PROJECT_ID])
        )
        added = next(
            p for p in built['resume']['projects'] if p.get('added_by_user')
        )
        for bullet in added['bullets']:
            assert '<' in bullet, bullet
            for token in bullet.split():
                assert not token.strip('.,').isdigit(), bullet

    def test_export_is_blocked_until_the_blanks_are_filled(self, parsed, requirement):
        from services.resume_export import ResumeExportError, render, required_blanks

        built = get_resume_builder().build(
            parsed, requirement, BuildOptions(projects_built=[self.PROJECT_ID])
        )
        with pytest.raises(ResumeExportError) as excinfo:
            render(built['text'], 'docx')
        assert 'need your own details' in str(excinfo.value)

        filled = built['text']
        for blank in dict.fromkeys(required_blanks(filled)):
            filled = filled.replace(blank, 'a real detail')
        assert required_blanks(filled) == []
        assert render(filled, 'docx')[:2] == b'PK'

    def test_in_progress_is_labelled_and_separate(self, parsed, requirement):
        built = get_resume_builder().build(
            parsed, requirement, BuildOptions(projects_in_progress=[self.PROJECT_ID])
        )
        assert built['projects_added']['in_progress']
        assert built['projects_added']['built'] == []
        assert 'In progress:' in built['text']
        # It must not appear as a finished project entry.
        finished = [p['name'] for p in built['resume']['projects']]
        assert built['projects_added']['in_progress'][0] not in finished

    def test_the_tool_blank_still_strips_cleanly(self):
        from services.resume_export import strip_placeholders

        line = '- Built dashboards for the team using <the specific tools you used>'
        cleaned = strip_placeholders(line)
        assert '<' not in cleaned
        assert not cleaned.rstrip().endswith('using')
        assert cleaned.strip() == '- Built dashboards for the team'


class TestUserSelectedProjectsAPI:
    @pytest.fixture(scope='class')
    def client(self):
        from fastapi.testclient import TestClient

        import main

        with TestClient(main.app) as test_client:
            yield test_client

    @pytest.fixture(scope='class')
    def analysis_id(self, client):
        text = (SAMPLES / 'sample_resume.txt').read_text(encoding='utf-8')
        upload = client.post('/api/resume/parse-text', data={'resume_text': text})
        analysis = client.post(
            '/api/analyze',
            json={
                'resume_id': upload.json()['resume_id'],
                'company': 'amazon',
                'role': 'machine-learning-engineer',
                'level': 'entry',
            },
        )
        return analysis.json()['analysis_id']

    def test_unknown_project_id_is_rejected(self, client, analysis_id):
        response = client.post(
            '/api/resume/build',
            json={'analysis_id': analysis_id, 'projects_built': ['not-a-project']},
        )
        assert response.status_code == 422
        assert 'Unknown project id' in response.json()['detail']

    def test_a_project_cannot_be_both_finished_and_in_progress(self, client, analysis_id):
        response = client.post(
            '/api/resume/build',
            json={
                'analysis_id': analysis_id,
                'projects_built': ['e2e-ml-aws'],
                'projects_in_progress': ['e2e-ml-aws'],
            },
        )
        assert response.status_code == 422
        assert 'cannot be both' in response.json()['detail']

    def test_export_endpoint_reports_unfilled_blanks(self, client, analysis_id):
        built = client.post(
            '/api/resume/build',
            json={'analysis_id': analysis_id, 'projects_built': ['e2e-ml-aws']},
        ).json()
        assert built['unfilled_blanks'] > 0
        response = client.post(
            '/api/resume/export',
            json={'text': built['text'], 'format': 'docx'},
        )
        assert response.status_code == 422
        assert 'need your own details' in response.json()['detail']

class TestContactExtraction:
    """A skills line used to be printed as the candidate's location."""

    @pytest.mark.parametrize(
        "contact_line,expected",
        [
            ("rohit@example.com | Lucknow | linkedin.com/in/rohit", "Lucknow"),
            ("Bengaluru, India | a@example.com | +91 98765 43210", "Bengaluru, India"),
            ("john@example.com | github.com/john", ""),
        ],
    )
    def test_location_comes_from_the_contact_line(self, contact_line, expected):
        raw = (
            "ROHIT KUMAR" + chr(10) + contact_line + chr(10) * 2
            + "TECHNICAL SKILLS" + chr(10)
            + "ML & AI: Machine Learning, Deep Learning, Feature Engineering" + chr(10)
        )
        parsed = get_resume_parser().parse_text(raw)
        assert parsed.contact["location"] == expected

    def test_a_skills_line_is_never_a_location(self):
        raw = (
            "JANE DOE" + chr(10) + "jane@example.com" + chr(10) * 2
            + "TECHNICAL SKILLS" + chr(10)
            + "ML & AI: Machine Learning, Deep Learning, Computer Vision" + chr(10)
        )
        parsed = get_resume_parser().parse_text(raw)
        assert "Machine Learning" not in parsed.contact["location"]
