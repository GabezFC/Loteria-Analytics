# API do Cassino (Fastify, via Nginx em `http://localhost:3000/api/*`)

Contrato único consumido pelo dashboard. Tudo em JSON, UTF-8. O navegador **nunca** acessa o PostgreSQL nem a porta 3001.
Quando algo ainda não foi calculado a API responde **404/503 com `{ "error": "..." }`** — nunca dados fabricados.

Convenções: modalidades (`lottery`): `megasena` | `lotofacil` | `quina`. Datas `YYYY-MM-DD`; instantes ISO-8601 UTC.
Números monetários e inteiros grandes vêm como **string** (`"payout_amount":"7534.97"`, `"50063860"`). Parâmetros de consulta desconhecidos → `400`.
Erros: `{ "error": string }`. Rotas `POST` exigem o cabeçalho `X-Requested-With: cassino` e `Content-Type: application/json`.

## Princípio científico (a UI deve refletir)
Probabilidade exata ≠ frequência histórica ≠ score heurístico ≠ resultado de modelo. Sorteios são independentes e uniformes; o histórico
não altera a chance do próximo concurso. Scores **nunca** são exibidos como probabilidade de acerto. Resultados negativos/inconclusivos têm o mesmo destaque.

## Dados oficiais (etapa 03)
- `GET /api/health` → `{status:"ok"|"degraded", database:"up"|"down"}`
- `GET /api/lotteries` → `{items:[{slug,name,pool_size,draw_size,min_bet_size,max_bet_size,simple_price:"6.00",price_source,price_checked_on,draw_count,last_contest,last_draw_date}]}`
- `GET /api/draws?lottery&limit(1-100,=20)&offset&contest&date_from&date_to&numbers=1,2,3` → `{limit,offset,count,total,items:[{id,lottery_slug,contest,draw_date,numbers:[...]}]}` (`numbers`: concursos que contêm TODAS as dezenas listadas)
- `GET /api/draws/:lottery/:contest` → `{id,lottery_slug,contest,draw_date,numbers,prizes:[{hits,winners,payout_amount}],extra:{winner_locations,accumulated_main,total_collected,next_estimate,special_accumulated,observation},source_sha256,ingest_run_id}` | 404
- `GET /api/ingestion/status` → `{lotteries:[{lottery_slug,name,draw_count,first_contest,last_contest,last_draw_date,gap_count,open_divergences,quarantined_rows,prize_tier_rows,collector:{last_attempt_at,last_success_at,last_error,consecutive_failures,next_attempt_at}|null}]}`
- `GET /api/ingestion/runs?limit` → `{items:[{id,lottery_slug,status,started_at,completed_at,row_count,inserted_count,unchanged_count,prize_changed_count,divergent_count,quarantined_count,checkpoint_contest,adapter_version,source_sha256,error_message}]}`
- `GET /api/ingestion/divergences?status=open|accepted|rejected&limit` → `{items:[{id,lottery_slug,contest,status,previous_value:{draw_date,numbers},current_value:{draw_date,numbers},detected_at,resolution_note}]}`
- `GET /api/ingestion/quarantine?limit` → `{items:[{id,lottery_slug,contest,kind:"draw"|"prize",reason,source_line,created_at}]}`
- `GET /api/jobs?kind&status=pending|running|succeeded|failed&limit` → `{items:[{id,kind,lottery_slug,status,attempts,error,params,created_at,started_at,finished_at}]}`
  (kinds: `ingest`, `analyze`, `experiment`, `suggestion`)
- `POST /api/admin/ingestion` body `{lottery?}` → `202 {job_id,status:"pending"}` | `409` (já há coleta pendente) | `429` (máx. 6/min). Coleta manual.

## Probabilidades exatas (etapa 04)
`GET /api/probabilities?lottery=&bet_size=&hits=&tickets=&budget=&contests=1`
- `bet_size` ∈ [`min_bet_size`,`max_bet_size`] (default = mínimo = aposta simples). `hits` filtra uma faixa. `tickets` (m apostas simples distintas) **ou** `budget` (R$ → floor(budget/preço)); só para aposta simples. `contests` (1–10000) = nº de concursos independentes.
- Resposta: `{lottery,bet_size,draw_size,pool_size,total_combinations:"C(N,k)",simple_games,simple_price,bet_cost,price_source,formula_version,`
  `tiers:[{hits,is_prize_tier,exact:{numerator,denominator},probability,one_in,at_least:{numerator,denominator},at_least_probability}],`
  `tickets_jackpot:null|{count,contests,probability,one_in,fraction?:{numerator,denominator},budget?,spent?},assumptions:[string]}`
- `hits` = nº de dezenas sorteadas contidas na aposta. `is_prize_tier` marca faixas premiadas da aposta simples. Exibir `assumptions` e fórmulas.

## Estatísticas (etapa 04) — `window` ∈ `30|100|300|1000|all` (default `all`)
- `GET /api/stats/windows?lottery` → `{items:[{window_label,window_start_contest,window_end_contest,sample_size,completed_at}]}` (janelas disponíveis)
- `GET /api/stats?lottery&window` → `{analysis_run:{id,lottery_slug,method,window_label,window_size,window_start_contest,window_end_contest,sample_size,code_version,seed,completed_at,params},`
  `numbers:[{number,frequency,relative_frequency,expected_frequency,z_score,ci_low,ci_high,current_delay,max_delay,mean_gap}],`
  `distributions:{sum:{mean,median,std,variance,min,max,range,expected_mean,expected_variance,histogram:{edges:[...],counts:[...]}},`
  `parity:{evens_per_draw:{values,observed,expected,gof:{chi2,df,p_value},mean,expected_mean}},low_high:{low_per_draw:{...igual...}},`
  `groups_of_ten:[{range:[a,b],mean_per_draw,expected_mean_per_draw}],volante:{rows,columns,row_mean_per_draw,column_mean_per_draw,expected_row_mean,expected_column_mean},`
  `consecutive:{pairs_per_draw_distribution:{values,observed},mean,expected_mean},spacing:{...},repeated_from_previous:{...igual a parity.evens_per_draw...},`
  `appearance_gaps:{bins,observed,expected_geometric,mean,expected_mean,max,sample_size}},meta:{sample_size,first_contest,last_contest,stats_version,seed,disclaimer,inference_available,combinations_available},disclaimer}`
  `z_score` = desvio da frequência esperada k/N (binomial). `current_delay` = concursos desde a última aparição. 404 se a análise ainda não existe.
- `GET /api/stats/inference?lottery&window` → `{analysis_run,inference:null|{sample_size,chi_square_uniformity:{null_hypothesis,statistic,df,p_value_asymptotic,p_value_monte_carlo,limitation},entropy:{bits,max_bits,normalized,null_mean_bits,p_value_lower_tail},autocorrelation_lag1:{null_hypothesis,tests,significant_q05,expected_false_positives_at_05,max_abs_z,p_value_permutation_max_abs_z,per_number:[{number,z,p_value,q_value}]},sum_ljung_box:{null_hypothesis,lags,acf,statistic,p_value},runs_test_sum:{runs,expected_runs,z,p_value},window_stability:{jsd_bits,p_value_permutation},change_point_sum:{candidate_index,statistic,p_value_permutation,note}},available,disclaimer}`
  (`window_stability`/`change_point_sum`/`runs_test_sum` podem faltar; janelas < 100 concursos não têm inferência). Mostrar a hipótese nula de cada teste; p-values isolados não indicam previsibilidade.
- `GET /api/stats/combinations?lottery&window&size=2|3|4&order=over|under&limit(≤100)` → `{analysis_run,size,order,items:[{combo_size,numbers,observed,expected,lift,z_score,p_value,q_value,sample_size}],meta:{sizes:{"2":{tested,possible,expected_count,significant_q05,expected_false_positives_at_05},...}},note,disclaimer}` (janelas < 300 não têm combinações)

## Modelos, experimentos e simulações (etapa 05)
- `GET /api/models` → `{items:[{name,label,family:"baseline"|"frequency"|"delay"|"ml",description,experimental:boolean,probabilistic:boolean,default:boolean}]}`
- `POST /api/experiments` → `202 {experiment_id,job_id}`
  - backtest: `{kind:"backtest",lottery,models?:string[],test_contests?:50..2000(=500),tickets_per_contest?:1..50(=10),seeds?:1..10(=5),baseline_replicates?:50..2000(=500),refit_every?:10..500(=50),seed?:int}`
  - Monte Carlo: `{kind:"montecarlo",lottery,tickets_per_contest:1..100,contests:1..5000,replicates:10..2000,seed?:int}`
- `GET /api/experiments?lottery&kind&status&limit` → `{items:[{id,kind,lottery_slug,status:"pending"|"running"|"succeeded"|"failed",models:[string],config,created_at,started_at,completed_at,progress:{done,total,stage}|null,verdict_summary:string|null}]}`
- `GET /api/experiments/:id` → `{experiment:{id,kind,lottery_slug,status,config,seed,train_cutoff_contest,test_start_contest,test_end_contest,n_hypotheses,code_version,data_fingerprint,error,progress,created_at,started_at,completed_at},`
  `results:[{model_name,metric_name,value,ci_low,ci_high,baseline_value,baseline_ci_low,baseline_ci_high,p_value,q_value,verdict,payload}],conclusion:{summary,verdict:"inconclusive"|"no_evidence_of_advantage"|"candidate_advantage_needs_replication",limitations:[string]},disclaimer}`
  - Backtest `metric_name` ∈ `log_loss` (menor é melhor; só modelos probabilísticos), `brier`, `mean_hits_per_ticket`, `tier_hit_rate`, `return_ratio` (retorno histórico nominal ÷ custo).
    `baseline_*` = baseline uniforme de mesmo custo (analítico ou replicado com sementes). `verdict` por métrica/modelo ∈ `worse_than_baseline`|`indistinguishable`|`better_not_significant`|`better_significant_not_replicated`|`better_replicated`.
    `payload` (opcional): `{per_seed:[...],halves:{first:{p_value,value},second:{...}},hits_distribution:{values,observed,expected},tickets,contests}`.
  - Monte Carlo: `model_name:"montecarlo"`; `metric_name`: `hits_distribution` (payload `{values,observed_share,expected_share,gof_p_value,tickets_total}`), `net_result_paths` (payload `{checkpoints:[contest_idx],percentiles:{"5":[...],"25":[...],"50":[...],"75":[...],"95":[...]}, cost_curve:[...]}`), `final_net_distribution` (payload `{edges,counts,mean,median,share_positive}`), `jackpot_probability` (value exata do período). Prêmio principal sem ganhador histórico conta 0 (declarado em `limitations`).
- `POST /api/suggestions` body `{lottery,strategy:"uniform_random"|"diversity"|"frequency_weighted"|"delay_weighted",tickets?:1..200,budget?:number,seed?:int}` → `202 {suggestion_set_id,job_id}`
- `GET /api/suggestions?lottery&limit` → `{items:[{id,lottery_slug,strategy,status,ticket_count,budget,created_at}]}`
- `GET /api/suggestions/:id` → `{set:{id,lottery_slug,strategy,seed,status,budget,ticket_count,based_on_contest,created_at,explanation,evidence:null|{experiment_id,model_name,verdict},jackpot_probability:{event,numerator,denominator,probability},total_cost},`
  `tickets:[{position,numbers,heuristic_score,score_interpretation,exact_jackpot_probability:{numerator,denominator},cost}],predictive_advantage_validated:false,illustrative_only:true,disclaimer}`
  `heuristic_score` (0–1) é pontuação descritiva de diversidade/modelo, **sem interpretação probabilística**; a chance real é `exact_jackpot_probability` (igual para todos os bilhetes simples). Nunca apostar de verdade.

## Segurança
`X-Requested-With` obrigatório nos POST; limite de 6 coletas/min; Fastify sem porta publicada; PostgreSQL sem porta host; papéis de banco com privilégio mínimo (`cassino_api` lê dados e insere apenas jobs/experimentos/sugestões).
