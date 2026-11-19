"""Importa automaticamente os dados da versão anterior (arquivos JSON) para o banco SQLite.

Roda uma única vez. Os arquivos antigos não são apagados — depois de conferir o painel,
você pode removê-los (data/config.json, data/eventos.jsonl, data/visitors/*.json, data/admin.json).
"""
import json
from datetime import datetime
from typing import Any, Dict

from . import paginas
from .analise import detectar_robo
from .config import LEGADO_ADMIN, LEGADO_CONFIG, LEGADO_EVENTOS, LEGADO_VISITANTES
from .db import agora_iso, ajuste, conexao, definir_ajuste, json_texto, transacao


def _ler(caminho) -> Any:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _epoch(ts: str) -> float:
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (TypeError, ValueError):
        return 0.0


def executar() -> Dict[str, int]:
    resumo = {"paginas": 0, "eventos": 0, "visitantes": 0, "usuarios": 0}
    if ajuste("migracao_v3_concluida"):
        _garantir_pagina()
        return resumo

    # 1) Página principal a partir do config.json antigo
    with conexao() as con:
        tem_pagina = con.execute("SELECT COUNT(*) FROM paginas").fetchone()[0] > 0
    if not tem_pagina:
        antigo = _ler(LEGADO_CONFIG) if LEGADO_CONFIG.exists() else None
        if isinstance(antigo, dict):
            nome = (antigo.get("perfil") or {}).get("nome") or "Página principal"
            paginas.criar(nome, "principal", antigo, principal=True)
            resumo["paginas"] = 1
    pagina = _garantir_pagina()

    # 2) Eventos (eventos.jsonl)
    if LEGADO_EVENTOS.exists():
        lote = []
        with LEGADO_EVENTOS.open("r", encoding="utf-8") as f:
            for linha in f:
                try:
                    ev = json.loads(linha)
                except ValueError:
                    continue
                if not isinstance(ev, dict) or not ev.get("tipo") or not ev.get("ts"):
                    continue
                ts = ev.pop("ts")
                ua = ev.get("ua") or ""
                robo = bool(ev.get("tipo") == "pageview" and ua and detectar_robo(ua))
                cols = {k: ev.pop(k, None) for k in ("tipo", "sessao", "visitante", "link_id")}
                canal = (ev.get("origem") or {}).get("canal")
                ev.pop("pagina", None)
                lote.append((ts, _epoch(ts), cols["tipo"], pagina["id"], cols["sessao"], cols["visitante"], 1 if robo else 0,
                             canal, cols["link_id"], None, json_texto(ev)))
        if lote:
            with transacao() as con:
                con.executemany("INSERT INTO eventos (ts, ts_epoch, tipo, pagina_id, sessao, visitante, robo, canal, link_id, campanha_id, dados) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", lote)
            resumo["eventos"] = len(lote)

    # 3) Visitantes (data/visitors/*.json)
    if LEGADO_VISITANTES.exists():
        for arq in LEGADO_VISITANTES.glob("*.json"):
            reg = _ler(arq)
            if not isinstance(reg, dict) or not reg.get("visitante_id"):
                continue
            vid = reg["visitante_id"]
            ipinfo = reg.pop("ipinfo_admin", None) or {}
            sessoes = reg.pop("sessoes", None) or []
            ip = (reg.get("conexao_servidor") or {}).get("ip_observado")
            atualizado = reg.get("atualizado_em") or agora_iso()
            with transacao() as con:
                con.execute("INSERT OR IGNORE INTO visitantes (id, criado_em, atualizado_em, atualizado_epoch, quantidade_coletas, ip, registro, ipinfo) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (vid, reg.get("criado_em") or atualizado, atualizado, _epoch(atualizado), int(reg.get("quantidade_coletas") or 1),
                             ip, json_texto(reg), json_texto(ipinfo)))
                for s in sessoes:
                    con.execute("INSERT OR IGNORE INTO visitante_sessoes (visitante, sessao) VALUES (?, ?)", (vid, s))
                for h in reg.get("historico_acessos") or []:
                    if isinstance(h, dict) and h.get("sessao"):
                        con.execute("INSERT OR IGNORE INTO visitante_sessoes (visitante, sessao) VALUES (?, ?)", (vid, h["sessao"]))
            resumo["visitantes"] += 1

    # 4) Senha do painel (admin.json) → usuário "admin"
    adm = _ler(LEGADO_ADMIN) if LEGADO_ADMIN.exists() else None
    if isinstance(adm, dict) and adm.get("hash") and adm.get("sal"):
        with conexao() as con:
            existe = con.execute("SELECT 1 FROM usuarios WHERE usuario = 'admin'").fetchone()
        if not existe:
            with transacao() as con:
                con.execute("INSERT INTO usuarios (usuario, hash, sal, iteracoes, criado_em) VALUES ('admin', ?, ?, 200000, ?)",
                            (adm["hash"], adm["sal"], agora_iso()))
            resumo["usuarios"] = 1

    definir_ajuste("migracao_v3_concluida", {"em": agora_iso(), **resumo})
    return resumo


def _garantir_pagina() -> Dict[str, Any]:
    p = paginas.obter()
    if p:
        return p
    return paginas.criar("Página principal", "principal", principal=True)
