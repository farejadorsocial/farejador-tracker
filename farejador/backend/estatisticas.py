"""Cálculo das estatísticas do painel (visão geral, comparação, retorno, campanhas, robôs)."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from . import paginas
from .db import conexao, json_carregar, linha_evento


# ------------------------------------------------------------------ períodos
def _local(d: date, fim: bool = False) -> datetime:
    t = datetime(d.year, d.month, d.day, 23, 59, 59) if fim else datetime(d.year, d.month, d.day)
    return t.astimezone()


def resolver_periodo(dias: Optional[int], de: Optional[str], ate: Optional[str],
                     cmp_de: Optional[str] = None, cmp_ate: Optional[str] = None) -> Dict[str, Any]:
    hoje = datetime.now().astimezone().date()
    try:
        d_ate = date.fromisoformat(ate) if ate else hoje
        d_de = date.fromisoformat(de) if de else d_ate - timedelta(days=max(1, min(int(dias or 30), 730)) - 1)
    except ValueError:
        d_ate, d_de = hoje, hoje - timedelta(days=29)
    if d_de > d_ate:
        d_de, d_ate = d_ate, d_de
    n = (d_ate - d_de).days + 1
    try:
        if cmp_de and cmp_ate:
            c_de, c_ate = date.fromisoformat(cmp_de), date.fromisoformat(cmp_ate)
        else:
            c_ate = d_de - timedelta(days=1)
            c_de = c_ate - timedelta(days=n - 1)
    except ValueError:
        c_ate = d_de - timedelta(days=1)
        c_de = c_ate - timedelta(days=n - 1)
    return {
        "de": d_de, "ate": d_ate, "dias": n, "cmp_de": c_de, "cmp_ate": c_ate,
        "ini": _local(d_de).timestamp(), "fim": _local(d_ate, True).timestamp(),
        "cmp_ini": _local(c_de).timestamp(), "cmp_fim": _local(c_ate, True).timestamp(),
    }


def carregar(pagina_id: int, ini: float, fim: float, incluir_robos: bool = False, tipos: Optional[Tuple[str, ...]] = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM eventos WHERE pagina_id = ? AND ts_epoch BETWEEN ? AND ?"
    params: List[Any] = [pagina_id, ini, fim]
    if not incluir_robos:
        sql += " AND robo = 0"
    if tipos:
        sql += " AND tipo IN ({})".format(",".join("?" * len(tipos)))
        params += list(tipos)
    with conexao() as con:
        return [linha_evento(l) for l in con.execute(sql + " ORDER BY ts_epoch", params)]


# ------------------------------------------------------------------ visão geral
def _kpis(evs: List[Dict[str, Any]]) -> Dict[str, Any]:
    pv = [e for e in evs if e["tipo"] == "pageview"]
    ck = [e for e in evs if e["tipo"] == "clique"]
    sess = {e["sessao"] for e in pv if e["sessao"]}
    sess_click = {e["sessao"] for e in ck if e["sessao"] in sess}
    dur: Dict[str, int] = defaultdict(int)
    for e in evs:
        if e["tipo"] == "saida" and e["sessao"]:
            dur[e["sessao"]] = max(dur[e["sessao"]], int(e.get("duracao_ms") or 0))
    cons = [e for e in evs if e["tipo"] == "consentimento"]
    aceitos = sum(1 for e in cons if (e.get("dados") or {}).get("escolha") == "aceito")
    return {
        "visualizacoes": len(pv), "sessoes": len(sess), "cliques": len(ck),
        "visitantes_identificados": len({e["visitante"] for e in evs if e["visitante"]}),
        "ctr": round(100 * len(sess_click) / len(sess), 1) if sess else 0,
        "tempo_medio_s": round(sum(dur.values()) / len(dur) / 1000, 1) if dur else 0,
        "consentimento_taxa": round(100 * aceitos / len(cons), 1) if cons else 0,
        "compartilhamentos": sum(1 for e in evs if e["tipo"] == "compartilhar"),
    }


def _serie(evs: List[Dict[str, Any]], d_de: date, n: int) -> List[Dict[str, Any]]:
    dias = [(d_de + timedelta(days=i)).isoformat() for i in range(n)]
    s = {d: {"dia": d, "visualizacoes": 0, "cliques": 0, "sessoes": set()} for d in dias}
    for e in evs:
        if e["tipo"] not in ("pageview", "clique"):
            continue
        d = datetime.fromtimestamp(e["ts_epoch"]).astimezone().date().isoformat()
        if d in s:
            s[d]["visualizacoes" if e["tipo"] == "pageview" else "cliques"] += 1
            if e["tipo"] == "pageview" and e["sessao"]:
                s[d]["sessoes"].add(e["sessao"])
    return [{"dia": v["dia"], "visualizacoes": v["visualizacoes"], "cliques": v["cliques"], "sessoes": len(v["sessoes"])} for v in s.values()]


def _top(c: Counter, n: int = 8) -> List[Dict[str, Any]]:
    itens = c.most_common()
    saida = [{"nome": k, "valor": v} for k, v in itens[:n]]
    resto = sum(v for _, v in itens[n:])
    if resto:
        saida.append({"nome": "Outros", "valor": resto})
    return saida


def _canal_sessao(evs: List[Dict[str, Any]]) -> Dict[str, str]:
    return {e["sessao"]: (e["canal"] or "Direto") for e in evs if e["tipo"] == "pageview" and e["sessao"]}


def _por_link(evs: List[Dict[str, Any]], links_cfg: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    total_sess = len({e["sessao"] for e in evs if e["tipo"] == "pageview" and e["sessao"]})
    por: Dict[str, Dict[str, Any]] = {}
    for l in links_cfg:
        por[l["id"]] = {"id": l["id"], "titulo": l.get("titulo"), "tipo": l.get("tipo"), "url": l.get("url"), "ativo": l.get("ativo"),
                        "cliques": 0, "_s": set(), "icone": 0, "botao": 0}
    for e in evs:
        if e["tipo"] != "clique":
            continue
        it = por.setdefault(e["link_id"], {"id": e["link_id"], "titulo": e.get("link_titulo"), "tipo": e.get("link_tipo"),
                                           "url": e.get("destino"), "ativo": False, "cliques": 0, "_s": set(), "icone": 0, "botao": 0})
        it["cliques"] += 1
        if e["sessao"]:
            it["_s"].add(e["sessao"])
        if e.get("area") in ("icone", "botao"):
            it[e["area"]] += 1
    for v in por.values():
        v["unicos"] = len(v.pop("_s"))
        v["ctr"] = round(100 * v["unicos"] / total_sess, 1) if total_sess else 0
    return por


def visao_geral(pagina_id: int, periodo: Dict[str, Any], incluir_robos: bool = False) -> Dict[str, Any]:
    pagina = paginas.obter(pagina_id)
    links_cfg = pagina["config"]["links"] if pagina else []
    evs = carregar(pagina_id, periodo["ini"], periodo["fim"], incluir_robos)
    ant = carregar(pagina_id, periodo["cmp_ini"], periodo["cmp_fim"], incluir_robos)
    pv = [e for e in evs if e["tipo"] == "pageview"]
    ck = [e for e in evs if e["tipo"] == "clique"]
    canal_s = _canal_sessao(evs)

    links_atual = _por_link(evs, links_cfg)
    links_ant = _por_link(ant, links_cfg)
    links = []
    for lid, v in links_atual.items():
        a = links_ant.get(lid) or {}
        v["cliques_anterior"] = a.get("cliques", 0)
        v["ctr_anterior"] = a.get("ctr", 0)
        links.append(v)
    links.sort(key=lambda x: x["cliques"], reverse=True)

    canais = Counter(canal_s.values())
    canais_ant = Counter(_canal_sessao(ant).values())
    comparacao_canais = [{"nome": k, "atual": canais.get(k, 0), "anterior": canais_ant.get(k, 0)}
                         for k in sorted(set(canais) | set(canais_ant), key=lambda k: -(canais.get(k, 0) + canais_ant.get(k, 0) / 1000))][:12]

    fluxo = Counter()
    for e in ck:
        fluxo[(canal_s.get(e["sessao"]) or e["canal"] or "Direto", e.get("link_titulo") or e["link_id"])] += 1

    calor = [[0] * 24 for _ in range(7)]
    for e in pv:
        dt = datetime.fromtimestamp(e["ts_epoch"]).astimezone()
        calor[dt.weekday()][dt.hour] += 1

    cliques_sessao = Counter(e["sessao"] for e in ck if e["sessao"])
    return {
        "periodo": {"de": periodo["de"].isoformat(), "ate": periodo["ate"].isoformat(), "dias": periodo["dias"],
                    "cmp_de": periodo["cmp_de"].isoformat(), "cmp_ate": periodo["cmp_ate"].isoformat()},
        "kpis": _kpis(evs), "kpis_anterior": _kpis(ant),
        "serie": _serie(evs, periodo["de"], periodo["dias"]),
        "serie_anterior": _serie(ant, periodo["cmp_de"], (periodo["cmp_ate"] - periodo["cmp_de"]).days + 1),
        "links": links,
        "comparacao_canais": comparacao_canais,
        "fluxo": [{"origem": o, "destino": d, "valor": v} for (o, d), v in fluxo.most_common(40)],
        "canais": _top(canais),
        "referers": _top(Counter(e.get("origem", {}).get("dominio") for e in pv if (e.get("origem") or {}).get("dominio")), 10),
        "campanhas_utm": _top(Counter((e.get("utm") or {}).get("utm_campaign") for e in pv if (e.get("utm") or {}).get("utm_campaign")), 10),
        "dispositivos": _top(Counter((e.get("ua_info") or {}).get("dispositivo") for e in pv)),
        "navegadores": _top(Counter((e.get("ua_info") or {}).get("navegador") for e in pv)),
        "sistemas": _top(Counter((e.get("ua_info") or {}).get("sistema") for e in pv)),
        "idiomas": _top(Counter(e.get("idioma") for e in pv if e.get("idioma")), 6),
        "fusos": _top(Counter(e.get("timezone") for e in pv if e.get("timezone")), 6),
        "telas": _top(Counter(e.get("tela") for e in pv if e.get("tela")), 6),
        "calor": calor,
        "funil": [
            {"etapa": "Abriram a página", "valor": len({e["sessao"] for e in pv if e["sessao"]})},
            {"etapa": "Clicaram em um link", "valor": len(cliques_sessao)},
            {"etapa": "Clicaram em 2 ou mais", "valor": sum(1 for v in cliques_sessao.values() if v >= 2)},
        ],
        "robos": resumo_robos(pagina_id, periodo["ini"], periodo["fim"]),
    }


def resumo_robos(pagina_id: int, ini: float, fim: float) -> Dict[str, Any]:
    with conexao() as con:
        linhas = con.execute("SELECT tipo, dados FROM eventos WHERE pagina_id = ? AND robo = 1 AND ts_epoch BETWEEN ? AND ?",
                             (pagina_id, ini, fim)).fetchall()
    nomes = Counter()
    tipos = Counter()
    for l in linhas:
        d = json_carregar(l["dados"])
        nomes[d.get("robo_nome") or (d.get("ua_info") or {}).get("navegador") or "Robô"] += 1
        tipos[l["tipo"]] += 1
    return {"total": len(linhas), "por_robo": _top(nomes, 10), "previas": tipos.get("previa", 0),
            "visitas": tipos.get("pageview", 0), "cliques": tipos.get("clique", 0)}


# ------------------------------------------------------------------ retorno de visitantes
def _mapa_sessao_visitante(con) -> Dict[str, str]:
    m = {l["sessao"]: l["visitante"] for l in con.execute("SELECT sessao, visitante FROM visitante_sessoes")}
    for l in con.execute("SELECT DISTINCT sessao, visitante FROM eventos WHERE visitante IS NOT NULL AND sessao IS NOT NULL"):
        m.setdefault(l["sessao"], l["visitante"])
    return m


def retorno(pagina_id: int, periodo: Dict[str, Any]) -> Dict[str, Any]:
    with conexao() as con:
        s2v = _mapa_sessao_visitante(con)
        linhas = con.execute("SELECT sessao, MIN(ts_epoch) AS inicio, canal FROM eventos WHERE pagina_id = ? AND tipo = 'pageview' "
                             "AND robo = 0 AND sessao IS NOT NULL AND ts_epoch <= ? GROUP BY sessao", (pagina_id, periodo["fim"])).fetchall()
    ini, fim = periodo["ini"], periodo["fim"]
    por_vis: Dict[str, List[Tuple[float, str]]] = defaultdict(list)
    anonimas = identificadas = 0
    for l in linhas:
        if not (ini <= l["inicio"] <= fim):
            v = s2v.get(l["sessao"])
            if v:
                por_vis[v].append((l["inicio"], l["canal"] or "Direto"))
            continue
        v = s2v.get(l["sessao"])
        if v:
            por_vis[v].append((l["inicio"], l["canal"] or "Direto"))
            identificadas += 1
        else:
            anonimas += 1
    for v in por_vis.values():
        v.sort()

    ativos = {v: s for v, s in por_vis.items() if any(ini <= t <= fim for t, _ in s)}
    novos = {v for v, s in ativos.items() if s[0][0] >= ini}
    recorrentes = set(ativos) - novos
    voltaram_novos = {v for v in novos if len(ativos[v]) >= 2}

    faixas = Counter()
    for s in ativos.values():
        if len(s) >= 2:
            gap = (s[1][0] - s[0][0]) / 86400
            faixas["Menos de 1 dia" if gap < 1 else "1 a 7 dias" if gap <= 7 else "8 a 30 dias" if gap <= 30 else "Mais de 30 dias"] += 1
    ordem = ["Menos de 1 dia", "1 a 7 dias", "8 a 30 dias", "Mais de 30 dias"]

    # Série diária: visitante conta como "novo" no dia da primeira visita, "recorrente" nos outros dias.
    dias = [(periodo["de"] + timedelta(days=i)).isoformat() for i in range(periodo["dias"])]
    serie = {d: {"dia": d, "novos": set(), "recorrentes": set()} for d in dias}
    for v, s in ativos.items():
        primeiro = datetime.fromtimestamp(s[0][0]).astimezone().date().isoformat()
        for t, _ in s:
            d = datetime.fromtimestamp(t).astimezone().date().isoformat()
            if d in serie:
                serie[d]["novos" if d == primeiro else "recorrentes"].add(v)

    canais: Dict[str, Dict[str, int]] = defaultdict(lambda: {"visitantes": 0, "voltaram": 0})
    for v, s in ativos.items():
        c = canais[s[0][1]]
        c["visitantes"] += 1
        c["voltaram"] += 1 if len(s) >= 2 else 0
    por_canal = sorted([{"canal": k, **v, "taxa": round(100 * v["voltaram"] / v["visitantes"], 1)} for k, v in canais.items()],
                       key=lambda x: -x["visitantes"])[:10]

    # Coortes semanais (8 semanas até o fim do período)
    fim_d = periodo["ate"]
    seg_fim = fim_d - timedelta(days=fim_d.weekday())
    coortes = []
    for w in range(7, -1, -1):
        seg = seg_fim - timedelta(weeks=w)
        a, b = _local(seg).timestamp(), _local(seg + timedelta(days=6), True).timestamp()
        grupo = [s for s in por_vis.values() if a <= s[0][0] <= b]
        semanas = []
        for k in range(1, 5):
            ka, kb = a + k * 7 * 86400, b + k * 7 * 86400
            if ka > fim:
                semanas.append(None)
                continue
            semanas.append(round(100 * sum(1 for s in grupo if any(ka <= t <= kb for t, _ in s)) / len(grupo), 1) if grupo else 0)
        coortes.append({"semana": seg.isoformat(), "visitantes": len(grupo), "retorno": semanas})

    top = sorted(ativos.items(), key=lambda kv: -len(kv[1]))[:12]
    return {
        "visitantes_ativos": len(ativos), "novos": len(novos), "recorrentes": len(recorrentes),
        "taxa_retorno_novos": round(100 * len(voltaram_novos) / len(novos), 1) if novos else 0,
        "sessoes_por_visitante": round(sum(len(s) for s in ativos.values()) / len(ativos), 2) if ativos else 0,
        "cobertura": {"identificadas": identificadas, "anonimas": anonimas,
                      "pct": round(100 * identificadas / (identificadas + anonimas), 1) if (identificadas + anonimas) else 0},
        "intervalo_retorno": [{"nome": k, "valor": faixas.get(k, 0)} for k in ordem],
        "serie": [{"dia": v["dia"], "novos": len(v["novos"]), "recorrentes": len(v["recorrentes"])} for v in serie.values()],
        "por_canal": por_canal,
        "coortes": coortes,
        "top_visitantes": [{"visitante": v, "sessoes": len(s), "primeira": datetime.fromtimestamp(s[0][0]).astimezone().isoformat(timespec="minutes"),
                            "ultima": datetime.fromtimestamp(s[-1][0]).astimezone().isoformat(timespec="minutes"), "canal": s[0][1]} for v, s in top],
    }


# ------------------------------------------------------------------ campanhas
def campanhas(pagina_id: int, periodo: Dict[str, Any]) -> List[Dict[str, Any]]:
    with conexao() as con:
        lista = [dict(l) for l in con.execute("SELECT * FROM campanhas WHERE pagina_id = ? ORDER BY id DESC", (pagina_id,))]
    evs = carregar(pagina_id, periodo["ini"], periodo["fim"], tipos=("pageview", "clique"))
    ant = carregar(pagina_id, periodo["cmp_ini"], periodo["cmp_fim"], tipos=("pageview", "clique"))

    def medir(eventos):
        m: Dict[int, Dict[str, Any]] = defaultdict(lambda: {"visitas": 0, "sessoes": set(), "cliques": 0, "s_click": set(), "ultimo": None, "links": Counter()})
        for e in eventos:
            cid = e["campanha_id"]
            if not cid:
                continue
            x = m[cid]
            if e["tipo"] == "pageview":
                x["visitas"] += 1
                if e["sessao"]:
                    x["sessoes"].add(e["sessao"])
                x["ultimo"] = e["ts"]
            else:
                x["cliques"] += 1
                if e["sessao"]:
                    x["s_click"].add(e["sessao"])
                x["links"][e.get("link_titulo") or e["link_id"]] += 1
        return m

    atual, anterior = medir(evs), medir(ant)
    for c in lista:
        a, p = atual.get(c["id"]), anterior.get(c["id"])
        ses = len(a["sessoes"]) if a else 0
        c.update({
            "ativo": bool(c["ativo"]), "visitas": a["visitas"] if a else 0, "sessoes": ses, "cliques": a["cliques"] if a else 0,
            "ctr": round(100 * len(a["s_click"]) / ses, 1) if a and ses else 0, "ultimo": a["ultimo"] if a else None,
            "links": [{"nome": k, "valor": v} for k, v in a["links"].most_common(5)] if a else [],
            "visitas_anterior": p["visitas"] if p else 0, "cliques_anterior": p["cliques"] if p else 0,
        })
    return lista
