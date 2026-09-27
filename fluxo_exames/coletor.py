"""Coletor do Medicina Direta (MD), somente leitura (F1, etapa A).

Conecta por CDP ao Chrome **dedicado** do projeto, já aberto e já logado pelo
Ivson (``--remote-debugging-port=9222``, perfil em
``%LOCALAPPDATA%\\FluxoExames\\chrome-profile``; ver
``docs/FASE-0-ETAPA-A.md``). Nunca abre navegador próprio nem cria contexto:
usa o contexto padrão do Chrome dedicado e a aba do MD que já existe.

Caminhos, seletores e a árvore de quadros vêm do mapa de leitura
(``docs/FASE-0-ETAPA-B.md``, seções 3, 4, 8 e 9). O coletor só clica em
elementos desse mapa e só lê o DOM.

Guarda em 3 camadas (todas levantam ``ColetorBloqueado``, sem tentar
alternativa):

1. **Operação.** Cada método público é uma operação. Antes de agir, a
   operação precisa estar em ``OPERACOES_PERMITIDAS``, e cada clique precisa
   estar em ``CLIQUES`` para a operação corrente, com o código JS do alvo
   (``href``, ``onclick`` ou ``item-href``) casando com o caminho do mapa.
2. **Rede.** Uma rota no contexto do Playwright (``Fetch`` do CDP) passa
   toda requisição por ``guard.avaliar_requisicao`` e aborta o que a guarda
   nega: POST fora da lista branca, operações do ScriptCase, endpoints de
   escrita, assinatura, impressão e log (inclusive por ``funcao``). Um
   canário para um host ``.invalid`` prova que a rota está ativa antes da
   primeira ação. Requisição bloqueada que não seja um dos automáticos
   conhecidos (``BLOQUEIOS_TOLERADOS``) interrompe a coleta.
3. **Texto.** Antes de cada clique, o texto, ``value``, ``title``,
   ``aria-label``, ``id`` e o código do alvo (e do ancestral clicável) passam
   por ``guard.clique_permitido``: nada de Finalizar e Assinar, Salvar,
   Enviar, ASSINAR PDF, Excluir, Imprimir etc.

``origem_md`` só muda nos testes, que usam um servidor sintético local. Nesse
modo a guarda avalia as URLs do servidor sintético como se fossem do MD, e
qualquer requisição ao MD real é abortada.

ESTADO: desenvolvido e testado só contra o servidor sintético. A validação ao
vivo é uma sessão separada com o Ivson (``docs/FASE-1-ETAPA-A.md``).
"""

import functools
import hashlib
import re
import secrets
import time
from contextlib import contextmanager
from datetime import date
from urllib.parse import urlencode, urlsplit, urlunsplit

from fluxo_exames import guard

CDP_PADRAO = "http://localhost:9222"
ORIGEM_MD = "https://" + guard.HOST_MD
HOSTS_CDP_LOCAIS = frozenset({"localhost", "127.0.0.1", "::1"})
DOMINIO_MD = "medicinadireta.com.br"
CANARIO = "https://coletor-canario.invalid/"
ESPERA_PADRAO_MS = 15000

# Camada 1. Operações de leitura do mapa (B §8).
OPERACOES_PERMITIDAS = (
    "ler_agenda",
    "localizar_paciente",
    "abrir_ficha",
    "identidade",
    "listar_atendimentos",
    "listar_laudos",
    "abrir_texto_laudo",
)

# Bloqueadas até validação numa sessão da Fase 0 (ver guard.py e B §9).
OPERACOES_PENDENTES_VALIDACAO = {
    "paginar": "nmgp_opcao=rec (F4) nunca foi observado; fora da lista branca (B §9.7).",
    "abrir_resultado": "form_exames_resultados pendente (B §9.4).",
    "abrir_evolucao": "form_tbl_pacientes_crm_editavel pendente; é onde está o "
                      "questionário respondido (B §9.6).",
    "pesquisar_questionario": "blank_quest_config_funcoes rel_dados_acompanhar pendente (B §9.2).",
    "baixar_pdf_laudo": "blank_laudo_pdf bloqueado: formphp e estado de assinatura (B §9.3).",
}

# Camada 1. Cliques do mapa: chave -> operações que podem usá-la, atributos
# cujo código precisa casar com o padrão e, se houver, o texto esperado
# (forma de guard.normalizar_texto).
CLIQUES = {
    "menu_agendamento": {
        "operacoes": ("ler_agenda", "abrir_ficha"),
        "atributos": ("item-href",),
        "padrao": r"[?&]sc_apl_menu=blank_div(&|$)",
        "texto": r"^AGENDAMENTO$",
    },
    "agenda_nome": {
        "operacoes": ("abrir_ficha",),
        "atributos": ("href", "onclick"),
        "padrao": r"^\s*javascript:\s*nm_gp_submit5\(\s*'/treemenu_paciente/'",
    },
    "menu_laudo": {
        "operacoes": ("listar_atendimentos", "listar_laudos", "abrir_texto_laudo"),
        "atributos": ("item-href",),
        "padrao": r"[?&]sc_apl_menu=grid_exames_laudo(&|$)",
        "texto": r"^LAUDO$",
    },
    "laudo_lapis": {
        "operacoes": ("listar_laudos", "abrir_texto_laudo"),
        "atributos": ("href", "onclick"),
        "padrao": r"^\s*javascript:\s*nm_gp_submit5\(\s*'/cont_exame_resultado_laudo/'",
    },
    "laudo_abrir": {
        "operacoes": ("abrir_texto_laudo",),
        "atributos": ("href", "onclick"),
        "padrao": r"nm_gp_submit4\(\s*'/form_paciente_exames_laudos_resultado/'",
    },
    "laudo_voltar": {
        "operacoes": ("abrir_texto_laudo",),
        "atributos": ("onclick",),
        "padrao": r"^\s*scFormClose_F6\(\s*'form_paciente_exames_laudos_resultado_fim\.php'\s*\)"
                  r"\s*;?\s*$",
        "texto": r"^VOLTAR$",
    },
}

# Camada 2. Requisições automáticas das telas do mapa que a guarda bloqueia e
# que não impedem a leitura. Continuam abortadas; só não interrompem a coleta.
BLOQUEIOS_TOLERADOS = (
    "/blank_notifica_lembrete/",    # POST automático ao abrir a ficha (B §5)
    "/blank_fecha_atendimento/",    # GET automático ao abrir a 2ª ficha (B §6.3)
)

# Quadros do mapa (B §3.1), localizados por name + caminho, nunca só por id.
QUADRO_FICHA = "menu_inicial_treemenu_paciente_iframe"
QUADRO_WIDGET_LAUDOS = "dbifrm_widget3"
CAMINHO_MENU = "/menu_inicial/"
CAMINHO_AGENDA = "/blank_div/"
CAMINHO_FICHA = "/treemenu_paciente/"
CAMINHO_NIVEL1 = "/grid_exames_laudo/"
CAMINHO_NIVEL2 = "/cont_exame_resultado_laudo/"
CAMINHO_LISTA_LAUDOS = "/grid_paciente_exames_laudos_resultado/"
CAMINHO_FORM_LAUDO = "/form_paciente_exames_laudos_resultado/"

CAMPOS_AGENDA = ("cmp_hora_ini", "c_nome", "cmp_img", "cmp_atendimento", "a_titulo",
                 "e_ds_agenda_status")
CAMPOS_NIVEL1 = ("id", "cmp_atendimento_versao", "cmp_data_evento", "cmp_receituario_hint",
                 "cmp_status", "cmp_usuario", "qtd_aberto", "qtd_assinado_pdf",
                 "cmp_status_assinatura")
CAMPOS_NIVEL2 = ("id", "cmp_descricao", "realizado", "data", "profissional", "cmp_assinar",
                 "cmp_pdf", "cmp_status_assinatura", "cmp_editavel")
ROTULOS_IDENTIDADE = {
    "PRONTUARIO": "prontuario",
    "NOME": "nome",
    "DATA DE NASCIMENTO": "dn",
    "CPF": "cpf",
}

_JS_INFO_ALVO = """el => {
    const alvos = [el];
    const pai = el.parentElement && el.parentElement.closest('a, button, input, [onclick]');
    if (pai) alvos.push(pai);
    return alvos.map(e => ({
        id: e.id || '',
        texto: (e.innerText || e.textContent || '').trim(),
        value: e.getAttribute('value') || '',
        title: e.getAttribute('title') || '',
        aria: e.getAttribute('aria-label') || '',
        onclick: e.getAttribute('onclick') || '',
        href: e.getAttribute('href') || '',
        'item-href': e.getAttribute('item-href') || '',
    }));
}"""

_JS_PRONTO = """([marca, seletor]) => document.readyState === 'complete'
    && (!marca || window.__coletor_marca !== marca)
    && (!seletor || !!document.querySelector(seletor))"""

_JS_GRADE = """([campos, raiz]) => {
    const base = raiz ? document.querySelector(raiz) : document;
    if (!base) return null;
    const linhas = {};
    for (const el of base.querySelectorAll('[id^="id_sc_field_"]')) {
        const m = el.id.match(/^id_sc_field_(.+)_(\\d+)$/);
        if (!m || !campos.includes(m[1])) continue;
        const comTitulo = el.hasAttribute('title') ? el : el.querySelector('[title]');
        (linhas[m[2]] = linhas[m[2]] || {})[m[1]] = {
            texto: (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim(),
            titulo: comTitulo ? comTitulo.getAttribute('title') : '',
        };
    }
    return linhas;
}"""

_JS_PAGINACAO = """raiz => {
    const base = raiz ? document.querySelector(raiz) : document;
    return !!base && base.querySelectorAll(
        '[id^="sc_b_avc"], [id^="sc_b_ret"], [id^="sc_b_ini_"], [id^="sc_b_fim_"], '
        + '[onclick*="nm_gp_move"], [href*="nm_gp_move"]').length > 0;
}"""

_JS_IDENTIDADE = """() => Array.from(
    document.querySelectorAll('.cabecalho .cabecalho__grupo-info')).map(g => [
        (g.querySelector('.cabecalho__campo-nome') || {}).textContent || '',
        (g.querySelector('.cabecalho__campo-valor') || {}).textContent || ''])"""

_JS_CARREGAR_AGENDA = """url => new Promise(ok => {
    const jq = window.jQuery;
    if (!jq || !document.querySelector('#campotabela')) { ok('sem_mecanismo'); return; }
    jq('#campotabela').load(url, (resposta, status) => ok(status));
})"""

_JS_FORM_LAUDO = """() => {
    const texto = document.querySelector('textarea[name="receituario"]');
    const campo = document.querySelector('#id_sc_field_id');
    const so_leitura = document.querySelector('#id_read_on_id');
    return {
        texto: texto ? texto.defaultValue : null,
        id: campo ? (campo.value || campo.textContent) : (so_leitura ? so_leitura.textContent : null),
    };
}"""

_JS_CANARIO = """url => { fetch(url, {method: 'POST', mode: 'no-cors', body: 'canario=1'})
    .catch(() => 0); }"""


class ColetorBloqueado(Exception):
    """Uma verificação da guarda falhou. A coleta para; nada é tentado no lugar."""

    def __init__(self, motivo, detalhe=""):
        self.motivo = motivo
        self.detalhe = detalhe
        super().__init__("%s: %s" % (motivo, detalhe) if detalhe else motivo)


def _digitos(texto):
    return re.sub(r"\D", "", texto or "")


def _x_de_y(texto):
    m = re.search(r"(\d+)\s*de\s*(\d+)", texto or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _operacao(nome):
    """Marca um método público como operação da camada 1."""
    def decorador(metodo):
        @functools.wraps(metodo)
        def envolto(self, *args, **kwargs):
            with self._em_operacao(nome):
                resultado = metodo(self, *args, **kwargs)
                self._drenar()
                self.verificar_rede()
                return resultado
        return envolto
    return decorador


class Coletor:
    """Coletor somente leitura. Use ``with Coletor() as c: ...``."""

    def __init__(self, cdp_url=CDP_PADRAO, origem_md=ORIGEM_MD, espera_ms=ESPERA_PADRAO_MS):
        partes = urlsplit(cdp_url)
        if partes.scheme not in ("http", "ws") or partes.hostname not in HOSTS_CDP_LOCAIS:
            raise ColetorBloqueado("cdp_nao_local", "só http://localhost:<porta>")
        origem = urlsplit(origem_md)
        if origem.scheme not in ("http", "https") or not origem.hostname:
            raise ColetorBloqueado("origem_invalida")
        self.cdp_url = cdp_url
        self.origem_md = urlunsplit((origem.scheme, origem.netloc, "", "", ""))
        self._host_origem = origem.hostname.lower()
        self._netloc_origem = origem.netloc.lower()
        self._sintetico = self._host_origem != guard.HOST_MD
        self.espera_ms = espera_ms
        self.bloqueios = []
        self._vistos = 0
        self._canario_visto = False
        self._operacao_atual = None
        self._pw = None
        self.contexto = None
        self.pagina = None
        self._ficha = None
        self._agenda = None

    # --- conexão --------------------------------------------------------------

    def __enter__(self):
        self.conectar()
        return self

    def __exit__(self, *exc):
        self.desconectar()

    def conectar(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        try:
            navegador = self._pw.chromium.connect_over_cdp(self.cdp_url)
            if not navegador.contexts:
                raise ColetorBloqueado("sem_contexto")
            self.contexto = navegador.contexts[0]
            self.pagina = self._localizar_aba()
            self._checar_service_workers()
            self.contexto.route("**/*", self._rota)
            self._testar_canario()
            self._checar_sessao()
        except BaseException:
            self.desconectar()
            raise

    def desconectar(self):
        """Solta o Chrome dedicado sem fechá-lo."""
        if self._pw is None:
            return
        try:
            self._drenar()
        except Exception:
            pass
        self._pw.stop()
        self._pw = None
        self.contexto = self.pagina = self._ficha = None

    @property
    def guarda_ativa(self):
        return self._canario_visto

    def _no_md(self, url):
        partes = urlsplit(url or "")
        return partes.scheme in ("http", "https") and partes.netloc.lower() == self._netloc_origem

    def _localizar_aba(self):
        abas = [p for p in self.contexto.pages if self._no_md(p.url)]
        if not abas:
            raise ColetorBloqueado("aba_md_ausente", "abra e faça login no MD no Chrome dedicado")
        no_menu = [p for p in abas if urlsplit(p.url).path.startswith(CAMINHO_MENU)]
        if len(no_menu) != 1:
            raise ColetorBloqueado("aba_md_ambigua", "%d abas do MD em %s" % (len(no_menu),
                                                                             CAMINHO_MENU))
        return no_menu[0]

    def _checar_service_workers(self):
        # Requisições de service worker não passam pela rota do contexto.
        if any(self._no_md(w.url) for w in self.contexto.service_workers):
            raise ColetorBloqueado("service_worker_md")

    def _testar_canario(self):
        self._canario_visto = False
        self.pagina.main_frame.evaluate(_JS_CANARIO, CANARIO)
        limite = time.monotonic() + 5
        while not self._canario_visto and time.monotonic() < limite:
            self.pagina.wait_for_timeout(50)
        if not self._canario_visto:
            raise ColetorBloqueado("guarda_de_rede_inativa")

    def _checar_sessao(self):
        if self.pagina is None or self.pagina.is_closed():
            raise ColetorBloqueado("desconectado")
        if not (self._no_md(self.pagina.url)
                and urlsplit(self.pagina.url).path.startswith(CAMINHO_MENU)):
            raise ColetorBloqueado("sessao_fora_do_menu", "login ou sessão expirada?")

    # --- camada 2: rede -------------------------------------------------------

    def _url_para_guarda(self, url):
        """URL que a guarda avalia. No modo sintético, a origem vira o MD."""
        if self._sintetico and self._no_md(url):
            p = urlsplit(url)
            return urlunsplit(("https", guard.HOST_MD, p.path, p.query, ""))
        return url

    def decidir(self, metodo, url, corpo=None, tipo=None):
        """``(permitida, motivo)`` para uma requisição que sai do navegador."""
        host = (urlsplit(url or "").hostname or "").lower()
        if self._sintetico and (host == DOMINIO_MD or host.endswith("." + DOMINIO_MD)):
            return False, "md_real_em_modo_sintetico"
        return guard.avaliar_requisicao(metodo, self._url_para_guarda(url), corpo, tipo)

    def _rota(self, route, request):
        try:
            url = request.url
            if urlsplit(url).hostname == urlsplit(CANARIO).hostname:
                self._canario_visto = True
                route.abort("blockedbyclient")
                return
            try:
                corpo = request.post_data_buffer
            except Exception:
                corpo = guard.CORPO_ILEGIVEL
            tipo = (request.headers or {}).get("content-type")
            permitida, motivo = self.decidir(request.method, url, corpo, tipo)
        except Exception:
            permitida, motivo = False, "erro_na_guarda"
        if permitida:
            try:
                route.continue_()
            except Exception:
                pass
            return
        partes = urlsplit(request.url)
        self.bloqueios.append({
            "metodo": request.method,
            "host": partes.hostname or "",
            "caminho": partes.path,
            "motivo": motivo,
            "operacao": self._operacao_atual,
        })
        try:
            route.abort("blockedbyclient")
        except Exception:
            pass

    def _tolerado(self, evento):
        host = evento["host"].lower()
        if host != self._host_origem and host != DOMINIO_MD \
                and not host.endswith("." + DOMINIO_MD):
            return True     # terceiros (telemetria, chat): abortados, sem efeito no MD
        return host == self._host_origem and any(
            evento["caminho"].lower().startswith(p) for p in BLOQUEIOS_TOLERADOS)

    def _drenar(self, ms=150):
        # A API síncrona só atende a rota durante chamadas ao Playwright.
        if self.pagina is not None and not self.pagina.is_closed():
            self.pagina.wait_for_timeout(ms)

    def verificar_rede(self):
        """Levanta ``ColetorBloqueado`` se houve bloqueio não tolerado desde a última vez."""
        novos = self.bloqueios[self._vistos:]
        self._vistos = len(self.bloqueios)
        graves = [e for e in novos if not self._tolerado(e)]
        if graves:
            raise ColetorBloqueado("rede", "; ".join(
                "%s %s (%s)" % (e["metodo"], e["caminho"], e["motivo"]) for e in graves))

    # --- camadas 1 e 3: operação e clique -------------------------------------

    def _autorizar(self, operacao):
        if operacao in OPERACOES_PENDENTES_VALIDACAO:
            raise ColetorBloqueado("operacao_pendente", operacao)
        if operacao not in OPERACOES_PERMITIDAS:
            raise ColetorBloqueado("operacao_nao_permitida", operacao)
        if self._pw is None:
            raise ColetorBloqueado("desconectado")

    @contextmanager
    def _em_operacao(self, nome):
        self._autorizar(nome)
        anterior = self._operacao_atual
        self._operacao_atual = nome
        try:
            self._checar_sessao()
            self.verificar_rede()
            yield
        finally:
            self._operacao_atual = anterior

    def executar(self, operacao, *args, **kwargs):
        """Executa uma operação pelo nome, depois de autorizá-la (camada 1)."""
        self._autorizar(operacao)
        return getattr(self, operacao)(*args, **kwargs)

    def _clicar(self, chave, alvo):
        operacao = self._operacao_atual
        if operacao is None:
            raise ColetorBloqueado("clique_fora_de_operacao", chave)
        regra = CLIQUES.get(chave)
        if regra is None or operacao not in regra["operacoes"]:
            raise ColetorBloqueado("clique_nao_mapeado", "%s/%s" % (operacao, chave))
        if alvo.count() != 1:
            raise ColetorBloqueado("alvo_ausente_ou_ambiguo", chave)
        info = alvo.evaluate(_JS_INFO_ALVO)
        for elemento in info:
            codigo = " ".join(elemento[a] for a in ("onclick", "href", "item-href") if elemento[a])
            textos = [elemento[k] for k in ("texto", "value", "title", "aria")]
            if not guard.clique_permitido(textos, elemento["id"], codigo):
                raise ColetorBloqueado("clique_interditado", chave)
        codigo = " ".join(info[0][a] for a in regra["atributos"] if info[0][a])
        if not re.search(regra["padrao"], codigo):
            raise ColetorBloqueado("clique_fora_do_mapa", chave)
        if "texto" in regra and not re.search(regra["texto"],
                                              guard.normalizar_texto(info[0]["texto"])):
            raise ColetorBloqueado("clique_fora_do_mapa", chave)
        self.verificar_rede()
        try:
            alvo.click(timeout=self.espera_ms)
        except Exception as erro:
            raise ColetorBloqueado("clique_falhou", chave) from erro

    # --- quadros --------------------------------------------------------------

    def _quadros(self, nome=None, caminho=None, pai=None):
        achados = []
        for quadro in self.pagina.frames:
            if nome is not None and quadro.name != nome:
                continue
            if caminho is not None and not (self._no_md(quadro.url)
                                            and urlsplit(quadro.url).path.startswith(caminho)):
                continue
            if pai is not None and quadro.parent_frame != pai:
                continue
            achados.append(quadro)
        return achados

    def _marcar(self, quadro):
        """Marca o documento atual do quadro, para reconhecer o próximo."""
        if quadro is None:
            return None
        marca = secrets.token_hex(8)
        try:
            quadro.evaluate("m => { window.__coletor_marca = m; }", marca)
        except Exception:
            return None
        return marca

    def _esperar_quadro(self, nome, caminho, pai=None, marca=None, pronto=None):
        limite = time.monotonic() + self.espera_ms / 1000
        while True:
            for quadro in self._quadros(nome, caminho, pai):
                try:
                    if quadro.evaluate(_JS_PRONTO, [marca, pronto]):
                        return quadro
                except Exception:
                    pass        # documento trocando
            if time.monotonic() > limite:
                raise ColetorBloqueado("tela_inesperada", "%s %s" % (nome or "", caminho))
            self.pagina.wait_for_timeout(100)

    def _estavel(self, nome, caminho, pai, pronto=None, janela_ms=400):
        """Espera o quadro ficar ``janela_ms`` sem trocar de documento.

        O widget da lista de laudos é recarregado logo depois da 1ª carga
        (B §2, 19:47:19).
        """
        limite = time.monotonic() + self.espera_ms / 1000
        while True:
            quadro = self._esperar_quadro(nome, caminho, pai, pronto=pronto)
            marca = self._marcar(quadro)
            self.pagina.wait_for_timeout(janela_ms)
            try:
                if marca and quadro.evaluate("m => window.__coletor_marca === m", marca) \
                        and urlsplit(quadro.url).path.startswith(caminho):
                    return quadro
            except Exception:
                pass
            if time.monotonic() > limite:
                raise ColetorBloqueado("tela_instavel", caminho)

    def _ler_grade(self, quadro, campos, raiz=None):
        linhas = quadro.evaluate(_JS_GRADE, [list(campos), raiz])
        if linhas is None:
            raise ColetorBloqueado("grade_ausente", raiz or "")
        return [(int(n), linhas[n]) for n in sorted(linhas, key=int)]

    def _checar_paginacao(self, quadro, raiz=None):
        if quadro.evaluate(_JS_PAGINACAO, raiz):
            raise ColetorBloqueado("paginacao_pendente", OPERACOES_PENDENTES_VALIDACAO["paginar"])

    @staticmethod
    def _texto(campos, nome):
        return campos.get(nome, {}).get("texto", "")

    @staticmethod
    def _titulo(campos, nome):
        return campos.get(nome, {}).get("titulo", "")

    # --- agenda ---------------------------------------------------------------

    def _quadro_agenda(self):
        """Quadro da agenda visível. Devolve ``(quadro, reaberto)``.

        Se a agenda não está aberta ou está escondida atrás da ficha, clica
        em "Agendamento" no menu; nesse caso a grade pode ter voltado ao dia
        de hoje (``reaberto=True``).
        """
        principal = self.pagina.main_frame
        menu = principal.locator('a[item-href*="sc_apl_menu=blank_div"]')
        nome = menu.first.get_attribute("item-target") if menu.count() == 1 else None
        existentes = self._quadros(nome, CAMINHO_AGENDA, principal)
        if existentes and existentes[0].frame_element().is_visible():
            return self._esperar_quadro(existentes[0].name, CAMINHO_AGENDA, principal,
                                        pronto="#campotabela > *"), False
        if nome is None:
            raise ColetorBloqueado("menu_agenda_ausente")
        self._clicar("menu_agendamento", menu)
        return self._estavel(nome, CAMINHO_AGENDA, principal, pronto="#campotabela > *"), True

    def _carregar_agenda(self, quadro, data):
        # Mesmo GET que o calendário faz ao clicar num dia (B §2, 19:46:46).
        consulta = urlencode({
            "p_zerar_id_paciente": "S", "vg_redir_form": "N", "dt": data, "diaClicado": data,
            "vg_data_ini": data, "vg_data_fim": data, "vg_limpar_filtro_calendario": "S",
        })
        url = "../grid_agenda_md_calendario/grid_agenda_md_calendario.php?" + consulta
        status = quadro.evaluate(_JS_CARREGAR_AGENDA, url)
        if status not in ("success", "notmodified"):
            raise ColetorBloqueado("agenda_nao_carregou", status)
        self._checar_paginacao(quadro, "#campotabela")
        linhas = []
        for n, c in self._ler_grade(quadro, CAMPOS_AGENDA, "#campotabela"):
            if "c_nome" not in c:
                continue
            linhas.append({
                "linha": n,
                "hora": self._texto(c, "cmp_hora_ini"),
                "nome": self._texto(c, "c_nome"),
                "prontuario": _digitos(self._texto(c, "cmp_img")),
                "atendimento": self._texto(c, "cmp_atendimento"),
                "titulo": self._texto(c, "a_titulo"),
                "status": self._texto(c, "e_ds_agenda_status"),
            })
        self._agenda = {"data": data, "linhas": linhas}
        return linhas

    @_operacao("ler_agenda")
    def ler_agenda(self, data=None):
        """Linhas da agenda do dia (padrão: hoje), lidas de ``div#campotabela``."""
        data = (data or date.today())
        data = data.isoformat() if isinstance(data, date) else date.fromisoformat(data).isoformat()
        quadro, _ = self._quadro_agenda()
        return self._carregar_agenda(quadro, data)

    @_operacao("localizar_paciente")
    def localizar_paciente(self, chave):
        """Linha da agenda lida pelo prontuário (só dígitos) ou pelo nome."""
        if self._agenda is None:
            raise ColetorBloqueado("agenda_nao_lida")
        if isinstance(chave, dict):
            chave = chave.get("prontuario") or chave.get("nome") or ""
        chave = str(chave).strip()
        if chave.isdigit():
            achadas = [l for l in self._agenda["linhas"] if l["prontuario"] == chave]
        else:
            alvo = guard.normalizar_texto(chave)
            achadas = [l for l in self._agenda["linhas"] if guard.normalizar_texto(l["nome"]) == alvo]
        if not achadas:
            return None
        if len({l["prontuario"] for l in achadas}) > 1:
            raise ColetorBloqueado("paciente_ambiguo")
        return achadas[0]

    # --- ficha ----------------------------------------------------------------

    @_operacao("abrir_ficha")
    def abrir_ficha(self, linha):
        """Abre a ficha pelo nome na agenda lida e devolve a identidade do cabeçalho.

        ``linha`` é um item de ``ler_agenda`` ou o número da linha.
        """
        if self._agenda is None:
            raise ColetorBloqueado("agenda_nao_lida")
        if isinstance(linha, dict):
            registro = linha
        else:
            registro = next((l for l in self._agenda["linhas"] if l["linha"] == int(linha)), None)
            if registro is None:
                raise ColetorBloqueado("linha_inexistente")
        agenda, reaberta = self._quadro_agenda()
        n = registro["linha"]
        if reaberta:
            # A grade foi recarregada: os links são novos e a linha pode ter mudado.
            linhas = self._carregar_agenda(agenda, self._agenda["data"])
            achadas = [l for l in linhas if l["prontuario"] == registro["prontuario"]]
            if not achadas:
                raise ColetorBloqueado("paciente_sumiu_da_agenda")
            n = achadas[0]["linha"]
        principal = self.pagina.main_frame
        anteriores = self._quadros(QUADRO_FICHA, None, principal)
        marca = self._marcar(anteriores[0]) if anteriores else None
        self._clicar("agenda_nome", agenda.locator("#campotabela a#id_sc_field_c_nome_%d" % n))
        self._ficha = self._esperar_quadro(QUADRO_FICHA, CAMINHO_FICHA, principal, marca=marca,
                                           pronto=".cabecalho .cabecalho__grupo-info")
        identidade = self._ler_identidade()
        if registro.get("prontuario") and registro["prontuario"] != identidade["prontuario"]:
            self._ficha = None
            raise ColetorBloqueado("ficha_divergente", "prontuário da ficha difere da agenda")
        return identidade

    def _ler_identidade(self):
        if self._ficha is None:
            raise ColetorBloqueado("ficha_fechada")
        pares = self._ficha.evaluate(_JS_IDENTIDADE)
        dados = {}
        for rotulo, valor in pares:
            chave = ROTULOS_IDENTIDADE.get(guard.normalizar_texto(rotulo))
            if chave:
                dados[chave] = " ".join(valor.split())
        dados["prontuario"] = _digitos(dados.get("prontuario"))
        dados["cpf"] = _digitos(dados.get("cpf"))
        if not (dados.get("nome") and dados["prontuario"]
                and re.fullmatch(r"\d{2}/\d{2}/\d{4}", dados.get("dn", ""))
                and len(dados["cpf"]) == 11):
            raise ColetorBloqueado("identidade_incompleta")
        return {k: dados[k] for k in ("prontuario", "nome", "dn", "cpf")}

    @_operacao("identidade")
    def identidade(self):
        """Nome, DN e CPF do cabeçalho da ficha aberta, lidos pelo rótulo."""
        return self._ler_identidade()

    # --- laudos ---------------------------------------------------------------

    def _abrir_nivel1(self):
        if self._ficha is None:
            raise ColetorBloqueado("ficha_fechada")
        item = self._ficha.locator('a[item-href*="sc_apl_menu=grid_exames_laudo"]')
        if item.count() != 1:
            raise ColetorBloqueado("menu_laudo_ausente")
        nome = item.get_attribute("item-target")
        anteriores = self._quadros(nome, None, self._ficha)
        marca = self._marcar(anteriores[0]) if anteriores else None
        self._clicar("menu_laudo", item)
        return self._esperar_quadro(nome, CAMINHO_NIVEL1, self._ficha, marca=marca)

    def _linha_por_id(self, quadro, campos, ident):
        alvo = _digitos(str(ident))
        for n, c in self._ler_grade(quadro, campos):
            if alvo and _digitos(self._texto(c, "id")) == alvo:
                return n
        return None

    @_operacao("listar_atendimentos")
    def listar_atendimentos(self):
        """Laudo, 1º nível: um item por atendimento, com os contadores."""
        quadro = self._abrir_nivel1()
        self._checar_paginacao(quadro)
        return [{
            "linha": n,
            "id": self._texto(c, "id"),
            "atendimento": self._texto(c, "cmp_atendimento_versao"),
            "versao": _digitos(self._titulo(c, "cmp_atendimento_versao")),
            "data_evento": self._texto(c, "cmp_data_evento"),
            "titulo": self._texto(c, "cmp_receituario_hint"),
            "status": self._texto(c, "cmp_status"),
            "profissional": self._texto(c, "cmp_usuario"),
            "registros_em_aberto": _x_de_y(self._texto(c, "qtd_aberto")),
            "pdf_assinado": _x_de_y(self._texto(c, "qtd_assinado_pdf")),
            "status_assinatura": self._texto(c, "cmp_status_assinatura"),
        } for n, c in self._ler_grade(quadro, CAMPOS_NIVEL1) if "id" in c]

    def _ir_nivel2(self, id_atendimento):
        nivel1 = self._abrir_nivel1()
        n = self._linha_por_id(nivel1, CAMPOS_NIVEL1, id_atendimento)
        if n is None:
            raise ColetorBloqueado("atendimento_nao_encontrado")
        marca = self._marcar(nivel1)
        self._clicar("laudo_lapis", nivel1.locator("a#id_sc_field_cmp_ligacao_%d" % n))
        container = self._esperar_quadro(nivel1.name, CAMINHO_NIVEL2, self._ficha, marca=marca)
        return container, self._estavel(QUADRO_WIDGET_LAUDOS, CAMINHO_LISTA_LAUDOS, container)

    @_operacao("listar_laudos")
    def listar_laudos(self, atendimento):
        """Laudo, 2º nível: os laudos de um atendimento (título, data, profissional, estado)."""
        id_atendimento = atendimento["id"] if isinstance(atendimento, dict) else atendimento
        _, lista = self._ir_nivel2(id_atendimento)
        self._checar_paginacao(lista)
        laudos = []
        for n, c in self._ler_grade(lista, CAMPOS_NIVEL2):
            if "id" not in c:
                continue
            pdf = self._titulo(c, "cmp_pdf") or self._texto(c, "cmp_pdf")
            laudos.append({
                "linha": n,
                "id": self._texto(c, "id"),
                "atendimento": str(id_atendimento),
                "titulo": self._texto(c, "cmp_descricao"),
                "realizado": self._texto(c, "realizado"),
                "data": self._texto(c, "data"),
                "profissional": self._texto(c, "profissional"),
                # Só "Aguardando assinatura!" foi observado; laudo assinado é lacuna (C §4).
                "estado": ("aguardando_assinatura"
                           if "AGUARDANDO ASSINATURA" in guard.normalizar_texto(pdf)
                           else "a_confirmar"),
                "pdf": pdf,
                "assinatura": self._texto(c, "cmp_assinar"),
                "status_assinatura": self._texto(c, "cmp_status_assinatura"),
                "abertura_registro": self._titulo(c, "cmp_editavel"),
            })
        return laudos

    @_operacao("abrir_texto_laudo")
    def abrir_texto_laudo(self, laudo):
        """Abre o form do laudo (``igual``), lê ``textarea[name=receituario]`` e volta."""
        container, lista = self._ir_nivel2(laudo["atendimento"])
        n = self._linha_por_id(lista, CAMPOS_NIVEL2, laudo["id"])
        if n is None:
            raise ColetorBloqueado("laudo_nao_encontrado")
        link = lista.locator(
            "xpath=//*[@id='id_sc_field_id_%d']/ancestor::tr[1]//a["
            "contains(@href, 'form_paciente_exames_laudos_resultado') or "
            "contains(@onclick, 'form_paciente_exames_laudos_resultado')]" % n)
        marca = self._marcar(lista)
        self._clicar("laudo_abrir", link)
        form = self._esperar_quadro(QUADRO_WIDGET_LAUDOS, CAMINHO_FORM_LAUDO, container,
                                    marca=marca, pronto='textarea[name="receituario"]')
        lido = form.evaluate(_JS_FORM_LAUDO)
        if lido["texto"] is None:
            raise ColetorBloqueado("texto_ausente")
        if not lido["id"]:
            raise ColetorBloqueado("laudo_sem_id")
        if _digitos(lido["id"]) != _digitos(laudo["id"]):
            raise ColetorBloqueado("laudo_divergente")
        texto = lido["texto"]
        marca = self._marcar(form)
        voltar = form.locator('[onclick*="scFormClose_F6"]').filter(visible=True).first
        self._clicar("laudo_voltar", voltar)
        self._esperar_quadro(QUADRO_WIDGET_LAUDOS, CAMINHO_LISTA_LAUDOS, container, marca=marca)
        return {
            "id": laudo["id"],
            "atendimento": laudo["atendimento"],
            "titulo": laudo.get("titulo", ""),
            "origem": "md:laudo:%s" % _digitos(laudo["id"]),
            "texto": texto,
            "sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
        }
