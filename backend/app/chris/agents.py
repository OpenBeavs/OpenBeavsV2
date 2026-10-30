"""Agent metadata Chris routes between, plus a mock list for testing.

v2 has no agents database yet. ``MOCK_AGENTS`` uses the same fields as v1
(id, name, description, skills) so routing can be tried before real agents
exist. It is used only when ``CHRIS_USE_MOCK_AGENTS`` is set (see router.py).
"""

from dataclasses import dataclass, field


@dataclass
class Agent:
    """The minimum agent metadata the router needs."""

    id: str
    name: str
    description: str = ""
    skills: list[str] = field(default_factory=list)


MOCK_AGENTS: list[Agent] = [
    Agent(
        id="honors-college",
        name="Honors College",
        description="Answers questions about the OSU Honors College: admission, "
        "thesis requirements, honors courses, scholarships and advising.",
        skills=[
            "honors college",
            "honors thesis",
            "honors courses",
            "honors scholarship",
        ],
    ),
    Agent(
        id="engineering-advisor",
        name="Engineering Advisor",
        description="Helps College of Engineering students with degree requirements, "
        "course planning, prerequisites, majors and registration.",
        skills=[
            "engineering",
            "degree requirements",
            "course planning",
            "prerequisites",
            "major",
        ],
    ),
    Agent(
        id="writing-center",
        name="Writing Center",
        description="Helps with writing: drafting, editing, structure, citations, "
        "essays, personal statements and booking writing consultations.",
        skills=["writing", "essay", "editing", "citations", "personal statement"],
    ),
    Agent(
        id="library",
        name="Library",
        description="Helps find library resources: books, articles, databases, "
        "research help, study rooms and library hours.",
        skills=["library", "databases", "articles", "research help", "study rooms"],
    ),
]
