"""Rotas do painel: páginas (várias), configuração, campanhas e upload de imagens."""
import base64
import re
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import paginas
from ..config import UPLOADS
from ..db import agora_iso, conexao, transacao
from ..seguranca import exigir_admin

rota = APIRouter(prefix="/api/admin", dependencies=[Depends(exigir_admin)])


def _pagina_ou_404(pid: int):
    p = paginas.obter(pid)
    if not p:
        raise HTTPException(404, "Página não encontrada.")
    return p


def _erro(fn, *a, **k):
    try:
        return fn(*a, **k)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------------------------ páginas
class PayloadPagina(BaseModel):
    nome: Optional[str] = None
    slug: Optional[str] = None
    principal: Optional[bool] = None
    copiar_de: Optional[int] = None


@rota.get("/paginas")
def listar():
    with conexao() as con:
        cont = {l["pagina_id"]: l["n"] for l in con.execute("SELECT pagina_id, COUNT(*) AS n FROM eventos WHERE tipo = 'pageview' AND robo = 0 GROUP BY pagina_id")}
    return {"paginas": [{"id": p["id"], "slug": p["slug"], "nome": p["nome"], "principal": p["principal"], "atualizado_em": p["atualizado_em"],
                         "links": len(p["config"]["links"]), "visitas": cont.get(p["id"], 0),
                         "avatar": p["config"]["perfil"].get("avatar"), "preset": p["config"]["tema"].get("preset")} for p in paginas.listar()]}


@rota.post("/paginas")
def criar(payload: PayloadPagina):
    base = None
    if payload.copiar_de:
        base = _pagina_ou_404(payload.copiar_de)["config"]
    nome = (payload.nome or "Nova página").strip()
    cfg = base or {"perfil": {"nome": nome}, "textos": {"titulo_pagina": nome}}
    p = _erro(paginas.criar, nome, payload.slug or nome, cfg, bool(payload.principal))
    return p


@rota.patch("/paginas/{pid}")
def atualizar(pid: int, payload: PayloadPagina):
    _pagina_ou_404(pid)
    return _erro(paginas.atualizar, pid, payload.nome, payload.slug, payload.principal)


@rota.delete("/paginas/{pid}")
def excluir(pid: int):
    _pagina_ou_404(pid)
    _erro(paginas.excluir, pid)
    return {"ok": True}


@rota.get("/paginas/{pid}/config")
def config(pid: int):
    return _pagina_ou_404(pid)


@rota.put("/paginas/{pid}/config")
async def salvar_config(pid: int, request: Request):
    _pagina_ou_404(pid)
    try:
        novo = await request.json()
    except ValueError:
        raise HTTPException(400, "JSON inválido.")
    return paginas.salvar_config(pid, novo)


@rota.get("/opcoes")
def opcoes():
    return {"fontes": paginas.FONTES, "presets": paginas.PRESETS}


# ------------------------------------------------------------------ campanhas (links rastreados)
class PayloadCampanha(BaseModel):
    pagina_id: int
    nome: str
    origem: Optional[str] = None
    utm_source: str
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    codigo: Optional[str] = None
    ativo: Optional[bool] = None


def _limpar_utm(v: Optional[str]) -> Optional[str]:
    v = re.sub(r"[^a-z0-9_.\-]", "-", (v or "").strip().lower())
    v = re.sub(r"-{2,}", "-", v).strip("-")[:60]
    return v or None


@rota.post("/campanhas")
def criar_campanha(p: PayloadCampanha):
    _pagina_ou_404(p.pagina_id)
    if not p.nome.strip() or not _limpar_utm(p.utm_source):
        raise HTTPException(400, "Informe o nome e a origem da campanha.")
    codigo = _limpar_utm(p.codigo) if p.codigo else None
    with transacao() as con:
        if codigo and con.execute("SELECT 1 FROM campanhas WHERE codigo = ?", (codigo,)).fetchone():
            raise HTTPException(400, "Esse código curto já está em uso.")
        while not codigo:
            c = secrets.token_urlsafe(4).replace("_", "").replace("-", "").lower()[:5]
            if len(c) == 5 and not con.execute("SELECT 1 FROM campanhas WHERE codigo = ?", (c,)).fetchone():
                codigo = c
        cur = con.execute("INSERT INTO campanhas (codigo, pagina_id, nome, origem, utm_source, utm_medium, utm_campaign, utm_content, ativo, criado_em) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                          (codigo, p.pagina_id, p.nome.strip()[:80], (p.origem or "")[:40], _limpar_utm(p.utm_source), _limpar_utm(p.utm_medium),
                           _limpar_utm(p.utm_campaign) or _limpar_utm(p.nome), _limpar_utm(p.utm_content), agora_iso()))
        cid = cur.lastrowid
    with conexao() as con:
        return dict(con.execute("SELECT * FROM campanhas WHERE id = ?", (cid,)).fetchone())


class PayloadCampanhaEdicao(BaseModel):
    nome: Optional[str] = None
    ativo: Optional[bool] = None


@rota.patch("/campanhas/{cid}")
def editar_campanha(cid: int, p: PayloadCampanhaEdicao):
    with transacao() as con:
        if p.ativo is not None:
            con.execute("UPDATE campanhas SET ativo = ? WHERE id = ?", (1 if p.ativo else 0, cid))
        if p.nome and p.nome.strip():
            con.execute("UPDATE campanhas SET nome = ? WHERE id = ?", (p.nome.strip()[:80], cid))
    return {"ok": True}


@rota.delete("/campanhas/{cid}")
def excluir_campanha(cid: int):
    with transacao() as con:
        con.execute("UPDATE eventos SET campanha_id = NULL WHERE campanha_id = ?", (cid,))
        con.execute("DELETE FROM campanhas WHERE id = ?", (cid,))
    return {"ok": True}


# ------------------------------------------------------------------ upload de imagens
class PayloadUpload(BaseModel):
    nome: str = "imagem"
    data_url: str


@rota.post("/upload")
def upload(payload: PayloadUpload):
    m = re.match(r"^data:image/(png|jpe?g|webp|gif);base64,(.+)$", payload.data_url, re.S)
    if not m:
        raise HTTPException(400, "Envie uma imagem PNG, JPG, WEBP ou GIF.")
    ext = "jpg" if m.group(1) == "jpeg" else m.group(1)
    try:
        dados = base64.b64decode(m.group(2), validate=False)
    except ValueError:
        raise HTTPException(400, "Imagem corrompida.")
    if len(dados) > 5 * 1024 * 1024:
        raise HTTPException(400, "Imagem acima de 5 MB.")
    assinaturas = {"png": b"\x89PNG", "jpg": b"\xff\xd8", "gif": b"GIF8", "webp": b"RIFF"}
    if not dados.startswith(assinaturas[ext]):
        raise HTTPException(400, "O arquivo não parece ser uma imagem válida.")
    nome = "{}-{}.{}".format(re.sub(r"[^a-z0-9]", "", payload.nome.lower())[:20] or "img", secrets.token_hex(4), ext)
    (UPLOADS / nome).write_bytes(dados)
    return {"ok": True, "url": "/media/" + nome}
