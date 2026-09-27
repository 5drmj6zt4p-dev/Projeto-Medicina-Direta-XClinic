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
- não clica, não digita, não navega, não abre nem fecha abas. Por HTTP, só
  lê ``/json/version`` (nunca ``/json/new``);
- o nome dos arquivos e o console usam só host e caminho da URL. Título e
  URL completa ficam apenas no ``sessao.log``.

Anexação (Etapa D): uma só conexão, no websocket do navegador, com
``Target.setAutoAttach`` (``flatten``, ``waitForDebuggerOnStart``). O Chrome
anexa o gravador às abas que já existem e, dali em diante, a cada aba nova
(e a cada iframe de outro site, via o mesmo comando na sessão da aba) no
momento em que ela nasce, **pausada antes da primeira requisição**. O
gravador liga ``Network.enable``, ``Page.enable`` e o auto-attach dos filhos
nessa sessão e só então solta a aba com ``Runtime.runIfWaitingForDebugger``.
Assim nenhuma requisição escapa entre a criação da aba e a anexação (antes,
as abas eram descobertas por ``/json/list`` a cada 2 s e perdiam as
primeiras requisições: o POST do Imprimir, por exemplo). A aba é solta
mesmo se a preparação falhar, e o Chrome solta sozinho as abas pausadas se
a conexão cair.

Opção ``--rede`` (desligada por padrão): observação passiva das requisições,
para montar o mapa de operações do ScriptCase que alimenta
``fluxo_exames/guard.py``. Em cada alvo, envia ``Network.enable`` e processa
só ``Network.requestWillBeSent``, ``Network.responseReceived`` e
``Network.loadingFailed``:

- grava em ``<saida>/rede-AAAA-MM-DD.jsonl`` horário, requestId, método, URL
  completa, tipo do recurso e status;
- da query e do corpo de um POST ``application/x-www-form-urlencoded`` (o
  ``postData`` que já vem no evento), extrai só os valores de ``nmgp_opcao``
  e de ``funcao`` (operação dos endpoints ``blank_*_funcoes``). O resto do
  corpo é descartado na memória e nunca é gravado;
- nunca pede conteúdo: ``Network.getResponseBody``,
  ``Network.getRequestPostData`` e afins são recusados como qualquer outro
  comando fora da lista;
- ao parar, imprime e salva em ``<saida>/rede-resumo.json`` as tuplas
  distintas (método, caminho, nmgp_opcao, funcao) com contagem.

Uso:
    python scripts/gravador_passivo.py [--porta 9222] [--saida PASTA] [--rede]

Para parar: Ctrl+C.
"""

import argparse
import base64
import collections
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
import urllib.parse
import urllib.request

import websocket

METODOS_CDP_PERMITIDOS = frozenset({
    "Page.enable",        # só assina eventos de navegação
    "DOM.getDocument",    # lê a árvore do DOM
    "DOM.getOuterHTML",   # lê o HTML de um nó
    "DOM.disable",        # para de receber eventos do DOM
    # Etapa D. Anexa o gravador às abas e aos iframes de outro site no momento
    # em que nascem, pausados antes da 1ª requisição. Não cria, fecha nem
    # navega alvos. Target.attachToTarget, createTarget, closeTarget e afins
    # continuam de fora: o auto-attach já cobre os alvos que existem.
    "Target.setAutoAttach",
    # Etapa D. Solta o alvo que o auto-attach segurou, depois de Network.enable
    # e Page.enable já valerem. Não executa JavaScript: só libera o carregamento
    # pausado. É o único comando que desfaz a pausa de waitForDebuggerOnStart,
    # por isso não há como usar o auto-attach com pausa sem ele.
    "Runtime.runIfWaitingForDebugger",
})
# Só com --rede. Network.enable liga o envio de eventos de rede; dos eventos
# que chegam, só EVENTOS_REDE são processados. Comandos que buscam conteúdo
# (Network.getResponseBody, Network.getRequestPostData...) ficam de fora.
METODOS_CDP_REDE = frozenset({"Network.enable"})
EVENTOS_REDE = frozenset({
    "Network.requestWillBeSent",
    "Network.responseReceived",
    "Network.loadingFailed",
})
# Buffers de conteúdo zerados: o Chrome não guarda corpos para esta conexão.
# maxPostDataSize garante que o postData de formulários venha no próprio evento.
PARAMS_NETWORK_ENABLE = {"maxTotalBufferSize": 0, "maxResourceBufferSize": 0, "maxPostDataSize": 65536}
PARAMETRO_OPERACAO = "nmgp_opcao"
PARAMETRO_FUNCAO = "funcao"  # operação dos endpoints blank_*_funcoes
FORMULARIO = "application/x-www-form-urlencoded"
LIMITE_REQUISICOES_ABERTAS = 5000
ROTAS_HTTP_PERMITIDAS = frozenset({"/json/version"})
TIPOS_ALVO = frozenset({"page", "iframe"})
# Só abas e iframes de outro site são anexados (e pausados). Workers, service
# workers, "tab" e o próprio navegador ficam de fora e seguem sem pausa.
PARAMS_AUTO_ATTACH = {
    "autoAttach": True,
    "waitForDebuggerOnStart": True,
    "flatten": True,
    "filter": [{"type": t, "exclude": False} for t in sorted(TIPOS_ALVO)] + [{"exclude": True}],
}
PREFIXOS_INTERNOS = ("chrome://", "chrome-extension://", "chrome-untrusted://",
                     "devtools://", "about:", "edge://")
EVENTOS_NAVEGACAO = frozenset({
    "Page.frameNavigated",
    "Page.navigatedWithinDocument",
    "Page.frameStoppedLoading",
    "Page.loadEventFired",
})
TIMEOUT_COMANDO = 20.0
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


def url_registravel(url):
    """URL como vai para o log de rede. De ``data:`` fica só o tipo, não o conteúdo."""
    url = url or ""
    if url.startswith("data:"):
        return url.split(",", 1)[0][:100] + ",..."
    return url


def tipo_conteudo(cabecalhos):
    for nome, valor in (cabecalhos or {}).items():
        if nome.lower() == "content-type":
            return str(valor).split(";", 1)[0].strip().lower()
    return None


def operacoes(consulta):
    """(nmgp_opcao, funcao) numa query string ou corpo urlencoded.

    De cada chave vale o último valor; None se a chave não aparece. Nada
    além desses dois valores sai desta função.
    """
    achados = {}
    for k, v in urllib.parse.parse_qsl(consulta or "", keep_blank_values=True):
        if k in (PARAMETRO_OPERACAO, PARAMETRO_FUNCAO):
            achados[k] = v
    return achados.get(PARAMETRO_OPERACAO), achados.get(PARAMETRO_FUNCAO)


def operacoes_no_corpo(requisicao):
    """(nmgp_opcao, funcao) do corpo form-urlencoded que veio no evento.

    Devolve (opcao, funcao, disponivel). ``disponivel`` é False quando o
    corpo é form-urlencoded mas não veio no evento (mais de 64 KB): os dois
    valores ficam desconhecidos e o corpo não é buscado. O corpo só existe
    dentro desta função e não é devolvido nem gravado.
    """
    if not requisicao.get("hasPostData") or tipo_conteudo(requisicao.get("headers")) != FORMULARIO:
        return None, None, True
    if "postData" in requisicao:
        return (*operacoes(requisicao["postData"]), True)
    entradas = requisicao.get("postDataEntries")
    if not entradas or any("bytes" not in e for e in entradas):
        return None, None, False  # corpo grande demais para vir no evento
    corpo = b"".join(base64.b64decode(e["bytes"]) for e in entradas)
    return (*operacoes(corpo.decode("utf-8", "replace")), True)


def origem_e_caminho(url):
    """('https://host[:porta]', '/caminho') sem credenciais, query nem fragmento."""
    partes = urllib.parse.urlsplit(url)
    if partes.scheme in ("http", "https", "ws", "wss"):
        porta = f":{partes.port}" if partes.port else ""
        return f"{partes.scheme}://{partes.hostname or ''}{porta}", partes.path or "/"
    return f"{partes.scheme}:", url_registravel(url).split("?", 1)[0]


def nova_tupla():
    return {"contagem": 0, "origens": set(), "status": collections.Counter()}


def chave_ordenacao(chave):
    return tuple(str(parte if parte is not None else "") for parte in chave)


class ObservadorRede:
    """Log ``rede-AAAA-MM-DD.jsonl`` e resumo por (método, caminho, nmgp_opcao, funcao).

    Na chave, ``funcao`` ausente vale ``""``, como nos resumos gravados antes
    de o gravador extrair ``funcao``. Requisições cujo corpo não veio no evento
    ficam em tuplas à parte (quinto elemento da chave, ``corpo_fora_do_evento``),
    porque nelas o valor efetivo do corpo é desconhecido.
    """

    def __init__(self, raiz):
        self.raiz = raiz
        self.caminho_resumo = os.path.join(raiz, "rede-resumo.json")
        self._trava = threading.Lock()
        self._tuplas = {}
        self.requisicoes = 0

    def gravar(self, momento, **dados):
        linha = {"ts": momento.isoformat(timespec="milliseconds"), **dados}
        caminho = os.path.join(self.raiz, f"rede-{momento:%Y-%m-%d}.jsonl")
        with self._trava:
            with open(caminho, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(linha, ensure_ascii=False) + "\n")

    def contar(self, metodo, url, opcao, funcao, corpo_fora_do_evento=False):
        origem, caminho = origem_e_caminho(url)
        chave = (metodo, caminho, opcao, funcao or "", bool(corpo_fora_do_evento))
        with self._trava:
            tupla = self._tuplas.setdefault(chave, nova_tupla())
            tupla["contagem"] += 1
            tupla["origens"].add(origem)
            self.requisicoes += 1
        return chave

    def status(self, chave, codigo):
        with self._trava:
            self._tuplas[chave]["status"][str(codigo)] += 1

    def resumo(self):
        with self._trava:
            return {k: {"contagem": v["contagem"], "origens": set(v["origens"]),
                        "status": collections.Counter(v["status"])} for k, v in self._tuplas.items()}

    def salvar_resumo(self):
        """Soma esta sessão ao rede-resumo.json existente e salva. Devolve o resumo da sessão."""
        sessao = self.resumo()
        total = self.resumo()
        sessoes = 1
        if os.path.exists(self.caminho_resumo):
            try:
                with open(self.caminho_resumo, encoding="utf-8") as f:
                    anterior = json.load(f)
                for t in anterior.get("tuplas", []):
                    # Resumos anteriores à extração de funcao não têm a chave: vale "".
                    chave = (t["metodo"], t["caminho"], t["nmgp_opcao"], t.get("funcao") or "",
                             bool(t.get("corpo_fora_do_evento")))
                    atual = total.setdefault(chave, nova_tupla())
                    atual["contagem"] += t["contagem"]
                    atual["origens"].update(t.get("origens", []))
                    atual["status"].update(t.get("status", {}))
                sessoes += anterior.get("sessoes", 0)
            except (OSError, ValueError, KeyError, TypeError):
                os.replace(self.caminho_resumo, f"{self.caminho_resumo}.ilegivel-{agora():%Y%m%d%H%M%S}")
        dados = {
            "atualizado_em": agora().isoformat(timespec="seconds"),
            "sessoes": sessoes,
            "nota": "Acumulado de todas as sessões do gravador com --rede nesta pasta, por "
                    "(metodo, caminho, nmgp_opcao, funcao). Só evidencia o que foi observado; "
                    "não libera nem bloqueia nada. Fonte do mapa de operações para "
                    "POSTS_PERMITIDOS, OPERACOES_SCRIPTCASE_BLOQUEADAS e FUNCOES_AJAX_BLOQUEADAS "
                    "em fluxo_exames/guard.py. nmgp_opcao e funcao são o valor do corpo "
                    "form-urlencoded ou, sem ele, o da query. funcao \"\" quer dizer ausente, vazio "
                    "ou não registrado (sessões gravadas antes da extração de funcao): não é "
                    "evidência de nenhum valor. Tuplas com corpo_fora_do_evento: true vêm de corpos "
                    "com mais de 64 KB que o gravador não viu; nelas os valores são só os da query "
                    "e o do corpo é desconhecido.",
            "tuplas": [
                {"metodo": m, "caminho": c, "nmgp_opcao": o, "funcao": fn,
                 **({"corpo_fora_do_evento": True} if fora else {}),
                 "contagem": v["contagem"], "status": dict(sorted(v["status"].items())),
                 "origens": sorted(v["origens"])}
                for (m, c, o, fn, fora), v in sorted(total.items(), key=lambda i: chave_ordenacao(i[0]))
            ],
        }
        temporario = self.caminho_resumo + ".tmp"
        with open(temporario, "w", encoding="utf-8", newline="\n") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temporario, self.caminho_resumo)
        return sessao


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


class ConexaoCDP:
    """Websocket do navegador, com as sessões dos alvos multiplexadas por ``sessionId``.

    Toda mensagem sai por ``enviar``, que recusa qualquer comando fora de
    ``permitidos`` antes de enviar. Respostas voltam a quem enviou; eventos
    vão para ``ao_evento(conexao, msg)``, na thread de leitura e na ordem em que
    chegam.
    """

    def __init__(self, url_ws, permitidos, ao_evento):
        self.url_ws = url_ws
        self.permitidos = permitidos
        self.ao_evento = ao_evento
        self.ws = None
        self._ids = itertools.count(1)
        self._pendentes = {}
        self._trava = threading.Lock()
        self.fechada = threading.Event()

    def abrir(self):
        self.ws = websocket.create_connection(
            self.url_ws, timeout=None, suppress_origin=True, enable_multithread=True)
        threading.Thread(target=self._ler, daemon=True, name="leitor-cdp").start()

    def _checar(self, metodo):
        if metodo not in self.permitidos:
            raise RuntimeError(f"comando CDP não permitido: {metodo}")

    def _despachar(self, metodo, params, sessao, esperar=True):
        self._checar(metodo)
        ident = next(self._ids)
        mensagem = {"id": ident, "method": metodo, "params": params or {}}
        if sessao:
            mensagem["sessionId"] = sessao
        resposta = None
        if esperar:
            resposta = queue.Queue(maxsize=1)
            with self._trava:
                if self.fechada.is_set():
                    raise RuntimeError(f"{metodo}: conexão com o navegador fechada")
                self._pendentes[ident] = resposta
        try:
            self.ws.send(json.dumps(mensagem))
        except BaseException:
            with self._trava:
                self._pendentes.pop(ident, None)
            raise
        return ident, resposta

    def _colher(self, metodo, ident, resposta):
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

    def enviar(self, metodo, params=None, sessao=None, esperar=True):
        """Envia um comando permitido. Com ``esperar=False`` não aguarda a resposta."""
        ident, resposta = self._despachar(metodo, params, sessao, esperar)
        return self._colher(metodo, ident, resposta) if esperar else None

    def enviar_em_lote(self, comandos, sessao=None):
        """Envia ``[(metodo, params), ...]`` em sequência, sem esperar entre eles, e só
        depois colhe as respostas.

        É o que permite preparar um alvo pausado: ele só responde depois de solto,
        mas o Chrome processa os comandos de uma sessão na ordem em que chegam.
        Todos os métodos são conferidos antes de o primeiro sair.
        """
        for metodo, _ in comandos:
            self._checar(metodo)
        enviados = [(metodo, *self._despachar(metodo, params, sessao)) for metodo, params in comandos]
        erros = []
        for metodo, ident, resposta in enviados:
            try:
                self._colher(metodo, ident, resposta)
            except (RuntimeError, TimeoutError) as erro:
                erros.append(str(erro))
        if erros:
            raise RuntimeError("; ".join(erros))

    def _ler(self):
        try:
            while True:
                bruto = self.ws.recv()
                if not bruto:
                    continue
                msg = json.loads(bruto)
                if "id" in msg:
                    with self._trava:
                        destino = self._pendentes.get(msg["id"])
                    if destino:
                        destino.put(msg)
                else:
                    self.ao_evento(self, msg)
        except (websocket.WebSocketException, OSError, ValueError):
            pass
        finally:
            with self._trava:
                self.fechada.set()
                for destino in self._pendentes.values():
                    destino.put({"error": {"message": "conexão com o navegador fechada"}})

    def fechar(self):
        try:
            if self.ws:
                self.ws.close()
        except (websocket.WebSocketException, OSError):
            pass


class Gravador:
    """Anexa-se ao navegador e mantém uma ``SessaoAlvo`` por aba ou iframe de outro site."""

    def __init__(self, registro, espera, parar, rede=None):
        self.registro = registro
        self.espera = espera
        self.parar = parar
        self.rede = rede
        self.permitidos = METODOS_CDP_PERMITIDOS | (METODOS_CDP_REDE if rede else frozenset())
        self.conexao = None
        self._sessoes = {}  # sessionId -> SessaoAlvo
        self._trava = threading.Lock()

    def ativo(self):
        return self.conexao is not None and not self.conexao.fechada.is_set()

    def conectar(self, url_ws):
        self.conexao = ConexaoCDP(url_ws, self.permitidos, self._ao_evento)
        self.conexao.abrir()
        # No navegador: anexa as abas que já existem e, dali em diante, cada aba
        # nova no momento em que nasce, pausada até a SessaoAlvo soltá-la.
        self.conexao.enviar("Target.setAutoAttach", PARAMS_AUTO_ATTACH)

    def encerrar(self, espera_threads=3):
        """Fecha a conexão (o Chrome solta os alvos ainda pausados) e as sessões."""
        if self.conexao:
            self.conexao.fechar()
        self.conexao = None
        with self._trava:
            sessoes = list(self._sessoes.values())
            self._sessoes.clear()
        for sessao in sessoes:
            sessao.encerrar()
        for sessao in sessoes:
            sessao.join(timeout=espera_threads)

    def _ao_evento(self, conexao, msg):
        metodo, p = msg.get("method"), msg.get("params") or {}
        try:
            if metodo == "Target.attachedToTarget":
                self._anexado(conexao, p, msg.get("sessionId"))
            elif metodo == "Target.detachedFromTarget":
                with self._trava:
                    sessao = self._sessoes.pop(p.get("sessionId"), None)
                if sessao:
                    sessao.encerrar()
            else:
                with self._trava:
                    sessao = self._sessoes.get(msg.get("sessionId"))
                if sessao:
                    sessao.ao_evento(metodo, p)
        except Exception as erro:  # um evento estranho não derruba a conexão
            self.registro.erros += 1
            self.registro.evento("ERRO", detalhe=f"evento {metodo}: {type(erro).__name__}: {erro}")

    def _anexado(self, conexao, p, sessao_pai):
        """Target.attachedToTarget: vale para as abas (sessão do navegador) e para
        os iframes de outro site (sessão da aba ou do iframe pai)."""
        info = p.get("targetInfo") or {}
        sessao_id = p.get("sessionId")
        with self._trava:
            pai = self._sessoes.get(sessao_pai)
            repetido = any(s.alvo["id"] == info.get("targetId") for s in self._sessoes.values())
        if (info.get("type") not in TIPOS_ALVO or info.get("url", "").startswith("devtools://")
                or repetido or not sessao_id):
            # Fora do escopo: nenhum domínio é ligado; só se desfaz a pausa.
            if p.get("waitingForDebugger") and sessao_id:
                conexao.enviar("Runtime.runIfWaitingForDebugger", sessao=sessao_id, esperar=False)
            return
        alvo = {"id": info["targetId"], "type": info.get("type"), "url": info.get("url", ""),
                "parentId": pai.alvo["id"] if pai else "", "openerId": info.get("openerId") or ""}
        sessao = SessaoAlvo(alvo, sessao_id, conexao, self.registro, self.espera, self.parar,
                            self.rede, pausado=bool(p.get("waitingForDebugger")))
        # Registrada antes de a thread de leitura seguir: nenhum evento da sessão se perde.
        with self._trava:
            self._sessoes[sessao_id] = sessao
        sessao.start()


class SessaoAlvo(threading.Thread):
    """Uma sessão CDP (flatten) com um alvo: aba ou iframe fora do processo."""

    def __init__(self, alvo, sessao_id, conexao, registro, espera, parar, rede=None, pausado=False):
        super().__init__(daemon=True, name=f"alvo-{alvo['id'][:8]}")
        self.alvo = alvo
        self.id_curto = alvo["id"][:8]
        self.sessao_id = sessao_id
        self.conexao = conexao
        self.registro = registro
        self.espera = espera
        self.parar = parar
        self.rede = rede
        self.pausado = pausado
        self._abertas = collections.OrderedDict()  # requestId -> (método, url, chave do resumo)
        self._trava = threading.Lock()
        self._prazo = None
        self._motivo = None
        self._ultimo_hash = None
        self._fechado = threading.Event()

    # --- CDP -------------------------------------------------------------

    def enviar(self, metodo, params=None):
        return self.conexao.enviar(metodo, params, sessao=self.sessao_id)

    def ao_evento(self, metodo, params):
        """Eventos desta sessão, na thread de leitura da conexão."""
        if metodo in EVENTOS_NAVEGACAO:
            with self._trava:
                self._prazo = time.monotonic() + self.espera
                self._motivo = metodo.split(".", 1)[1]
        elif self.rede and metodo in EVENTOS_REDE:
            try:
                self._evento_rede(metodo, params)
            except Exception as erro:  # um evento estranho não derruba a aba
                self.registro.erros += 1
                self.registro.evento("ERRO", alvo=self.id_curto, detalhe=f"rede: {type(erro).__name__}")

    def encerrar(self):
        self._fechado.set()

    # --- rede (--rede) ---------------------------------------------------

    def _evento_rede(self, evento, p):
        momento = agora()
        ident = p.get("requestId")
        base = {"alvo": self.id_curto, "requestId": ident, "tipo": p.get("type")}
        if evento == "Network.requestWillBeSent":
            req = p.get("request") or {}
            redirecionamento = p.get("redirectResponse")
            if redirecionamento and ident in self._abertas:
                self.rede.status(self._abertas[ident][2], redirecionamento.get("status"))
            metodo = req.get("method", "")
            url = url_registravel(req.get("url"))
            opcao_url, funcao_url = operacoes(urllib.parse.urlsplit(url).query)
            opcao_corpo, funcao_corpo, corpo_disponivel = operacoes_no_corpo(req)
            chave = self.rede.contar(
                metodo, url,
                opcao_corpo if opcao_corpo is not None else opcao_url,
                funcao_corpo if funcao_corpo is not None else funcao_url,
                corpo_fora_do_evento=not corpo_disponivel)
            self._abertas[ident] = (metodo, url, chave)
            self._abertas.move_to_end(ident)
            while len(self._abertas) > LIMITE_REQUISICOES_ABERTAS:
                self._abertas.popitem(last=False)
            linha = {"evento": "requisicao", **base, "metodo": metodo, "url": url}
            if redirecionamento:
                linha["status_redirecionamento"] = redirecionamento.get("status")
            if opcao_url is not None:
                linha["nmgp_opcao_url"] = opcao_url
            if opcao_corpo is not None:
                linha["nmgp_opcao_corpo"] = opcao_corpo
            if funcao_url is not None:
                linha["funcao_url"] = funcao_url
            if funcao_corpo is not None:
                linha["funcao_corpo"] = funcao_corpo
            if req.get("hasPostData"):
                linha["tipo_corpo"] = tipo_conteudo(req.get("headers")) or "desconhecido"
                if not corpo_disponivel:
                    # nmgp_opcao e funcao do corpo ficam desconhecidos; o corpo não é buscado.
                    linha["corpo_fora_do_evento"] = True
                    linha["funcao_fora_do_evento"] = True
            self.rede.gravar(momento, **linha)
        elif evento == "Network.responseReceived":
            resposta = p.get("response") or {}
            metodo, url, chave = self._abertas.get(ident, (None, url_registravel(resposta.get("url")), None))
            if chave:
                self.rede.status(chave, resposta.get("status"))
            self.rede.gravar(momento, evento="resposta", **base, metodo=metodo, url=url,
                             status=resposta.get("status"))
        else:  # Network.loadingFailed
            metodo, url, chave = self._abertas.pop(ident, (None, None, None))
            if chave:
                self.rede.status(chave, "falha")
            self.rede.gravar(momento, evento="falha", **base, metodo=metodo, url=url,
                             erro=p.get("errorText"), cancelada=bool(p.get("canceled")))

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
                if self.parar.is_set():
                    return  # encerramento no meio da leitura: não é erro
                if tentativa == 2 or self._fechado.is_set() or self.conexao.fechada.is_set():
                    self.registro.erros += 1
                    self.registro.evento("ERRO", alvo=self.id_curto, motivo=motivo, detalhe=str(erro))
                    return
                time.sleep(0.5)

    # --- ciclo -----------------------------------------------------------

    def _preparar(self):
        """Liga os domínios com o alvo ainda pausado e só então o solta.

        Vai tudo num lote: o alvo pausado só responde depois de solto, e o
        Chrome aplica os comandos da sessão na ordem de chegada, então
        Network.enable já vale quando a pausa se desfaz. A soltura sai no mesmo
        lote, mesmo que algum comando anterior falhe: a aba não fica parada.
        """
        comandos = [("Network.enable", PARAMS_NETWORK_ENABLE)] if self.rede else []
        comandos += [("Page.enable", None),
                     # Iframes de outro site deste alvo: anexados e pausados do mesmo jeito.
                     ("Target.setAutoAttach", PARAMS_AUTO_ATTACH)]
        if self.pausado:
            comandos.append(("Runtime.runIfWaitingForDebugger", None))
        self.conexao.enviar_em_lote(comandos, sessao=self.sessao_id)

    def run(self):
        abertura = self.alvo.get("openerId")
        self.registro.evento("CONECTADO", alvo=self.id_curto, tipo=self.alvo.get("type"), rede=bool(self.rede),
                             pausado=self.pausado, **({"aberta_por": abertura[:8]} if abertura else {}))
        try:
            self._preparar()
            self._capturar_com_retentativa("inicial")
            while not (self.parar.is_set() or self._fechado.is_set() or self.conexao.fechada.is_set()):
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
            self.registro.evento("DESCONECTADO", alvo=self.id_curto)


def main():
    padrao = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "FluxoExames", "captures")
    p = argparse.ArgumentParser(description="Gravador passivo (Fase 0): grava navegações do Chrome dedicado via CDP.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--porta", type=int, default=9222)
    p.add_argument("--saida", default=padrao, help=f"pasta das capturas (padrão: {padrao})")
    p.add_argument("--espera", type=float, default=1.5,
                   help="segundos sem novos eventos de navegação antes do snapshot (padrão: 1.5)")
    p.add_argument("--rede", action="store_true",
                   help="registra também as requisições (método, URL, status, nmgp_opcao, funcao), nunca corpos")
    args = p.parse_args()

    if hasattr(signal, "SIGBREAK"):  # Windows: Ctrl+Break encerra igual a Ctrl+C
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    return executar(args, threading.Event())


def executar(args, parar):
    """Grava até Ctrl+C (KeyboardInterrupt) ou até ``parar`` ser acionado."""
    try:
        versao = http_get_json(args.host, args.porta, "/json/version")
    except OSError as erro:
        print(f"Chrome não responde em http://{args.host}:{args.porta} ({erro}).\n"
              "Abra o Chrome do perfil dedicado com --remote-debugging-port (ver docs/FASE-0-ETAPA-A.md).",
              file=sys.stderr)
        return 2

    registro = Registro(os.path.abspath(args.saida))
    rede = ObservadorRede(registro.raiz) if args.rede else None
    registro.evento("INICIO", navegador=versao.get("Browser"), porta=args.porta, pid=os.getpid(), rede=args.rede)
    print(f"Conectado a {versao.get('Browser')} na porta {args.porta}.")
    print(f"Capturas em {registro.raiz}")
    if rede:
        print("Rede: registrando método, URL, status, nmgp_opcao e funcao em rede-AAAA-MM-DD.jsonl (sem corpos).")
    print("Modo passivo: nenhuma interação com as páginas. Ctrl+C para parar.", flush=True)

    gravador = Gravador(registro, args.espera, parar, rede)
    proxima_tentativa = 0.0
    try:
        while not parar.is_set():
            if not gravador.ativo():
                if gravador.conexao is not None:
                    gravador.encerrar()
                    registro.evento("ERRO", detalhe="conexão com o navegador perdida")
                if time.monotonic() >= proxima_tentativa:
                    try:
                        gravador.conectar(http_get_json(args.host, args.porta, "/json/version")["webSocketDebuggerUrl"])
                    except (OSError, websocket.WebSocketException, RuntimeError, TimeoutError, KeyError) as erro:
                        gravador.encerrar()
                        registro.evento("ERRO", detalhe=f"conexão com o navegador: {type(erro).__name__}: {erro}")
                        proxima_tentativa = time.monotonic() + ESPERA_RECONEXAO
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        parar.set()
        gravador.encerrar()
        if rede:
            imprimir_resumo_rede(rede.salvar_resumo(), rede)
        registro.evento("FIM", capturas=registro.capturas, erros=registro.erros,
                        **({"requisicoes": rede.requisicoes} if rede else {}))
        print(f"\nEncerrado. {registro.capturas} capturas, {registro.erros} erros. Log: {registro.caminho_log}")
    return 0


def imprimir_resumo_rede(sessao, rede):
    print(f"\nResumo de rede desta sessão: {rede.requisicoes} requisições,"
          f" {len(sessao)} tuplas (método, caminho, nmgp_opcao, funcao).")
    for (metodo, caminho, opcao, funcao, fora), v in sorted(
            sessao.items(), key=lambda i: (i[0][0] == "GET", *chave_ordenacao(i[0]))):
        print(f"  {v['contagem']:5d}  {metodo:7s} {caminho}  nmgp_opcao={opcao if opcao is not None else '-'}"
              f"  funcao={funcao or '-'}" + ("  [corpo fora do evento]" if fora else ""))
    print(f"Acumulado salvo em {rede.caminho_resumo}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
