-- Distribuição de multiplicadores por faixa de risco
WITH base AS (
    SELECT
        CASE
            WHEN multiplier < 2.0 THEN 'Baixo'
            WHEN multiplier < 5.0 THEN 'Médio'
            WHEN multiplier < 10.0 THEN 'Alto'
            ELSE 'Extremo'
        END AS faixa_risco,
        multiplier
    FROM public.game_rounds
    WHERE multiplier IS NOT NULL
)
SELECT
    faixa_risco,
    COUNT(*) AS total_rodadas,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS porcentagem
FROM base
GROUP BY faixa_risco
ORDER BY
    CASE faixa_risco
        WHEN 'Baixo' THEN 1
        WHEN 'Médio' THEN 2
        WHEN 'Alto' THEN 3
        WHEN 'Extremo' THEN 4
        ELSE 5
    END;
