"""Qual fila uma vaga avaliada vai: automática ou manual.

Calculado na hora (não gravado): mudar o limiar no profile.yaml reclassifica tudo sem
reprocessar nada.
"""

from enum import StrEnum

from night_shift.domain.enums import SOURCE_RISK, RiskLevel, Source


class Lane(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


def lane_for(source: Source, score: int | None, red_flags: list[str], threshold: int) -> Lane:
    """Automática só quando tudo indica que dá para aplicar sem olhar:

    - fonte de baixo risco (formulário padrão de ATS: Greenhouse, Lever, Ashby);
    - nota do LLM no limiar ou acima;
    - nenhum alerta (inglês fluente, anos de experiência, presencial longe...).
    Qualquer dúvida vai para a manual.
    """
    if (
        SOURCE_RISK[source] is RiskLevel.LOW
        and score is not None
        and score >= threshold
        and not red_flags
    ):
        return Lane.AUTO
    return Lane.MANUAL


def manual_reason(source: Source, score: int | None, red_flags: list[str], threshold: int) -> str:
    """Por que a vaga não foi para a fila automática (texto curto para o painel)."""
    if SOURCE_RISK[source] is not RiskLevel.LOW:
        return f"{source}: candidatura só manual"
    if score is None or score < threshold:
        return f"nota abaixo de {threshold}"
    if red_flags:
        return "tem alertas"
    return ""
