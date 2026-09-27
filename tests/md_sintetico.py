"""Servidor local que imita a estrutura do MD descrita no mapa (B §3 e §4).

Só dados sintéticos ("Paciente A", "Paciente B"). Reproduz a árvore de
quadros, os ids ``id_sc_field_<campo>_<n>``, os formulários F1/F3/F6 e os
mecanismos de navegação (auto-POST do menu, ``nm_gp_submit4/5``,
``ajax_save_ancor``, ``igual``, ``_fim.php``), além dos botões de escrita
("Finalizar e Assinar", Salvar, Imprimir, ASSINAR PDF, cadeado, status da
agenda), que chamam os mesmos endpoints do MD.

Toda requisição recebida fica em ``requisicoes``, com o corpo cru. O teste
confere do lado do servidor que nada que a guarda nega chegou aqui.
"""

import hashlib
import html
import itertools
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from fluxo_exames import guard

DATA_AGENDA = "2026-10-01"

PACIENTES = {
    "900001": {
        "nome": "Paciente A", "sexo": "F", "dn": "01/01/1900", "cpf": "00000000000",
        "atendimentos": [
            {"id": "5001", "numero": "11", "versao": "2", "data": "20/09/2026 10:00 UTC-3",
             "titulo": "US Mamas / US Axilas", "status": "Fechado",
             "profissional": "Profissional X", "aberto": "0 de 2", "assinado": "0 de 2",
             "laudos": [
                 {"id": "70001", "titulo": "US Mamas", "data": "20/09/2026",
                  "profissional": "Profissional X", "realizado": "Interno",
                  "texto": "<p>Paciente A. Texto sintético do laudo L1.</p>"
                           "<p>Conclusão: BI-RADS 2 (sintético).</p>"},
                 {"id": "70002", "titulo": "US Axilas", "data": "20/09/2026",
                  "profissional": "Profissional X", "realizado": "Interno",
                  "texto": "<p>Paciente A. Texto sintético do laudo L2 &amp; "
                           "linfonodos <b>sem</b> alterações.</p>"},
             ]},
            {"id": "5002", "numero": "12", "versao": "1", "data": "10/03/2026 09:00 UTC-3",
             "titulo": "US Tireoide", "status": "Fechado", "profissional": "Profissional X",
             "aberto": "0 de 1", "assinado": "0 de 1",
             "laudos": [
                 {"id": "70003", "titulo": "US Tireoide", "data": "10/03/2026",
                  "profissional": "Profissional X", "realizado": "Interno",
                  "texto": "<p>Paciente A. Tireoide sintética.</p>"},
             ]},
        ],
    },
    "900002": {
        "nome": "Paciente B", "sexo": "M", "dn": "02/02/1900", "cpf": "00000000001",
        "atendimentos": [
            {"id": "5101", "numero": "21", "versao": "1", "data": "05/05/2026 08:00 UTC-3",
             "titulo": "US Abdome", "status": "Fechado", "profissional": "Profissional Y",
             "aberto": "0 de 1", "assinado": "0 de 1",
             "laudos": [
                 {"id": "71001", "titulo": "US Abdome", "data": "05/05/2026",
                  "profissional": "Profissional Y", "realizado": "Interno",
                  "outro_profissional": True,
                  "texto": "<p>Paciente B. Abdome sintético.</p>"},
             ]},
        ],
    },
}

AGENDA = [("08:00", "900001", "US Mamas"), ("08:30", "900002", "US Abdome")]

# Assinaturas de escrita que nunca podem chegar ao servidor.
ENDPOINTS_ESCRITA = (
    "/blank_status/", "/blank_editavel/", "/blank_assinatura_digital/", "/blank_laudo_pdf/",
    "/blank_notifica_lembrete/", "/blank_fecha_atendimento/", "/blank_desmarcar/",
)
OPCOES_ESCRITA = {"alterar", "incluir", "excluir", "novo", "formphp"}

_ESTILO = ("<style>iframe{width:1000px;height:600px;border:1px solid #999}"
           "a{cursor:pointer}</style>")

_JQUERY_MINIMO = """<script>
window.jQuery = window.$ = function (seletor) {
  const el = document.querySelector(seletor);
  return { load: function (url, cb) {
    fetch(url, {credentials: 'same-origin'})
      .then(r => r.text().then(t => [t, r.ok]))
      .then(([t, ok]) => {
        el.innerHTML = t;
        el.querySelectorAll('script').forEach(s => {
          const n = document.createElement('script'); n.textContent = s.textContent;
          s.replaceWith(n);
        });
        if (cb) cb(t, ok ? 'success' : 'error');
      })
      .catch(() => { if (cb) cb('', 'error'); });
    return this;
  } };
};
</script>"""

_JS_IFRAMES = """<script>
function mostrar(fr) {
  for (const f of document.querySelectorAll('#conteudo > iframe')) f.style.display = (f === fr ? '' : 'none');
}
function abrirIframe(id, nome, url) {
  let fr = document.getElementById(id);
  if (!fr) { fr = document.createElement('iframe'); fr.id = id; fr.name = nome;
             document.getElementById('conteudo').appendChild(fr); }
  fr.src = url; mostrar(fr);
}
document.querySelectorAll('a[item-href]').forEach(a => a.addEventListener('click', ev => {
  ev.preventDefault();
  abrirIframe('iframe_' + a.id, a.getAttribute('item-target'), a.getAttribute('item-href'));
}));
</script>"""


def _pagina(titulo, corpo):
    return ("<!doctype html><html><head><meta charset='utf-8'><title>%s</title>%s</head>"
            "<body>%s</body></html>" % (html.escape(titulo), _ESTILO, corpo))


def _auto_post(acao, init):
    return _pagina("", (
        "<form name='F1' method='post' action='%s'>"
        "<input type='hidden' name='script_case_init' value='%s'>"
        "<input type='hidden' name='nm_run_menu' value='1'></form>"
        "<script>document.F1.submit()</script>") % (acao, init))


def _post_js(url, corpo):
    return ("fetch('%s', {method: 'POST', headers: {'Content-Type': "
            "'application/x-www-form-urlencoded'}, body: '%s'}).catch(() => 0);" % (url, corpo))


def _item_menu(n, app, texto, alvo, prefixo):
    return ("<li><a id='item_%d' href='#' item-href='%s_form_php.php?sc_item_menu=item_%d"
            "&amp;sc_apl_menu=%s&amp;sc_apl_link=/&amp;sc_usa_grupo=' item-target='%s'>%s</a>"
            "</li>" % (n, prefixo, n, app, alvo, html.escape(texto)))


class MDSintetico:
    def __init__(self, paginacao=False, armadilha=False):
        self.paginacao = paginacao
        self.armadilha = armadilha
        self.requisicoes = []
        self._trava = threading.Lock()
        self._init = itertools.count(100)
        self._tokens = {}
        self.sessao = {"paciente": None, "atendimento": None, "fichas": 0}
        self._servidor = None

    # --- ciclo de vida -------------------------------------------------------

    def iniciar(self):
        servidor_md = self

        class Tratador(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                servidor_md._atender(self, "GET")

            def do_POST(self):
                servidor_md._atender(self, "POST")

            def do_PUT(self):
                servidor_md._atender(self, "PUT")

            def do_DELETE(self):
                servidor_md._atender(self, "DELETE")

        self._servidor = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
        threading.Thread(target=self._servidor.serve_forever, daemon=True).start()
        return self.url

    def parar(self):
        if self._servidor:
            self._servidor.shutdown()
            self._servidor.server_close()

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self._servidor.server_address[1]

    # --- verificação do lado do servidor --------------------------------------

    def recebidas(self, metodo=None, caminho=None):
        return [r for r in self.requisicoes
                if (metodo is None or r["metodo"] == metodo)
                and (caminho is None or r["caminho"].startswith(caminho))]

    def violacoes(self):
        """Requisições que chegaram mas que a guarda nega."""
        saida = []
        for r in self.requisicoes:
            url = "https://%s%s%s" % (guard.HOST_MD, r["caminho"],
                                      "?" + r["query"] if r["query"] else "")
            permitida, motivo = guard.avaliar_requisicao(r["metodo"], url, r["corpo"] or None,
                                                         r["tipo"])
            if not permitida:
                saida.append((r["metodo"], r["caminho"], motivo))
        return saida

    def escritas(self):
        """Requisições com assinatura explícita de escrita, assinatura ou envio."""
        saida = []
        for r in self.requisicoes:
            pares = parse_qsl(r["query"], keep_blank_values=True)
            if "multipart" not in (r["tipo"] or ""):
                pares += parse_qsl(r["corpo"].decode("utf-8", "replace"), keep_blank_values=True)
            opcoes = {v.lower() for k, v in pares if k == "nmgp_opcao"}
            if (r["metodo"] not in ("GET", "POST")
                    or any(r["caminho"].startswith(e) for e in ENDPOINTS_ESCRITA)
                    or opcoes & OPCOES_ESCRITA
                    or any(k in ("rs", "nm_call_php") for k, _ in pares)
                    or "multipart" in (r["tipo"] or "")
                    or b"formphp" in r["corpo"]):
                saida.append((r["metodo"], r["caminho"]))
        return saida

    # --- HTTP ----------------------------------------------------------------

    def _atender(self, tratador, metodo):
        partes = urlsplit(tratador.path)
        tamanho = int(tratador.headers.get("Content-Length") or 0)
        corpo = tratador.rfile.read(tamanho) if tamanho else b""
        tipo = tratador.headers.get("Content-Type")
        with self._trava:
            self.requisicoes.append({"metodo": metodo, "caminho": partes.path,
                                     "query": partes.query, "corpo": corpo, "tipo": tipo})
        pares = dict(parse_qsl(partes.query, keep_blank_values=True))
        if metodo == "POST" and "multipart" not in (tipo or ""):
            pares.update(parse_qsl(corpo.decode("utf-8", "replace"), keep_blank_values=True))
        status, conteudo = self._rotear(metodo, partes.path, pares)
        dados = conteudo.encode("utf-8")
        tratador.send_response(status)
        tratador.send_header("Content-Type", "text/html; charset=utf-8")
        tratador.send_header("Content-Length", str(len(dados)))
        tratador.send_header("Cache-Control", "no-store")
        tratador.end_headers()
        tratador.wfile.write(dados)

    def _token(self, valor):
        token = hashlib.md5(("%s-%d" % (valor, next(self._init))).encode()).hexdigest()
        self._tokens[token] = valor
        return token

    def _do_token(self, nmgp_parms):
        return self._tokens.get(nmgp_parms.rsplit("@SC_par@", 1)[-1])

    def _rotear(self, metodo, caminho, p):
        init = next(self._init)
        if metodo == "GET":
            if caminho == "/menu_inicial/":
                return 200, self._menu()
            if caminho == "/home/home.php":
                return 200, _pagina("Home", "<p>Início (sintético)</p>")
            if caminho.endswith("_form_php.php"):
                return 200, _auto_post("/%s/" % p.get("sc_apl_menu", ""), init)
            if caminho == "/grid_agenda_md_calendario/grid_agenda_md_calendario.php":
                return 200, self._grade_agenda(p.get("dt", ""))
            if caminho == "/treemenu_paciente/":
                return 200, self._ficha(p.get("nmgp_parms", ""))
            if caminho == "/form_paciente_sbis/form_paciente_sbis.php":
                return 200, _pagina("Dados Gerais", "<input id='id_sc_field_cpf' value=''>")
            if caminho == "/menu_info_comp/menu_info_comp.php":
                return 200, _pagina("Histórico", "")
            if caminho == "/grid_exames_laudo/grid_exames_laudo.php":
                return 200, self._nivel1()
            if caminho == CAMINHO_LISTA:
                return 200, self._lista_laudos()
            if caminho == "/grid_exames_resultados_laudo/":
                return 200, _pagina("Resultado", "<table></table>")
            return 404, _pagina("404", "")
        if metodo == "POST":
            if caminho == "/blank_div/":
                return 200, self._agenda()
            if caminho == "/blank_treemenu_paciente/":
                return 200, _pagina("", "<script>location.href='/form_paciente_sbis/"
                                        "form_paciente_sbis.php'</script>")
            if caminho == "/grid_exames_laudo/":
                return 200, self._nivel1()
            if caminho == "/cont_exame_resultado_laudo/":
                pares = guard._pares_de_nmgp_parms(p.get("nmgp_parms", ""))
                self.sessao["atendimento"] = dict(pares).get("vg_exames_resultados")
                return 200, self._container()
            if caminho == CAMINHO_LISTA + "index.php":
                return 200, "OK"
            if caminho == CAMINHO_LISTA:
                return 200, self._lista_laudos()
            if caminho == CAMINHO_FORM:
                if p.get("nmgp_opcao") == "igual":
                    return 200, self._form_laudo(self._do_token(p.get("nmgp_parms", "")))
                return 200, "gravado"
            if caminho == CAMINHO_FORM + "form_paciente_exames_laudos_resultado_fim.php":
                return 200, _pagina("", (
                    "<form name='F' method='post' action='%s'><input type='hidden' "
                    "name='script_case_init' value='%s'></form>"
                    "<script>document.F.submit()</script>") % (CAMINHO_LISTA, init))
            return 200, "{}"
        return 405, ""

    # --- telas ---------------------------------------------------------------

    def _menu(self):
        return _pagina("Medicina Direta (sintético)", (
            "<ul id='menu'>%s</ul><div id='conteudo'>"
            "<iframe id='iframe_menu_inicial' name='menu_inicial_iframe' "
            "src='/home/home.php?nm_run_menu=1&amp;nm_apl_menu=menu_inicial&amp;"
            "script_case_init=1'></iframe></div>%s"
            "<script>function abrirFicha(url) { abrirIframe('iframe_treemenu_paciente', "
            "'menu_inicial_treemenu_paciente_iframe', url); }</script>") % (
                _item_menu(31, "blank_div", "Agendamento", "menu_inicial_item_31_iframe",
                           "menu_inicial"),
                _JS_IFRAMES))

    def _agenda(self):
        hoje = "2000-01-01"   # carga inicial: dia sem agenda
        return _pagina("Agenda", (
            "%s<div id='calendario'>calendário</div><div id='campotabela'></div>"
            "<script>jQuery('#campotabela').load('../grid_agenda_md_calendario/"
            "grid_agenda_md_calendario.php?dia=1&mes=1&ano=2000&dt=%s')</script>") % (
                _JQUERY_MINIMO, hoje))

    def _grade_agenda(self, data):
        if data != DATA_AGENDA:
            return "<div class='scGridSemRegistro'>Nenhum registro</div>"
        linhas = []
        for n, (hora, pront, titulo) in enumerate(AGENDA, 1):
            parms = "@SC_par@1@SC_par@grid_agenda_md_calendario@SC_par@%s" % self._token(pront)
            linhas.append((
                "<tr><td><span id='id_sc_field_cmp_hora_ini_{n}'>{hora}</span></td>"
                "<td><a id='id_sc_field_c_nome_{n}' href=\"javascript:nm_gp_submit5("
                "'/treemenu_paciente/', '/grid_agenda_md_calendario/', '{parms}', '_blank', "
                "'', '')\">{nome}</a></td>"
                "<td><span id='id_sc_field_cmp_img_{n}'>{pront}</span></td>"
                "<td><span id='id_sc_field_c_celular_{n}'>(00) 00000-0000</span></td>"
                "<td><span id='id_sc_field_cmp_atendimento_{n}'>{n}</span></td>"
                "<td><span id='id_sc_field_a_titulo_{n}'>{titulo}</span></td>"
                "<td><span id='id_sc_field_e_ds_agenda_status_{n}'>Agendado</span></td>"
                "<td><a id='id_sc_field_cmp_chegada_{n}' onclick=\"fetch('../blank_status/"
                "blank_status.php?id={n}')\">Chegou</a></td></tr>").format(
                    n=n, hora=hora, parms=parms, nome=PACIENTES[pront]["nome"], pront=pront,
                    titulo=titulo))
        return ("<table class='scGridTabela'>%s</table><script>"
                "function nm_gp_submit5(apl, orig, parms, alvo) {"
                "  top.abrirFicha(apl + '?nmgp_parms=' + encodeURIComponent(parms)"
                "    + '&nm_run_menu=1&nmgp_opcao=&script_case_init=7'); }</script>"
                % "".join(linhas))

    def _ficha(self, nmgp_parms):
        pront = self._do_token(nmgp_parms)
        if pront is None:
            return _pagina("Erro", "sessão inválida")
        self.sessao["paciente"] = pront
        self.sessao["fichas"] += 1
        pac = PACIENTES[pront]
        rotulos = [("Prontuário:", pront), ("Nome:", pac["nome"]), ("Sexo:", pac["sexo"]),
                   ("Data de Nascimento:", pac["dn"]), ("Idade:", "126"), ("CPF:", pac["cpf"]),
                   ("Convênio:", "Particular"),
                   ("" if pront == "900002" else "E-mail:", "sintetico@exemplo.invalid")]
        cabecalho = "".join(
            "<div class='cabecalho__grupo-info'><a class='cabecalho__campo-nome'>%s</a>"
            "<a class='cabecalho__campo-valor'%s>%s</a></div>" % (
                html.escape(r), " id='id_titulo_atend'" if r.startswith("Conv") else "",
                html.escape(v)) for r, v in rotulos)
        arvore = "".join(_item_menu(n, app, texto, "treemenu_paciente_item_%d_iframe" % n,
                                    "treemenu_paciente") for n, app, texto in (
            (17, "blank_treemenu_paciente", "Dados Gerais"),
            (19, "grid_tbl_pacientes_crm", "Evolução (1)"),
            (163, "grid_exames_solicitacao", "Solicitação"),
            (164, "grid_exames_resultados", "Resultado"),
            (165, "grid_exames_laudo", "Laudo")))
        automaticos = (
            _post_js("../blank_sessao_funcoes/blank_sessao_funcoes.php",
                     "funcao=limpar_sessao_aplicacoes")
            + _post_js("../blank_notifica_lembrete/blank_notifica_lembrete.php",
                       "id_org=1&id_usuario=1&id_paciente=1")
            + "document.addEventListener('DOMContentLoaded', () => { "
            + _post_js("../blank_treemenu_paciente_funcoes/blank_treemenu_paciente_funcoes.php",
                       "funcao=config_itens_historico") + " });")
        if self.sessao["fichas"] > 1:
            automaticos += ("fetch('../blank_fecha_atendimento/blank_fecha_atendimento.php"
                            "?tipo=t').catch(() => 0);")
        return _pagina("Ficha Clínica", (
            "<div class='cabecalho'>%s</div><ul id='arvore'>%s</ul><div id='conteudo'>"
            "<iframe id='iframe_treemenu_paciente' name='treemenu_paciente_iframe' "
            "src='treemenu_paciente_form_php.php?sc_item_menu=treemenu_paciente&amp;"
            "sc_apl_menu=blank_treemenu_paciente&amp;sc_apl_link=/&amp;sc_usa_grupo='></iframe>"
            "</div><iframe id='frame_historico_prontuario' "
            "src='/menu_info_comp/menu_info_comp.php'></iframe>%s<script>%s</script>") % (
                cabecalho, arvore, _JS_IFRAMES, automaticos))

    def _paciente(self):
        return PACIENTES[self.sessao["paciente"]]

    def _nivel1(self):
        linhas = []
        for n, at in enumerate(self._paciente()["atendimentos"], 1):
            linhas.append((
                "<tr><td><a id='id_sc_field_cmp_ligacao_{n}' style='display:inline-block;"
                "width:16px;height:16px;background:#ccc' href=\"javascript:nm_gp_submit5("
                "'/cont_exame_resultado_laudo/', '/grid_exames_laudo/', 'OrScLink?#?1?@?"
                "vg_exames_resultados?#?{id}?@?vg_id_exame?#?{id}?@?', '_self', '', '')\" "
                "onmouseover=\"nm_mostra_hint(this, 'Editar o Registro')\"></a></td>"
                "<td><span id='id_sc_field_id_{n}'>{id}</span></td>"
                "<td><span id='id_sc_field_cmp_atendimento_versao_{n}' title='Versão: "
                "{versao}'>{numero}</span></td>"
                "<td><span id='id_sc_field_cmp_data_evento_{n}'>{data}</span></td>"
                "<td><span id='id_sc_field_cmp_receituario_hint_{n}'>{titulo}</span></td>"
                "<td><a id='id_sc_field_cmp_status_{n}' href='grid_exames_laudos_fase.php?"
                "vg_id_exames_laudos={id}'>{status}</a></td>"
                "<td><span id='id_sc_field_cmp_usuario_{n}'>{profissional}</span></td>"
                "<td><span id='id_sc_field_qtd_aberto_{n}'>{aberto}</span></td>"
                "<td><span id='id_sc_field_qtd_assinado_pdf_{n}'>{assinado}</span></td>"
                "<td><a id='id_sc_field_cmp_editavel_{n}' onclick='fn_js_editavel({id})'>"
                "<img alt='' title='Cadeado'></a></td>"
                "<td><span id='id_sc_field_cmp_status_assinatura_{n}'></span></td></tr>"
            ).format(n=n, **{k: html.escape(str(v)) for k, v in at.items() if k != "laudos"}))
        paginacao = ("<span id='sc_b_avc_bot' onclick=\"nm_gp_move('avanca')\">Avançar"
                     "</span>" if self.paginacao else "")
        return _pagina("Laudo", (
            "<input type='button' id='sc_vincular_solicitacao_top' value='Vincular "
            "Solicitação'><table>%s</table>%s"
            "<form name='F3' method='post'><input type='hidden' name='nmgp_opcao' value=''>"
            "<input type='hidden' name='nmgp_parms' value=''><input type='hidden' "
            "name='script_case_init' value='3'></form><script>"
            "function nm_gp_submit5(apl, orig, parms, alvo) { document.F3.action = apl; "
            "document.F3.target = alvo; document.F3.nmgp_opcao.value = ''; "
            "document.F3.nmgp_parms.value = parms; document.F3.submit(); }"
            "function nm_mostra_hint() {}"
            "function fn_js_editavel(id) { %s }</script>") % (
                "".join(linhas), paginacao,
                _post_js("../blank_editavel/blank_editavel.php", "id=' + id + '")))

    def _container(self):
        widget = ("%s?script_case_init=11&under_dashboard=1&dashboard_app="
                  "cont_exame_resultado_laudo&own_widget=dbifrm_widget3" % CAMINHO_LISTA)
        return _pagina("Laudo", (
            "<iframe id='id-iframe-0' name='dbifrm_widget3' src='%s'></iframe>"
            "<iframe id='id-iframe-1' name='dbifrm_widget5' src='/grid_exames_resultados_laudo/"
            "?script_case_init=12&amp;under_dashboard=1&amp;own_widget=dbifrm_widget5'></iframe>"
            # O MD recarrega o widget 3 com o parâmetro de maximizar (B §2, 19:47:19).
            "<script>setTimeout(() => { document.getElementById('id-iframe-0').src = '%s' "
            "+ '&nm_maximizar=S'; }, 50);</script>") % (widget.replace("&", "&amp;"), widget))

    def _atendimento(self):
        for at in self._paciente()["atendimentos"]:
            if at["id"] == self.sessao["atendimento"]:
                return at
        return {"laudos": []}

    def _lista_laudos(self):
        linhas = []
        for n, laudo in enumerate(self._atendimento()["laudos"], 1):
            parms = ("@SC_par@1@SC_par@grid_paciente_exames_laudos_resultado@SC_par@%s"
                     % self._token(laudo["id"]))
            assinar = ("Registro de outro profissional" if laudo.get("outro_profissional") else
                       "<a onclick='fn_js_assinatura_pdf_lc(%s)'>ASSINAR PDF</a>" % laudo["id"])
            id_fmt = "%s.%s" % (laudo["id"][:-3], laudo["id"][-3:])
            linhas.append((
                "<tr><td><span id='id_sc_field_id_{n}'>{id_fmt}</span></td>"
                "<td><a id='id_sc_field_cmp_descricao_{n}' href=\"javascript:nm_gp_submit4("
                "'/form_paciente_exames_laudos_resultado/', '/grid_paciente_exames_laudos_"
                "resultado/', '{parms}', '_self', '', 'form_paciente_exames_laudos_resultado', "
                "'{n}')\">{titulo}</a></td>"
                "<td><span id='id_sc_field_realizado_{n}'>{realizado}</span></td>"
                "<td><span id='id_sc_field_data_{n}'>{data}</span></td>"
                "<td><span id='id_sc_field_profissional_{n}'>{profissional}</span></td>"
                "<td><span id='id_sc_field_cmp_assinar_{n}'>{assinar}</span></td>"
                "<td><span id='id_sc_field_cmp_pdf_{n}'><img alt='' "
                "title='Aguardando assinatura!'></span></td>"
                "<td><span id='id_sc_field_cmp_status_assinatura_{n}'></span></td>"
                "<td><span id='id_sc_field_cmp_editavel_{n}'><img id='imagem{id}' alt='' "
                "title='Abertura do Registro: {data} 10:05'></span></td></tr>").format(
                    n=n, id=laudo["id"], id_fmt=id_fmt, parms=parms, assinar=assinar,
                    titulo=html.escape(laudo["titulo"]), realizado=laudo["realizado"],
                    data=laudo["data"], profissional=html.escape(laudo["profissional"])))
        return _pagina("Consulta - tbl_paciente_exames_laudos", (
            "<a id='sc_b_voltar_top' onclick='sc_btn_voltar_js_top()'>Voltar</a> "
            "<span id='sc_btgp_btn_group_1_top'>Criar Laudo</span>"
            "<a id='sc_btn_novo_top' onclick=\"%s\">Interno - Em Branco</a>"
            "<table>%s</table>"
            "<form name='F3' method='post'><input type='hidden' name='nmgp_opcao' value=''>"
            "<input type='hidden' name='nmgp_parms' value=''><input type='hidden' "
            "name='script_case_init' value='11'></form><script>"
            "function nm_gp_submit4(apl, orig, parms, alvo, x, dest, ancora) {"
            "  fetch('index.php', {method: 'POST', headers: {'Content-Type': "
            "'application/x-www-form-urlencoded'}, body: 'nmgp_opcao=ajax_save_ancor&"
            "script_case_init=11&ancor_save=' + ancora}).then(() => {"
            "    document.F3.action = apl; document.F3.target = alvo;"
            "    document.F3.nmgp_opcao.value = 'igual'; document.F3.nmgp_parms.value = parms;"
            "    document.F3.submit(); }); }"
            "function fn_js_assinatura_pdf_lc(id) { %s }"
            "function sc_btn_voltar_js_top() { window.open('/grid_exames_laudo/"
            "grid_exames_laudo.php', '_parent'); }</script>") % (
                _post_js("/form_paciente_exames_laudos_resultado/index.php", "nmgp_opcao="),
                "".join(linhas),
                _post_js("../blank_assinatura_digital/blank_assinatura_digital.php",
                         "requisito=1&receitaId=' + id + '")))

    def _form_laudo(self, id_laudo):
        laudo = next((l for p in PACIENTES.values() for a in p["atendimentos"]
                      for l in a["laudos"] if l["id"] == id_laudo), None)
        if laudo is None:
            return _pagina("Erro", "registro não encontrado")
        voltar = ("<a id='sc_b_sai_t' onclick=\"scFormClose_F6('form_paciente_exames_laudos_"
                  "resultado_fim.php')\">Voltar</a>")
        if self.armadilha:
            voltar = ("<a id='sc_b_sai_t' onclick=\"scFormClose_F6('form_paciente_exames_laudos_"
                      "resultado_fim.php'); scBtnFn_finalizar_assinar()\">Finalizar e Assinar</a>")
        return _pagina("Atualização - tbl_paciente_exames_laudos", (
            "<div id='barra'>%s "
            "<a id='sc_imprimir_normal_top' onclick='sc_btn_imprimir_normal_ok()'>Imprimir</a> "
            "<a id='sc_btgp_btn_group_2_top'>Enviar Por</a> "
            "<a id='sc_email_top' onclick='scBtnFn_email()'>E-MAIL</a> "
            "<a id='sc_finalizar_assinar_top' onclick='scBtnFn_finalizar_assinar()'>"
            "Finalizar e Assinar</a>"
            "<a id='sc_b_upd_t' style='display:none' onclick=\"nm_atualiza('alterar')\">"
            "Salvar</a>"
            "<a id='sc_b_del_t' style='display:none' onclick=\"nm_atualiza('excluir')\">"
            "Excluir</a></div>"
            "<form name='F1' method='post' action='./' enctype='multipart/form-data'>"
            "<input type='hidden' name='nmgp_opcao' value=''>"
            "<input type='hidden' name='nmgp_parms' value=''>"
            "<input type='hidden' name='csrf_token' value='tok'>"
            "<span id='id_read_on_id' style='display:none'>{id}</span>"
            "<input id='id_sc_field_id' name='id' value='{id}' readonly>"
            "<input id='id_sc_field_descricao' name='descricao' value='{titulo}'>"
            "<textarea id='id_sc_field_receituario' name='receituario'>{texto}</textarea>"
            "<textarea id='id_sc_field_laudo_obs' name='laudo_obs'></textarea></form>"
            "<form name='F6' method='post' action=''><input type='hidden' "
            "name='script_case_init' value='13'></form><script>"
            "function scFormClose_F6(url) { document.F6.action = url; document.F6.submit(); }"
            "function nm_atualiza(op) { document.F1.nmgp_opcao.value = op; document.F1.submit(); }"
            "function scBtnFn_finalizar_assinar() { %s }"
            "function sc_btn_imprimir_normal_ok() { document.F1.nmgp_parms.value = "
            "'nmgp_opcao?#?formphp?@?nm_call_php?#?imprimir_normal?@?'; "
            "document.F1.target = '_blank'; document.F1.submit(); }"
            "function scBtnFn_email() { document.F1.nmgp_parms.value = "
            "'nmgp_opcao?#?formphp?@?nm_call_php?#?email?@?'; document.F1.submit(); }"
            "</script>") % (
                voltar,
                _post_js("./", "rs=event_scajaxbutton_finalizar_assinar_onclick&rst=&rsargs[]="
                         + laudo["id"]))).replace("{id}", laudo["id"]).replace(
                "{titulo}", html.escape(laudo["titulo"])).replace(
                "{texto}", html.escape(laudo["texto"]))


CAMINHO_LISTA = "/grid_paciente_exames_laudos_resultado/"
CAMINHO_FORM = "/form_paciente_exames_laudos_resultado/"
