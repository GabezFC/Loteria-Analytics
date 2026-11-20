# CLAUDE.md — Cassino / Loteria Analytics

> Complemento para Claude Code. `AGENTS.md` contém as regras compartilhadas e deve ser lido antes de atuar.

## 1. Identificação e caminhos

- **Projeto:** Cassino — Loteria Analytics.
- **Objetivo:** aplicar análise estatística, probabilidades exatas, simulações e backtests a resultados oficiais da Mega-Sena, Lotofácil e Quina. Sem apostas reais nem promessa de previsão.
- **Raiz Git e de código confirmada:** `C:\Users\fonse\Projetos_AI\Cassino`.
- **Vault Obsidian:** `C:\Users\fonse\Cérebro_AI`.
- **Pasta exclusiva no vault:** `30-Projetos/Cassino`.
- **Regras compartilhadas:** `AGENTS.md` nesta raiz de código, ao lado de `CLAUDE.md` e `LEIA-ME.md`. Não abrir ou copiar arquivos `.env` reais.
- **Leitura:** sistema de arquivos; MCP Obsidian ou Anamnésia/Memory Gateway apenas para recuperação, se disponíveis com escopo confirmado.
- **Escrita:** sistema de arquivos, restrita à documentação pertinente e autorizada na pasta exclusiva. Não contorne limitações de acesso do ambiente nem use o gateway para escrever.
- **Documentação técnica:** [[30-Projetos/Cassino/Arquitetura/ESPECIFICACAO_LOTERIA_ANALYTICS_HERMES|Especificação técnica]] e [[30-Projetos/Cassino/Arquitetura/ESQUELETO_DOCKER_LOTERIA_ANALYTICS_HERMES|Esqueleto Docker]].

## 2. Instruções operacionais

1. Leia `AGENTS.md`, depois `estado-atual-cassino.md` e `cassino.md` na pasta exclusiva. Se precisar ampliar a busca, comece com até três notas pertinentes. Não varra o vault.
2. Identifique os arquivos, o escopo e os testes da tarefa. Confirme o estado real no código e no ambiente; documentos de planejamento não demonstram execução.
3. Delegue partes independentes só quando houver economia de tempo/contexto, com um responsável por arquivo e sem duplicar testes.
4. Registre decisões e descobertas duráveis nas notas existentes ou em `Notas/`, sem duplicar conteúdo de `Arquitetura/`. Use `cassino.md` como índice; não crie `indice.md` ou `estado-atual.md` paralelos.
5. Quando o estado mudar, atualize `estado-atual-cassino.md` com evidência, pendências e próximo passo. Confirme a gravação; se não houver acesso, informe a pendência. Não grave segredos, `.env` ou logs brutos.
6. Informe alterações, testes realmente executados e itens ainda apenas especificados.

## 3. Limites

- **Código:** escrever apenas na raiz de código confirmada e no escopo solicitado. O vault guarda documentação e memória, não código da aplicação.
- **Operação:** não realizar apostas ou transações, acessar contas de loteria, alterar bancos de outros projetos, remover volumes, fazer push, publicar serviços ou usar APIs pagas sem autorização específica onde aplicável. Apostas e transações estão fora do escopo do produto.
- **Infraestrutura aprovada (planejada):** Nginx no frontend React encaminha `/api` ao Fastify interno (`backend:3001`) e publica apenas `127.0.0.1:3000`; PostgreSQL e workers sem portas publicadas. CloudBeaver `127.0.0.1:8978` e Portainer CE HTTPS `127.0.0.1:9443` autenticados, este último em Compose separado com volume próprio e Docker socket privilegiado. Não criar Nginx extra nem usar Portainer como editor Dockerfile; arquivos Compose versionados são fonte da verdade.
- **Validação:** identifique os comandos de teste no repositório real. Quando existirem Compose executáveis, valide as configurações **da aplicação e do Portainer separadamente** com `docker compose config --quiet` e confira a saúde com `docker compose ps` depois de subir os serviços localmente. Não exponha segredos e não declare execução de serviços a partir do esqueleto Markdown.
- **Revisão científica:** chance matemática, frequência histórica e score de modelo são medidas distintas. Compare experimentos cronológicos com baseline uniforme de mesmo custo e não rotule score como probabilidade.

Em caso de divergência com `AGENTS.md`, aplique o limite mais restritivo e resolva a inconsistência antes de gravar. Mantenha os dois arquivos coerentes, sem duplicar regras longas.
