"""
Inicializador do Farejador - Coleta Didática.
Execute este arquivo pelo VS Code ou com: python iniciar.py
Compatível com Python 3.9.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import uvicorn
except ImportError:
    print("Dependências não instaladas.")
    print("Execute: python -m pip install -r requirements.txt")
    input("Pressione ENTER para sair...")
    raise SystemExit(1)

if __name__ == "__main__":
    print("=" * 58)
    print("FAREJADOR - GUIA DE REDES + COLETA")
    print("Pagina principal: http://127.0.0.1:8000")
    print("Outras paginas:   http://127.0.0.1:8000/<endereco>")
    print("Painel admin:     http://127.0.0.1:8000/admin")
    print("Documentacao API: http://127.0.0.1:8000/docs")
    print("Para encerrar: CTRL+C")
    print("=" * 58)
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )
