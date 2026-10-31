#!/usr/bin/env python3
"""Sentinela externa: confere um endereco e avisa o celular pelo ntfy.

Duas falhas seguidas = aviso de queda, uma vez so. Primeira conferencia boa
depois do aviso = aviso de volta, uma vez so. Aviso que nao saiu fica pendente
para a proxima rodada e a rodada termina com erro.
"""
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BRT = timezone(timedelta(hours=-3))
FALHAS_PARA_AVISAR = 2
TEMPO_LIMITE = 20
AGENTE = "tms-cortex-sentinela/1.0"
NTFY = "https://ntfy.sh/"
ESTADO_LIMPO = {"falhas": 0, "desde": None, "avisado": False, "voltou_em": None}


def avaliar(status, corpo):
    """Retorna (ok, motivo). So vale 200 com "status":"ok" em JSON."""
    if status != 200:
        return False, f"http {status}"
    try:
        dados = json.loads(corpo)
    except (ValueError, TypeError):
        return False, "resposta fora do formato"
    if not isinstance(dados, dict) or dados.get("status") != "ok":
        return False, "status diferente de ok"
    return True, "ok"


def conferir(url, tempo_limite=TEMPO_LIMITE):
    try:
        pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE})
        with urllib.request.urlopen(pedido, timeout=tempo_limite) as resposta:
            return avaliar(resposta.status, resposta.read(65536))
    except urllib.error.HTTPError as erro:
        return False, f"http {erro.code}"
    except (OSError, ValueError, http.client.HTTPException) as erro:
        return False, f"sem resposta ({type(erro).__name__})"


def _hora(momento, agora):
    texto = momento.strftime("%H:%M")
    if momento.date() != agora.date():
        texto += momento.strftime(" de %d/%m")
    return texto


def _duracao(inicio, fim):
    minutos = int((fim - inicio).total_seconds() // 60)
    if minutos < 60:
        return f"{minutos} min"
    return f"{minutos // 60}h{minutos % 60:02d}"


def decidir(estado, ok, motivo, agora, rotulo=""):
    """Retorna (estado se o aviso saiu, estado se nao saiu, aviso ou None)."""
    desde = datetime.fromisoformat(estado["desde"]) if estado["desde"] else None
    if ok:
        if not estado["avisado"]:
            return dict(ESTADO_LIMPO), dict(ESTADO_LIMPO), None
        voltou = datetime.fromisoformat(estado["voltou_em"]) if estado["voltou_em"] else agora
        aviso = {
            "titulo": f"{rotulo}PROBLEMA NOSSO RESOLVIDO — plataforma voltou às {_hora(voltou, agora)}",
            "texto": f"Ficou fora desde {_hora(desde, agora)} ({_duracao(desde, voltou)}). Conferido de fora do servidor.",
            "prioridade": 3,
        }
        return dict(ESTADO_LIMPO), {**estado, "voltou_em": voltou.isoformat()}, aviso

    novo = {
        "falhas": estado["falhas"] + 1,
        "desde": (desde or agora).isoformat(),
        "avisado": estado["avisado"],
        "voltou_em": None,
    }
    if novo["falhas"] < FALHAS_PARA_AVISAR or novo["avisado"]:
        return novo, novo, None
    aviso = {
        "titulo": f"{rotulo}PROBLEMA NOSSO — plataforma fora do ar desde {_hora(desde or agora, agora)}",
        "texto": f"O que fazer: abrir o painel da Hostinger e ver o servidor. Conferido de fora do servidor, 2 vezes seguidas ({motivo}).",
        "prioridade": 5,
    }
    return {**novo, "avisado": True}, novo, aviso


def enviar(topico, aviso, tentativas=3, espera=5):
    corpo = json.dumps(
        {"topic": topico, "title": aviso["titulo"], "message": aviso["texto"], "priority": aviso["prioridade"]}
    ).encode("utf-8")
    for tentativa in range(tentativas):
        pedido = urllib.request.Request(
            NTFY, data=corpo, headers={"Content-Type": "application/json", "User-Agent": AGENTE}
        )
        try:
            with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE) as resposta:
                if resposta.status == 200:
                    return True
        except (OSError, ValueError, http.client.HTTPException) as erro:
            print(f"aviso nao saiu ({type(erro).__name__})")
        if tentativa + 1 < tentativas:
            time.sleep(espera)
    return False


def ler_estado(caminho):
    try:
        with open(caminho, encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        estado = {
            "falhas": int(dados["falhas"]),
            "desde": dados["desde"],
            "avisado": bool(dados["avisado"]),
            "voltou_em": dados["voltou_em"],
        }
        for campo in ("desde", "voltou_em"):
            if estado[campo]:
                datetime.fromisoformat(estado[campo])
        if estado["avisado"] and not estado["desde"]:
            return dict(ESTADO_LIMPO)
        return estado
    except (OSError, ValueError, KeyError, TypeError):
        return dict(ESTADO_LIMPO)


def gravar_estado(caminho, estado):
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as arquivo:
        json.dump(estado, arquivo)


def principal(agora=None):
    url = os.environ["SENTINELA_URL"]
    caminho = os.environ["SENTINELA_ESTADO"]
    rotulo = os.environ.get("SENTINELA_ROTULO", "")
    topico = os.environ.get("NTFY_TOPICO", "")
    agora = agora or datetime.now(BRT)

    estado = ler_estado(caminho)
    ok, motivo = conferir(url)
    print(f"conferido: {'ok' if ok else 'falha'} ({motivo})")
    saiu_estado, ficou_estado, aviso = decidir(estado, ok, motivo, agora, rotulo)

    if not topico:
        gravar_estado(caminho, ficou_estado)
        print("canal de aviso nao configurado")
        return 1
    if aviso is None:
        gravar_estado(caminho, saiu_estado)
        return 0
    if enviar(topico, aviso):
        gravar_estado(caminho, saiu_estado)
        print("aviso enviado")
        return 0
    gravar_estado(caminho, ficou_estado)
    print("aviso pendente para a proxima rodada")
    return 1


if __name__ == "__main__":
    sys.exit(principal())
