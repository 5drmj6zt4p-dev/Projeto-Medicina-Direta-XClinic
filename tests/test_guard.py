"""Testes da guarda de somente leitura (dados sintéticos, sem PHI)."""

import pytest

from fluxo_exames import guard

MD = "https://pep.medicinadireta.com.br"
FORM_LAUDO = MD + "/form_paciente_exames_laudos_resultado/"
URLENC = "application/x-www-form-urlencoded"


def post(caminho, corpo="", tipo=URLENC, host=MD):
    return guard.avaliar_requisicao("POST", host + caminho, corpo, tipo)


# --- permitido explícito ---------------------------------------------------

@pytest.mark.parametrize("caminho, corpo", [
    ("/blank_notificacao_funcoes/blank_notificacao_funcoes.php", "funcao=qtd_novo"),
    ("/blank_home_funcoes/blank_home_funcoes.php", "funcao=m_noticias&tipo=1"),
    ("/blank_sessao_funcoes/blank_sessao_funcoes.php",
     "funcao=limpar_sessao_aplicacoes&apls=%5B%22grid_x%22%5D"),
    ("/grid_exames_laudo/", "script_case_init=1&nm_run_menu=1"),
    ("/cont_exame_resultado_laudo/", "nmgp_opcao=&nmgp_parms=OrScLink%3F%23%3F1%3F%40%3F"),
    ("/grid_paciente_exames_laudos_resultado/index.php",
     "nmgp_opcao=ajax_save_ancor&script_case_init=1&ancor_save=2"),
    ("/form_paciente_exames_laudos_resultado/form_paciente_exames_laudos_resultado_fim.php",
     "script_case_init=1"),
    # v2: funcao gravada na sessão da Etapa C
    ("/blank_notificacao_funcoes/blank_notificacao_funcoes.php", "funcao=buscar_sala_usuario"),
    ("/blank_menu_inicial_funcoes/blank_menu_inicial_funcoes.php",
     "funcao=m_token_sessao&acao=consultar"),
    # v2: telas novas da sessão da Etapa C
    ("/grid_exames_resultados/", "script_case_init=1&nm_run_menu=1"),
    ("/ctr_quest_rel_acompanhar/", "script_case_init=1"),
    ("/grid_tbl_paciente_crm_anexo_doc/", "script_case_init=1"),
    ("/grid_tbl_paciente_crm_anexo_img/", "script_case_init=1"),
    ("/grid_tbl_pacientes_crm/", "script_case_init=1"),
])
def test_post_permitido_explicito(caminho, corpo):
    permitida, motivo = post(caminho, corpo)
    assert permitida, motivo
    assert motivo.startswith("post_permitido:")


def test_igual_liberado_no_form_do_laudo():
    # ALTERADO v1->v2: nm_gp_submit4 (F3) do 2º nível
    corpo = ("nmgp_opcao=igual&nmgp_parms=%40SC_par%401%40SC_par%40grid_paciente_exames_"
             "laudos_resultado%40SC_par%400123456789abcdef&script_case_init=1&nmgp_ancora=2")
    assert post("/form_paciente_exames_laudos_resultado/", corpo) == \
        (True, "post_permitido:laudo_form_abrir")


@pytest.mark.parametrize("metodo, url", [
    ("GET", MD + "/grid_exames_laudo/grid_exames_laudo.php"),
    ("GET", MD + "/treemenu_paciente/?nmgp_parms=@SC_par@1@SC_par@grid_agenda_md_calendario"
            "@SC_par@0123456789abcdef0123456789abcdef&nm_run_menu=1&nmgp_opcao=&script_case_init=2"),
    ("HEAD", MD + "/"),
    ("OPTIONS", "https://api.exemplo.invalid/online"),
])
def test_leitura_permitida(metodo, url):
    assert guard.requisicao_permitida(metodo, url)


def test_post_aceita_corpo_bytes():
    assert guard.requisicao_permitida(
        "POST", MD + "/blank_treemenu_paciente_funcoes/blank_treemenu_paciente_funcoes.php",
        b"funcao=config_itens_historico", URLENC)


# --- bloqueado explícito ---------------------------------------------------

@pytest.mark.parametrize("opcao", ["alterar", "incluir", "excluir", "novo", "ALTERAR"])
def test_operacao_de_gravacao_no_form(opcao):
    permitida, motivo = post("/form_paciente_exames_laudos_resultado/", "nmgp_opcao=" + opcao)
    assert not permitida
    assert motivo == "operacao:nmgp_opcao=" + opcao.lower()


@pytest.mark.parametrize("caminho", [
    "/form_paciente_sbis/",
    "/form_receitas/",
    "/grid_exames_laudo/",
])
def test_igual_fora_do_form_do_laudo_segue_bloqueado(caminho):
    assert post(caminho, "nmgp_opcao=igual") == (False, "operacao:nmgp_opcao=igual")


def test_igual_por_get_segue_bloqueado():
    assert guard.avaliar_requisicao("GET", FORM_LAUDO + "?nmgp_opcao=igual") == \
        (False, "operacao:nmgp_opcao=igual")


@pytest.mark.parametrize("corpo", [
    "nmgp_opcao=igual&nmgp_parms=nm_call_php%3F%23%3Fimprimir_normal%3F%40%3F",
    "nmgp_opcao=igual&nm_call_php=imprimir_normal",
    "nmgp_opcao=igual&rs=ajax_form_paciente_exames_laudos_resultado_submit_form",
    "nmgp_opcao=igual&nmgp_opcao=alterar",
    "nmgp_opcao=igual&funcao=copiar_link",
])
def test_liberacao_de_igual_nao_cobre_outras_operacoes(corpo):
    permitida, motivo = post("/form_paciente_exames_laudos_resultado/", corpo)
    assert not permitida
    assert motivo.startswith(("operacao:", "funcao:")), motivo


def test_liberacao_nao_vale_dentro_de_nmgp_parms():
    # "igual" embutido em nmgp_parms continua bloqueado, mesmo no caminho liberado
    corpo = "nmgp_opcao=igual&nmgp_parms=nmgp_opcao%3F%23%3Figual%3F%40%3F"
    assert post("/form_paciente_exames_laudos_resultado/", corpo) == \
        (False, "operacao:nmgp_opcao=igual")


def test_imprimir_do_laudo_negado():
    # F1 é multipart: o form inteiro vai no corpo, com formphp/imprimir_normal
    corpo = ("--x\r\nContent-Disposition: form-data; name=\"nmgp_parms\"\r\n\r\n"
             "nmgp_opcao?#?formphp?@?nm_call_php?#?imprimir_normal?@?\r\n--x--\r\n")
    assert post("/form_paciente_exames_laudos_resultado/", corpo,
                "multipart/form-data; boundary=x") == (False, "corpo_nao_analisavel")


@pytest.mark.parametrize("metodo, url, corpo", [
    ("POST", MD + "/blank_laudo_pdf/", "script_case_init=1"),
    ("GET", MD + "/blank_laudo_pdf/blank_laudo_pdf.php?vg_id_receita_livre_pdf=1&assinar=S",
     None),
    ("POST", MD + "/blank_assinatura_digital/blank_assinatura_digital.php",
     "requisito=laudo&receitaId=1&clinica=1&usr=1"),
    ("POST", MD + "/grid_evolucao_imp/", "nmgp_opcao=print"),
    ("POST", MD + "/grid_evolucao_imp/", "nmgp_opcao=grid"),
    ("GET", MD + "/grid_evolucao_imp/grid_evolucao_imp_iframe_prt.php?script_case_init=1", None),
    ("GET", MD + "/blank_log_personalizado/blank_log_personalizado.php?p_action=print", None),
    ("POST", MD + "/blank_quest_config_funcoes/blank_quest_config_funcoes.php",
     "funcao=rel_dados_acompanhar"),
    ("GET", MD + "/blank_quest_acompanhar_pdf/blank_quest_acompanhar_pdf.php", None),
    ("POST", MD + "/form_log_inativar/", "nmgp_opcao="),
    ("POST", MD + "/ctr_editar_item_soap/", ""),
])
def test_pdf_assinatura_impressao_e_log_bloqueados(metodo, url, corpo):
    permitida, motivo = guard.avaliar_requisicao(metodo, url, corpo, URLENC)
    assert not permitida and motivo.startswith("endpoint:")


@pytest.mark.parametrize("metodo, url, corpo", [
    ("POST", MD + "/form_tbl_pacientes_crm_editavel/", "nmgp_opcao="),
    ("GET", MD + "/form_tbl_pacientes_crm_editavel/form_tbl_pacientes_crm_editavel.php", None),
    ("POST", MD + "/form_exames_resultados/", "nmgp_opcao="),
    ("POST", MD + "/form_exames_resultados/form_exames_resultados_fim.php", "script_case_init=1"),
])
def test_forms_em_edicao_pendentes(metodo, url, corpo):
    permitida, motivo = guard.avaliar_requisicao(metodo, url, corpo, URLENC)
    assert not permitida and motivo.startswith("pendente:")


@pytest.mark.parametrize("opcao", ["print", "pdf", "xls", "csv"])
def test_impressao_e_exportacao_de_grade_bloqueadas(opcao):
    assert post("/grid_exames_laudo/", "nmgp_opcao=" + opcao) == \
        (False, "operacao:nmgp_opcao=" + opcao)


def test_chave_assinar_bloqueada_em_qualquer_endpoint():
    assert guard.avaliar_requisicao("GET", MD + "/blank_receita_x/x.php?assinar=S") == \
        (False, "operacao:assinar")


def test_token_sessao_so_com_consultar():
    caminho = "/blank_menu_inicial_funcoes/blank_menu_inicial_funcoes.php"
    assert post(caminho, "funcao=m_token_sessao&acao=alterar_sessao_ativa&valor=S") == \
        (False, "acao:alterar_sessao_ativa")
    assert post(caminho, "funcao=m_token_sessao") == (False, "post_nao_listado")
    assert post(caminho, "funcao=m_token_sessao&acao=consultar&acao=outra") == \
        (False, "post_nao_listado")


def test_obter_favoritos_saiu_da_lista_branca():
    # ALTERADO v1->v2: valor deduzido na v1, nunca gravado
    assert post("/blank_menu_inicial_funcoes/blank_menu_inicial_funcoes.php",
                "funcao=m_obter_favoritos") == (False, "post_nao_listado")


def test_operacao_bloqueia_ate_em_post_liberado():
    permitida, motivo = post("/grid_exames_laudo/", "nmgp_opcao=excluir")
    assert not permitida and motivo.startswith("operacao:")


def test_botao_php_escondido_em_nmgp_parms():
    # sc_btn_email_ok: nmgp_parms = "nmgp_opcao?#?formphp?@?nm_call_php?#?email?@?"
    corpo = "nmgp_opcao=&nmgp_parms=nmgp_opcao%3F%23%3Fformphp%3F%40%3Fnm_call_php%3F%23%3Femail%3F%40%3F"
    permitida, motivo = post("/cont_exame_resultado_laudo/", corpo)
    assert not permitida
    assert motivo == "operacao:nmgp_opcao=formphp"


def test_sajax_bloqueado_em_get_e_post():
    rs = "ajax_form_paciente_exames_laudos_resultado_submit_form"
    assert not guard.requisicao_permitida("GET", FORM_LAUDO + "?rs=" + rs + "&rst=")
    assert not guard.requisicao_permitida("POST", FORM_LAUDO, "rs=" + rs, URLENC)


@pytest.mark.parametrize("funcao", ["alteracao_agenda", "favoritar", "visualizar_novos"])
def test_funcao_de_escrita_em_endpoint_liberado(funcao):
    permitida, motivo = post("/blank_notificacao_funcoes/blank_notificacao_funcoes.php",
                             "funcao=" + funcao)
    assert not permitida
    assert motivo == "funcao:" + funcao


@pytest.mark.parametrize("metodo", ["PUT", "PATCH", "DELETE", "TRACE"])
def test_metodo_bloqueado(metodo):
    permitida, motivo = guard.avaliar_requisicao(metodo, MD + "/grid_exames_laudo/")
    assert not permitida and motivo == "metodo:" + metodo


@pytest.mark.parametrize("url", [
    MD + "/blank_fecha_atendimento/blank_fecha_atendimento.php?tipo=t",
    MD + "/blank_log_personalizado/blank_log_personalizado.php?p_action=expired",
    MD + "/blank_assinatura_digital/blank_assinatura_digital.php",
    MD + "/grid_exames_laudo/../blank_editavel/blank_editavel.php",
    MD + "//BLANK_ASSINAR_PDF/blank_assinar_pdf.php",
])
def test_endpoint_bloqueado_mesmo_em_get(url):
    permitida, motivo = guard.avaliar_requisicao("GET", url)
    assert not permitida and motivo.startswith("endpoint:")


# --- desconhecido -> negado ------------------------------------------------

def test_post_desconhecido_negado():
    assert post("/endpoint_nunca_visto/", "a=1") == (False, "post_nao_listado")


def test_post_de_terceiro_negado():
    assert post("/collect", "x=1", host="https://h.telemetria.invalid") == \
        (False, "post_nao_listado")


def test_valor_de_funcao_desconhecido_negado():
    assert post("/blank_home_funcoes/blank_home_funcoes.php", "funcao=m_algo_novo") == \
        (False, "post_nao_listado")


def test_opcao_desconhecida_em_post_liberado_negada():
    assert post("/cont_exame_resultado_laudo/", "nmgp_opcao=rec") == (False, "post_nao_listado")


def test_host_diferente_nao_herda_a_lista_branca():
    assert post("/grid_exames_laudo/", "", host="https://pep.outro-host.invalid") == \
        (False, "post_nao_listado")


@pytest.mark.parametrize("corpo, tipo", [
    ('{"funcao": "qtd_novo"}', "application/json"),
    ("--x\r\nContent-Disposition: form-data\r\n", "multipart/form-data; boundary=x"),
    ('{"funcao": "qtd_novo"}', None),
    (b"\xff\xfe", URLENC),
    (guard.CORPO_ILEGIVEL, URLENC),
])
def test_corpo_nao_analisavel_negado(corpo, tipo):
    assert post("/blank_notificacao_funcoes/blank_notificacao_funcoes.php", corpo, tipo) == \
        (False, "corpo_nao_analisavel")


def test_metodo_desconhecido_negado():
    assert guard.avaliar_requisicao("FOO", MD + "/") == (False, "metodo_desconhecido:FOO")


# --- camada 2: cliques -----------------------------------------------------

def test_normalizar_texto():
    assert guard.normalizar_texto("  Ações\n de   Solicitação ") == "ACOES DE SOLICITACAO"
    assert guard.normalizar_texto("E-MAIL") == "E MAIL"
    assert guard.normalizar_texto(None) == ""


@pytest.mark.parametrize("texto", [
    "Finalizar e Assinar", "ASSINAR PDF", "Salvar", "Enviar Por", "Criar Laudo",
    "Interno - Em Branco", "E-MAIL", "Sim", "Ações",
    "Upload Imagem", "Excluir Selecionados", "Novo Documento", "Refazer", "Copiar",
    "Imprimir",
])
def test_clique_bloqueado_por_texto(texto):
    assert not guard.clique_permitido(texto)


def test_clique_bloqueado_por_title_ou_value():
    assert not guard.clique_permitido(["", "Assinar PDF digitalmente"])


@pytest.mark.parametrize("texto", [
    "Voltar", "Laudo", "Agendamento", "SIMONE TESTE", "", "Resultado", "Evolução",
    "Últimos Resultados", "Ver Slide",
])
def test_clique_permitido(texto):
    assert guard.clique_permitido(texto)


@pytest.mark.parametrize("id_elemento, onclick", [
    ("sc_b_upd_t", None),
    ("sc_finalizar_assinar_top", None),
    ("id_sc_field_cmp_assinar_2", None),
    (None, "fn_js_assinatura_pdf_lc(\"laudo\", 1, 2, 3);"),
    (None, "javascript:nm_atualiza ('alterar');"),
    ("sc_refazer_top", None),
    ("sc_inativar_top", None),
    ("sc_btn_imprimir_top", None),
    ("sc_btn_novo_mult_top", None),
    ("sc_btn_excluir_top", None),
    ("id_sc_field_cmp_copiar_1", None),
    (None, "scBtnFn_btn_imprimir(); return false;"),
    (None, "m_js_imprimir();"),
    (None, "if (!mdPepOpenCertificates(param, menu, url)) {}"),
])
def test_clique_bloqueado_por_id_ou_funcao(id_elemento, onclick):
    assert not guard.clique_permitido("", id_elemento=id_elemento, onclick=onclick)


def test_clique_no_lapis_do_nivel1_permitido():
    href = "javascript:nm_gp_submit5('/cont_exame_resultado_laudo/', '/grid_exames_laudo/', 'x')"
    assert guard.clique_permitido("", id_elemento="id_sc_field_cmp_ligacao_1", onclick=href)


# --- consistência das listas -----------------------------------------------

def test_entradas_da_lista_branca_tem_evidencia_e_nao_colidem_com_bloqueios():
    ids = [e["id"] for e in guard.POSTS_PERMITIDOS]
    assert len(ids) == len(set(ids))
    for entrada in guard.POSTS_PERMITIDOS:
        assert entrada["evidencia"].strip()
        assert entrada["exige"], entrada["id"]
        libera = entrada.get("libera", {})
        for chave, valores in libera.items():
            # só libera o que a própria entrada exige, e a liberação precisa de registro
            assert set(valores) <= set(entrada["exige"][chave]), entrada["id"]
            assert "ALTERADO v1→v2" in entrada["evidencia"], entrada["id"]
        for valor in entrada["exige"].get("nmgp_opcao", ()):
            if valor not in libera.get("nmgp_opcao", ()):
                assert valor not in guard.OPERACOES_SCRIPTCASE_BLOQUEADAS["nmgp_opcao"]
        for valor in entrada["exige"].get("funcao", ()):
            assert valor.lower() not in guard.FUNCOES_AJAX_BLOQUEADAS
        for valor in entrada["exige"].get("acao", ()):
            assert valor.lower() not in guard.ACOES_AJAX_BLOQUEADAS
        caminho = guard._normalizar_caminho(entrada["caminho"])
        assert not any(caminho.startswith(p) for p in guard.ENDPOINTS_BLOQUEADOS)
        assert not any(caminho.startswith(p) for p in guard.ENDPOINTS_PENDENTES_VALIDACAO)


def test_pendencias_documentadas():
    for p in guard.OPERACOES_PENDENTES_VALIDACAO:
        assert p["operacao"] and p["motivo"] and p["validar"]
    assert not any("igual" in p["operacao"] for p in guard.OPERACOES_PENDENTES_VALIDACAO)


# --- instalar() com um contexto falso --------------------------------------

class _Requisicao:
    def __init__(self, metodo, url, corpo=None, tipo=URLENC):
        self.method, self.url, self._corpo = metodo, url, corpo
        self.headers = {"content-type": tipo} if tipo else {}

    @property
    def post_data_buffer(self):
        if self._corpo is guard.CORPO_ILEGIVEL:
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "x")
        return self._corpo


class _Rota:
    def __init__(self):
        self.resultado = None

    def continue_(self):
        self.resultado = "continuou"

    def abort(self, erro):
        self.resultado = "abortou:" + erro


class _Contexto:
    def route(self, padrao, manipulador):
        self.padrao, self.manipulador = padrao, manipulador


def test_instalar_aborta_e_registra_sem_query():
    contexto, eventos = _Contexto(), []
    guard.instalar(contexto, eventos.append)
    assert contexto.padrao == "**/*"

    rota = _Rota()
    contexto.manipulador(rota, _Requisicao("GET", MD + "/grid_exames_laudo/grid_exames_laudo.php"))
    assert rota.resultado == "continuou" and eventos == []

    rota = _Rota()
    contexto.manipulador(rota, _Requisicao(
        "POST", FORM_LAUDO + "?id_paciente=123", b"nmgp_opcao=alterar"))
    assert rota.resultado == "abortou:blockedbyclient"
    assert eventos == [{"metodo": "POST", "host": "pep.medicinadireta.com.br",
                        "caminho": "/form_paciente_exames_laudos_resultado/",
                        "motivo": "operacao:nmgp_opcao=alterar"}]
    assert "123" not in repr(eventos)

    rota = _Rota()
    contexto.manipulador(rota, _Requisicao(
        "POST", MD + "/grid_exames_laudo/", guard.CORPO_ILEGIVEL))
    assert rota.resultado == "abortou:blockedbyclient"
    assert eventos[-1]["motivo"] == "corpo_nao_analisavel"
