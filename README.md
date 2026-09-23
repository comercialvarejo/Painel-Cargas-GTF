# Painel de Cargas — GTFOODS Terra Boa Abatedouro

Acompanhamento dos romaneios de carregamento. Funciona como aplicativo no
computador e no celular: abre pelo link, pode ser instalado na tela inicial e
continua abrindo mesmo sem internet (mostrando o último conteúdo carregado).

O status de cada carga (**Veículo chegou na planta**, **Separado**, **Carregado**,
**Faturado**) é sincronizado em tempo real: quando alguém marca no computador,
aparece no celular de todo mundo na hora.

---

## Publicar no GitHub Pages

1. Crie um repositório novo no GitHub (por exemplo `painel-cargas-gtf`).
2. Envie estes arquivos para ele:

   ```bash
   git init
   git add -A
   git commit -m "Painel de cargas"
   git branch -M main
   git remote add origin https://github.com/SEU-USUARIO/painel-cargas-gtf.git
   git push -u origin main
   ```

3. No GitHub, vá em **Settings → Pages**.
4. Em *Source*, escolha **Deploy from a branch**; em *Branch*, escolha **main** e
   a pasta **/ (root)**. Salve.
5. Espere um ou dois minutos. O endereço será:

   ```
   https://SEU-USUARIO.github.io/painel-cargas-gtf/
   ```

Esse é o link para mandar para a equipe.

> **Precisa ser https.** O recurso de instalar como aplicativo e o funcionamento
> offline só valem em `https://` — o GitHub Pages já entrega assim.

---

## Instalar como aplicativo

**Android (Chrome):** abra o link e toque em **Instalar aplicativo** (o botão
aparece ao lado de "Entrar como admin"), ou use o menu ⋮ → *Instalar aplicativo*.

**iPhone / iPad (Safari):** abra o link, toque em **Compartilhar** e depois em
**Adicionar à Tela de Início**. O painel mostra esse aviso sozinho na primeira vez.

**Computador (Chrome / Edge):** clique no ícone de instalar na barra de endereço,
ou no botão **Instalar aplicativo** dentro do painel.

Depois de instalado, o painel abre em janela própria, com ícone igual ao de
qualquer outro aplicativo.

---

## Atualizar as cargas

Os dados ficam dentro do próprio `index.html`. Para trocar as cargas, use o
script — ele valida os dados, refaz os totais e prepara a atualização do app:

```bash
# 1) tira as cargas de hoje para um arquivo editável
python3 painel.py exportar

# 2) edite viagens.json com as cargas novas

# 3) coloca de volta no painel
python3 painel.py atualizar viagens.json

# 4) publica
git add -A && git commit -m "Atualiza cargas" && git push
```

Em um ou dois minutos o GitHub Pages publica, e quem tem o app instalado recebe
a versão nova ao abrir.

### Formato de `viagens.json`

```json
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
        "obs": "opcional — aparece destacado em amarelo",
        "itens": [
          ["FRASCANMI000037", "CARNE RESFRIADA DE FRANGO ASA PV CX 20 KG", 40.0, 800.0]
        ]
      }
    ]
  }
]
```

Cada item é `[código, descrição, caixas, quilos]`.
Os campos `entregas`, `totalCx` e `totalKg` podem ser deixados de fora — o script
calcula somando os itens.

### Outros comandos

```bash
python3 painel.py conferir              # resumo do que está publicado
python3 painel.py senha "NovaSenha123"  # troca a senha do modo admin
```

Cada atualização gera um backup `index.html.bak-AAAAMMDD-HHMMSS` (ignorado pelo
Git). Use `--sem-backup` se não quiser.

---

## Sincronização em tempo real (Firebase)

O status das cargas fica em um Realtime Database do Firebase, no projeto
**`painel-cargas-gtf`**, configurado no final do `index.html`.

Esse projeto é exclusivo deste painel. Um painel que aponte para outro projeto
(ou para outro caminho dentro do mesmo projeto) tem marcações totalmente
independentes — foi exatamente por isso que este projeto foi criado.

O arquivo **`firebase.rules.json`** tem as regras recomendadas do banco. Vale a
pena aplicá-las antes de divulgar o link:

1. Acesse [console.firebase.google.com](https://console.firebase.google.com) e
   abra o projeto.
2. **Realtime Database → aba Regras**.
3. Cole o conteúdo de `firebase.rules.json` (sem a chave `_comentario`) e
   clique em **Publicar**.

Elas mantêm a leitura liberada (o painel lê sem login) mas só aceitam gravação no
caminho exato `cargas/<número da viagem>/<1 a 4>`, com valor `true` ou `false`.
Sem isso, no modo de teste, qualquer pessoa com o link consegue apagar o banco
inteiro ou encher ele de lixo.

Se o Firebase estiver fora do ar ou sem configuração, o painel não trava: ele
passa a guardar os status só no navegador de quem está usando, e avisa isso na
barra do topo.

---

## Segurança — leia antes de divulgar o link

Este repositório é **público**, então vale ser claro sobre o que isso significa:

- **Qualquer pessoa com o link vê as cargas.** Não há login para consultar.
  O `<meta name="robots" content="noindex">` pede ao Google que não indexe a
  página, mas isso não é uma trava — é só um pedido.
- **A senha do admin não é segurança de verdade.** Ela não aparece mais em texto
  puro no código (só o hash SHA-256), mas serve apenas para evitar cliques
  acidentais: quem entender do assunto consegue gravar direto no banco sem passar
  pelo painel. Para impedir isso de fato seria preciso login real
  (Firebase Authentication).
- **Troque a senha antes de divulgar**, com
  `python3 painel.py senha "SuaSenhaNova"`.
- **Nunca coloque no repositório** dados que não possam ser públicos: tabela de
  preços, CNPJ/CPF, contato de motorista, contrato, margem. Os romaneios já
  trazem cliente e cidade — vale conferir se a empresa considera isso divulgável.

Se qualquer um desses pontos for problema, a alternativa é deixar o repositório
**privado**. Nesse caso o GitHub Pages exige plano pago (Pro/Team/Enterprise),
ou dá para hospedar de graça em Netlify ou Cloudflare Pages, com o repositório
privado e o site protegido por senha.

---

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `index.html` | O painel inteiro: layout, código e os dados das cargas |
| `manifest.webmanifest` | Faz o painel ser instalável como aplicativo |
| `sw.js` | Guarda o painel no aparelho (abre offline e mais rápido) |
| `icone-*.png`, `apple-touch-icon.png`, `favicon-32.png` | Ícones do aplicativo |
| `viagens.json` | Cópia editável das cargas, usada para atualizar |
| `painel.py` | Exporta, valida e atualiza as cargas |
| `firebase.rules.json` | Regras recomendadas do banco de status |
| `.nojekyll` | Impede o GitHub de processar os arquivos como blog |

### Cuidado ao publicar mais de um painel na mesma conta

Todos os repositórios de uma conta compartilham o mesmo endereço
(`usuario.github.io`), e o navegador trata isso como **um site só** para efeito
de cache e de armazenamento local. Por isso este painel usa nomes próprios:
cache com prefixo `cargas-gtf-` e chaves `cargas_gtf_*`. Sem isso, um painel
apagaria o cache do outro ao abrir.

Se você publicar outro painel nesta conta, dê a ele um prefixo diferente.

### Sobre o `sw.js`

Ele guarda a versão do painel no aparelho. Por isso tem um número de versão
(`cargas-gtf-v1`): quando ele muda, os celulares baixam a versão nova.
O `painel.py` já sobe esse número sozinho a cada atualização — se você
editar o `index.html` na mão, lembre de subir o número também, senão quem tem o
app instalado pode continuar vendo as cargas antigas.

---

## Uso do painel

- **Buscar**: por número da viagem, transportadora, motorista, placa ou cliente.
- **Filtrar**: pela etapa (na planta, separado, carregado, faturado).
- **Abrir os itens**: toque na carga para ver os pedidos, e no pedido para ver os
  produtos.
- **Marcar status**: entre como admin e toque na etapa. As quatro etapas são
  independentes — uma carga pode estar separada antes do veículo chegar.
