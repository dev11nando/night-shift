"""Similaridade por palavras-chave, sem modelo: implementa a porta ``Embedder``.

O vocabulário vem do próprio CV (termos técnicos e de domínio). Cada texto vira um vetor
com a frequência log-escalada desses termos, e o pipeline compara por cosseno como faria
com embeddings. Serve só para decidir a ordem em que as vagas vão para o LLM.
"""

import math
import re
from collections import Counter

from night_shift.domain.text import fold

# Palavras comuns em PT/EN que não ajudam a diferenciar vagas.
_STOPWORDS_TEXT = """
    a o as os um uma uns umas de do da dos das em no na nos nas por para pra com sem e ou
    que se ao aos como mais menos muito sua seu suas seus ser ter foi sao esta este essa esse
    isso nao sim ja entre sobre ate ate tambem atraves via cada todo toda todos todas
    the of and or to in on for with by an at from as is are be this that it its our your we you
    experiencia desenvolvimento desenvolvedor engenheiro engenheira software solucao solucoes
    aplicacoes aplicacao utilizando atuando participacao principios
"""
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.\-]*[a-z0-9+#]|[a-z0-9]")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(fold(text)) if len(t) > 1 and t not in STOPWORDS]


class KeywordEmbedder:
    model = "keywords"

    def __init__(self, reference_text: str, max_terms: int = 300) -> None:
        counts = Counter(tokenize(reference_text))
        self.vocabulary = [term for term, _ in counts.most_common(max_terms)]
        self._index = {t: i for i, t in enumerate(self.vocabulary)}

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * len(self.vocabulary)
        for term, n in Counter(tokenize(text)).items():
            i = self._index.get(term)
            if i is not None:
                vec[i] = 1.0 + math.log(n)
        return vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]
