-- ==========================================
-- AUDITORIA DE INTEGRIDADE TEMPORAL E DE DADOS CRUS (GAME_ROUNDS)
-- ==========================================

-- 1. Intervalo (em segundos) entre cada rodada e a anterior
WITH ordenado AS (
  SELECT
    id,
    round_id,
    multiplier,
    created_at,
    LAG(created_at) OVER (ORDER BY created_at) AS created_at_anterior,
    LAG(round_id)   OVER (ORDER BY created_at) AS round_id_anterior
  FROM game_rounds
)
SELECT
  id,
  round_id,
  created_at,
  created_at_anterior,
  EXTRACT(EPOCH FROM (created_at - created_at_anterior)) AS intervalo_segundos
FROM ordenado
ORDER BY created_at;

-- 2. Estatística geral dos intervalos (detecta ritmo do coletor e anomalias)
WITH intervalos AS (
  SELECT
    EXTRACT(EPOCH FROM (created_at - LAG(created_at) OVER (ORDER BY created_at))) AS seg
  FROM game_rounds
)
SELECT
  COUNT(*)                            AS total_intervalos,
  ROUND(AVG(seg)::numeric, 3)        AS media_seg,
  ROUND(STDDEV(seg)::numeric, 3)    AS desvio_padrao_seg,
  MIN(seg)                            AS minimo_seg,
  MAX(seg)                            AS maximo_seg,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY seg) AS mediana_seg,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY seg) AS p95_seg
FROM intervalos
WHERE seg IS NOT NULL;

-- 3. Rodadas "suspeitas": intervalo zero/negativo ou gap grande (> 60s)
WITH ordenado AS (
  SELECT
    id, round_id, created_at,
    LAG(created_at) OVER (ORDER BY created_at) AS anterior
  FROM game_rounds
)
SELECT id, round_id, anterior, created_at,
       EXTRACT(EPOCH FROM (created_at - anterior)) AS intervalo_seg
FROM ordenado
WHERE created_at <= anterior                        -- fora de ordem ou duplicado
   OR EXTRACT(EPOCH FROM (created_at - anterior)) > 60 -- gap > 60s
ORDER BY created_at;

-- 4. Duplicidade de round_id
SELECT round_id, COUNT(*) AS ocorrencias
FROM game_rounds
GROUP BY round_id
HAVING COUNT(*) > 1
ORDER BY ocorrencias DESC;

-- 5. Estatística descritiva geral do multiplicador
SELECT
  COUNT(*)                                    AS total_rodadas,
  ROUND(AVG(multiplier)::numeric, 4)          AS media,
  ROUND(STDDEV(multiplier)::numeric, 4)       AS desvio_padrao,
  MIN(multiplier)                             AS minimo,
  MAX(multiplier)                             AS maximo,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY multiplier)  AS mediana,
  PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY multiplier) AS q1,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY multiplier) AS q3
FROM game_rounds;

-- 6. Outliers pelo método IQR (isolando ruído bruto)
WITH stats AS (
  SELECT
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY multiplier) AS q1,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY multiplier) AS q3
  FROM game_rounds
),
limites AS (
  SELECT q1, q3, (q3 - q1) AS iqr,
         q1 - 1.5 * (q3 - q1) AS limite_inferior,
         q3 + 1.5 * (q3 - q1) AS limite_superior
  FROM stats
)
SELECT g.id, g.round_id, g.multiplier, g.created_at
FROM game_rounds g, limites l
WHERE g.multiplier < l.limite_inferior
   OR g.multiplier > l.limite_superior
ORDER BY g.multiplier DESC;

-- 7. Valores impossíveis ou inválidos
SELECT id, round_id, multiplier, created_at
FROM game_rounds
WHERE multiplier IS NULL
   OR multiplier <= 0        
   OR multiplier < 1.00      
ORDER BY created_at;

-- 8. Histograma simples por faixa de multiplicador
SELECT
  WIDTH_BUCKET(multiplier, 1, 20, 19) AS faixa,
  COUNT(*) AS qtd_rodadas,
  ROUND(AVG(multiplier)::numeric, 2) AS media_na_faixa
FROM game_rounds
GROUP BY faixa
ORDER BY faixa;

-- 9. Repetição consecutiva idêntica (possível bug de gravação)
WITH ordenado AS (
  SELECT id, round_id, multiplier, created_at,
         LAG(multiplier) OVER (ORDER BY created_at) AS multiplier_anterior,
         LAG(round_id)   OVER (ORDER BY created_at) AS round_id_anterior
  FROM game_rounds
)
SELECT *
FROM ordenado
WHERE multiplier = multiplier_anterior
  AND round_id <> round_id_anterior;
