#!/usr/bin/env python3
"""Bateria da sentinela. Roda sem internet: python testes/testar.py"""
import contextlib
import http.server
import io
import itertools
import json
import os
import random
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import sentinela as s  # noqa: E402

COMECO = datetime(2026, 10, 22, 8, 57, tzinfo=s.BRT)
PASSO = timedelta(minutes=5)
TOPICO = "canal-falso-nao-pode-aparecer"
contagem = {"ok": 0, "falhou": 0}
falhas = []


def confere(condicao, nome):
    if condicao:
        contagem["ok"] += 1
    else:
        contagem["falhou"] += 1
        falhas.append(nome)


def simular(sequencia, envios=None, comeco=COMECO):
    """Roda a decisao em sequencia. envios[i] False = o aviso daquela rodada nao saiu."""
    estado = dict(s.ESTADO_LIMPO)
    avisos = []
    for i, ok in enumerate(sequencia):
        agora = comeco + PASSO * i
        saiu, ficou, aviso = s.decidir(estado, ok, "http 502", agora)
        enviado = envios[i] if envios else True
        if aviso and enviado:
            avisos.append((i, aviso["titulo"]))
        estado = saiu if (aviso is None or enviado) else ficou
    return avisos, estado


def esperado(sequencia):
    """Oraculo independente: varre os trechos de falha, sem usar decidir()."""
    saida = []
    i = 0
    while i < len(sequencia):
        if sequencia[i]:
            i += 1
            continue
        fim = i
        while fim < len(sequencia) and not sequencia[fim]:
            fim += 1
        if fim - i >= 2:
            saida.append((i + 1, "queda"))
            if fim < len(sequencia):
                saida.append((fim, "volta"))
        i = fim
    return saida


def tipo(titulo):
    return "volta" if "RESOLVIDO" in titulo else "queda"


# 1. Todas as sequencias de ok/falha ate 13 rodadas: 16.382 casos contra o oraculo.
for tamanho in range(1, 14):
    for sequencia in itertools.product([True, False], repeat=tamanho):
        avisos, _ = simular(sequencia)
        obtido = [(i, tipo(t)) for i, t in avisos]
        confere(obtido == esperado(sequencia), f"sequencia {sequencia}")

# 2. Toda combinacao de rodada e aviso que nao sai, ate 7 rodadas: nada se perde nem repete.
for tamanho in range(1, 8):
    for sequencia in itertools.product([True, False], repeat=tamanho):
        for envios in itertools.product([True, False], repeat=tamanho):
            avisos, estado = simular(list(sequencia) + [False, False, True], list(envios) + [True, True, True])
            tipos = [tipo(t) for _, t in avisos]
            alternam = all(a != b for a, b in zip(tipos, tipos[1:]))
            confere(alternam and (not tipos or tipos[0] == "queda"), f"alternancia {sequencia} {envios}")
            confere(tipos and tipos[-1] == "volta", f"ultimo aviso {sequencia} {envios}")
            confere(estado == s.ESTADO_LIMPO, f"estado final {sequencia} {envios}")

# 3. Longas e aleatorias, com semente fixa.
sorteio = random.Random(20261022)
for caso in range(3000):
    sequencia = [sorteio.random() < 0.6 for _ in range(sorteio.randint(14, 400))]
    avisos, _ = simular(sequencia)
    confere([(i, tipo(t)) for i, t in avisos] == esperado(sequencia), f"longa {caso}")

# 4. Texto: o caso real de 22/10.
avisos, _ = simular([False, False] + [False] * 20 + [True])
confere(avisos[0][1] == "PROBLEMA NOSSO — plataforma fora do ar desde 08:57", "manchete da queda")
confere(avisos[1][1] == "PROBLEMA NOSSO RESOLVIDO — plataforma voltou às 10:47", "manchete da volta")
_, _, aviso = s.decidir(
    {"falhas": 22, "desde": COMECO.isoformat(), "avisado": True, "voltou_em": None},
    True, "ok", COMECO + timedelta(minutes=110),
)
confere(aviso["texto"].startswith("Ficou fora desde 08:57 (1h50)"), "duracao 1h50")
confere(aviso["prioridade"] == 3, "volta sem urgencia")
_, _, aviso = s.decidir({"falhas": 1, "desde": COMECO.isoformat(), "avisado": False, "voltou_em": None},
                        False, "http 502", COMECO + PASSO, "TESTE · ")
confere(aviso["titulo"] == "TESTE · PROBLEMA NOSSO — plataforma fora do ar desde 08:57", "rotulo de teste")
confere(aviso["prioridade"] == 5, "queda urgente")
confere("http 502" in aviso["texto"], "motivo no texto")

# 5. Hora: toda a virada de dia e toda duracao de 0 a 3 dias.
noite = datetime(2026, 10, 30, 23, 50, tzinfo=s.BRT)
_, _, aviso = s.decidir({"falhas": 1, "desde": noite.isoformat(), "avisado": False, "voltou_em": None},
                        False, "x", noite + timedelta(minutes=15))
confere("desde 23:50 de 30/10" in aviso["titulo"], "queda na virada do dia")
for minutos in range(0, 4320, 7):
    texto = s._duracao(COMECO, COMECO + timedelta(minutes=minutos))
    certo = f"{minutos} min" if minutos < 60 else f"{minutos // 60}h{minutos % 60:02d}"
    confere(texto == certo, f"duracao {minutos}")
utc = datetime(2026, 10, 22, 11, 57, tzinfo=s.timezone.utc).astimezone(s.BRT)
confere(utc.strftime("%H:%M") == "08:57", "UTC vira BRT")

# 6. Volta que nao saiu guarda a hora certa da volta.
estado = {"falhas": 5, "desde": COMECO.isoformat(), "avisado": True, "voltou_em": None}
volta = COMECO + timedelta(minutes=30)
_, ficou, aviso = s.decidir(estado, True, "ok", volta)
_, _, aviso2 = s.decidir(ficou, True, "ok", volta + PASSO)
confere(aviso["titulo"] == aviso2["titulo"], "volta pendente mantem a hora")
novo_saiu, _, aviso3 = s.decidir(ficou, False, "http 500", volta + PASSO)
confere(aviso3 is None and novo_saiu["avisado"] and novo_saiu["voltou_em"] is None, "caiu de novo antes de avisar a volta")

# 7. Classificacao da resposta.
for status in [100, 201, 202, 204, 301, 302, 400, 401, 403, 404, 408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 530]:
    confere(s.avaliar(status, b'{"status":"ok"}') == (False, f"http {status}"), f"codigo {status}")
for corpo, valido in [
    (b'{"status":"ok"}', True),
    (b'{"status":"ok","timestamp":"x","version":"v411","db":"ok"}', True),
    (b'{"status":"OK"}', False), (b'{"status":"fora"}', False), (b'{"status":"degraded"}', False),
    (b'{"status":null}', False), (b'{"status":true}', False), (b'{"estado":"ok"}', False), (b"{}", False),
    (b"[]", False), (b'["status","ok"]', False), (b'"ok"', False), (b"ok", False), (b"", False), (b"null", False),
    (b'{"status":"ok"', False), (b"<!doctype html><html></html>", False),
    (b'<html>"status":"ok"</html>', False), (b"\xff\xfe", False), (b'{"status":["ok"]}', False),
]:
    confere(s.avaliar(200, corpo)[0] is valido, f"corpo {corpo!r}")


# 8. Rede de verdade, num servidor local.
class Falso(http.server.BaseHTTPRequestHandler):
    recebidos = []
    ntfy_status = 200

    def log_message(self, *args):
        pass

    def do_GET(self):
        Falso.agentes.append(self.headers.get("User-Agent"))
        if self.path == "/lento":
            time.sleep(2)
        if self.path == "/ir":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
            return
        if self.path == "/lixo":
            self.wfile.write(b"isto nao e http" + bytes([13, 10, 13, 10]))
            return
        if self.path == "/corta":
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"{")
            self.close_connection = True
            return
        corpo, codigo = {
            "/ok": (b'{"status":"ok"}', 200), "/html": (b"<html></html>", 200), "/fora": (b'{"status":"fora"}', 200),
            "/401": (b"", 401), "/404": (b"", 404), "/500": (b"", 500), "/502": (b"", 502), "/503": (b"", 503),
            "/lento": (b'{"status":"ok"}', 200),
        }[self.path]
        self.send_response(codigo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        Falso.recebidos.append(json.loads(self.rfile.read(tamanho).decode("utf-8")))
        self.send_response(Falso.ntfy_status)
        self.send_header("Content-Length", "0")
        self.end_headers()


Falso.agentes = []
servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Falso)
servidor.handle_error = lambda *args: None
threading.Thread(target=servidor.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{servidor.server_port}"
for caminho, resposta in [
    ("/ok", (True, "ok")), ("/ir", (True, "ok")), ("/html", (False, "resposta fora do formato")),
    ("/fora", (False, "status diferente de ok")), ("/401", (False, "http 401")), ("/404", (False, "http 404")),
    ("/500", (False, "http 500")), ("/502", (False, "http 502")), ("/503", (False, "http 503")),
]:
    confere(s.conferir(base + caminho) == resposta, f"rede {caminho}")
confere(s.conferir(base + "/lixo")[0] is False, "resposta que nao e http")
confere(s.conferir(base + "/corta")[0] is False, "resposta cortada no meio")
confere(s.conferir(base + "/lento", tempo_limite=0.3)[0] is False, "rede demorada")
confere(s.conferir(base + "/lento", tempo_limite=5)[0] is True, "rede lenta dentro do limite")
confere(Falso.agentes[0] == s.AGENTE, "agente identificado")
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
porta_morta = sock.getsockname()[1]
sock.close()
confere(s.conferir(f"http://127.0.0.1:{porta_morta}/")[0] is False, "porta fechada")
confere(s.conferir("http://nao-existe.invalid/", tempo_limite=3)[0] is False, "endereco inexistente")
confere(s.conferir("isto nao e endereco")[0] is False, "endereco invalido")

# 9. Rodada inteira: arquivo de estado, envio e silencio do canal na saida.
s.NTFY = base + "/"
s.time.sleep = lambda _: None
pasta = tempo = tempfile.mkdtemp()
arquivo = os.path.join(pasta, "sub", "estado.json")
os.environ.update(SENTINELA_ESTADO=arquivo, NTFY_TOPICO=TOPICO, SENTINELA_ROTULO="")


def rodada(caminho, minutos=0):
    os.environ["SENTINELA_URL"] = base + caminho
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(saida):
        codigo = s.principal(COMECO + timedelta(minutes=minutos))
    confere(TOPICO not in saida.getvalue(), "canal fora da saida")
    return codigo


confere(rodada("/ok") == 0 and not Falso.recebidos, "ok em silencio")
confere(rodada("/502", 5) == 0 and not Falso.recebidos, "1 falha nao avisa")
confere(rodada("/502", 10) == 0 and len(Falso.recebidos) == 1, "2 falhas avisam")
pedido = Falso.recebidos[0]
confere(pedido["topic"] == TOPICO and pedido["priority"] == 5, "canal e urgencia no envio")
confere(pedido["title"] == "PROBLEMA NOSSO — plataforma fora do ar desde 09:02", "acento e travessao no envio")
confere(rodada("/500", 15) == 0 and len(Falso.recebidos) == 1, "nao repete")
Falso.ntfy_status = 500
confere(rodada("/ok", 20) == 1, "volta que nao saiu termina com erro")
Falso.ntfy_status = 200
Falso.recebidos.clear()
confere(rodada("/ok", 25) == 0 and len(Falso.recebidos) == 1, "volta sai na rodada seguinte")
confere("voltou às 09:17" in Falso.recebidos[0]["title"], "volta com a hora em que voltou")
Falso.recebidos.clear()
confere(rodada("/ok", 30) == 0 and not Falso.recebidos, "volta nao repete")
Falso.ntfy_status = 503
confere(rodada("/502", 35) == 0 and rodada("/502", 40) == 1, "queda que nao saiu termina com erro")
Falso.ntfy_status = 200
Falso.recebidos.clear()
confere(rodada("/502", 45) == 0 and len(Falso.recebidos) == 1, "queda sai na rodada seguinte")
confere("desde 09:32" in Falso.recebidos[0]["title"], "queda pendente mantem o inicio")
rodada("/ok", 50)
os.environ["NTFY_TOPICO"] = ""
confere(rodada("/ok", 55) == 1, "sem canal termina com erro")
os.environ["NTFY_TOPICO"] = TOPICO

# 10. Estado estragado nao derruba a rodada.
for ruim in ["", "{", "[]", "null", "42", '{"falhas":1}', '{"falhas":"x","desde":null,"avisado":false,"voltou_em":null}',
             '{"falhas":1,"desde":"ontem","avisado":false,"voltou_em":null}',
             '{"falhas":2,"desde":null,"avisado":true,"voltou_em":null}']:
    with open(arquivo, "w", encoding="utf-8") as f:
        f.write(ruim)
    confere(s.ler_estado(arquivo) == s.ESTADO_LIMPO, f"estado estragado {ruim}")
    confere(rodada("/ok") == 0, f"rodada com estado estragado {ruim}")
confere(s.ler_estado(os.path.join(pasta, "nao-existe.json")) == s.ESTADO_LIMPO, "sem estado")

servidor.shutdown()
print(f"testes: {contagem['ok']} certos, {contagem['falhou']} errados")
for nome in falhas[:20]:
    print("ERRO:", nome)
sys.exit(1 if contagem["falhou"] else 0)
