"""Testes do coletor contra o servidor sintético (sem acesso ao MD, sem PHI).

Cada teste abre um Chrome descartável com porta de depuração e o coletor
conecta por CDP, como no uso real. As asserções de segurança são feitas do
lado do servidor: o que a guarda nega nunca pode aparecer em
``md.requisicoes``.
"""

import hashlib

import pytest

from fluxo_exames import coletor as mod
from fluxo_exames.coletor import Coletor, ColetorBloqueado
from tests.md_sintetico import DATA_AGENDA, PACIENTES

CAMINHO_FORM = "/form_paciente_exames_laudos_resultado/"


def _sem_escrita(md):
    assert md.escritas() == []
    assert md.violacoes() == []


def _widget(coletor, caminho):
    quadros = [f for f in coletor.pagina.frames
               if f.name == "dbifrm_widget3" and caminho in f.url]
    assert len(quadros) == 1
    return quadros[0]


# --- conexão -----------------------------------------------------------------

def test_conecta_com_guarda_de_rede_ativa(coletor, md):
    assert coletor.guarda_ativa
    assert coletor.pagina.url.startswith(md.url + "/menu_inicial/")
    assert not any("canario" in r["caminho"] for r in md.requisicoes)


@pytest.mark.parametrize("cdp", ["http://10.0.0.5:9222", "http://exemplo.invalid:9222",
                                 "file:///tmp/x"])
def test_recusa_cdp_que_nao_e_local(cdp):
    with pytest.raises(ColetorBloqueado) as erro:
        Coletor(cdp_url=cdp)
    assert erro.value.motivo == "cdp_nao_local"


def test_sem_aba_do_md_nao_conecta(chrome):
    c = Coletor(cdp_url=chrome.cdp_url, origem_md="http://127.0.0.1:1")
    with pytest.raises(ColetorBloqueado) as erro:
        c.conectar()
    assert erro.value.motivo == "aba_md_ausente"
    assert c._pw is None


def test_desconectar_nao_fecha_o_chrome(coletor, chrome, md):
    coletor.desconectar()
    assert chrome.vivo()
    assert any(a["url"].startswith(md.url + "/menu_inicial/") for a in chrome.abas())


# --- leitura -----------------------------------------------------------------

def test_leitura_completa_dos_dois_pacientes(coletor, md):
    agenda = coletor.ler_agenda(DATA_AGENDA)
    assert [(l["hora"], l["nome"], l["prontuario"], l["titulo"]) for l in agenda] == [
        ("08:00", "Paciente A", "900001", "US Mamas"),
        ("08:30", "Paciente B", "900002", "US Abdome")]
    assert "celular" not in agenda[0]

    linha = coletor.localizar_paciente("900001")
    assert linha["nome"] == "Paciente A"
    assert coletor.localizar_paciente("paciente   a") == linha
    assert coletor.localizar_paciente("999999") is None

    ident = coletor.abrir_ficha(linha)
    assert ident == {"prontuario": "900001", "nome": "Paciente A", "dn": "01/01/1900",
                     "cpf": "00000000000"}
    assert coletor.identidade() == ident

    atendimentos = coletor.listar_atendimentos()
    assert [(a["id"], a["atendimento"], a["versao"], a["titulo"]) for a in atendimentos] == [
        ("5001", "11", "2", "US Mamas / US Axilas"), ("5002", "12", "1", "US Tireoide")]
    assert atendimentos[0]["registros_em_aberto"] == (0, 2)
    assert atendimentos[0]["pdf_assinado"] == (0, 2)
    assert atendimentos[0]["data_evento"] == "20/09/2026 10:00 UTC-3"
    assert atendimentos[0]["profissional"] == "Profissional X"

    laudos = coletor.listar_laudos(atendimentos[0])
    assert [(l["id"], l["titulo"], l["data"], l["estado"]) for l in laudos] == [
        ("70.001", "US Mamas", "20/09/2026", "aguardando_assinatura"),
        ("70.002", "US Axilas", "20/09/2026", "aguardando_assinatura")]
    assert laudos[0]["abertura_registro"].startswith("Abertura do Registro")

    esperados = PACIENTES["900001"]["atendimentos"][0]["laudos"]
    for laudo, esperado in zip(laudos, esperados):
        lido = coletor.abrir_texto_laudo(laudo)
        assert lido["texto"] == esperado["texto"]
        assert lido["sha256"] == hashlib.sha256(esperado["texto"].encode()).hexdigest()
        assert lido["origem"] == "md:laudo:" + esperado["id"]
    # Voltou para a lista do 2º nível depois de cada leitura.
    assert _widget(coletor, "/grid_paciente_exames_laudos_resultado/")
    assert len(md.recebidas("POST", CAMINHO_FORM + "form_paciente_exames_laudos_"
                                                   "resultado_fim.php")) == 2

    # Paciente B: o 2º acesso à ficha dispara o GET automático de blank_fecha_atendimento.
    ident_b = coletor.abrir_ficha(coletor.localizar_paciente("900002"))
    assert ident_b["nome"] == "Paciente B"
    at_b = coletor.listar_atendimentos()
    laudos_b = coletor.listar_laudos(at_b[0]["id"])
    assert laudos_b[0]["assinatura"] == "Registro de outro profissional"
    assert coletor.abrir_texto_laudo(laudos_b[0])["texto"] == \
        PACIENTES["900002"]["atendimentos"][0]["laudos"][0]["texto"]

    # Do lado do servidor: o caminho de leitura passou e nada bloqueado chegou.
    assert len(md.recebidas("POST", CAMINHO_FORM)) >= 3
    assert md.recebidas("POST", "/grid_paciente_exames_laudos_resultado/index.php")
    _sem_escrita(md)
    motivos = {(e["caminho"], e["motivo"]) for e in coletor.bloqueios}
    assert ("/blank_notifica_lembrete/blank_notifica_lembrete.php", "post_nao_listado") in motivos
    assert ("/blank_fecha_atendimento/blank_fecha_atendimento.php",
            "endpoint:/blank_fecha_atendimento/") in motivos


def test_agenda_de_dia_sem_exames(coletor, md):
    assert coletor.ler_agenda("2026-10-02") == []
    _sem_escrita(md)


def test_localizar_exige_agenda_lida(coletor):
    with pytest.raises(ColetorBloqueado) as erro:
        coletor.localizar_paciente("900001")
    assert erro.value.motivo == "agenda_nao_lida"


def test_ficha_exige_agenda_lida(coletor, md):
    with pytest.raises(ColetorBloqueado) as erro:
        coletor.abrir_ficha(1)
    assert erro.value.motivo == "agenda_nao_lida"
    assert not md.recebidas("POST", "/blank_div/")


def test_ficha_divergente_da_agenda(coletor, md):
    agenda = coletor.ler_agenda(DATA_AGENDA)
    linha = dict(agenda[0], prontuario="900002")
    with pytest.raises(ColetorBloqueado) as erro:
        coletor.abrir_ficha(linha)
    assert erro.value.motivo == "ficha_divergente"
    _sem_escrita(md)


@pytest.mark.md(paginacao=True)
def test_paginacao_interrompe_em_vez_de_ler_pela_metade(coletor, md):
    coletor.ler_agenda(DATA_AGENDA)
    coletor.abrir_ficha(1)
    with pytest.raises(ColetorBloqueado) as erro:
        coletor.listar_atendimentos()
    assert erro.value.motivo == "paginacao_pendente"
    _sem_escrita(md)


# --- camada 1: operação ------------------------------------------------------

@pytest.mark.parametrize("operacao, motivo", [
    ("finalizar_assinar", "operacao_nao_permitida"),
    ("salvar", "operacao_nao_permitida"),
    ("_rota", "operacao_nao_permitida"),
    ("baixar_pdf_laudo", "operacao_pendente"),
    ("abrir_evolucao", "operacao_pendente"),
    ("paginar", "operacao_pendente"),
])
def test_operacao_fora_da_lista_aborta(coletor, md, operacao, motivo):
    with pytest.raises(ColetorBloqueado) as erro:
        coletor.executar(operacao)
    assert erro.value.motivo == motivo
    _sem_escrita(md)


def test_clique_fora_de_operacao(coletor, md):
    alvo = coletor.pagina.main_frame.locator("#item_31")
    with pytest.raises(ColetorBloqueado) as erro:
        coletor._clicar("menu_agendamento", alvo)
    assert erro.value.motivo == "clique_fora_de_operacao"


def test_clique_nao_mapeado_para_a_operacao(coletor, md):
    alvo = coletor.pagina.main_frame.locator("#item_31")
    with coletor._em_operacao("identidade"):
        with pytest.raises(ColetorBloqueado) as erro:
            coletor._clicar("menu_agendamento", alvo)
    assert erro.value.motivo == "clique_nao_mapeado"
    with coletor._em_operacao("ler_agenda"):
        with pytest.raises(ColetorBloqueado) as erro:
            coletor._clicar("finalizar_assinar", alvo)
    assert erro.value.motivo == "clique_nao_mapeado"


# --- camada 3: interdição de textos --------------------------------------------

def _abrir_form_sem_coletor(coletor):
    """Leva a lista do 2º nível até o form do laudo, como um usuário faria."""
    laudos = coletor.listar_laudos(coletor.listar_atendimentos()[0])
    lista = _widget(coletor, "/grid_paciente_exames_laudos_resultado/")
    lista.locator("#id_sc_field_cmp_descricao_1").click()
    coletor.pagina.wait_for_timeout(100)
    for _ in range(100):
        forms = [f for f in coletor.pagina.frames
                 if f.name == "dbifrm_widget3" and CAMINHO_FORM in f.url]
        if forms and forms[0].locator("#sc_finalizar_assinar_top").count():
            return laudos, forms[0]
        coletor.pagina.wait_for_timeout(100)
    raise AssertionError("form do laudo não abriu")


@pytest.mark.parametrize("seletor", [
    "#sc_finalizar_assinar_top",   # Finalizar e Assinar
    "#sc_imprimir_normal_top",     # Imprimir
    "#sc_email_top",               # E-MAIL
    "#sc_btgp_btn_group_2_top",    # Enviar Por
])
def test_interdicao_de_texto_no_form_do_laudo(coletor, md, seletor):
    coletor.ler_agenda(DATA_AGENDA)
    coletor.abrir_ficha(1)
    _, form = _abrir_form_sem_coletor(coletor)
    antes = len(md.requisicoes)
    with coletor._em_operacao("abrir_texto_laudo"):
        with pytest.raises(ColetorBloqueado) as erro:
            coletor._clicar("laudo_voltar", form.locator(seletor))
    assert erro.value.motivo == "clique_interditado"
    coletor.pagina.wait_for_timeout(300)
    assert len(md.requisicoes) == antes
    _sem_escrita(md)


def test_interdicao_de_assinar_pdf_na_lista(coletor, md):
    coletor.ler_agenda(DATA_AGENDA)
    coletor.abrir_ficha(1)
    coletor.listar_laudos(coletor.listar_atendimentos()[0])
    lista = _widget(coletor, "/grid_paciente_exames_laudos_resultado/")
    with coletor._em_operacao("abrir_texto_laudo"):
        with pytest.raises(ColetorBloqueado) as erro:
            coletor._clicar("laudo_abrir", lista.locator("#id_sc_field_cmp_assinar_1 a"))
    assert erro.value.motivo == "clique_interditado"
    _sem_escrita(md)


@pytest.mark.md(armadilha=True)
def test_armadilha_no_lugar_do_voltar(coletor, md):
    """O botão na posição do Voltar chama Finalizar e Assinar: o coletor para."""
    coletor.ler_agenda(DATA_AGENDA)
    coletor.abrir_ficha(1)
    laudos = coletor.listar_laudos(coletor.listar_atendimentos()[0])
    with pytest.raises(ColetorBloqueado) as erro:
        coletor.abrir_texto_laudo(laudos[0])
    assert erro.value.motivo == "clique_interditado"
    coletor.pagina.wait_for_timeout(300)
    assert not md.recebidas("POST", CAMINHO_FORM + "form_paciente_exames_laudos_resultado_fim")
    _sem_escrita(md)


# --- camada 2: rede ------------------------------------------------------------

def test_escrita_forcada_pela_pagina_nao_chega_ao_servidor(coletor, md):
    """Simula a página (ou um bug) disparando escrita por fora do coletor."""
    coletor.ler_agenda(DATA_AGENDA)
    coletor.abrir_ficha(1)
    _, form = _abrir_form_sem_coletor(coletor)
    form.evaluate("""() => {
        scBtnFn_finalizar_assinar();
        fetch('./', {method: 'POST', headers: {'Content-Type':
            'application/x-www-form-urlencoded'}, body: 'nmgp_opcao=alterar&receituario=x'})
            .catch(() => 0);
        fetch('./', {method: 'PUT', body: 'x'}).catch(() => 0);
        fetch('../blank_laudo_pdf/blank_laudo_pdf.php?vg_id_receita_livre_pdf=1&assinar=S')
            .catch(() => 0);
        nm_atualiza('alterar');
    }""")
    coletor.pagina.wait_for_timeout(1000)
    with pytest.raises(ColetorBloqueado) as erro:
        coletor.verificar_rede()
    assert erro.value.motivo == "rede"
    motivos = {e["motivo"] for e in coletor.bloqueios}
    assert {"operacao:rs", "operacao:nmgp_opcao=alterar", "metodo:PUT",
            "endpoint:/blank_laudo_pdf/", "corpo_nao_analisavel"} <= motivos
    _sem_escrita(md)
    assert not md.recebidas("PUT")


def test_bloqueio_nao_tolerado_interrompe_a_operacao_seguinte(coletor, md):
    coletor.ler_agenda(DATA_AGENDA)
    agenda = [f for f in coletor.pagina.frames if f.name == "menu_inicial_item_31_iframe"][0]
    agenda.evaluate("() => document.querySelector('#id_sc_field_cmp_chegada_1').click()")
    coletor.pagina.wait_for_timeout(500)
    with pytest.raises(ColetorBloqueado) as erro:
        coletor.abrir_ficha(1)
    assert erro.value.motivo == "rede"
    assert "/blank_status/" in erro.value.detalhe
    # Nada foi clicado: a ficha não abriu.
    assert not md.recebidas("GET", "/treemenu_paciente/")
    _sem_escrita(md)


def test_assinar_pdf_e_cadeado_forcados(coletor, md):
    coletor.ler_agenda(DATA_AGENDA)
    coletor.abrir_ficha(1)
    coletor.listar_atendimentos()
    nivel1 = [f for f in coletor.pagina.frames if f.name == "treemenu_paciente_item_165_iframe"][0]
    nivel1.evaluate("() => fn_js_editavel(5001)")
    coletor.pagina.wait_for_timeout(500)
    with pytest.raises(ColetorBloqueado):
        coletor.verificar_rede()
    coletor.listar_laudos("5001")
    lista = _widget(coletor, "/grid_paciente_exames_laudos_resultado/")
    lista.evaluate("() => { fn_js_assinatura_pdf_lc(70001); "
                   "document.querySelector('#sc_btn_novo_top').click(); }")
    coletor.pagina.wait_for_timeout(500)
    with pytest.raises(ColetorBloqueado):
        coletor.verificar_rede()
    motivos = {e["motivo"] for e in coletor.bloqueios}
    assert {"endpoint:/blank_editavel/", "endpoint:/blank_assinatura_digital/",
            "post_nao_listado"} <= motivos
    _sem_escrita(md)


# --- decisão de rede (sem navegador) -------------------------------------------

def test_modo_sintetico_nunca_deixa_passar_o_md_real():
    c = Coletor(cdp_url="http://127.0.0.1:9", origem_md="http://127.0.0.1:8000")
    for url in ("https://pep.medicinadireta.com.br/menu_inicial/",
                "https://medicinadireta.com.br/", "https://www.medicinadireta.com.br/x"):
        assert c.decidir("GET", url) == (False, "md_real_em_modo_sintetico")
    assert c.decidir("GET", "http://127.0.0.1:8000/grid_exames_laudo/grid_exames_laudo.php")[0]
    assert c.decidir("POST", "http://127.0.0.1:8000/blank_div/", b"script_case_init=1",
                     "application/x-www-form-urlencoded") == (True, "post_permitido:menu_agenda")
    # Outra porta do mesmo host não é a origem: não herda a lista branca.
    assert c.decidir("POST", "http://127.0.0.1:8001/blank_div/", b"",
                     "application/x-www-form-urlencoded") == (False, "post_nao_listado")


def test_modo_real_usa_a_guarda_sem_traducao():
    c = Coletor()
    assert not c._sintetico
    url = "https://pep.medicinadireta.com.br/form_paciente_exames_laudos_resultado/"
    assert c.decidir("POST", url, b"nmgp_opcao=igual", "application/x-www-form-urlencoded") \
        == (True, "post_permitido:laudo_form_abrir")
    assert c.decidir("POST", url, b"nmgp_opcao=alterar",
                     "application/x-www-form-urlencoded")[0] is False


def test_tolerados_so_os_automaticos_do_mapa():
    c = Coletor(cdp_url="http://127.0.0.1:9", origem_md="http://127.0.0.1:8000")
    evento = {"metodo": "POST", "host": "127.0.0.1", "motivo": "x"}
    assert c._tolerado(dict(evento, caminho="/blank_notifica_lembrete/blank_notifica_lembrete.php"))
    assert c._tolerado(dict(evento, caminho="/blank_fecha_atendimento/blank_fecha_atendimento.php"))
    assert c._tolerado(dict(evento, host="h.clarity.ms", caminho="/collect"))
    assert not c._tolerado(dict(evento, caminho="/blank_status/blank_status.php"))
    assert not c._tolerado(dict(evento, caminho=CAMINHO_FORM))
    assert not c._tolerado(dict(evento, host="api.medicinadireta.com.br", caminho="/x"))


def test_cliques_do_mapa_so_para_operacoes_permitidas():
    for chave, regra in mod.CLIQUES.items():
        assert set(regra["operacoes"]) <= set(mod.OPERACOES_PERMITIDAS), chave
    assert not set(mod.OPERACOES_PENDENTES_VALIDACAO) & set(mod.OPERACOES_PERMITIDAS)
