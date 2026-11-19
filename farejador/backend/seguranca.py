"""Login do painel: usuários, senhas com PBKDF2, sessões no banco, bloqueio e CSRF."""
import hashlib
import hmac
import secrets
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request, Response

from .config import SENHA_ADMIN_ENV
from .db import agora_iso, conexao, transacao

ITERACOES = 310_000
COOKIE = "farejador_admin"
SESSAO_CURTA = 60 * 60 * 12          # 12 horas
SESSAO_LONGA = 60 * 60 * 24 * 30     # 30 dias ("manter conectado")
MAX_FALHAS_IP = 10                   # por 15 minutos
MAX_FALHAS_USUARIO = 6               # bloqueia a conta por 15 minutos
BLOQUEIO_S = 15 * 60
SENHA_MIN = 8


def _hash(senha: str, sal: bytes, iteracoes: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, iteracoes).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def validar_senha_nova(senha: str) -> None:
    if len(senha or "") < SENHA_MIN:
        raise HTTPException(400, "A senha precisa ter pelo menos {} caracteres.".format(SENHA_MIN))
    if senha.isdigit() or senha.lower() in ("12345678", "senha123", "password", "farejador"):
        raise HTTPException(400, "Escolha uma senha menos óbvia (misture letras e números).")


def tem_usuarios() -> bool:
    with conexao() as con:
        return con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] > 0


def criar_usuario(usuario: str, senha: str, iteracoes: int = ITERACOES, sal_hex: Optional[str] = None, hash_hex: Optional[str] = None) -> None:
    usuario = (usuario or "").strip()[:40]
    if not usuario or not usuario.replace("_", "").replace(".", "").replace("-", "").isalnum():
        raise HTTPException(400, "Usuário inválido (use letras, números, ponto, hífen ou _).")
    if hash_hex is None:
        sal = secrets.token_bytes(16)
        sal_hex, hash_hex = sal.hex(), _hash(senha, sal, iteracoes)
    with transacao() as con:
        if con.execute("SELECT 1 FROM usuarios WHERE usuario = ?", (usuario,)).fetchone():
            raise HTTPException(400, "Esse usuário já existe.")
        con.execute("INSERT INTO usuarios (usuario, hash, sal, iteracoes, criado_em) VALUES (?, ?, ?, ?, ?)",
                    (usuario, hash_hex, sal_hex, iteracoes, agora_iso()))


def definir_senha(usuario_id: int, senha: str) -> None:
    sal = secrets.token_bytes(16)
    with transacao() as con:
        con.execute("UPDATE usuarios SET hash = ?, sal = ?, iteracoes = ?, falhas = 0, bloqueado_ate = 0 WHERE id = ?",
                    (_hash(senha, sal, ITERACOES), sal.hex(), ITERACOES, usuario_id))


def aplicar_senha_env() -> None:
    """FAREJADOR_ADMIN_SENHA cria/redefine o usuário 'admin' (útil se esquecer a senha)."""
    if not SENHA_ADMIN_ENV:
        return
    with conexao() as con:
        l = con.execute("SELECT id FROM usuarios WHERE usuario = 'admin'").fetchone()
    if l:
        definir_senha(l["id"], SENHA_ADMIN_ENV)
    else:
        criar_usuario("admin", SENHA_ADMIN_ENV)


def ip_de(request: Request) -> str:
    return request.client.host if request.client else "?"


def autenticar(usuario: str, senha: str, request: Request) -> Dict[str, Any]:
    ip, agora = ip_de(request), time.time()
    with transacao() as con:
        con.execute("DELETE FROM tentativas_login WHERE ts_epoch < ?", (agora - BLOQUEIO_S,))
        falhas_ip = con.execute("SELECT COUNT(*) FROM tentativas_login WHERE ip = ?", (ip,)).fetchone()[0]
    if falhas_ip >= MAX_FALHAS_IP:
        raise HTTPException(429, "Muitas tentativas deste dispositivo. Aguarde 15 minutos.")
    with conexao() as con:
        u = con.execute("SELECT * FROM usuarios WHERE usuario = ?", ((usuario or "").strip(),)).fetchone()
    if u and u["bloqueado_ate"] > agora:
        raise HTTPException(429, "Conta bloqueada temporariamente por tentativas erradas. Tente em alguns minutos.")
    ok = bool(u) and hmac.compare_digest(_hash(senha or "", bytes.fromhex(u["sal"]), u["iteracoes"]), u["hash"])
    if not u:
        _hash(senha or "", b"x" * 16, ITERACOES)  # mesmo tempo de resposta para usuário inexistente
    if not ok:
        with transacao() as con:
            con.execute("INSERT INTO tentativas_login (ip, ts_epoch) VALUES (?, ?)", (ip, agora))
            if u:
                falhas = u["falhas"] + 1
                bloq = agora + BLOQUEIO_S if falhas >= MAX_FALHAS_USUARIO else 0
                con.execute("UPDATE usuarios SET falhas = ?, bloqueado_ate = ? WHERE id = ?", (0 if bloq else falhas, bloq, u["id"]))
        raise HTTPException(401, "Usuário ou senha incorretos.")
    with transacao() as con:
        con.execute("UPDATE usuarios SET falhas = 0, bloqueado_ate = 0, ultimo_login = ? WHERE id = ?", (agora_iso(), u["id"]))
    # Senhas da versão antiga (menos iterações) são reforçadas no primeiro login.
    if u["iteracoes"] < ITERACOES:
        definir_senha(u["id"], senha)
    return {"id": u["id"], "usuario": u["usuario"]}


def abrir_sessao(response: Response, request: Request, usuario_id: int, lembrar: bool) -> None:
    token = secrets.token_urlsafe(32)
    duracao = SESSAO_LONGA if lembrar else SESSAO_CURTA
    with transacao() as con:
        con.execute("INSERT INTO sessoes_admin (token_hash, usuario_id, criado_em, expira_epoch, ultimo_uso, ip, ua) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (_hash_token(token), usuario_id, agora_iso(), time.time() + duracao, agora_iso(), ip_de(request),
                     (request.headers.get("user-agent") or "")[:200]))
    response.set_cookie(COOKIE, token, max_age=duracao if lembrar else None, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")


def sessao_atual(request: Request) -> Optional[Dict[str, Any]]:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    th = _hash_token(token)
    with conexao() as con:
        l = con.execute("SELECT s.token_hash, s.usuario_id, s.expira_epoch, u.usuario FROM sessoes_admin s "
                        "JOIN usuarios u ON u.id = s.usuario_id WHERE s.token_hash = ?", (th,)).fetchone()
    if not l:
        return None
    if l["expira_epoch"] < time.time():
        with transacao() as con:
            con.execute("DELETE FROM sessoes_admin WHERE token_hash = ?", (th,))
        return None
    return {"token_hash": th, "usuario_id": l["usuario_id"], "usuario": l["usuario"]}


def exigir_admin(request: Request) -> Dict[str, Any]:
    """Dependência das rotas do painel: exige login e, em escritas, o cabeçalho anti-CSRF."""
    s = sessao_atual(request)
    if not s:
        raise HTTPException(401, "Faça login no painel.")
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-farejador") != "1":
        raise HTTPException(403, "Requisição bloqueada (proteção CSRF).")
    with transacao() as con:
        con.execute("UPDATE sessoes_admin SET ultimo_uso = ? WHERE token_hash = ?", (agora_iso(), s["token_hash"]))
    return s


def encerrar_sessao(request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        with transacao() as con:
            con.execute("DELETE FROM sessoes_admin WHERE token_hash = ?", (_hash_token(token),))
    response.delete_cookie(COOKIE, path="/")


def listar_sessoes(usuario_id: int, token_hash_atual: str) -> List[Dict[str, Any]]:
    with conexao() as con:
        linhas = con.execute("SELECT * FROM sessoes_admin WHERE usuario_id = ? AND expira_epoch > ? ORDER BY ultimo_uso DESC",
                             (usuario_id, time.time())).fetchall()
    return [{"id": l["token_hash"][:16], "criado_em": l["criado_em"], "ultimo_uso": l["ultimo_uso"], "ip": l["ip"], "ua": l["ua"],
             "atual": l["token_hash"] == token_hash_atual} for l in linhas]


def encerrar_outras(usuario_id: int, token_hash_atual: str) -> int:
    with transacao() as con:
        return con.execute("DELETE FROM sessoes_admin WHERE usuario_id = ? AND token_hash <> ?", (usuario_id, token_hash_atual)).rowcount


def encerrar_por_id(usuario_id: int, prefixo: str) -> None:
    with transacao() as con:
        con.execute("DELETE FROM sessoes_admin WHERE usuario_id = ? AND substr(token_hash, 1, 16) = ?", (usuario_id, prefixo[:16]))
