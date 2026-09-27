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
    entrada foi observada na Fase 0 e traz a evidência anotada.

Valem para qualquer método, antes das camadas 1 e 3:

- ``ENDPOINTS_BLOQUEADOS``: caminhos com efeito de escrita, assinatura,
  envio ou log vistos no DOM ou na rede. Alguns deles são chamados por ``GET``.
- ``ENDPOINTS_PENDENTES_VALIDACAO``: formulários que abrem registro em modo
  de edição e ainda não têm evidência suficiente de leitura.
- ``OPERACOES_SCRIPTCASE_BLOQUEADAS`` e ``CHAVES_SCRIPTCASE_BLOQUEADAS``:
  parâmetros de operação do ScriptCase, lidos na query, no corpo
  urlencoded e dentro de ``nmgp_parms``. Uma entrada de ``POSTS_PERMITIDOS``
  pode liberar um valor bloqueado só no seu caminho, pelo campo ``libera``.
- ``FUNCOES_AJAX_BLOQUEADAS`` e ``ACOES_AJAX_BLOQUEADAS``: valores de
  ``funcao`` e ``acao`` dos endpoints ``blank_*_funcoes`` que gravam, enviam
  ou mudam configuração.

Toda requisição bloqueada é registrada. Uma tentativa de escrita registrada
conta como erro crítico no modo sombra.

Fontes: sessão da Etapa B (26/09/2026) e sessão da Etapa C (27/09/2026), em
``docs/FASE-0-ETAPA-B.md`` e ``docs/FASE-0-ETAPA-C.md``. As evidências vêm dos
``rede-AAAA-MM-DD.jsonl`` e do ``rede-resumo.json`` do gravador com
``--rede`` e das capturas HTML. Os arquivos ficam na pasta local de capturas e
não entram no repositório. Para cá vêm só caminhos e valores de operação, sem
query nem identificador de paciente.

Desde a Etapa C, os valores de ``funcao`` liberados em ``POSTS_PERMITIDOS``
são os gravados pelo gravador (``funcao_corpo`` no jsonl, chave
``funcao`` do resumo), e não mais os deduzidos do JS. Onde o gravador não vê o
bastante (a chave ``acao``), a entrada exige também o valor lido no JS da
página, o que só estreita a liberação.

ESTADO: versão 2. Decisões da v1 alteradas com evidência da sessão da Etapa C
(marcadas "ALTERADO v1→v2" na evidência de cada entrada):

- ``nmgp_opcao=igual`` no formulário do laudo passou de pendente a liberado,
  só nesse caminho (entrada ``laudo_form_abrir``).
- ``m_obter_favoritos`` saiu da lista branca: não foi gravado em nenhuma
  sessão. O POST automático do menu é ``m_token_sessao``.
- ``m_token_sessao`` saiu de ``FUNCOES_AJAX_BLOQUEADAS`` e foi liberado só com
  ``acao=consultar``; ``acao=alterar_sessao_ativa`` segue bloqueado.

Continuam pendentes (``OPERACOES_PENDENTES_VALIDACAO``) o ``GET`` automático de
``blank_fecha_atendimento``, os formulários de Resultado e de Evolução, o PDF
do laudo (``blank_laudo_pdf``) e a pesquisa do questionário.
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
    "EXCLUIR",                  # "Excluir", "Excluir Selecionados" (anexos)
    "APAGAR",
    "REMOVER",
    "INATIVAR",
    "CRIAR",                    # "Criar Laudo" (2º nível)
    "NOVO",                     # form do laudo; "Novo Documento"; "Integrar Omie (novo)"
    "INCLUIR",
    "ADICIONAR",
    "ALTERAR",
    "EDITAR",
    "REFAZER",                  # form da Evolução -> ctr_editar_item_soap
    "UPLOAD",                   # "Upload Imagem" (anexos)
    "ENVIAR",                   # "Enviar por", "Enviar Por", "Enviar para atendimento/enfermagem/triagem"
    "SOLICITAR",
    "SOLICITACAO",              # "Vincular Solicitação"
    "SOLICITACOES",
    "CONFIRMAR",
    "SIM",                      # botões de confirmação dos diálogos
    "CANCELAR",
    "DESMARCAR",
    "ACOES",                    # menu "Ações"
    "IMPRIMIR",                 # laudo: formphp + blank_laudo_pdf; Evolução: log "print"
    "E-MAIL",
    "EMAIL",
    "SMS",
    "WHATSAPP",
    "COPIAR",                   # "COPIAR LINK"; "Copiar" da Evolução (blank_copiar_dados)
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
    r"^sc_btn_(btn_)?imprimir_",            # Imprimir da Evolução
    r"^sc_(sms|email|copiar|copiar_link)_",
    r"^sc_btn_(novo|modelo)_",              # Criar Laudo -> Em Branco / Utilizar Modelo
    r"^sc_btn_(novo_mult|novo1|excluir)_",  # anexos e Evolução
    r"^sc_(refazer|inativar)_",             # form da Evolução e de Resultado
    r"^sc_btgp_btn_group_",                 # grupos "Criar Laudo" e "Enviar por"
    r"^sc_vincular_solicitacao_",
    r"^id_sc_field_cmp_(assinar|editavel|copiar)_\d+$",   # ASSINAR PDF, cadeado, Copiar
)

# Camada 2. Funções JS de escrita, assinatura ou envio vistas nas capturas.
FUNCOES_JS_BLOQUEADAS = (
    "nm_atualiza",                  # incluir/alterar/excluir do form ScriptCase
    "scBtnFn_sys_format_alt",
    "scBtnFn_sys_format_exc",
    "scBtnFn_sys_format_inc",
    "scBtnFn_finalizar_assinar",
    "sc_btn_finalizar_assinar",
    "fn_js_assinatura_pdf",         # ASSINAR PDF no 2º nível (fn_js_assinatura_pdf_lc)
    "mdPepOpenCertificates",        # modal do certificado de assinatura
    "fn_js_editavel",               # cadeado: muda a editabilidade do registro
    "scBtnFn_imprimir",
    "sc_btn_imprimir",
    "scBtnFn_btn_imprimir",
    "sc_btn_btn_imprimir",
    "m_js_imprimir",                # Imprimir do questionário
    "scBtnFn_refazer",
    "sc_btn_refazer",
    "scBtnFn_inativar",
    "sc_btn_inativar",
    "scBtnFn_email",
    "scBtnFn_sms",
    "scBtnFn_copiar",
    "sc_btn_copiar",
    "abre_atendimento",
)

# Camada 3. Lista branca de POSTs observados na Fase 0 e classificados como
# leitura ou estado de interface benigno. Casamento: host igual, caminho
# igual (normalizado) e, para cada chave de "exige", todas as ocorrências no
# corpo com valor na tupla (AUSENTE = a chave pode faltar). "libera" lista os
# valores de "exige" que, só nesse caminho, deixam de ser operação bloqueada.
# Contagens: "B" é a sessão de 26/09, "C" a de 27/09 (requisições no jsonl).
POSTS_PERMITIDOS = (
    {
        "id": "menu_agenda",
        "host": HOST_MD,
        "caminho": "/blank_div/",
        "exige": {"nmgp_opcao": (AUSENTE, "")},
        "evidencia": "B 1, C 1 POST Document, status 200, ao abrir Agendamento (menu "
                     "item_31 -> menu_inicial_form_php.php -> POST automático). Resposta: "
                     "página HTML do contêiner da agenda, que carrega a grade por GET XHR.",
    },
    {
        "id": "ficha_treemenu",
        "host": HOST_MD,
        "caminho": "/blank_treemenu_paciente/",
        "exige": {"nmgp_opcao": (AUSENTE, "")},
        "evidencia": "B 2, C 1 POST Document, status 200, um por ficha aberta, logo após o "
                     "GET /treemenu_paciente/?nmgp_parms=@SC_par@... Resposta: página HTML "
                     "transitória que carrega form_paciente_sbis por GET.",
    },
    {
        "id": "sessao_limpar_apls",
        "host": HOST_MD,
        "caminho": "/blank_sessao_funcoes/blank_sessao_funcoes.php",
        "exige": {"funcao": ("limpar_sessao_aplicacoes",)},
        "evidencia": "funcao gravada (C 1 POST XHR, status 200; B 2). Script inline do "
                     "treemenu_paciente; limpa a sessão PHP das aplicações listadas. A "
                     "resposta é ignorada pelo JS. Estado de sessão, não de registro.",
    },
    {
        "id": "ficha_config_historico",
        "host": HOST_MD,
        "caminho": "/blank_treemenu_paciente_funcoes/blank_treemenu_paciente_funcoes.php",
        "exige": {"funcao": ("config_itens_historico",)},
        "evidencia": "funcao gravada (C 1 POST XHR, status 200; B 2). Disparado no "
                     "DOMContentLoaded do treemenu_paciente; resposta JSON guardada em "
                     "top.config_treemenu_historico.",
    },
    {
        "id": "notificacao_polling",
        "host": HOST_MD,
        "caminho": "/blank_notificacao_funcoes/blank_notificacao_funcoes.php",
        "exige": {"funcao": ("qtd_novo", "cards_novos", "cards_visualizados",
                             "cards_favoritos")},
        "evidencia": "funcao gravada: C 1 POST XHR de cada valor, status 200, na carga do "
                     "menu (iframes blank_notificacao_icon e _div). Respostas: número e "
                     "fragmentos HTML postos via innerHTML. O mesmo endpoint aceita "
                     "alteracao_agenda, favoritar, visualizar_novos e config_* (escrita), "
                     "por isso a liberação é por valor de funcao.",
    },
    {
        "id": "notificacao_sala",
        "host": HOST_MD,
        "caminho": "/blank_notificacao_funcoes/blank_notificacao_funcoes.php",
        "exige": {"funcao": ("buscar_sala_usuario",)},
        "evidencia": "funcao gravada: C 1 POST XHR, status 200, na carga do menu (era o 5º "
                     "POST sem valor da sessão B). Script do menu_inicial: a resposta JSON é "
                     "a lista de salas que o JS usa em socket.emit('entrar'). Leitura; o "
                     "WebSocket de notificações não passa pelo route.",
    },
    {
        "id": "home_conteudo",
        "host": HOST_MD,
        "caminho": "/blank_home_funcoes/blank_home_funcoes.php",
        "exige": {"funcao": ("m_botoes_suporte", "m_frases", "m_noticias")},
        "evidencia": "funcao gravada: C 4 POSTs XHR (m_botoes_suporte 1, m_frases 1, "
                     "m_noticias 2), status 200, na carga de home.php. Respostas JSON usadas "
                     "só para montar a tela.",
    },
    {
        "id": "menu_sessao_consultar",
        "host": HOST_MD,
        "caminho": "/blank_menu_inicial_funcoes/blank_menu_inicial_funcoes.php",
        "exige": {"funcao": ("m_token_sessao",), "acao": ("consultar",)},
        "evidencia": "ALTERADO v1→v2. funcao gravada: C 1 POST XHR m_token_sessao, status "
                     "200, na carga do menu; é o único POST automático desse endpoint nas "
                     "duas sessões (a v1 tinha deduzido m_obter_favoritos, nunca gravado). No "
                     "JS, a chamada da carga (verificaSessaoAtiva) e o keepalive "
                     "(renovaSessaoPHP) mandam acao=consultar; acao=alterar_sessao_ativa "
                     "(bloqueio por inatividade) é escrita e fica de fora. O gravador não "
                     "grava acao, por isso a entrada exige o valor lido no JS.",
    },
    {
        "id": "laudo_nivel1",
        "host": HOST_MD,
        "caminho": "/grid_exames_laudo/",
        "exige": {"nmgp_opcao": (AUSENTE, "")},
        "evidencia": "B 2, C 1 POST Document, status 200, um por paciente, em Exames -> "
                     "Laudo (item_165 -> treemenu_paciente_form_php.php -> POST automático). "
                     "Resposta: grade HTML do 1º nível (atendimentos).",
    },
    {
        "id": "laudo_nivel2_container",
        "host": HOST_MD,
        "caminho": "/cont_exame_resultado_laudo/",
        "exige": {"nmgp_opcao": ("",)},
        "evidencia": "B 2, C 2 POSTs Document, status 200, com nmgp_opcao vazio, vindos do "
                     "link de lápis de uma linha do 1º nível (nm_gp_submit5, alvo _self). "
                     "Resposta: contêiner com dois widgets carregados por GET "
                     "(grid_paciente_exames_laudos_resultado e grid_exames_resultados_laudo).",
    },
    {
        "id": "laudo_nivel2_ancora",
        "host": HOST_MD,
        "caminho": "/grid_paciente_exames_laudos_resultado/index.php",
        "exige": {"nmgp_opcao": ("ajax_save_ancor",)},
        "evidencia": "B 6, C 6 POSTs XHR, status 200. ajax_save_ancor('F3', ancora) roda "
                     "dentro de nm_gp_submit4 antes de submeter F3 e guarda na sessão a "
                     "linha clicada (âncora 1, 2, 3) para a grade voltar a ela. As grades de "
                     "1º e 2º nível ficaram idênticas antes e depois nas duas sessões. "
                     "Estado de interface na sessão.",
    },
    {
        "id": "laudo_form_abrir",
        "host": HOST_MD,
        "caminho": "/form_paciente_exames_laudos_resultado/",
        "exige": {"nmgp_opcao": ("igual",)},
        "libera": {"nmgp_opcao": ("igual",)},
        "evidencia": "ALTERADO v1→v2 (era pendente). B 6, C 6 POSTs Document, status 200, "
                     "vindos de nm_gp_submit4 (F3). Na sessão C, 3 laudos foram abertos 2 "
                     "vezes cada: o texto (textarea receituario) saiu idêntico byte a byte "
                     "entre as aberturas e os campos de F1 só mudaram em tokens de sessão. "
                     "As grades de 1º e 2º nível ficaram idênticas campo a campo antes e "
                     "depois ('Registros em Aberto', 'PDF Assinado', versão do atendimento, "
                     "cadeado e data/hora de 'Abertura do Registro'). A carga do form não "
                     "dispara XHR nem POST. Liberado só aqui; em qualquer outro caminho "
                     "'igual' segue bloqueado.",
    },
    {
        "id": "laudo_nivel2_retorno",
        "host": HOST_MD,
        "caminho": "/grid_paciente_exames_laudos_resultado/",
        "exige": {"nmgp_opcao": (AUSENTE,)},
        "evidencia": "B 6, C 5 POSTs Document, status 200, sem nmgp_opcao, logo após cada "
                     "form_..._fim.php. Resposta: grade do 2º nível recarregada.",
    },
    {
        "id": "laudo_form_sair",
        "host": HOST_MD,
        "caminho": "/form_paciente_exames_laudos_resultado/"
                   "form_paciente_exames_laudos_resultado_fim.php",
        "exige": {"nmgp_opcao": (AUSENTE,)},
        "evidencia": "B 6, C 5 POSTs Document, status 200, pelo botão Voltar do form "
                     "(scFormClose_F6: form F6 só com script_case_init). Encerra a "
                     "instância do form e devolve para a grade.",
    },
    {
        "id": "resultado_lista",
        "host": HOST_MD,
        "caminho": "/grid_exames_resultados/",
        "exige": {"nmgp_opcao": (AUSENTE,)},
        "evidencia": "C 3 POSTs Document, status 200: 1 do menu Exames -> Resultado "
                     "(item_164) e 2 de volta do form. Resposta: grade 'Relatório de "
                     "tbl_exames_resultados' (ID, Atend., Data Evento, Título, Exames "
                     "Solicitados, Arquivo, Status, Profissional). Grade idêntica campo a "
                     "campo antes e depois das 2 aberturas do form.",
    },
    {
        "id": "questionario_tela",
        "host": HOST_MD,
        "caminho": "/ctr_quest_rel_acompanhar/",
        "exige": {"nmgp_opcao": (AUSENTE,)},
        "evidencia": "C 1 POST Document, status 200, do menu da ficha (item_218). Resposta: "
                     "controle 'Questionário - Acompanhar' (filtros questionário, datas, "
                     "Exibir Sessão/Pontuação) com o iframe blank_quest_rel_acompanhar por "
                     "GET. Só a tela: a pesquisa (blank_quest_config_funcoes, "
                     "rel_dados_acompanhar) não foi feita e segue bloqueada.",
    },
    {
        "id": "anexo_documentos",
        "host": HOST_MD,
        "caminho": "/grid_tbl_paciente_crm_anexo_doc/",
        "exige": {"nmgp_opcao": (AUSENTE,)},
        "evidencia": "C 1 POST Document, status 200, do menu da ficha (item_26). Resposta: "
                     "grade 'Anexo - Documentos' (vazia para o paciente A). Botões Novo "
                     "Documento e Excluir Selecionados ficam na camada 2.",
    },
    {
        "id": "anexo_imagens",
        "host": HOST_MD,
        "caminho": "/grid_tbl_paciente_crm_anexo_img/",
        "exige": {"nmgp_opcao": (AUSENTE,)},
        "evidencia": "C 1 POST Document, status 200, do menu da ficha (item_106). Resposta: "
                     "grade 'Anexo - Imagens' (vazia). Upload Imagem e Excluir Selecionados "
                     "ficam na camada 2.",
    },
    {
        "id": "evolucao_lista",
        "host": HOST_MD,
        "caminho": "/grid_tbl_pacientes_crm/",
        "exige": {"nmgp_opcao": (AUSENTE,)},
        "evidencia": "C 1 POST Document, status 200, do menu Evolução (item_19). Resposta: "
                     "grade 'Andamento' (ID, Atend., Data Evento, Título, Profissional). O "
                     "questionário pré-exame respondido pelo paciente aparece aqui como "
                     "registro de Evolução; abrir o registro segue pendente.",
    },
)

# Operações do ScriptCase que gravam, disparam código PHP do botão, recarregam
# um formulário em edição ou exportam/imprimem. Valem na query, no corpo e
# dentro de nmgp_parms.
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
        "igual",            # abre registro pela chave; liberado só em laudo_form_abrir
        "print",            # impressão de grade (grid_evolucao_imp): grava log "print"
        "pdf",              # exportações de grade: geram arquivo no servidor
        "xls",
        "xlsx",
        "csv",
        "xml",
        "rtf",
        "word",
    ),
}

# Chaves que bloqueiam com qualquer valor não vazio.
CHAVES_SCRIPTCASE_BLOQUEADAS = (
    "rs",           # sajax: eventos AJAX, validações e submit_form do form (GET ou POST)
    "rsargs[]",
    "nm_call_php",  # botão PHP do form: email, sms, imprimir_normal
    "nmgp_clone",   # clonar registro
    "assinar",      # blank_laudo_pdf.php?assinar=S: gera o PDF para assinatura
)

# Valores de "funcao" dos endpoints blank_*_funcoes vistos no DOM com efeito
# de escrita, envio ou configuração. O deny-by-default já os bloqueia; a
# lista explícita vale também para endpoints liberados e documenta o risco.
FUNCOES_AJAX_BLOQUEADAS = frozenset(f.lower() for f in (
    "alteracao_agenda", "alterar_status", "favoritar", "visualizar_novos", "card",
    "config_permite_audio", "config_permite_card", "config_modelo",
    "m_salvar_favoritos", "m_validar_senha",
    "gerar_link", "abrir_lembrete", "copiar_link", "log_copy",
    "sms", "email", "whatsapp", "enviar_sms", "enviar_email", "enviar_whatsapp",
    "gerar_atualizacao_cadastral", "incluir_atualizacao_cadastral",
    "novo_cliente", "UpsertCliente", "atualizar_cliente",
    "relacionar_ids_cliente_paciente", "AssociarCodIntCliente",
))

# Valores de "acao" com efeito de escrita. m_token_sessao com
# alterar_sessao_ativa liga/desliga o bloqueio de inatividade da sessão.
ACOES_AJAX_BLOQUEADAS = frozenset({"alterar_sessao_ativa"})

# Caminhos (prefixo, após normalização) bloqueados em qualquer método.
ENDPOINTS_BLOQUEADOS = (
    "/blank_fecha_atendimento/",        # PENDENTE: GET automático tipo=t ao abrir a 2ª ficha
    "/blank_menu_atendimento/",         # abre atendimento
    "/blank_editavel/",                 # cadeado: fecha/abre o registro
    "/blank_registro_em_aberto_ajax/",
    "/blank_assinatura_digital/",       # 1º passo do ASSINAR PDF (visto na sessão C)
    "/blank_assinar_pdf/",
    "/blank_validar_xml_assinado/",
    "/_lib/libraries/grp/assinatura_receita/",
    "/blank_laudo_pdf/",                # PDF do laudo: gera arquivo para assinatura (ver Etapa C)
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
    "/blank_quest_config_funcoes/",     # PENDENTE: pesquisa do questionário (rel_dados_acompanhar)
    "/blank_quest_acompanhar_pdf/",     # Imprimir do questionário
    "/blank_omie_funcoes/",
    "/blank_doctoralia_funcoes/",
    "/blank_doctoralia_integracao_funcoes/",
    "/blank_integracao_agora/",
    "/blank_log_personalizado/",        # grava log por GET (p_action=print, expired...)
    "/grid_evolucao_imp/",              # impressão da Evolução: dispara o log "print"
    "/form_log_inativar/",              # Excluir da Evolução (inativa o registro)
    "/ctr_editar_item_soap/",           # Refazer da Evolução
    "/blank_copiar_dados/",             # Copiar da Evolução
)

# Formulários que abrem um registro em modo de edição ("Atualização") e ainda
# não têm evidência suficiente de leitura. Bloqueados em qualquer método.
ENDPOINTS_PENDENTES_VALIDACAO = (
    "/form_exames_resultados/",
    "/form_tbl_pacientes_crm_editavel/",
)

# Bloqueados, mas com efeito real a confirmar numa próxima sessão da Fase 0.
OPERACOES_PENDENTES_VALIDACAO = (
    {
        "operacao": "GET /blank_fecha_atendimento/blank_fecha_atendimento.php?tipo=t",
        "motivo": "Emitido sozinho, pelo HTML do treemenu, ao abrir a ficha do 2º "
                  "paciente (sessão B). A sessão C abriu uma ficha só e não o reproduziu. "
                  "O nome indica que fecha um atendimento; fechar o do Ivson em outra "
                  "sessão seria efeito colateral.",
        "validar": "Abrir duas fichas seguidas com a guarda instalada e ver se o bloqueio "
                   "altera o comportamento da segunda.",
    },
    {
        "operacao": "POST /blank_notifica_lembrete/blank_notifica_lembrete.php",
        "motivo": "Automático na abertura da ficha (B 2, C 1). A resposta vira notificação "
                  "na tela; não se sabe se o servidor grava algo. Não é necessário à "
                  "leitura: fica fora da lista branca.",
        "validar": "Só se o bloqueio atrapalhar a navegação.",
    },
    {
        "operacao": "POST /form_exames_resultados/ nmgp_opcao=''",
        "motivo": "Abre o registro de Resultado em 'Atualização de tbl_exames_resultados', "
                  "com Salvar e Excluir visíveis. C 2 aberturas; a grade ficou idêntica, "
                  "mas o form não foi reaberto no mesmo registro. O coletor não precisa "
                  "dele: a grade traz título, data e arquivo.",
        "validar": "Abrir o mesmo resultado 2 vezes e comparar form e grade, como foi "
                   "feito com o laudo; clicar no Arquivo de um resultado com anexo.",
    },
    {
        "operacao": "POST /form_tbl_pacientes_crm_editavel/ nmgp_opcao=''",
        "motivo": "Abre um registro de Evolução em 'Atualização - form_tbl_pacientes' "
                  "(Salvar oculto; Excluir, Refazer e Imprimir visíveis). É onde está o "
                  "questionário pré-exame respondido. C 1 abertura; o conteúdo ficou "
                  "idêntico depois do Imprimir, mas a grade não foi recarregada. Não é "
                  "edição do cadastro do paciente (tbl_paciente_crm = itens da Evolução).",
        "validar": "Abrir o mesmo registro 2 vezes, recarregar a grade 'Andamento' e "
                   "comparar versão, data e conteúdo.",
    },
    {
        "operacao": "POST /blank_laudo_pdf/ (Imprimir do form do laudo)",
        "motivo": "O Imprimir submete F1 (multipart, o form inteiro) com "
                  "nmgp_opcao=formphp e nm_call_php=imprimir_normal para uma aba nova; o "
                  "servidor encaminha para POST /blank_laudo_pdf/. Duas vezes a resposta "
                  "foi a página 'Validade da assinatura' com o PDF em data: URI; uma vez, "
                  "no laudo em que antes se clicou ASSINAR PDF, foi JSON com o nome de um "
                  "arquivo temporário e data_assinatura. Comportamento dependente de "
                  "estado de sessão; o corpo do POST não é conhecido.",
        "validar": "Gravar Imprimir de um laudo sem nenhum ASSINAR PDF antes na sessão, com "
                   "o gravador capturando a 1ª requisição de abas novas.",
    },
    {
        "operacao": "POST /blank_quest_config_funcoes/ funcao=rel_dados_acompanhar",
        "motivo": "É o 'Pesquisar' da tela do questionário (JSON com os questionários do "
                  "filtro). Não foi clicado; o endpoint também serve à configuração de "
                  "questionários.",
        "validar": "Clicar Pesquisar com um questionário e período escolhidos.",
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


def _operacao_bloqueada(pares, liberadas=frozenset()):
    """Motivo do bloqueio por parâmetro de operação, ou ``None``.

    ``liberadas`` são pares ``(chave, valor)`` em minúsculas que a entrada da
    lista branca casada libera no seu caminho. Não valem dentro de
    ``nmgp_parms``.
    """
    expandidos = [(k, v, True) for k, v in pares]
    for chave, valor in pares:
        if chave.lower() == "nmgp_parms":
            expandidos.extend((k, v, False) for k, v in _pares_de_nmgp_parms(valor))
    for chave, valor, direto in expandidos:
        k = chave.strip().lower()
        v = valor.strip().lower()
        if direto and (k, v) in liberadas:
            continue
        if k in OPERACOES_SCRIPTCASE_BLOQUEADAS and v in OPERACOES_SCRIPTCASE_BLOQUEADAS[k]:
            return "operacao:%s=%s" % (k, v)
        if k in CHAVES_SCRIPTCASE_BLOQUEADAS and v:
            return "operacao:%s" % k
        if k == "funcao" and v in FUNCOES_AJAX_BLOQUEADAS:
            return "funcao:%s" % v
        if k == "acao" and v in ACOES_AJAX_BLOQUEADAS:
            return "acao:%s" % v
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


def _liberadas(entrada):
    return frozenset((k.lower(), v.lower())
                     for k, valores in entrada.get("libera", {}).items() for v in valores)


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
    for prefixo in ENDPOINTS_PENDENTES_VALIDACAO:
        if caminho.startswith(prefixo.lower()):
            return False, "pendente:%s" % prefixo

    pares = parse_qsl(partes.query, keep_blank_values=True)
    corpo_pares = []
    entrada = None
    if metodo == "POST":
        try:
            corpo_pares = _corpo_urlencoded(_texto_do_corpo(corpo), tipo_corpo)
        except ValueError:
            corpo_pares = None
        if corpo_pares is None:
            return False, "corpo_nao_analisavel"
        entrada = next((e for e in POSTS_PERMITIDOS
                        if _casa_entrada(e, host, caminho, corpo_pares)), None)
    liberadas = _liberadas(entrada) if entrada else frozenset()
    motivo = _operacao_bloqueada(pares + corpo_pares, liberadas)
    if motivo:
        return False, motivo

    if metodo in METODOS_HTTP_LEITURA:
        return True, "leitura:%s" % metodo
    if entrada:
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
    também não passa pelo ``route``; o MD usa um para o chat de terceiros e
    outro para as notificações.
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
