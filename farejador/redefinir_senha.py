"""
Redefine (ou cria) um usuário do painel administrativo.
Use se esqueceu a senha ou se a conta ficou bloqueada por tentativas erradas.

    python redefinir_senha.py
"""
import getpass
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from backend import migracao, seguranca  # noqa: E402
from backend.db import conexao, iniciar_banco, transacao  # noqa: E402


def main() -> None:
    iniciar_banco()
    migracao.executar()  # importa os dados antigos, se ainda não importou
    with conexao() as con:
        usuarios = [l["usuario"] for l in con.execute("SELECT usuario FROM usuarios ORDER BY id")]
    print("=" * 50)
    print("REDEFINIR SENHA DO PAINEL")
    print("Usuários existentes:", ", ".join(usuarios) if usuarios else "(nenhum)")
    print("=" * 50)
    usuario = input("Usuário [admin]: ").strip() or "admin"
    while True:
        senha = getpass.getpass("Nova senha (mín. 8 caracteres, não aparece ao digitar): ")
        if len(senha) < 8:
            print("  A senha precisa ter pelo menos 8 caracteres.")
            continue
        if getpass.getpass("Repita a nova senha: ") != senha:
            print("  As senhas não conferem. Tente de novo.")
            continue
        break
    with conexao() as con:
        l = con.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
    if l:
        seguranca.definir_senha(l["id"], senha)  # também desbloqueia a conta
        with transacao() as con:
            con.execute("DELETE FROM sessoes_admin WHERE usuario_id = ?", (l["id"],))
        print("Senha do usuário '{}' redefinida.".format(usuario))
    else:
        seguranca.criar_usuario(usuario, senha)
        print("Usuário '{}' criado.".format(usuario))
    with transacao() as con:
        con.execute("DELETE FROM tentativas_login")
    print("Pronto! Entre em http://127.0.0.1:8000/admin com o usuário '{}'.".format(usuario))


if __name__ == "__main__":
    try:
        main()
    finally:
        if sys.platform.startswith("win"):
            input("\nPressione ENTER para fechar...")
