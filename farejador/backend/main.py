"""
Farejador — Guia de Redes Sociais + Laboratório de Coleta (Python 3.9+)

Monta a aplicação: banco, migração dos dados antigos, limpeza automática,
cabeçalhos de segurança e rotas. A lógica fica nos módulos ao lado:

    config.py        caminhos e variáveis de ambiente
    db.py            banco SQLite (data/farejador.db)
    paginas.py       páginas públicas e personalização
    seguranca.py     login, sessões e CSRF
    analise.py       User-Agent, robôs e origem das visitas
    estatisticas.py  visão geral, comparação, retorno e campanhas
    ipinfo.py        consulta de IP (só pelo painel)
    limpeza.py       retenção de dados
    migracao.py      importa os arquivos JSON da versão anterior
    rotas/           endpoints HTTP
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import limpeza, migracao, seguranca
from .config import FRONTEND, UPLOADS, VERSAO
from .db import iniciar_banco
from .rotas import admin_auth, admin_dados, admin_paginas, publico

app = FastAPI(title="Farejador — Guia de Redes + Coleta", version=VERSAO)
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
app.mount("/media", StaticFiles(directory=str(UPLOADS)), name="media")

# A ordem importa: a rota pública "/{slug}" fica por último.
app.include_router(admin_auth.rota)
app.include_router(admin_paginas.rota)
app.include_router(admin_dados.rota)
app.include_router(publico.rota)


@app.on_event("startup")
def ao_iniciar() -> None:
    iniciar_banco()
    resumo = migracao.executar()
    if any(resumo.values()):
        print("[migração] dados antigos importados para o banco:", resumo)
    seguranca.aplicar_senha_env()
    limpeza.iniciar_agendador()


@app.middleware("http")
async def cabecalhos(request: Request, call_next):
    resposta = await call_next(request)
    caminho = request.url.path
    h = resposta.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if caminho.startswith("/admin") or caminho.startswith("/api/admin"):
        h["X-Frame-Options"] = "DENY"
        h["Cache-Control"] = "no-store"
    else:
        h.setdefault("X-Frame-Options", "SAMEORIGIN")  # a prévia do painel usa iframe da própria origem
        if caminho.startswith("/static") or caminho.startswith("/api/public") or "." not in caminho:
            h.setdefault("Cache-Control", "no-cache, must-revalidate")
    return resposta


@app.exception_handler(StarletteHTTPException)
async def erro_http(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith(("/api/", "/static/", "/media/")):
        return RedirectResponse("/", status_code=302)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))
