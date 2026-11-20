# LEIA-ME — Instruções do projeto Cassino / Loteria Analytics

Estas são as cópias preenchidas dos modelos de `99-Templates/Instruções/`. Os originais ficam inalterados. O projeto pretende analisar resultados da Mega-Sena, Lotofácil e Quina; a especificação e o esqueleto Docker **atualizados para Nginx e Portainer** descrevem o planejamento, não uma aplicação pronta.

## Caminhos

- **Raiz do vault Obsidian:** `C:\Users\fonse\Cérebro_AI`
- **Pasta do projeto relativa ao vault:** `30-Projetos/Cassino`
- **Raiz confirmada do código, do Git e das instruções:** `C:\Users\fonse\Projetos_AI\Cassino`.

## Como usar

1. Use [AGENTS.md](AGENTS.md) como regra compartilhada do projeto. Se a sessão for no Claude Code, consulte também [CLAUDE.md](CLAUDE.md).
2. No vault, leia primeiro [[30-Projetos/Cassino/estado-atual-cassino|Estado atual]] e depois [[30-Projetos/Cassino/cassino|Índice Cassino]]. Consulte a [[30-Projetos/Cassino/Arquitetura/ESPECIFICACAO_LOTERIA_ANALYTICS_HERMES|especificação técnica]] e o [[30-Projetos/Cassino/Arquitetura/ESQUELETO_DOCKER_LOTERIA_ANALYTICS_HERMES|esqueleto Docker]] conforme a tarefa.
3. As instruções canônicas estão na raiz do código. As referências de arquitetura, os prompts e as notas permanecem no vault. Abra a sessão na raiz Git e indique o caminho do vault explicitamente quando necessário.
4. Ao executar a etapa de infraestrutura, aplicar as duas stacks independentes da especificação: Cassino com React/Nginx (`localhost:3000` e `/api` interno ao Fastify) e CloudBeaver (`localhost:8978`); administração Portainer CE (`https://localhost:9443`) fora do ciclo de vida da aplicação. Não expor `3001` ou `5432` nem publicar consoles na internet. O Portainer administra Docker, mas não altera Dockerfiles de origem; evitar configurações divergentes entre CLI e UI.
5. Reutilize `cassino.md`, `estado-atual-cassino.md`, `Arquitetura/` e `Notas/`. Não crie índices ou estados duplicados. Não confunda a pasta de documentação com a raiz do código.

## Acesso e verificação

A leitura e a escrita destes documentos foram feitas diretamente pelo sistema de arquivos. Esse acesso vale para o ambiente em que foram gravados; confirme permissões em outras sessões. O Memory Gateway/Anamnésia é opcional e serve apenas para recuperação. Estes arquivos não instalam nem configuram MCPs, não inicializam Git e não sobem Docker.

Se não puder ler ou gravar no destino autorizado, informe a pendência. Não tente salvar em outra pasta do vault.
