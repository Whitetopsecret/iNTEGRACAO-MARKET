-- =========================================================
-- JANELA DE CALMARIA (gatilho de entrada)
-- =========================================================
-- Objetivo:
-- Detectar, em tempo real sobre os dados históricos, quando as
-- últimas rodadas entram em uma fase de estabilidade, sem gaps
-- anômalos e sem variação brusca no ritmo do fluxo.
--
-- Critério usado:
-- 1) intervalo entre rodadas não pode ser um gap anômalo;
-- 2) o intervalo atual deve ficar próximo da mediana da janela;
-- 3) a janela recente precisa ter baixa dispersão (stddev baixo);
-- 4) ao menos 6 das últimas 8 rodadas devem ser estáveis.
-- =========================================================

WITH ordered AS (
    SELECT
        id,
        round_id,
        created_at,
        multiplier,
        EXTRACT(EPOCH FROM (created_at - LAG(created_at) OVER (ORDER BY created_at))) AS intervalo_seg
    FROM public.game_rounds
),
features AS (
    SELECT
        id,
        round_id,
        created_at,
        multiplier,
        intervalo_seg,
        AVG(intervalo_seg) OVER (
            ORDER BY created_at
            ROWS BETWEEN 8 PRECEDING AND CURRENT ROW
        ) AS media_intervalo,
        STDDEV(intervalo_seg) OVER (
            ORDER BY created_at
            ROWS BETWEEN 8 PRECEDING AND CURRENT ROW
        ) AS desvio_intervalo,
        MAX(intervalo_seg) OVER (
            ORDER BY created_at
            ROWS BETWEEN 8 PRECEDING AND CURRENT ROW
        ) AS max_intervalo
    FROM ordered
),
flags AS (
    SELECT
        *,
        CASE
            WHEN intervalo_seg IS NULL THEN FALSE
            WHEN COALESCE(media_intervalo, 0) = 0 THEN FALSE
            WHEN intervalo_seg > GREATEST(90, COALESCE(media_intervalo, 0) * 2) THEN FALSE
            WHEN ABS(intervalo_seg - COALESCE(media_intervalo, intervalo_seg))
                 > GREATEST(3.0, COALESCE(media_intervalo, intervalo_seg) * 0.25) THEN FALSE
            WHEN COALESCE(desvio_intervalo, 0) > GREATEST(5.0, COALESCE(media_intervalo, intervalo_seg) * 0.20) THEN FALSE
            ELSE TRUE
        END AS intervalo_estavel
    FROM features
),
windowed AS (
    SELECT
        *,
        SUM(CASE WHEN intervalo_estavel THEN 1 ELSE 0 END) OVER (
            ORDER BY created_at
            ROWS BETWEEN 8 PRECEDING AND CURRENT ROW
        ) AS qtd_estavel_janela
    FROM flags
)
SELECT
    id,
    round_id,
    created_at,
    multiplier,
    intervalo_seg,
    ROUND(COALESCE(media_intervalo, 0)::numeric, 3) AS media_intervalo,
    ROUND(COALESCE(desvio_intervalo, 0)::numeric, 3) AS desvio_intervalo,
    ROUND(COALESCE(max_intervalo, 0)::numeric, 3) AS max_intervalo,
    intervalo_estavel,
    qtd_estavel_janela,
    CASE
        WHEN intervalo_estavel AND qtd_estavel_janela >= 6 THEN TRUE
        ELSE FALSE
    END AS gatilho_calmaria
FROM windowed
WHERE intervalo_seg IS NOT NULL
ORDER BY created_at DESC
LIMIT 50;
