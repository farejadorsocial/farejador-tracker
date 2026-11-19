"""Rotas públicas: página de links, eventos de tráfego, redirecionamento de cliques e campanhas."""
import html
import ipaddress
import json
import re
import secrets
from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from .. import paginas
from ..analise import analisar_ua, classificar_origem, detectar_robo
from ..config import CONFIAR_PROXY, CONFIG_PERMISSOES, FRONTEND, VERSAO
from ..db import agora_epoch, agora_iso, conexao, gravar_evento, json_carregar, json_texto, transacao
from ..ipinfo import ip_publico

rota = APIRouter()
RE_SESSAO = re.compile(r"[a-zA-Z0-9_-]{8,64}")
RE_VISITANTE = re.compile(r"[a-f0-9]{32}")
COOKIE_VISITANTE = "farejador_estudo_id"
TIPOS_EVENTO = {"pageview", "saida", "consentimento", "compartilhar", "localizacao"}


def visitante_do_cookie(request: Request) -> Optional[str]:
    vid = request.cookies.get(COOKIE_VISITANTE)
    return vid if vid and RE_VISITANTE.fullmatch(vid) else None


def obter_ip_cliente(request: Request):
    """Por padrão confia apenas no IP da conexão; proxy só se explicitamente configurado."""
    ip_conexao = request.client.host if request.client else None
    if not CONFIAR_PROXY:
        return ip_conexao, "conexao_direta"
    cf_ip = request.headers.get("cf-connecting-ip")
    fwd = request.headers.get("x-forwarded-for")
    candidato = cf_ip.strip() if cf_ip else (fwd.split(",")[0].strip() if fwd else None)
    if candidato:
        try:
            return str(ipaddress.ip_address(candidato)), "proxy_configurado"
        except ValueError:
            pass
    return ip_conexao, "fallback_conexao"


def _sessao_info(sessao: Optional[str]) -> Dict[str, Any]:
    """Origem e campanha da sessão (gravadas no pageview)."""
    if not sessao:
        return {}
    with conexao() as con:
        l = con.execute("SELECT canal, campanha_id, dados FROM eventos WHERE sessao = ? AND tipo = 'pageview' ORDER BY id LIMIT 1", (sessao,)).fetchone()
    if not l:
        return {}
    d = json_carregar(l["dados"])
    return {"canal": l["canal"], "campanha_id": l["campanha_id"], "origem": d.get("origem"), "utm": d.get("utm") or {}}


# ------------------------------------------------------------------ página HTML
_HTML_CACHE: Dict[str, Any] = {}


def _html_pagina(pagina: Dict[str, Any]) -> str:
    caminho = FRONTEND / "index.html"
    mtime = caminho.stat().st_mtime
    if _HTML_CACHE.get("mtime") != mtime:
        _HTML_CACHE.update(mtime=mtime, texto=caminho.read_text(encoding="utf-8"))
    cfg = pagina["config"]
    titulo = html.escape(cfg["textos"].get("titulo_pagina") or pagina["nome"])
    descricao = html.escape(cfg["textos"].get("descricao_pagina") or cfg["perfil"].get("bio") or "")
    imagem = html.escape(cfg["perfil"].get("avatar") or "")
    meta = ('<title>{t}</title>\n  <meta name="description" content="{d}">\n  <meta property="og:title" content="{t}">\n'
            '  <meta property="og:description" content="{d}">\n  <meta property="og:type" content="website">\n'
            '  <meta name="twitter:card" content="summary">').format(t=titulo, d=descricao)
    if imagem:
        meta += '\n  <meta property="og:image" content="{}">'.format(imagem)
    texto = _HTML_CACHE["texto"].replace("<!--META-->", meta).replace("__SLUG__", html.escape(pagina["slug"]))
    return texto.replace("__V__", VERSAO)


def _servir_pagina(pagina: Optional[Dict[str, Any]], request: Request):
    if not pagina:
        return RedirectResponse("/", status_code=302)
    ua = request.headers.get("user-agent")
    robo = detectar_robo(ua)
    if robo and not request.query_params.get("preview"):
        # Robôs de prévia (WhatsApp, Facebook…) não executam JavaScript: registramos aqui.
        gravar_evento({"tipo": "previa", "pagina_id": pagina["id"], "robo": True, "robo_nome": robo, "ua": (ua or "")[:300],
                       "ua_info": analisar_ua(ua)})
    return HTMLResponse(_html_pagina(pagina))


@rota.get("/", include_in_schema=False)
def inicio(request: Request):
    return _servir_pagina(paginas.obter(), request)


@rota.get("/api/health")
def health():
    return {"ok": True, "versao": VERSAO}


@rota.get("/api/config/permissoes-navegador")
def config_permissoes():
    try:
        return json.loads(CONFIG_PERMISSOES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ativo": False}


@rota.get("/api/public/config")
def config_publica(slug: Optional[str] = None):
    pagina = paginas.obter(slug=slug) if slug else paginas.obter()
    if not pagina:
        raise HTTPException(404, "Página não encontrada.")
    return paginas.config_publica(pagina)


# ------------------------------------------------------------------ eventos
class PayloadEvento(BaseModel):
    tipo: str
    sessao: str
    slug: Optional[str] = None
    pagina: Optional[str] = None
    referer: Optional[str] = None
    campanha: Optional[str] = None
    utm: Dict[str, Optional[str]] = Field(default_factory=dict)
    dados: Dict[str, Any] = Field(default_factory=dict)


def _campanha_id(pagina_id: int, codigo: Optional[str], utm: Dict[str, Optional[str]]) -> Optional[int]:
    with conexao() as con:
        if codigo and re.fullmatch(r"[a-zA-Z0-9_-]{3,40}", codigo):
            l = con.execute("SELECT id FROM campanhas WHERE codigo = ? AND pagina_id = ?", (codigo, pagina_id)).fetchone()
            if l:
                return l["id"]
        if utm.get("utm_campaign"):
            l = con.execute("SELECT id FROM campanhas WHERE pagina_id = ? AND utm_campaign = ? AND (utm_source = ? OR ? IS NULL) ORDER BY id DESC LIMIT 1",
                            (pagina_id, utm["utm_campaign"], utm.get("utm_source"), utm.get("utm_source"))).fetchone()
            if l:
                return l["id"]
    return None


@rota.post("/api/evento")
def registrar_evento(payload: PayloadEvento, request: Request):
    if payload.tipo not in TIPOS_EVENTO or not RE_SESSAO.fullmatch(payload.sessao):
        raise HTTPException(400, "Evento inválido.")
    pagina = paginas.obter(slug=payload.slug) if payload.slug else paginas.obter()
    if not pagina:
        raise HTTPException(404, "Página não encontrada.")
    ua = request.headers.get("user-agent")
    robo_nome = detectar_robo(ua) or ("Navegador automatizado" if payload.dados.get("webdriver") else None)
    ev: Dict[str, Any] = {"tipo": payload.tipo, "pagina_id": pagina["id"], "sessao": payload.sessao,
                          "visitante": visitante_do_cookie(request), "robo": bool(robo_nome)}
    if robo_nome:
        ev["robo_nome"] = robo_nome
    if payload.tipo == "pageview":
        utm = {k: (str(v)[:120] if v else None) for k, v in (payload.utm or {}).items()
               if k in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")}
        origem = classificar_origem(payload.referer, utm.get("utm_source"), request.headers.get("host"), ua)
        ev.update({
            "canal": origem["canal"], "campanha_id": _campanha_id(pagina["id"], payload.campanha, utm),
            "referer": (payload.referer or None) and payload.referer[:500], "utm": utm, "origem": origem,
            "ua": (ua or "")[:400], "ua_info": analisar_ua(ua),
            "idioma": str(payload.dados.get("idioma") or "")[:20] or None,
            "timezone": str(payload.dados.get("timezone") or "")[:60] or None,
            "tela": str(payload.dados.get("tela") or "")[:20] or None,
        })
    elif payload.tipo == "saida":
        try:
            ev["duracao_ms"] = max(0, min(int(payload.dados.get("duracao_ms") or 0), 6 * 3600 * 1000))
            ev["scroll_max"] = max(0, min(int(payload.dados.get("scroll_max") or 0), 100))
        except (TypeError, ValueError):
            ev["duracao_ms"], ev["scroll_max"] = 0, 0
    else:
        ev["dados"] = {k: str(v)[:120] for k, v in list((payload.dados or {}).items())[:8]}
    gravar_evento(ev)
    return {"ok": True}


# ------------------------------------------------------------------ cliques e campanhas
def _clique(pagina: Optional[Dict[str, Any]], link_id: str, request: Request, s: Optional[str], pos: Optional[int], area: Optional[str]):
    if not pagina:
        return RedirectResponse("/", status_code=302)
    link = next((l for l in pagina["config"]["links"] if l["id"] == link_id and l.get("ativo")), None)
    if not link or not link.get("url"):
        return RedirectResponse("/" if pagina["principal"] else "/" + pagina["slug"], status_code=302)
    destino = link["url"]  # só redireciona para URLs cadastradas no painel
    if not request.query_params.get("preview"):
        sessao = s if s and RE_SESSAO.fullmatch(s) else None
        ua = request.headers.get("user-agent")
        prefetch = (request.headers.get("sec-purpose") or request.headers.get("purpose") or "").lower().startswith("prefetch")
        robo_nome = detectar_robo(ua) or ("Pré-carregamento do navegador" if prefetch else None)
        info = _sessao_info(sessao)
        origem = info.get("origem") or classificar_origem(request.headers.get("referer"), None, request.headers.get("host"), ua)
        try:
            host_destino = urlparse(destino).hostname
        except ValueError:
            host_destino = None
        ev = {"tipo": "clique", "pagina_id": pagina["id"], "sessao": sessao, "visitante": visitante_do_cookie(request),
              "robo": bool(robo_nome), "canal": info.get("canal") or origem.get("canal"), "link_id": link_id,
              "campanha_id": info.get("campanha_id"), "link_titulo": link.get("titulo"), "link_tipo": link.get("tipo"),
              "destino": destino, "destino_host": host_destino, "posicao": pos, "area": area if area in ("icone", "botao") else None,
              "origem": origem, "utm": info.get("utm") or {}, "ua_info": analisar_ua(ua)}
        if robo_nome:
            ev["robo_nome"] = robo_nome
        gravar_evento(ev)
    return RedirectResponse(destino, status_code=302)


@rota.get("/r/{slug}/{link_id}", include_in_schema=False)
def redirecionar(slug: str, link_id: str, request: Request, s: Optional[str] = None, pos: Optional[int] = None, area: Optional[str] = None):
    return _clique(paginas.obter(slug=slug), link_id, request, s, pos, area)


@rota.get("/r/{link_id}", include_in_schema=False)
def redirecionar_antigo(link_id: str, request: Request, s: Optional[str] = None, pos: Optional[int] = None, area: Optional[str] = None):
    """Compatibilidade com links da versão anterior (/r/<id>) — usa a página principal."""
    return _clique(paginas.obter(), link_id, request, s, pos, area)


@rota.get("/c/{codigo}", include_in_schema=False)
def campanha(codigo: str):
    with conexao() as con:
        c = con.execute("SELECT c.*, p.slug, p.principal FROM campanhas c JOIN paginas p ON p.id = c.pagina_id WHERE c.codigo = ?", (codigo,)).fetchone()
    if not c:
        return RedirectResponse("/", status_code=302)
    base = "/" if c["principal"] else "/" + c["slug"]
    if not c["ativo"]:
        return RedirectResponse(base, status_code=302)
    q = {k: c[k] for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content") if c[k]}
    q["cmp"] = c["codigo"]
    return RedirectResponse(base + "?" + urlencode(q), status_code=302)


# ------------------------------------------------------------------ coleta consentida
class PayloadColeta(BaseModel):
    consentimento: bool
    sessao: Optional[str] = None
    slug: Optional[str] = None
    coletado_em_cliente: Optional[str] = None
    navegador: Dict[str, Any] = Field(default_factory=dict)
    tela: Dict[str, Any] = Field(default_factory=dict)
    capacidades: Dict[str, Any] = Field(default_factory=dict)
    permissoes: Dict[str, Any] = Field(default_factory=dict)
    origem: Dict[str, Any] = Field(default_factory=dict)
    geolocalizacao: Optional[Dict[str, Any]] = None
    ip_publico_detectado_cliente: Optional[str] = None
    ipinfo_publico_cliente: Optional[Dict[str, Any]] = None
    ips_publicos_cliente: Optional[Dict[str, Any]] = None


@rota.post("/api/coleta")
def coletar(payload: PayloadColeta, request: Request, response: Response):
    if not payload.consentimento:
        raise HTTPException(400, "É necessário consentir com a coleta.")
    vid = visitante_do_cookie(request)
    if not vid:
        vid = secrets.token_hex(16)
        response.set_cookie(COOKIE_VISITANTE, vid, max_age=60 * 60 * 24 * 180, httponly=True, samesite="lax",
                            secure=request.url.scheme == "https")
    with conexao() as con:
        l = con.execute("SELECT * FROM visitantes WHERE id = ?", (vid,)).fetchone()
    anterior = json_carregar(l["registro"]) if l else {}

    ip_conexao, origem_ip = obter_ip_cliente(request)
    ip = ip_conexao
    ips_publicos = payload.ips_publicos_cliente or {}
    if not ip_publico(ip_conexao):
        # Em localhost o servidor só enxerga 127.0.0.1: usamos o IP público descoberto pelo navegador (ipify).
        for cand in (ips_publicos.get("ipv4"), ips_publicos.get("ipv6"), payload.ip_publico_detectado_cliente):
            if cand and ip_publico(cand):
                ip, origem_ip = str(ipaddress.ip_address(cand)), "ip_publico_detectado_pelo_navegador_localhost"
                break
    try:
        tipo_ip = ("IPv6" if ipaddress.ip_address(ip).version == 6 else "IPv4") if ip else None
    except ValueError:
        tipo_ip = None
    h = request.headers
    cabecalhos = {k: h.get(v) for k, v in {
        "user_agent": "user-agent", "accept_language": "accept-language", "referer": "referer", "sec_ch_ua": "sec-ch-ua",
        "sec_ch_ua_mobile": "sec-ch-ua-mobile", "sec_ch_ua_platform": "sec-ch-ua-platform",
        "sec_ch_ua_platform_version": "sec-ch-ua-platform-version", "sec_ch_ua_model": "sec-ch-ua-model",
        "sec_ch_ua_arch": "sec-ch-ua-arch", "sec_ch_ua_bitness": "sec-ch-ua-bitness", "sec_ch_ua_full_version": "sec-ch-ua-full-version",
        "dnt": "dnt", "sec_gpc": "sec-gpc"}.items()}
    conexao_srv = {"ip_observado": ip, "tipo_ip": tipo_ip, "origem_ip": origem_ip, "ips_publicos_detectados": ips_publicos,
                   "ip_conexao_servidor": ip_conexao, "cabecalhos_http": cabecalhos}
    dados_nav = payload.model_dump()
    historico = [x for x in (anterior.get("historico_acessos") or []) if isinstance(x, dict)]
    historico.append({"registrado_em": agora_iso(), "sessao": payload.sessao, "pagina": payload.slug,
                      "conexao_servidor": conexao_srv, "dados_navegador": dados_nav})
    registro = {
        "schema_versao": 4, "visitante_id": vid, "criado_em": anterior.get("criado_em", agora_iso()), "atualizado_em": agora_iso(),
        "quantidade_coletas": int(anterior.get("quantidade_coletas", 0)) + 1,
        "consentimento": {"aceito": True, "registrado_em": agora_iso(), "texto_versao": "coleta-guia-v4"},
        "conexao_servidor": conexao_srv, "dados_navegador": dados_nav, "historico_acessos": historico[-100:],
    }
    with transacao() as con:
        con.execute("INSERT INTO visitantes (id, criado_em, atualizado_em, atualizado_epoch, quantidade_coletas, ip, registro) VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET atualizado_em = excluded.atualizado_em, atualizado_epoch = excluded.atualizado_epoch, "
                    "quantidade_coletas = excluded.quantidade_coletas, ip = excluded.ip, registro = excluded.registro",
                    (vid, registro["criado_em"], registro["atualizado_em"], agora_epoch(), registro["quantidade_coletas"], ip, json_texto(registro)))
        if payload.sessao and RE_SESSAO.fullmatch(payload.sessao):
            con.execute("INSERT OR IGNORE INTO visitante_sessoes (visitante, sessao) VALUES (?, ?)", (vid, payload.sessao))
            # Liga os eventos anônimos desta sessão (antes do "Aceitar") ao visitante.
            con.execute("UPDATE eventos SET visitante = ? WHERE sessao = ? AND visitante IS NULL", (vid, payload.sessao))
    pagina = paginas.obter(slug=payload.slug) if payload.slug else paginas.obter()
    if pagina and payload.sessao and RE_SESSAO.fullmatch(payload.sessao):
        gravar_evento({"tipo": "coleta", "pagina_id": pagina["id"], "sessao": payload.sessao, "visitante": vid,
                       "geolocalizacao": bool(payload.geolocalizacao)})
    return {"ok": True, "visitante_id": vid, "quantidade_coletas": registro["quantidade_coletas"]}


# ------------------------------------------------------------------ páginas extras (/<slug>) — deve ser a última rota
@rota.get("/{slug}", include_in_schema=False)
def pagina_por_slug(slug: str, request: Request):
    if "." in slug:
        raise HTTPException(404, "Não encontrado.")
    return _servir_pagina(paginas.obter(slug=slug), request)
