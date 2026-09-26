"""Máquina de estados de cada item da agenda (um exame de um paciente num dia).

O estado fica em SQLite (F1). Cada item percorre, em geral, esta sequência:

    DESCOBERTO -> ANTECEDENTES_OK -> PRONTO_PARA_EXAME
      -> LAUDO_DO_DIA_PENDENTE -> EVOLUTIVO_PENDENTE -> REVISAO_MEDICA
      -> CONCLUIDO

``IDENTIDADE_PENDENTE`` é um desvio: pausa só aquele item (o lote segue)
até o vínculo MD <-> XClinic ser confirmado.

Cobertura das fontes e pendências são dimensões separadas do estado. Um
item pode estar ``PRONTO_PARA_EXAME`` com a pendência "XClinic
indisponível", e isso nunca vira histórico negativo.

ESTADO: esqueleto. Transições, persistência e checkpoints por documento
entram na F1.
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
