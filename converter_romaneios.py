#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Conversor de romaneios — Painel de Cargas GTFOODS.

Lê os PDFs do SIGA (Relatório de Ordem de Carregamento, v.12), um por viagem,
e grava o viagens.json que o painel.py entende.

USO
---

  python converter_romaneios.py <pdf ou pasta> [...] -o viagens.json

A leitura usa o `pdftohtml -xml` do Poppler, e não o `pdftotext`: o XML traz
cada trecho do PDF na ordem em que foi escrito e com a fonte usada, o que
separa sem ambiguidade o cabeçalho do cliente e a OBS (negrito), os códigos e
números (Courier) e a descrição do produto (Arial). Com o texto em colunas,
uma OBS longa se mistura com a linha do produto e as colunas embaralham.

A TRAVA
-------
Cada romaneio traz no rodapé `Qtde. de Entregas`, `CX:` e `KG:`. Se a soma do
que foi lido não bater com o impresso, o conversor para com erro e NÃO grava
nada. Qualquer trecho que não se encaixe no formato conhecido também para.

CIDADES
-------
O cabeçalho do pedido vem como `CODIGO - CLIENTE  CIDADE/UF`. A cidade é
conferida contra o cidades.txt, que tem só municípios reais (lista do IBGE).
Cidade desconhecida faz o conversor parar. Nunca acrescente ao cidades.txt
nomes tirados dos romaneios sem confirmar que o município existe.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET

RAIZ = pathlib.Path(__file__).resolve().parent
CIDADES = RAIZ / "cidades.txt"

NUM = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d+$")
CANCAO = re.compile(r"^\d{1,6}$")
PRODUTO = re.compile(r"^[A-Z]{3,}[A-Z0-9]*\d{3,}$")
PEDIDO = re.compile(r"^(\d{6}) - (.+)$")
DATA_HORA = re.compile(r"^(\d{4})(\d{2})(\d{2}) (\d{2}:\d{2})$")
CIDADE_UF = re.compile(r"^[A-Z][A-Z .'-]*/[A-Z]{2}$")
FIM_TRANSP = re.compile(r"^(.*?\b(?:LTDA|S/A|S\.A\.?|ME|EIRELI|CIA)\.?)\s+(\S.*)$")
CABECALHO_PAGINA = re.compile(
    r"^(Folha:|SIGA/|Relatório de Ordem de Carregamento|Dt\.Ref:|Hora: \d|Emissão:|Grupo de Empresa:)"
)
TITULOS = {
    "Viagem", "Transportadora", "Motorista", "Placa", "Data", "Hora",
    "Cancao", "Produto", "Descricao Produto", "CX", "KG", "Carreg",
}
TRACOS = "_____/_____"


class ErroRomaneio(Exception):
    pass


def br_num(txt):
    return float(txt.replace(".", "").replace(",", "."))


def espacos(txt):
    return re.sub(r"\s+", " ", txt).strip()


# --------------------------------------------------------------------------- cidades
def carregar_cidades():
    if not CIDADES.exists():
        sys.exit(f"ERRO: não encontrei {CIDADES}")
    return {
        l.strip() for l in CIDADES.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.startswith("#")
    }


def sem_acento(txt):
    return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()


def separar_cidade(resto, cidades):
    """'SUPERMERCADO X LTDA  LONDRINA/PR' -> ('SUPERMERCADO X LTDA', 'LONDRINA/PR').

    A cidade é conferida sem acento (o SIGA às vezes imprime UBIRATÃ/PR), mas
    fica gravada como veio no romaneio."""
    partes = re.split(r"\s{2,}", resto.strip())
    if len(partes) >= 2 and sem_acento(espacos(partes[-1])) in cidades:
        return espacos(" ".join(partes[:-1])), espacos(partes[-1])
    # sem o espaço duplo: casa o sufixo mais longo contra a lista de municípios
    palavras = espacos(resto).split(" ")
    for i in range(1, len(palavras)):
        cand = " ".join(palavras[i:])
        if sem_acento(cand) in cidades:
            return " ".join(palavras[:i]), cand
    raise ErroRomaneio(f"cidade não reconhecida no pedido: '{espacos(resto)}'")


# --------------------------------------------------------------------------- leitura do PDF
def trechos(pdf):
    """Devolve [(tipo, texto)] na ordem do PDF. tipo: 'b' negrito, 'c' Courier, 'a' Arial."""
    try:
        r = subprocess.run(
            ["pdftohtml", "-xml", "-i", "-q", "-enc", "UTF-8", "-stdout", str(pdf)],
            capture_output=True, check=True,
        )
    except FileNotFoundError:
        sys.exit("ERRO: pdftohtml não encontrado (instale o Poppler).")
    except subprocess.CalledProcessError as e:
        raise ErroRomaneio(f"pdftohtml falhou: {e.stderr.decode('utf-8', 'replace').strip()}")

    raiz = ET.fromstring(r.stdout)
    fontes = {}
    saida = []
    for pagina in raiz.iter("page"):
        for el in pagina:
            if el.tag == "fontspec":
                fontes[el.get("id")] = el.get("family", "")
            elif el.tag == "text":
                texto = "".join(el.itertext())
                if not texto.strip():
                    continue
                if el.find("b") is not None:
                    tipo = "b"
                elif "Courier" in fontes.get(el.get("font"), ""):
                    tipo = "c"
                else:
                    tipo = "a"
                texto = texto.strip()
                # número e linha de conferência às vezes vêm num trecho só:
                # '1.000,0 _____/_____' -> '1.000,0', '_____/_____'
                if tipo == "c" and re.fullmatch(r"[\d.,]+(?:\s+[\d.,]+)*\s+_+/_+", texto):
                    saida += [("c", t) for t in texto.split()]
                else:
                    saida.append((tipo, texto))
    return saida


def converter(pdf, cidades):
    # os títulos de coluna saem em Courier/negrito; em Arial só "Descricao
    # Produto" é título — um "KG" em Arial é o fim de uma descrição quebrada
    seq = [
        (t, x) for t, x in trechos(pdf)
        if not CABECALHO_PAGINA.match(x)
        and not (x in TITULOS and (t != "a" or x == "Descricao Produto"))
    ]
    viagem = None
    cab = []           # trechos entre o número da viagem e a data
    pedidos = []
    pedido = item = None
    numeros = []
    fechado = True     # o item atual já passou pelo _____/_____
    rodape = {}

    def fechar_item():
        nonlocal item
        if item is None:
            return
        if not fechado:
            raise ErroRomaneio(f"item {item['codigo']} sem a linha de conferência (_____/_____)")
        pedido["itens"].append([item["codigo"], espacos(" ".join(item["desc"])), item["cx"], item["kg"]])
        item = None

    i = 0
    while i < len(seq):
        tipo, x = seq[i]
        i += 1

        # ---- cabeçalho da viagem
        if viagem is None:
            if tipo == "b" and re.fullmatch(r"\d{7}", x):
                viagem = {"numero": x}
            continue
        if "data" not in viagem:
            m = DATA_HORA.match(x)
            if m:
                viagem["data"] = f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
                viagem["hora"] = m.group(4)
                if len(cab) == 2:
                    viagem["transportadora"], viagem["motorista"] = map(espacos, cab)
                elif len(cab) == 1 and FIM_TRANSP.match(espacos(cab[0])):
                    m2 = FIM_TRANSP.match(espacos(cab[0]))
                    viagem["transportadora"], viagem["motorista"] = m2.group(1), m2.group(2)
                else:
                    raise ErroRomaneio(f"cabeçalho da viagem fora do padrão: {cab}")
            else:
                cab.append(x)
            continue

        # ---- rodapé
        if tipo == "b" and x.startswith("Qtde. de Entregas"):
            fechar_item()
            rodape["entregas"] = int(re.sub(r"\D", "", x))
            continue
        if "entregas" in rodape:
            m = re.fullmatch(r"(CX|KG):\s*([\d.,]+)", x)
            if m:
                rodape[m.group(1)] = br_num(m.group(2))
            if "CX" in rodape and "KG" in rodape:
                break
            continue

        # ---- cabeçalho do pedido e OBS
        m = PEDIDO.match(x) if tipo == "b" else None
        if m:
            fechar_item()
            cliente, cidade = separar_cidade(m.group(2), cidades)
            pedido = {"codigo": m.group(1), "cliente": cliente, "cidade": cidade, "itens": []}
            pedidos.append(pedido)
            continue
        if tipo == "b":
            if pedido is None or pedido["itens"] or item is not None:
                raise ErroRomaneio(f"texto em negrito fora do lugar: '{x}'")
            if x.startswith("OBS:"):
                pedido["obs"] = espacos(x[4:])
            elif "obs" in pedido:
                pedido["obs"] = espacos(pedido["obs"] + " " + x)  # OBS quebrada em várias linhas
            else:
                raise ErroRomaneio(f"texto em negrito inesperado no pedido {pedido['codigo']}: '{x}'")
            continue

        # ---- itens
        if tipo == "c" and (PRODUTO.match(x) or (CANCAO.match(x) and i < len(seq) and PRODUTO.match(seq[i][1]))):
            if pedido is None:
                raise ErroRomaneio(f"item antes do primeiro pedido: '{x}'")
            fechar_item()
            if CANCAO.match(x):          # código interno da Canção (opcional)
                x = seq[i][1]
                i += 1
            item = {"codigo": x, "desc": [], "cx": None, "kg": None}
            numeros, fechado = [], False
            continue
        if item is None:
            raise ErroRomaneio(f"trecho fora de um item: '{x}'")
        if tipo == "a":
            item["desc"].append(x)       # descrição, inclusive a que quebra de linha
            continue
        if tipo == "c" and NUM.match(x) and not fechado:
            numeros.append(br_num(x))
            continue
        if tipo == "c" and x == TRACOS and not fechado:
            if len(numeros) != 2:
                raise ErroRomaneio(f"item {item['codigo']}: esperava CX e KG, li {numeros}")
            item["cx"], item["kg"] = numeros
            fechado = True
            continue
        raise ErroRomaneio(f"trecho inesperado no item {item['codigo']}: '{x}'")

    # ---- conferência com o rodapé (a trava)
    if viagem is None or "data" not in viagem:
        raise ErroRomaneio("não achei o cabeçalho da viagem")
    if not {"entregas", "CX", "KG"} <= rodape.keys():
        raise ErroRomaneio("não achei o rodapé com Qtde. de Entregas / CX / KG")
    cx = round(sum(it[2] for p in pedidos for it in p["itens"]), 3)
    kg = round(sum(it[3] for p in pedidos for it in p["itens"]), 3)
    problemas = []
    if len(pedidos) != rodape["entregas"]:
        problemas.append(f"entregas lidas {len(pedidos)} ≠ impresso {rodape['entregas']}")
    if abs(cx - rodape["CX"]) > 0.001:
        problemas.append(f"CX lido {cx} ≠ impresso {rodape['CX']}")
    if abs(kg - rodape["KG"]) > 0.001:
        problemas.append(f"KG lido {kg} ≠ impresso {rodape['KG']}")
    for p in pedidos:
        if not p["itens"]:
            problemas.append(f"pedido {p['codigo']} sem itens")
    if problemas:
        raise ErroRomaneio("divergência com o rodapé: " + "; ".join(problemas))

    viagem.update(placa="", entregas=len(pedidos), totalCx=cx, totalKg=kg, pedidos=pedidos)
    return viagem


def main():
    ap = argparse.ArgumentParser(description="Converte romaneios do SIGA em viagens.json.")
    ap.add_argument("entradas", nargs="+", help="PDFs ou pastas com os PDFs")
    ap.add_argument("-o", "--saida", required=True, help="arquivo JSON de saída")
    args = ap.parse_args()

    pdfs = []
    for e in map(pathlib.Path, args.entradas):
        pdfs += sorted(e.glob("*.pdf")) if e.is_dir() else [e]
    if not pdfs:
        sys.exit("ERRO: nenhum PDF encontrado.")

    cidades = carregar_cidades()
    viagens, erros = [], []
    for pdf in pdfs:
        try:
            v = converter(pdf, cidades)
        except ErroRomaneio as e:
            erros.append(f"{pdf.name}: {e}")
            continue
        if pdf.stem.isdigit() and v["numero"] != pdf.stem:
            erros.append(f"{pdf.name}: o PDF é da viagem {v['numero']}")
        viagens.append(v)

    numeros = [v["numero"] for v in viagens]
    for n in sorted({n for n in numeros if numeros.count(n) > 1}):
        erros.append(f"viagem {n} aparece em mais de um PDF")

    if erros:
        print(f"ERRO: {len(erros)} problema(s) — nada foi gravado.\n", file=sys.stderr)
        for e in erros:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    pathlib.Path(args.saida).write_text(
        json.dumps(viagens, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    ent = sum(v["entregas"] for v in viagens)
    kg = sum(v["totalKg"] for v in viagens)
    print(f"{len(viagens)} viagens · {ent} entregas · {kg:,.1f} kg — todas conferidas com o rodapé.")
    print(f"Gravado em {args.saida}")


if __name__ == "__main__":
    main()
