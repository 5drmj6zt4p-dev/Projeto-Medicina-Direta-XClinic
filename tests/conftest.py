"""Fixtures dos testes do coletor: servidor sintético e Chrome descartável.

O Chrome é aberto como no uso real (``--remote-debugging-port``), só que com
perfil temporário, headless e apontado para o servidor sintético local. O
coletor conecta a ele por CDP, como faria com o Chrome dedicado. Nenhum
teste acessa o MD.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

from tests.md_sintetico import MDSintetico

_CANDIDATOS_CHROME = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)


def _chrome():
    candidatos = [os.environ.get("FLUXO_CHROME")] + list(_CANDIDATOS_CHROME)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            candidatos.append(p.chromium.executable_path)
    except Exception:
        pass
    return next((c for c in candidatos if c and Path(c).is_file()), None)


class ChromeDescartavel:
    def __init__(self, executavel, url):
        self.perfil = tempfile.mkdtemp(prefix="fluxo-teste-chrome-")
        self.processo = subprocess.Popen(
            [executavel, "--headless=new", "--remote-debugging-port=0",
             "--user-data-dir=" + self.perfil, "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", "--disable-background-networking", "--disable-sync",
             "--disable-component-update", "--window-size=1400,1000", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        arquivo = Path(self.perfil, "DevToolsActivePort")
        limite = time.monotonic() + 20
        while time.monotonic() < limite:
            if arquivo.exists() and arquivo.read_text().strip():
                break
            time.sleep(0.1)
        else:
            self.fechar()
            raise RuntimeError("Chrome não abriu a porta de depuração")
        self.cdp_url = "http://127.0.0.1:%s" % arquivo.read_text().split()[0]
        while time.monotonic() < limite and not any(
                a.get("url", "").startswith(url) for a in self.abas()):
            time.sleep(0.1)

    def abas(self):
        try:
            with urllib.request.urlopen(self.cdp_url + "/json/list", timeout=2) as resposta:
                return [a for a in json.load(resposta) if a.get("type") == "page"]
        except OSError:
            return []

    def vivo(self):
        return self.processo.poll() is None

    def fechar(self):
        if self.vivo():
            self.processo.kill()
        self.processo.wait(timeout=20)
        for _ in range(20):
            shutil.rmtree(self.perfil, ignore_errors=True)
            if not Path(self.perfil).exists():
                break
            time.sleep(0.2)


@pytest.fixture
def md(request):
    marcador = request.node.get_closest_marker("md")
    servidor = MDSintetico(**(marcador.kwargs if marcador else {}))
    servidor.iniciar()
    yield servidor
    servidor.parar()


@pytest.fixture
def chrome(md):
    executavel = _chrome()
    if executavel is None:
        pytest.skip("Chrome/Chromium não encontrado (defina FLUXO_CHROME)")
    navegador = ChromeDescartavel(executavel, md.url + "/menu_inicial/")
    yield navegador
    navegador.fechar()


@pytest.fixture
def coletor(chrome, md):
    from fluxo_exames.coletor import Coletor

    c = Coletor(cdp_url=chrome.cdp_url, origem_md=md.url, espera_ms=10000)
    c.conectar()
    yield c
    c.desconectar()


def pytest_configure(config):
    config.addinivalue_line("markers", "md(**opcoes): opções do servidor sintético")
