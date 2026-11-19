"""Rotas de login, sessões e usuários do painel."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import seguranca as seg
from ..config import FRONTEND
from ..db import conexao, transacao

rota = APIRouter()


class PayloadLogin(BaseModel):
    usuario: str
    senha: str
    lembrar: bool = False


class PayloadSenha(BaseModel):
    senha_atual: str
    nova_senha: str


class PayloadUsuario(BaseModel):
    usuario: str
    senha: str


@rota.get("/admin", include_in_schema=False)
def admin_pagina():
    return FileResponse(str(FRONTEND / "admin.html"))


@rota.get("/api/admin/estado")
def estado(request: Request):
    s = seg.sessao_atual(request)
    return {"tem_usuarios": seg.tem_usuarios(), "logado": bool(s), "usuario": s["usuario"] if s else None}


@rota.post("/api/admin/primeiro-acesso")
def primeiro_acesso(payload: PayloadLogin, request: Request, response: Response):
    if request.headers.get("x-farejador") != "1":
        raise HTTPException(403, "Requisição bloqueada.")
    if seg.tem_usuarios():
        raise HTTPException(400, "O primeiro usuário já foi criado.")
    seg.validar_senha_nova(payload.senha)
    seg.criar_usuario(payload.usuario, payload.senha)
    u = seg.autenticar(payload.usuario, payload.senha, request)
    seg.abrir_sessao(response, request, u["id"], payload.lembrar)
    return {"ok": True}


@rota.post("/api/admin/login")
def login(payload: PayloadLogin, request: Request, response: Response):
    if request.headers.get("x-farejador") != "1":
        raise HTTPException(403, "Requisição bloqueada.")
    u = seg.autenticar(payload.usuario, payload.senha, request)
    seg.abrir_sessao(response, request, u["id"], payload.lembrar)
    return {"ok": True, "usuario": u["usuario"]}


@rota.post("/api/admin/logout")
def logout(request: Request, response: Response):
    seg.encerrar_sessao(request, response)
    return {"ok": True}


@rota.get("/api/admin/sessoes")
def sessoes(s=Depends(seg.exigir_admin)):
    return {"sessoes": seg.listar_sessoes(s["usuario_id"], s["token_hash"])}


@rota.post("/api/admin/sessoes/encerrar-outras")
def encerrar_outras(s=Depends(seg.exigir_admin)):
    return {"encerradas": seg.encerrar_outras(s["usuario_id"], s["token_hash"])}


@rota.delete("/api/admin/sessoes/{sid}")
def encerrar_uma(sid: str, s=Depends(seg.exigir_admin)):
    seg.encerrar_por_id(s["usuario_id"], sid)
    return {"ok": True}


@rota.post("/api/admin/trocar-senha")
def trocar_senha(payload: PayloadSenha, request: Request, s=Depends(seg.exigir_admin)):
    seg.autenticar(s["usuario"], payload.senha_atual, request)
    seg.validar_senha_nova(payload.nova_senha)
    seg.definir_senha(s["usuario_id"], payload.nova_senha)
    seg.encerrar_outras(s["usuario_id"], s["token_hash"])
    return {"ok": True}


@rota.get("/api/admin/usuarios")
def usuarios(s=Depends(seg.exigir_admin)):
    with conexao() as con:
        lista = [{"id": l["id"], "usuario": l["usuario"], "criado_em": l["criado_em"], "ultimo_login": l["ultimo_login"], "voce": l["id"] == s["usuario_id"]}
                 for l in con.execute("SELECT * FROM usuarios ORDER BY id")]
    return {"usuarios": lista}


@rota.post("/api/admin/usuarios")
def criar_usuario(payload: PayloadUsuario, s=Depends(seg.exigir_admin)):
    seg.validar_senha_nova(payload.senha)
    seg.criar_usuario(payload.usuario, payload.senha)
    return {"ok": True}


@rota.delete("/api/admin/usuarios/{uid}")
def excluir_usuario(uid: int, s=Depends(seg.exigir_admin)):
    if uid == s["usuario_id"]:
        raise HTTPException(400, "Você não pode excluir o próprio usuário.")
    with transacao() as con:
        if con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] <= 1:
            raise HTTPException(400, "Mantenha pelo menos um usuário.")
        con.execute("DELETE FROM sessoes_admin WHERE usuario_id = ?", (uid,))
        con.execute("DELETE FROM usuarios WHERE id = ?", (uid,))
    return {"ok": True}
