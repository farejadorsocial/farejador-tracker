"""Apaga dados antigos automaticamente (retenção configurável no painel)."""
import threading
import time
from typing import Any, Dict

from .db import agora_iso, ajuste, definir_ajuste, transacao

RETENCAO_PADRAO = {"eventos_dias": 180, "visitantes_dias": 365, "ativa": True}
INTERVALO_S = 6 * 3600


def obter_retencao() -> Dict[str, Any]:
    r = dict(RETENCAO_PADRAO)
    r.update(ajuste("retencao", {}) or {})
    return r


def salvar_retencao(eventos_dias: int, visitantes_dias: int, ativa: bool) -> Dict[str, Any]:
    r = {"eventos_dias": max(0, min(int(eventos_dias), 3650)), "visitantes_dias": max(0, min(int(visitantes_dias), 3650)), "ativa": bool(ativa)}
    definir_ajuste("retencao", r)
    return r


def executar(forcar: bool = False) -> Dict[str, Any]:
    r = obter_retencao()
    agora = time.time()
    resultado = {"eventos": 0, "visitantes": 0, "sessoes_admin": 0, "executado_em": agora_iso()}
    with transacao() as con:
        # Sempre: sessões de login vencidas e tentativas antigas
        resultado["sessoes_admin"] = con.execute("DELETE FROM sessoes_admin WHERE expira_epoch < ?", (agora,)).rowcount
        con.execute("DELETE FROM tentativas_login WHERE ts_epoch < ?", (agora - 86400,))
        if r["ativa"] or forcar:
            if r["eventos_dias"] > 0:
                resultado["eventos"] = con.execute("DELETE FROM eventos WHERE ts_epoch < ?", (agora - r["eventos_dias"] * 86400,)).rowcount
            if r["visitantes_dias"] > 0:
                limite = agora - r["visitantes_dias"] * 86400
                resultado["visitantes"] = con.execute("DELETE FROM visitantes WHERE atualizado_epoch < ?", (limite,)).rowcount
                con.execute("DELETE FROM visitante_sessoes WHERE visitante NOT IN (SELECT id FROM visitantes)")
    definir_ajuste("ultima_limpeza", resultado)
    return resultado


def iniciar_agendador() -> None:
    def laco():
        while True:
            try:
                executar()
            except Exception as erro:  # nunca derrubar o servidor por causa da limpeza
                print("[limpeza] erro:", erro)
            time.sleep(INTERVALO_S)
    threading.Thread(target=laco, name="farejador-limpeza", daemon=True).start()
