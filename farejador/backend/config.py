"""Caminhos, variáveis de ambiente e constantes do projeto."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = Path(os.getenv("FAREJADOR_DATA_ROOT", str(RAIZ / "data")))
UPLOADS = DADOS / "uploads"
BANCO = DADOS / "farejador.db"
FRONTEND = RAIZ / "frontend"
CONFIG_PERMISSOES = RAIZ / "sistema" / "config" / "permissoes_navegador.json"

# Arquivos da versão anterior (JSON), importados automaticamente para o banco.
LEGADO_CONFIG = DADOS / "config.json"
LEGADO_EVENTOS = DADOS / "eventos.jsonl"
LEGADO_VISITANTES = Path(os.getenv("FAREJADOR_DATA_DIR", str(DADOS / "visitors")))
LEGADO_ADMIN = DADOS / "admin.json"

IPINFO_TOKEN = os.getenv("IPINFO_TOKEN", "").strip()
CONFIAR_PROXY = os.getenv("FAREJADOR_TRUST_PROXY", "0").strip() == "1"
SENHA_ADMIN_ENV = os.getenv("FAREJADOR_ADMIN_SENHA", "")

VERSAO = "4.0.0"

# Endereços que não podem virar "slug" de página pública.
SLUGS_RESERVADOS = {"admin", "api", "static", "media", "r", "c", "docs", "redoc", "openapi.json", "favicon.ico", "robots.txt"}

for _pasta in (DADOS, UPLOADS):
    _pasta.mkdir(parents=True, exist_ok=True)
