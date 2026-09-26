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
])
def test_post_permitido_explicito(caminho, corpo):
    permitida, motivo = post(caminho, corpo)
    assert permitida, motivo
    assert motivo.startswith("post_permitido:")


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


def test_igual_no_form_do_laudo_pendente_e_bloqueado():
    permitida, motivo = post("/form_paciente_exames_laudos_resultado/",
                             "nmgp_opcao=igual&nmgp_parms=%40SC_par%40x")
    assert not permitida
    assert motivo == "operacao:nmgp_opcao=igual"
    assert any("igual" in p["operacao"] for p in guard.OPERACOES_PENDENTES_VALIDACAO)


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
])
def test_clique_bloqueado_por_texto(texto):
    assert not guard.clique_permitido(texto)


def test_clique_bloqueado_por_title_ou_value():
    assert not guard.clique_permitido(["", "Assinar PDF digitalmente"])


@pytest.mark.parametrize("texto", ["Voltar", "Laudo", "Agendamento", "SIMONE TESTE", ""])
def test_clique_permitido(texto):
    assert guard.clique_permitido(texto)


@pytest.mark.parametrize("id_elemento, onclick", [
    ("sc_b_upd_t", None),
    ("sc_finalizar_assinar_top", None),
    ("id_sc_field_cmp_assinar_2", None),
    (None, "fn_js_assinatura_pdf_lc(\"laudo\", 1, 2, 3);"),
    (None, "javascript:nm_atualiza ('alterar');"),
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
        for valor in entrada["exige"].get("nmgp_opcao", ()):
            assert valor not in guard.OPERACOES_SCRIPTCASE_BLOQUEADAS["nmgp_opcao"]
        for valor in entrada["exige"].get("funcao", ()):
            assert valor.lower() not in guard.FUNCOES_AJAX_BLOQUEADAS
        caminho = guard._normalizar_caminho(entrada["caminho"])
        assert not any(caminho.startswith(p) for p in guard.ENDPOINTS_BLOQUEADOS)


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
