# Formato CAIXA observado

Fonte: `https://servicebus3.caixa.gov.br/portaldeloterias/api/resultados/download?modalidade=...`, conforme `https://loterias.caixa.gov.br/Style%20Library/json/params.txt` e o componente oficial de download. Três downloads HTTP 200, XLSX com primeira planilha e uma linha de cabeçalho. Em 19/11/2026, 3088 Mega-Sena, 3834 Lotofácil, 7172 Quina; contagens ainda não são concursos importados.

- Mega-Sena: `Concurso`, `Data do Sorteio`, `Bola1` a `Bola6`, `Ganhadores 6 acertos`, `Cidade / UF`, `Rateio 6 acertos`, depois pares `Ganhadores N acertos` / `Rateio N acertos` para 5 e 4.
- Lotofácil: `Concurso`, `Data Sorteio`, `Bola1` a `Bola15`, `Ganhadores 15 acertos`, `Cidade / UF`, `Rateio 15 acertos`, depois pares para 14, 13, 12, 11.
- Quina: `Concurso`, `Data Sorteio`, `Bola1` a `Bola5`, `Ganhadores 5 acertos`, `Cidade / UF`, `Rateio 5 acertos`, depois pares para 4, 3, 2.

O XLSX real da Mega-Sena declara dimensão `A1:T1`, mas o XML contém 3089 linhas. Em `openpyxl` com `read_only=True`, chame `reset_dimensions()` antes de iterar; a data vem como texto `DD/MM/AAAA` (por exemplo, `11/03/1996`). O adaptador precisa aceitar também o cabeçalho `Data Sorteio`, sem a palavra `do`.

Observação: nomes de outras colunas e capitalização variam por modalidade. Não interpretar célula vazia como zero sem evidência. Os endpoints públicos não oferecem contrato documentado de estabilidade; downloads conservadores, sem autenticação ou contorno de bloqueios.
