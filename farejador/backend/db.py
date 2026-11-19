"""Banco de dados SQLite (arquivo data/farejador.db). Não precisa instalar nada."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional

from .config import BANCO

_TRAVA_ESCRITA = threading.Lock()

ESQUEMA = """
CREATE TABLE IF NOT EXISTS paginas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    nome TEXT NOT NULL,
    principal INTEGER NOT NULL DEFAULT 0,
    config TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    ts_epoch REAL NOT NULL,
    tipo TEXT NOT NULL,
    pagina_id INTEGER,
    sessao TEXT,
    visitante TEXT,
    robo INTEGER NOT NULL DEFAULT 0,
    canal TEXT,
    link_id TEXT,
    campanha_id INTEGER,
    dados TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_eventos_pagina_ts ON eventos (pagina_id, ts_epoch);
CREATE INDEX IF NOT EXISTS ix_eventos_sessao ON eventos (sessao);
CREATE INDEX IF NOT EXISTS ix_eventos_visitante ON eventos (visitante);
CREATE INDEX IF NOT EXISTS ix_eventos_campanha ON eventos (campanha_id);

CREATE TABLE IF NOT EXISTS visitantes (
    id TEXT PRIMARY KEY,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    atualizado_epoch REAL NOT NULL,
    quantidade_coletas INTEGER NOT NULL DEFAULT 0,
    ip TEXT,
    registro TEXT NOT NULL,
    ipinfo TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS visitante_sessoes (
    visitante TEXT NOT NULL,
    sessao TEXT NOT NULL,
    PRIMARY KEY (visitante, sessao)
);
CREATE INDEX IF NOT EXISTS ix_vs_sessao ON visitante_sessoes (sessao);

CREATE TABLE IF NOT EXISTS campanhas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    pagina_id INTEGER NOT NULL,
    nome TEXT NOT NULL,
    origem TEXT,
    utm_source TEXT,
    utm_medium TEXT,
    utm_campaign TEXT,
    utm_content TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT NOT NULL UNIQUE COLLATE NOCASE,
    hash TEXT NOT NULL,
    sal TEXT NOT NULL,
    iteracoes INTEGER NOT NULL,
    criado_em TEXT NOT NULL,
    ultimo_login TEXT,
    falhas INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessoes_admin (
    token_hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    criado_em TEXT NOT NULL,
    expira_epoch REAL NOT NULL,
    ultimo_uso TEXT,
    ip TEXT,
    ua TEXT
);

CREATE TABLE IF NOT EXISTS tentativas_login (
    ip TEXT NOT NULL,
    ts_epoch REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS ajustes (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
"""


def agora_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def agora_epoch() -> float:
    return time.time()


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(str(BANCO), timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextmanager
def conexao() -> Iterator[sqlite3.Connection]:
    """Conexão de leitura (ou escrita simples com autocommit)."""
    con = _conectar()
    try:
        yield con
    finally:
        con.close()


@contextmanager
def transacao() -> Iterator[sqlite3.Connection]:
    """Escrita em bloco: tudo ou nada."""
    with _TRAVA_ESCRITA:
        con = _conectar()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()


def iniciar_banco() -> None:
    with _TRAVA_ESCRITA:
        con = _conectar()
        try:
            con.executescript(ESQUEMA)
        finally:
            con.close()


def json_carregar(texto: Optional[str], padrao: Any = None) -> Any:
    if not texto:
        return {} if padrao is None else padrao
    try:
        return json.loads(texto)
    except (TypeError, ValueError):
        return {} if padrao is None else padrao


def json_texto(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, separators=(",", ":"))


def ajuste(chave: str, padrao: Any = None) -> Any:
    with conexao() as con:
        linha = con.execute("SELECT valor FROM ajustes WHERE chave = ?", (chave,)).fetchone()
    return json_carregar(linha["valor"], padrao) if linha else padrao


def definir_ajuste(chave: str, valor: Any) -> None:
    with transacao() as con:
        con.execute("INSERT INTO ajustes (chave, valor) VALUES (?, ?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                    (chave, json_texto(valor)))


def gravar_evento(evento: Dict[str, Any]) -> None:
    """Grava um evento. Campos conhecidos viram colunas; o resto vai em `dados`."""
    ev = dict(evento)
    agora = datetime.now(timezone.utc).astimezone()
    ts = ev.pop("ts", None) or agora.isoformat(timespec="seconds")
    try:
        epoch = datetime.fromisoformat(ts).timestamp()
    except ValueError:
        ts, epoch = agora.isoformat(timespec="seconds"), agora.timestamp()
    colunas = {k: ev.pop(k, None) for k in ("tipo", "pagina_id", "sessao", "visitante", "canal", "link_id", "campanha_id")}
    robo = 1 if ev.pop("robo", False) else 0
    with transacao() as con:
        con.execute(
            "INSERT INTO eventos (ts, ts_epoch, tipo, pagina_id, sessao, visitante, robo, canal, link_id, campanha_id, dados) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, epoch, colunas["tipo"], colunas["pagina_id"], colunas["sessao"], colunas["visitante"], robo,
             colunas["canal"], colunas["link_id"], colunas["campanha_id"], json_texto(ev)),
        )


def linha_evento(linha: sqlite3.Row) -> Dict[str, Any]:
    """Converte uma linha da tabela eventos no formato de dicionário usado pelo painel."""
    ev = json_carregar(linha["dados"])
    ev.update({
        "id": linha["id"], "ts": linha["ts"], "ts_epoch": linha["ts_epoch"], "tipo": linha["tipo"],
        "pagina_id": linha["pagina_id"], "sessao": linha["sessao"], "visitante": linha["visitante"],
        "robo": bool(linha["robo"]), "canal": linha["canal"], "link_id": linha["link_id"], "campanha_id": linha["campanha_id"],
    })
    return ev
