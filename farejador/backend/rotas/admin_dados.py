"""Rotas do painel: estatísticas, tráfego, visitantes, IPinfo, exportação e retenção."""
import csv
import io
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import estatisticas as est
from .. import ipinfo, limpeza, paginas
from ..analise import analisar_ua
from ..config import BANCO, VERSAO
from ..db import ajuste, conexao, json_carregar, json_texto, linha_evento, transacao
from ..seguranca import exigir_admin

rota = APIRouter(prefix="/api/admin", dependencies=[Depends(exigir_admin)])
RE_VISITANTE = re.compile(r"[a-f0-9]{32}")


def _pid(pagina: Optional[int]) -> int:
    p = paginas.obter(pagina) if pagina else paginas.obter()
    if not p:
        raise HTTPException(404, "Página não encontrada.")
    return p["id"]


def _periodo(dias, de, ate, cmp_de=None, cmp_ate=None):
    return est.resolver_periodo(dias, de, ate, cmp_de, cmp_ate)


@rota.get("/estatisticas")
def estatisticas(pagina: Optional[int] = None, dias: int = 30, de: Optional[str] = None, ate: Optional[str] = None,
                 cmp_de: Optional[str] = None, cmp_ate: Optional[str] = None, robos: bool = False):
    pid = _pid(pagina)
    dados = est.visao_geral(pid, _periodo(dias, de, ate, cmp_de, cmp_ate), robos)
    dados["mapa"] = _pontos_mapa(pid)
    return dados


@rota.get("/retorno")
def retorno(pagina: Optional[int] = None, dias: int = 30, de: Optional[str] = None, ate: Optional[str] = None):
    return est.retorno(_pid(pagina), _periodo(dias, de, ate))


@rota.get("/campanhas")
def campanhas(pagina: Optional[int] = None, dias: int = 30, de: Optional[str] = None, ate: Optional[str] = None):
    return {"campanhas": est.campanhas(_pid(pagina), _periodo(dias, de, ate))}


@rota.get("/eventos")
def eventos(pagina: Optional[int] = None, limite: int = 150, tipo: Optional[str] = None, robos: bool = False):
    pid = _pid(pagina)
    sql, params = "SELECT * FROM eventos WHERE pagina_id = ?", [pid]
    if tipo == "robo":
        sql += " AND robo = 1"
    else:
        if tipo:
            sql += " AND tipo = ?"
            params.append(tipo)
        if not robos:
            sql += " AND robo = 0"
    with conexao() as con:
        linhas = [linha_evento(l) for l in con.execute(sql + " ORDER BY id DESC LIMIT ?", params + [max(1, min(limite, 1000))])]
    saida = []
    for e in linhas:
        e.pop("ua", None)
        saida.append(e)
    return {"eventos": saida}


# ------------------------------------------------------------------ visitantes
def _resumo(l) -> dict:
    reg = json_carregar(l["registro"])
    nav = reg.get("dados_navegador") or {}
    con = reg.get("conexao_servidor") or {}
    n, t = nav.get("navegador") or {}, nav.get("tela") or {}
    ua = (con.get("cabecalhos_http") or {}).get("user_agent") or n.get("user_agent")
    ipi = json_carregar(l["ipinfo"]).get(l["ip"] or "") or None
    return {
        "visitante_id": l["id"], "criado_em": l["criado_em"], "atualizado_em": l["atualizado_em"], "quantidade_coletas": l["quantidade_coletas"],
        "ip": l["ip"], "tipo_ip": con.get("tipo_ip"), "ips": con.get("ips_publicos_detectados") or {}, "ua_info": analisar_ua(ua),
        "idioma": n.get("idioma"), "timezone": n.get("timezone"),
        "tela": "{}×{}".format(t.get("largura"), t.get("altura")) if t.get("largura") else None,
        "gps": bool(nav.get("geolocalizacao")),
        "local": "{}, {}".format(ipi.get("cidade"), ipi.get("codigo_pais")) if ipi and ipi.get("cidade") else None,
    }


@rota.get("/visitantes")
def visitantes(pagina: Optional[int] = None):
    pid = _pid(pagina)
    with conexao() as con:
        s2v = est._mapa_sessao_visitante(con)
        stats = {}
        for l in con.execute("SELECT sessao, tipo, canal, ts_epoch AS t FROM eventos WHERE pagina_id = ? AND robo = 0 AND sessao IS NOT NULL "
                             "AND tipo IN ('pageview','clique')", (pid,)):
            v = s2v.get(l["sessao"])
            if not v:
                continue
            x = stats.setdefault(v, {"sessoes": set(), "cliques": 0, "canal": None, "t": None})
            if l["tipo"] == "pageview":
                x["sessoes"].add(l["sessao"])
                if x["t"] is None or l["t"] < x["t"]:
                    x["t"], x["canal"] = l["t"], l["canal"]
            else:
                x["cliques"] += 1
        linhas = con.execute("SELECT * FROM visitantes ORDER BY atualizado_epoch DESC").fetchall()
    lista = []
    for l in linhas:
        x = stats.get(l["id"])
        if not x:
            continue  # visitante sem visitas nesta página
        r = _resumo(l)
        r.update(sessoes=len(x["sessoes"]), cliques=x["cliques"], origem_canal=x["canal"])
        lista.append(r)
    return {"visitantes": lista}


@rota.get("/visitantes/{vid}")
def visitante(vid: str):
    if not RE_VISITANTE.fullmatch(vid):
        raise HTTPException(400, "ID inválido.")
    with conexao() as con:
        l = con.execute("SELECT * FROM visitantes WHERE id = ?", (vid,)).fetchone()
        if not l:
            raise HTTPException(404, "Visitante não encontrado.")
        sess = [r["sessao"] for r in con.execute("SELECT sessao FROM visitante_sessoes WHERE visitante = ?", (vid,))]
        q = "SELECT * FROM eventos WHERE visitante = ?" + (" OR sessao IN ({})".format(",".join("?" * len(sess))) if sess else "")
        evs = [linha_evento(e) for e in con.execute(q + " ORDER BY ts_epoch DESC LIMIT 300", [vid] + sess)]
    reg = json_carregar(l["registro"])
    reg["ipinfo_admin"] = json_carregar(l["ipinfo"])
    nomes = {p["id"]: p["nome"] for p in paginas.listar()}
    for e in evs:
        e.pop("ua", None)
        e["pagina_nome"] = nomes.get(e["pagina_id"])
    return {"registro": reg, "resumo": _resumo(l), "eventos": list(reversed(evs))}


@rota.delete("/visitantes/{vid}")
def excluir_visitante(vid: str):
    if not RE_VISITANTE.fullmatch(vid):
        raise HTTPException(400, "ID inválido.")
    with transacao() as con:
        con.execute("DELETE FROM visitantes WHERE id = ?", (vid,))
        con.execute("DELETE FROM visitante_sessoes WHERE visitante = ?", (vid,))
        con.execute("UPDATE eventos SET visitante = NULL WHERE visitante = ?", (vid,))
    return {"ok": True}


@rota.post("/ipinfo/{ip}")
def consultar_ipinfo(ip: str, visitante: Optional[str] = None):
    """Única rota que consulta o IPinfo — acionada pelo botão no painel."""
    r = ipinfo.consultar(ip)
    if visitante and RE_VISITANTE.fullmatch(visitante) and r.get("consultado"):
        with transacao() as con:
            l = con.execute("SELECT ipinfo FROM visitantes WHERE id = ?", (visitante,)).fetchone()
            if l:
                atual = json_carregar(l["ipinfo"])
                atual[r["ip"]] = r
                con.execute("UPDATE visitantes SET ipinfo = ? WHERE id = ?", (json_texto(atual), visitante))
    return r


def _pontos_mapa(pid: int) -> list:
    vis = {v["visitante_id"] for v in visitantes(pid)["visitantes"]}
    pontos = []
    with conexao() as con:
        linhas = con.execute("SELECT id, registro, ipinfo FROM visitantes").fetchall()
    for l in linhas:
        if l["id"] not in vis:
            continue
        for ip, inf in json_carregar(l["ipinfo"]).items():
            if inf.get("latitude") is not None:
                pontos.append({"visitante": l["id"], "ip": ip, "lat": inf["latitude"], "lon": inf["longitude"], "cidade": inf.get("cidade"),
                               "regiao": inf.get("regiao"), "pais": inf.get("pais"), "org": inf.get("organizacao"), "tipo": "ip"})
        gps = (json_carregar(l["registro"]).get("dados_navegador") or {}).get("geolocalizacao")
        if gps and gps.get("latitude") is not None:
            pontos.append({"visitante": l["id"], "lat": gps["latitude"], "lon": gps["longitude"], "precisao": gps.get("precisao_metros"), "tipo": "gps"})
    return pontos


# ------------------------------------------------------------------ exportação
@rota.get("/exportar/eventos.csv")
def exportar_csv(pagina: Optional[int] = None):
    pid = _pid(pagina)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["data_hora", "tipo", "robo", "sessao", "visitante", "canal", "referer", "utm_source", "utm_campaign", "campanha_id",
                "link", "destino", "dispositivo", "navegador", "sistema", "duracao_ms"])
    with conexao() as con:
        for l in con.execute("SELECT * FROM eventos WHERE pagina_id = ? ORDER BY ts_epoch", (pid,)):
            e = linha_evento(l)
            u, ua = e.get("utm") or {}, e.get("ua_info") or {}
            w.writerow([e["ts"], e["tipo"], int(e["robo"]), e["sessao"], e["visitante"], e["canal"], e.get("referer"), u.get("utm_source"),
                        u.get("utm_campaign"), e["campanha_id"], e.get("link_titulo"), e.get("destino"), ua.get("dispositivo"),
                        ua.get("navegador"), ua.get("sistema"), e.get("duracao_ms")])
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=farejador_eventos.csv"})


# ------------------------------------------------------------------ retenção / sistema
class PayloadRetencao(BaseModel):
    eventos_dias: int
    visitantes_dias: int
    ativa: bool = True


@rota.get("/retencao")
def obter_retencao():
    with conexao() as con:
        contagem = {"eventos": con.execute("SELECT COUNT(*) FROM eventos").fetchone()[0],
                    "visitantes": con.execute("SELECT COUNT(*) FROM visitantes").fetchone()[0],
                    "mais_antigo": con.execute("SELECT MIN(ts) FROM eventos").fetchone()[0]}
    return {"retencao": limpeza.obter_retencao(), "ultima_limpeza": ajuste("ultima_limpeza"), "contagem": contagem,
            "banco_mb": round(BANCO.stat().st_size / 1048576, 2) if BANCO.exists() else 0, "versao": VERSAO,
            "migracao": ajuste("migracao_v3_concluida")}


@rota.put("/retencao")
def salvar_retencao(p: PayloadRetencao):
    return {"retencao": limpeza.salvar_retencao(p.eventos_dias, p.visitantes_dias, p.ativa)}


@rota.post("/retencao/executar")
def executar_limpeza():
    return limpeza.executar(forcar=True)
