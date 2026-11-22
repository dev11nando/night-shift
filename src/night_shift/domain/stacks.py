"""Em que stack uma vaga se encaixa, para usar o perfil de CV certo (python, ia, java).

Regra: o título manda (é onde a empresa diz o que quer); sem pista no título, conta as
menções na descrição. Sem nenhuma pista, a vaga fica com o perfil padrão (python).

Na descrição, só sinais fortes de IA contam: muita vaga cita "IA" de passagem ("usamos IA
no produto") sem ser vaga de IA.
"""

from night_shift.domain.text import contains_term, fold

DEFAULT_STACK = "python"

JAVA_TERMS = ["java", "spring", "spring boot", "springboot", "jvm", "kotlin", "quarkus"]
PYTHON_TERMS = ["python", "fastapi", "django", "flask", "pydantic", "sqlalchemy"]
STRONG_IA_TERMS = [
    "llm",
    "llms",
    "genai",
    "ia generativa",
    "generative ai",
    "machine learning",
    "ml engineer",
    "rag",
    "langchain",
    "langgraph",
    "agentes de ia",
    "agentes inteligentes",
    "ai agents",
    "inteligencia artificial generativa",
]
# No título, até "IA"/"AI" solto vale: "Desenvolvedor de IA" é vaga de IA.
TITLE_IA_TERMS = [
    *STRONG_IA_TERMS,
    "ia",
    "ai",
    "inteligencia artificial",
    "artificial intelligence",
]

TIE_ORDER = ["python", "ia", "java"]  # empate: python ganha (perfil mais forte), depois ia


def _hits(text: str, terms: list[str]) -> int:
    return sum(1 for t in terms if contains_term(text, t))


def _best(hits: dict[str, int]) -> str:
    return max(TIE_ORDER, key=lambda s: (hits[s], -TIE_ORDER.index(s)))


def classify_stack(title: str, description: str = "") -> str:
    title_hits = {
        "java": _hits(title, JAVA_TERMS),
        "ia": _hits(title, TITLE_IA_TERMS),
        "python": _hits(title, PYTHON_TERMS),
    }
    if any(title_hits.values()):
        # Java no título é sinal forte ("Java/Python" é vaga Java: é o que pedem primeiro).
        return "java" if title_hits["java"] else _best(title_hits)

    desc = fold(description[:6000])
    desc_hits = {
        "java": _hits(desc, JAVA_TERMS),
        "ia": _hits(desc, STRONG_IA_TERMS),
        "python": _hits(desc, PYTHON_TERMS),
    }
    return _best(desc_hits) if any(desc_hits.values()) else DEFAULT_STACK
