"""Fila persistente dos itens da agenda (F1), em SQLite.

Cada item é um exame de um paciente num dia, identificado pela chave natural
(paciente, exame, data). Inserir de novo a mesma chave devolve o item que já
existe: rodar a coleta duas vezes, ou retomá-la depois de uma queda, não
duplica nada.

O estado segue a máquina de ``state.py``. Toda mudança passa por
``atualizar_estado``, que valida a transição, grava o histórico e aceita um
``esperado`` (compare-and-set) para duas execuções não avançarem o mesmo item.

Checkpoints são por documento (``md:laudo:<id>`` etc.), com o hash do
conteúdo. Na retomada, o coletor pula o documento cujo hash não mudou.

O arquivo fica em ``%LOCALAPPDATA%\\FluxoExames\\fila.db``, fora do
repositório e das pastas sincronizadas. O banco usa WAL com
``synchronous=FULL``: o que foi confirmado sobrevive a uma queda do processo,
e uma transação interrompida é desfeita na abertura seguinte.

A fila não guarda texto de laudo nem dado clínico: só a chave do item, o
estado e os hashes dos documentos.
"""

import os
import sqlite3
import unicodedata
from datetime import date, datetime
from pathlib import Path

from fluxo_exames import state

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS itens (
    id            INTEGER PRIMARY KEY,
    paciente      TEXT NOT NULL,
    exame         TEXT NOT NULL,
    data          TEXT NOT NULL,
    chave_paciente TEXT NOT NULL,
    chave_exame   TEXT NOT NULL,
    estado        TEXT NOT NULL,
    retorno       TEXT,
    criado_em     TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    UNIQUE (chave_paciente, chave_exame, data)
);
CREATE TABLE IF NOT EXISTS historico (
    id       INTEGER PRIMARY KEY,
    item_id  INTEGER NOT NULL REFERENCES itens(id),
    de       TEXT,
    para     TEXT NOT NULL,
    em       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (
    item_id       INTEGER NOT NULL REFERENCES itens(id),
    documento     TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    situacao      TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    PRIMARY KEY (item_id, documento)
);
"""


class ConflitoDeEstado(RuntimeError):
    """O item não estava no estado esperado (outra execução o moveu)."""


def caminho_padrao():
    """``%LOCALAPPDATA%\\FluxoExames\\fila.db``."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "FluxoExames" / "fila.db"


def chave_natural(texto):
    """Forma de comparação: sem acento, espaços juntos, sem caixa."""
    decomposto = unicodedata.normalize("NFKD", str(texto or ""))
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acento.split()).casefold()


def _agora():
    return datetime.now().isoformat(timespec="seconds")


def _data_iso(valor):
    if isinstance(valor, date):
        return valor.isoformat()
    return date.fromisoformat(str(valor)).isoformat()


class Fila:
    """Fila de itens num arquivo SQLite. Use como gerenciador de contexto."""

    def __init__(self, caminho=None):
        self.caminho = Path(caminho) if caminho else caminho_padrao()
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(self.caminho), isolation_level=None, timeout=10)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=FULL")
        self._con.execute("PRAGMA foreign_keys=ON")
        self._con.executescript(_ESQUEMA)

    def fechar(self):
        self._con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fechar()

    def _transacao(self):
        return _Transacao(self._con)

    # --- itens -----------------------------------------------------------

    def inserir(self, paciente, exame, data):
        """Insere o item, ou devolve o existente. Retorna ``(item, criado)``."""
        if not chave_natural(paciente) or not chave_natural(exame):
            raise ValueError("paciente e exame são obrigatórios")
        data = _data_iso(data)
        chaves = (chave_natural(paciente), chave_natural(exame), data)
        with self._transacao() as con:
            linha = con.execute(
                "SELECT id FROM itens WHERE chave_paciente=? AND chave_exame=? AND data=?",
                chaves).fetchone()
            if linha:
                return self.obter(linha["id"]), False
            agora = _agora()
            cursor = con.execute(
                "INSERT INTO itens (paciente, exame, data, chave_paciente, chave_exame, "
                "estado, criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (str(paciente).strip(), str(exame).strip(), data, chaves[0], chaves[1],
                 state.INICIAL, agora, agora))
            con.execute("INSERT INTO historico (item_id, de, para, em) VALUES (?, NULL, ?, ?)",
                        (cursor.lastrowid, state.INICIAL, agora))
            return self.obter(cursor.lastrowid), True

    def obter(self, item_id):
        linha = self._con.execute("SELECT * FROM itens WHERE id=?", (item_id,)).fetchone()
        return dict(linha) if linha else None

    def itens(self, data=None):
        if data is None:
            linhas = self._con.execute("SELECT * FROM itens ORDER BY data, id")
        else:
            linhas = self._con.execute("SELECT * FROM itens WHERE data=? ORDER BY id",
                                       (_data_iso(data),))
        return [dict(l) for l in linhas]

    def obter_proximo(self, estados=None, data=None):
        """Item mais antigo que ainda tem trabalho, ou ``None``.

        Pula os finais e os pausados em ``IDENTIDADE_PENDENTE``. ``estados``
        restringe aos estados dados; ``data`` a um dia.
        """
        fora = tuple(state.FINAIS | {state.IDENTIDADE_PENDENTE})
        sql = "SELECT * FROM itens WHERE estado NOT IN (%s)" % ",".join("?" * len(fora))
        args = list(fora)
        if estados:
            sql += " AND estado IN (%s)" % ",".join("?" * len(estados))
            args += list(estados)
        if data is not None:
            sql += " AND data=?"
            args.append(_data_iso(data))
        linha = self._con.execute(sql + " ORDER BY data, id LIMIT 1", args).fetchone()
        return dict(linha) if linha else None

    def atualizar_estado(self, item_id, novo, esperado=None):
        """Move o item para ``novo``, validando a transição.

        ``esperado``: se dado e o item não estiver nele, levanta
        ``ConflitoDeEstado`` sem mudar nada.
        """
        with self._transacao() as con:
            linha = con.execute("SELECT estado, retorno FROM itens WHERE id=?",
                                (item_id,)).fetchone()
            if linha is None:
                raise KeyError(item_id)
            de, retorno = linha["estado"], linha["retorno"]
            if esperado is not None and de != esperado:
                raise ConflitoDeEstado("item %s está em %s, esperado %s" % (item_id, de, esperado))
            if not state.transicao_valida(de, novo, retorno):
                raise state.TransicaoInvalida("%s -> %s" % (de, novo))
            if novo == state.IDENTIDADE_PENDENTE:
                retorno = de
            elif de == state.IDENTIDADE_PENDENTE:
                retorno = None
            agora = _agora()
            con.execute("UPDATE itens SET estado=?, retorno=?, atualizado_em=? WHERE id=?",
                        (novo, retorno, agora, item_id))
            con.execute("INSERT INTO historico (item_id, de, para, em) VALUES (?, ?, ?, ?)",
                        (item_id, de, novo, agora))
        return self.obter(item_id)

    def historico(self, item_id):
        return [dict(l) for l in self._con.execute(
            "SELECT de, para, em FROM historico WHERE item_id=? ORDER BY id", (item_id,))]

    # --- checkpoints por documento ------------------------------------------

    def registrar_checkpoint(self, item_id, documento, sha256, situacao="coletado"):
        """Grava o checkpoint do documento. Devolve ``True`` se é novo ou mudou.

        ``False`` quer dizer mesmo hash e mesma situação: nada a refazer.
        """
        with self._transacao() as con:
            atual = con.execute(
                "SELECT sha256, situacao FROM checkpoints WHERE item_id=? AND documento=?",
                (item_id, documento)).fetchone()
            if atual and atual["sha256"] == sha256 and atual["situacao"] == situacao:
                return False
            con.execute(
                "INSERT INTO checkpoints (item_id, documento, sha256, situacao, atualizado_em) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (item_id, documento) DO UPDATE SET "
                "sha256=excluded.sha256, situacao=excluded.situacao, "
                "atualizado_em=excluded.atualizado_em",
                (item_id, documento, sha256, situacao, _agora()))
            return True

    def checkpoint(self, item_id, documento):
        linha = self._con.execute(
            "SELECT * FROM checkpoints WHERE item_id=? AND documento=?",
            (item_id, documento)).fetchone()
        return dict(linha) if linha else None

    def checkpoints(self, item_id):
        return [dict(l) for l in self._con.execute(
            "SELECT * FROM checkpoints WHERE item_id=? ORDER BY documento", (item_id,))]


class _Transacao:
    """``BEGIN IMMEDIATE`` ... ``COMMIT``, ou ``ROLLBACK`` se houver exceção."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, tipo, *_):
        self.con.execute("ROLLBACK" if tipo else "COMMIT")
        return False
