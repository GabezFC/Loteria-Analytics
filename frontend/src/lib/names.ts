import type { Lottery } from '../api/types';

export const LOTTERY_NAMES: Record<Lottery, string> = { megasena: 'Mega-Sena', lotofacil: 'Lotofácil', quina: 'Quina' };

export const STRATEGY_LABELS: Record<string, string> = {
  uniform_random: 'Aleatória uniforme',
  diversity: 'Diversidade (cobertura)',
  frequency_weighted: 'Ponderada por frequência histórica',
  delay_weighted: 'Ponderada por atraso',
};

export const VERDICT_LABELS: Record<string, string> = {
  worse_than_baseline: 'Pior que o baseline',
  indistinguishable: 'Indistinguível do baseline',
  better_not_significant: 'Melhor, mas não significativo',
  better_significant_not_replicated: 'Melhor e significativo, sem replicação',
  better_replicated: 'Melhor e replicado',
};

export const CONCLUSION_LABELS: Record<string, string> = {
  inconclusive: 'Inconclusivo',
  no_evidence_of_advantage: 'Sem evidência de vantagem',
  candidate_advantage_needs_replication: 'Candidato a vantagem — requer replicação',
};

export const METRIC_LABELS: Record<string, string> = {
  log_loss: 'Log-loss (menor é melhor)',
  brier: 'Brier (menor é melhor)',
  mean_hits_per_ticket: 'Acertos médios por bilhete',
  tier_hit_rate: 'Taxa de acerto em faixa premiada',
  return_ratio: 'Retorno histórico nominal ÷ custo',
  hits_distribution: 'Distribuição de acertos',
  net_result_paths: 'Trajetórias do resultado líquido',
  final_net_distribution: 'Distribuição do resultado final',
  jackpot_probability: 'Probabilidade exata do prêmio principal',
};

export const STATUS_LABELS: Record<string, string> = {
  pending: 'Na fila',
  running: 'Em execução',
  succeeded: 'Concluído',
  failed: 'Falhou',
};
