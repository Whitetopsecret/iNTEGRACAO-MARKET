-- =========================================================
-- GATILHO DE ESPELHO TEMPORAL (24h)
-- =========================================================
-- Objetivo:
-- Projetar o horário da 'vela alta' do dia anterior para o dia
-- atual, compensar esse alvo com base no comportamento recente
-- do fluxo e classificar a entrada em 3 cenários:
--   [A] Espelho Direto Compensado
--   [B] Janela de Tolerância Ampliada
--   [C] Zona de Invalidação (Quebra de Padrão)
--
-- Hipótese usada:
-- A 'vela alta' do dia anterior é o registro com maior
-- multiplicador naquele dia; seu horário local é espelhado
-- para o dia atual.
-- =========================================================

WITH local_rounds AS (
    SELECT
        id,
        round_id,
        created_at,
        (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Manaus') AS created_at_local,
        multiplier
    FROM public.game_rounds
),
latest_day AS (
    SELECT MAX(created_at_local::date) AS data_local
    FROM local_rounds
),
prev_day_ref AS (
    SELECT
        lr.id,
        lr.round_id,
        lr.created_at_local,
        lr.multiplier
    FROM local_rounds lr
    CROSS JOIN latest_day ld
    WHERE lr.created_at_local::date = (ld.data_local - 1)
      AND lr.multiplier = (
          SELECT MAX(lr2.multiplier)
          FROM local_rounds lr2
          WHERE lr2.created_at_local::date = (ld.data_local - 1)
      )
    ORDER BY lr.created_at_local
    LIMIT 1
),
recent_flow AS (
    SELECT
        AVG(intervalo_seg) AS media_intervalo,
        STDDEV(intervalo_seg) AS desvio_intervalo
    FROM (
        SELECT
            EXTRACT(EPOCH FROM (created_at - LAG(created_at) OVER (ORDER BY created_at))) AS intervalo_seg
        FROM public.game_rounds
        ORDER BY created_at DESC
        LIMIT 12
    ) s
    WHERE intervalo_seg IS NOT NULL
),
projected AS (
    SELECT
        ld.data_local,
        pdr.created_at_local AS high_candle_local,
        (ld.data_local::date + pdr.created_at_local::time) AS projected_local_time,
        COALESCE(rf.media_intervalo, 0) AS media_intervalo,
        COALESCE(rf.desvio_intervalo, 0) AS desvio_intervalo,
        ROUND(GREATEST(0, COALESCE(rf.media_intervalo, 0) * 0.5 + COALESCE(rf.desvio_intervalo, 0) * 0.8)::numeric, 2) AS compensation_seconds
    FROM latest_day ld
    CROSS JOIN prev_day_ref pdr
    CROSS JOIN recent_flow rf
),
reference AS (
    SELECT
        p.data_local,
        p.high_candle_local,
        p.projected_local_time,
        p.media_intervalo,
        p.desvio_intervalo,
        p.compensation_seconds,
        (SELECT MAX(created_at_local) FROM local_rounds) AS latest_local_ts,
        EXTRACT(EPOCH FROM ((SELECT MAX(created_at_local) FROM local_rounds) - p.projected_local_time)) AS delta_seconds
    FROM projected p
)
SELECT
    data_local,
    high_candle_local,
    projected_local_time,
    ROUND(media_intervalo::numeric, 3) AS media_intervalo,
    ROUND(desvio_intervalo::numeric, 3) AS desvio_intervalo,
    compensation_seconds,
    latest_local_ts,
    ROUND(delta_seconds::numeric, 3) AS delta_seconds,
    CASE
        WHEN ABS(delta_seconds) <= compensation_seconds THEN '[A] Espelho Direto Compensado'
        WHEN ABS(delta_seconds) <= GREATEST(compensation_seconds + 600, 1800) THEN '[B] Janela de Tolerância Ampliada'
        ELSE '[C] Zona de Invalidação (Quebra de Padrão)'
    END AS scenario,
    CASE
        WHEN ABS(delta_seconds) <= compensation_seconds THEN 'Entrada alinhada ao espelho compensado'
        WHEN ABS(delta_seconds) <= GREATEST(compensation_seconds + 600, 1800) THEN 'Entrada tolerada, mas fora do espelho direto'
        ELSE 'Padrão quebrado; invalidar sinal'
    END AS interpretacao
FROM reference;
