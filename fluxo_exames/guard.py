"""Guarda de somente leitura do coletor do Medicina Direta (MD).

No MD, o caminho de leitura de um laudo passa ao lado de ações de escrita e
de assinatura ("Finalizar e Assinar" no formulário e "ASSINAR PDF" na lista).
Esta guarda garante o somente leitura por mecanismo, em camadas
independentes. A política é negar por padrão: o que não foi demonstrado como
leitura na Fase 0 fica bloqueado.

Camada 1 — métodos HTTP
    ``GET``, ``HEAD`` e ``OPTIONS`` seguem para as outras checagens;
    ``POST`` vai para a camada 3; qualquer outro método é abortado no
    ``context.route`` do Playwright antes de sair do navegador.

Camada 2 — cliques
    O coletor não clica em elemento cujo texto visível (ou ``value``,
    ``title`` ou ``aria-label``) contenha uma palavra de
    ``TEXTOS_BOTAO_BLOQUEADOS``, cujo ``id`` case com
    ``IDS_ELEMENTO_BLOQUEADOS`` ou cujo ``onclick``/``href`` chame uma
    função de ``FUNCOES_JS_BLOQUEADAS``. O texto é comparado normalizado
    (sem acento, caixa alta) e por palavra inteira, para "SIM" não
    bloquear um nome como "SIMONE".

Camada 3 — POST
    Todo ``POST`` é abortado, salvo os que casam com uma entrada de
    ``POSTS_PERMITIDOS`` (host, caminho e valores exigidos no corpo). Cada
    entrada foi observada na Etapa B e traz a evidência anotada.

Valem para qualquer método, antes das camadas 1 e 3:

- ``ENDPOINTS_BLOQUEADOS``: caminhos com efeito de escrita, assinatura,
  envio ou log vistos no DOM. Alguns deles são chamados por ``GET``.
- ``OPERACOES_SCRIPTCASE_BLOQUEADAS`` e ``CHAVES_SCRIPTCASE_BLOQUEADAS``:
  parâmetros de operação do ScriptCase, lidos na query, no corpo
  urlencoded e dentro de ``nmgp_parms``.
- ``FUNCOES_AJAX_BLOQUEADAS``: valores de ``funcao`` dos endpoints
  ``blank_*_funcoes`` que gravam, enviam ou mudam configuração.

Toda requisição bloqueada é registrada. Uma tentativa de escrita registrada
conta como erro crítico no modo sombra.

Fonte: sessão da Etapa B de 26/09/2026 (``docs/FASE-0-ETAPA-B.md``). As
evidências vêm do ``rede-2026-09-26.jsonl`` e do ``rede-resumo.json`` do
gravador com ``--rede`` e das capturas HTML. Os arquivos ficam na pasta local
de capturas e não entram no repositório. Para cá vêm só caminhos e valores
de operação, sem query nem identificador de paciente.

Nesta versão, os valores de ``funcao`` liberados em ``POSTS_PERMITIDOS`` foram
deduzidos do JS das capturas, porque o gravador da sessão de 26/09 não os
registrava. Desde a Etapa B.2, o gravador registra ``funcao`` (query e corpo
urlencoded) e o ``rede-resumo.json`` agrupa por (método, caminho,
``nmgp_opcao``, ``funcao``). A fonte de evidência passa a incluir o valor de
``funcao`` gravado, e a guarda v2 poderá liberar (caminho, ``funcao``) direto
dessa evidência. As listas desta versão continuam as mesmas.

ESTADO: versão 1. ``nmgp_opcao=igual`` no formulário do laudo e o ``GET``
automático de ``blank_fecha_atendimento`` estão bloqueados **pendentes de
validação** (``OPERACOES_PENDENTES_VALIDACAO``). Com isso o formulário do laudo
fica inacessível ao coletor até a próxima sessão da Fase 0.
"""

import posixpath
import re
import unicodedata
from urllib.parse import parse_qsl, urlsplit

HOST_MD = "pep.medicinadireta.com.br"

AUSENTE = None
"""Em ``POSTS_PERMITIDOS``, indica que o parâmetro pode faltar no corpo."""

# Camada 1. POST é tratado pela camada 3; métodos fora das duas listas
# também são negados.
METODOS_HTTP_LEITURA = frozenset({"GET", "HEAD", "OPTIONS"})

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
    "TRACE",
    "CONNECT",
})

# Camada 2. Palavras ou expressões, na forma de ``normalizar_texto``; casam
# por palavra inteira ("ASSINAR" bloqueia "FINALIZAR E ASSINAR" e
# "ASSINAR PDF"). Textos vistos nos botões e links das capturas.
TEXTOS_BOTAO_BLOQUEADOS = (
    "ASSINAR",                  # "ASSINAR PDF" (2º nível), "Finalizar e Assinar" (form)
    "ASSINATURA",
    "FINALIZAR",
    "SALVAR",                   # form do laudo; "Salvar Escolhas"
    "GRAVAR",
    "EXCLUIR",
    "APAGAR",
    "REMOVER",
    "CRIAR",                    # "Criar Laudo" (2º nível)
    "NOVO",                     # form do laudo; "Integrar Omie (novo)"
    "INCLUIR",
    "ADICIONAR",
    "ALTERAR",
    "EDITAR",
    "ENVIAR",                   # "Enviar por", "Enviar Por", "Enviar para atendimento/enfermagem/triagem"
    "SOLICITAR",
    "SOLICITACAO",              # "Vincular Solicitação"
    "SOLICITACOES",
    "CONFIRMAR",
    "SIM",                      # botões de confirmação dos diálogos
    "CANCELAR",
    "DESMARCAR",
    "ACOES",                    # menu "Ações"
    "IMPRIMIR",                 # pendente: proveniência do PDF não validada (ver Etapa B)
    "E-MAIL",
    "EMAIL",
    "SMS",
    "WHATSAPP",
    "COPIAR LINK",
    "VINCULAR",
    "INTEGRAR",
    "ETIQUETA",
    "LISTA DE ESPERA",
    "ATUALIZACAO CADASTRAL",
    "INTERNO",                  # "Interno - Em Branco", "Interno - Utilizar Modelo"
    "EXTERNO",
    "UTILIZAR MODELO",
)

# Camada 2. Ids de botões de escrita do ScriptCase e do MD vistos nas capturas.
IDS_ELEMENTO_BLOQUEADOS = (
    r"^sc_b_(upd|del|new|ins)_",            # Salvar, Excluir, Novo, Incluir
    r"^sc_finalizar_assinar",
    r"^sc_imprimir_",
    r"^sc_(sms|email|copiar|copiar_link)_",
    r"^sc_btn_(novo|modelo)_",              # Criar Laudo -> Em Branco / Utilizar Modelo
    r"^sc_btgp_btn_group_",                 # grupos "Criar Laudo" e "Enviar por"
    r"^sc_vincular_solicitacao_",
    r"^id_sc_field_cmp_(assinar|editavel)_\d+$",   # ASSINAR PDF e cadeado
)

# Camada 2. Funções JS de escrita, assinatura ou envio vistas nas capturas.
FUNCOES_JS_BLOQUEADAS = (
    "nm_atualiza",                  # incluir/alterar/excluir do form ScriptCase
    "scBtnFn_sys_format_alt",
    "scBtnFn_sys_format_exc",
    "scBtnFn_sys_format_inc",
    "scBtnFn_finalizar_assinar",
    "sc_btn_finalizar_assinar",
    "fn_js_assinatura_pdf_lc",      # ASSINAR PDF no 2º nível
    "fn_js_editavel",               # cadeado: muda a editabilidade do registro
    "scBtnFn_imprimir",
    "sc_btn_imprimir",
    "scBtnFn_email",
    "scBtnFn_sms",
    "scBtnFn_copiar",
    "sc_btn_copiar",
    "abre_atendimento",
)

# Camada 3. Lista branca de POSTs observados na Etapa B e classificados como
# leitura ou estado de interface benigno. Casamento: host igual, caminho
# igual (normalizado) e, para cada chave de "exige", todas as ocorrências no
# corpo com valor na tupla (AUSENTE = a chave pode faltar).
POSTS_PERMITIDOS = (
    {
        "id": "menu_agenda",
        "host": HOST_MD,
        "caminho": "/blank_div/",
        "exige": {"nmgp_opcao": (AUSENTE, "")},
        "evidencia": "1 POST Document, status 200, ao abrir Agendamento (menu item_31 -> "
                     "menu_inicial_form_php.php -> POST automático). Resposta: página HTML "
                     "do contêiner da agenda, que carrega a grade por GET XHR.",
    },
    {
        "id": "ficha_treemenu",
        "host": HOST_MD,
        "caminho": "/blank_treemenu_paciente/",
        "exige": {"nmgp_opcao": (AUSENTE, "")},
        "evidencia": "2 POSTs Document, status 200, um por ficha aberta, logo após o GET "
                     "/treemenu_paciente/?nmgp_parms=@SC_par@... Resposta: página HTML "
                     "transitória que carrega form_paciente_sbis por GET.",
    },
    {
        "id": "sessao_limpar_apls",
        "host": HOST_MD,
        "caminho": "/blank_sessao_funcoes/blank_sessao_funcoes.php",
        "exige": {"funcao": ("limpar_sessao_aplicacoes",)},
        "evidencia": "2 POSTs XHR, status 200, um por ficha aberta. Script inline do "
                     "treemenu_paciente; limpa a sessão PHP das aplicações listadas. A "
                     "resposta é ignorada pelo JS. Estado de sessão, não de registro.",
    },
    {
        "id": "ficha_config_historico",
        "host": HOST_MD,
        "caminho": "/blank_treemenu_paciente_funcoes/blank_treemenu_paciente_funcoes.php",
        "exige": {"funcao": ("config_itens_historico",)},
        "evidencia": "2 POSTs XHR, status 200, um por ficha. Disparado no DOMContentLoaded "
                     "do treemenu_paciente; resposta JSON guardada em "
                     "top.config_treemenu_historico.",
    },
    {
        "id": "notificacao_polling",
        "host": HOST_MD,
        "caminho": "/blank_notificacao_funcoes/blank_notificacao_funcoes.php",
        "exige": {"funcao": ("qtd_novo", "cards_novos", "cards_visualizados",
                             "cards_favoritos")},
        "evidencia": "5 POSTs XHR, status 200, na carga do menu. Chamadas no topo dos "
                     "iframes blank_notificacao_icon (qtd_novo) e blank_notificacao_div "
                     "(cards_*). Respostas: número e fragmentos HTML postos via innerHTML. "
                     "O mesmo endpoint aceita alteracao_agenda, favoritar, visualizar_novos "
                     "e config_* (escrita), por isso a liberação é por valor de funcao.",
    },
    {
        "id": "home_conteudo",
        "host": HOST_MD,
        "caminho": "/blank_home_funcoes/blank_home_funcoes.php",
        "exige": {"funcao": ("m_botoes_suporte", "m_frases", "m_noticias")},
        "evidencia": "4 POSTs XHR, status 200, na carga de home.php (suporte, frases, "
                     "notícias e informativos). Respostas JSON usadas só para montar a tela.",
    },
    {
        "id": "menu_favoritos_ler",
        "host": HOST_MD,
        "caminho": "/blank_menu_inicial_funcoes/blank_menu_inicial_funcoes.php",
        "exige": {"funcao": ("m_obter_favoritos",)},
        "evidencia": "1 POST XHR, status 200, na carga do menu (obterItensFavoritados). "
                     "Resposta: lista de favoritos separada por vírgula. m_salvar_favoritos, "
                     "m_token_sessao e m_validar_senha ficam de fora.",
    },
    {
        "id": "laudo_nivel1",
        "host": HOST_MD,
        "caminho": "/grid_exames_laudo/",
        "exige": {"nmgp_opcao": (AUSENTE, "")},
        "evidencia": "2 POSTs Document, status 200, um por paciente, em Exames -> Laudo "
                     "(item_165 -> treemenu_paciente_form_php.php -> POST automático). "
                     "Resposta: grade HTML do 1º nível (atendimentos).",
    },
    {
        "id": "laudo_nivel2_container",
        "host": HOST_MD,
        "caminho": "/cont_exame_resultado_laudo/",
        "exige": {"nmgp_opcao": ("",)},
        "evidencia": "2 POSTs Document, status 200, com nmgp_opcao vazio, vindos do link "
                     "de lápis de uma linha do 1º nível (nm_gp_submit5, alvo _self). "
                     "Resposta: contêiner com dois widgets carregados por GET "
                     "(grid_paciente_exames_laudos_resultado e grid_exames_resultados_laudo).",
    },
    {
        "id": "laudo_nivel2_ancora",
        "host": HOST_MD,
        "caminho": "/grid_paciente_exames_laudos_resultado/index.php",
        "exige": {"nmgp_opcao": ("ajax_save_ancor",)},
        "evidencia": "6 POSTs XHR, status 200 (o status está no jsonl; o resumo "
                     "reconstruído o perdeu). ajax_save_ancor('F3', ancora) roda dentro de "
                     "nm_gp_submit4 antes de submeter F3 e guarda na sessão a linha clicada "
                     "(âncora 1, 2, 3) para a grade voltar a ela. As grades de 1º e 2º nível "
                     "ficaram idênticas antes e depois. Estado de interface na sessão.",
    },
    {
        "id": "laudo_nivel2_retorno",
        "host": HOST_MD,
        "caminho": "/grid_paciente_exames_laudos_resultado/",
        "exige": {"nmgp_opcao": (AUSENTE,)},
        "evidencia": "6 POSTs Document, status 200, sem nmgp_opcao, logo após cada "
                     "form_..._fim.php. Resposta: grade do 2º nível recarregada.",
    },
    {
        "id": "laudo_form_sair",
        "host": HOST_MD,
        "caminho": "/form_paciente_exames_laudos_resultado/"
                   "form_paciente_exames_laudos_resultado_fim.php",
        "exige": {"nmgp_opcao": (AUSENTE,)},
        "evidencia": "6 POSTs Document, status 200, pelo botão Voltar do form "
                     "(scFormClose_F6: form F6 só com script_case_init). Encerra a "
                     "instância do form e devolve para a grade. Só é alcançável depois de "
                     "nmgp_opcao=igual, hoje bloqueado.",
    },
)

# Operações do ScriptCase que gravam, disparam código PHP do botão ou recarregam
# um formulário em edição. Valem na query, no corpo e dentro de nmgp_parms.
OPERACOES_SCRIPTCASE_BLOQUEADAS = {
    "nmgp_opcao": (
        "incluir",          # nm_atualiza('incluir')
        "alterar",          # nm_atualiza('alterar'), botão Salvar
        "excluir",          # nm_atualiza('excluir'), botão Excluir
        "novo",             # nm_move('novo'), botão Novo
        "formphp",          # botões PHP (E-MAIL, SMS, Imprimir) via nmgp_parms
        "recarga",
        "recarga_mobile",
        "muda_form",
        "igual",            # PENDENTE: abrir o form do laudo (ver OPERACOES_PENDENTES_VALIDACAO)
    ),
}

# Chaves que bloqueiam com qualquer valor não vazio.
CHAVES_SCRIPTCASE_BLOQUEADAS = (
    "rs",           # sajax: eventos AJAX, validações e submit_form do form (GET ou POST)
    "rsargs[]",
    "nm_call_php",  # botão PHP do form: email, sms, imprimir_normal
    "nmgp_clone",   # clonar registro
)

# Valores de "funcao" dos endpoints blank_*_funcoes vistos no DOM com efeito
# de escrita, envio ou configuração. O deny-by-default já os bloqueia; a
# lista explícita vale também para endpoints liberados e documenta o risco.
FUNCOES_AJAX_BLOQUEADAS = frozenset(f.lower() for f in (
    "alteracao_agenda", "alterar_status", "favoritar", "visualizar_novos", "card",
    "config_permite_audio", "config_permite_card", "config_modelo",
    "m_salvar_favoritos", "m_token_sessao", "m_validar_senha",
    "gerar_link", "abrir_lembrete", "copiar_link", "log_copy",
    "sms", "email", "whatsapp", "enviar_sms", "enviar_email", "enviar_whatsapp",
    "gerar_atualizacao_cadastral", "incluir_atualizacao_cadastral",
    "novo_cliente", "UpsertCliente", "atualizar_cliente",
    "relacionar_ids_cliente_paciente", "AssociarCodIntCliente",
))

# Caminhos (prefixo, após normalização) bloqueados em qualquer método.
ENDPOINTS_BLOQUEADOS = (
    "/blank_fecha_atendimento/",        # PENDENTE: GET automático tipo=t ao abrir a 2ª ficha
    "/blank_menu_atendimento/",         # abre atendimento
    "/blank_editavel/",                 # cadeado: fecha/abre o registro
    "/blank_registro_em_aberto_ajax/",
    "/blank_assinatura_digital/",
    "/blank_assinar_pdf/",
    "/blank_validar_xml_assinado/",
    "/_lib/libraries/grp/assinatura_receita/",
    "/blank_laudo_pdf/",                # gera o PDF para assinatura; pendente (item 5 da Etapa B)
    "/blank_receita/",
    "/blank_receita_livre/",
    "/blank_receita_funcoes/",
    "/blank_oftalmo_oculos_pdf/",
    "/blank_oftalmo_funcoes/",
    "/blank_mover_pdf/",
    "/blank_desmarcar/",
    "/blank_status/",
    "/blank_retirar_lista_espera/",
    "/blank_atualiza_dados_paciente/",
    "/blank_videochamada_funcoes/",
    "/blank_questionario_funcoes/",
    "/blank_quest_config_funcoes/",
    "/blank_omie_funcoes/",
    "/blank_doctoralia_funcoes/",
    "/blank_doctoralia_integracao_funcoes/",
    "/blank_integracao_agora/",
    "/blank_log_personalizado/",        # grava log por GET (p_action=...)
)

# Bloqueados, mas com efeito real a confirmar na próxima sessão da Fase 0.
OPERACOES_PENDENTES_VALIDACAO = (
    {
        "operacao": "POST /form_paciente_exames_laudos_resultado/ nmgp_opcao=igual",
        "motivo": "No ScriptCase, 'igual' carrega o registro pela chave, sem gravar (é o "
                  "padrão de nm_gp_submit4 quando o link não traz opção). As grades de 1º e "
                  "2º nível ficaram idênticas depois das 6 aberturas. Mas o form abre em "
                  "modo Atualização, com campos editáveis e 'Finalizar e Assinar' visível, "
                  "e o evento onLoad do servidor não é observável. Dúvida razoável: "
                  "bloqueado.",
        "validar": "Abrir 1 laudo do paciente A e conferir, antes e depois, as grades e o "
                   "histórico de alterações do registro (se o MD mostrar). Procurar uma "
                   "via só de leitura (form_visualizar_exames_resultados, Imprimir).",
    },
    {
        "operacao": "GET /blank_fecha_atendimento/blank_fecha_atendimento.php?tipo=t",
        "motivo": "Emitido sozinho, pelo HTML do treemenu, ao abrir a ficha do 2º "
                  "paciente. O nome indica que fecha um atendimento; o coletor nunca abre "
                  "atendimento, e fechar o do Ivson em outra sessão seria efeito colateral.",
        "validar": "Ver se bloquear a chamada altera o comportamento da ficha seguinte.",
    },
    {
        "operacao": "POST /blank_notifica_lembrete/blank_notifica_lembrete.php",
        "motivo": "2 POSTs automáticos na abertura da ficha (ids de organização, usuário "
                  "e paciente). A resposta vira notificação na tela; não se sabe se o "
                  "servidor grava algo. Não é necessário à leitura: fica fora da lista "
                  "branca.",
        "validar": "Só se o bloqueio atrapalhar a navegação.",
    },
)


class EscritaBloqueada(Exception):
    """Levantada quando o coletor tenta uma operação que a guarda bloqueia."""


def normalizar_texto(texto):
    """Remove acentos, junta espaços e passa para caixa alta.

    Pontuação vira espaço ("E-MAIL" -> "E MAIL"). É a forma usada para
    comparar textos de botão com ``TEXTOS_BOTAO_BLOQUEADOS``.
    """
    if texto is None:
        return ""
    decomposto = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^0-9A-Za-z]+", " ", sem_acento).upper().split())


_TERMOS_BLOQUEADOS = tuple(normalizar_texto(t) for t in TEXTOS_BOTAO_BLOQUEADOS)
_IDS_BLOQUEADOS = tuple(re.compile(p, re.IGNORECASE) for p in IDS_ELEMENTO_BLOQUEADOS)
_FUNCOES_JS = re.compile(r"\b(%s)\w*\s*\(" % "|".join(map(re.escape, FUNCOES_JS_BLOQUEADAS)))


def _normalizar_caminho(caminho):
    """Resolve ``.``, ``..`` e barras duplas, mantendo a barra final."""
    caminho = caminho or "/"
    normal = posixpath.normpath("/" + caminho.lstrip("/")).replace("//", "/")
    if caminho.endswith("/") and not normal.endswith("/"):
        normal += "/"
    return normal.lower()


CORPO_ILEGIVEL = object()
"""Corpo que existe mas não pôde ser lido; num POST, a requisição é negada."""


def _texto_do_corpo(corpo):
    """Texto do corpo, ``None`` se não há corpo; ``ValueError`` se ilegível."""
    if corpo is None:
        return None
    if corpo is CORPO_ILEGIVEL:
        raise ValueError("corpo ilegível")
    if isinstance(corpo, (bytes, bytearray)):
        return bytes(corpo).decode("utf-8")   # UnicodeDecodeError é ValueError
    return str(corpo)


def _corpo_urlencoded(texto, tipo_corpo):
    """Lista de pares do corpo, ou ``None`` se o formato não for analisável."""
    if texto is None or texto == "":
        return []
    tipo = (tipo_corpo or "").lower()
    if tipo and "application/x-www-form-urlencoded" not in tipo:
        return None
    inicio = texto.lstrip()[:2]
    if inicio.startswith(("{", "[")) or inicio == "--":
        return None
    return parse_qsl(texto, keep_blank_values=True)


def _pares_de_nmgp_parms(valor):
    """Pares embutidos em ``nmgp_parms`` (formatos ``?#?``/``?@?`` e ``*scin``/``*scout``).

    O formato ``@SC_par@<init>@SC_par@<apl>@SC_par@<md5>`` só referencia a
    sessão e não traz pares.
    """
    pares = []
    for sep_item, sep_par in (("?@?", "?#?"), ("*scout", "*scin")):
        if sep_par in valor:
            for item in valor.split(sep_item):
                if sep_par in item:
                    chave, _, v = item.partition(sep_par)
                    pares.append((chave, v))
    return pares


def _operacao_bloqueada(pares):
    """Motivo do bloqueio por parâmetro de operação, ou ``None``."""
    expandidos = list(pares)
    for chave, valor in pares:
        if chave.lower() == "nmgp_parms":
            expandidos.extend(_pares_de_nmgp_parms(valor))
    for chave, valor in expandidos:
        k = chave.strip().lower()
        v = valor.strip().lower()
        if k in OPERACOES_SCRIPTCASE_BLOQUEADAS and v in OPERACOES_SCRIPTCASE_BLOQUEADAS[k]:
            return "operacao:%s=%s" % (k, v)
        if k in CHAVES_SCRIPTCASE_BLOQUEADAS and v:
            return "operacao:%s" % k
        if k == "funcao" and v in FUNCOES_AJAX_BLOQUEADAS:
            return "funcao:%s" % v
    return None


def _casa_entrada(entrada, host, caminho, pares):
    if host != entrada["host"] or caminho != _normalizar_caminho(entrada["caminho"]):
        return False
    for chave, permitidos in entrada["exige"].items():
        valores = [v for k, v in pares if k == chave]
        if not valores:
            if AUSENTE not in permitidos:
                return False
        elif any(v not in permitidos for v in valores):
            return False
    return True


def avaliar_requisicao(metodo, url, corpo=None, tipo_corpo=None):
    """Decide sobre uma requisição e devolve ``(permitida, motivo)``.

    ``motivo`` é um código curto, sem query nem dado de paciente, próprio
    para o registro de bloqueios.
    """
    metodo = (metodo or "").upper()
    if metodo in METODOS_HTTP_BLOQUEADOS:
        return False, "metodo:%s" % metodo
    if metodo not in METODOS_HTTP_LEITURA and metodo != "POST":
        return False, "metodo_desconhecido:%s" % metodo

    partes = urlsplit(url or "")
    host = (partes.hostname or "").lower()
    caminho = _normalizar_caminho(partes.path)

    for prefixo in ENDPOINTS_BLOQUEADOS:
        if caminho.startswith(prefixo.lower()):
            return False, "endpoint:%s" % prefixo

    pares = parse_qsl(partes.query, keep_blank_values=True)
    corpo_pares = []
    if metodo == "POST":
        try:
            corpo_pares = _corpo_urlencoded(_texto_do_corpo(corpo), tipo_corpo)
        except ValueError:
            corpo_pares = None
        if corpo_pares is None:
            return False, "corpo_nao_analisavel"
    motivo = _operacao_bloqueada(pares + corpo_pares)
    if motivo:
        return False, motivo

    if metodo in METODOS_HTTP_LEITURA:
        return True, "leitura:%s" % metodo

    for entrada in POSTS_PERMITIDOS:
        if _casa_entrada(entrada, host, caminho, corpo_pares):
            return True, "post_permitido:%s" % entrada["id"]
    return False, "post_nao_listado"


def requisicao_permitida(metodo, url, corpo=None, tipo_corpo=None):
    """Decide se uma requisição de rede pode sair do navegador.

    Aplica as camadas 1 e 3 e os bloqueios por endpoint e por operação.
    Devolve ``True`` só quando a requisição é leitura demonstrada. Na
    dúvida, devolve ``False``.
    """
    return avaliar_requisicao(metodo, url, corpo, tipo_corpo)[0]


def clique_permitido(texto_elemento, id_elemento=None, onclick=None):
    """Decide se o coletor pode clicar num elemento (camada 2).

    ``texto_elemento`` é uma string ou uma sequência de strings (texto
    visível, ``value``, ``title``, ``aria-label``). ``onclick`` pode trazer
    também o ``href`` ``javascript:``. Devolve ``False`` se qualquer texto
    contiver um termo de ``TEXTOS_BOTAO_BLOQUEADOS`` como palavra inteira, se
    o id casar com ``IDS_ELEMENTO_BLOQUEADOS`` ou se o código chamar uma
    função de ``FUNCOES_JS_BLOQUEADAS``.
    """
    if texto_elemento is None:
        textos = ()
    elif isinstance(texto_elemento, str):
        textos = (texto_elemento,)
    else:
        textos = tuple(texto_elemento)
    for texto in textos:
        alvo = " %s " % normalizar_texto(texto)
        if any(" %s " % termo in alvo for termo in _TERMOS_BLOQUEADOS):
            return False
    if id_elemento and any(p.search(id_elemento) for p in _IDS_BLOQUEADOS):
        return False
    if onclick and _FUNCOES_JS.search(onclick):
        return False
    return True


def instalar(contexto_playwright, registrar):
    """Instala a guarda num ``BrowserContext`` do Playwright (F2).

    Registra um ``route`` para todas as URLs que aborta o que
    ``avaliar_requisicao`` recusar e chama ``registrar(evento)`` para cada
    bloqueio. O evento leva método, host, caminho e motivo, nunca a query
    nem o corpo.

    Instale depois do login manual: ``login_sha`` e ``login_autenticar`` não
    estão na lista branca. Crie o contexto com ``service_workers="block"``,
    porque o ``route`` não vê requisições de service worker. WebSocket
    também não passa pelo ``route``; o MD usa um só para o chat de terceiros.
    """
    def _rota(route, request):
        try:
            corpo = request.post_data_buffer
        except Exception:
            corpo = CORPO_ILEGIVEL
        tipo = (request.headers or {}).get("content-type")
        permitida, motivo = avaliar_requisicao(request.method, request.url, corpo, tipo)
        if permitida:
            route.continue_()
            return
        partes = urlsplit(request.url)
        registrar({
            "metodo": request.method,
            "host": partes.hostname or "",
            "caminho": partes.path,
            "motivo": motivo,
        })
        route.abort("blockedbyclient")

    contexto_playwright.route("**/*", _rota)
