"""Repassa as requisições gravadas pelo gravador (``--rede``) pela guarda.

Lê um ``rede-AAAA-MM-DD.jsonl`` e, para cada evento ``requisicao``, pergunta a
``fluxo_exames.guard.avaliar_requisicao`` se ela sairia do navegador. Serve
para conferir a guarda contra uma sessão real sem acessar o MD.

O corpo de um POST é remontado só com o que o gravador registra: os valores de
``nmgp_opcao`` e ``funcao`` do corpo urlencoded. O resto do corpo nunca foi
gravado, então chaves como ``acao`` faltam, e entradas que as exigem são
negadas no repasse. Corpo acima de 64 KB (``corpo_fora_do_evento``) é tratado
como ilegível; corpo JSON, multipart ou de tipo desconhecido, pelo tipo
registrado.

A saída agrupa por (decisão, método, host, caminho, motivo), sem query nem
corpo. Hosts de terceiros aparecem só pelo nome; URLs ``data:`` e
``chrome-extension:`` aparecem só pelo esquema.

Uso:
    python scripts/repassar_rede.py [JSONL ...]

Sem argumento, usa todos os ``rede-*.jsonl`` de
``%LOCALAPPDATA%\\FluxoExames\\captures``.
"""

import argparse
import collections
import glob
import json
import os
import sys
from urllib.parse import urlencode, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))

from fluxo_exames import guard  # noqa: E402


def _corpo(evento):
    """Corpo remontado e tipo, a partir dos campos gravados."""
    if evento.get("corpo_fora_do_evento"):
        return guard.CORPO_ILEGIVEL, evento.get("tipo_corpo")
    tipo = evento.get("tipo_corpo")
    if tipo is None:
        return None, None
    if "application/x-www-form-urlencoded" not in tipo:
        return guard.CORPO_ILEGIVEL, tipo
    pares = []
    for chave, campo in (("nmgp_opcao", "nmgp_opcao_corpo"), ("funcao", "funcao_corpo")):
        if campo in evento:
            pares.append((chave, evento[campo]))
    return urlencode(pares), tipo


def _rotulo(url):
    partes = urlsplit(url)
    if partes.scheme not in ("http", "https"):
        return partes.scheme + ":", ""
    return (partes.hostname or ""), partes.path


def repassar(caminho_jsonl):
    """Devolve um ``Counter`` de (decisão, método, host, caminho, motivo)."""
    contagem = collections.Counter()
    with open(caminho_jsonl, encoding="utf-8") as arquivo:
        for linha in arquivo:
            evento = json.loads(linha)
            if evento.get("evento") != "requisicao":
                continue
            host, caminho = _rotulo(evento["url"])
            if not caminho:           # data:, chrome-extension:, blob:
                contagem[("n/a", evento["metodo"], host, "", "fora_da_rede")] += 1
                continue
            corpo, tipo = _corpo(evento) if evento["metodo"] == "POST" else (None, None)
            permitida, motivo = guard.avaliar_requisicao(evento["metodo"], evento["url"],
                                                         corpo, tipo)
            decisao = "PASSA" if permitida else "NEGA"
            if motivo.startswith("leitura:"):
                caminho = "(GET de leitura)" if host == guard.HOST_MD else "(terceiro)"
            contagem[(decisao, evento["metodo"], host, caminho, motivo)] += 1
    return contagem


def imprimir(contagem):
    total = collections.Counter()
    for (decisao, metodo, _, _, _), n in contagem.items():
        total[(decisao, metodo)] += n
    print("  totais:", ", ".join("%s %s=%d" % (d, m, n) for (d, m), n in sorted(total.items())))
    for (decisao, metodo, host, caminho, motivo), n in sorted(contagem.items()):
        if caminho.startswith("(") and decisao == "PASSA":
            continue
        print("  %-5s %-4s %4d  %-26s %-70s %s" % (decisao, metodo, n, host[:26], caminho, motivo))
    passa_md = sum(n for (d, m, h, c, _), n in contagem.items()
                   if d == "PASSA" and c.startswith("(GET"))
    passa_terc = sum(n for (d, m, h, c, _), n in contagem.items()
                     if d == "PASSA" and c == "(terceiro)")
    print("  GETs de leitura que passam: MD=%d, terceiros=%d" % (passa_md, passa_terc))


def main():
    padrao = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                          "FluxoExames", "captures", "rede-*.jsonl")
    p = argparse.ArgumentParser(description="Repassa um jsonl do gravador pela guarda.")
    p.add_argument("jsonl", nargs="*", help="arquivos rede-*.jsonl (padrão: %s)" % padrao)
    args = p.parse_args()
    arquivos = args.jsonl or sorted(glob.glob(padrao))
    if not arquivos:
        p.error("nenhum jsonl encontrado")
    for caminho in arquivos:
        print(os.path.basename(caminho))
        imprimir(repassar(caminho))


if __name__ == "__main__":
    main()
