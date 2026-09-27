"""Máquina de estados de cada item da agenda (um exame de um paciente num dia).

O estado fica em SQLite (``fluxo_exames/fila.py``). Cada item percorre, em
geral, esta sequência:

    DESCOBERTO -> ANTECEDENTES_OK -> PRONTO_PARA_EXAME
      -> LAUDO_DO_DIA_PENDENTE -> EVOLUTIVO_PENDENTE -> REVISAO_MEDICA
      -> CONCLUIDO

O único atalho é ``LAUDO_DO_DIA_PENDENTE -> REVISAO_MEDICA``, para exame sem
série evolutiva (nem mamas nem tireoide).

``IDENTIDADE_PENDENTE`` é um desvio: pausa só aquele item (o lote segue)
até o vínculo MD <-> XClinic ser confirmado. Entra-se nele a partir de
qualquer estado não final e volta-se exatamente ao estado de onde se saiu
(a fila guarda esse estado de retorno).

Cobertura das fontes e pendências são dimensões separadas do estado. Um
item pode estar ``PRONTO_PARA_EXAME`` com a pendência "XClinic
indisponível", e isso nunca vira histórico negativo.

ESTADO: F1. Transições definidas aqui; persistência e checkpoints por
documento em ``fila.py``.
"""

DESCOBERTO = "DESCOBERTO"
"""Item lido da agenda do MD; nada foi coletado ainda."""

ANTECEDENTES_OK = "ANTECEDENTES_OK"
"""Laudos anteriores levantados nas fontes disponíveis, com a cobertura registrada."""

IDENTIDADE_PENDENTE = "IDENTIDADE_PENDENTE"
"""Vínculo com o XClinic ambíguo ou divergente; aguarda confirmação do médico."""

PRONTO_PARA_EXAME = "PRONTO_PARA_EXAME"
"""Briefing (e dossiê, quando aplicável) pronto antes do exame."""

LAUDO_DO_DIA_PENDENTE = "LAUDO_DO_DIA_PENDENTE"
"""Exame realizado ou em curso; aguardando o laudo do dia passar pelo validador."""

EVOLUTIVO_PENDENTE = "EVOLUTIVO_PENDENTE"
"""Laudo do dia validado; controle evolutivo (mamas/tireoide) a gerar."""

REVISAO_MEDICA = "REVISAO_MEDICA"
"""Saídas geradas como rascunho; aguardando revisão do médico."""

CONCLUIDO = "CONCLUIDO"
"""Revisado pelo médico. Nada é escrito no MD pelo app."""

ESTADOS = (
    DESCOBERTO,
    ANTECEDENTES_OK,
    IDENTIDADE_PENDENTE,
    PRONTO_PARA_EXAME,
    LAUDO_DO_DIA_PENDENTE,
    EVOLUTIVO_PENDENTE,
    REVISAO_MEDICA,
    CONCLUIDO,
)

INICIAL = DESCOBERTO
FINAIS = frozenset({CONCLUIDO})

# Transições da sequência principal. O desvio IDENTIDADE_PENDENTE é tratado
# à parte em ``transicao_valida``.
TRANSICOES = {
    DESCOBERTO: frozenset({ANTECEDENTES_OK}),
    ANTECEDENTES_OK: frozenset({PRONTO_PARA_EXAME}),
    PRONTO_PARA_EXAME: frozenset({LAUDO_DO_DIA_PENDENTE}),
    LAUDO_DO_DIA_PENDENTE: frozenset({EVOLUTIVO_PENDENTE, REVISAO_MEDICA}),
    EVOLUTIVO_PENDENTE: frozenset({REVISAO_MEDICA}),
    REVISAO_MEDICA: frozenset({CONCLUIDO}),
    CONCLUIDO: frozenset(),
}


class TransicaoInvalida(ValueError):
    """Mudança de estado fora da máquina de estados."""


def transicao_valida(de, para, retorno=None):
    """Diz se ``de -> para`` é permitido.

    ``retorno`` é o estado de onde o item entrou em ``IDENTIDADE_PENDENTE``;
    só ele é destino válido na saída do desvio.
    """
    if de not in ESTADOS or para not in ESTADOS:
        return False
    if para == IDENTIDADE_PENDENTE:
        return de not in FINAIS and de != IDENTIDADE_PENDENTE
    if de == IDENTIDADE_PENDENTE:
        return retorno is not None and para == retorno
    return para in TRANSICOES[de]
