"""Testes do gravador passivo: abas novas registradas desde a 1ª requisição (Etapa D).

Chrome descartável (headless, perfil temporário, porta de depuração) e um
servidor sintético local; nada acessa o MD. O gravador roda como no uso real
(``executar``), com o websocket e o HTTP dele espionados: todo comando CDP
que ele envia é conferido contra a lista permitida. Quem age nas páginas é o
teste, por uma conexão CDP própria que faz o papel do usuário
(``Runtime.evaluate`` com ``userGesture``), nunca o gravador.

Os marcadores dos corpos de requisição e de resposta são gerados na hora e
só aparecem nas páginas em base64 (``atob``), para que o snapshot HTML, que
por design grava o DOM, não os contenha literalmente.
"""

import argparse
import base64
import collections
import http.server
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import pytest
import websocket

from tests.conftest import ChromeDescartavel, _chrome

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "scripts" / "gravador_passivo.py"

_spec = importlib.util.spec_from_file_location("gravador_passivo", SCRIPT)
grav = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grav)

WS_ORIGINAL = websocket.create_connection
ESPERA = 0.5
PROIBIDOS = ("Runtime.evaluate", "Runtime.callFunctionOn", "Network.getResponseBody",
             "Network.getRequestPostData", "Target.attachToTarget", "Target.createTarget",
             "Target.closeTarget", "Page.navigate", "Input.")


# --- apoio -------------------------------------------------------------------

class Verificacoes:
    """Acumula verificações nomeadas; o teste falha no fim listando todas as falhas."""

    total = 0

    def __init__(self):
        self.feitas = 0
        self.falhas = []

    def __call__(self, condicao, descricao):
        self.feitas += 1
        Verificacoes.total += 1
        if not condicao:
            self.falhas.append(descricao)
        return bool(condicao)

    def concluir(self, nome):
        print(f"\n[{nome}] {self.feitas} verificações, {len(self.falhas)} falhas")
        assert not self.falhas, "\n".join(self.falhas)


def esperar(condicao, limite=20.0, intervalo=0.1):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(intervalo)
    return False


def _marcador(nome):
    return f"MARCADOR-{nome}-{uuid.uuid4().hex[:12]}"


def _b64(texto):
    return base64.b64encode(texto.encode()).decode()


def _html(titulo, corpo):
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{titulo}</title>'
            f'<link rel="icon" href="data:,"></head><body>{corpo}</body></html>')


def _campos_js(campos):
    """JS que cria um <input type=text> por campo. Valor por propriedade, não por atributo."""
    return "".join(
        f"{{const i=document.createElement('input');i.type='text';i.name={json.dumps(k)};"
        f"i.value=atob('{_b64(v)}');f.appendChild(i);}}"
        for k, v in campos)


def _form_js(acao, campos, enctype="application/x-www-form-urlencoded", alvo="_blank"):
    return ("(()=>{const f=document.createElement('form');f.method='post';"
            f"f.action={json.dumps(acao)};f.enctype={json.dumps(enctype)};f.target={json.dumps(alvo)};"
            + _campos_js(campos) + "document.body.appendChild(f);f.submit();f.remove();})()")


class ServidorSintetico:
    """Páginas locais que imitam o Imprimir do MD e as outras aberturas de aba."""

    def __init__(self):
        self.requisicoes = []
        self._trava = threading.Lock()
        self.m = {n: _marcador(n) for n in (
            "req_imprimir", "req_pdf", "req_redir", "req_grande", "req_xhr", "req_xhr_grande",
            "resp_css", "resp_json", "resp_js", "resp_oop")}

    def iniciar(self):
        servidor = self

        class Tratador(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                servidor._atender(self, "GET")

            def do_POST(self):
                servidor._atender(self, "POST")

        class Servidor(http.server.ThreadingHTTPServer):
            def handle_error(self, *args):
                pass  # conexões keep-alive derrubadas pelo Chrome ao fechar

        self.httpd = Servidor(("127.0.0.1", 0), Tratador)
        self.porta = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.porta}"
        self.outro = f"http://localhost:{self.porta}"  # outro site: vira iframe fora do processo
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def parar(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def recebidas(self, desde=0):
        with self._trava:
            return list(self.requisicoes[desde:])

    def recebeu(self, metodo, caminho):
        return any(r["metodo"] == metodo and r["caminho"] == caminho for r in self.recebidas())

    def _atender(self, h, metodo):
        tamanho = int(h.headers.get("Content-Length") or 0)
        corpo = h.rfile.read(tamanho) if tamanho else b""
        with self._trava:
            self.requisicoes.append({"metodo": metodo, "caminho": h.path, "corpo": corpo,
                                     "agente": h.headers.get("User-Agent", "")})
        status, cabecalhos, conteudo = self._rotear(metodo, urllib.parse.urlsplit(h.path).path)
        h.send_response(status)
        for nome, valor in cabecalhos.items():
            h.send_header(nome, valor)
        dados = conteudo.encode() if isinstance(conteudo, str) else conteudo
        h.send_header("Content-Length", str(len(dados)))
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        h.wfile.write(dados)

    def _rotear(self, metodo, caminho):
        html = {"Content-Type": "text/html; charset=utf-8"}
        m = self.m
        paginas = {
            ("GET", "/inicio"): _html("Inicio", '<h1>Inicio</h1><iframe src="/quadro1"></iframe>'
                                      f'<iframe src="{self.outro}/oop_inicio"></iframe>'),
            ("GET", "/quadro1"): _html("Q1", '<p>quadro 1</p><iframe src="/quadro2"></iframe>'),
            ("GET", "/quadro2"): _html("Q2", "<p>quadro 2</p>"),
            ("GET", "/quadro3"): _html("Q3", "<p>quadro 3</p>"),
            ("GET", "/oop_inicio"): _html("OOP inicio", '<p>outro site</p><img src="/pixel.png">'),
            # Imprimir: F1 multipart numa aba nova, que devolve um form que se submete sozinho.
            ("POST", "/sc_form/"): _html("F1", "<p>gerando</p><script>(()=>{const f=document.createElement"
                                         "('form');f.method='post';f.action='/blank_laudo_pdf/';"
                                         + _campos_js([("nmgp_opcao", "imprimir_normal"), ("funcao", "gerar_pdf"),
                                                       ("dados", m["req_pdf"])])
                                         + "document.body.appendChild(f);f.submit();})()</script>"),
            ("POST", "/blank_laudo_pdf/"): _html(
                "Validade da assinatura",
                '<link rel="stylesheet" href="/estilo.css"><img src="/logo.png">'
                '<object type="application/pdf" data="data:application/pdf;base64,JVBERi0xLjQKJSVFT0YK"></object>'
                "<script>fetch('/dados.json').then(r=>r.text())</script>"),
            ("GET", "/final"): _html("Final", '<p>fim da cadeia</p><script src="/final.js"></script>'),
            ("POST", "/grande/"): _html("Grande", "<p>ok</p>"),
            ("GET", "/janela"): _html(
                "Janela", '<iframe src="/janela_q1"></iframe>'
                f'<iframe src="{self.outro}/janela_oop"></iframe>'
                "<script>fetch('/janela_xhr?nmgp_opcao=ajax_x',{method:'POST',headers:{'Content-Type':"
                f"'application/x-www-form-urlencoded'}},body:'funcao=buscar_sala&seg='+atob('{_b64(m['req_xhr'])}')}});"
                # fetch acima de 64 KB: o corpo não vem no evento.
                "fetch('/janela_grande?nmgp_opcao=ajax_g',{method:'POST',headers:{'Content-Type':"
                f"'application/x-www-form-urlencoded'}},body:atob('{_b64('funcao=funcao_oculta_fetch&x=' + m['req_xhr_grande'])}')"
                "+'&pad='+'a'.repeat(70000)})"
                "</script>"),
            ("GET", "/janela_q1"): _html("JQ1", '<p>janela q1</p><iframe src="/quadro2"></iframe>'),
            ("GET", "/janela_oop"): _html("JOOP", '<p>janela oop</p><script src="/janela_oop.js"></script>'),
            ("POST", "/janela_xhr"): "{}",
            ("POST", "/janela_grande"): "{}",
        }
        if (metodo, caminho) in paginas:
            tipo = {"Content-Type": "application/json"} if caminho.startswith("/janela_") and metodo == "POST" else html
            return 200, tipo, paginas[(metodo, caminho)]
        if (metodo, caminho) == ("POST", "/redir1"):
            return 302, {"Location": "/redir2?etapa=2"}, ""
        if caminho == "/redir2":
            return 303, {"Location": "/final"}, ""
        estaticos = {
            "/estilo.css": ("text/css", f"/* {m['resp_css']} */ body{{color:#000}}"),
            "/dados.json": ("application/json", json.dumps({"segredo": m["resp_json"]})),
            "/final.js": ("application/javascript", f"var x='{m['resp_js']}';"),
            "/janela_oop.js": ("application/javascript", f"var y='{m['resp_oop']}';"),
            "/logo.png": ("image/png", b"\x89PNG\r\n\x1a\n"),
            "/pixel.png": ("image/png", b"\x89PNG\r\n\x1a\n"),
        }
        if caminho in estaticos:
            tipo, conteudo = estaticos[caminho]
            return 200, {"Content-Type": tipo}, conteudo
        return 404, html, _html("404", "nada")


def _executar_na_aba(cdp_url, prefixo, expressao):
    """Faz o papel do usuário: executa JS na aba, por uma conexão do teste (não do gravador)."""
    with urllib.request.urlopen(cdp_url + "/json/list", timeout=5) as resposta:
        abas = [a for a in json.load(resposta) if a.get("type") == "page" and a["url"].startswith(prefixo)]
    assert abas, f"aba {prefixo} não encontrada"
    ws = WS_ORIGINAL(abas[0]["webSocketDebuggerUrl"], suppress_origin=True, timeout=15)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": expressao, "userGesture": True}}))
        while json.loads(ws.recv()).get("id") != 1:
            pass
    finally:
        ws.close()


class _WsEspiao:
    def __init__(self, ws, registro):
        self._ws = ws
        self._registro = registro

    def send(self, dados, *args, **kwargs):
        self._registro.append(json.loads(dados))
        return self._ws.send(dados, *args, **kwargs)

    def __getattr__(self, nome):
        return getattr(self._ws, nome)


class GravadorEmTeste:
    """Roda ``executar`` numa thread, com websocket e HTTP espionados."""

    def __init__(self, monkeypatch, porta, saida, rede):
        self.enviados = []
        self.rotas_http = []
        self.parar = threading.Event()
        self.args = argparse.Namespace(host="127.0.0.1", porta=porta, saida=str(saida), espera=ESPERA, rede=rede)
        self.saida = Path(saida)
        urlopen_original = urllib.request.urlopen

        def urlopen(url, *a, **k):
            if threading.current_thread().name == "gravador":
                self.rotas_http.append(urllib.parse.urlsplit(url).path)
            return urlopen_original(url, *a, **k)

        def create_connection(url, *a, **k):
            return _WsEspiao(WS_ORIGINAL(url, *a, **k), self.enviados)

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        monkeypatch.setattr(websocket, "create_connection", create_connection)
        self.thread = threading.Thread(target=self._rodar, name="gravador", daemon=True)

    def _rodar(self):
        self.codigo = grav.executar(self.args, self.parar)

    def iniciar(self):
        self.thread.start()

    def encerrar(self):
        self.parar.set()
        self.thread.join(timeout=30)
        assert not self.thread.is_alive(), "gravador não encerrou"

    def log(self):
        caminho = self.saida / "sessao.log"
        if not caminho.exists():
            return []
        return [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]

    def rede(self):
        linhas = []
        for arquivo in sorted(self.saida.glob("rede-*.jsonl")):
            linhas += [json.loads(l) for l in arquivo.read_text(encoding="utf-8").splitlines() if l.strip()]
        return linhas

    def capturou(self, caminho):
        return any(e["evento"] == "CAPTURA" and urllib.parse.urlsplit(e["url"]).path == caminho
                   for e in self.log())


def _caminho(url):
    partes = urllib.parse.urlsplit(url)
    return partes.path + (f"?{partes.query}" if partes.query else "")


def _vazamentos(saida, marcadores):
    achados = []
    for arquivo in Path(saida).rglob("*"):
        if arquivo.is_file():
            texto = arquivo.read_bytes().decode("utf-8", "replace")
            achados += [f"{m} em {arquivo.name}" for m in marcadores if m in texto]
    return achados


@pytest.fixture
def servidor():
    s = ServidorSintetico()
    s.iniciar()
    yield s
    s.parar()


@pytest.fixture
def navegador(servidor):
    executavel = _chrome()
    if executavel is None:
        pytest.skip("Chrome/Chromium não encontrado (defina FLUXO_CHROME)")
    chrome = ChromeDescartavel(executavel, servidor.base + "/inicio")
    esperar(lambda: servidor.recebeu("GET", "/quadro2") and servidor.recebeu("GET", "/oop_inicio"))
    yield chrome
    chrome.fechar()


@pytest.fixture
def saida():
    pasta = tempfile.mkdtemp(prefix="fluxo-teste-gravador-")
    yield Path(pasta)
    shutil.rmtree(pasta, ignore_errors=True)


@pytest.fixture
def gravar(monkeypatch, navegador, saida):
    """Fábrica de GravadorEmTeste; encerra o gravador antes de apagar a pasta."""
    criados = []

    def criar(rede):
        gravador = GravadorEmTeste(monkeypatch, _porta(navegador), saida, rede)
        criados.append(gravador)
        gravador.iniciar()
        return gravador

    yield criar
    for gravador in criados:
        gravador.parar.set()
        gravador.thread.join(timeout=30)


def _porta(chrome):
    return int(chrome.cdp_url.rsplit(":", 1)[1])


# --- guardião de comandos (sem navegador) --------------------------------------

def test_guardiao_recusa_comandos_fora_da_lista():
    enviados = []

    class WsFalso:
        def send(self, dados):
            enviados.append(dados)

    conexao = grav.ConexaoCDP("ws://nao-usado", grav.METODOS_CDP_PERMITIDOS | grav.METODOS_CDP_REDE, None)
    conexao.ws = WsFalso()
    for metodo in ("Runtime.evaluate", "Network.getResponseBody", "Network.getRequestPostData",
                   "Target.attachToTarget", "Target.createTarget", "Target.closeTarget",
                   "Target.setDiscoverTargets", "Page.navigate", "Input.dispatchMouseEvent"):
        with pytest.raises(RuntimeError, match="não permitido"):
            conexao.enviar(metodo, esperar=False)
    assert enviados == []
    assert grav.METODOS_CDP_PERMITIDOS == {
        "Page.enable", "DOM.getDocument", "DOM.getOuterHTML", "DOM.disable",
        "Target.setAutoAttach", "Runtime.runIfWaitingForDebugger"}
    assert grav.METODOS_CDP_REDE == {"Network.enable"}
    assert grav.ROTAS_HTTP_PERMITIDAS == {"/json/version"}
    assert grav.PARAMS_AUTO_ATTACH["waitForDebuggerOnStart"] and grav.PARAMS_AUTO_ATTACH["flatten"]


# --- abas novas desde a 1ª requisição -------------------------------------------

def test_abas_novas_registradas_desde_a_primeira_requisicao(servidor, navegador, saida, gravar):
    v = Verificacoes()
    m = servidor.m
    inicio_servidor = len(servidor.recebidas())
    gravador = gravar(rede=True)
    assert esperar(lambda: gravador.capturou("/inicio") and gravador.capturou("/oop_inicio")), gravador.log()

    cdp, base = navegador.cdp_url, servidor.base
    # 1. Imprimir: F1 multipart com target=_blank -> aba nova -> POST /blank_laudo_pdf/.
    _executar_na_aba(cdp, base + "/inicio", _form_js(
        "/sc_form/?nmgp_opcao=formphp",
        [("funcao", "imprimir_normal"), ("campo", m["req_imprimir"])], enctype="multipart/form-data"))
    assert esperar(lambda: servidor.recebeu("GET", "/dados.json") and gravador.capturou("/blank_laudo_pdf/"))
    # 2. Redirecionamento em cadeia na aba nova: POST 302 -> GET 303 -> GET.
    _executar_na_aba(cdp, base + "/inicio", _form_js(
        "/redir1?nmgp_opcao=ajax_navegar", [("funcao", "consultar"), ("x", m["req_redir"])]))
    assert esperar(lambda: servidor.recebeu("GET", "/final.js") and gravador.capturou("/final"))
    # 3. 1º POST da aba nova com corpo acima de 64 KB (navegação: o corpo vem inteiro no evento).
    _executar_na_aba(cdp, base + "/inicio", _form_js(
        "/grande/?nmgp_opcao=igual",
        [("nmgp_opcao", "opcao_grande"), ("funcao", "funcao_grande"), ("pad", m["req_grande"] + "a" * 70000)]))
    assert esperar(lambda: servidor.recebeu("POST", "/grande/?nmgp_opcao=igual") and gravador.capturou("/grande/"))
    # 4. window.open de página com iframes (mesmo site aninhado e outro site).
    _executar_na_aba(cdp, base + "/inicio", "window.open('/janela')")
    assert esperar(lambda: servidor.recebeu("GET", "/janela_oop.js")
                   and servidor.recebeu("POST", "/janela_xhr?nmgp_opcao=ajax_x")
                   and servidor.recebeu("POST", "/janela_grande?nmgp_opcao=ajax_g")
                   and gravador.capturou("/janela") and gravador.capturou("/janela_oop"))
    # 5. Não regressão na aba existente: navegação só em iframe e pushState.
    _executar_na_aba(cdp, base + "/inicio", "document.querySelector('iframe').src='/quadro3'")
    assert esperar(lambda: servidor.recebeu("GET", "/quadro3"))
    time.sleep(ESPERA + 1.5)
    _executar_na_aba(cdp, base + "/inicio", "history.pushState({}, '', '/inicio/estado2')")
    assert esperar(lambda: gravador.capturou("/inicio/estado2"))
    time.sleep(ESPERA + 1.0)
    gravador.encerrar()

    log, rede = gravador.log(), gravador.rede()
    requisicoes = [l for l in rede if l["evento"] == "requisicao"]
    capturas = [e for e in log if e["evento"] == "CAPTURA"]
    conectados = {e["alvo"]: e for e in log if e["evento"] == "CONECTADO"}

    def alvo_da_captura(sufixo):
        return next((c["alvo"] for c in capturas if c["url"].endswith(sufixo)), None)

    def reqs(alvo):
        return [r for r in requisicoes if r["alvo"] == alvo]

    def req(caminho, metodo=None):
        achadas = [r for r in requisicoes if _caminho(r["url"]) == caminho and (metodo is None or r["metodo"] == metodo)]
        return achadas[0] if len(achadas) == 1 else None

    aba_a = alvo_da_captura("/inicio")
    v(aba_a and not conectados[aba_a]["pausado"], "aba existente anexada sem pausa")

    # 1. Imprimir
    f1 = req("/sc_form/?nmgp_opcao=formphp", "POST")
    v(f1 is not None, "POST F1 registrado uma vez")
    aba_x = f1 and f1["alvo"]
    v(aba_x and aba_x != aba_a, "POST F1 na aba nova, não na aba de origem")
    v(aba_x and reqs(aba_x)[0] is f1, "1ª requisição da aba do Imprimir é o POST F1")
    v(f1 and f1["tipo"] == "Document" and f1["tipo_corpo"].startswith("multipart/form-data"), "F1: Document multipart")
    v(f1 and f1.get("nmgp_opcao_url") == "formphp" and "nmgp_opcao_corpo" not in f1
      and "funcao_corpo" not in f1, "F1: nmgp_opcao da query; multipart não analisado")
    pdf = req("/blank_laudo_pdf/", "POST")
    v(pdf is not None and pdf["alvo"] == aba_x, "POST /blank_laudo_pdf/ registrado na aba do Imprimir")
    v(pdf and pdf.get("nmgp_opcao_corpo") == "imprimir_normal" and pdf.get("funcao_corpo") == "gerar_pdf",
      "blank_laudo_pdf: nmgp_opcao e funcao do corpo")
    v(pdf and pdf.get("tipo_corpo") == "application/x-www-form-urlencoded", "blank_laudo_pdf: urlencoded")
    for recurso in ("/estilo.css", "/logo.png", "/dados.json"):
        r = req(recurso, "GET")
        v(r is not None and r["alvo"] == aba_x, f"recurso {recurso} registrado na aba do Imprimir")
    v(all(r["url"].endswith(",...") for r in requisicoes if r["url"].startswith("data:")),
      "URLs data: (PDF inline) registradas sem conteúdo")
    respostas = {(l["requestId"], l["status"]) for l in rede if l["evento"] == "resposta"}
    v(f1 and (f1["requestId"], 200) in respostas and pdf and (pdf["requestId"], 200) in respostas,
      "respostas 200 do F1 e do PDF")
    v(aba_x in conectados and conectados[aba_x]["pausado"] and conectados[aba_x].get("aberta_por") == aba_a,
      "aba do Imprimir anexada pausada, aberta pela aba de origem")
    v(alvo_da_captura("/blank_laudo_pdf/") == aba_x, "snapshot da página do PDF na aba do Imprimir")

    # 2. Redirecionamentos
    r1 = req("/redir1?nmgp_opcao=ajax_navegar", "POST")
    aba_y = r1 and r1["alvo"]
    v(r1 is not None and aba_y not in (aba_a, aba_x), "POST redir1 numa aba nova")
    v(aba_y and reqs(aba_y)[0] is r1, "1ª requisição da aba do redirecionamento é o POST")
    v(r1 and r1.get("nmgp_opcao_url") == "ajax_navegar" and r1.get("funcao_corpo") == "consultar",
      "redir1: nmgp_opcao da query e funcao do corpo")
    r2, r3 = req("/redir2?etapa=2", "GET"), req("/final", "GET")
    v(r2 and r2.get("status_redirecionamento") == 302 and r2["requestId"] == r1["requestId"],
      "redir2 com status_redirecionamento 302 no mesmo requestId")
    v(r3 and r3.get("status_redirecionamento") == 303 and r3["requestId"] == r1["requestId"],
      "final com status_redirecionamento 303 no mesmo requestId")
    v(r3 and (r3["requestId"], 200) in respostas, "final respondeu 200")
    v(req("/final.js", "GET") and req("/final.js", "GET")["alvo"] == aba_y, "final.js na aba do redirecionamento")

    # 3. Corpo grande
    g = req("/grande/?nmgp_opcao=igual", "POST")
    aba_z = g and g["alvo"]
    v(g is not None and aba_z not in (aba_a, aba_x, aba_y), "POST grande numa aba nova")
    v(aba_z and reqs(aba_z)[0] is g, "1ª requisição da aba do corpo grande é o POST")
    v(g and g.get("nmgp_opcao_url") == "igual" and g.get("nmgp_opcao_corpo") == "opcao_grande"
      and g.get("funcao_corpo") == "funcao_grande" and "corpo_fora_do_evento" not in g,
      "POST de navegação acima de 64 KB: nmgp_opcao e funcao do corpo extraídos")

    # 4. window.open com iframes
    j = req("/janela", "GET")
    aba_w = j and j["alvo"]
    v(j is not None and j["tipo"] == "Document" and aba_w not in (aba_a, aba_x, aba_y, aba_z),
      "GET /janela numa aba nova")
    v(aba_w and reqs(aba_w)[0] is j, "1ª requisição da janela é o documento")
    v(aba_w in conectados and conectados[aba_w]["pausado"] and conectados[aba_w].get("aberta_por") == aba_a,
      "janela anexada pausada, aberta pela aba de origem")
    for caminho in ("/janela_q1", "/janela_oop"):
        v(req(caminho, "GET") is not None, f"documento do iframe {caminho} registrado")
    v(sum(1 for r in reqs(aba_w) if _caminho(r["url"]) == "/quadro2") == 1, "iframe aninhado registrado na janela")
    x = req("/janela_xhr?nmgp_opcao=ajax_x", "POST")
    v(x and x["alvo"] == aba_w and x.get("nmgp_opcao_url") == "ajax_x" and x.get("funcao_corpo") == "buscar_sala",
      "fetch imediato da janela com nmgp_opcao e funcao")
    xg = req("/janela_grande?nmgp_opcao=ajax_g", "POST")
    v(xg and xg["alvo"] == aba_w and xg.get("corpo_fora_do_evento") is True and xg.get("funcao_fora_do_evento") is True
      and xg.get("nmgp_opcao_url") == "ajax_g" and "funcao_corpo" not in xg and "nmgp_opcao_corpo" not in xg,
      "fetch imediato acima de 64 KB marcado fora do evento, só com o valor da query")
    js_oop = req("/janela_oop.js", "GET")
    alvo_oop = js_oop and js_oop["alvo"]
    v(alvo_oop and alvo_oop != aba_w and conectados.get(alvo_oop, {}).get("tipo") == "iframe",
      "recurso do iframe de outro site registrado no alvo do iframe")
    cap_janela = next((c for c in capturas if c["alvo"] == aba_w and c["url"].endswith("/janela")), None)
    v(cap_janela and [q["url"].rsplit("/", 1)[1] for q in cap_janela["quadros"]] == ["janela_q1", "quadro2"],
      "snapshot da janela com os 2 iframes do mesmo site")
    cap_oop = next((c for c in capturas if c["url"].endswith("/janela_oop")), None)
    v(cap_oop and cap_oop["alvo"] == alvo_oop and cap_oop["alvo_pai"] == aba_w,
      "snapshot do iframe de outro site ligado à janela (alvo_pai)")

    # 5. Não regressão na aba existente
    cap_oop_a = next((c for c in capturas if c["url"].endswith("/oop_inicio")), None)
    v(cap_oop_a and cap_oop_a["alvo_pai"] == aba_a and not conectados[cap_oop_a["alvo"]]["pausado"],
      "iframe de outro site existente capturado, ligado à aba")
    v(req("/quadro3", "GET") and req("/quadro3", "GET")["alvo"] == aba_a, "navegação do iframe registrada")
    v(any(c["alvo"] == aba_a and any(q["url"].endswith("/quadro3") for q in c["quadros"]) for c in capturas),
      "navegação só em iframe gerou snapshot da aba")
    v(any(c["alvo"] == aba_a and c["url"].endswith("/inicio/estado2") for c in capturas), "pushState capturado")

    # Tudo o que o servidor recebeu está no jsonl.
    no_servidor = collections.Counter((r["metodo"], r["caminho"]) for r in servidor.recebidas(inicio_servidor))
    no_jsonl = collections.Counter((r["metodo"], _caminho(r["url"])) for r in requisicoes
                                   if r["url"].startswith((servidor.base, servidor.outro)))
    faltando = {k: n for k, n in no_servidor.items() if no_jsonl[k] < n}
    v(not faltando, f"requisições do servidor ausentes do jsonl: {faltando}")
    v(all(no_servidor[k] >= n for k, n in no_jsonl.items()), "jsonl não inventa requisições locais")
    print(f"\n  servidor recebeu {sum(no_servidor.values())} requisições durante a gravação; "
          f"jsonl tem {len(requisicoes)} (inclui data: e outras sem servidor)")
    v(all("Chrome" in r["agente"] for r in servidor.recebidas()), "toda requisição veio do Chrome")
    corpo_pdf = next(r["corpo"] for r in servidor.recebidas() if r["caminho"] == "/blank_laudo_pdf/")
    v(m["req_pdf"].encode() in corpo_pdf, "corpo do POST chegou intacto ao servidor")

    # Resumo com a chave de 4+1 elementos.
    resumo = json.loads((saida / "rede-resumo.json").read_text(encoding="utf-8"))
    tuplas = {(t["metodo"], t["caminho"], t["nmgp_opcao"], t["funcao"], t.get("corpo_fora_do_evento", False)): t
              for t in resumo["tuplas"]}
    v(resumo["sessoes"] == 1, "resumo com 1 sessão")
    v(all(set(t) - {"corpo_fora_do_evento"} == {"metodo", "caminho", "nmgp_opcao", "funcao", "contagem",
                                                "status", "origens"} for t in resumo["tuplas"]),
      "tuplas só com os campos do resumo")
    v(("POST", "/sc_form/", "formphp", "", False) in tuplas, "tupla do F1")
    v(tuplas.get(("POST", "/blank_laudo_pdf/", "imprimir_normal", "gerar_pdf", False), {}).get("status") == {"200": 1},
      "tupla do blank_laudo_pdf com status 200")
    v(("POST", "/grande/", "opcao_grande", "funcao_grande", False) in tuplas, "tupla do POST grande de navegação")
    v(("POST", "/janela_grande", "ajax_g", "", True) in tuplas, "tupla do fetch grande à parte (corpo_fora_do_evento)")
    v(("POST", "/redir1", "ajax_navegar", "consultar", False) in tuplas, "tupla do POST redirecionado")

    # Nenhum vazamento de corpo.
    ocultos = list(m.values()) + ["funcao_oculta_fetch"]
    v(not _vazamentos(saida, ocultos), f"vazamentos: {_vazamentos(saida, ocultos)}")

    # Só comandos permitidos, e na ordem certa.
    metodos = [c["method"] for c in gravador.enviados]
    permitidos = grav.METODOS_CDP_PERMITIDOS | grav.METODOS_CDP_REDE
    v(set(metodos) <= permitidos, f"comandos fora da lista: {set(metodos) - permitidos}")
    v(not [x for x in metodos if x.startswith(PROIBIDOS)], "nenhum comando proibido")
    v({"Target.setAutoAttach", "Runtime.runIfWaitingForDebugger", "Network.enable"} <= set(metodos),
      "auto-attach, soltura e Network.enable enviados")
    v([c["method"] for c in gravador.enviados if "sessionId" not in c] == ["Target.setAutoAttach"],
      "no navegador, só Target.setAutoAttach")
    soltas = [c["sessionId"] for c in gravador.enviados if c["method"] == "Runtime.runIfWaitingForDebugger"]
    v(len(soltas) >= 5, f"abas novas e iframes soltos após a preparação ({len(soltas)})")
    for sessao in soltas:
        ordem = [c["method"] for c in gravador.enviados if c.get("sessionId") == sessao]
        v(ordem[:4] == ["Network.enable", "Page.enable", "Target.setAutoAttach",
                        "Runtime.runIfWaitingForDebugger"], f"preparação antes de soltar: {ordem[:4]}")
    v(gravador.rotas_http and set(gravador.rotas_http) == {"/json/version"}, f"HTTP: {gravador.rotas_http}")

    # Encerramento limpo.
    v(gravador.codigo == 0, "executar devolveu 0")
    v(not [e for e in log if e["evento"] == "ERRO"], f"erros no log: {[e for e in log if e['evento'] == 'ERRO']}")
    fim = [e for e in log if e["evento"] == "FIM"]
    v(len(fim) == 1 and fim[0]["erros"] == 0 and fim[0]["requisicoes"] == len(requisicoes), "FIM com contagens")
    v(sum(1 for e in log if e["evento"] == "DESCONECTADO") == len(conectados), "todas as sessões desconectadas")
    v.concluir("abas novas")


def test_sem_rede_nao_liga_network_e_captura_aba_nova(servidor, navegador, saida, gravar):
    v = Verificacoes()
    gravador = gravar(rede=False)
    assert esperar(lambda: gravador.capturou("/inicio"))
    _executar_na_aba(navegador.cdp_url, servidor.base + "/inicio", "window.open('/janela')")
    assert esperar(lambda: gravador.capturou("/janela") and gravador.capturou("/janela_oop"))
    gravador.encerrar()
    metodos = {c["method"] for c in gravador.enviados}
    v(metodos <= grav.METODOS_CDP_PERMITIDOS, f"comandos: {metodos}")
    v(not any(x.startswith("Network.") for x in metodos), "nenhum Network.* sem --rede")
    v("Runtime.runIfWaitingForDebugger" in metodos, "aba nova solta")
    v(not list(saida.glob("rede-*")), "nenhum arquivo rede-* sem --rede")
    log = gravador.log()
    v(not [e for e in log if e["evento"] == "ERRO"], "sem ERRO")
    v(servidor.recebeu("POST", "/janela_xhr?nmgp_opcao=ajax_x"), "janela carregou por inteiro")
    v.concluir("sem --rede")


def test_processo_real_ctrl_break_e_kill_nao_travam_abas(servidor, navegador, saida):
    """Uso real (subprocesso): Ctrl+Break grava resumo e FIM; depois de parar ou morrer,
    o Chrome não fica com abas pausadas."""
    v = Verificacoes()
    windows = os.name == "nt"
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if windows else 0

    def iniciar():
        return subprocess.Popen(
            [sys.executable, str(SCRIPT), "--porta", str(_porta(navegador)), "--saida", str(saida),
             "--espera", str(ESPERA), "--rede"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)

    def log():
        caminho = saida / "sessao.log"
        return [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines()] if caminho.exists() else []

    processo = iniciar()
    v(esperar(lambda: any(e["evento"] == "CAPTURA" and e["url"].endswith("/inicio") for e in log())),
      "subprocesso conectou e capturou a aba existente")
    _executar_na_aba(navegador.cdp_url, servidor.base + "/inicio", _form_js(
        "/sc_form/?nmgp_opcao=formphp", [("funcao", "imprimir_normal")], enctype="multipart/form-data"))
    v(esperar(lambda: servidor.recebeu("GET", "/dados.json")), "Imprimir completou com o gravador rodando")
    time.sleep(ESPERA + 1.0)
    processo.send_signal(signal.CTRL_BREAK_EVENT if windows else signal.SIGINT)
    saida_console = processo.communicate(timeout=30)[0].decode("utf-8", "replace")
    v(processo.returncode == 0, f"código de saída {processo.returncode}: {saida_console[-500:]}")
    eventos = log()
    v([e["evento"] for e in eventos].count("FIM") == 1, "FIM gravado")
    v(not [e for e in eventos if e["evento"] == "ERRO"], f"sem ERRO: {[e for e in eventos if e['evento'] == 'ERRO']}")
    resumo = json.loads((saida / "rede-resumo.json").read_text(encoding="utf-8"))
    v(any(t["caminho"] == "/sc_form/" and t["nmgp_opcao"] == "formphp" for t in resumo["tuplas"]),
      "resumo com o POST F1 da aba nova")
    v("Resumo de rede desta sessão" in saida_console, "resumo impresso no console")

    # Depois do Ctrl+Break, uma aba nova carrega normalmente.
    antes = len(servidor.recebidas())
    _executar_na_aba(navegador.cdp_url, servidor.base + "/inicio", "window.open('/quadro3')")
    v(esperar(lambda: any(r["caminho"] == "/quadro3" for r in servidor.recebidas(antes)), limite=10),
      "aba nova carrega depois do Ctrl+Break")

    # Gravador morto sem aviso (kill): o Chrome solta a pausa e a aba nova carrega.
    processo = iniciar()
    v(esperar(lambda: [e["evento"] for e in log()].count("INICIO") == 2 and
              sum(1 for e in log() if e["evento"] == "CONECTADO") >= 4), "segundo gravador conectado")
    processo.kill()
    processo.wait(timeout=10)
    antes = len(servidor.recebidas())
    _executar_na_aba(navegador.cdp_url, servidor.base + "/inicio", "window.open('/quadro2')")
    v(esperar(lambda: any(r["caminho"] == "/quadro2" for r in servidor.recebidas(antes)), limite=10),
      "aba nova carrega depois de o gravador morrer")
    v.concluir("processo real")
