"""Testes da fila persistente e da máquina de estados (dados sintéticos)."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from fluxo_exames import fila as mod_fila
from fluxo_exames import state
from fluxo_exames.fila import ConflitoDeEstado, Fila

SEQUENCIA = [state.ANTECEDENTES_OK, state.PRONTO_PARA_EXAME, state.LAUDO_DO_DIA_PENDENTE,
             state.EVOLUTIVO_PENDENTE, state.REVISAO_MEDICA, state.CONCLUIDO]


@pytest.fixture
def caminho(tmp_path):
    return tmp_path / "FluxoExames" / "fila.db"


# --- máquina de estados ----------------------------------------------------------

def test_transicoes_da_sequencia_principal():
    atual = state.INICIAL
    for proximo in SEQUENCIA:
        assert state.transicao_valida(atual, proximo)
        atual = proximo
    assert state.transicao_valida(state.LAUDO_DO_DIA_PENDENTE, state.REVISAO_MEDICA)


@pytest.mark.parametrize("de, para", [
    (state.DESCOBERTO, state.PRONTO_PARA_EXAME),     # pula antecedentes
    (state.ANTECEDENTES_OK, state.DESCOBERTO),       # volta
    (state.CONCLUIDO, state.REVISAO_MEDICA),         # sai do final
    (state.CONCLUIDO, state.IDENTIDADE_PENDENTE),
    (state.DESCOBERTO, "INEXISTENTE"),
    (state.IDENTIDADE_PENDENTE, state.IDENTIDADE_PENDENTE),
])
def test_transicoes_invalidas(de, para):
    assert not state.transicao_valida(de, para)


def test_desvio_de_identidade_volta_so_para_a_origem():
    assert state.transicao_valida(state.ANTECEDENTES_OK, state.IDENTIDADE_PENDENTE)
    assert state.transicao_valida(state.IDENTIDADE_PENDENTE, state.ANTECEDENTES_OK,
                                  retorno=state.ANTECEDENTES_OK)
    assert not state.transicao_valida(state.IDENTIDADE_PENDENTE, state.PRONTO_PARA_EXAME,
                                      retorno=state.ANTECEDENTES_OK)
    assert not state.transicao_valida(state.IDENTIDADE_PENDENTE, state.ANTECEDENTES_OK)


def test_todos_os_estados_tem_transicoes():
    assert set(state.TRANSICOES) == set(state.ESTADOS) - {state.IDENTIDADE_PENDENTE}


# --- fila --------------------------------------------------------------------------

def test_caminho_padrao_em_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert mod_fila.caminho_padrao() == tmp_path / "FluxoExames" / "fila.db"


def test_ciclo_completo_com_historico(caminho):
    with Fila(caminho) as f:
        item, criado = f.inserir("900001", "US Mamas", "2026-10-01")
        assert criado and item["estado"] == state.DESCOBERTO
        for proximo in SEQUENCIA:
            item = f.atualizar_estado(item["id"], proximo, esperado=item["estado"])
        assert item["estado"] == state.CONCLUIDO
        historico = f.historico(item["id"])
        assert [h["para"] for h in historico] == [state.DESCOBERTO] + SEQUENCIA
        assert historico[0]["de"] is None
        assert f.obter_proximo() is None


def test_transicao_invalida_nao_muda_nada(caminho):
    with Fila(caminho) as f:
        item, _ = f.inserir("900001", "US Mamas", "2026-10-01")
        with pytest.raises(state.TransicaoInvalida):
            f.atualizar_estado(item["id"], state.CONCLUIDO)
        assert f.obter(item["id"])["estado"] == state.DESCOBERTO
        assert len(f.historico(item["id"])) == 1


def test_conflito_de_estado_esperado(caminho):
    with Fila(caminho) as f:
        item, _ = f.inserir("900001", "US Mamas", "2026-10-01")
        f.atualizar_estado(item["id"], state.ANTECEDENTES_OK, esperado=state.DESCOBERTO)
        with pytest.raises(ConflitoDeEstado):
            f.atualizar_estado(item["id"], state.ANTECEDENTES_OK, esperado=state.DESCOBERTO)
        with pytest.raises(KeyError):
            f.atualizar_estado(999, state.ANTECEDENTES_OK)


def test_desvio_de_identidade_pausa_so_o_item(caminho):
    with Fila(caminho) as f:
        a, _ = f.inserir("900001", "US Mamas", "2026-10-01")
        b, _ = f.inserir("900002", "US Abdome", "2026-10-01")
        f.atualizar_estado(a["id"], state.ANTECEDENTES_OK)
        pausado = f.atualizar_estado(a["id"], state.IDENTIDADE_PENDENTE)
        assert pausado["retorno"] == state.ANTECEDENTES_OK
        assert f.obter_proximo()["id"] == b["id"]          # o lote segue
        with pytest.raises(state.TransicaoInvalida):
            f.atualizar_estado(a["id"], state.PRONTO_PARA_EXAME)
        retomado = f.atualizar_estado(a["id"], state.ANTECEDENTES_OK)
        assert retomado["retorno"] is None
        assert f.obter_proximo()["id"] == a["id"]


def test_idempotencia_pela_chave_natural(caminho):
    with Fila(caminho) as f:
        item, criado = f.inserir("900001", "US Mamas", "2026-10-01")
        de_novo, criado_de_novo = f.inserir(" 900001 ", "us  mamas", "2026-10-01")
        assert criado and not criado_de_novo
        assert de_novo["id"] == item["id"]
        _, outro_dia = f.inserir("900001", "US Mamas", "2026-10-02")
        _, outro_exame = f.inserir("900001", "US Axilas", "2026-10-01")
        assert outro_dia and outro_exame
        assert len(f.itens()) == 3
        assert len(f.itens("2026-10-01")) == 2


@pytest.mark.parametrize("paciente, exame, data", [
    ("", "US Mamas", "2026-10-01"),
    ("900001", "  ", "2026-10-01"),
    ("900001", "US Mamas", "01/10/2026"),
])
def test_inserir_rejeita_chave_invalida(caminho, paciente, exame, data):
    with Fila(caminho) as f:
        with pytest.raises(ValueError):
            f.inserir(paciente, exame, data)
        assert f.itens() == []


def test_obter_proximo_por_data_e_filtros(caminho):
    with Fila(caminho) as f:
        tarde, _ = f.inserir("900002", "US Abdome", "2026-10-02")
        cedo, _ = f.inserir("900001", "US Mamas", "2026-10-01")
        assert f.obter_proximo()["id"] == cedo["id"]
        assert f.obter_proximo(data="2026-10-02")["id"] == tarde["id"]
        f.atualizar_estado(tarde["id"], state.ANTECEDENTES_OK)
        assert f.obter_proximo(estados=[state.ANTECEDENTES_OK])["id"] == tarde["id"]


def test_checkpoints_por_documento(caminho):
    with Fila(caminho) as f:
        item, _ = f.inserir("900001", "US Mamas", "2026-10-01")
        assert f.registrar_checkpoint(item["id"], "md:laudo:70001", "a" * 64)
        assert not f.registrar_checkpoint(item["id"], "md:laudo:70001", "a" * 64)
        assert f.registrar_checkpoint(item["id"], "md:laudo:70001", "b" * 64)   # texto mudou
        assert f.registrar_checkpoint(item["id"], "md:laudo:70002", "c" * 64)
        assert f.checkpoint(item["id"], "md:laudo:70001")["sha256"] == "b" * 64
        assert f.checkpoint(item["id"], "md:laudo:99999") is None
        assert [c["documento"] for c in f.checkpoints(item["id"])] == [
            "md:laudo:70001", "md:laudo:70002"]


def test_fechar_e_reabrir_preserva_tudo(caminho):
    with Fila(caminho) as f:
        item, _ = f.inserir("900001", "US Mamas", "2026-10-01")
        f.atualizar_estado(item["id"], state.ANTECEDENTES_OK)
        f.registrar_checkpoint(item["id"], "md:laudo:70001", "a" * 64)
    with Fila(caminho) as f:
        assert f.obter(item["id"])["estado"] == state.ANTECEDENTES_OK
        assert not f.registrar_checkpoint(item["id"], "md:laudo:70001", "a" * 64)
        assert f.inserir("900001", "US Mamas", "2026-10-01")[1] is False


_SCRIPT_QUEDA = textwrap.dedent("""
    import os, sys
    sys.path.insert(0, {raiz!r})
    from fluxo_exames import state
    from fluxo_exames.fila import Fila
    f = Fila({caminho!r})
    a, _ = f.inserir("900001", "US Mamas", "2026-10-01")
    b, _ = f.inserir("900001", "US Axilas", "2026-10-01")
    c, _ = f.inserir("900002", "US Abdome", "2026-10-01")
    f.atualizar_estado(a["id"], state.ANTECEDENTES_OK)
    f.registrar_checkpoint(a["id"], "md:laudo:70001", "a" * 64)
    # Queda no meio de uma transação: nada dela pode sobrar.
    f._con.execute("BEGIN IMMEDIATE")
    f._con.execute("UPDATE itens SET estado='CONCLUIDO' WHERE id=?", (b["id"],))
    f._con.execute("INSERT INTO checkpoints VALUES (?, 'md:laudo:70002', 'x', 'coletado', 'x')",
                   (b["id"],))
    os._exit(3)
""")


def test_retomada_apos_queda_sem_duplicar(caminho):
    raiz = str(Path(__file__).resolve().parents[1])
    script = _SCRIPT_QUEDA.format(raiz=raiz, caminho=str(caminho))
    saida = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=60)
    assert saida.returncode == 3, saida.stderr.decode(errors="replace")

    with Fila(caminho) as f:
        itens = f.itens()
        assert [(i["paciente"], i["exame"], i["estado"]) for i in itens] == [
            ("900001", "US Mamas", state.ANTECEDENTES_OK),
            ("900001", "US Axilas", state.DESCOBERTO),      # a transação interrompida sumiu
            ("900002", "US Abdome", state.DESCOBERTO)]
        assert f.checkpoints(itens[1]["id"]) == []
        assert f.checkpoint(itens[0]["id"], "md:laudo:70001")["sha256"] == "a" * 64

        # A coleta refeita do zero reinsere a agenda inteira: nada duplica.
        for paciente, exame in (("900001", "US Mamas"), ("900001", "US Axilas"),
                                ("900002", "US Abdome")):
            assert f.inserir(paciente, exame, "2026-10-01")[1] is False
        assert len(f.itens()) == 3
        # Retoma pelo item mais antigo com trabalho, do estado em que parou.
        proximo = f.obter_proximo()
        assert proximo["id"] == itens[0]["id"] and proximo["estado"] == state.ANTECEDENTES_OK
        assert not f.registrar_checkpoint(itens[0]["id"], "md:laudo:70001", "a" * 64)
        f.atualizar_estado(itens[1]["id"], state.ANTECEDENTES_OK, esperado=state.DESCOBERTO)
