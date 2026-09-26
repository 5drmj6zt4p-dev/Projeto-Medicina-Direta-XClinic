"""Guarda de somente leitura do coletor do Medicina Direta (MD).

No MD, o caminho de leitura de um laudo passa ao lado de ações de escrita e
de assinatura ("Finalizar e Assinar" no formulário e "ASSINAR PDF" na lista).
Esta guarda garante o somente leitura por mecanismo, em três camadas
independentes. A política é negar por padrão: o que não foi demonstrado como
leitura na Fase 0 fica bloqueado.

Camada 1 — métodos HTTP
    Toda requisição com método em ``METODOS_HTTP_BLOQUEADOS`` é abortada
    no ``context.route`` do Playwright antes de sair do navegador.

Camada 2 — textos de botão
    O coletor não clica em elemento cujo texto visível (ou ``value``,
    ``title`` ou ``aria-label``) case com ``TEXTOS_BOTAO_BLOQUEADOS``. A
    checagem é feita sobre o texto normalizado (sem acento, caixa alta).

Camada 3 — POST
    Todo ``POST`` é abortado, salvo os que casam com uma entrada de
    ``POSTS_PERMITIDOS``. Cada entrada precisa ter sido observada e
    demonstrada como leitura na Fase 0 (Etapa B), com a evidência anotada.
    O ScriptCase também usa POST para navegar em grades, então a lista
    branca não pode ficar vazia em produção. Mesmo assim, um POST que não
    está nela nunca passa.

Além disso, um parâmetro de operação de gravação do ScriptCase
(``OPERACOES_SCRIPTCASE_BLOQUEADAS``) bloqueia a requisição mesmo quando o
método e o endpoint pareceriam permitidos.

Toda requisição bloqueada é registrada. Uma tentativa de escrita registrada
conta como erro crítico no modo sombra.

Fonte do mapa de operações: o ``rede-resumo.json`` produzido por
``scripts/gravador_passivo.py --rede`` durante a Etapa B (ver
``docs/FASE-0-ETAPA-A.md``, item 4.1). Ele lista as tuplas distintas
(método, caminho, ``nmgp_opcao``) observadas, com contagem e status. Cada
entrada de ``POSTS_PERMITIDOS`` e de ``OPERACOES_SCRIPTCASE_BLOQUEADAS`` deve
corresponder a uma tupla desse resumo, associada à ação de tela que a gerou.
O arquivo fica na pasta local de capturas e não entra no repositório. Para
cá vêm só caminho e valor de operação, sem query nem identificador de paciente.

ESTADO: esqueleto. As listas abaixo são PLACEHOLDER e as funções ainda não
estão implementadas. Os valores reais saem do mapeamento da Fase 0, Etapa B.
"""

# PLACEHOLDER — camada 1. GET, HEAD e OPTIONS passam por esta camada; POST
# é tratado pela camada 3; os métodos abaixo são sempre bloqueados.
METODOS_HTTP_BLOQUEADOS = frozenset({
    "PUT",
    "PATCH",
    "DELETE",
    "PROPFIND",
    "PROPPATCH",
    "MKCOL",
    "COPY",
    "MOVE",
    "LOCK",
    "UNLOCK",
})

# PLACEHOLDER — camada 2. Textos normalizados (sem acento, caixa alta).
# Casamento por substring: "FINALIZAR" também bloqueia "FINALIZAR E ASSINAR".
TEXTOS_BOTAO_BLOQUEADOS = (
    "ASSINAR",
    "ASSINAR PDF",
    "FINALIZAR",
    "FINALIZAR E ASSINAR",
    "SALVAR",
    "GRAVAR",
    "EXCLUIR",
    "APAGAR",
    "REMOVER",
    "CRIAR",
    "NOVO",
    "INCLUIR",
    "ADICIONAR",
    "ALTERAR",
    "EDITAR",
    "ENVIAR",
    "ENVIAR POR",
    "SOLICITA",
    "CONFIRMAR",
    "ACOES",
)

# PLACEHOLDER — camada 3. Lista branca de POSTs demonstrados como leitura.
# Formato previsto de cada entrada (preencher na Etapa B):
#   {"url_regex": r"...", "parametros_obrigatorios": {"nmgp_opcao": "..."},
#    "evidencia": "tupla do rede-resumo.json + tela que demonstrou ser leitura"}
POSTS_PERMITIDOS = ()

# PLACEHOLDER — valores de operação do ScriptCase que indicam gravação.
# Nomes e valores exatos a confirmar na Etapa B.
OPERACOES_SCRIPTCASE_BLOQUEADAS = {
    "nmgp_opcao": ("alterar", "incluir", "excluir", "novo"),
}


class EscritaBloqueada(Exception):
    """Levantada quando o coletor tenta uma operação que a guarda bloqueia."""


def normalizar_texto(texto):
    """Remove acentos, junta espaços e passa para caixa alta.

    É a forma usada para comparar textos de botão com
    ``TEXTOS_BOTAO_BLOQUEADOS``.
    """
    raise NotImplementedError("Fase 0: esqueleto")


def requisicao_permitida(metodo, url, corpo=None):
    """Decide se uma requisição de rede pode sair do navegador.

    Aplica as camadas 1 e 3 e o bloqueio por operação do ScriptCase.
    Devolve ``True`` só quando a requisição é leitura demonstrada. Na
    dúvida, devolve ``False``.
    """
    raise NotImplementedError("Fase 0: esqueleto")


def clique_permitido(texto_elemento):
    """Decide se o coletor pode clicar num elemento (camada 2).

    Devolve ``False`` se o texto normalizado contiver qualquer termo de
    ``TEXTOS_BOTAO_BLOQUEADOS``.
    """
    raise NotImplementedError("Fase 0: esqueleto")


def instalar(contexto_playwright, registrar):
    """Instala a guarda num ``BrowserContext`` do Playwright (F2).

    Registra um ``route`` para todas as URLs que aborta o que
    ``requisicao_permitida`` recusar e chama ``registrar(evento)`` para
    cada bloqueio.
    """
    raise NotImplementedError("Fase 0: esqueleto")
