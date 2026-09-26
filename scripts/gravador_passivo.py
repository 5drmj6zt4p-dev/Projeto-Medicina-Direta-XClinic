"""Gravador passivo da Fase 0 (Etapa A).

Conecta ao Chrome JÁ ABERTO no perfil dedicado do projeto, via Chrome
DevTools Protocol (CDP), e grava cada navegação de cada aba:

- URL, título e horário, em ``<saida>/sessao.log`` (uma linha JSON por evento);
- snapshot do HTML (outerHTML do documento e de cada iframe), em
  ``<saida>/AAAA-MM-DD/HHMMSS-<slug>.html`` e
  ``HHMMSS-<slug>.qNN-<slug-do-quadro>.html``.

A pasta ``<saida>`` padrão é ``%LOCALAPPDATA%\\FluxoExames\\captures``, fora
do repositório, porque as capturas da Etapa B terão dados reais de paciente.

É estritamente passivo:

- usa só websocket-client puro. Não usa Playwright, que ao conectar injeta
  scripts de apoio e ajusta emulação nas páginas;
- só envia os comandos CDP de ``METODOS_CDP_PERMITIDOS``. Todos são de
  leitura ou de assinatura de eventos. Qualquer outro comando levanta erro
  antes de sair;
- não executa JavaScript na página (não usa ``Runtime.evaluate``);
- não clica, não digita, não navega, não abre nem fecha abas. Só observa os
  alvos que já existem (HTTP ``/json/list``; nunca ``/json/new``);
- o nome dos arquivos e o console usam só host e caminho da URL. Título e
  URL completa ficam apenas no ``sessao.log``.

Uso:
    python scripts/gravador_passivo.py [--porta 9222] [--saida PASTA]

Para parar: Ctrl+C.
"""

import argparse
import datetime
import hashlib
import itertools
import json
import os
import queue
import re
import signal
import sys
import threading
import time
import unicodedata
import urllib.request

import websocket

METODOS_CDP_PERMITIDOS = frozenset({
    "Page.enable",        # só assina eventos de navegação
    "DOM.getDocument",    # lê a árvore do DOM
    "DOM.getOuterHTML",   # lê o HTML de um nó
    "DOM.disable",        # para de receber eventos do DOM
})
ROTAS_HTTP_PERMITIDAS = frozenset({"/json/version", "/json/list"})
TIPOS_ALVO = frozenset({"page", "iframe"})
PREFIXOS_INTERNOS = ("chrome://", "chrome-extension://", "chrome-untrusted://",
                     "devtools://", "about:", "edge://")
EVENTOS_NAVEGACAO = frozenset({
    "Page.frameNavigated",
    "Page.navigatedWithinDocument",
    "Page.frameStoppedLoading",
    "Page.loadEventFired",
})
TIMEOUT_COMANDO = 20.0
INTERVALO_DESCOBERTA = 2.0
ESPERA_RECONEXAO = 5.0


def agora():
    return datetime.datetime.now().astimezone()


def slug(url, limite=60):
    """Host + caminho da URL em ASCII minúsculo. Ignora query e fragmento."""
    sem_esquema = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", url or "")
    base = re.split(r"[?#]", sem_esquema, maxsplit=1)[0]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower()
    return (base[:limite].rstrip("-")) or "sem-url"


def url_interna(url):
    return not url or url.startswith(PREFIXOS_INTERNOS)


def http_get_json(host, porta, rota):
    if rota not in ROTAS_HTTP_PERMITIDAS:
        raise RuntimeError(f"rota HTTP não permitida: {rota}")
    with urllib.request.urlopen(f"http://{host}:{porta}{rota}", timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def comentario_seguro(texto):
    return (texto or "").replace("--", "%2D%2D")


class Registro:
    """Log da sessão (JSON por linha) e arquivos de captura."""

    def __init__(self, raiz):
        self.raiz = raiz
        os.makedirs(raiz, exist_ok=True)
        self.caminho_log = os.path.join(raiz, "sessao.log")
        self._trava = threading.Lock()
        self.capturas = 0
        self.erros = 0

    def evento(self, nome_evento, **dados):
        linha = {"ts": agora().isoformat(timespec="seconds"), "evento": nome_evento, **dados}
        with self._trava:
            with open(self.caminho_log, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(linha, ensure_ascii=False) + "\n")

    def novo_arquivo(self, momento, nome):
        pasta = os.path.join(self.raiz, momento.strftime("%Y-%m-%d"))
        with self._trava:
            os.makedirs(pasta, exist_ok=True)
            caminho = os.path.join(pasta, nome + ".html")
            n = 2
            while os.path.exists(caminho):
                caminho = os.path.join(pasta, f"{nome}-{n}.html")
                n += 1
            open(caminho, "x", encoding="utf-8").close()  # reserva o nome
        return caminho


class SessaoAlvo(threading.Thread):
    """Uma conexão CDP com um alvo (aba ou iframe fora do processo)."""

    def __init__(self, alvo, registro, espera, parar):
        super().__init__(daemon=True, name=f"alvo-{alvo['id'][:8]}")
        self.alvo = alvo
        self.id_curto = alvo["id"][:8]
        self.registro = registro
        self.espera = espera
        self.parar = parar
        self.ws = None
        self._ids = itertools.count(1)
        self._pendentes = {}
        self._trava = threading.Lock()
        self._prazo = None
        self._motivo = None
        self._ultimo_hash = None
        self._fechado = threading.Event()

    # --- CDP -------------------------------------------------------------

    def enviar(self, metodo, params=None):
        if metodo not in METODOS_CDP_PERMITIDOS:
            raise RuntimeError(f"comando CDP não permitido: {metodo}")
        ident = next(self._ids)
        resposta = queue.Queue(maxsize=1)
        with self._trava:
            self._pendentes[ident] = resposta
        self.ws.send(json.dumps({"id": ident, "method": metodo, "params": params or {}}))
        try:
            msg = resposta.get(timeout=TIMEOUT_COMANDO)
        except queue.Empty:
            raise TimeoutError(f"{metodo} sem resposta") from None
        finally:
            with self._trava:
                self._pendentes.pop(ident, None)
        if "error" in msg:
            raise RuntimeError(f"{metodo}: {msg['error'].get('message')}")
        return msg.get("result", {})

    def _ler(self):
        try:
            while not self.parar.is_set():
                bruto = self.ws.recv()
                if not bruto:
                    continue
                msg = json.loads(bruto)
                if "id" in msg:
                    with self._trava:
                        destino = self._pendentes.get(msg["id"])
                    if destino:
                        destino.put(msg)
                elif msg.get("method") in EVENTOS_NAVEGACAO:
                    with self._trava:
                        self._prazo = time.monotonic() + self.espera
                        self._motivo = msg["method"].split(".", 1)[1]
        except (websocket.WebSocketException, OSError, ValueError):
            pass
        finally:
            self._fechado.set()

    # --- captura ---------------------------------------------------------

    def _html_documento(self, doc):
        partes = []
        for filho in doc.get("children", []):
            if filho.get("nodeType") == 10:
                partes.append(f"<!DOCTYPE {filho.get('nodeName', 'html')}>")
            elif filho.get("nodeType") == 1:
                partes.append(self.enviar("DOM.getOuterHTML", {"nodeId": filho["nodeId"]})["outerHTML"])
        return "\n".join(partes)

    @staticmethod
    def _quadros(no, achados):
        """Documentos de iframes no mesmo processo, em ordem de documento."""
        doc = no.get("contentDocument")
        if doc:
            achados.append(doc)
            SessaoAlvo._quadros(doc, achados)
        for filho in no.get("children", []):
            SessaoAlvo._quadros(filho, achados)
        return achados

    @staticmethod
    def _titulo(no):
        if no.get("nodeName") == "TITLE":
            return "".join(f.get("nodeValue", "") for f in no.get("children", []) if f.get("nodeType") == 3).strip()
        for filho in no.get("children", []):
            titulo = SessaoAlvo._titulo(filho)
            if titulo is not None:
                return titulo
        return None

    def capturar(self, motivo):
        raiz = self.enviar("DOM.getDocument", {"depth": -1, "pierce": True})["root"]
        url = raiz.get("documentURL") or self.alvo.get("url", "")
        if url_interna(url):
            self.enviar("DOM.disable")
            return
        principal = self._html_documento(raiz)
        quadros = [(q.get("documentURL", ""), self._html_documento(q)) for q in self._quadros(raiz, [])]
        self.enviar("DOM.disable")

        resumo = hashlib.sha256()
        for parte in [url, principal] + [u + h for u, h in quadros]:
            resumo.update(parte.encode("utf-8", "replace"))
        if resumo.hexdigest() == self._ultimo_hash:
            return
        self._ultimo_hash = resumo.hexdigest()

        momento = agora()
        carimbo = momento.isoformat(timespec="seconds")
        base = f"{momento:%H%M%S}-{slug(url)}"
        arquivo = self.registro.novo_arquivo(momento, base)
        nome_base = os.path.splitext(os.path.basename(arquivo))[0]
        cabecalho = (f"<!-- gravador_passivo | capturado_em={carimbo} | alvo={self.id_curto}"
                     f" | quadro=principal | url={comentario_seguro(url)} -->\n")
        with open(arquivo, "w", encoding="utf-8", newline="") as f:
            f.write(cabecalho + principal)

        lista_quadros = []
        for n, (url_q, html_q) in enumerate(quadros, 1):
            arq_q = self.registro.novo_arquivo(momento, f"{nome_base}.q{n:02d}-{slug(url_q, 40)}")
            with open(arq_q, "w", encoding="utf-8", newline="") as f:
                f.write(f"<!-- gravador_passivo | capturado_em={carimbo} | alvo={self.id_curto}"
                        f" | quadro={n} | url={comentario_seguro(url_q)} -->\n" + html_q)
            lista_quadros.append({"url": url_q, "arquivo": os.path.basename(arq_q)})

        self.registro.capturas += 1
        self.registro.evento(
            "CAPTURA", motivo=motivo, alvo=self.id_curto, tipo=self.alvo.get("type"),
            alvo_pai=(self.alvo.get("parentId") or "")[:8], url=url, titulo=self._titulo(raiz) or "",
            arquivo=os.path.relpath(arquivo, self.registro.raiz), quadros=lista_quadros,
        )
        print(f"{momento:%H:%M:%S}  captura  aba {self.id_curto}  {slug(url)}"
              f"  (+{len(quadros)} iframes)  [{motivo}]", flush=True)

    def _capturar_com_retentativa(self, motivo):
        for tentativa in (1, 2):
            try:
                self.capturar(motivo)
                return
            except (RuntimeError, TimeoutError) as erro:
                # O DOM pode mudar no meio da leitura (nó some); tenta de novo.
                if tentativa == 2 or self._fechado.is_set():
                    self.registro.erros += 1
                    self.registro.evento("ERRO", alvo=self.id_curto, motivo=motivo, detalhe=str(erro))
                    return
                time.sleep(0.5)

    # --- ciclo -----------------------------------------------------------

    def run(self):
        try:
            self.ws = websocket.create_connection(
                self.alvo["webSocketDebuggerUrl"], timeout=None,
                suppress_origin=True, enable_multithread=True)
        except (websocket.WebSocketException, OSError) as erro:
            self.registro.evento("ERRO", alvo=self.id_curto, detalhe=f"conexão: {erro}")
            return
        leitor = threading.Thread(target=self._ler, daemon=True, name=f"leitor-{self.id_curto}")
        leitor.start()
        self.registro.evento("CONECTADO", alvo=self.id_curto, tipo=self.alvo.get("type"))
        try:
            self.enviar("Page.enable")
            self._capturar_com_retentativa("inicial")
            while not self.parar.is_set() and not self._fechado.is_set():
                with self._trava:
                    pronto = self._prazo is not None and time.monotonic() >= self._prazo
                    motivo = self._motivo
                    if pronto:
                        self._prazo = None
                if pronto:
                    self._capturar_com_retentativa(motivo)
                time.sleep(0.2)
        except Exception as erro:  # qualquer falha encerra só esta aba, com registro
            if not self.parar.is_set():
                self.registro.erros += 1
                self.registro.evento("ERRO", alvo=self.id_curto, detalhe=f"{type(erro).__name__}: {erro}")
        finally:
            self.fechar()
            self.registro.evento("DESCONECTADO", alvo=self.id_curto)

    def fechar(self):
        try:
            if self.ws:
                self.ws.close()
        except (websocket.WebSocketException, OSError):
            pass


def main():
    padrao = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "FluxoExames", "captures")
    p = argparse.ArgumentParser(description="Gravador passivo (Fase 0): grava navegações do Chrome dedicado via CDP.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--porta", type=int, default=9222)
    p.add_argument("--saida", default=padrao, help=f"pasta das capturas (padrão: {padrao})")
    p.add_argument("--espera", type=float, default=1.5,
                   help="segundos sem novos eventos de navegação antes do snapshot (padrão: 1.5)")
    args = p.parse_args()

    try:
        versao = http_get_json(args.host, args.porta, "/json/version")
    except OSError as erro:
        print(f"Chrome não responde em http://{args.host}:{args.porta} ({erro}).\n"
              "Abra o Chrome do perfil dedicado com --remote-debugging-port (ver docs/FASE-0-ETAPA-A.md).",
              file=sys.stderr)
        return 2

    if hasattr(signal, "SIGBREAK"):  # Windows: Ctrl+Break encerra igual a Ctrl+C
        signal.signal(signal.SIGBREAK, signal.default_int_handler)

    registro = Registro(os.path.abspath(args.saida))
    registro.evento("INICIO", navegador=versao.get("Browser"), porta=args.porta, pid=os.getpid())
    print(f"Conectado a {versao.get('Browser')} na porta {args.porta}.")
    print(f"Capturas em {registro.raiz}")
    print("Modo passivo: nenhuma interação com as páginas. Ctrl+C para parar.", flush=True)

    parar = threading.Event()
    sessoes = {}
    inicios = {}
    try:
        while True:
            try:
                alvos = http_get_json(args.host, args.porta, "/json/list")
            except OSError as erro:
                registro.evento("ERRO", detalhe=f"/json/list: {erro}")
                alvos = None
            if alvos is not None:
                vistos = set()
                for alvo in alvos:
                    if alvo.get("type") not in TIPOS_ALVO or not alvo.get("webSocketDebuggerUrl"):
                        continue
                    if alvo.get("url", "").startswith("devtools://"):
                        continue
                    vistos.add(alvo["id"])
                    atual = sessoes.get(alvo["id"])
                    if atual and atual.is_alive():
                        continue
                    if time.monotonic() - inicios.get(alvo["id"], -ESPERA_RECONEXAO) < ESPERA_RECONEXAO:
                        continue
                    inicios[alvo["id"]] = time.monotonic()
                    sessoes[alvo["id"]] = SessaoAlvo(alvo, registro, args.espera, parar)
                    sessoes[alvo["id"]].start()
                for ident in list(sessoes):
                    if ident not in vistos and not sessoes[ident].is_alive():
                        del sessoes[ident]
                        inicios.pop(ident, None)
            fim = time.monotonic() + INTERVALO_DESCOBERTA
            while time.monotonic() < fim:
                time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        parar.set()
        for sessao in sessoes.values():
            sessao.fechar()
        for sessao in sessoes.values():
            sessao.join(timeout=3)
        registro.evento("FIM", capturas=registro.capturas, erros=registro.erros)
        print(f"\nEncerrado. {registro.capturas} capturas, {registro.erros} erros. Log: {registro.caminho_log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
