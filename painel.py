#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilitário do Painel de Cargas — GTFOODS.

Os dados das cargas ficam dentro do próprio index.html (no bloco
`const viagens = [ ... ];`). Este script cuida de tirar e colocar esses dados
sem precisar mexer no HTML na mão.

COMANDOS
--------

  python3 painel.py exportar
      Tira as cargas que estão hoje no index.html e grava em viagens.json.
      Use para ter um ponto de partida antes de editar.

  python3 painel.py atualizar viagens.json
      Coloca as cargas do arquivo JSON dentro do index.html, recalcula os totais
      de cada carga e sobe a versão do cache do aplicativo (sw.js), para que os
      celulares baixem a versão nova.

      Opções:
        --sem-recalculo   mantém entregas/totalCx/totalKg como estão no JSON
        --sem-backup      não gera o arquivo .bak antes de sobrescrever

  python3 painel.py senha "MinhaNovaSenha"
      Troca a senha do modo administrador (grava só o hash no index.html).

  python3 painel.py conferir
      Mostra um resumo das cargas que estão no index.html hoje.

FORMATO DO viagens.json
-----------------------------
[
  {
    "numero": "5001086",
    "transportadora": "CARDOZO TRANSPORTES LTDA",
    "motorista": "LUIZ CLAUDIO CARDOZO",
    "data": "11/09/2026",
    "hora": "17:22",
    "placa": "APZ7814",
    "pedidos": [
      {
        "codigo": "003774",
        "cliente": "COMPANHIA SULAMERICANA DE DISTRIBUICAO",
        "cidade": "PAICANDU/PR",
        "obs": "opcional — aparece em amarelo no painel",
        "itens": [
          ["FRASCANMI000037", "CARNE RESFRIADA DE FRANGO ASA PV CX 20 KG", 40.0, 800.0]
        ]
      }
    ]
  }
]

Cada item é [codigo, descricao, caixas, quilos].
Os campos "entregas", "totalCx" e "totalKg" podem ser omitidos: o script calcula.
"""

import argparse
import json
import pathlib
import re
import shutil
import sys
import hashlib
from datetime import datetime

RAIZ = pathlib.Path(__file__).resolve().parent
INDEX = RAIZ / "index.html"
SW = RAIZ / "sw.js"
JSON_PADRAO = RAIZ / "viagens.json"

ABRE = "const viagens = ["
FECHA = "\n];"


# --------------------------------------------------------------------------- utilidades
def erro(msg):
    print(f"ERRO: {msg}", file=sys.stderr)
    sys.exit(1)


def ler_index():
    if not INDEX.exists():
        erro(f"não encontrei {INDEX}")
    return INDEX.read_text(encoding="utf-8")


def localizar_bloco(html):
    """Devolve (inicio, fim) das posições do bloco de dados dentro do HTML."""
    i = html.find(ABRE)
    if i == -1:
        erro("não encontrei o bloco 'const viagens = [' no index.html")
    j = html.find(FECHA, i)
    if j == -1:
        erro("não encontrei o fim do bloco de dados no index.html")
    return i, j + len(FECHA)


def js_para_json(trecho):
    """Converte o array JavaScript do painel em estrutura Python.

    O bloco usa chaves sem aspas (numero:"...") e aspas duplas nos valores,
    então basta colocar aspas nas chaves para virar JSON válido.
    """
    corpo = trecho[len(ABRE) - 1 :]  # começa no "[" que abre a lista
    if corpo.endswith(FECHA):
        corpo = corpo[: -len(FECHA)] + "]"  # troca o "\n];" final por "]"
    corpo = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', corpo)
    corpo = re.sub(r",(\s*[}\]])", r"\1", corpo)  # vírgula sobrando antes de } ou ]
    try:
        return json.loads(corpo)
    except json.JSONDecodeError as e:
        erro(f"não consegui interpretar os dados do index.html: {e}")


def esc(texto):
    """Escapa um texto para virar string JavaScript entre aspas duplas."""
    return (
        str(texto)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("</", "<\\/")  # nunca fechar a tag <script> por acidente
    )


def num(valor):
    """Formata número no estilo do arquivo original, sem perder casas decimais.

    6651 -> "6651.0"   |   200.5 -> "200.5"   |   50.25 -> "50.25"
    """
    f = round(float(valor), 3)
    if f == int(f):
        return f"{int(f)}.0"
    return f"{f:.3f}".rstrip("0")


# --------------------------------------------------------------------------- validação
def validar(viagens):
    if not isinstance(viagens, list) or not viagens:
        erro("o JSON precisa ser uma lista com pelo menos uma viagem")

    vistos = set()
    problemas = []

    for iv, v in enumerate(viagens, 1):
        onde = f"viagem #{iv}"
        if not isinstance(v, dict):
            problemas.append(f"{onde}: deveria ser um objeto")
            continue
        # 'placa' é opcional: nem toda versão do romaneio traz esse campo
        for campo in ("numero", "transportadora", "motorista", "data", "hora"):
            if not str(v.get(campo, "")).strip():
                problemas.append(f"{onde}: falta o campo '{campo}'")
        numero = str(v.get("numero", "")).strip()
        onde = f"viagem {numero or iv}"
        if numero in vistos:
            problemas.append(f"{onde}: número de viagem repetido")
        vistos.add(numero)

        data = str(v.get("data", ""))
        if data and not re.fullmatch(r"\d{2}/\d{2}/\d{4}", data):
            problemas.append(f"{onde}: data '{data}' fora do formato DD/MM/AAAA")
        hora = str(v.get("hora", ""))
        if hora and not re.fullmatch(r"\d{2}:\d{2}", hora):
            problemas.append(f"{onde}: hora '{hora}' fora do formato HH:MM")

        pedidos = v.get("pedidos")
        if not isinstance(pedidos, list) or not pedidos:
            problemas.append(f"{onde}: precisa ter ao menos um pedido")
            continue

        for ip, p in enumerate(pedidos, 1):
            ondep = f"{onde}, pedido #{ip}"
            if not isinstance(p, dict):
                problemas.append(f"{ondep}: deveria ser um objeto")
                continue
            for campo in ("codigo", "cliente", "cidade"):
                if not str(p.get(campo, "")).strip():
                    problemas.append(f"{ondep}: falta o campo '{campo}'")
            itens = p.get("itens")
            if not isinstance(itens, list) or not itens:
                problemas.append(f"{ondep}: precisa ter ao menos um item")
                continue
            for ii, it in enumerate(itens, 1):
                ondei = f"{ondep}, item #{ii}"
                if not isinstance(it, (list, tuple)) or len(it) != 4:
                    problemas.append(f"{ondei}: deve ser [codigo, descricao, caixas, quilos]")
                    continue
                for pos, nome in ((2, "caixas"), (3, "quilos")):
                    try:
                        if float(it[pos]) < 0:
                            problemas.append(f"{ondei}: {nome} negativo")
                    except (TypeError, ValueError):
                        problemas.append(f"{ondei}: {nome} '{it[pos]}' não é número")

    if problemas:
        print(f"Encontrei {len(problemas)} problema(s) no JSON:\n", file=sys.stderr)
        for p in problemas[:40]:
            print(f"  - {p}", file=sys.stderr)
        if len(problemas) > 40:
            print(f"  ... e mais {len(problemas) - 40}.", file=sys.stderr)
        sys.exit(1)


def normalizar(viagens):
    """Deixa todos os números no mesmo tipo (caixas/quilos como decimal),
    para que o arquivo gravado possa ser comparado com o que foi lido."""
    for v in viagens:
        v["placa"] = str(v.get("placa", "")).strip()
        # campos opcionais da planilha de carregamento
        if v.get("ordem") in (None, "", 0):
            v.pop("ordem", None)
        else:
            v["ordem"] = int(v["ordem"])
        for campo in ("chegada", "regiao"):
            if str(v.get(campo, "")).strip():
                v[campo] = str(v[campo]).strip()
            else:
                v.pop(campo, None)
        v["entregas"] = int(v.get("entregas", len(v["pedidos"])))
        v["totalCx"] = round(float(v.get("totalCx", 0)), 3)
        v["totalKg"] = round(float(v.get("totalKg", 0)), 3)
        for p in v["pedidos"]:
            if not str(p.get("obs", "")).strip():
                p.pop("obs", None)
            p["itens"] = [
                [str(it[0]), str(it[1]), round(float(it[2]), 3), round(float(it[3]), 3)]
                for it in p["itens"]
            ]
    return viagens


def recalcular(viagens):
    for v in viagens:
        cx = kg = 0.0
        for p in v["pedidos"]:
            for it in p["itens"]:
                cx += float(it[2])
                kg += float(it[3])
        v["entregas"] = len(v["pedidos"])
        v["totalCx"] = round(cx, 3)
        v["totalKg"] = round(kg, 3)
    return viagens


# --------------------------------------------------------------------------- geração
def gerar_js(viagens):
    linhas = [ABRE]
    for iv, v in enumerate(viagens):
        # campos opcionais, vindos da planilha de carregamento
        extra = ""
        if v.get("ordem"):
            extra += f'ordem:{int(v["ordem"])},'
        if str(v.get("chegada", "")).strip():
            extra += f'chegada:"{esc(v["chegada"])}",'
        if str(v.get("regiao", "")).strip():
            extra += f'regiao:"{esc(v["regiao"])}",'
        cab = (
            f'{{numero:"{esc(v["numero"])}",'
            f'transportadora:"{esc(v["transportadora"])}",'
            f'motorista:"{esc(v["motorista"])}",'
            f'data:"{esc(v["data"])}",'
            f'hora:"{esc(v["hora"])}",'
            f'placa:"{esc(v["placa"])}",'
            + extra +
            f'entregas:{int(v["entregas"])},'
            f'totalCx:{num(v["totalCx"])},'
            f'totalKg:{num(v["totalKg"])},pedidos:['
        )
        linhas.append(cab)
        for ip, p in enumerate(v["pedidos"]):
            obs = f',obs:"{esc(p["obs"])}"' if str(p.get("obs", "")).strip() else ""
            linhas.append(
                f'  {{codigo:"{esc(p["codigo"])}",'
                f'cliente:"{esc(p["cliente"])}",'
                f'cidade:"{esc(p["cidade"])}"{obs},itens:['
            )
            for ii, it in enumerate(p["itens"]):
                fim = "]}" if ii == len(p["itens"]) - 1 else ","
                if ii == len(p["itens"]) - 1 and ip < len(v["pedidos"]) - 1:
                    fim = "]},"
                linhas.append(f'    ["{esc(it[0])}","{esc(it[1])}",{num(it[2])},{num(it[3])}{"]" + fim}')
        linhas.append("]}" + ("," if iv < len(viagens) - 1 else ""))
    linhas.append("];")
    return "\n".join(linhas)


def subir_versao_sw():
    """Incrementa painel-cargas-vN em sw.js para forçar atualização nos aparelhos."""
    if not SW.exists():
        print("  aviso: sw.js não encontrado, versão do cache não foi alterada.")
        return None
    txt = SW.read_text(encoding="utf-8")
    # aceita os dois formatos: CACHE = "nome-vN"  ou  CACHE = PREFIXO + "vN"
    m = re.search(r'const CACHE = PREFIXO \+ "v(\d+)";', txt)
    if m:
        nova = int(m.group(1)) + 1
        SW.write_text(txt.replace(m.group(0), f'const CACHE = PREFIXO + "v{nova}";'), encoding="utf-8")
        return nova
    m = re.search(r'const CACHE = "([a-z-]*)v(\d+)";', txt)
    if not m:
        print("  aviso: não achei a versão do cache em sw.js.")
        return None
    nova = int(m.group(2)) + 1
    SW.write_text(
        txt.replace(m.group(0), f'const CACHE = "{m.group(1)}v{nova}";'), encoding="utf-8"
    )
    return nova


def br(valor):
    """Formata número no padrão brasileiro: 115.807,9"""
    return f"{float(valor):,.1f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def resumo(viagens):
    cx = sum(float(v["totalCx"]) for v in viagens)
    kg = sum(float(v["totalKg"]) for v in viagens)
    ent = sum(int(v["entregas"]) for v in viagens)
    itens = sum(len(p["itens"]) for v in viagens for p in v["pedidos"])
    datas = sorted({v["data"] for v in viagens}, key=lambda d: d.split("/")[::-1])
    print(f"  {len(viagens)} viagens · {ent} entregas · {itens} itens")
    print(f"  {br(cx)} caixas · {br(kg)} kg")
    print(f"  data(s): {', '.join(datas)}")


# --------------------------------------------------------------------------- comandos
def cmd_exportar(args):
    html = ler_index()
    i, j = localizar_bloco(html)
    viagens = js_para_json(html[i:j])
    destino = pathlib.Path(args.saida) if args.saida else JSON_PADRAO
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(viagens, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Exportado para {destino.relative_to(RAIZ)}")
    resumo(viagens)


def cmd_atualizar(args):
    origem = pathlib.Path(args.arquivo)
    if not origem.exists():
        erro(f"não encontrei o arquivo {origem}")
    try:
        viagens = json.loads(origem.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        erro(f"o arquivo {origem} não é um JSON válido: {e}")

    validar(viagens)
    if not args.sem_recalculo:
        recalcular(viagens)
    normalizar(viagens)

    html = ler_index()
    i, j = localizar_bloco(html)
    antigas = js_para_json(html[i:j])

    if not args.sem_backup:
        bak = INDEX.with_suffix(f".html.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(INDEX, bak)
        print(f"Backup: {bak.name}")

    INDEX.write_text(html[:i] + gerar_js(viagens) + html[j:], encoding="utf-8")

    # confere se o que ficou gravado é lido de volta exatamente igual
    novo = ler_index()
    ni, nj = localizar_bloco(novo)
    conferido = js_para_json(novo[ni:nj])
    if json.dumps(conferido, sort_keys=True) != json.dumps(viagens, sort_keys=True):
        erro("a gravação não bateu com o esperado — restaure o backup (.bak).")

    print(f"\nAntes:  {len(antigas)} viagens")
    print(f"Depois: {len(viagens)} viagens\n")
    resumo(viagens)

    nova = subir_versao_sw()
    if nova:
        print(f"\n  cache do aplicativo: painel-cargas-v{nova}")
    print("\nPronto. Agora é só enviar para o GitHub:")
    print("  git add -A && git commit -m 'Atualiza cargas' && git push")


def cmd_senha(args):
    nova = args.senha
    if len(nova) < 8:
        erro("use uma senha com pelo menos 8 caracteres.")
    h = hashlib.sha256(nova.encode("utf-8")).hexdigest()
    html = ler_index()
    m = re.search(r'const ADMIN_PASSWORD_HASH = "([0-9a-f]{64})";', html)
    if not m:
        erro("não encontrei ADMIN_PASSWORD_HASH no index.html")
    INDEX.write_text(html.replace(m.group(0), f'const ADMIN_PASSWORD_HASH = "{h}";'), encoding="utf-8")
    subir_versao_sw()
    print("Senha do modo administrador trocada.")
    print("Guarde-a: o index.html só tem o hash, não dá para recuperar a senha a partir dele.")


def cmd_cortes(args):
    """Injeta a planilha de corte do dia no index.html."""
    origem = pathlib.Path(args.arquivo)
    if not origem.exists():
        erro(f"não encontrei o arquivo {origem}")
    try:
        c = json.loads(origem.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        erro(f"{origem} não é um JSON válido: {e}")

    for campo in ("linhas", "totalCorte", "kgDescontar"):
        if campo not in c:
            erro(f"falta o campo '{campo}' no arquivo de cortes")

    html = ler_index()
    m = re.search(r"^const cortes = .*?;$", html, re.M)
    if not m:
        erro("não encontrei a linha 'const cortes = ...' no index.html")
    novo = "const cortes = " + json.dumps(c, ensure_ascii=False, separators=(",", ":")) + ";"
    INDEX.write_text(html[: m.start()] + novo + html[m.end():], encoding="utf-8")

    print(f"{len(c['linhas'])} linhas de corte publicadas")
    print(f"  {br(c['totalCorte'])} kg cortados · {br(c['kgDescontar'])} kg a descontar do peso do romaneio")
    print(f"  {sum(1 for l in c['linhas'] if l.get('viagem'))} com viagem identificada")
    subir_versao_sw()


def cmd_conferir(args):
    html = ler_index()
    i, j = localizar_bloco(html)
    viagens = js_para_json(html[i:j])
    print("Cargas hoje no index.html:")
    resumo(viagens)
    dif = []
    for v in viagens:
        cx = sum(float(it[2]) for p in v["pedidos"] for it in p["itens"])
        kg = sum(float(it[3]) for p in v["pedidos"] for it in p["itens"])
        if abs(cx - float(v["totalCx"])) > 0.05 or abs(kg - float(v["totalKg"])) > 0.05:
            dif.append(v["numero"])
        if int(v["entregas"]) != len(v["pedidos"]):
            dif.append(v["numero"])
    if dif:
        print(f"\n  atenção: totais divergentes em {len(set(dif))} viagem(ns): {', '.join(sorted(set(dif)))}")
        print("  rode 'exportar' e depois 'atualizar' para recalcular.")
    else:
        print("\n  totais conferem com a soma dos itens.")


def main():
    ap = argparse.ArgumentParser(
        description="Utilitário do Painel de Cargas — GTFOODS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("exportar", help="tira as cargas do index.html e grava em JSON")
    e.add_argument("saida", nargs="?", help="arquivo de saída (padrão: viagens.json)")
    e.set_defaults(func=cmd_exportar)

    a = sub.add_parser("atualizar", help="coloca as cargas de um JSON dentro do index.html")
    a.add_argument("arquivo", help="JSON com as cargas")
    a.add_argument("--sem-recalculo", action="store_true", help="não recalcular totais")
    a.add_argument("--sem-backup", action="store_true", help="não gerar arquivo .bak")
    a.set_defaults(func=cmd_atualizar)

    s = sub.add_parser("senha", help="troca a senha do modo administrador")
    s.add_argument("senha", help="a nova senha, entre aspas")
    s.set_defaults(func=cmd_senha)

    ct = sub.add_parser("cortes", help="injeta a planilha de corte do dia no painel")
    ct.add_argument("arquivo", help="JSON com os cortes")
    ct.set_defaults(func=cmd_cortes)

    c = sub.add_parser("conferir", help="mostra um resumo das cargas publicadas")
    c.set_defaults(func=cmd_conferir)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
